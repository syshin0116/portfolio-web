from __future__ import annotations

import asyncio
import copy
import hashlib
from pathlib import Path

import pytest
from agent.capabilities.budget import RunBudget, RunBudgetPolicy
from agent.retrieval.protocol import DocId

from blogeval.capability_runner import (
    CAPABILITY_ARMS,
    CapabilityEvaluationError,
    CapabilityExecutorIdentity,
    CapabilityObservation,
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
    model_id="fixture:structured-agent-v1",
    random_seed=20260728,
    input_usd_micros_per_million_tokens=3_000_000,
    output_usd_micros_per_million_tokens=15_000_000,
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


class DeterministicCapabilityExecutor:
    """No-provider executor that spends through the production RunBudget API."""

    async def execute(self, context):
        budget = context.budget
        budget.reserve_tool()
        root_model = budget.reserve_model(estimated_input_tokens=0)
        budget.settle_model(root_model, actual_tokens=12)
        input_tokens = 10
        output_tokens = 2

        needs_quickjs = context.task.task_id in {
            "combined-metric-evidence",
            "quickjs-ranked-list-overlap",
        }
        needs_subagent = context.task.task_id in {
            "combined-metric-evidence",
            "subagent-evidence-verification",
        }
        if needs_quickjs and context.arm.quickjs_enabled:
            reservation = budget.reserve_quickjs()
            budget.settle_quickjs(reservation, actual_output_bytes=64)
        if needs_subagent and context.arm.subagents_enabled:
            reservation = budget.reserve_task(depth=1)
            try:
                child_model = budget.reserve_model(
                    estimated_input_tokens=0,
                    task_reservation=reservation,
                )
                budget.settle_model(child_model, actual_tokens=6)
                input_tokens += 5
                output_tokens += 1
            finally:
                budget.finish_task(reservation)

        unavailable = (
            needs_quickjs
            and not context.arm.quickjs_enabled
            or needs_subagent
            and not context.arm.subagents_enabled
        )
        if unavailable:
            return CapabilityObservation(
                status="failed",
                answer=None,
                citations=(),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                failure_code="capability_unavailable",
            )
        return CapabilityObservation(
            status="completed",
            answer=_ANSWERS[context.task.task_id],
            citations=_CITATIONS[context.task.task_id],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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


def _run():
    dataset = load_capability_taskset(
        TASKSET_PATH,
        content_tree_sha=CONTENT_TREE_SHA,
    )
    return asyncio.run(
        run_capability_experiment(
            dataset=dataset,
            executor=DeterministicCapabilityExecutor(),
            executor_identity=FIXED_IDENTITY,
            budget_policy=FIXED_POLICY,
            provenance=FIXED_PROVENANCE,
            clock_ns=DeterministicClock(),
            budget_factory=_budget_factory,
        )
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
    assert combined.total_tokens == combined.input_tokens + combined.output_tokens
    assert combined.estimated_cost_usd_micros > 0
    assert all(
        task.budget.quickjs_in_flight == 0
        and task.budget.tasks_in_flight == 0
        and not task.budget.exhausted
        for task in run.arms[-1].tasks
    )


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


def test_runner_rejects_executor_token_usage_that_does_not_match_runbudget() -> None:
    class TokenDriftExecutor:
        async def execute(self, context):
            reservation = context.budget.reserve_model(estimated_input_tokens=0)
            context.budget.settle_model(reservation, actual_tokens=12)
            return CapabilityObservation(
                status="completed",
                answer=_ANSWERS[context.task.task_id],
                citations=_CITATIONS[context.task.task_id],
                input_tokens=10,
                output_tokens=1,
            )

    dataset = load_capability_taskset(TASKSET_PATH)
    with pytest.raises(CapabilityEvaluationError, match="token usage differs"):
        asyncio.run(
            run_capability_experiment(
                dataset=dataset,
                executor=TokenDriftExecutor(),
                executor_identity=FIXED_IDENTITY,
                budget_policy=FIXED_POLICY,
                provenance=FIXED_PROVENANCE,
                clock_ns=DeterministicClock(),
                budget_factory=_budget_factory,
            )
        )


def test_enabled_arm_without_capability_activity_is_rejected_as_incomplete() -> None:
    class CapabilityIgnoringExecutor:
        async def execute(self, context):
            reservation = context.budget.reserve_model(estimated_input_tokens=0)
            context.budget.settle_model(reservation, actual_tokens=12)
            input_tokens = 10
            output_tokens = 2
            if context.arm.subagents_enabled:
                task = context.budget.reserve_task(depth=1)
                try:
                    child = context.budget.reserve_model(
                        estimated_input_tokens=0,
                        task_reservation=task,
                    )
                    context.budget.settle_model(child, actual_tokens=6)
                    input_tokens += 5
                    output_tokens += 1
                finally:
                    context.budget.finish_task(task)
            return CapabilityObservation(
                status="completed",
                answer=_ANSWERS[context.task.task_id],
                citations=_CITATIONS[context.task.task_id],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

    dataset = load_capability_taskset(TASKSET_PATH)
    with pytest.raises(
        CapabilityEvaluationError,
        match="did not exercise enabled QuickJS",
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
                    input_tokens=observation.input_tokens,
                    output_tokens=observation.output_tokens,
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
