from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent.capabilities.budget import (
    RunBudget,
    RunBudgetMiddleware,
    RunBudgetPolicy,
)
from agent.capabilities.quickjs import QUICKJS_TOOL_NAME, BoundedQuickJSMiddleware
from agent.retrieval.protocol import DocId
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import Field

import blogeval.capability_runner as capability_runner
from blogeval.capability_runner import (
    CAPABILITY_ARMS,
    CapabilityEvaluationError,
    CapabilityExecutorIdentity,
    CapabilityObservation,
    build_capability_graph,
    load_capability_taskset,
    parse_capability_run,
    parse_capability_taskset,
    run_capability_experiment,
    verify_capability_run_directory,
    write_capability_artifacts,
)
from blogeval.jsonio import canonical_json_bytes, json_checksum
from blogeval.provenance import RunProvenance, RuntimePlatform

TASKSET_PATH = (
    Path(__file__).resolve().parents[1] / "querysets" / "capability-tasks-v1.json"
)
REPO_ROOT = Path(__file__).resolve().parents[2]
CONTENT_TREE_SHA = "71c5bbda097cc20be0cb15ca4666fd6917f89d5f"
FIXED_PROVENANCE = RunProvenance(
    agent_source_tree="sha256:" + "1" * 64,
    eval_source_tree="sha256:" + "2" * 64,
    workspace_lock="sha256:" + "3" * 64,
    runtime=RuntimePlatform(
        system="Linux",
        machine="x86_64",
        python_implementation="CPython",
        python_version="3.12.12",
    ),
)
FIXED_IDENTITY = CapabilityExecutorIdentity(
    executor_id="tests:deterministic-capability-executor@1",
    execution_id="123e4567-e89b-42d3-a456-426614174000",
    model_id="fixture:structured-agent-v1",
    random_seed=20260728,
    max_attempts=2,
    cache_mode="anthropic-ephemeral-5m-recorded",
    uncached_input_usd_micros_per_million_tokens=3_000_000,
    output_usd_micros_per_million_tokens=15_000_000,
    cache_read_input_usd_micros_per_million_tokens=300_000,
    cache_write_input_usd_micros_per_million_tokens=3_750_000,
)
FIXED_POLICY = RunBudgetPolicy(
    policy_id="capability-fixture-v1",
    max_model_calls=4,
    max_tool_calls=8,
    max_quickjs_calls=2,
    max_quickjs_in_flight=1,
    max_quickjs_output_bytes=512,
    max_quickjs_total_output_bytes=1_024,
    max_task_calls=2,
    max_tasks_in_flight=2,
    max_depth=1,
    max_output_tokens=128,
    max_total_tokens=2_048,
    max_elapsed_seconds=10,
)

_ANSWERS = {
    "baseline-citation-shape": {
        "summary": "LangGraph는 상태 기반 그래프 오케스트레이션을 다룬다."
    },
    "combined-metric-evidence": {
        "bm25_hit_at_2": True,
        "char_ngram_hit_at_2": False,
        "supported_claim_ids": ["claim-docker"],
    },
    "quickjs-ranked-list-overlap": {
        "jaccard_basis_points": 5000,
        "overlap_doc_ids": [
            "Study/Docker/2023-12-23-Docker.md",
            "Tools/Docker/2023-05-08-Docker와 VM 차이.md",
        ],
    },
    "subagent-evidence-verification": {
        "verdicts": [
            {"claim_id": "claim-agent", "supported": True},
            {"claim_id": "claim-rag", "supported": True},
        ]
    },
}
_CITATIONS = {
    "baseline-citation-shape": (DocId("AI/LangGraph.md"),),
    "combined-metric-evidence": (DocId("Study/Docker/2023-12-23-Docker.md"),),
    "quickjs-ranked-list-overlap": (
        DocId("Study/Docker/2023-12-23-Docker.md"),
        DocId("Tools/Docker/2023-05-08-Docker와 VM 차이.md"),
    ),
    "subagent-evidence-verification": (
        DocId("AI/2025-06-04-Agent Architecture Comparison.md"),
        DocId("Projects/Blog-rag/00-Overview.md"),
    ),
}


_ANTHROPIC_USAGE = {
    "input_tokens": 6,
    "output_tokens": 2,
    "total_tokens": 8,
    "input_token_details": {
        "cache_creation": 1,
        "cache_read": 1,
    },
}
_TASK_DESCRIPTION = """\
Question:
Verify the supplied claim and exact DocId.
Allowed corpus/method scope:
Use only the supplied evidence through the evidence-checker.
Expected output schema:
One compact supported verdict.
Stopping condition:
Stop after one bounded verdict.
"""


def _model_message(
    content: str,
    *,
    tool_calls: list[dict[str, object]] | None = None,
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        usage_metadata=copy.deepcopy(_ANTHROPIC_USAGE),
    )


def _final_payload(context, *, unavailable: bool) -> str:
    if unavailable:
        value = {
            "answer": None,
            "citations": [],
            "failure_code": "capability_unavailable",
            "status": "failed",
        }
    else:
        value = {
            "answer": _ANSWERS[context.task.task_id],
            "citations": [str(value) for value in _CITATIONS[context.task.task_id]],
            "failure_code": None,
            "status": "completed",
        }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _responses_for(context) -> list[AIMessage]:
    needs_quickjs = context.task.task_id in {
        "combined-metric-evidence",
        "quickjs-ranked-list-overlap",
    }
    needs_subagent = context.task.task_id in {
        "combined-metric-evidence",
        "subagent-evidence-verification",
    }
    responses: list[AIMessage] = []
    if needs_quickjs and context.arm.quickjs_enabled:
        responses.append(
            _model_message(
                "",
                tool_calls=[
                    {
                        "args": {
                            "code": (
                                "JSON.stringify({overlap:['a','b'],basisPoints:5000})"
                            )
                        },
                        "id": f"{context.attempt_id}-quickjs",
                        "name": QUICKJS_TOOL_NAME,
                        "type": "tool_call",
                    }
                ],
            )
        )
    if needs_subagent and context.arm.subagents_enabled:
        responses.extend(
            [
                _model_message(
                    "",
                    tool_calls=[
                        {
                            "args": {
                                "description": _TASK_DESCRIPTION,
                                "subagent_type": "evidence-checker",
                            },
                            "id": f"{context.attempt_id}-task",
                            "name": "task",
                            "type": "tool_call",
                        }
                    ],
                ),
                _model_message('{"supported":true}'),
            ]
        )
    unavailable = (
        needs_quickjs
        and not context.arm.quickjs_enabled
        or needs_subagent
        and not context.arm.subagents_enabled
    )
    responses.append(_model_message(_final_payload(context, unavailable=unavailable)))
    return responses


class RecordingFakeModel(FakeMessagesListChatModel):
    """Provider-free model with exact normalized Anthropic usage metadata."""

    bound_tool_names: list[frozenset[str]] = Field(default_factory=list)
    invoked_messages: list[list[object]] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        self.bound_tool_names.append(
            frozenset(
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in tools
            )
        )
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.invoked_messages.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


async def _exact_test_input_tokens(_request: ModelRequest) -> int:
    return 1


def _runtime(store: InMemoryStore):
    os.environ.setdefault(
        "AGENT_AUTH_SECRET",
        "test-secret-that-is-at-least-thirty-two-bytes",
    )
    os.environ.setdefault("AEGRA_CONFIG", str(REPO_ROOT / "aegra.json"))
    os.environ.setdefault("FF_V2_EVENT_STREAMING", "true")
    os.environ.setdefault("REDIS_BROKER_ENABLED", "false")
    os.environ.setdefault("BG_JOB_MAX_RETRIES", "0")
    from aegra_api.services.graph_factory import build_server_runtime

    return build_server_runtime(
        access_context="threads.create_run",
        store=store,
        user=SimpleNamespace(
            identity="capability-eval-user",
            display_name="capability-eval-user",
            is_authenticated=True,
            permissions=["eval"],
        ),
        context=None,
    )


class DeterministicCapabilityExecutor:
    """Execute the real production graph with only the provider model faked."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def execute(self, context):
        checkpointer = InMemorySaver()
        store = InMemoryStore()
        persistence_empty = (
            await checkpointer.aget_tuple(context.run_config) is None
            and store.list_namespaces() == []
        )
        model = RecordingFakeModel(responses=_responses_for(context))
        quickjs = BoundedQuickJSMiddleware(enabled=context.arm.quickjs_enabled)
        try:
            compiled = build_capability_graph(
                context,
                runtime=_runtime(store),
                model=model,
                input_token_counter=_exact_test_input_tokens,
                quickjs_middleware=quickjs,
            ).copy(
                update={
                    "checkpointer": checkpointer,
                    "store": store,
                }
            )
            result = await compiled.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "inputs": context.task.inputs,
                                    "prompt": context.task.prompt,
                                    "task_id": context.task.task_id,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        }
                    ]
                },
                context.run_config,
            )
        finally:
            await quickjs.aclose()

        self.records.append(
            {
                "arm_id": context.arm.arm_id,
                "attempt_id": context.attempt_id,
                "bound_tool_names": tuple(model.bound_tool_names),
                "graph_run_id": str(context.graph_run_id),
                "persistence_empty": persistence_empty,
                "task_id": context.task.task_id,
                "thread_id": context.thread_id,
            }
        )
        final = json.loads(result["messages"][-1].content)
        return CapabilityObservation(
            status=final["status"],
            answer=final["answer"],
            citations=tuple(DocId(value) for value in final["citations"]),
            persistence_empty=persistence_empty,
            cache_mode=FIXED_IDENTITY.cache_mode,
            failure_code=final["failure_code"],
        )


async def _record_provider_usage(context, *, complete: bool = True) -> None:
    middleware = RunBudgetMiddleware(
        context.budget,
        depth=0,
        allow_subagents=False,
        allowed_subagents=frozenset(),
        input_token_counter=_exact_test_input_tokens,
    )
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
    )

    async def respond(_request):
        message = AIMessage(content="accounted")
        if complete:
            message.usage_metadata = copy.deepcopy(_ANTHROPIC_USAGE)
        return ModelResponse(result=[message])

    await middleware.awrap_model_call(request, respond)


def _observation(context, *, answer=None, citations=None) -> CapabilityObservation:
    return CapabilityObservation(
        status="completed",
        answer=_ANSWERS[context.task.task_id] if answer is None else answer,
        citations=(
            _CITATIONS[context.task.task_id] if citations is None else citations
        ),
        persistence_empty=True,
        cache_mode=FIXED_IDENTITY.cache_mode,
    )


class DeterministicClock:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self) -> int:
        current = self._value
        self._value += 2_000_000
        return current


def _budget_factory(policy: RunBudgetPolicy) -> RunBudget:
    return RunBudget(policy, clock=lambda: 0.0)


GRAPH_EXECUTOR = DeterministicCapabilityExecutor()


def _run_dataset(dataset, *, executor=GRAPH_EXECUTOR, identity=FIXED_IDENTITY):
    return asyncio.run(
        run_capability_experiment(
            dataset=dataset,
            executor=executor,
            executor_identity=identity,
            budget_policy=FIXED_POLICY,
            provenance=FIXED_PROVENANCE,
            clock_ns=DeterministicClock(),
            budget_factory=_budget_factory,
        )
    )


@lru_cache(maxsize=1)
def _run():
    return _run_dataset(
        load_capability_taskset(
            TASKSET_PATH,
            content_tree_sha=CONTENT_TREE_SHA,
        )
    )


def _task_subset(*task_ids: str):
    dataset = load_capability_taskset(TASKSET_PATH)
    value = dataset.as_dict()
    selected = [
        task
        for task in value["tasks"]
        if isinstance(task, dict) and task["task_id"] in task_ids
    ]
    value["tasks"] = selected
    return parse_capability_taskset(
        value,
        checksum=json_checksum(canonical_json_bytes(value)),
    )


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode())
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def test_capability_taskset_is_canonical_and_content_tree_bound() -> None:
    dataset = load_capability_taskset(
        TASKSET_PATH,
        content_tree_sha=CONTENT_TREE_SHA,
    )

    assert dataset.dataset_id == "capability-tasks-v1"
    assert dataset.label_status == "synthetic-only"
    assert [task.task_id for task in dataset.tasks] == [
        "baseline-citation-shape",
        "combined-metric-evidence",
        "quickjs-ranked-list-overlap",
        "subagent-evidence-verification",
    ]
    assert (
        dataset.checksum
        == "sha256:b1a42c620c099390eeada6069814b83885f4d5aac54425421cd15502aee1f348"
    )
    with pytest.raises(CapabilityEvaluationError, match="content tree"):
        load_capability_taskset(TASKSET_PATH, content_tree_sha="f" * 40)
    forged = dataset.as_dict()
    forged["label_status"] = "owner-reviewed"
    with pytest.raises(CapabilityEvaluationError, match="cannot claim reviewed"):
        parse_capability_taskset(
            forged,
            checksum=json_checksum(canonical_json_bytes(forged)),
        )


@pytest.mark.parametrize(
    "dataset_id",
    [
        "../../escaped-capability-result",
        "nested/dataset",
        "Upper-Kebab",
        "underscored_id",
        "a" * 129,
    ],
    ids=[
        "traversal",
        "nested-path",
        "uppercase",
        "underscore",
        "oversized",
    ],
)
def test_capability_taskset_rejects_unsafe_or_unbounded_dataset_ids(
    dataset_id: str,
) -> None:
    dataset = load_capability_taskset(TASKSET_PATH)
    value = dataset.as_dict()
    value["dataset_id"] = dataset_id

    with pytest.raises(
        CapabilityEvaluationError,
        match="bounded lower kebab-case",
    ):
        parse_capability_taskset(
            value,
            checksum=json_checksum(canonical_json_bytes(value)),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"label_status": "owner-reviewed"},
            "cannot claim reviewed",
        ),
        (
            {"checksum": "sha256:" + "0" * 64},
            "checksum differs from canonical",
        ),
        (
            {"dataset_id": "../../escaped-capability-result"},
            "bounded lower kebab-case",
        ),
    ],
    ids=["forged-label", "forged-checksum", "traversal-id"],
)
def test_runner_reparses_directly_constructed_tasksets(
    changes: dict[str, str],
    message: str,
) -> None:
    dataset = load_capability_taskset(TASKSET_PATH)

    with pytest.raises(CapabilityEvaluationError, match=message):
        _run_dataset(replace(dataset, **changes))


def test_run_parse_write_and_verify_reparse_directly_constructed_tasksets(
    tmp_path: Path,
) -> None:
    run = _run()
    forged_label = replace(run.dataset, label_status="owner-reviewed")
    with pytest.raises(CapabilityEvaluationError, match="cannot claim reviewed"):
        parse_capability_run(run.as_dict(), dataset=forged_label)

    forged_path = replace(
        run.dataset,
        dataset_id="../../escaped-capability-result",
    )
    output_root = tmp_path / "output"
    with pytest.raises(
        CapabilityEvaluationError,
        match="bounded lower kebab-case",
    ):
        write_capability_artifacts(
            replace(run, dataset=forged_path),
            output_root=output_root,
        )
    assert not output_root.exists()
    assert not (tmp_path / "escaped-capability-result").exists()

    artifacts = write_capability_artifacts(run, output_root=output_root)
    forged_checksum = replace(
        run.dataset,
        checksum="sha256:" + "0" * 64,
    )
    with pytest.raises(
        CapabilityEvaluationError,
        match="checksum differs from canonical",
    ):
        verify_capability_run_directory(
            artifacts.directory,
            dataset=forged_checksum,
        )


def test_factorial_runner_executes_all_distinct_arms_with_shared_budgets() -> None:
    run = _run()

    assert tuple(result.arm for result in run.arms) == CAPABILITY_ARMS
    by_arm = {result.arm.arm_id: result.metrics for result in run.arms}
    assert {
        arm_id: (metrics.task_success_count, metrics.citation_correct_count)
        for arm_id, metrics in by_arm.items()
    } == {
        "quickjs-off_subagents-off": (1, 1),
        "quickjs-off_subagents-on": (2, 2),
        "quickjs-on_subagents-off": (2, 2),
        "quickjs-on_subagents-on": (4, 4),
    }
    combined = by_arm["quickjs-on_subagents-on"]
    assert (combined.quickjs_calls, combined.task_calls) == (2, 2)
    assert combined.quickjs_calls <= FIXED_POLICY.max_quickjs_calls * 4
    assert combined.task_calls <= FIXED_POLICY.max_task_calls * 4
    assert combined.total_tokens == (
        combined.input_tokens
        + combined.output_tokens
        + combined.cache_read_input_tokens
        + combined.cache_write_input_tokens
    )
    assert combined.estimated_cost_usd_micros > 0
    assert all(
        task.budget.finalized is True
        and task.budget.provider_usage_complete is True
        and task.budget.model_reservations_in_flight == 0
        and task.budget.quickjs_in_flight == 0
        and task.budget.tasks_in_flight == 0
        and not task.budget.exhausted
        for task in run.arms[-1].tasks
    )


def test_provider_free_graph_exercises_real_four_arm_topology_with_isolation() -> None:
    run = _run()
    records = GRAPH_EXECUTOR.records

    assert len(records) == len(CAPABILITY_ARMS) * len(run.dataset.tasks)
    assert [record["arm_id"] for record in records] == [
        "quickjs-off_subagents-off",
        "quickjs-off_subagents-on",
        "quickjs-on_subagents-on",
        "quickjs-on_subagents-off",
        "quickjs-off_subagents-on",
        "quickjs-on_subagents-off",
        "quickjs-off_subagents-off",
        "quickjs-on_subagents-on",
        "quickjs-on_subagents-off",
        "quickjs-on_subagents-on",
        "quickjs-off_subagents-on",
        "quickjs-off_subagents-off",
        "quickjs-on_subagents-on",
        "quickjs-off_subagents-off",
        "quickjs-on_subagents-off",
        "quickjs-off_subagents-on",
    ]
    for identity_key in ("attempt_id", "thread_id", "graph_run_id"):
        assert len({record[identity_key] for record in records}) == len(records)
    assert all(record["persistence_empty"] is True for record in records)

    quickjs_only = [
        record for record in records if record["arm_id"] == "quickjs-on_subagents-off"
    ]
    assert quickjs_only
    assert all(
        all(
            QUICKJS_TOOL_NAME in surface and "task" not in surface
            for surface in record["bound_tool_names"]
        )
        for record in quickjs_only
    )

    combined = next(
        record
        for record in records
        if record["arm_id"] == "quickjs-on_subagents-on"
        and record["task_id"] == "combined-metric-evidence"
    )
    child_surface = frozenset(
        {"keyword_search", "read_blog_retrieval_skill", "read_post"}
    )
    assert any(
        QUICKJS_TOOL_NAME in surface and "task" in surface
        for surface in combined["bound_tool_names"]
    )
    assert child_surface in combined["bound_tool_names"]
    forbidden_child_tools = {
        QUICKJS_TOOL_NAME,
        "task",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "shell",
        "env",
        "fetch",
        "http",
    }
    assert child_surface.isdisjoint(forbidden_child_tools)

    by_task_and_arm = {
        (arm.arm.arm_id, task.task_id): task for arm in run.arms for task in arm.tasks
    }
    assert (
        by_task_and_arm[
            ("quickjs-on_subagents-off", "quickjs-ranked-list-overlap")
        ].budget.quickjs_calls
        > 0
    )
    combined_result = by_task_and_arm[
        ("quickjs-on_subagents-on", "combined-metric-evidence")
    ]
    assert combined_result.budget.quickjs_calls > 0
    assert combined_result.budget.task_calls > 0
    assert all(task.attempt_number == 1 for arm in run.arms for task in arm.tasks)


def test_capability_artifacts_are_byte_stable_and_not_a_retrieval_leaderboard(
    tmp_path: Path,
) -> None:
    first_run = _run()
    second_run = _run()
    first = write_capability_artifacts(
        first_run,
        output_root=tmp_path / "first",
    )
    second = write_capability_artifacts(
        second_run,
        output_root=tmp_path / "second",
    )

    assert first.run_json.read_bytes() == second.run_json.read_bytes()
    assert _tree_digest(first.directory) == _tree_digest(second.directory)
    assert first.directory.parts[-3] == "capabilities"
    assert (
        first.directory.parent.resolve().parent
        == (tmp_path / "first" / "capabilities").resolve()
    )
    assert not (first.directory / "leaderboard.md").exists()
    report = first.report_markdown.read_text(encoding="utf-8")
    assert "intentionally excluded from the retrieval leaderboard" in report
    assert "QuickJS" in report
    assert "Subagents" in report
    verified = verify_capability_run_directory(
        first.directory,
        dataset=first_run.dataset,
    )
    assert verified.result_digest == first.result_digest
    assert verified.run == first_run


def test_capability_verifier_rejects_partial_result_directory(
    tmp_path: Path,
) -> None:
    run = _run()
    artifacts = write_capability_artifacts(run, output_root=tmp_path)
    artifacts.report_markdown.unlink()

    with pytest.raises(CapabilityEvaluationError, match="inventory mismatch"):
        verify_capability_run_directory(
            artifacts.directory,
            dataset=run.dataset,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["arms"].pop(),
            "exactly four arms",
        ),
        (
            lambda value: value["arms"].__setitem__(
                1,
                copy.deepcopy(value["arms"][0]),
            ),
            "missing, reordered, or duplicated",
        ),
        (
            lambda value: value["arms"][0]["tasks"].pop(),
            "every task exactly once",
        ),
        (
            lambda value: value["arms"][0]["metrics"].__setitem__(
                "task_success_count",
                4,
            ),
            "metrics differs",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0]["budget"].__setitem__(
                "quickjs_calls",
                1,
            ),
            "QuickJS was used in a disabled arm",
        ),
    ],
    ids=[
        "missing-arm",
        "duplicate-arm",
        "missing-task",
        "forged-metrics",
        "disabled-capability-usage",
    ],
)
def test_recorded_run_fails_closed_on_incomplete_or_forged_arm_data(
    mutate,
    message: str,
) -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    mutate(value)

    with pytest.raises(CapabilityEvaluationError, match=message):
        parse_capability_run(value, dataset=run.dataset)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["dataset"].__setitem__("task_count", True),
            r"run\.dataset\.task_count must be a non-negative integer",
        ),
        (
            lambda value: value["arms"][0]["arm"].__setitem__(
                "quickjs_enabled",
                0,
            ),
            "quickjs_enabled must be a boolean",
        ),
        (
            lambda value: value["arms"][0]["metrics"].__setitem__(
                "task_success_count",
                True,
            ),
            "task_success_count must be a non-negative integer",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0].__setitem__(
                "estimated_cost_usd_micros",
                True,
            ),
            "estimated_cost_usd_micros must be a non-negative integer",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0].__setitem__(
                "task_success",
                1,
            ),
            "task_success must be a boolean",
        ),
    ],
    ids=[
        "dataset-bool-as-int",
        "arm-int-as-bool",
        "metrics-bool-as-int",
        "cost-bool-as-int",
        "score-int-as-bool",
    ],
)
def test_recorded_run_rejects_boolean_integer_type_confusion(
    mutate,
    message: str,
) -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    mutate(value)

    with pytest.raises(CapabilityEvaluationError, match=message):
        parse_capability_run(value, dataset=run.dataset)


def _redact_provider_usage(value) -> None:
    budget = value["arms"][0]["tasks"][0]["budget"]
    budget["provider_usage_complete"] = False
    for key in (
        "provider_input_tokens",
        "provider_output_tokens",
        "provider_cache_read_input_tokens",
        "provider_cache_write_input_tokens",
    ):
        budget[key] = None


def _mark_incomplete_provider_usage_without_redaction(value) -> None:
    value["arms"][0]["tasks"][0]["budget"]["provider_usage_complete"] = False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["arms"][0]["tasks"][0]["budget"].__setitem__(
                "finalized",
                False,
            ),
            "terminal RunBudget snapshot",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0]["budget"].__setitem__(
                "model_reservations_in_flight",
                1,
            ),
            "unsettled capability reservation",
        ),
        (
            _redact_provider_usage,
            "complete Anthropic provider usage buckets",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0]["budget"].__setitem__(
                "provider_cache_read_input_tokens",
                None,
            ),
            "complete provider usage has a missing bucket",
        ),
        (
            _mark_incomplete_provider_usage_without_redaction,
            "incomplete provider usage must redact every bucket",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0]["budget"].__setitem__(
                "provider_cache_write_input_tokens",
                True,
            ),
            "provider_cache_write_input_tokens must be a non-negative integer",
        ),
        (
            lambda value: value["executor"]["pricing"].__setitem__(
                "cache_read_input_usd_micros_per_million_tokens",
                True,
            ),
            "cache_read_input_usd_micros_per_million_tokens must be a non-negative",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0].__setitem__(
                "persistence_empty",
                False,
            ),
            "empty attempt persistence",
        ),
        (
            lambda value: value["arms"][0]["tasks"][0].__setitem__(
                "attempt_id",
                "capability-attempt-" + "0" * 32,
            ),
            "attempt/thread/run identity is inconsistent",
        ),
    ],
    ids=[
        "nonterminal-snapshot",
        "open-model-reservation",
        "incomplete-all-null-provider-usage",
        "complete-missing-provider-bucket",
        "incomplete-unredacted-provider-buckets",
        "provider-bool-as-int",
        "pricing-bool-as-int",
        "persistence-not-empty",
        "attempt-identity-drift",
    ],
)
def test_recorded_run_rejects_nonterminal_or_untrusted_execution_evidence(
    mutate,
    message,
) -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    mutate(value)

    with pytest.raises(CapabilityEvaluationError, match=message):
        parse_capability_run(value, dataset=run.dataset)


def test_runner_aborts_when_executor_does_not_return_a_complete_observation() -> None:
    class ExplodingExecutor:
        async def execute(self, context):
            del context
            raise RuntimeError("provider detail must not enter a partial report")

    dataset = load_capability_taskset(TASKSET_PATH)
    with pytest.raises(
        CapabilityEvaluationError,
        match="failed before a complete observation",
    ) as raised:
        asyncio.run(
            run_capability_experiment(
                dataset=dataset,
                executor=ExplodingExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )

    assert "provider detail" not in str(raised.value)


def test_runner_rejects_incomplete_provider_usage_without_executor_accounting() -> None:
    class IncompleteUsageExecutor:
        async def execute(self, context):
            await _record_provider_usage(context, complete=False)
            return _observation(context)

    dataset = load_capability_taskset(TASKSET_PATH)
    with pytest.raises(
        CapabilityEvaluationError,
        match="incomplete Anthropic provider usage",
    ):
        asyncio.run(
            run_capability_experiment(
                dataset=dataset,
                executor=IncompleteUsageExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )


def test_observation_has_no_executor_reported_token_or_cost_surface() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        CapabilityObservation(
            status="completed",
            answer={"summary": "untrusted"},
            citations=(),
            persistence_empty=True,
            cache_mode=FIXED_IDENTITY.cache_mode,
            input_tokens=1,  # type: ignore[call-arg]
        )


def test_runner_wraps_the_complete_executor_in_the_runbudget_deadline() -> None:
    class BlockingExecutor:
        async def execute(self, context):
            del context
            await asyncio.Event().wait()

    async def run_with_external_safety_net():
        return await asyncio.wait_for(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=BlockingExecutor(),
                executor_identity=replace(FIXED_IDENTITY, max_attempts=1),
                budget_policy=replace(FIXED_POLICY, max_elapsed_seconds=1),
                provenance=FIXED_PROVENANCE,
            ),
            timeout=2,
        )

    with pytest.raises(
        CapabilityEvaluationError,
        match="complete RunBudget deadline",
    ):
        asyncio.run(run_with_external_safety_net())


@pytest.mark.parametrize(
    "reserve",
    [
        lambda budget: budget.reserve_model(input_tokens=0),
        lambda budget: budget.reserve_quickjs(),
        lambda budget: budget.reserve_task(depth=1),
    ],
    ids=["model", "quickjs", "task"],
)
def test_runner_rejects_each_open_reservation_explicitly(reserve) -> None:
    class OpenReservationExecutor:
        async def execute(self, context):
            await _record_provider_usage(context)
            reserve(context.budget)
            return _observation(context)

    with pytest.raises(CapabilityEvaluationError, match="unsettled RunBudget"):
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=OpenReservationExecutor(),
                executor_identity=replace(FIXED_IDENTITY, max_attempts=1),
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )


def test_zero_spend_retry_uses_fresh_attempt_thread_and_graph_run_ids() -> None:
    class RetryOncePerCellExecutor:
        def __init__(self) -> None:
            self.contexts = []

        async def execute(self, context):
            self.contexts.append(context)
            if context.attempt_number == 1:
                raise RuntimeError("zero-spend preflight sentinel")
            await _record_provider_usage(context)
            return _observation(context)

    executor = RetryOncePerCellExecutor()
    run = asyncio.run(
        run_capability_experiment(
            dataset=_task_subset("baseline-citation-shape"),
            executor=executor,
            executor_identity=FIXED_IDENTITY,
            budget_policy=FIXED_POLICY,
            provenance=FIXED_PROVENANCE,
            clock_ns=DeterministicClock(),
            budget_factory=_budget_factory,
        )
    )

    assert len(executor.contexts) == 8
    assert {context.attempt_number for context in executor.contexts} == {1, 2}
    assert len({context.attempt_id for context in executor.contexts}) == 8
    assert len({context.thread_id for context in executor.contexts}) == 8
    assert len({context.graph_run_id for context in executor.contexts}) == 8
    assert all(task.attempt_number == 2 for arm in run.arms for task in arm.tasks)


def test_spent_executor_failure_is_never_retried_or_omitted_from_cost() -> None:
    class SpentFailureExecutor:
        def __init__(self) -> None:
            self.attempt_ids = []

        async def execute(self, context):
            self.attempt_ids.append(context.attempt_id)
            await _record_provider_usage(context)
            raise RuntimeError("spent failure sentinel")

    executor = SpentFailureExecutor()
    with pytest.raises(
        CapabilityEvaluationError,
        match="failed before a complete observation",
    ):
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=executor,
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )
    assert len(executor.attempt_ids) == 1


@pytest.mark.parametrize(
    ("observation_changes", "message"),
    [
        ({"persistence_empty": False}, "empty attempt persistence"),
        ({"cache_mode": "disabled"}, "cache mode differs"),
    ],
    ids=["persistence-not-empty", "cache-mode-drift"],
)
def test_runner_requires_attempt_isolation_and_exact_cache_mode(
    observation_changes,
    message,
) -> None:
    class IsolationDriftExecutor:
        async def execute(self, context):
            await _record_provider_usage(context)
            return replace(_observation(context), **observation_changes)

    with pytest.raises(CapabilityEvaluationError, match=message):
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=IsolationDriftExecutor(),
                executor_identity=replace(FIXED_IDENTITY, max_attempts=1),
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )


def test_cost_uses_all_four_provider_buckets_and_rounds_once() -> None:
    run = _run()
    baseline = run.arms[0].tasks[0]

    assert (
        baseline.input_tokens,
        baseline.output_tokens,
        baseline.cache_read_input_tokens,
        baseline.cache_write_input_tokens,
    ) == (4, 2, 1, 1)
    assert baseline.estimated_cost_usd_micros == 47
    quarter_micro_identity = replace(
        FIXED_IDENTITY,
        uncached_input_usd_micros_per_million_tokens=250_000,
        output_usd_micros_per_million_tokens=250_000,
        cache_read_input_usd_micros_per_million_tokens=250_000,
        cache_write_input_usd_micros_per_million_tokens=250_000,
    )
    assert (
        capability_runner._estimated_cost(
            quarter_micro_identity,
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=1,
            cache_write_input_tokens=1,
        )
        == 1
    )


def test_enabled_arm_without_capability_activity_is_rejected_as_incomplete() -> None:
    class CapabilityIgnoringExecutor:
        async def execute(self, context):
            await _record_provider_usage(context)
            return _observation(context)

    dataset = _task_subset("quickjs-ranked-list-overlap")
    with pytest.raises(
        CapabilityEvaluationError,
        match="task-level QuickJS activity",
    ):
        asyncio.run(
            run_capability_experiment(
                dataset=dataset,
                executor=CapabilityIgnoringExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )


def test_unsettled_combined_capability_reservation_fails_closed() -> None:
    class UnsettledExecutor(DeterministicCapabilityExecutor):
        async def execute(self, context):
            observation = await super().execute(context)
            if (
                context.arm.arm_id == "quickjs-on_subagents-on"
                and context.task.task_id == "baseline-citation-shape"
            ):
                context.budget.reserve_quickjs()
            return observation

    dataset = load_capability_taskset(TASKSET_PATH)
    with pytest.raises(CapabilityEvaluationError, match="unsettled"):
        asyncio.run(
            run_capability_experiment(
                dataset=dataset,
                executor=UnsettledExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )


def test_completed_but_wrong_structured_output_scores_zero_without_aborting() -> None:
    class WrongOutputExecutor(DeterministicCapabilityExecutor):
        async def execute(self, context):
            observation = await super().execute(context)
            if (
                context.arm.arm_id == "quickjs-off_subagents-off"
                and context.task.task_id == "baseline-citation-shape"
            ):
                return CapabilityObservation(
                    status="completed",
                    answer={"summary": "wrong"},
                    citations=(DocId("Projects/Blog-rag/00-Overview.md"),),
                    persistence_empty=observation.persistence_empty,
                    cache_mode=observation.cache_mode,
                )
            return observation

    dataset = load_capability_taskset(TASKSET_PATH)
    run = asyncio.run(
        run_capability_experiment(
            dataset=dataset,
            executor=WrongOutputExecutor(),
            executor_identity=FIXED_IDENTITY,
            budget_policy=FIXED_POLICY,
            provenance=FIXED_PROVENANCE,
            clock_ns=DeterministicClock(),
            budget_factory=_budget_factory,
        )
    )

    result = run.arms[0].tasks[0]
    assert result.status == "completed"
    assert result.task_success is False
    assert result.citation_correct is False
    assert run.arms[0].metrics.task_success_count == 0
    assert run.arms[0].metrics.citation_correct_count == 0
