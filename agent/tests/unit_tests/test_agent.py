"""Unit tests for the agent module."""

import asyncio
import hashlib
import inspect
import json
from dataclasses import asdict
from types import SimpleNamespace

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
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime, ServerInfo
from langgraph.store.memory import InMemoryStore
from pydantic import Field

from agent.capabilities.budget import (
    CapabilityDeniedError,
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
    NATIVE_SUBAGENT_SYSTEM_PROMPT,
    SUBAGENT_NAMES,
    SUBAGENT_ROOT_PROMPT,
)
from agent.graph import (
    DEFAULT_MODEL,
    MODEL_MAX_OUTPUT_TOKENS,
    MODEL_TIMEOUT_SECONDS,
    NO_GENERAL_PURPOSE_SUBAGENT,
    _bounded_model,
    _build_backend,
    _disable_general_purpose_subagent,
    _filesystem_permissions,
    _memory_namespace,
    _normalized_model_spec,
    create_graph,
    graph,
)
from agent.inspection import InspectionEventTransformer
from agent.tools import TOOLS


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """Deterministic model that records each bound tool surface."""

    bound_tool_names: list[frozenset[str]] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        self.bound_tool_names.append(
            frozenset(
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in tools
            )
        )
        return self


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


def _compiled_tool_names(compiled_graph: CompiledStateGraph) -> set[str]:
    return set(compiled_graph.nodes["tools"].bound._tools_by_name)


def _user(permissions: list[str]):
    return SimpleNamespace(
        identity="runtime-user",
        display_name="runtime-user",
        is_authenticated=True,
        permissions=permissions,
    )


def _server_runtime(permissions: list[str]):
    return build_server_runtime(
        access_context="threads.create_run",
        store=InMemoryStore(),
        user=_user(permissions),
        context=None,
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


async def _exact_test_input_tokens(_request) -> int:
    return 1


@pytest.fixture(autouse=True)
def _replace_provider_token_count(monkeypatch):
    monkeypatch.setattr(
        "agent.graph.count_anthropic_input_tokens",
        _exact_test_input_tokens,
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
            _final_message("first run"),
            _final_message("second run"),
        ]
    )

    def create_budget():
        budget = RunBudget()
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


async def test_aegra_factory_creates_a_fresh_quickjs_tool_session_per_access(
    monkeypatch,
):
    model = ToolCapableFakeModel(
        responses=[
            _final_message("first access"),
            _final_message("second access"),
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

    assert "AsyncPostgresSaver" not in source
    assert "AsyncPostgresStore" not in source
    assert "checkpointer=" not in source


def test_prebuilt_production_model_resolves_fail_closed_harness_profile(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-profile-resolution-key")
    _bounded_model.cache_clear()
    _disable_general_purpose_subagent.cache_clear()
    try:
        _disable_general_purpose_subagent(DEFAULT_MODEL)
        model = _bounded_model(DEFAULT_MODEL)
        profile = _harness_profile_for_model(model, None)
    finally:
        _bounded_model.cache_clear()
        _disable_general_purpose_subagent.cache_clear()

    assert isinstance(model, ChatAnthropic)
    assert profile.general_purpose_subagent.enabled is False
    assert "SummarizationMiddleware" in profile.excluded_middleware


def test_repeated_graph_creation_registers_profile_once_per_model(monkeypatch):
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
                model=ToolCapableFakeModel(responses=[_final_message("done")]),
            )
    finally:
        _disable_general_purpose_subagent.cache_clear()

    assert calls == [(DEFAULT_MODEL, NO_GENERAL_PURPOSE_SUBAGENT)]


def test_compiled_graph_keeps_capability_topology_stable_while_opted_out():
    compiled = create_graph(
        runtime=_server_runtime(["admin"]),
        config={"configurable": {"thread_id": "compile-proof"}},
        model=ToolCapableFakeModel(responses=[_final_message("done")]),
    )
    registered_tools = _compiled_tool_names(compiled)

    assert {tool.name for tool in TOOLS} <= registered_tools
    assert {"task"} <= registered_tools
    assert QUICKJS_TOOL_NAME in registered_tools


@pytest.mark.parametrize(
    ("configured_model", "expected_model"),
    [
        (None, DEFAULT_MODEL),
        ("anthropic/claude-haiku-4-5", "anthropic:claude-haiku-4-5"),
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


def test_bounded_provider_model_disables_retries_and_runtime_configuration(monkeypatch):
    calls = []
    fake_model = ToolCapableFakeModel(responses=[_final_message("done")])

    def fake_init(model_spec, **kwargs):
        calls.append((model_spec, kwargs))
        return fake_model

    monkeypatch.setattr("agent.graph.init_chat_model", fake_init)
    _bounded_model.cache_clear()
    try:
        resolved = _bounded_model("anthropic:test-bounded-model")
        cached = _bounded_model("anthropic:test-bounded-model")
    finally:
        _bounded_model.cache_clear()

    assert resolved is fake_model
    assert cached is fake_model
    assert calls == [
        (
            "anthropic:test-bounded-model",
            {
                "max_tokens": MODEL_MAX_OUTPUT_TOKENS,
                "max_retries": 0,
                "timeout": MODEL_TIMEOUT_SECONDS,
            },
        )
    ]


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
    assert QUICKJS_TOOL_NAME not in model.bound_tool_names[0]
    assert len(root_prompts) == 1
    prompt_text = str(root_prompts[0])
    assert SUBAGENT_ROOT_PROMPT.strip() not in prompt_text
    assert NATIVE_SUBAGENT_SYSTEM_PROMPT not in prompt_text
    assert "## `task` (subagent spawner)" not in prompt_text
    assert "Available subagent types" not in prompt_text
    assert all(name not in prompt_text for name in SUBAGENT_NAMES)
    assert QUICKJS_SYSTEM_PROMPT.strip() not in prompt_text
    assert budget.snapshot().model_calls == 1


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
    assert "## `task` (subagent spawner)" in str(counted.system_message.content)
    assert "Available subagent types" in str(counted.system_message.content)


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
    native_prompt = NATIVE_SUBAGENT_SYSTEM_PROMPT.strip()
    quickjs_prompt = QUICKJS_SYSTEM_PROMPT.strip()
    assert (root_prompt in system_text) is subagents_enabled
    assert (native_prompt in system_text) is subagents_enabled
    assert (quickjs_prompt in system_text) is quickjs_enabled
    if subagents_enabled:
        assert system_text.count(root_prompt) == 1
        assert system_text.count(native_prompt) == 1
        assert system_text.index(root_prompt) < system_text.index(native_prompt)
    if quickjs_enabled:
        assert system_text.count(quickjs_prompt) == 1
    if subagents_enabled and quickjs_enabled:
        assert system_text.index(native_prompt) < system_text.index(quickjs_prompt)


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
        "policy_id": "owner-capability-lab-v2",
        "model_calls": 3,
        "model_reservations_in_flight": 0,
        "tool_calls": 1,
        "quickjs_calls": 0,
        "quickjs_in_flight": 0,
        "quickjs_output_bytes": 0,
        "task_calls": 1,
        "tasks_in_flight": 0,
        "charged_tokens": 30,
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
        assert "read_blog_retrieval_skill" in tool_names
        assert {
            "task",
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
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_blog_retrieval_skill",
                        "args": {},
                        "id": "child-config-tool",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
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
