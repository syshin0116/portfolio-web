"""Unit tests for the agent module."""

import ast
import asyncio
import hashlib
import inspect
import json
from dataclasses import asdict
from threading import Event, Lock
from types import SimpleNamespace
from uuid import UUID

import deepagents.profiles.harness.harness_profiles as harness_profiles
import pytest
from aegra_api.core import database as aegra_database
from aegra_api.services import graph_factory
from aegra_api.services.graph_factory import build_server_runtime
from aegra_api.services.langgraph_service import (
    LangGraphService,
    create_run_config,
)
from deepagents import FilesystemPermission
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
    StoreBackend,
)
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.profiles.harness.harness_profiles import (
    _harness_profile_for_model,
)
from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime, ServerInfo
from langgraph.store.memory import InMemoryStore
from pydantic import Field

import agent.graph as graph_module
from agent.capabilities.budget import (
    CapabilityDeniedError,
    InvalidDelegationError,
    RunBudget,
    RunBudgetMiddleware,
)
from agent.capabilities.quickjs import (
    QUICKJS_RESULT_SCHEMA,
    QUICKJS_SYSTEM_PROMPT,
    QUICKJS_TOOL_NAME,
    BoundedQuickJSMiddleware,
)
from agent.capabilities.subagents import (
    BOUNDED_TASK_TOOL_DESCRIPTION,
    SUBAGENT_NAMES,
    SUBAGENT_ROOT_PROMPT,
)
from agent.capabilities.token_counting import (
    OPENAI_API_BASE_URL,
    OPENAI_GUEST_MODEL_SPEC,
    OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    OPENAI_ROUTING_ENVIRONMENT_VARIABLES,
    InputTokenCountError,
    _require_exact_openai_guest_model,
    openai_guest_safety_identifier,
    prepare_openai_input_token_count,
)
from agent.graph import (
    DEFAULT_MODEL,
    GUEST_MODEL_MAX_OUTPUT_TOKENS,
    GUEST_ROOT_TOOL_NAMES,
    GUEST_RUN_BUDGET_POLICY,
    MODEL_MAX_OUTPUT_TOKENS,
    MODEL_TIMEOUT_SECONDS,
    NO_GENERAL_PURPOSE_SUBAGENT,
    OWNER_OPENAI_SAFETY_IDENTIFIER,
    _bounded_guest_model,
    _bounded_model,
    _build_backend,
    _disable_general_purpose_subagent,
    _filesystem_permissions,
    _memory_namespace,
    _normalized_guest_model_spec,
    _normalized_model_spec,
    _runtime_is_guest,
    create_graph,
    graph,
)
from agent.guest_budget import (
    GUEST_MIN_RUN_RESERVATION_MICRO_USD,
    minimum_guest_run_reservation_micro_usd,
)
from agent.inspection import InspectionEventTransformer
from agent.run_liveness import GuestExecutionFenceUnavailableError
from agent.tools import TOOLS, keyword_search


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """Deterministic model that records each bound tool surface."""

    model_name: str = "gpt-5.6-luna"
    bound_tool_names: list[frozenset[str]] = Field(default_factory=list)

    def _get_ls_params(self, stop=None, **kwargs):
        del stop, kwargs
        return {
            "ls_model_type": "chat",
            "ls_model_name": self.model_name,
            "ls_provider": "openai",
        }

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        self.bound_tool_names.append(
            frozenset(
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in tools
            )
        )
        return self


class AnthropicToolCapableFakeModel(ToolCapableFakeModel):
    """Deterministic injected model with an Anthropic provider identity."""

    model_name: str = "claude-sonnet-4-6"

    def _get_ls_params(self, stop=None, **kwargs):
        del stop, kwargs
        return {
            "ls_model_type": "chat",
            "ls_model_name": self.model_name,
            "ls_provider": "anthropic",
        }


class PayloadRecordingFakeModel(ToolCapableFakeModel):
    """Record the exact messages delivered after every middleware wrapper."""

    invoked_messages: list[list] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.invoked_messages.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class YieldingInMemoryStore(InMemoryStore):
    """Force concurrent create attempts to overlap at the read boundary."""

    async def aget(self, namespace, key, *, refresh_ttl=None):
        item = await super().aget(namespace, key, refresh_ttl=refresh_ttl)
        await asyncio.sleep(0)
        return item


class ObservedThreadLock:
    """Delegate to one real lock while exposing deterministic acquire attempts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._attempt_guard = Lock()
        self._attempts = 0
        self.second_attempted = Event()

    def acquire(self) -> bool:
        with self._attempt_guard:
            self._attempts += 1
            if self._attempts == 2:
                self.second_attempted.set()
        return self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        self.release()


class SyncHoldingInMemoryStore(InMemoryStore):
    """Hold the first synchronous read while an async create tries to enter."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self.async_read_entered = Event()
        self._hold_first_sync_read = True

    def get(self, namespace, key, *, refresh_ttl=None):
        if self._hold_first_sync_read:
            self._hold_first_sync_read = False
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError("synchronous memory create was not released")
        return super().get(namespace, key, refresh_ttl=refresh_ttl)

    async def aget(self, namespace, key, *, refresh_ttl=None):
        self.async_read_entered.set()
        return await super().aget(namespace, key, refresh_ttl=refresh_ttl)


class AsyncHoldingInMemoryStore(InMemoryStore):
    """Hold the first asynchronous read while another create tries to enter."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.sync_read_entered = Event()
        self._hold_first_async_read = True

    def get(self, namespace, key, *, refresh_ttl=None):
        self.sync_read_entered.set()
        return super().get(namespace, key, refresh_ttl=refresh_ttl)

    async def aget(self, namespace, key, *, refresh_ttl=None):
        if self._hold_first_async_read:
            self._hold_first_async_read = False
            self.entered.set()
            await self.release.wait()
        return await super().aget(namespace, key, refresh_ttl=refresh_ttl)


def _compiled_tool_names(compiled_graph: CompiledStateGraph) -> set[str]:
    return set(compiled_graph.nodes["tools"].bound._tools_by_name)


def _user(permissions: list[str], *, identity: str = "runtime-user"):
    return SimpleNamespace(
        identity=identity,
        display_name=identity,
        is_authenticated=True,
        permissions=permissions,
    )


def _server_runtime(
    permissions: list[str],
    *,
    identity: str = "runtime-user",
):
    return build_server_runtime(
        access_context="threads.create_run",
        store=InMemoryStore(),
        user=_user(permissions, identity=identity),
        context=None,
    )


def _guest_runtime():
    return _server_runtime(
        ["anon"],
        identity=f"anon:{UUID(int=1, version=4)}",
    )


def _quickjs_runtime(thread_id: str) -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"thread_id": thread_id}},
        stream_writer=lambda _event: None,
        tool_call_id=f"{thread_id}-eval",
        store=None,
    )


async def _execute_quickjs(
    middleware: BoundedQuickJSMiddleware,
    *,
    thread_id: str,
) -> None:
    tool = middleware.tools[0]
    assert tool.coroutine is not None
    await tool.coroutine(_quickjs_runtime(thread_id), "21 * 2")


def _quickjs_worker_thread(middleware: BoundedQuickJSMiddleware):
    slots = list(middleware._registry._slots.values())
    assert len(slots) == 1
    worker_thread = slots[0].worker._thread
    assert worker_thread is not None
    assert worker_thread.is_alive()
    return worker_thread


def _final_message(content: str, *, total_tokens: int = 10) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": total_tokens - 1,
            "output_tokens": 1,
            "total_tokens": total_tokens,
        },
    )


def _openai_final_message(content: str) -> AIMessage:
    return AIMessage(
        content=content,
        response_metadata={
            "model_provider": "openai",
            "model_name": "gpt-5.6-luna",
            "status": "completed",
        },
        usage_metadata={
            "input_tokens": 1,
            "output_tokens": 9,
            "total_tokens": 10,
            "input_token_details": {
                "cache_creation": 0,
                "cache_read": 0,
            },
            "output_token_details": {"reasoning": 0},
        },
    )


def _openai_tool_message(name: str, args: dict, tool_call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
        response_metadata={
            "model_provider": "openai",
            "model_name": "gpt-5.6-luna",
            "status": "completed",
        },
        usage_metadata={
            "input_tokens": 1,
            "output_tokens": 9,
            "total_tokens": 10,
            "input_token_details": {
                "cache_creation": 0,
                "cache_read": 0,
            },
            "output_token_details": {"reasoning": 0},
        },
    )


async def _exact_anthropic_test_input_tokens(_request) -> int:
    return 1


async def _exact_openai_test_input_tokens(_request) -> int:
    return 1


def test_guest_accounting_floor_tracks_the_runtime_policy():
    assert (
        minimum_guest_run_reservation_micro_usd(
            max_model_calls=GUEST_RUN_BUDGET_POLICY.max_model_calls,
            max_output_tokens=GUEST_RUN_BUDGET_POLICY.max_output_tokens,
            max_total_tokens=GUEST_RUN_BUDGET_POLICY.max_total_tokens,
            max_count_risk_tokens=(
                GUEST_RUN_BUDGET_POLICY.max_count_risk_tokens_per_run
            ),
        )
        == GUEST_MIN_RUN_RESERVATION_MICRO_USD
    )


def test_guest_budget_leaves_capacity_for_the_final_answer_after_retrieval():
    budget = RunBudget(GUEST_RUN_BUDGET_POLICY)

    first = budget.reserve_model(input_tokens=1_113)
    budget.settle_model(first, actual_tokens=1_190)
    second = budget.reserve_model(input_tokens=3_196)
    budget.settle_model(second, actual_tokens=3_300)
    final = budget.reserve_model(input_tokens=10_998)

    assert final.reserved_tokens == 11_766
    assert budget.snapshot().charged_tokens == 16_256


def test_guest_budget_admits_the_observed_subagent_synthesis_payload():
    budget = RunBudget(GUEST_RUN_BUDGET_POLICY)
    observed_attempts = (
        (11_563, 1_657),
        (7_628, 981),
        (9_950, 1_403),
        (24_774, 5_547),
        (57_603, 11_215),
        (15_306, 2_525),
    )

    for upper_bound, input_tokens in observed_attempts:
        attempt = budget.reserve_model_attempt(input_upper_bound=upper_bound)
        counted = budget.reserve_model_input(attempt, input_tokens=input_tokens)
        budget.settle_model(counted, actual_tokens=input_tokens + 300)

    snapshot = budget.snapshot()
    assert snapshot.model_calls == 6
    assert snapshot.charged_tokens == 25_128
    assert snapshot.count_risk_tokens == 23_328
    assert GUEST_RUN_BUDGET_POLICY.max_tool_calls == 24


def test_guest_budget_admits_eight_calls_just_below_the_generation_ceiling():
    budget = RunBudget(GUEST_RUN_BUDGET_POLICY)

    for _call in range(8):
        reservation = budget.reserve_model(input_tokens=7_231)
        budget.settle_model(reservation, actual_tokens=7_999)

    snapshot = budget.snapshot()
    assert snapshot.model_calls == 8
    assert snapshot.charged_tokens == 63_992
    assert GUEST_RUN_BUDGET_POLICY.max_output_tokens == 768
    assert GUEST_RUN_BUDGET_POLICY.max_total_tokens == 64_000


@pytest.fixture(autouse=True)
def _replace_provider_token_count(monkeypatch):
    monkeypatch.setattr(
        "agent.graph.count_anthropic_input_tokens",
        _exact_anthropic_test_input_tokens,
    )
    monkeypatch.setattr(
        "agent.graph.count_openai_input_tokens",
        _exact_openai_test_input_tokens,
    )
    monkeypatch.setattr(
        "agent.graph._OWNER_OPENAI_INPUT_TOKEN_COUNTER",
        _exact_openai_test_input_tokens,
    )
    monkeypatch.setattr(
        "agent.graph._owner_openai_input_token_counter",
        lambda _model_spec: _exact_openai_test_input_tokens,
    )


def test_graph_entrypoint_is_aegra_runtime_config_factory():
    graph_id = "unit-runtime-config-factory"
    graph_factory.clear_factory_registry(graph_id)
    try:
        graph_factory.classify_factory(graph, graph_id)

        assert graph_factory.is_factory(graph_id)
        assert tuple(inspect.signature(graph).parameters) == ("config", "runtime")
        assert inspect.isasyncgenfunction(graph.__wrapped__)
    finally:
        graph_factory.clear_factory_registry(graph_id)


async def test_aegra_injects_request_scoped_persistence_into_factory_graph(
    monkeypatch,
):
    checkpointer = InMemorySaver()
    store = InMemoryStore()
    fake_model = ToolCapableFakeModel(responses=[_final_message("done")])
    monkeypatch.setattr(
        aegra_database.db_manager,
        "get_checkpointer",
        lambda: checkpointer,
    )
    monkeypatch.setattr(aegra_database.db_manager, "get_store", lambda: store)
    monkeypatch.setattr("agent.graph._bounded_model", lambda _spec: fake_model)

    graph_id = "unit-agent-factory"
    service = LangGraphService()
    service._graph_registry = {
        graph_id: {
            "file_path": "./agent/src/agent/graph.py",
            "export_name": "graph",
        }
    }
    service._graph_factories[graph_id] = graph
    graph_factory.clear_factory_registry(graph_id)
    graph_factory.classify_factory(graph, graph_id)
    try:
        async with service.get_graph(
            graph_id,
            config={"configurable": {"thread_id": "factory-thread"}},
            user=_user(["admin"]),
        ) as request_graph:
            assert isinstance(request_graph, CompiledStateGraph)
            assert request_graph.checkpointer is checkpointer
            assert request_graph.store is store
            assert request_graph.stream_transformers[-1] is InspectionEventTransformer
    finally:
        graph_factory.clear_factory_registry(graph_id)


async def test_graph_factory_creates_a_fresh_budget_for_every_run(monkeypatch):
    created_budgets = []
    model = ToolCapableFakeModel(
        responses=[
            _openai_final_message("first run"),
            _openai_final_message("second run"),
        ]
    )

    def create_budget(policy=None):
        budget = RunBudget() if policy is None else RunBudget(policy)
        created_budgets.append(budget)
        return budget

    monkeypatch.setattr("agent.graph.RunBudget", create_budget)
    monkeypatch.setattr("agent.graph._bounded_model", lambda _spec: model)
    runtime = _server_runtime([])

    for run_id, expected in (
        ("fresh-budget-first", "first run"),
        ("fresh-budget-second", "second run"),
    ):
        config = {"configurable": {"thread_id": run_id}}
        async with graph(config, runtime) as request_graph:
            result = await request_graph.ainvoke(
                {"messages": [{"role": "user", "content": run_id}]},
                config,
            )
        assert result["messages"][-1].content == expected

    assert len(created_budgets) == 2
    assert created_budgets[0] is not created_budgets[1]
    assert [budget.snapshot().model_calls for budget in created_budgets] == [1, 1]
    assert [budget.snapshot().charged_tokens for budget in created_budgets] == [10, 10]


async def test_graph_factory_selects_the_guest_policy_before_compilation(monkeypatch):
    captured = []
    fence_calls = []
    lifecycle = []

    def capture_graph(**kwargs):
        lifecycle.append("compile")
        captured.append(kwargs)
        return object()

    class FakeFence:
        monitor_starts = 0

        def start_owner_monitor(self):
            lifecycle.append("monitor")
            self.monitor_starts += 1

        async def aclose(self):
            raise AssertionError("successful owner monitor must own cleanup")

    fence = FakeFence()

    async def acquire_fence(**kwargs):
        lifecycle.append("acquire")
        fence_calls.append(kwargs)
        return fence

    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr("agent.graph.create_graph", capture_graph)
    monkeypatch.setattr(
        "agent.graph.acquire_guest_execution_fence",
        acquire_fence,
    )

    async with graph(
        {
            "configurable": {
                "run_id": "guest-policy-run",
                "thread_id": "guest-policy-factory",
            }
        },
        _guest_runtime(),
    ) as request_graph:
        assert request_graph is not None

    assert fence_calls == [
        {
            "run_id": "guest-policy-run",
            "thread_id": "guest-policy-factory",
            "identity": f"anon:{UUID(int=1, version=4)}",
        }
    ]
    assert fence.monitor_starts == 1
    assert lifecycle == ["acquire", "monitor", "compile"]
    assert len(captured) == 1
    assert captured[0]["budget"].policy == GUEST_RUN_BUDGET_POLICY
    assert captured[0]["quickjs_middleware"].enabled is False


async def test_guest_monitor_start_failure_closes_fence_before_compilation(
    monkeypatch,
):
    lifecycle = []

    class FakeFence:
        def start_owner_monitor(self):
            lifecycle.append("monitor")
            raise RuntimeError("monitor could not start")

        async def aclose(self):
            lifecycle.append("close")

    async def acquire_fence(**_kwargs):
        lifecycle.append("acquire")
        return FakeFence()

    def reject_compilation(**_kwargs):
        lifecycle.append("compile")
        raise AssertionError("monitor failure must precede graph compilation")

    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr("agent.graph.create_graph", reject_compilation)
    monkeypatch.setattr(
        "agent.graph.acquire_guest_execution_fence",
        acquire_fence,
    )

    with pytest.raises(RuntimeError, match="monitor could not start"):
        async with graph(
            {
                "configurable": {
                    "run_id": "monitor-start-failure-run",
                    "thread_id": "monitor-start-failure-thread",
                }
            },
            _guest_runtime(),
        ):
            pass

    assert lifecycle == ["acquire", "monitor", "close"]


async def test_guest_execution_without_server_run_id_fails_before_graph_compilation(
    monkeypatch,
):
    compiled = False

    def capture_graph(**_kwargs):
        nonlocal compiled
        compiled = True
        return object()

    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr("agent.graph.create_graph", capture_graph)

    with pytest.raises(RuntimeError, match="run, thread, and user identity"):
        async with graph(
            {"configurable": {"thread_id": "missing-run-id"}},
            _guest_runtime(),
        ):
            pass

    assert compiled is False


async def test_guest_fence_contention_fails_before_graph_compilation(monkeypatch):
    compiled = False

    def capture_graph(**_kwargs):
        nonlocal compiled
        compiled = True
        return object()

    async def reject_fence(**_kwargs):
        raise GuestExecutionFenceUnavailableError(
            "guest execution liveness fence is already held"
        )

    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr("agent.graph.create_graph", capture_graph)
    monkeypatch.setattr(
        "agent.graph.acquire_guest_execution_fence",
        reject_fence,
    )

    with pytest.raises(GuestExecutionFenceUnavailableError, match="already held"):
        async with graph(
            {
                "configurable": {
                    "run_id": "contended-run",
                    "thread_id": "contended-thread",
                }
            },
            _guest_runtime(),
        ):
            pass

    assert compiled is False


async def test_aegra_factory_creates_a_fresh_quickjs_tool_session_per_access(
    monkeypatch,
):
    model = ToolCapableFakeModel(
        responses=[
            _openai_final_message("first access"),
            _openai_final_message("second access"),
        ]
    )
    monkeypatch.setenv("QUICKJS_ENABLED", "true")
    monkeypatch.setattr("agent.graph._bounded_model", lambda _spec: model)
    runtime = _server_runtime(["admin"])
    coroutine_ids = []

    for thread_id in ("quickjs-factory-first", "quickjs-factory-second"):
        config = {"configurable": {"thread_id": thread_id}}
        async with graph(config, runtime) as request_graph:
            eval_tool = request_graph.nodes["tools"].bound._tools_by_name[
                QUICKJS_TOOL_NAME
            ]
            coroutine_ids.append(id(eval_tool.coroutine))
            result = await request_graph.ainvoke(
                {"messages": [{"role": "user", "content": thread_id}]},
                config,
            )
        assert result["messages"][-1].content.endswith("access")
        assert QUICKJS_TOOL_NAME in model.bound_tool_names[-1]

    assert len(set(coroutine_ids)) == 2


async def test_graph_factory_explicitly_closes_quickjs_after_normal_exit(
    monkeypatch,
):
    captured = []

    def capture_graph(**kwargs):
        captured.append(kwargs["quickjs_middleware"])
        return object()

    monkeypatch.setenv("QUICKJS_ENABLED", "true")
    monkeypatch.setattr("agent.graph.create_graph", capture_graph)

    async with graph(
        {"configurable": {"thread_id": "quickjs-normal-close"}},
        _server_runtime(["admin"]),
    ):
        middleware = captured[0]
        await _execute_quickjs(
            middleware,
            thread_id="quickjs-normal-close",
        )
        worker_thread = _quickjs_worker_thread(middleware)

    assert middleware._registry._slots == {}
    assert not worker_thread.is_alive()


async def test_graph_factory_cleanup_does_not_mask_the_active_exception(
    monkeypatch,
):
    captured = []

    def capture_graph(**kwargs):
        captured.append(kwargs["quickjs_middleware"])
        return object()

    class GraphError(RuntimeError):
        pass

    class CleanupError(RuntimeError):
        pass

    original_aclose = BoundedQuickJSMiddleware.aclose

    async def close_then_fail(self):
        await original_aclose(self)
        raise CleanupError("cleanup sentinel")

    monkeypatch.setenv("QUICKJS_ENABLED", "true")
    monkeypatch.setattr("agent.graph.create_graph", capture_graph)
    monkeypatch.setattr(BoundedQuickJSMiddleware, "aclose", close_then_fail)
    graph_error = GraphError("graph sentinel")

    with pytest.raises(GraphError) as raised:
        async with graph(
            {"configurable": {"thread_id": "quickjs-error-close"}},
            _server_runtime(["admin"]),
        ):
            middleware = captured[0]
            await _execute_quickjs(
                middleware,
                thread_id="quickjs-error-close",
            )
            worker_thread = _quickjs_worker_thread(middleware)
            raise graph_error

    assert raised.value is graph_error
    assert middleware._registry._slots == {}
    assert not worker_thread.is_alive()


async def test_graph_factory_cancellation_waits_for_quickjs_worker_shutdown(
    monkeypatch,
):
    captured = []
    entered = asyncio.Event()
    hold = asyncio.Event()
    worker_threads = []

    def capture_graph(**kwargs):
        captured.append(kwargs["quickjs_middleware"])
        return object()

    monkeypatch.setenv("QUICKJS_ENABLED", "true")
    monkeypatch.setattr("agent.graph.create_graph", capture_graph)

    async def run_graph():
        async with graph(
            {"configurable": {"thread_id": "quickjs-cancel-close"}},
            _server_runtime(["admin"]),
        ):
            middleware = captured[0]
            await _execute_quickjs(
                middleware,
                thread_id="quickjs-cancel-close",
            )
            worker_threads.append(_quickjs_worker_thread(middleware))
            entered.set()
            await hold.wait()

    running = asyncio.create_task(run_graph())
    await entered.wait()
    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running

    middleware = captured[0]
    assert middleware._registry._slots == {}
    assert len(worker_threads) == 1
    assert not worker_threads[0].is_alive()


def test_graph_module_never_constructs_its_own_persistence():
    source = inspect.getsource(__import__("agent.graph", fromlist=["graph"]))
    constructed_names = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            constructed_names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            constructed_names.add(node.func.attr)

    assert "AsyncPostgresSaver" not in constructed_names
    assert "AsyncPostgresStore" not in constructed_names
    assert "checkpointer=" not in source


def test_prebuilt_production_model_resolves_fail_closed_harness_profile(monkeypatch):
    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-profile-resolution-key")
    _bounded_model.cache_clear()
    _disable_general_purpose_subagent.cache_clear()
    try:
        _disable_general_purpose_subagent(DEFAULT_MODEL)
        model = _bounded_model(DEFAULT_MODEL)
        profile = _harness_profile_for_model(model, None)
    finally:
        _bounded_model.cache_clear()
        _disable_general_purpose_subagent.cache_clear()

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-5.6-luna"
    assert profile.general_purpose_subagent.enabled is False
    assert "SummarizationMiddleware" in profile.excluded_middleware
    assert profile.excluded_tools == frozenset({"delete"})
    assert profile.tool_description_overrides == {"task": BOUNDED_TASK_TOOL_DESCRIPTION}


def test_repeated_injected_anthropic_graph_creation_registers_provider_profile_once(
    monkeypatch,
):
    calls = []
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.setattr(
        "agent.graph.register_harness_profile",
        lambda model, profile: calls.append((model, profile)),
    )
    _disable_general_purpose_subagent.cache_clear()
    try:
        for thread_id in ("profile-once-first", "profile-once-second"):
            create_graph(
                runtime=_server_runtime([]),
                config={"configurable": {"thread_id": thread_id}},
                model=AnthropicToolCapableFakeModel(responses=[_final_message("done")]),
            )
    finally:
        _disable_general_purpose_subagent.cache_clear()

    assert calls == [
        (DEFAULT_MODEL, NO_GENERAL_PURPOSE_SUBAGENT),
        ("anthropic", NO_GENERAL_PURPOSE_SUBAGENT),
    ]


def test_fresh_injected_openai_identity_resolves_exact_fail_closed_profile(
    monkeypatch,
):
    monkeypatch.setattr(harness_profiles, "_HARNESS_PROFILES", {})
    model = ToolCapableFakeModel(responses=[_final_message("unused")])
    _disable_general_purpose_subagent.cache_clear()
    try:
        compiled = create_graph(
            runtime=_server_runtime(["eval"]),
            config={"configurable": {"thread_id": "fresh-openai-profile-resolution"}},
            model=model,
            input_token_counter=_exact_anthropic_test_input_tokens,
            dynamic_subagents_enabled=True,
            quickjs_enabled=False,
            root_tool_allowlist=frozenset({"task"}),
            experiment_subagent_allowlist=frozenset({"evidence-checker"}),
        )
        profile = _harness_profile_for_model(model, None)
    finally:
        _disable_general_purpose_subagent.cache_clear()

    task_tool = compiled.nodes["tools"].bound._tools_by_name["task"]
    assert profile.general_purpose_subagent.enabled is False
    assert "SummarizationMiddleware" in profile.excluded_middleware
    assert "- evidence-checker:" in task_tool.description
    assert "- general-purpose:" not in task_tool.description


def test_injected_anthropic_eval_resolves_fail_closed_profile_without_general_purpose():
    model = AnthropicToolCapableFakeModel(responses=[_final_message("unused")])
    _disable_general_purpose_subagent.cache_clear()
    try:
        compiled = create_graph(
            runtime=_server_runtime(["eval"]),
            config={"configurable": {"thread_id": "anthropic-profile-resolution"}},
            model=model,
            input_token_counter=_exact_anthropic_test_input_tokens,
            dynamic_subagents_enabled=True,
            quickjs_enabled=False,
            root_tool_allowlist=frozenset({"task"}),
            experiment_subagent_allowlist=frozenset({"evidence-checker"}),
        )
        profile = _harness_profile_for_model(model, None)
    finally:
        _disable_general_purpose_subagent.cache_clear()

    task_tool = compiled.nodes["tools"].bound._tools_by_name["task"]
    assert profile.general_purpose_subagent.enabled is False
    assert "SummarizationMiddleware" in profile.excluded_middleware
    assert profile.excluded_tools == frozenset({"delete"})
    assert "- evidence-checker:" in task_tool.description
    assert "- general-purpose:" not in task_tool.description


def test_compiled_graph_keeps_capability_topology_stable_while_opted_out():
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "compile-proof"}},
        model=ToolCapableFakeModel(responses=[_final_message("done")]),
    )
    registered_tools = _compiled_tool_names(compiled)

    assert {tool.name for tool in TOOLS} <= registered_tools
    assert {"task", "write_todos"} <= registered_tools
    assert QUICKJS_TOOL_NAME in registered_tools


def test_owner_runtime_without_model_override_defaults_to_exact_luna(monkeypatch):
    monkeypatch.delenv("MODEL", raising=False)

    assert _normalized_model_spec() == "openai:gpt-5.6-luna"


async def test_owner_default_luna_preserves_dynamic_subagents_and_quickjs_topology(
    monkeypatch,
):
    monkeypatch.delenv("MODEL", raising=False)
    model = ToolCapableFakeModel(
        responses=[_openai_final_message("owner topology preserved")]
    )
    monkeypatch.setattr("agent.graph._bounded_model", lambda _spec: model)
    budget = RunBudget()
    quickjs_middleware = BoundedQuickJSMiddleware(enabled=True)
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "owner-luna-topology"}},
        budget=budget,
        input_token_counter=_exact_openai_test_input_tokens,
        dynamic_subagents_enabled=True,
        quickjs_enabled=True,
        quickjs_middleware=quickjs_middleware,
    )

    try:
        result = await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "inspect topology"}]},
            {"configurable": {"thread_id": "owner-luna-topology"}},
        )
    finally:
        await quickjs_middleware.aclose()

    assert result["messages"][-1].content == "owner topology preserved"
    bound_tools = model.bound_tool_names[0]
    assert {"task", "write_todos", QUICKJS_TOOL_NAME} <= bound_tools
    task_tool = compiled.nodes["tools"].bound._tools_by_name["task"]
    assert "shared run budget" in task_tool.description
    assert all(f"- {name}:" in task_tool.description for name in SUBAGENT_NAMES)
    snapshot = budget.finalize()
    assert snapshot.provider_usage_complete is True
    assert snapshot.provider_input_tokens == 1
    assert snapshot.provider_output_tokens == 9


@pytest.mark.parametrize(
    ("configured_model", "expected_model"),
    [
        (None, DEFAULT_MODEL),
        ("openai/gpt-5.6-luna", DEFAULT_MODEL),
    ],
    ids=["default-model", "normalized-model-override"],
)
def test_create_graph_for_selected_model_keeps_declared_task_dispatch(
    monkeypatch,
    configured_model,
    expected_model,
):
    if configured_model is None:
        monkeypatch.delenv("MODEL", raising=False)
    else:
        monkeypatch.setenv("MODEL", configured_model)

    compiled_graph = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "selected-model"}},
        model=ToolCapableFakeModel(responses=[_final_message("done")]),
    )

    assert _normalized_model_spec() == expected_model
    assert isinstance(compiled_graph, CompiledStateGraph)
    assert {tool.name for tool in TOOLS} <= _compiled_tool_names(compiled_graph)
    assert "task" in _compiled_tool_names(compiled_graph)
    assert QUICKJS_TOOL_NAME in _compiled_tool_names(compiled_graph)
    assert compiled_graph.stream_transformers[-1] is InspectionEventTransformer


@pytest.mark.parametrize(
    ("model_spec", "model_name"),
    [
        ("openai:gpt-5.6-luna", "gpt-5.6-luna"),
        ("openai:gpt-5.6-terra", "gpt-5.6-terra"),
        ("openai:gpt-5.6-sol", "gpt-5.6-sol"),
    ],
)
def test_bounded_owner_model_uses_exact_responses_contract(
    monkeypatch,
    model_spec,
    model_name,
):
    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    api_key = "test-openai-owner-construction-key"
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    _bounded_model.cache_clear()
    try:
        resolved = _bounded_model(model_spec)
        cached = _bounded_model(model_spec)
    finally:
        _bounded_model.cache_clear()

    assert isinstance(resolved, ChatOpenAI)
    assert cached is resolved
    assert resolved.model_name == model_name
    assert resolved.openai_api_key.get_secret_value() == api_key
    assert resolved.max_tokens == MODEL_MAX_OUTPUT_TOKENS
    assert resolved.max_retries == 0
    assert resolved.request_timeout == MODEL_TIMEOUT_SECONDS
    assert resolved.use_responses_api is True
    assert resolved.output_version == "responses/v1"
    assert resolved.reasoning == {"context": "current_turn", "effort": "none"}
    assert resolved.store is False
    assert resolved.truncation == "disabled"
    assert resolved.streaming is False
    assert resolved.cache is False
    assert resolved.extra_body == {"safety_identifier": OWNER_OPENAI_SAFETY_IDENTIFIER}
    assert resolved.openai_api_base == OPENAI_API_BASE_URL


def test_bounded_guest_model_uses_the_lower_nonconfigurable_output_limit(monkeypatch):
    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-guest-construction-key")
    safety_identifier = openai_guest_safety_identifier(
        "anon:00000000-0000-4000-8000-000000000001"
    )
    _bounded_guest_model.cache_clear()
    try:
        resolved = _bounded_guest_model(
            OPENAI_GUEST_MODEL_SPEC,
            safety_identifier,
        )
        cached = _bounded_guest_model(
            OPENAI_GUEST_MODEL_SPEC,
            safety_identifier,
        )
    finally:
        _bounded_guest_model.cache_clear()

    assert isinstance(resolved, ChatOpenAI)
    assert cached is resolved
    assert resolved.model_name == "gpt-5.6-luna"
    assert resolved.max_tokens == GUEST_MODEL_MAX_OUTPUT_TOKENS
    assert resolved.max_retries == 0
    assert resolved.request_timeout == MODEL_TIMEOUT_SECONDS
    assert resolved.use_responses_api is True
    assert resolved.output_version == "responses/v1"
    assert resolved.reasoning == {"context": "current_turn", "effort": "none"}
    assert resolved.store is False
    assert resolved.truncation == "disabled"
    assert resolved.streaming is False
    assert "streaming" not in resolved.model_fields_set
    assert resolved.cache is False
    assert resolved.extra_body == {"safety_identifier": safety_identifier}
    assert resolved.openai_api_base == OPENAI_API_BASE_URL
    assert str(resolved.root_client.base_url) == f"{OPENAI_API_BASE_URL}/"
    assert str(resolved.root_async_client.base_url) == f"{OPENAI_API_BASE_URL}/"
    assert _require_exact_openai_guest_model(resolved) is resolved


def test_bounded_guest_model_rejects_ambient_routing_before_credential_read(
    monkeypatch,
):
    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS",
        "Authorization: Bearer attacker\nOpenAI-Project: attacker-project",
    )
    credential_reads = 0

    def unexpected_credential_read() -> str:
        nonlocal credential_reads
        credential_reads += 1
        raise AssertionError("ambient routing reached credential access")

    monkeypatch.setattr(
        "agent.graph.require_openai_api_key",
        unexpected_credential_read,
    )
    safety_identifier = openai_guest_safety_identifier(
        "anon:00000000-0000-4000-8000-000000000001"
    )
    _bounded_guest_model.cache_clear()
    try:
        with pytest.raises(
            InputTokenCountError,
            match="ambient OpenAI routing configuration is forbidden",
        ):
            _bounded_guest_model(OPENAI_GUEST_MODEL_SPEC, safety_identifier)
    finally:
        _bounded_guest_model.cache_clear()

    assert credential_reads == 0


def test_guest_and_owner_graphs_route_distinct_server_owned_counters(monkeypatch):
    captured = []
    compiled = SimpleNamespace(stream_transformers=())
    compiled.copy = lambda *, update: SimpleNamespace(**update)

    def capture_deep_agent(**kwargs):
        captured.append(kwargs)
        return compiled

    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr("agent.graph.create_deep_agent", capture_deep_agent)
    monkeypatch.setattr("agent.graph.build_subagents", lambda **_kwargs: [])
    fake_model = ToolCapableFakeModel(responses=[_final_message("unused")])

    create_graph(
        runtime=_guest_runtime(),
        config={"configurable": {"thread_id": "guest-counter-routing"}},
        model=fake_model,
        budget=RunBudget(GUEST_RUN_BUDGET_POLICY),
    )
    create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "owner-counter-routing"}},
        model=fake_model,
        budget=RunBudget(),
    )

    guest_middleware = captured[0]["middleware"][-1]
    owner_middleware = captured[1]["middleware"][-1]
    assert isinstance(guest_middleware, RunBudgetMiddleware)
    assert isinstance(owner_middleware, RunBudgetMiddleware)
    assert guest_middleware._input_token_counter is _exact_openai_test_input_tokens
    assert guest_middleware._model_provider == "openai"
    assert (
        guest_middleware._expected_response_models == OPENAI_GUEST_RESPONSE_MODEL_NAMES
    )
    assert guest_middleware._root_tool_allowlist == GUEST_ROOT_TOOL_NAMES | {"task"}
    assert owner_middleware._input_token_counter is _exact_anthropic_test_input_tokens
    assert owner_middleware._model_provider == "anthropic"
    assert owner_middleware._expected_response_models == frozenset()
    assert owner_middleware._root_tool_allowlist is None
    assert guest_middleware._input_token_count_preparer is None
    assert owner_middleware._input_token_count_preparer is None
    assert captured[0]["skills"] == []
    assert captured[1]["skills"] == ["/skills/"]
    guest_prompt = captured[0]["system_prompt"]
    assert "semantic_search" in guest_prompt
    assert "keyword_search" in guest_prompt
    assert "no mounted skill" in guest_prompt
    assert "Use the mounted blog-retrieval skill" not in guest_prompt


def test_real_openai_guest_graph_wires_atomic_count_preparation(monkeypatch):
    captured = []
    compiled = SimpleNamespace(stream_transformers=())
    compiled.copy = lambda *, update: SimpleNamespace(**update)

    def capture_deep_agent(**kwargs):
        captured.append(kwargs)
        return compiled

    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-guest-construction-key")
    monkeypatch.setattr("agent.graph.create_deep_agent", capture_deep_agent)
    monkeypatch.setattr("agent.graph.build_subagents", lambda **_kwargs: [])
    safety_identifier = openai_guest_safety_identifier(
        "anon:00000000-0000-4000-8000-000000000001"
    )
    _bounded_guest_model.cache_clear()
    try:
        model = _bounded_guest_model(OPENAI_GUEST_MODEL_SPEC, safety_identifier)
        create_graph(
            runtime=_guest_runtime(),
            config={"configurable": {"thread_id": "guest-atomic-count"}},
            model=model,
            budget=RunBudget(GUEST_RUN_BUDGET_POLICY),
        )
    finally:
        _bounded_guest_model.cache_clear()

    middleware = captured[0]["middleware"][-1]
    assert isinstance(middleware, RunBudgetMiddleware)
    assert middleware._input_token_count_preparer is prepare_openai_input_token_count


def test_real_openai_owner_graph_wires_contract_bound_atomic_count_preparation(
    monkeypatch,
):
    captured = []
    subagent_kwargs = {}
    compiled = SimpleNamespace(stream_transformers=())
    compiled.copy = lambda *, update: SimpleNamespace(**update)

    def capture_deep_agent(**kwargs):
        captured.append(kwargs)
        return compiled

    def capture_subagents(**kwargs):
        subagent_kwargs.update(kwargs)
        return []

    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-owner-construction-key")
    monkeypatch.setattr("agent.graph.create_deep_agent", capture_deep_agent)
    monkeypatch.setattr("agent.graph.build_subagents", capture_subagents)
    _bounded_model.cache_clear()
    try:
        create_graph(
            runtime=_server_runtime(["admin"]),
            config={"configurable": {"thread_id": "owner-atomic-count"}},
            budget=RunBudget(),
        )
    finally:
        _bounded_model.cache_clear()

    middleware = captured[0]["middleware"][-1]
    preparer = graph_module._OWNER_OPENAI_INPUT_TOKEN_PREPARER
    assert isinstance(middleware, RunBudgetMiddleware)
    assert middleware._input_token_count_preparer is preparer
    assert subagent_kwargs["input_token_count_preparer"] is preparer


def test_guest_root_tool_contract_is_literal_ordered_unique_and_exact():
    expected = (
        "keyword_search",
        "semantic_search",
        "metadata_filter",
        "graph_traverse",
        "list_posts",
        "read_post",
    )
    actual = tuple(tool.name for tool in TOOLS)

    assert actual == expected
    assert len(actual) == len(set(actual)) == 6
    assert frozenset(expected) == GUEST_ROOT_TOOL_NAMES


def test_seventh_root_tool_fails_graph_creation_before_compilation(monkeypatch):
    called = False

    def forbidden_compile(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("a mutated root surface must fail before compilation")

    monkeypatch.setattr(
        graph_module,
        "TOOLS",
        [*TOOLS, SimpleNamespace(name="write_file")],
    )
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr(graph_module, "create_deep_agent", forbidden_compile)

    with pytest.raises(RuntimeError, match="reviewed six-name ordered allowlist"):
        create_graph(
            runtime=_guest_runtime(),
            config={"configurable": {"thread_id": "guest-seventh-tool"}},
            model=ToolCapableFakeModel(responses=[_final_message("unused")]),
            budget=RunBudget(GUEST_RUN_BUDGET_POLICY),
        )

    assert called is False


@pytest.mark.parametrize(
    ("configured_model", "expected"),
    [
        (OPENAI_GUEST_MODEL_SPEC, OPENAI_GUEST_MODEL_SPEC),
        ("openai/gpt-5.6-luna", OPENAI_GUEST_MODEL_SPEC),
    ],
)
def test_guest_model_is_explicit_and_canonical(monkeypatch, configured_model, expected):
    monkeypatch.setenv("GUEST_MODEL", configured_model)

    assert _normalized_guest_model_spec() == expected


@pytest.mark.parametrize(
    "configured_model",
    [
        "",
        "openai:gpt-5",
        "anthropic:claude-haiku-4-5",
        "runtime configurable",
    ],
)
def test_missing_or_unsupported_guest_model_fails_closed(
    monkeypatch,
    configured_model,
):
    monkeypatch.setenv("GUEST_MODEL", configured_model)

    with pytest.raises(RuntimeError, match="GUEST_MODEL"):
        _normalized_guest_model_spec()


@pytest.mark.parametrize(
    "configured_model",
    [
        "ollama:local-model",
        "openai:gpt-5",
        "anthropic:",
        "client configurable model",
    ],
)
def test_unsupported_server_model_configuration_fails_closed(
    monkeypatch,
    configured_model,
):
    monkeypatch.setenv("MODEL", configured_model)

    with pytest.raises(RuntimeError, match="MODEL"):
        _normalized_model_spec()


async def test_runtime_without_owner_permission_hides_task_and_delegation_prompt():
    model = ToolCapableFakeModel(responses=[_final_message("no delegation")])
    budget = RunBudget()
    root_prompts = []

    async def capture_counted_prompt(request):
        root_prompts.append(request.system_message.content)
        return 1

    compiled = create_graph(
        runtime=_server_runtime([]),
        config={"configurable": {"thread_id": "unauthorized-task"}},
        model=model,
        budget=budget,
        input_token_counter=capture_counted_prompt,
        dynamic_subagents_enabled=True,
        quickjs_enabled=True,
    )

    result = await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "answer directly"}]},
        {"configurable": {"thread_id": "unauthorized-task"}},
    )

    assert result["messages"][-1].content == "no delegation"
    assert len(model.bound_tool_names) == 1
    assert "task" not in model.bound_tool_names[0]
    assert "write_todos" in model.bound_tool_names[0]
    assert "delete" not in model.bound_tool_names[0]
    assert QUICKJS_TOOL_NAME not in model.bound_tool_names[0]
    assert len(root_prompts) == 1
    prompt_text = str(root_prompts[0])
    assert SUBAGENT_ROOT_PROMPT.strip() not in prompt_text
    assert all(name not in prompt_text for name in SUBAGENT_NAMES)
    assert QUICKJS_SYSTEM_PROMPT.strip() not in prompt_text
    assert budget.snapshot().model_calls == 1


async def test_canonical_guest_runtime_forces_low_budget_and_no_paid_capabilities(
    monkeypatch,
):
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    model = PayloadRecordingFakeModel(responses=[_openai_final_message("guest answer")])
    budget = RunBudget(GUEST_RUN_BUDGET_POLICY)
    compiled = create_graph(
        runtime=_guest_runtime(),
        config={"configurable": {"thread_id": "guest-tier"}},
        model=model,
        budget=budget,
        dynamic_subagents_enabled=True,
        quickjs_enabled=True,
    )

    result = await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "public test"}]},
        {"configurable": {"thread_id": "guest-tier"}},
    )

    assert result["messages"][-1].content == "guest answer"
    assert model.bound_tool_names == [GUEST_ROOT_TOOL_NAMES | {"task"}]
    assert len(model.invoked_messages) == 1
    guest_system_text = "\n".join(
        block["text"]
        for block in model.invoked_messages[0][0].content_blocks
        if block["type"] == "text"
    )
    assert WRITE_TODOS_SYSTEM_PROMPT not in guest_system_text
    assert "within 600 output tokens" in guest_system_text
    snapshot = budget.snapshot()
    assert snapshot.policy_id == "anonymous-public-v7"
    assert snapshot.model_calls == 1
    assert snapshot.charged_tokens == 10


async def test_canonical_guest_can_delegate_to_one_isolated_specialist(monkeypatch):
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    monkeypatch.setattr(
        keyword_search,
        "func",
        lambda query, top_k=10, runtime=None: (
            f"{query}:{top_k}:{runtime is None}\ncontent/AI/a.md\ncontent/AI/b.md"
        ),
    )
    description = """\
Question:
Compare two RAG posts.
Allowed corpus/method scope:
Published retrieval evidence only.
Expected output schema:
One comparison with two source paths.
Stopping condition:
Stop after one comparison.
"""
    model = ToolCapableFakeModel(
        responses=[
            _openai_tool_message(
                "task",
                {
                    "description": description,
                    "subagent_type": "evidence-checker",
                },
                "guest-specialist-task",
            ),
            _openai_tool_message(
                "keyword_search",
                {"query": "Docker", "top_k": 1},
                "guest-specialist-retrieval",
            ),
            _openai_final_message("The claim is supported."),
            _openai_final_message(
                "Compared [A](content/AI/a.md) and [B](content/AI/b.md)."
            ),
        ]
    )
    child_tool_names = []

    async def capture_child_tools(request):
        tool_names = {
            tool.get("name") if isinstance(tool, dict) else tool.name
            for tool in request.tools
        }
        if "task" not in tool_names:
            child_tool_names.append(tool_names)
        return 1

    budget = RunBudget(GUEST_RUN_BUDGET_POLICY)
    compiled = create_graph(
        runtime=_guest_runtime(),
        config={"configurable": {"thread_id": "guest-specialist"}},
        model=model,
        budget=budget,
        input_token_counter=capture_child_tools,
    )

    result = await compiled.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "서브에이전트를 활용해서 내 블로그의 RAG 관련 글 두 편을 찾아, "
                        "각 글의 핵심 주장과 서로 다른 점을 출처와 함께 비교해줘."
                    ),
                }
            ]
        },
        {"configurable": {"thread_id": "guest-specialist"}},
    )

    final_answer = result["messages"][-1].content
    assert "content/AI/a.md" in final_answer
    assert "content/AI/b.md" in final_answer
    assert len(child_tool_names) == 2
    for tool_names in child_tool_names:
        assert {
            "task",
            "read_blog_retrieval_skill",
            QUICKJS_TOOL_NAME,
            "write_file",
            "edit_file",
        }.isdisjoint(tool_names)
    snapshot = budget.snapshot()
    assert (snapshot.model_calls, snapshot.tool_calls, snapshot.task_calls) == (4, 2, 1)
    assert snapshot.charged_tokens <= 64_000
    assert snapshot.count_risk_tokens <= 128_000
    assert snapshot.exhausted is False
    assert GUEST_RUN_BUDGET_POLICY.max_task_calls == 8
    assert GUEST_RUN_BUDGET_POLICY.max_tasks_in_flight == 2


def test_guest_model_selection_is_rejected_even_with_a_signed_override():
    with pytest.raises(ValueError, match="server-owned"):
        create_graph(
            runtime=_guest_runtime(),
            config={
                "configurable": {
                    "thread_id": "guest-model-selection",
                    "model": "gpt-5.6-terra",
                }
            },
            model=ToolCapableFakeModel(responses=[_final_message("unused")]),
        )


def test_owner_model_selection_uses_server_allowlist(monkeypatch):
    selected = []
    model = ToolCapableFakeModel(responses=[_final_message("selected")])

    def select_model(model_spec):
        selected.append(model_spec)
        return model

    monkeypatch.setattr("agent.graph._bounded_model", select_model)
    compiled = create_graph(
        runtime=_server_runtime(["model:select"]),
        config={
            "configurable": {
                "thread_id": "owner-model-selection",
                "model": "gpt-5.6-terra",
            }
        },
        input_token_counter=_exact_anthropic_test_input_tokens,
        dynamic_subagents_enabled=False,
        quickjs_enabled=False,
    )

    assert isinstance(compiled, CompiledStateGraph)
    assert selected == ["openai:gpt-5.6-terra"]


@pytest.mark.parametrize(
    "requested",
    ["openai:gpt-5.6-terra", "gpt-5.6-arbitrary", 1],
)
def test_owner_model_selection_rejects_values_outside_server_allowlist(requested):
    with pytest.raises(ValueError, match="not an allowed model"):
        create_graph(
            runtime=_server_runtime(["model:select"]),
            config={
                "configurable": {
                    "thread_id": "owner-model-selection-invalid",
                    "model": requested,
                }
            },
            dynamic_subagents_enabled=False,
            quickjs_enabled=False,
        )


def test_owner_model_selection_requires_server_permission():
    with pytest.raises(ValueError, match="server-owned"):
        create_graph(
            runtime=_server_runtime([]),
            config={
                "configurable": {
                    "thread_id": "owner-model-selection-denied",
                    "model": "gpt-5.6-terra",
                }
            },
            model=ToolCapableFakeModel(responses=[_final_message("unused")]),
        )


async def test_eval_injected_openai_contract_uses_provider_native_settlement(
    monkeypatch,
):
    monkeypatch.setenv("MODEL", OPENAI_GUEST_MODEL_SPEC)
    model = ToolCapableFakeModel(responses=[_openai_final_message("eval answer")])
    budget = RunBudget()
    compiled = create_graph(
        runtime=_server_runtime(["eval"]),
        config={"configurable": {"thread_id": "openai-eval-provider"}},
        model=model,
        budget=budget,
        input_token_counter=_exact_openai_test_input_tokens,
        model_provider="openai",
        expected_response_models=frozenset({"gpt-5.6-luna"}),
        dynamic_subagents_enabled=False,
        quickjs_enabled=False,
    )

    result = await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "bounded local eval"}]},
        {"configurable": {"thread_id": "openai-eval-provider"}},
    )

    assert result["messages"][-1].content == "eval answer"
    snapshot = budget.finalize()
    assert snapshot.provider_usage_complete is True
    assert snapshot.provider_input_tokens == 1
    assert snapshot.provider_output_tokens == 9
    assert snapshot.charged_tokens == 10


def test_provider_contract_override_requires_an_injected_exact_model():
    with pytest.raises(ValueError, match="requires an injected model"):
        create_graph(
            runtime=_server_runtime(["eval"]),
            config={"configurable": {"thread_id": "provider-without-model"}},
            model_provider="openai",
            expected_response_models=frozenset({"gpt-5.6-luna"}),
        )

    with pytest.raises(ValueError, match="requires exact response models"):
        create_graph(
            runtime=_server_runtime(["eval"]),
            config={"configurable": {"thread_id": "provider-without-model-name"}},
            model=ToolCapableFakeModel(responses=[_final_message("unused")]),
            model_provider="openai",
            expected_response_models=frozenset(),
        )

    with pytest.raises(ValueError, match="requires exact response models"):
        create_graph(
            runtime=_server_runtime(["eval"]),
            config={"configurable": {"thread_id": "provider-wrong-model-name"}},
            model=ToolCapableFakeModel(responses=[_final_message("unused")]),
            model_provider="openai",
            expected_response_models=frozenset({"gpt-5.4-mini"}),
        )


async def test_canonical_guest_runtime_rejects_a_forged_filesystem_tool_call(
    monkeypatch,
):
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "/guest-injected.txt",
                            "content": "forbidden",
                        },
                        "id": "forged-guest-filesystem-call",
                        "type": "tool_call",
                    }
                ],
                response_metadata={
                    "model_provider": "openai",
                    "model_name": "gpt-5.6-luna",
                    "status": "completed",
                },
                usage_metadata={
                    "input_tokens": 1,
                    "output_tokens": 9,
                    "total_tokens": 10,
                    "input_token_details": {
                        "cache_creation": 0,
                        "cache_read": 0,
                    },
                    "output_token_details": {"reasoning": 0},
                },
            )
        ]
    )
    budget = RunBudget(GUEST_RUN_BUDGET_POLICY)
    compiled = create_graph(
        runtime=_guest_runtime(),
        config={"configurable": {"thread_id": "guest-forged-filesystem"}},
        model=model,
        budget=budget,
    )

    with pytest.raises(CapabilityDeniedError, match="server-owned root tool allowlist"):
        await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "write a file"}]},
            {"configurable": {"thread_id": "guest-forged-filesystem"}},
        )

    assert model.bound_tool_names == [GUEST_ROOT_TOOL_NAMES | {"task"}]
    assert budget.snapshot().tool_calls == 0


async def test_owner_runtime_rejects_a_forged_recursive_delete_tool_call():
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "delete",
                        "args": {"file_path": "/memories"},
                        "id": "forged-owner-delete-call",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 1,
                    "output_tokens": 9,
                    "total_tokens": 10,
                },
            )
        ]
    )
    budget = RunBudget()
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "owner-forged-delete"}},
        model=model,
        budget=budget,
    )

    with pytest.raises(CapabilityDeniedError, match="reviewed root tool surface"):
        await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "delete memories"}]},
            {"configurable": {"thread_id": "owner-forged-delete"}},
        )

    assert len(model.bound_tool_names) == 1
    assert {"task", "write_todos", "write_file", "edit_file"} <= (
        model.bound_tool_names[0]
    )
    assert "delete" not in model.bound_tool_names[0]
    assert budget.snapshot().tool_calls == 0


async def test_owner_runtime_keeps_reviewed_write_overwrite_and_edit_semantics():
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "/draft.txt",
                            "content": "after overwrite\n",
                        },
                        "id": "owner-overwrite-file",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "edit_file",
                        "args": {
                            "file_path": "/draft.txt",
                            "old_string": "after overwrite",
                            "new_string": "after reviewed edit",
                        },
                        "id": "owner-edit-file",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            _final_message("Draft updated."),
        ]
    )
    budget = RunBudget()
    thread_id = "owner-reviewed-write-edit"
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": thread_id}},
        model=model,
        budget=budget,
    )

    result = await compiled.ainvoke(
        {
            "messages": [{"role": "user", "content": "update the draft"}],
            "files": {
                "/draft.txt": {
                    "content": "before overwrite\n",
                    "encoding": "utf-8",
                }
            },
        },
        {"configurable": {"thread_id": thread_id}},
    )

    assert result["files"]["/draft.txt"]["content"] == "after reviewed edit\n"
    assert all("delete" not in names for names in model.bound_tool_names)
    assert all(
        {"write_todos", "write_file", "edit_file"} <= names
        for names in model.bound_tool_names
    )
    assert budget.snapshot().tool_calls == 2


async def test_persistent_memory_write_is_create_only_and_edit_is_explicit():
    backend = _build_backend()
    memory_backend = backend.routes["/memories/"]
    memory_backend._store = InMemoryStore()
    memory_backend._namespace = lambda _runtime: (
        "users",
        "test-owner",
        "filesystem",
    )

    created = await backend.awrite("/memories/profile.txt", "first")
    overwritten = await backend.awrite("/memories/profile.txt", "blind overwrite")
    unchanged = await backend.aread("/memories/profile.txt")
    edited = await backend.aedit(
        "/memories/profile.txt",
        "first",
        "reviewed edit",
    )
    updated = await backend.aread("/memories/profile.txt")

    assert created.path == "/memories/profile.txt"
    assert overwritten.path is None
    assert overwritten.error is not None
    assert "already exists" in overwritten.error
    assert unchanged.file_data is not None
    assert unchanged.file_data["content"] == "first"
    assert edited.path == "/memories/profile.txt"
    assert updated.file_data is not None
    assert updated.file_data["content"] == "reviewed edit"


async def test_persistent_memory_unknown_store_fails_closed_without_dml():
    class UnsupportedStore:
        def __getattr__(self, name):
            raise AssertionError(f"unsupported store DML was attempted through {name}")

    backend = graph_module.CreateOnlyStoreBackend(
        namespace=lambda _runtime: ("users", "unsupported-owner", "filesystem"),
        store=UnsupportedStore(),
    )

    async_result = await backend.awrite("/profile.txt", "async content")
    sync_result = await asyncio.to_thread(
        backend.write,
        "/other.txt",
        "sync content",
    )

    for result in (async_result, sync_result):
        assert result.path is None
        assert result.error == graph_module._PERSISTENT_MEMORY_ATOMIC_GUARD_ERROR


async def test_persistent_memory_postgres_guard_failure_never_falls_back(
    monkeypatch,
):
    store = graph_module.AsyncPostgresStore(conn=SimpleNamespace())
    backend = graph_module.CreateOnlyStoreBackend(
        namespace=lambda _runtime: ("users", "postgres-failure-owner", "filesystem"),
        store=store,
    )

    async def fail_async(*_args, **_kwargs):
        raise RuntimeError("injected async PostgreSQL guard failure")

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("injected sync PostgreSQL guard failure")

    monkeypatch.setattr(
        graph_module,
        "_atomic_postgres_memory_create",
        fail_async,
    )
    async_result = await backend.awrite("/profile.txt", "async content")
    monkeypatch.setattr(
        graph_module,
        "_atomic_postgres_memory_create_sync",
        fail_sync,
    )
    sync_result = await asyncio.to_thread(
        backend.write,
        "/other.txt",
        "sync content",
    )

    for result in (async_result, sync_result):
        assert result.path is None
        assert result.error == graph_module._PERSISTENT_MEMORY_ATOMIC_GUARD_ERROR


async def test_persistent_memory_concurrent_creates_have_one_winner():
    backend = _build_backend()
    memory_backend = backend.routes["/memories/"]
    memory_backend._store = YieldingInMemoryStore()
    memory_backend._namespace = lambda _runtime: (
        "users",
        "concurrent-owner",
        "filesystem",
    )

    results = await asyncio.gather(
        backend.awrite("/memories/profile.txt", "first contender"),
        backend.awrite("/memories/profile.txt", "second contender"),
    )
    persisted = await backend.aread("/memories/profile.txt")

    assert sum(result.path is not None for result in results) == 1
    assert sum(result.error is not None for result in results) == 1
    assert persisted.file_data is not None
    assert persisted.file_data["content"] in {
        "first contender",
        "second contender",
    }


async def test_persistent_memory_sync_create_blocks_async_create(
    monkeypatch,
):
    lock = ObservedThreadLock()
    store = SyncHoldingInMemoryStore()
    backend = graph_module.CreateOnlyStoreBackend(
        namespace=lambda _runtime: ("users", "sync-first-owner", "filesystem"),
        store=store,
    )
    monkeypatch.setattr(graph_module, "_PERSISTENT_MEMORY_WRITE_LOCK", lock)

    sync_create = asyncio.create_task(
        asyncio.to_thread(backend.write, "/profile.txt", "sync winner")
    )
    assert await asyncio.to_thread(store.entered.wait, 2)
    async_create = asyncio.create_task(
        backend.awrite("/profile.txt", "async contender")
    )
    second_attempted = await asyncio.to_thread(lock.second_attempted.wait, 2)
    async_read_blocked = store.async_read_entered.is_set() is False

    store.release.set()
    sync_result, async_result = await asyncio.wait_for(
        asyncio.gather(sync_create, async_create),
        timeout=2,
    )

    assert second_attempted is True
    assert async_read_blocked is True
    assert sync_result.path == "/profile.txt"
    assert sync_result.error is None
    assert async_result.path is None
    assert "already exists" in (async_result.error or "")
    persisted = await backend.aread("/profile.txt")
    assert persisted.file_data is not None
    assert persisted.file_data["content"] == "sync winner"


async def test_persistent_memory_async_create_blocks_sync_create(
    monkeypatch,
):
    lock = ObservedThreadLock()
    store = AsyncHoldingInMemoryStore()
    backend = graph_module.CreateOnlyStoreBackend(
        namespace=lambda _runtime: ("users", "async-first-owner", "filesystem"),
        store=store,
    )
    monkeypatch.setattr(graph_module, "_PERSISTENT_MEMORY_WRITE_LOCK", lock)

    async_create = asyncio.create_task(backend.awrite("/profile.txt", "async winner"))
    await asyncio.wait_for(store.entered.wait(), timeout=2)
    sync_create = asyncio.create_task(
        asyncio.to_thread(backend.write, "/profile.txt", "sync contender")
    )
    second_attempted = await asyncio.to_thread(lock.second_attempted.wait, 2)
    sync_read_blocked = store.sync_read_entered.is_set() is False

    store.release.set()
    async_result, sync_result = await asyncio.wait_for(
        asyncio.gather(async_create, sync_create),
        timeout=2,
    )

    assert second_attempted is True
    assert sync_read_blocked is True
    assert async_result.path == "/profile.txt"
    assert async_result.error is None
    assert sync_result.path is None
    assert "already exists" in (sync_result.error or "")
    persisted = await backend.aread("/profile.txt")
    assert persisted.file_data is not None
    assert persisted.file_data["content"] == "async winner"


async def test_cancelled_persistent_memory_waiter_releases_lock_for_reuse(
    monkeypatch,
):
    lock = ObservedThreadLock()
    store = AsyncHoldingInMemoryStore()
    backend = graph_module.CreateOnlyStoreBackend(
        namespace=lambda _runtime: ("users", "cancel-owner", "filesystem"),
        store=store,
    )
    monkeypatch.setattr(graph_module, "_PERSISTENT_MEMORY_WRITE_LOCK", lock)

    holder = asyncio.create_task(backend.awrite("/profile.txt", "winner"))
    await asyncio.wait_for(store.entered.wait(), timeout=2)
    cancelled_waiter = asyncio.create_task(
        backend.awrite("/profile.txt", "cancelled contender")
    )
    second_attempted = await asyncio.to_thread(lock.second_attempted.wait, 2)

    cancelled_waiter.cancel()
    cancellation_waited_for_lock = False
    try:
        await asyncio.wait_for(asyncio.shield(cancelled_waiter), timeout=0.1)
    except TimeoutError:
        cancellation_waited_for_lock = True

    store.release.set()
    holder_result = await asyncio.wait_for(holder, timeout=2)
    assert holder_result.path == "/profile.txt"
    waiter_propagated_cancellation = False
    try:
        await asyncio.wait_for(cancelled_waiter, timeout=2)
    except asyncio.CancelledError:
        waiter_propagated_cancellation = True

    assert lock.locked() is False
    followup = await asyncio.wait_for(
        backend.awrite("/profile.txt", "late contender"),
        timeout=2,
    )
    assert second_attempted is True
    assert cancellation_waited_for_lock is True
    assert waiter_propagated_cancellation is True
    assert followup.path is None
    assert "already exists" in (followup.error or "")
    persisted = await backend.aread("/profile.txt")
    assert persisted.file_data is not None
    assert persisted.file_data["content"] == "winner"


def test_guest_runtime_rejects_caller_supplied_experiment_root_allowlist(monkeypatch):
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)

    with pytest.raises(ValueError, match="experiment root tool allowlist"):
        create_graph(
            runtime=_guest_runtime(),
            config={"configurable": {"thread_id": "guest-experiment-root-tools"}},
            model=ToolCapableFakeModel(responses=[_openai_final_message("unused")]),
            budget=RunBudget(GUEST_RUN_BUDGET_POLICY),
            root_tool_allowlist=frozenset(),
        )


def test_guest_runtime_rejects_an_owner_budget_override(monkeypatch):
    monkeypatch.setenv("GUEST_MODEL", OPENAI_GUEST_MODEL_SPEC)

    with pytest.raises(ValueError, match="anonymous run budget"):
        create_graph(
            runtime=_guest_runtime(),
            config={"configurable": {"thread_id": "guest-owner-budget"}},
            model=ToolCapableFakeModel(responses=[_final_message("unused")]),
            budget=RunBudget(),
        )


def test_only_the_canonical_anonymous_identity_selects_the_guest_tier():
    assert _runtime_is_guest(_guest_runtime())
    assert not _runtime_is_guest(_server_runtime(["anon"]))
    assert not _runtime_is_guest(
        _server_runtime(
            ["anon", "admin"],
            identity=f"anon:{UUID(int=2, version=4)}",
        )
    )
    assert not _runtime_is_guest(
        _server_runtime(
            ["admin"],
            identity=f"anon:{UUID(int=3, version=4)}",
        )
    )


async def test_exact_counter_sees_the_token_affecting_payload_delivered_to_model():
    model = PayloadRecordingFakeModel(responses=[_final_message("same payload")])
    counted_requests = []

    async def capture_exact_payload(request):
        counted_requests.append(request)
        return 1

    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "payload-equivalence"}},
        model=model,
        budget=RunBudget(),
        input_token_counter=capture_exact_payload,
    )
    await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "compare payloads"}]},
        {"configurable": {"thread_id": "payload-equivalence"}},
    )

    assert len(counted_requests) == 1
    assert len(model.invoked_messages) == 1
    counted = counted_requests[0]
    assert model.invoked_messages[0] == [
        counted.system_message,
        *counted.messages,
    ]
    counted_tool_names = frozenset(
        tool.get("name") if isinstance(tool, dict) else tool.name
        for tool in counted.tools
    )
    assert model.bound_tool_names == [counted_tool_names]
    assert {"task", "write_todos", "write_file", "edit_file"} <= counted_tool_names
    assert "delete" not in counted_tool_names
    owner_system_text = "\n".join(
        block["text"]
        for block in counted.system_message.content_blocks
        if block["type"] == "text"
    )
    assert WRITE_TODOS_SYSTEM_PROMPT in owner_system_text
    task_tools = [
        tool
        for tool in counted.tools
        if (tool.get("name") if isinstance(tool, dict) else tool.name) == "task"
    ]
    assert len(task_tools) == 1
    task_description = (
        task_tools[0].get("description")
        if isinstance(task_tools[0], dict)
        else task_tools[0].description
    )
    assert isinstance(task_description, str)
    assert "shared run budget" in task_description
    assert "limits task dispatch count" in task_description
    assert all(f"- {name}:" in task_description for name in SUBAGENT_NAMES)


@pytest.mark.parametrize(
    (
        "quickjs_enabled",
        "dynamic_subagents_enabled",
        "expected_quickjs",
        "expected_task",
    ),
    [
        (False, False, False, False),
        (False, True, False, True),
        (True, False, True, False),
        (True, True, True, True),
    ],
    ids=[
        "quickjs-off-subagents-off",
        "quickjs-off-subagents-on",
        "quickjs-on-subagents-off",
        "quickjs-on-subagents-on",
    ],
)
async def test_server_selected_capability_axes_bind_four_distinct_model_surfaces(
    quickjs_enabled,
    dynamic_subagents_enabled,
    expected_quickjs,
    expected_task,
):
    thread_id = (
        f"capability-factorial-{int(quickjs_enabled)}-{int(dynamic_subagents_enabled)}"
    )
    model = ToolCapableFakeModel(responses=[_final_message("arm complete")])
    compiled = create_graph(
        runtime=_server_runtime(["eval"]),
        config={"configurable": {"thread_id": thread_id}},
        model=model,
        budget=RunBudget(),
        quickjs_enabled=quickjs_enabled,
        dynamic_subagents_enabled=dynamic_subagents_enabled,
    )

    await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "run one arm"}]},
        {"configurable": {"thread_id": thread_id}},
    )

    assert (QUICKJS_TOOL_NAME in model.bound_tool_names[0]) is expected_quickjs
    assert ("task" in model.bound_tool_names[0]) is expected_task


@pytest.mark.parametrize("permission", ["admin", "eval"])
async def test_owner_or_eval_server_opt_in_executes_native_quickjs(permission):
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": QUICKJS_TOOL_NAME,
                        "args": {"code": "6 * 7"},
                        "id": "native-quickjs-call",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            _final_message("The bounded result is 42."),
        ]
    )
    budget = RunBudget()
    quickjs_middleware = BoundedQuickJSMiddleware(enabled=True)
    compiled = create_graph(
        runtime=_server_runtime([permission]),
        config={"configurable": {"thread_id": f"quickjs-{permission}"}},
        model=model,
        budget=budget,
        dynamic_subagents_enabled=False,
        quickjs_enabled=True,
        quickjs_middleware=quickjs_middleware,
    )
    config = {"configurable": {"thread_id": f"quickjs-{permission}"}}

    try:
        result = await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "calculate once"}]},
            config,
        )
    finally:
        await quickjs_middleware.aclose()

    eval_messages = [
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == QUICKJS_TOOL_NAME
    ]
    assert len(eval_messages) == 1
    payload = json.loads(eval_messages[0].content)
    assert payload == {
        "output": "42",
        "schema": QUICKJS_RESULT_SCHEMA,
        "status": "ok",
        "truncated": False,
    }
    assert all(QUICKJS_TOOL_NAME in names for names in model.bound_tool_names)
    assert all("task" not in names for names in model.bound_tool_names)
    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.quickjs_calls,
        snapshot.quickjs_in_flight,
        snapshot.quickjs_output_bytes,
    ) == (1, 1, 0, len(eval_messages[0].content.encode("utf-8")))


@pytest.mark.parametrize(
    ("subagents_enabled", "quickjs_enabled"),
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
    ids=["neither", "subagent-only", "quickjs-only", "combined"],
)
async def test_server_capability_axes_have_exact_prompt_and_tool_order(
    subagents_enabled,
    quickjs_enabled,
):
    thread_id = f"axes-{subagents_enabled}-{quickjs_enabled}"
    model = PayloadRecordingFakeModel(responses=[_final_message("done")])
    counted_requests = []
    quickjs_middleware = BoundedQuickJSMiddleware(enabled=quickjs_enabled)

    async def capture_exact_payload(request):
        counted_requests.append(request)
        return 1

    try:
        compiled = create_graph(
            runtime=_server_runtime(["admin"]),
            config={"configurable": {"thread_id": thread_id}},
            model=model,
            budget=RunBudget(),
            input_token_counter=capture_exact_payload,
            dynamic_subagents_enabled=subagents_enabled,
            quickjs_enabled=quickjs_enabled,
            quickjs_middleware=quickjs_middleware,
        )
        await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "same input"}]},
            {"configurable": {"thread_id": thread_id}},
        )
    finally:
        await quickjs_middleware.aclose()

    assert len(counted_requests) == 1
    assert len(model.invoked_messages) == 1
    counted = counted_requests[0]
    assert model.invoked_messages[0] == [
        counted.system_message,
        *counted.messages,
    ]
    counted_tool_names = frozenset(
        tool.get("name") if isinstance(tool, dict) else tool.name
        for tool in counted.tools
    )
    assert model.bound_tool_names == [counted_tool_names]
    assert ("task" in counted_tool_names) is subagents_enabled
    assert (QUICKJS_TOOL_NAME in counted_tool_names) is quickjs_enabled

    system_text = "\n".join(
        block["text"]
        for block in counted.system_message.content_blocks
        if block["type"] == "text"
    )
    root_prompt = SUBAGENT_ROOT_PROMPT.strip()
    quickjs_prompt = QUICKJS_SYSTEM_PROMPT.strip()
    assert (root_prompt in system_text) is subagents_enabled
    assert (quickjs_prompt in system_text) is quickjs_enabled
    if subagents_enabled:
        task_tools = [
            tool
            for tool in counted.tools
            if (tool.get("name") if isinstance(tool, dict) else tool.name) == "task"
        ]
        assert len(task_tools) == 1
        task_description = (
            task_tools[0].get("description")
            if isinstance(task_tools[0], dict)
            else task_tools[0].description
        )
        assert isinstance(task_description, str)
        assert all(f"- {name}:" in task_description for name in SUBAGENT_NAMES)
        assert "shared run budget" in task_description
        assert "limits task dispatch count" in task_description
        assert "Question:" in task_description
        assert "Stopping condition:" in task_description
        assert system_text.count(root_prompt) == 1
    if quickjs_enabled:
        assert system_text.count(quickjs_prompt) == 1


async def test_experiment_subagent_allowlist_rejects_other_specialists_before_reservation():
    thread_id = "experiment-evidence-checker-only"
    description = """\
Question:
Verify one supplied claim.
Allowed corpus/method scope:
Use only the supplied published DocId.
Expected output schema:
One supported or unsupported verdict.
Stopping condition:
Stop after one verdict.
"""
    model = PayloadRecordingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": description,
                            "subagent_type": "general-purpose",
                        },
                        "id": "forged-general-purpose",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            )
        ]
    )
    budget = RunBudget()
    counted_requests = []

    async def capture_exact_payload(request):
        counted_requests.append(request)
        return 1

    quickjs_middleware = BoundedQuickJSMiddleware(enabled=False)
    compiled = create_graph(
        runtime=_server_runtime(["eval"]),
        config={"configurable": {"thread_id": thread_id}},
        model=model,
        budget=budget,
        input_token_counter=capture_exact_payload,
        dynamic_subagents_enabled=True,
        quickjs_enabled=False,
        quickjs_middleware=quickjs_middleware,
        root_tool_allowlist=frozenset({"task"}),
        experiment_subagent_allowlist=frozenset({"evidence-checker"}),
    )

    try:
        with pytest.raises(InvalidDelegationError, match="server-declared"):
            await compiled.ainvoke(
                {"messages": [{"role": "user", "content": "delegate once"}]},
                {"configurable": {"thread_id": thread_id}},
            )
    finally:
        await quickjs_middleware.aclose()

    assert len(counted_requests) == 1
    task_tools = [
        tool
        for tool in counted_requests[0].tools
        if (tool.get("name") if isinstance(tool, dict) else tool.name) == "task"
    ]
    assert len(task_tools) == 1
    task_description = (
        task_tools[0].get("description")
        if isinstance(task_tools[0], dict)
        else task_tools[0].description
    )
    assert isinstance(task_description, str)
    assert "shared run budget" in task_description
    assert "Question:" in task_description
    assert "Stopping condition:" in task_description
    assert "- evidence-checker:" in task_description
    assert all(
        f"- {name}:" not in task_description
        for name in SUBAGENT_NAMES - {"evidence-checker"}
    )
    assert budget.snapshot().task_calls == 0


def test_openai_experiment_compiles_only_the_evidence_checker_task_inventory(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-eval-construction-key")
    safety_identifier = openai_guest_safety_identifier(
        "anon:00000000-0000-4000-8000-000000000001"
    )
    _bounded_guest_model.cache_clear()
    try:
        model = _bounded_guest_model(OPENAI_GUEST_MODEL_SPEC, safety_identifier)
        compiled = create_graph(
            runtime=_server_runtime(["eval"]),
            config={"configurable": {"thread_id": "openai-evidence-inventory"}},
            model=model,
            budget=RunBudget(),
            input_token_counter=_exact_openai_test_input_tokens,
            model_provider="openai",
            expected_response_models=OPENAI_GUEST_RESPONSE_MODEL_NAMES,
            dynamic_subagents_enabled=True,
            quickjs_enabled=False,
            root_tool_allowlist=frozenset({"task"}),
            experiment_subagent_allowlist=frozenset({"evidence-checker"}),
        )
    finally:
        _bounded_guest_model.cache_clear()

    task_tool = compiled.nodes["tools"].bound._tools_by_name["task"]
    assert "- evidence-checker:" in task_tool.description
    assert all(
        f"- {name}:" not in task_tool.description
        for name in SUBAGENT_NAMES - {"evidence-checker"}
    )


@pytest.mark.parametrize("invalid", [1, 0, "true", [], object()])
def test_dynamic_subagent_server_axis_requires_an_exact_boolean(invalid):
    with pytest.raises(TypeError, match="dynamic_subagents_enabled"):
        create_graph(
            runtime=_server_runtime(["admin"]),
            config={"configurable": {"thread_id": "invalid-subagent-axis"}},
            model=ToolCapableFakeModel(responses=[_final_message("done")]),
            dynamic_subagents_enabled=invalid,
        )


async def test_public_runtime_cannot_execute_forged_eval_call():
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": QUICKJS_TOOL_NAME,
                        "args": {"code": "6 * 7"},
                        "id": "forged-public-eval",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            )
        ]
    )
    budget = RunBudget()
    compiled = create_graph(
        runtime=_server_runtime(["anon"]),
        config={"configurable": {"thread_id": "forged-public-eval"}},
        model=model,
        budget=budget,
        quickjs_enabled=True,
    )

    with pytest.raises(CapabilityDeniedError, match="QuickJS"):
        await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "forged eval"}]},
            {"configurable": {"thread_id": "forged-public-eval"}},
        )

    assert QUICKJS_TOOL_NAME not in model.bound_tool_names[0]
    snapshot = budget.snapshot()
    assert (snapshot.quickjs_calls, snapshot.quickjs_output_bytes) == (0, 0)


async def test_root_and_child_share_one_ledger_and_child_has_no_task_or_eval():
    description = """\
Question:
Find one Docker post.
Allowed corpus/method scope:
Published exact retrieval evidence already supplied in this instruction.
Expected output schema:
One DocId and one evidence sentence.
Stopping condition:
Stop after the first supported DocId.
"""
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": description,
                            "subagent_type": "evidence-checker",
                        },
                        "id": "shared-budget-task",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            _final_message("Dev/docker.md is supported."),
            _final_message("Final answer cites Dev/docker.md."),
        ]
    )
    budget = RunBudget()
    quickjs_middleware = BoundedQuickJSMiddleware(enabled=True)
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "shared-ledger"}},
        model=model,
        budget=budget,
        dynamic_subagents_enabled=True,
        quickjs_enabled=True,
        quickjs_middleware=quickjs_middleware,
    )

    try:
        result = await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "delegate once"}]},
            {"configurable": {"thread_id": "shared-ledger"}},
        )
    finally:
        await quickjs_middleware.aclose()

    assert result["messages"][-1].content == "Final answer cites Dev/docker.md."
    assert len(model.bound_tool_names) == 3
    assert "task" in model.bound_tool_names[0]
    assert QUICKJS_TOOL_NAME in model.bound_tool_names[0]
    assert {"task", "eval"}.isdisjoint(model.bound_tool_names[1])
    assert "task" in model.bound_tool_names[2]
    assert QUICKJS_TOOL_NAME in model.bound_tool_names[2]
    snapshot = asdict(budget.snapshot())
    snapshot.pop("elapsed_ms")
    assert snapshot == {
        "policy_id": "owner-capability-lab-v4",
        "model_calls": 3,
        "model_reservations_in_flight": 0,
        "tool_calls": 1,
        "quickjs_calls": 0,
        "quickjs_in_flight": 0,
        "quickjs_output_bytes": 0,
        "task_calls": 1,
        "tasks_in_flight": 0,
        "charged_tokens": 30,
        "count_risk_tokens": 0,
        "count_risk_tokens_in_flight": 0,
        "provider_input_tokens": None,
        "provider_output_tokens": None,
        "provider_cache_read_input_tokens": None,
        "provider_cache_write_input_tokens": None,
        "provider_usage_complete": False,
        "exhausted": False,
        "finalized": False,
    }


async def test_parallel_children_receive_only_their_envelopes_and_return_no_files():
    descriptions = [
        """\
Question:
Check sibling A.
Allowed corpus/method scope:
Published exact retrieval evidence only.
Expected output schema:
One bounded verdict.
Stopping condition:
Stop after one verdict.
""",
        """\
Question:
Check sibling B.
Allowed corpus/method scope:
Published exact retrieval evidence only.
Expected output schema:
One bounded verdict.
Stopping condition:
Stop after one verdict.
""",
    ]
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": description,
                            "subagent_type": "evidence-checker",
                        },
                        "id": f"isolated-task-{index}",
                        "type": "tool_call",
                    }
                    for index, description in enumerate(descriptions)
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            _final_message("child A isolated"),
            _final_message("child B isolated"),
            _final_message("root isolated"),
        ]
    )
    child_requests = []

    async def capture_child_boundaries(request):
        tool_names = {
            tool.get("name") if isinstance(tool, dict) else tool.name
            for tool in request.tools
        }
        if "task" not in tool_names:
            child_requests.append(request)
        return 1

    budget = RunBudget()
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "parallel-child-isolation"}},
        model=model,
        budget=budget,
        input_token_counter=capture_child_boundaries,
    )
    original_files = {
        "/parent-secret.txt": {
            "content": "PARENT_ONLY_SECRET",
            "encoding": "utf-8",
        },
        "/sibling-a.txt": {
            "content": "SIBLING_A_SECRET",
            "encoding": "utf-8",
        },
        "/sibling-b.txt": {
            "content": "SIBLING_B_SECRET",
            "encoding": "utf-8",
        },
    }

    result = await compiled.ainvoke(
        {
            "messages": [{"role": "user", "content": "delegate in parallel"}],
            "files": original_files,
        },
        {"configurable": {"thread_id": "parallel-child-isolation"}},
    )

    assert len(child_requests) == 2
    assert {request.messages[0].content for request in child_requests} == set(
        descriptions
    )
    for request in child_requests:
        assert "files" not in request.state
        tool_names = {
            tool.get("name") if isinstance(tool, dict) else tool.name
            for tool in request.tools
        }
        assert {
            "task",
            "read_blog_retrieval_skill",
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "execute",
        }.isdisjoint(tool_names)
    assert result["files"] == original_files
    assert "skills_metadata" not in result
    assert "memory_contents" not in result
    snapshot = budget.snapshot()
    assert (
        snapshot.model_calls,
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (4, 2, 2, 0, 40)


async def test_aegra_run_config_reaches_child_without_carrying_budget(monkeypatch):
    monkeypatch.setattr(
        keyword_search,
        "func",
        lambda query, top_k=10, runtime=None: f"{query}:{top_k}:{runtime is None}",
    )
    description = """\
Question:
Verify one supplied DocId.
Allowed corpus/method scope:
Published exact evidence supplied by the parent.
Expected output schema:
One verification sentence.
Stopping condition:
Stop after one verdict.
"""
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": description,
                            "subagent_type": "evidence-checker",
                        },
                        "id": "config-propagation-task",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            _openai_tool_message(
                "keyword_search",
                {"query": "DocId", "top_k": 1},
                "child-config-retrieval",
            ),
            _final_message("Child observed the server config."),
            _final_message("Root completed."),
        ]
    )
    observed = []
    original = RunBudgetMiddleware.awrap_tool_call

    async def capture_child_config(self, request, handler):
        if self._depth == 1:
            configurable = request.runtime.config.get("configurable", {})
            observed.append(configurable.get("propagation_proof"))
        return await original(self, request, handler)

    monkeypatch.setattr(
        RunBudgetMiddleware,
        "awrap_tool_call",
        capture_child_config,
    )
    user = _user(["admin"])
    run_config = create_run_config(
        "aegra-run",
        "aegra-thread",
        user,
        additional_config={"configurable": {"propagation_proof": "server-preserved"}},
    )
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config=run_config,
        model=model,
        budget=RunBudget(),
    )

    await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "delegate once"}]},
        run_config,
    )

    assert observed == ["server-preserved"]
    assert "run_budget" not in run_config["configurable"]
    assert "budget" not in run_config["configurable"]


async def test_checkpoint_serialization_contains_no_run_budget_or_snapshot():
    model = ToolCapableFakeModel(responses=[_final_message("persisted safely")])
    budget = RunBudget()
    saver = InMemorySaver()
    compiled = create_graph(
        runtime=_server_runtime([]),
        config={"configurable": {"thread_id": "budget-checkpoint"}},
        model=model,
        budget=budget,
    ).copy(update={"checkpointer": saver})
    config = {"configurable": {"thread_id": "budget-checkpoint"}}

    result = await compiled.ainvoke(
        {"messages": [{"role": "user", "content": "persist this run"}]},
        config,
    )
    checkpoint = await saver.aget_tuple(config)

    assert checkpoint is not None
    encoding, payload = saver.serde.dumps_typed(checkpoint.checkpoint)
    assert encoding == "msgpack"
    assert saver.serde.loads_typed((encoding, payload)) == checkpoint.checkpoint
    assert b"RunBudget" not in payload
    assert b"owner-dynamic-subagents-v1" not in payload
    assert all("budget" not in key.casefold() for key in result)
    assert budget.snapshot().model_calls == 1


async def test_quickjs_call_mode_never_enters_aegra_checkpoint_state():
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": QUICKJS_TOOL_NAME,
                        "args": {"code": "globalThis.privateState = 42; privateState"},
                        "id": "checkpoint-quickjs-call",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            ),
            _final_message("done"),
        ]
    )
    saver = InMemorySaver()
    quickjs_middleware = BoundedQuickJSMiddleware(enabled=True)
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "quickjs-checkpoint"}},
        model=model,
        budget=RunBudget(),
        quickjs_enabled=True,
        quickjs_middleware=quickjs_middleware,
    ).copy(update={"checkpointer": saver})
    config = {"configurable": {"thread_id": "quickjs-checkpoint"}}

    try:
        result = await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "run bounded JavaScript"}]},
            config,
        )
        checkpoint = await saver.aget_tuple(config)
    finally:
        await quickjs_middleware.aclose()

    assert checkpoint is not None
    assert "_quickjs_snapshot_payload" not in result
    channel_values = checkpoint.checkpoint["channel_values"]
    assert "_quickjs_snapshot_payload" not in channel_values
    encoding, payload = saver.serde.dumps_typed(checkpoint.checkpoint)
    assert encoding == "msgpack"
    assert b"_quickjs_snapshot_payload" not in payload


def test_backend_uses_instances_for_all_routes():
    backend = _build_backend()

    assert isinstance(backend, CompositeBackend)
    assert not callable(backend)
    assert isinstance(backend.default, StateBackend)
    assert isinstance(backend.routes["/memories/"], StoreBackend)
    assert isinstance(backend.routes["/skills/"], FilesystemBackend)
    assert set(backend.routes) == {"/memories/", "/skills/"}


def test_guest_backend_has_ephemeral_thread_files_and_no_persistent_memory():
    backend = _build_backend(persistent_memory=False)

    assert isinstance(backend, CompositeBackend)
    assert isinstance(backend.default, StateBackend)
    assert isinstance(backend.routes["/skills/"], FilesystemBackend)
    assert set(backend.routes) == {"/skills/"}


def test_skills_are_the_only_host_filesystem_route_and_are_write_denied():
    permissions = _filesystem_permissions()

    assert permissions == [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills", "/skills/**"],
            mode="deny",
        )
    ]


def test_single_blog_workflow_skill_loads_without_warnings(caplog):
    middleware = SkillsMiddleware(backend=_build_backend(), sources=["/skills/"])

    update = middleware.before_agent({}, Runtime(), {})

    assert update is not None
    assert update.get("skills_load_errors", []) == []
    assert [(skill["name"], skill["path"]) for skill in update["skills_metadata"]] == [
        ("blog-retrieval", "/skills/blog-retrieval/SKILL.md")
    ]
    assert not caplog.records


def test_expected_blog_tools_are_registered():
    assert {tool.name for tool in TOOLS} == {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_post",
        "semantic_search",
    }
    for ranked_tool in (
        next(tool for tool in TOOLS if tool.name == "keyword_search"),
        next(tool for tool in TOOLS if tool.name == "semantic_search"),
    ):
        assert set(ranked_tool.tool_call_schema.model_json_schema()["properties"]) == {
            "query",
            "top_k",
        }


def test_persistent_memory_namespace_uses_only_runtime_server_identity():
    runtime = Runtime(
        server_info=ServerInfo(
            assistant_id="fixture",
            graph_id="agent",
            user=SimpleNamespace(identity="runtime-user"),
        )
    )

    assert _memory_namespace(runtime) == (
        "users",
        hashlib.sha256(b"runtime-user").hexdigest(),
        "filesystem",
    )


def test_persistent_memory_namespace_fails_closed_without_runtime_identity():
    with pytest.raises(ValueError, match="runtime authentication identity"):
        _memory_namespace(Runtime())

    with pytest.raises(ValueError, match="runtime authentication identity"):
        _memory_namespace(
            Runtime(
                server_info=ServerInfo(
                    assistant_id="fixture",
                    graph_id="agent",
                    user=SimpleNamespace(identity=""),
                )
            )
        )


def test_owner_output_ceiling_is_high_enough_not_to_truncate_an_answer() -> None:
    """A 2_048-token ceiling cut real answers short, and the usage contract then
    rejected the truncated response outright, so the visitor received nothing."""
    from agent.graph import MODEL_MAX_OUTPUT_TOKENS, OWNER_RUN_BUDGET_POLICY

    assert MODEL_MAX_OUTPUT_TOKENS >= 64_000
    assert OWNER_RUN_BUDGET_POLICY.max_output_tokens == MODEL_MAX_OUTPUT_TOKENS


def test_guests_keep_their_own_far_lower_ceiling() -> None:
    """Only the signed-in path is uncapped; anonymous output stays bounded
    because it spends from the reviewed public budget."""
    from agent.graph import (
        GUEST_MODEL_MAX_OUTPUT_TOKENS,
        GUEST_RUN_BUDGET_POLICY,
        MODEL_MAX_OUTPUT_TOKENS,
    )

    assert GUEST_RUN_BUDGET_POLICY.max_output_tokens == GUEST_MODEL_MAX_OUTPUT_TOKENS
    assert GUEST_MODEL_MAX_OUTPUT_TOKENS < MODEL_MAX_OUTPUT_TOKENS
    assert GUEST_RUN_BUDGET_POLICY.max_total_tokens < MODEL_MAX_OUTPUT_TOKENS * 2
