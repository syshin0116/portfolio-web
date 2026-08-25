from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import json
import os
import traceback
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
from agent.capabilities.token_counting import InputTokenCountError
from agent.retrieval.protocol import DocId
from agent.tools import keyword_search
from deepagents.profiles.harness.harness_profiles import _harness_profile_for_model
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from openai import OpenAIError
from pydantic import Field

import blogeval.capability_openai as capability_openai
import blogeval.capability_runner as capability_runner
from blogeval.capability_runner import (
    CAPABILITY_ARMS,
    CAPABILITY_PROVIDER_EVIDENCE_STATUS,
    OPENAI_CAPABILITY_CACHE_MODE,
    OPENAI_CAPABILITY_EXECUTOR_ID,
    OPENAI_CAPABILITY_MAX_ATTEMPTS,
    OPENAI_CAPABILITY_MODEL_ID,
    OPENAI_CAPABILITY_PRICING,
    OPENAI_CAPABILITY_PROVIDER_CONTRACT,
    CapabilityEvaluationError,
    CapabilityExecutorDiagnosticError,
    CapabilityExecutorIdentity,
    CapabilityObservation,
    activated_capabilities,
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
CONTENT_TREE_SHA = "ba0f643fec95bec1bb03ea606d81d56a11794d9a"
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
    content_tree_sha=CONTENT_TREE_SHA,
    model_id="fixture:structured-agent-v1",
    provider_contract="synthetic:provider-free",
    random_seed=20260728,
    max_attempts=2,
    cache_mode="anthropic-ephemeral-5m-recorded",
    max_generation_cost_usd_micros=500_000,
    uncached_input_usd_micros_per_million_tokens=3_000_000,
    output_usd_micros_per_million_tokens=15_000_000,
    cache_read_input_usd_micros_per_million_tokens=300_000,
    cache_write_input_usd_micros_per_million_tokens=3_750_000,
)
PROVIDER_IDENTITY = replace(
    FIXED_IDENTITY,
    executor_id=OPENAI_CAPABILITY_EXECUTOR_ID,
    model_id=OPENAI_CAPABILITY_MODEL_ID,
    provider_contract=OPENAI_CAPABILITY_PROVIDER_CONTRACT,
    max_attempts=OPENAI_CAPABILITY_MAX_ATTEMPTS,
    cache_mode=OPENAI_CAPABILITY_CACHE_MODE,
    **OPENAI_CAPABILITY_PRICING,
)
FIXED_POLICY = RunBudgetPolicy(
    policy_id="capability-fixture-v1",
    max_model_calls=5,
    max_tool_calls=8,
    max_quickjs_calls=2,
    max_quickjs_in_flight=1,
    max_quickjs_output_bytes=512,
    max_quickjs_total_output_bytes=1_024,
    max_task_calls=1,
    max_tasks_in_flight=1,
    max_depth=1,
    max_output_tokens=128,
    max_total_tokens=2_048,
    max_count_risk_tokens_per_attempt=2_048,
    max_count_risk_tokens_per_run=2_048,
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
    unavailable = (
        needs_quickjs
        and not context.arm.quickjs_enabled
        or needs_subagent
        and not context.arm.subagents_enabled
    )
    responses: list[AIMessage] = []
    if not unavailable and needs_quickjs and context.arm.quickjs_enabled:
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
    if not unavailable and needs_subagent and context.arm.subagents_enabled:
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
                _model_message(
                    "",
                    tool_calls=[
                        {
                            "args": {"query": "Docker", "top_k": 1},
                            "id": f"{context.attempt_id}-child-retrieval",
                            "name": "keyword_search",
                            "type": "tool_call",
                        }
                    ],
                ),
                _model_message('{"supported":true}'),
            ]
        )
    responses.append(_model_message(_final_payload(context, unavailable=unavailable)))
    return responses


class RecordingFakeModel(FakeMessagesListChatModel):
    """Provider-free model with exact normalized Anthropic usage metadata."""

    model_name: str = "claude-sonnet-4-6"
    bound_tool_names: list[frozenset[str]] = Field(default_factory=list)
    invoked_messages: list[list[object]] = Field(default_factory=list)

    def _get_ls_params(self, stop=None, **kwargs):
        del stop, kwargs
        return {
            "ls_model_type": "chat",
            "ls_model_name": self.model_name,
            "ls_provider": "anthropic",
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
        quickjs_active, _subagents_active = activated_capabilities(context)
        quickjs = BoundedQuickJSMiddleware(enabled=quickjs_active)
        original_keyword_search = keyword_search.func
        keyword_search.func = lambda query, top_k=10, runtime=None: (
            f"{query}:{top_k}:{runtime is None}"
        )
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
            resolved_profile = _harness_profile_for_model(model, None)
            task_tool = compiled.nodes["tools"].bound._tools_by_name["task"]
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
            keyword_search.func = original_keyword_search
            await quickjs.aclose()

        self.records.append(
            {
                "arm_id": context.arm.arm_id,
                "attempt_id": context.attempt_id,
                "bound_tool_names": tuple(model.bound_tool_names),
                "content_tree_sha": context.content_tree_sha,
                "graph_run_id": str(context.graph_run_id),
                "persistence_empty": persistence_empty,
                "resolved_excluded_middleware": (resolved_profile.excluded_middleware),
                "resolved_general_purpose_enabled": (
                    resolved_profile.general_purpose_subagent.enabled
                ),
                "task_description": task_tool.description,
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
            delegated_subagent_types=capability_runner.recorded_subagent_types(
                result["messages"]
            ),
            root_tool_trace=capability_runner.recorded_root_tool_trace(
                result["messages"]
            ),
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


GRAPH_EXECUTOR = DeterministicCapabilityExecutor()


def _run_dataset(
    dataset,
    *,
    executor=GRAPH_EXECUTOR,
    identity=FIXED_IDENTITY,
    evidence_status="synthetic-provider-free",
):
    return asyncio.run(
        run_capability_experiment(
            dataset=dataset,
            executor=executor,
            executor_identity=identity,
            budget_policy=FIXED_POLICY,
            evidence_status=evidence_status,
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


def _recorded_task(value, *, arm_id: str, task_id: str):
    return next(
        task
        for arm in value["arms"]
        if arm["arm"]["arm_id"] == arm_id
        for task in arm["tasks"]
        if task["task_id"] == task_id
    )


def test_recorded_root_tool_trace_uses_actual_langchain_completion_boundaries() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "args": {"code": "JSON.stringify([1,2])"},
                    "id": "quickjs-call",
                    "name": QUICKJS_TOOL_NAME,
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status":"ok"}',
            name=QUICKJS_TOOL_NAME,
            tool_call_id="quickjs-call",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "args": {
                        "description": _TASK_DESCRIPTION,
                        "subagent_type": "evidence-checker",
                    },
                    "id": "task-call",
                    "name": "task",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"supported":true}',
            name="task",
            tool_call_id="task-call",
        ),
    ]

    trace = capability_runner.recorded_root_tool_trace(messages)

    assert [event.as_dict() for event in trace] == [
        {
            "message_index": 0,
            "phase": "call",
            "tool_call_id": "quickjs-call",
            "tool_name": "eval",
        },
        {
            "message_index": 1,
            "phase": "completion",
            "tool_call_id": "quickjs-call",
            "tool_name": "eval",
        },
        {
            "message_index": 2,
            "phase": "call",
            "tool_call_id": "task-call",
            "tool_name": "task",
        },
        {
            "message_index": 3,
            "phase": "completion",
            "tool_call_id": "task-call",
            "tool_name": "task",
        },
    ]


@pytest.mark.parametrize(
    "completion",
    [
        None,
        ToolMessage(
            content="{}",
            name=QUICKJS_TOOL_NAME,
            tool_call_id="wrong-call-id",
        ),
        ToolMessage(
            content="{}",
            name="task",
            tool_call_id="quickjs-call",
        ),
    ],
    ids=["missing-completion", "call-id-mismatch", "tool-name-mismatch"],
)
def test_recorded_root_tool_trace_rejects_missing_or_mismatched_completion(
    completion: ToolMessage | None,
) -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "args": {"code": "JSON.stringify([1,2])"},
                    "id": "quickjs-call",
                    "name": QUICKJS_TOOL_NAME,
                    "type": "tool_call",
                }
            ],
        )
    ]
    if completion is not None:
        messages.append(completion)

    with pytest.raises(CapabilityEvaluationError, match="root call|ToolMessage"):
        capability_runner.recorded_root_tool_trace(messages)


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
        == "sha256:0101008f258b63e40b23e55e653e79c09d5dd94856a916bcb8bc384ec4863676"
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


def test_capability_taskset_rejects_more_than_the_bounded_task_count() -> None:
    dataset = load_capability_taskset(TASKSET_PATH)
    value = dataset.as_dict()
    template = copy.deepcopy(value["tasks"][0])
    value["tasks"] = []
    for index in range(33):
        task = copy.deepcopy(template)
        task["task_id"] = f"task-{index:02d}"
        value["tasks"].append(task)

    with pytest.raises(
        CapabilityEvaluationError,
        match="cannot contain more than 32 tasks",
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
    assert combined.estimated_generation_cost_usd_micros > 0
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
    assert all(record["content_tree_sha"] == CONTENT_TREE_SHA for record in records)
    assert all(
        record["resolved_general_purpose_enabled"] is False for record in records
    )
    assert all(
        "SummarizationMiddleware" in record["resolved_excluded_middleware"]
        for record in records
    )
    assert all(
        "- general-purpose:" not in record["task_description"] for record in records
    )

    quickjs_only = [
        record
        for record in records
        if record["arm_id"] == "quickjs-on_subagents-off"
        and record["task_id"] == "quickjs-ranked-list-overlap"
    ]
    assert quickjs_only
    assert all(
        all(
            surface == frozenset({QUICKJS_TOOL_NAME})
            for surface in record["bound_tool_names"]
        )
        for record in quickjs_only
    )

    baseline_combined_arm = next(
        record
        for record in records
        if record["arm_id"] == "quickjs-on_subagents-on"
        and record["task_id"] == "baseline-citation-shape"
    )
    assert all(
        surface == frozenset() for surface in baseline_combined_arm["bound_tool_names"]
    )

    combined = next(
        record
        for record in records
        if record["arm_id"] == "quickjs-on_subagents-on"
        and record["task_id"] == "combined-metric-evidence"
    )
    child_surface = frozenset({"keyword_search", "read_post"})
    assert any(
        surface == frozenset({QUICKJS_TOOL_NAME, "task"})
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
    quickjs_only_result = by_task_and_arm[
        ("quickjs-on_subagents-off", "quickjs-ranked-list-overlap")
    ]
    assert [
        (event.message_index, event.phase, event.tool_name)
        for event in quickjs_only_result.root_tool_trace
    ] == [(1, "call", "eval"), (2, "completion", "eval")]
    combined_result = by_task_and_arm[
        ("quickjs-on_subagents-on", "combined-metric-evidence")
    ]
    assert combined_result.budget.quickjs_calls > 0
    assert combined_result.budget.task_calls == 1
    assert combined_result.delegated_tool_calls == 1
    assert combined_result.budget.tool_calls == (
        combined_result.budget.quickjs_calls
        + combined_result.budget.task_calls
        + combined_result.delegated_tool_calls
    )
    assert combined_result.delegated_subagent_types == ("evidence-checker",)
    assert [
        (event.message_index, event.phase, event.tool_name)
        for event in combined_result.root_tool_trace
    ] == [
        (1, "call", "eval"),
        (2, "completion", "eval"),
        (3, "call", "task"),
        (4, "completion", "task"),
    ]
    assert all(
        task.root_tool_trace == ()
        for arm in run.arms
        for task in arm.tasks
        if task.task_id == "baseline-citation-shape"
    )
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
    assert "SYNTHETIC PROVIDER-FREE EVIDENCE ONLY" in report
    assert "does not satisfy P4.5 acceptance" in report
    assert "synthetic-provider-free" in report
    assert "intentionally excluded from the retrieval leaderboard" in report
    assert "QuickJS" in report
    assert "Subagents" in report
    verified = verify_capability_run_directory(
        first.directory,
        dataset=first_run.dataset,
    )
    assert verified.result_digest == first.result_digest
    assert verified.run == first_run


def test_capability_artifact_verifier_rejects_manifest_consistent_trace_forgery(
    tmp_path: Path,
) -> None:
    run = _run()
    artifacts = write_capability_artifacts(run, output_root=tmp_path)
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["root_tool_trace"][0]["tool_name"] = "write_file"
    task["root_tool_trace"][1]["tool_name"] = "write_file"
    run_payload = canonical_json_bytes(value)
    artifacts.run_json.write_bytes(run_payload)

    manifest = json.loads(artifacts.result_manifest.read_bytes())
    run_record = next(
        record for record in manifest["files"] if record["path"] == "run.json"
    )
    run_record["bytes"] = len(run_payload)
    run_record["sha256"] = json_checksum(run_payload)
    manifest["result_digest"] = capability_runner._result_digest(manifest["files"])
    artifacts.result_manifest.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(CapabilityEvaluationError, match="non-allowlisted"):
        verify_capability_run_directory(
            artifacts.directory,
            dataset=run.dataset,
        )


def test_synthetic_capability_artifacts_cannot_be_relabelled_as_provider_backed(
    tmp_path: Path,
) -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    value["evidence_status"] = CAPABILITY_PROVIDER_EVIDENCE_STATUS
    with pytest.raises(
        CapabilityEvaluationError,
        match="local provider evidence requires the exact reviewed OpenAI identity",
    ):
        parse_capability_run(value, dataset=run.dataset)

    artifacts = write_capability_artifacts(run, output_root=tmp_path)
    manifest = json.loads(artifacts.result_manifest.read_bytes())
    manifest["evidence_status"] = CAPABILITY_PROVIDER_EVIDENCE_STATUS
    artifacts.result_manifest.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(
        CapabilityEvaluationError,
        match="manifest evidence differs from the run",
    ):
        verify_capability_run_directory(
            artifacts.directory,
            dataset=run.dataset,
        )


def test_local_provider_evidence_has_a_distinct_unattested_report_tier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProviderCacheExecutor(DeterministicCapabilityExecutor):
        async def execute(self, context):
            observation = await super().execute(context)
            return replace(observation, cache_mode=OPENAI_CAPABILITY_CACHE_MODE)

    monkeypatch.setattr(
        capability_runner,
        "_reviewed_provider_executor_type",
        lambda: ProviderCacheExecutor,
    )
    dataset = load_capability_taskset(TASKSET_PATH)
    run = _run_dataset(
        dataset,
        executor=ProviderCacheExecutor(),
        identity=PROVIDER_IDENTITY,
        evidence_status=CAPABILITY_PROVIDER_EVIDENCE_STATUS,
    )
    artifacts = write_capability_artifacts(run, output_root=tmp_path)
    report = artifacts.report_markdown.read_text(encoding="utf-8")
    run_value = run.as_dict()
    assert run_value["cost_accounting"] == {
        "excluded_request_billing": [
            {
                "billing_status": "provider-pricing-undocumented",
                "endpoint": "/responses/input_tokens",
                "included_in_generation_cost_ceiling": False,
                "maximum_request_count": (
                    FIXED_POLICY.max_model_calls
                    * PROVIDER_IDENTITY.max_attempts
                    * len(dataset.tasks)
                    * len(CAPABILITY_ARMS)
                ),
            }
        ],
        "generation_cost_ceiling_usd_micros": (
            PROVIDER_IDENTITY.max_generation_cost_usd_micros
        ),
        "scope": "generation-token-usage-only",
    }
    assert "PROVIDER-BACKED LOCAL EVIDENCE; UNATTESTED" in report
    assert CAPABILITY_PROVIDER_EVIDENCE_STATUS in report
    assert "cannot enable a public capability" in report
    assert "Explicit experiment cost ceiling" not in report
    assert "Explicit generation-token cost ceiling" in report
    assert "/responses/input_tokens" in report
    assert "outside the generation-token ceiling" in report
    assert (
        verify_capability_run_directory(
            artifacts.directory,
            dataset=dataset,
        ).run
        == run
    )


def test_synthetic_executor_cannot_claim_the_exact_live_provider_identity() -> None:
    with pytest.raises(
        CapabilityEvaluationError,
        match="requires the exact reviewed executor implementation",
    ):
        _run_dataset(
            _task_subset("baseline-citation-shape"),
            identity=PROVIDER_IDENTITY,
            evidence_status=CAPABILITY_PROVIDER_EVIDENCE_STATUS,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda accounting: accounting.__setitem__("scope", "provider-wide"),
        lambda accounting: accounting["excluded_request_billing"].clear(),
        lambda accounting: accounting["excluded_request_billing"][0].__setitem__(
            "endpoint",
            "/responses/forged-count",
        ),
        lambda accounting: accounting["excluded_request_billing"][0].__setitem__(
            "included_in_generation_cost_ceiling",
            True,
        ),
        lambda accounting: accounting["excluded_request_billing"][0].__setitem__(
            "maximum_request_count",
            65,
        ),
    ],
    ids=[
        "scope",
        "missing-exclusion",
        "endpoint",
        "included-flag",
        "request-bound",
    ],
)
def test_provider_cost_accounting_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    class ProviderCacheExecutor(DeterministicCapabilityExecutor):
        async def execute(self, context):
            observation = await super().execute(context)
            return replace(observation, cache_mode=OPENAI_CAPABILITY_CACHE_MODE)

    monkeypatch.setattr(
        capability_runner,
        "_reviewed_provider_executor_type",
        lambda: ProviderCacheExecutor,
    )
    dataset = load_capability_taskset(TASKSET_PATH)
    run = _run_dataset(
        dataset,
        executor=ProviderCacheExecutor(),
        identity=PROVIDER_IDENTITY,
        evidence_status=CAPABILITY_PROVIDER_EVIDENCE_STATUS,
    )
    value = copy.deepcopy(run.as_dict())
    mutate(value["cost_accounting"])

    with pytest.raises(CapabilityEvaluationError, match="scoped contract"):
        parse_capability_run(value, dataset=dataset)


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("executor_id", "tests:forged-openai-executor@1"),
        ("model_id", "openai:gpt-5.6-luna-forged"),
        ("provider_contract", "openai-responses:forged-provider-free-executor"),
        ("max_attempts", 2),
        ("cache_mode", "disabled"),
        ("uncached_input_usd_micros_per_million_tokens", 1),
        ("cache_read_input_usd_micros_per_million_tokens", 1),
        ("cache_write_input_usd_micros_per_million_tokens", 1),
        ("output_usd_micros_per_million_tokens", 1),
    ),
)
def test_local_provider_evidence_rejects_forged_identity_fields(
    field: str,
    forged_value: object,
) -> None:
    with pytest.raises(
        CapabilityEvaluationError,
        match="local provider evidence requires the exact reviewed OpenAI identity",
    ):
        _run_dataset(
            _task_subset("baseline-citation-shape"),
            identity=replace(PROVIDER_IDENTITY, **{field: forged_value}),
            evidence_status=CAPABILITY_PROVIDER_EVIDENCE_STATUS,
        )


def test_capability_runner_stays_provider_independent_and_paid_cli_stays_local() -> (
    None
):
    runner_path = REPO_ROOT / "eval" / "src" / "blogeval" / "capability_runner.py"
    cli_path = REPO_ROOT / "eval" / "src" / "blogeval" / "cli.py"

    def imported_modules(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.add(node.module)
        return modules

    assert imported_modules(runner_path).isdisjoint(
        {"anthropic", "langchain_anthropic"}
    )
    assert "blogeval.capability_openai" in imported_modules(cli_path)
    workflow_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    )
    assert "capability-sweep" not in workflow_source
    assert "capability-openai" not in workflow_source


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
    ("delegated_subagent_types", "message"),
    [
        (["general-purpose"], "evidence-checker delegation differs"),
        ([], "recorded subagent types differ"),
        (
            ["evidence-checker", "evidence-checker"],
            "recorded subagent types differ",
        ),
    ],
    ids=["wrong-specialist", "missing-record", "duplicate-delegation"],
)
def test_recorded_subagent_type_mutations_fail_closed(
    delegated_subagent_types: list[str],
    message: str,
) -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task_record = next(
        task
        for arm in value["arms"]
        if arm["arm"]["arm_id"] == "quickjs-on_subagents-on"
        for task in arm["tasks"]
        if task["task_id"] == "combined-metric-evidence"
    )
    task_record["delegated_subagent_types"] = delegated_subagent_types

    with pytest.raises(CapabilityEvaluationError, match=message):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_two_quickjs_calls_for_one_required_task() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    trace = task["root_tool_trace"]
    duplicate_pair = copy.deepcopy(trace[:2])
    for event in duplicate_pair:
        event["tool_call_id"] += "-duplicate"
    task["root_tool_trace"] = [*trace[:2], *duplicate_pair, *trace[2:]]
    for message_index, event in enumerate(task["root_tool_trace"], start=1):
        event["message_index"] = message_index
    task["budget"]["quickjs_calls"] = 2
    task["budget"]["tool_calls"] = 3

    with pytest.raises(CapabilityEvaluationError, match="QuickJS activity"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_task_before_quickjs_chronology() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    trace = task["root_tool_trace"]
    task["root_tool_trace"] = [trace[2], trace[3], trace[0], trace[1]]
    for message_index, event in enumerate(task["root_tool_trace"], start=1):
        event["message_index"] = message_index

    with pytest.raises(CapabilityEvaluationError, match="exact capability chronology"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_parallel_quickjs_and_task_in_one_ai_message() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    trace = task["root_tool_trace"]
    task["root_tool_trace"] = [trace[0], trace[2], trace[1], trace[3]]
    for event, message_index in zip(
        task["root_tool_trace"],
        (1, 1, 2, 3),
        strict=True,
    ):
        event["message_index"] = message_index

    with pytest.raises(CapabilityEvaluationError, match="exact capability chronology"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_required_quickjs_without_completion() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["root_tool_trace"].pop(1)

    with pytest.raises(CapabilityEvaluationError, match="without a ToolMessage"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_quickjs_for_a_nonrequired_task() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="baseline-citation-shape",
    )
    task["root_tool_trace"] = [
        {
            "message_index": 1,
            "phase": "call",
            "tool_call_id": "forged-quickjs-call",
            "tool_name": "eval",
        },
        {
            "message_index": 2,
            "phase": "completion",
            "tool_call_id": "forged-quickjs-call",
            "tool_name": "eval",
        },
    ]
    task["budget"]["quickjs_calls"] = 1
    task["budget"]["tool_calls"] = 1

    with pytest.raises(CapabilityEvaluationError, match="QuickJS activity"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_allowlist_external_root_call_trace() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["root_tool_trace"][0]["tool_name"] = "write_file"
    task["root_tool_trace"][1]["tool_name"] = "write_file"

    with pytest.raises(CapabilityEvaluationError, match="non-allowlisted"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_root_tool_trace_shape_forgery() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["root_tool_trace"][0]["forged"] = True

    with pytest.raises(CapabilityEvaluationError, match="unexpected object shape"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_tool_call_ledger_sum_mismatch() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["budget"]["tool_calls"] = 1

    with pytest.raises(CapabilityEvaluationError, match="undercounts"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_forged_delegated_tool_count() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["delegated_tool_calls"] += 1

    with pytest.raises(CapabilityEvaluationError, match="derived scoring"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_subagent_without_child_tool_activity() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-on_subagents-on",
        task_id="combined-metric-evidence",
    )
    task["budget"]["tool_calls"] = 2
    task["delegated_tool_calls"] = 0
    next(
        arm
        for arm in value["arms"]
        if arm["arm"]["arm_id"] == "quickjs-on_subagents-on"
    )["metrics"]["tool_calls"] -= 1

    with pytest.raises(CapabilityEvaluationError, match="without delegated child"):
        parse_capability_run(value, dataset=run.dataset)


def test_recorded_run_rejects_delegated_tool_count_without_task() -> None:
    run = _run()
    value = copy.deepcopy(run.as_dict())
    task = _recorded_task(
        value,
        arm_id="quickjs-off_subagents-off",
        task_id="baseline-citation-shape",
    )
    task["budget"]["tool_calls"] = 1
    task["delegated_tool_calls"] = 1
    next(
        arm
        for arm in value["arms"]
        if arm["arm"]["arm_id"] == "quickjs-off_subagents-off"
    )["metrics"]["tool_calls"] += 1

    with pytest.raises(CapabilityEvaluationError, match="non-allowlisted root"):
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
                "estimated_generation_cost_usd_micros",
                True,
            ),
            "estimated_generation_cost_usd_micros must be a non-negative integer",
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
            "complete provider-native usage buckets",
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
        (
            lambda value: value["arms"][0]["tasks"][0]["budget"].__setitem__(
                "elapsed_ms",
                FIXED_POLICY.max_elapsed_seconds * 1_000,
            ),
            "exceeds or differs from its RunBudgetPolicy",
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
        "elapsed-at-exclusive-deadline",
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


@pytest.mark.parametrize(
    "changes",
    [
        {"max_generation_cost_usd_micros": 25_000_001},
        {"uncached_input_usd_micros_per_million_tokens": 0},
        {"output_usd_micros_per_million_tokens": 0},
        {"cache_read_input_usd_micros_per_million_tokens": 0},
        {"cache_write_input_usd_micros_per_million_tokens": 0},
        {"output_usd_micros_per_million_tokens": 100_000_001},
    ],
    ids=[
        "experiment-cap",
        "uncached-input-zero",
        "output-zero",
        "cache-read-zero",
        "cache-write-zero",
        "price-cap",
    ],
)
def test_executor_identity_rejects_unbounded_or_zero_pricing(
    changes: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match="executor identity is malformed"):
        replace(FIXED_IDENTITY, **changes)


@pytest.mark.parametrize(
    ("identity", "policy", "message"),
    [
        (
            replace(FIXED_IDENTITY, max_generation_cost_usd_micros=1),
            FIXED_POLICY,
            "worst-case generation-token cost exceeds",
        ),
        (
            FIXED_IDENTITY,
            replace(FIXED_POLICY, max_task_calls=3),
            "RunBudgetPolicy exceeds the capability experiment maxima",
        ),
    ],
    ids=["whole-sweep-cost", "policy-maxima"],
)
def test_runner_rejects_unsafe_experiment_inputs_before_executor_invocation(
    identity: CapabilityExecutorIdentity,
    policy: RunBudgetPolicy,
    message: str,
) -> None:
    class InvocationSpy:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, context):
            del context
            self.calls += 1
            raise AssertionError("unsafe experiment reached the executor")

    executor = InvocationSpy()
    with pytest.raises(CapabilityEvaluationError, match=message):
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=executor,
                executor_identity=identity,
                budget_policy=policy,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )
    assert executor.calls == 0


def test_runner_deep_isolates_tasks_and_rejects_executor_mutation() -> None:
    class MutatingExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, context):
            self.calls += 1
            evidence = context.task.inputs["evidence"]
            assert isinstance(evidence, list)
            evidence.append({"doc_id": "mutated", "statement": "mutated"})
            await _record_provider_usage(context)
            return _observation(context)

    dataset = _task_subset("baseline-citation-shape")
    executor = MutatingExecutor()
    with pytest.raises(
        CapabilityEvaluationError,
        match="executor mutated its isolated capability task",
    ):
        asyncio.run(
            run_capability_experiment(
                dataset=dataset,
                executor=executor,
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )

    assert executor.calls == 1
    original_evidence = dataset.tasks[0].inputs["evidence"]
    assert isinstance(original_evidence, list)
    assert len(original_evidence) == 1


def test_runner_rejects_incomplete_provider_usage_without_executor_accounting() -> None:
    class IncompleteUsageExecutor:
        async def execute(self, context):
            await _record_provider_usage(context, complete=False)
            return _observation(context)

    dataset = load_capability_taskset(TASKSET_PATH)
    with pytest.raises(
        CapabilityEvaluationError,
        match="incomplete provider-native usage",
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


def test_disabled_cache_mode_rejects_nonzero_provider_cache_buckets() -> None:
    class CacheDriftExecutor:
        async def execute(self, context):
            await _record_provider_usage(context)
            return replace(_observation(context), cache_mode="disabled")

    with pytest.raises(
        CapabilityEvaluationError,
        match="disabled cache mode cannot record cache token buckets",
    ):
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=CacheDriftExecutor(),
                executor_identity=replace(
                    FIXED_IDENTITY,
                    cache_mode="disabled",
                    max_attempts=1,
                ),
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


def test_runner_reports_only_typed_executor_diagnostics_and_final_budget_counts() -> (
    None
):
    class DiagnosticFailureExecutor:
        async def execute(self, context):
            await _record_provider_usage(context)
            private = RuntimeError("private provider body and prompt")
            diagnostic = CapabilityExecutorDiagnosticError(
                phase="graph_invoke",
                reason_code="provider",
                root_tool_events=("call:other",),
            )
            raise diagnostic from private

    with pytest.raises(CapabilityEvaluationError) as raised:
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=DiagnosticFailureExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )

    message = str(raised.value)
    assert "phase=graph_invoke" in message
    assert "reason=provider" in message
    assert "budget_counts=model:1,tool:0,quickjs:0,task:0" in message
    assert "root_tool_events=call:other" in message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "private" not in _exception_graph_text(raised.value)
    assert "private" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize(
    ("failure_point", "expected_reason"),
    [("input_count", "input_count"), ("provider", "provider")],
)
def test_runner_preserves_diagnostic_when_failed_provider_usage_is_incomplete(
    failure_point: str,
    expected_reason: str,
) -> None:
    class FailedProviderExecutor:
        async def execute(self, context):
            async def count_input(_request):
                if failure_point == "input_count":
                    raise InputTokenCountError("private serialized prompt")
                return 3

            middleware = RunBudgetMiddleware(
                context.budget,
                depth=0,
                allow_subagents=False,
                allowed_subagents=frozenset(),
                input_token_counter=count_input,
                model_provider="openai",
                expected_response_models=frozenset({"gpt-5.6-luna"}),
            )
            request = ModelRequest(
                model=FakeMessagesListChatModel(
                    responses=[AIMessage(content="unused")]
                ),
                messages=[],
                tools=[],
            )

            async def failed_provider(_request):
                raise OpenAIError("private provider response body")

            try:
                await middleware.awrap_model_call(request, failed_provider)
            except BaseException as error:
                raise CapabilityExecutorDiagnosticError(
                    phase="graph_invoke",
                    reason_code=capability_openai._executor_reason_code(error),
                ) from None

    with pytest.raises(CapabilityEvaluationError) as raised:
        asyncio.run(
            run_capability_experiment(
                dataset=_task_subset("baseline-citation-shape"),
                executor=FailedProviderExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )

    rendered = "".join(traceback.format_exception(raised.value))
    assert f"reason={expected_reason}" in rendered
    assert "budget_counts=model:1,tool:0,quickjs:0,task:0" in rendered
    assert "incomplete provider-native usage" not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "private" not in _exception_graph_text(raised.value)
    assert "private" not in rendered


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
    assert baseline.estimated_generation_cost_usd_micros == 47
    quarter_micro_identity = replace(
        FIXED_IDENTITY,
        uncached_input_usd_micros_per_million_tokens=250_000,
        output_usd_micros_per_million_tokens=250_000,
        cache_read_input_usd_micros_per_million_tokens=250_000,
        cache_write_input_usd_micros_per_million_tokens=250_000,
    )
    assert (
        capability_runner._estimated_generation_cost(
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
            if not context.arm.quickjs_enabled:
                return CapabilityObservation(
                    status="failed",
                    answer=None,
                    citations=(),
                    persistence_empty=True,
                    cache_mode=FIXED_IDENTITY.cache_mode,
                    failure_code="capability_unavailable",
                )
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


def test_missing_peer_capability_allows_an_early_structured_unavailable_stop() -> None:
    class EarlyUnavailableExecutor(DeterministicCapabilityExecutor):
        async def execute(self, context):
            if (
                context.arm.arm_id == "quickjs-on_subagents-off"
                and context.task.task_id == "combined-metric-evidence"
            ):
                await _record_provider_usage(context)
                return CapabilityObservation(
                    status="failed",
                    answer=None,
                    citations=(),
                    persistence_empty=True,
                    cache_mode=FIXED_IDENTITY.cache_mode,
                    failure_code="capability_unavailable",
                )
            return await super().execute(context)

    run = _run_dataset(
        _task_subset("combined-metric-evidence"),
        executor=EarlyUnavailableExecutor(),
    )
    partial = next(
        arm for arm in run.arms if arm.arm.arm_id == "quickjs-on_subagents-off"
    ).tasks[0]

    assert partial.failure_code == "capability_unavailable"
    assert partial.budget.quickjs_calls == 0


def test_missing_capability_rejects_executor_error_as_availability_evidence() -> None:
    class ExecutorErrorOnMissing(DeterministicCapabilityExecutor):
        async def execute(self, context):
            if (
                context.arm.arm_id == "quickjs-off_subagents-off"
                and context.task.task_id == "combined-metric-evidence"
            ):
                await _record_provider_usage(context)
                return CapabilityObservation(
                    status="failed",
                    answer=None,
                    citations=(),
                    persistence_empty=True,
                    cache_mode=FIXED_IDENTITY.cache_mode,
                    failure_code="executor_error",
                )
            return await super().execute(context)

    with pytest.raises(
        CapabilityEvaluationError,
        match="structured capability availability",
    ):
        _run_dataset(
            _task_subset("combined-metric-evidence"),
            executor=ExecutorErrorOnMissing(),
        )


def test_unrequired_disabled_capabilities_cannot_be_reported_as_unavailable() -> None:
    class FalseUnavailableExecutor:
        async def execute(self, context):
            await _record_provider_usage(context)
            return CapabilityObservation(
                status="failed",
                answer=None,
                citations=(),
                persistence_empty=True,
                cache_mode=FIXED_IDENTITY.cache_mode,
                failure_code="capability_unavailable",
            )

    with pytest.raises(
        CapabilityEvaluationError,
        match="structured capability availability",
    ):
        _run_dataset(
            _task_subset("baseline-citation-shape"),
            executor=FalseUnavailableExecutor(),
        )


def test_provider_free_executor_cannot_forge_a_generic_root_tool_call() -> None:
    class GenericRootToolExecutor(DeterministicCapabilityExecutor):
        async def execute(self, context):
            observation = await super().execute(context)
            context.budget.reserve_tool()
            return observation

    with pytest.raises(
        CapabilityEvaluationError,
        match="non-allowlisted root tool call",
    ):
        _run_dataset(
            _task_subset("baseline-citation-shape"),
            executor=GenericRootToolExecutor(),
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
