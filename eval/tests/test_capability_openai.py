from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from agent.capabilities.budget import RunBudget, RunBudgetExceededError
from agent.capabilities.token_counting import (
    OPENAI_API_BASE_URL,
    OPENAI_ROUTING_ENVIRONMENT_VARIABLES,
    InputTokenCountError,
)
from agent.retrieval.protocol import DocId
from langchain_core.messages import AIMessage, ToolMessage

import blogeval.capability_openai as capability_openai
from blogeval.capability_openai import (
    OPENAI_CAPABILITY_MODEL_ID,
    OPENAI_CAPABILITY_POLICY,
    OPENAI_CAPABILITY_PROVIDER_CONTRACT,
    build_openai_executor_identity,
)
from blogeval.capability_runner import (
    CAPABILITY_ARMS,
    CapabilityEvaluationError,
    CapabilityExecutionContext,
    CapabilityExecutorDiagnosticError,
    load_capability_taskset,
)
from blogeval.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKSET_PATH = REPO_ROOT / "eval" / "querysets" / "capability-tasks-v1.json"


class _FakeCompiledGraph:
    def __init__(self, *, result: object = None, error: BaseException | None = None):
        self._result = result
        self._error = error

    def copy(self, *, update: object):
        del update
        return self

    async def ainvoke(self, inputs: object, config: object):
        del inputs, config
        if self._error is not None:
            raise self._error
        return self._result


def _executor(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        capability_openai, "_runtime", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        capability_openai.OpenAICapabilityExecutor,
        "_model_client",
        lambda _self: object(),
    )
    return capability_openai.OpenAICapabilityExecutor(
        workspace_root=REPO_ROOT,
        cache_mode="openai-implicit-recorded",
    )


def _exception_graph_text(error: BaseException) -> str:
    pending = [error]
    seen: set[int] = set()
    rendered: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        rendered.append(f"{type(current).__name__}:{current}")
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(rendered)


@pytest.fixture(autouse=True)
def _clear_openai_routing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def _context(task_id: str, *, arm_index: int) -> CapabilityExecutionContext:
    dataset = load_capability_taskset(TASKSET_PATH)
    task = next(task for task in dataset.tasks if task.task_id == task_id)
    run_id = UUID("123e4567-e89b-42d3-a456-426614174000")
    return CapabilityExecutionContext(
        arm=CAPABILITY_ARMS[arm_index],
        task=task,
        budget=RunBudget(OPENAI_CAPABILITY_POLICY),
        content_tree_sha=dataset.content_tree_sha,
        random_seed=20260801,
        attempt_id="capability-attempt-test",
        attempt_number=1,
        thread_id="capability-thread-test",
        graph_run_id=run_id,
        run_config={
            "configurable": {"thread_id": "capability-thread-test"},
            "run_id": run_id,
        },
    )


def test_openai_executor_pins_exact_sync_and_async_sdk_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capability_openai,
        "require_openai_api_key",
        lambda: "test-capability-api-key",
    )

    model = capability_openai.OpenAICapabilityExecutor(
        workspace_root=REPO_ROOT,
        cache_mode="openai-implicit-recorded",
    )._model_client()

    assert model.openai_api_base == OPENAI_API_BASE_URL
    assert "openai_api_base" in model.model_fields_set
    assert "stream_usage" in model.model_fields_set
    assert model.max_retries == 0
    assert model.reasoning == {"context": "current_turn", "effort": "none"}
    assert model.store is False
    assert model.truncation == "disabled"
    assert model.cache is False
    assert model.extra_body == {
        "safety_identifier": capability_openai._SAFETY_IDENTIFIER
    }
    for client in (model.root_client, model.root_async_client):
        assert str(client.base_url) == f"{OPENAI_API_BASE_URL}/"
        assert client.organization is None
        assert client.project is None
        assert client._custom_headers == {}
        assert client.auth_headers == {
            "Authorization": "Bearer test-capability-api-key"
        }


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("OPENAI_ADMIN_KEY", "attacker-admin"),
        ("OPENAI_API_BASE", ""),
        ("OPENAI_BASE_URL", "https://attacker.invalid/v1"),
        (
            "OPENAI_CUSTOM_HEADERS",
            "Authorization: Bearer attacker\nOpenAI-Project: attacker-project",
        ),
        ("OPENAI_ORGANIZATION", "attacker-organization"),
        ("OPENAI_ORG_ID", "attacker-organization"),
        ("OPENAI_PROJECT_ID", "attacker-project"),
        ("OPENAI_PROXY", "http://attacker.invalid:8080"),
    ],
)
def test_openai_executor_rejects_ambient_routing_before_credential_read(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    credential_reads = 0

    def unexpected_credential_read() -> str:
        nonlocal credential_reads
        credential_reads += 1
        raise AssertionError("ambient routing reached credential access")

    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(
        capability_openai,
        "require_openai_api_key",
        unexpected_credential_read,
    )

    with pytest.raises(
        InputTokenCountError,
        match="ambient OpenAI routing configuration is forbidden",
    ):
        capability_openai.OpenAICapabilityExecutor(
            workspace_root=REPO_ROOT,
            cache_mode="openai-implicit-recorded",
        )._model_client()

    assert credential_reads == 0


def test_openai_identity_derives_exact_luna_contract_and_fresh_execution_ids() -> None:
    first = build_openai_executor_identity(
        content_tree_sha="a" * 40,
        max_generation_cost_usd_micros=1_000_000,
        random_seed=20260801,
    )
    second = build_openai_executor_identity(
        content_tree_sha="a" * 40,
        max_generation_cost_usd_micros=1_000_000,
        random_seed=20260801,
    )

    assert first.model_id == OPENAI_CAPABILITY_MODEL_ID
    assert first.provider_contract == OPENAI_CAPABILITY_PROVIDER_CONTRACT
    assert first.provider_contract.endswith("langchain-openai-1.3.5:openai-2.53.0")
    assert capability_openai._EXPECTED_DISTRIBUTIONS == {
        "deepagents": "0.7.5",
        "langchain-openai": "1.3.5",
        "openai": "2.53.0",
    }
    assert first.execution_id != second.execution_id
    assert UUID(first.execution_id).version == 4
    assert first.cache_mode == "openai-implicit-recorded"
    assert first.max_generation_cost_usd_micros == 1_000_000
    assert OPENAI_CAPABILITY_POLICY.max_output_tokens == 1_024
    assert (
        first.uncached_input_usd_micros_per_million_tokens,
        first.cache_read_input_usd_micros_per_million_tokens,
        first.cache_write_input_usd_micros_per_million_tokens,
        first.output_usd_micros_per_million_tokens,
    ) == (200_000, 20_000, 250_000, 1_200_000)


def test_openai_task_payload_forces_only_the_server_selected_capabilities() -> None:
    context = _context("combined-metric-evidence", arm_index=3)

    payload = json.loads(capability_openai._task_payload(context))

    assert payload["capability_contract"] == {
        "quickjs_enabled": True,
        "quickjs_required": True,
        "subagents_enabled": True,
        "subagents_required": True,
    }
    assert payload["permitted_tool_calls"] == [
        {"name": "eval", "purpose": "one deterministic pure-data transform"},
        {
            "name": "task",
            "purpose": "one complete stateless envelope to evidence-checker",
        },
    ]
    assert payload["missing_required_capabilities"] == []
    assert "expected" not in payload
    assert payload["task_id"] == "combined-metric-evidence"
    assert any("exactly once" in line for line in payload["instructions"])
    assert any(
        "matching ToolMessage completion" in line and "later model turn" in line
        for line in payload["instructions"]
    )
    assert any(
        "answer MUST be a JSON object" in line for line in payload["instructions"]
    )


def test_openai_eval_budget_rejects_a_second_subagent_task_reservation() -> None:
    budget = RunBudget(OPENAI_CAPABILITY_POLICY)
    first = budget.reserve_task(depth=1)
    budget.finish_task(first)

    with pytest.raises(RunBudgetExceededError, match="subagent task budget exhausted"):
        budget.reserve_task(depth=1)

    assert budget.snapshot().task_calls == 1


def test_capability_graph_forwards_the_exact_provider_contract(monkeypatch) -> None:
    captured = {}
    monkeypatch.setenv(
        "AGENT_AUTH_SECRET",
        "test-capability-provider-secret-at-least-32-bytes",
    )
    monkeypatch.setenv("AEGRA_CONFIG", str(REPO_ROOT / "aegra.json"))
    monkeypatch.setenv("BG_JOB_MAX_RETRIES", "0")
    monkeypatch.setenv("FF_V2_EVENT_STREAMING", "true")
    monkeypatch.setenv("REDIS_BROKER_ENABLED", "false")

    def fake_create_graph(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("agent.graph.create_graph", fake_create_graph)
    context = _context("combined-metric-evidence", arm_index=3)

    result = capability_openai.build_capability_graph(
        context,
        runtime=object(),
        model=object(),
        input_token_counter=object(),
        model_provider="openai",
        expected_response_models=frozenset({"gpt-5.6-luna"}),
    )

    assert result is not None
    assert captured["model_provider"] == "openai"
    assert captured["expected_response_models"] == frozenset({"gpt-5.6-luna"})
    assert captured["quickjs_enabled"] is True
    assert captured["dynamic_subagents_enabled"] is True
    assert captured["root_tool_allowlist"] == frozenset({"eval", "task"})
    assert captured["experiment_subagent_allowlist"] == frozenset({"evidence-checker"})


def test_missing_required_peer_exposes_no_tool_surface() -> None:
    context = _context("combined-metric-evidence", arm_index=2)

    payload = json.loads(capability_openai._task_payload(context))

    assert payload["missing_required_capabilities"] == ["subagents"]
    assert payload["permitted_tool_calls"] == []
    assert any(
        "call no tools and immediately return" in line
        for line in payload["instructions"]
    )


def test_openai_observation_accepts_only_strict_bounded_final_json() -> None:
    message = AIMessage(
        content=json.dumps(
            {
                "answer": {"summary": "ok"},
                "citations": ["AI/LangGraph.md"],
                "failure_code": None,
                "status": "completed",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    observation = capability_openai._observation(
        message,
        cache_mode="openai-implicit-recorded",
    )

    assert observation.answer == {"summary": "ok"}
    assert observation.citations == (DocId("AI/LangGraph.md"),)
    assert observation.status == "completed"

    duplicate = AIMessage(
        content='{"answer":null,"answer":{},"citations":[],"failure_code":null,"status":"completed"}'
    )
    with pytest.raises(CapabilityEvaluationError, match="duplicate key"):
        capability_openai._observation(
            duplicate,
            cache_mode="openai-implicit-recorded",
        )


@pytest.mark.parametrize(
    ("error", "reason_code"),
    [
        (
            capability_openai.InvalidDelegationError("private delegation"),
            "delegation_contract",
        ),
        (RunBudgetExceededError("private budget"), "budget"),
        (InputTokenCountError("private prompt"), "input_count"),
        (capability_openai.CapabilityDeniedError("private tool"), "root_tool_denied"),
        (capability_openai.OpenAIError("private provider"), "provider"),
        (RuntimeError("private graph"), "graph_other"),
    ],
)
def test_executor_failure_classifier_exposes_only_allowlisted_codes(
    error: BaseException,
    reason_code: str,
) -> None:
    assert capability_openai._executor_reason_code(error) == reason_code


def test_executor_failure_classifier_follows_a_bounded_cause_chain() -> None:
    private = InputTokenCountError("private prompt body")
    wrapper = RuntimeError("private wrapper")
    wrapper.__cause__ = private

    assert capability_openai._executor_reason_code(wrapper) == "input_count"


def test_executor_redacts_root_tool_trace_names_ids_and_arguments() -> None:
    messages = [
        AIMessage(
            content="private model content",
            tool_calls=[
                {
                    "name": "eval",
                    "args": {"code": "private QuickJS source"},
                    "id": "private-eval-id",
                    "type": "tool_call",
                },
                {
                    "name": "write_secret",
                    "args": {"value": "private argument"},
                    "id": "private-other-id",
                    "type": "tool_call",
                },
            ],
        ),
        ToolMessage(
            content="private tool output",
            name="eval",
            tool_call_id="private-eval-id",
        ),
    ]

    events = capability_openai._redacted_root_tool_events(messages)

    assert events == ("call:eval", "call:other", "completion:eval")
    assert "private" not in repr(events)


def test_openai_executor_reports_graph_invoke_failure_without_secret_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = RunBudgetExceededError("private model response")
    monkeypatch.setattr(
        capability_openai,
        "build_capability_graph",
        lambda *_args, **_kwargs: _FakeCompiledGraph(error=primary),
    )

    with pytest.raises(CapabilityExecutorDiagnosticError) as raised:
        asyncio.run(
            _executor(monkeypatch).execute(
                _context("baseline-citation-shape", arm_index=0)
            )
        )

    assert raised.value.phase == "graph_invoke"
    assert raised.value.reason_code == "budget"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "private" not in _exception_graph_text(raised.value)
    assert "private" not in "".join(traceback.format_exception(raised.value))


def test_openai_executor_cleanup_cannot_mask_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = InputTokenCountError("private prompt")
    monkeypatch.setattr(
        capability_openai,
        "build_capability_graph",
        lambda *_args, **_kwargs: _FakeCompiledGraph(error=primary),
    )

    async def failed_cleanup(_self) -> None:
        raise RuntimeError("private cleanup")

    monkeypatch.setattr(
        capability_openai.BoundedQuickJSMiddleware,
        "aclose",
        failed_cleanup,
    )

    with pytest.raises(CapabilityExecutorDiagnosticError) as raised:
        asyncio.run(
            _executor(monkeypatch).execute(
                _context("baseline-citation-shape", arm_index=0)
            )
        )

    assert raised.value.phase == "graph_invoke"
    assert raised.value.reason_code == "input_count"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    rendered = _exception_graph_text(raised.value)
    assert "private prompt" not in rendered
    assert "private cleanup" not in rendered


def test_openai_executor_cancellation_wins_over_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capability_openai,
        "build_capability_graph",
        lambda *_args, **_kwargs: _FakeCompiledGraph(error=asyncio.CancelledError()),
    )

    async def failed_cleanup(_self) -> None:
        raise RuntimeError("private cleanup")

    monkeypatch.setattr(
        capability_openai.BoundedQuickJSMiddleware,
        "aclose",
        failed_cleanup,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            _executor(monkeypatch).execute(
                _context("baseline-citation-shape", arm_index=0)
            )
        )


def test_openai_executor_cleanup_cancellation_wins_over_ordinary_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capability_openai,
        "build_capability_graph",
        lambda *_args, **_kwargs: _FakeCompiledGraph(
            error=InputTokenCountError("private prompt")
        ),
    )

    async def cancelled_cleanup(_self) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        capability_openai.BoundedQuickJSMiddleware,
        "aclose",
        cancelled_cleanup,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            _executor(monkeypatch).execute(
                _context("baseline-citation-shape", arm_index=0)
            )
        )


@pytest.mark.parametrize("persistence_error", [False, True])
def test_openai_executor_persistence_preflight_failure_is_typed_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
    persistence_error: bool,
) -> None:
    class FailedOrNonemptySaver:
        async def aget_tuple(self, config: object):
            del config
            if persistence_error:
                raise InputTokenCountError("private persistence cause")
            return object()

    monkeypatch.setattr(capability_openai, "InMemorySaver", FailedOrNonemptySaver)

    with pytest.raises(CapabilityExecutorDiagnosticError) as raised:
        asyncio.run(
            _executor(monkeypatch).execute(
                _context("baseline-citation-shape", arm_index=0)
            )
        )

    assert raised.value.phase == "persistence_preflight"
    assert raised.value.reason_code == (
        "input_count" if persistence_error else "graph_other"
    )
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "private" not in _exception_graph_text(raised.value)


@pytest.mark.parametrize(
    ("failure_branch", "phase", "reason_code"),
    [
        ("graph_build", "graph_build", "graph_other"),
        ("cleanup", "quickjs_cleanup", "cleanup"),
        ("result_shape", "result_shape", "result_shape"),
        ("subtype_trace", "subtype_trace", "trace"),
        ("root_trace", "root_trace", "trace"),
        ("final_json", "final_json", "strict_json"),
    ],
)
def test_openai_executor_failure_branches_emit_typed_redacted_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    failure_branch: str,
    phase: str,
    reason_code: str,
) -> None:
    valid_final = AIMessage(
        content='{"answer":{"summary":"ok"},"citations":[],"failure_code":null,"status":"completed"}'
    )
    result: object = {"messages": [valid_final]}
    if failure_branch == "graph_build":

        def failed_build(*_args, **_kwargs):
            raise RuntimeError("private build")

        monkeypatch.setattr(capability_openai, "build_capability_graph", failed_build)
    else:
        monkeypatch.setattr(
            capability_openai,
            "build_capability_graph",
            lambda *_args, **_kwargs: _FakeCompiledGraph(
                result={} if failure_branch == "result_shape" else result
            ),
        )
    if failure_branch == "cleanup":

        async def failed_cleanup(_self) -> None:
            raise RuntimeError("private cleanup")

        monkeypatch.setattr(
            capability_openai.BoundedQuickJSMiddleware,
            "aclose",
            failed_cleanup,
        )
    elif failure_branch == "subtype_trace":
        monkeypatch.setattr(
            capability_openai,
            "recorded_subagent_types",
            lambda _messages: (_ for _ in ()).throw(RuntimeError("private subtype")),
        )
    elif failure_branch == "root_trace":
        monkeypatch.setattr(
            capability_openai,
            "recorded_root_tool_trace",
            lambda _messages: (_ for _ in ()).throw(RuntimeError("private trace")),
        )
    elif failure_branch == "final_json":
        result = {"messages": [AIMessage(content="private non-JSON response")]}
        monkeypatch.setattr(
            capability_openai,
            "build_capability_graph",
            lambda *_args, **_kwargs: _FakeCompiledGraph(result=result),
        )

    with pytest.raises(CapabilityExecutorDiagnosticError) as raised:
        asyncio.run(
            _executor(monkeypatch).execute(
                _context("baseline-citation-shape", arm_index=0)
            )
        )

    assert raised.value.phase == phase
    assert raised.value.reason_code == reason_code
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "private" not in _exception_graph_text(raised.value)


def test_paid_openai_cli_requires_explicit_acknowledgement(capsys) -> None:
    result = main(
        [
            "capability-openai",
            "--dataset",
            str(TASKSET_PATH),
            "--index-root",
            str(REPO_ROOT / "agent" / ".index"),
            "--workspace-root",
            str(REPO_ROOT),
            "--max-generation-token-cost-usd-micros",
            "1000000",
        ]
    )

    assert result == 1
    assert "requires --accept-paid-openai-run" in capsys.readouterr().err


def test_paid_openai_cli_requires_unpriced_count_acknowledgement(capsys) -> None:
    result = main(
        [
            "capability-openai",
            "--dataset",
            str(TASKSET_PATH),
            "--index-root",
            str(REPO_ROOT / "agent" / ".index"),
            "--workspace-root",
            str(REPO_ROOT),
            "--max-generation-token-cost-usd-micros",
            "1000000",
            "--accept-paid-openai-run",
        ]
    )

    assert result == 1
    assert "requires --accept-unpriced-input-token-counting" in capsys.readouterr().err


def test_paid_openai_library_path_fails_before_index_credentials_or_network(
    tmp_path: Path,
) -> None:
    dataset = load_capability_taskset(TASKSET_PATH)

    with pytest.raises(CapabilityEvaluationError, match="explicit acceptance"):
        asyncio.run(
            capability_openai.run_openai_capability_sweep(
                dataset=dataset,
                workspace_root=REPO_ROOT,
                index_root=tmp_path / "missing-index",
                output_root=tmp_path / "results",
                max_generation_cost_usd_micros=1_000_000,
                random_seed=20260801,
                paid_run_accepted=False,
                unpriced_counting_accepted=False,
            )
        )
    assert not (tmp_path / "results").exists()


def test_paid_openai_cost_preflight_fails_before_credentials_or_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dataset = load_capability_taskset(TASKSET_PATH)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        capability_openai,
        "PublishedCorpus",
        lambda _path: SimpleNamespace(
            content_git_tree_sha=dataset.content_tree_sha,
        ),
    )

    with pytest.raises(CapabilityEvaluationError, match="cost exceeds"):
        asyncio.run(
            capability_openai.run_openai_capability_sweep(
                dataset=dataset,
                workspace_root=REPO_ROOT,
                index_root=tmp_path / "stub-index",
                output_root=tmp_path / "results",
                max_generation_cost_usd_micros=1,
                random_seed=20260801,
                paid_run_accepted=True,
                unpriced_counting_accepted=True,
            )
        )
    assert not (tmp_path / "results").exists()


def test_openai_sweep_rejects_index_content_tree_drift_before_identity_or_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dataset = load_capability_taskset(TASKSET_PATH)
    identity_calls = 0

    monkeypatch.setattr(
        capability_openai,
        "PublishedCorpus",
        lambda _path: SimpleNamespace(content_git_tree_sha="f" * 40),
    )

    def unexpected_identity(**_kwargs):
        nonlocal identity_calls
        identity_calls += 1
        raise AssertionError("tree drift reached provider identity construction")

    monkeypatch.setattr(
        capability_openai,
        "build_openai_executor_identity",
        unexpected_identity,
    )

    with pytest.raises(CapabilityEvaluationError, match="corpus content tree differs"):
        asyncio.run(
            capability_openai.run_openai_capability_sweep(
                dataset=dataset,
                workspace_root=REPO_ROOT,
                index_root=tmp_path / "stale-index",
                output_root=tmp_path / "results",
                max_generation_cost_usd_micros=1_000_000,
                random_seed=20260801,
                paid_run_accepted=True,
                unpriced_counting_accepted=True,
            )
        )

    assert identity_calls == 0
    assert not (tmp_path / "results").exists()


def test_provider_stack_version_drift_fails_before_credentials_or_network(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        capability_openai.importlib.metadata,
        "version",
        lambda distribution: (
            "0.0.0"
            if distribution == "openai"
            else {
                "deepagents": "0.7.5",
                "langchain-openai": "1.3.5",
            }[distribution]
        ),
    )

    with pytest.raises(CapabilityEvaluationError, match="reviewed exact versions"):
        build_openai_executor_identity(
            content_tree_sha="a" * 40,
            max_generation_cost_usd_micros=1_000_000,
            random_seed=20260801,
        )
