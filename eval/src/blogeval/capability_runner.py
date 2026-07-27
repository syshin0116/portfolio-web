"""Reproducible QuickJS × dynamic-subagent capability experiments.

Capability experiments are deliberately separate from retrieval evaluation.  The
runner owns the four factorial arms, one real :class:`RunBudget` per task, strict
scoring, and immutable report bytes.  A caller supplies the provider/agent executor;
tests use a deterministic no-provider executor.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Protocol, cast

from agent.capabilities.budget import (
    BudgetSnapshot,
    RunBudget,
    RunBudgetPolicy,
)
from agent.capabilities.subagents import validate_capability_config
from agent.retrieval.protocol import DocId

from blogeval.jsonio import (
    StrictJsonError,
    canonical_json_bytes,
    json_checksum,
    load_canonical_json,
)
from blogeval.provenance import (
    ProvenanceError,
    RunProvenance,
    collect_run_provenance,
    parse_run_provenance,
)

CAPABILITY_TASKSET_SCHEMA = "blogeval-capability-taskset-v1"
CAPABILITY_RUN_SCHEMA = "blogeval-capability-run-v1"
CAPABILITY_RUNNER_ID = "blogeval.capability_runner@1"
CAPABILITY_MANIFEST_SCHEMA = "blogeval-capability-result-manifest-v1"
CAPABILITY_RESULT_DIGEST_SCHEMA = "blogeval-capability-result-digest-v1"
CAPABILITY_RESULT_FILES = ("capability-report.md", "run.json")
_TASK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PROMPT_BYTES = 16_000
_RATE_SCALE = 1_000_000
_FAILURE_CODES = frozenset(
    {
        "budget_exhausted",
        "capability_unavailable",
        "executor_error",
        "invalid_result",
        "timeout",
    }
)


class CapabilityEvaluationError(ValueError):
    """Capability inputs or observations are incomplete, malformed, or unsafe."""


@dataclass(frozen=True, slots=True)
class CapabilityArm:
    """One fixed cell in the QuickJS × subagent factorial design."""

    arm_id: str
    quickjs_enabled: bool
    subagents_enabled: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "quickjs_enabled": self.quickjs_enabled,
            "subagents_enabled": self.subagents_enabled,
        }


CAPABILITY_ARMS = (
    CapabilityArm("quickjs-off_subagents-off", False, False),
    CapabilityArm("quickjs-off_subagents-on", False, True),
    CapabilityArm("quickjs-on_subagents-off", True, False),
    CapabilityArm("quickjs-on_subagents-on", True, True),
)


@dataclass(frozen=True, slots=True)
class CapabilityTask:
    task_id: str
    prompt: str
    inputs: Mapping[str, object]
    expected_answer: Mapping[str, object]
    expected_citations: tuple[DocId, ...]
    tags: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "expected": {
                "answer": dict(self.expected_answer),
                "citations": [str(value) for value in self.expected_citations],
            },
            "inputs": dict(self.inputs),
            "prompt": self.prompt,
            "tags": list(self.tags),
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityTaskSet:
    dataset_id: str
    content_tree_sha: str
    description: str
    label_status: str
    tasks: tuple[CapabilityTask, ...]
    checksum: str

    def as_dict(self) -> dict[str, object]:
        return {
            "content_tree_sha": self.content_tree_sha,
            "dataset_id": self.dataset_id,
            "description": self.description,
            "label_status": self.label_status,
            "schema": CAPABILITY_TASKSET_SCHEMA,
            "tasks": [task.as_dict() for task in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class CapabilityExecutorIdentity:
    """Stable execution identity and exact model pricing for one sweep."""

    executor_id: str
    model_id: str
    random_seed: int
    input_usd_micros_per_million_tokens: int
    output_usd_micros_per_million_tokens: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.executor_id, str)
            or not self.executor_id
            or self.executor_id != self.executor_id.strip()
            or not isinstance(self.model_id, str)
            or not self.model_id
            or self.model_id != self.model_id.strip()
            or not _is_non_negative_int(self.random_seed)
            or not _is_non_negative_int(self.input_usd_micros_per_million_tokens)
            or not _is_non_negative_int(self.output_usd_micros_per_million_tokens)
        ):
            raise ValueError("capability executor identity is malformed")

    def as_dict(self) -> dict[str, object]:
        return {
            "executor_id": self.executor_id,
            "model_id": self.model_id,
            "pricing": {
                "input_usd_micros_per_million_tokens": (
                    self.input_usd_micros_per_million_tokens
                ),
                "output_usd_micros_per_million_tokens": (
                    self.output_usd_micros_per_million_tokens
                ),
            },
            "random_seed": self.random_seed,
        }


@dataclass(frozen=True, slots=True)
class CapabilityObservation:
    """Structured executor output; raw provider errors never enter a report."""

    status: str
    answer: Mapping[str, object] | None
    citations: tuple[DocId, ...]
    input_tokens: int
    output_tokens: int
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityExecutionContext:
    """Server-owned arm and budget passed to one executor invocation."""

    arm: CapabilityArm
    task: CapabilityTask
    budget: RunBudget
    random_seed: int
    run_config: Mapping[str, object]


class CapabilityExecutor(Protocol):
    async def execute(
        self,
        context: CapabilityExecutionContext,
    ) -> CapabilityObservation:
        """Execute exactly one task and return a complete structured observation."""


@dataclass(frozen=True, slots=True)
class CapabilityTaskResult:
    task_id: str
    status: str
    answer: Mapping[str, object] | None
    citations: tuple[DocId, ...]
    task_success: bool
    citation_correct: bool
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd_micros: int
    failure_code: str | None
    budget: BudgetSnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "answer": None if self.answer is None else dict(self.answer),
            "budget": asdict(self.budget),
            "citation_correct": self.citation_correct,
            "citations": [str(value) for value in self.citations],
            "estimated_cost_usd_micros": self.estimated_cost_usd_micros,
            "failure_code": self.failure_code,
            "input_tokens": self.input_tokens,
            "latency_ms": self.latency_ms,
            "output_tokens": self.output_tokens,
            "status": self.status,
            "task_id": self.task_id,
            "task_success": self.task_success,
        }


@dataclass(frozen=True, slots=True)
class CapabilityArmMetrics:
    task_count: int
    task_success_count: int
    task_success_rate_ppm: int
    citation_correct_count: int
    citation_correctness_rate_ppm: int
    failed_task_count: int
    latency_ms_total: int
    latency_ms_mean_milli: int
    model_calls: int
    tool_calls: int
    quickjs_calls: int
    task_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd_micros: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityArmResult:
    arm: CapabilityArm
    metrics: CapabilityArmMetrics
    tasks: tuple[CapabilityTaskResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm.as_dict(),
            "metrics": self.metrics.as_dict(),
            "tasks": [task.as_dict() for task in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class CapabilityRun:
    run_id: str
    dataset: CapabilityTaskSet
    executor: CapabilityExecutorIdentity
    budget_policy: RunBudgetPolicy
    arms: tuple[CapabilityArmResult, ...]
    provenance: RunProvenance

    def as_dict(self) -> dict[str, object]:
        return {
            "arms": [arm.as_dict() for arm in self.arms],
            "budget_policy": asdict(self.budget_policy),
            "dataset": {
                "checksum": self.dataset.checksum,
                "content_tree_sha": self.dataset.content_tree_sha,
                "dataset_id": self.dataset.dataset_id,
                "label_status": self.dataset.label_status,
                "task_count": len(self.dataset.tasks),
            },
            "executor": self.executor.as_dict(),
            "provenance": self.provenance.as_dict(),
            "run_id": self.run_id,
            "runner": CAPABILITY_RUNNER_ID,
            "schema": CAPABILITY_RUN_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class CapabilityArtifacts:
    directory: Path
    run_json: Path
    report_markdown: Path
    result_manifest: Path
    result_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedCapabilityRun:
    run: CapabilityRun
    result_digest: str


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _mapping(
    value: object,
    *,
    location: str,
    keys: frozenset[str] | None = None,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CapabilityEvaluationError(f"{location} must be a JSON object")
    result = cast(Mapping[str, object], value)
    if keys is not None and set(result) != keys:
        raise CapabilityEvaluationError(f"{location} has an unexpected object shape")
    return result


def _array(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        raise CapabilityEvaluationError(f"{location} must be an array")
    return value


def _text(value: object, *, location: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityEvaluationError(
            f"{location} must be a non-empty trimmed string"
        )
    return value


def _integer(value: object, *, location: str) -> int:
    if not _is_non_negative_int(value):
        raise CapabilityEvaluationError(f"{location} must be a non-negative integer")
    return cast(int, value)


def _boolean(value: object, *, location: str) -> bool:
    if not isinstance(value, bool):
        raise CapabilityEvaluationError(f"{location} must be a boolean")
    return value


def _canonical_object(value: object, *, location: str) -> Mapping[str, object]:
    result = _mapping(value, location=location)
    try:
        canonical_json_bytes(result)
    except (StrictJsonError, UnicodeEncodeError) as exc:
        raise CapabilityEvaluationError(f"{location} is not portable JSON") from exc
    return dict(result)


def _doc_ids(value: object, *, location: str) -> tuple[DocId, ...]:
    result: list[DocId] = []
    for index, item in enumerate(_array(value, location=location)):
        try:
            result.append(DocId(item))
        except (TypeError, ValueError) as exc:
            raise CapabilityEvaluationError(
                f"{location}[{index}] is not a valid DocId"
            ) from exc
    values = tuple(result)
    if values != tuple(sorted(set(values), key=str)):
        raise CapabilityEvaluationError(f"{location} must contain sorted unique DocIds")
    return values


def parse_capability_taskset(
    value: object,
    *,
    checksum: str,
) -> CapabilityTaskSet:
    """Parse a strict, versioned capability task manifest."""

    raw = _mapping(
        value,
        location="capability task-set",
        keys=frozenset(
            {
                "content_tree_sha",
                "dataset_id",
                "description",
                "label_status",
                "schema",
                "tasks",
            }
        ),
    )
    if raw["schema"] != CAPABILITY_TASKSET_SCHEMA:
        raise CapabilityEvaluationError("capability task-set schema is unsupported")
    dataset_id = _text(raw["dataset_id"], location="task-set.dataset_id")
    content_tree_sha = _text(
        raw["content_tree_sha"],
        location="task-set.content_tree_sha",
    )
    if _SHA1_RE.fullmatch(content_tree_sha) is None:
        raise CapabilityEvaluationError(
            "task-set.content_tree_sha must be a full git tree SHA"
        )
    description = _text(raw["description"], location="task-set.description")
    label_status = _text(
        raw["label_status"],
        location="task-set.label_status",
    )
    if label_status != "synthetic-only":
        raise CapabilityEvaluationError(
            "capability task-set v1 cannot claim reviewed labels"
        )
    raw_tasks = _array(raw["tasks"], location="task-set.tasks")
    if not raw_tasks:
        raise CapabilityEvaluationError("capability task-set must not be empty")

    tasks: list[CapabilityTask] = []
    for index, task_value in enumerate(raw_tasks):
        location = f"task-set.tasks[{index}]"
        task = _mapping(
            task_value,
            location=location,
            keys=frozenset({"expected", "inputs", "prompt", "tags", "task_id"}),
        )
        task_id = _text(task["task_id"], location=f"{location}.task_id")
        if _TASK_ID_RE.fullmatch(task_id) is None:
            raise CapabilityEvaluationError(
                f"{location}.task_id must be lower kebab-case"
            )
        prompt = _text(task["prompt"], location=f"{location}.prompt")
        try:
            prompt_bytes = len(prompt.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise CapabilityEvaluationError(
                f"{location}.prompt is not valid UTF-8"
            ) from exc
        if prompt_bytes > _MAX_PROMPT_BYTES:
            raise CapabilityEvaluationError(f"{location}.prompt is too large")
        inputs = _canonical_object(task["inputs"], location=f"{location}.inputs")
        expected = _mapping(
            task["expected"],
            location=f"{location}.expected",
            keys=frozenset({"answer", "citations"}),
        )
        expected_answer = _canonical_object(
            expected["answer"],
            location=f"{location}.expected.answer",
        )
        expected_citations = _doc_ids(
            expected["citations"],
            location=f"{location}.expected.citations",
        )
        tags = tuple(
            _text(item, location=f"{location}.tags[{tag_index}]")
            for tag_index, item in enumerate(
                _array(task["tags"], location=f"{location}.tags")
            )
        )
        if not tags or tags != tuple(sorted(set(tags))):
            raise CapabilityEvaluationError(
                f"{location}.tags must be sorted, unique, and non-empty"
            )
        tasks.append(
            CapabilityTask(
                task_id=task_id,
                prompt=prompt,
                inputs=inputs,
                expected_answer=expected_answer,
                expected_citations=expected_citations,
                tags=tags,
            )
        )

    task_ids = tuple(task.task_id for task in tasks)
    if task_ids != tuple(sorted(set(task_ids))):
        raise CapabilityEvaluationError(
            "capability tasks must be sorted by unique task_id"
        )
    if _SHA256_RE.fullmatch(checksum) is None:
        raise CapabilityEvaluationError("capability task-set checksum is malformed")
    return CapabilityTaskSet(
        dataset_id=dataset_id,
        content_tree_sha=content_tree_sha,
        description=description,
        label_status=label_status,
        tasks=tuple(tasks),
        checksum=checksum,
    )


def load_capability_taskset(
    path: Path,
    *,
    content_tree_sha: str | None = None,
) -> CapabilityTaskSet:
    """Load canonical JSON and optionally bind it to the current content tree."""

    try:
        value, payload = load_canonical_json(path)
    except StrictJsonError as exc:
        raise CapabilityEvaluationError(str(exc)) from exc
    taskset = parse_capability_taskset(value, checksum=json_checksum(payload))
    if content_tree_sha is not None and taskset.content_tree_sha != content_tree_sha:
        raise CapabilityEvaluationError(
            "capability task-set content tree differs from the requested tree"
        )
    return taskset


def build_capability_graph(
    context: CapabilityExecutionContext,
    *,
    runtime: Any,
    model: Any,
):
    """Compile the actual topology-stable agent graph for one server-owned arm."""

    from agent.graph import create_graph

    return create_graph(
        runtime=runtime,
        config=context.run_config,
        budget=context.budget,
        model=model,
        quickjs_enabled=context.arm.quickjs_enabled,
        subagents_enabled=context.arm.subagents_enabled,
    )


def _derived_seed(
    identity: CapabilityExecutorIdentity,
    arm: CapabilityArm,
    task: CapabilityTask,
) -> int:
    payload = canonical_json_bytes(
        {
            "arm_id": arm.arm_id,
            "executor_id": identity.executor_id,
            "random_seed": identity.random_seed,
            "task_id": task.task_id,
        }
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], byteorder="big")


def _thread_id(
    identity: CapabilityExecutorIdentity,
    arm: CapabilityArm,
    task: CapabilityTask,
) -> str:
    payload = (
        f"{identity.executor_id}\0{identity.random_seed}\0{arm.arm_id}\0{task.task_id}"
    ).encode()
    return f"capability-{hashlib.sha256(payload).hexdigest()[:32]}"


def _estimated_cost(
    identity: CapabilityExecutorIdentity,
    *,
    input_tokens: int,
    output_tokens: int,
) -> int:
    numerator = (
        input_tokens * identity.input_usd_micros_per_million_tokens
        + output_tokens * identity.output_usd_micros_per_million_tokens
    )
    return (numerator + 999_999) // 1_000_000


def _validate_observation(
    observation: object,
    *,
    arm: CapabilityArm,
    task: CapabilityTask,
    latency_ms: int,
    budget: BudgetSnapshot,
    identity: CapabilityExecutorIdentity,
) -> CapabilityTaskResult:
    if not isinstance(observation, CapabilityObservation):
        raise CapabilityEvaluationError(
            f"executor returned no structured observation for {arm.arm_id}/{task.task_id}"
        )
    if observation.status not in {"completed", "failed"}:
        raise CapabilityEvaluationError("capability observation status is unsupported")
    input_tokens = _integer(
        observation.input_tokens,
        location="observation.input_tokens",
    )
    output_tokens = _integer(
        observation.output_tokens,
        location="observation.output_tokens",
    )
    citations = observation.citations
    if (
        not isinstance(citations, tuple)
        or not all(isinstance(value, DocId) for value in citations)
        or citations != tuple(sorted(set(citations), key=str))
    ):
        raise CapabilityEvaluationError(
            "observation citations must be sorted unique DocIds"
        )
    if not budget.policy_id or budget.policy_id != budget.policy_id.strip():
        raise CapabilityEvaluationError("budget snapshot policy is malformed")
    if budget.quickjs_in_flight != 0 or budget.tasks_in_flight != 0:
        raise CapabilityEvaluationError(
            "executor returned with an unsettled capability reservation"
        )
    if budget.charged_tokens != input_tokens + output_tokens:
        raise CapabilityEvaluationError(
            "executor token usage differs from the shared RunBudget ledger"
        )
    if not arm.quickjs_enabled and (
        budget.quickjs_calls != 0 or budget.quickjs_output_bytes != 0
    ):
        raise CapabilityEvaluationError("QuickJS was used in a disabled arm")
    if not arm.subagents_enabled and budget.task_calls != 0:
        raise CapabilityEvaluationError("subagents were used in a disabled arm")
    if budget.quickjs_calls == 0 and budget.quickjs_output_bytes != 0:
        raise CapabilityEvaluationError(
            "QuickJS output was charged without an execution"
        )

    if observation.status == "completed":
        if observation.answer is None or observation.failure_code is not None:
            raise CapabilityEvaluationError(
                "completed observation requires an answer and no failure code"
            )
        answer = _canonical_object(
            observation.answer,
            location="observation.answer",
        )
    else:
        if (
            observation.answer is not None
            or citations
            or observation.failure_code not in _FAILURE_CODES
        ):
            raise CapabilityEvaluationError(
                "failed observation must be redacted and use an allowlisted code"
            )
        answer = None
    if budget.exhausted != (observation.failure_code == "budget_exhausted"):
        raise CapabilityEvaluationError(
            "budget exhaustion and structured failure code disagree"
        )

    task_success = observation.status == "completed" and canonical_json_bytes(
        answer
    ) == canonical_json_bytes(task.expected_answer)
    citation_correct = (
        observation.status == "completed" and citations == task.expected_citations
    )
    return CapabilityTaskResult(
        task_id=task.task_id,
        status=observation.status,
        answer=answer,
        citations=citations,
        task_success=task_success,
        citation_correct=citation_correct,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd_micros=_estimated_cost(
            identity,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        failure_code=observation.failure_code,
        budget=budget,
    )


def _summarize_arm(
    arm: CapabilityArm,
    tasks: Sequence[CapabilityTaskResult],
) -> CapabilityArmMetrics:
    task_count = len(tasks)
    if task_count < 1:
        raise CapabilityEvaluationError(f"arm {arm.arm_id} contains no task results")
    quickjs_calls = sum(task.budget.quickjs_calls for task in tasks)
    task_calls = sum(task.budget.task_calls for task in tasks)
    if arm.quickjs_enabled and quickjs_calls < 1:
        raise CapabilityEvaluationError(
            f"arm {arm.arm_id} did not exercise enabled QuickJS"
        )
    if arm.subagents_enabled and task_calls < 1:
        raise CapabilityEvaluationError(
            f"arm {arm.arm_id} did not exercise enabled subagents"
        )
    successes = sum(task.task_success for task in tasks)
    correct_citations = sum(task.citation_correct for task in tasks)
    latency_total = sum(task.latency_ms for task in tasks)
    input_tokens = sum(task.input_tokens for task in tasks)
    output_tokens = sum(task.output_tokens for task in tasks)
    return CapabilityArmMetrics(
        task_count=task_count,
        task_success_count=successes,
        task_success_rate_ppm=(successes * _RATE_SCALE) // task_count,
        citation_correct_count=correct_citations,
        citation_correctness_rate_ppm=(correct_citations * _RATE_SCALE) // task_count,
        failed_task_count=sum(task.status == "failed" for task in tasks),
        latency_ms_total=latency_total,
        latency_ms_mean_milli=(latency_total * 1_000) // task_count,
        model_calls=sum(task.budget.model_calls for task in tasks),
        tool_calls=sum(task.budget.tool_calls for task in tasks),
        quickjs_calls=quickjs_calls,
        task_calls=task_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd_micros=sum(task.estimated_cost_usd_micros for task in tasks),
    )


def _run_id(
    *,
    dataset: CapabilityTaskSet,
    executor: CapabilityExecutorIdentity,
    policy: RunBudgetPolicy,
    provenance: RunProvenance,
) -> str:
    payload = {
        "arms": [arm.as_dict() for arm in CAPABILITY_ARMS],
        "budget_policy": asdict(policy),
        "dataset": {
            "checksum": dataset.checksum,
            "content_tree_sha": dataset.content_tree_sha,
            "dataset_id": dataset.dataset_id,
            "label_status": dataset.label_status,
            "task_count": len(dataset.tasks),
        },
        "executor": executor.as_dict(),
        "provenance": provenance.as_dict(),
        "runner": CAPABILITY_RUNNER_ID,
        "schema": CAPABILITY_RUN_SCHEMA,
    }
    return json_checksum(canonical_json_bytes(payload))


async def run_capability_experiment(
    *,
    dataset: CapabilityTaskSet,
    executor: CapabilityExecutor,
    executor_identity: CapabilityExecutorIdentity,
    budget_policy: RunBudgetPolicy,
    provenance: RunProvenance | None = None,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    budget_factory: Callable[[RunBudgetPolicy], RunBudget] = RunBudget,
) -> CapabilityRun:
    """Run all four arms or fail without returning a partial experiment."""

    if not isinstance(dataset, CapabilityTaskSet) or not dataset.tasks:
        raise CapabilityEvaluationError("a parsed non-empty task-set is required")
    if not isinstance(executor_identity, CapabilityExecutorIdentity):
        raise CapabilityEvaluationError("executor identity is required")
    if not isinstance(budget_policy, RunBudgetPolicy):
        raise CapabilityEvaluationError("RunBudgetPolicy is required")
    measured_provenance = provenance or collect_run_provenance()

    arms: list[CapabilityArmResult] = []
    for arm in CAPABILITY_ARMS:
        task_results: list[CapabilityTaskResult] = []
        for task in dataset.tasks:
            budget = budget_factory(budget_policy)
            if not isinstance(budget, RunBudget) or budget.policy != budget_policy:
                raise CapabilityEvaluationError(
                    "budget factory must return RunBudget with the requested policy"
                )
            run_config: dict[str, object] = {
                "configurable": {
                    "thread_id": _thread_id(executor_identity, arm, task),
                }
            }
            validate_capability_config(run_config)
            context = CapabilityExecutionContext(
                arm=arm,
                task=task,
                budget=budget,
                random_seed=_derived_seed(executor_identity, arm, task),
                run_config=run_config,
            )
            started_ns = clock_ns()
            if not _is_non_negative_int(started_ns):
                raise CapabilityEvaluationError("experiment clock is malformed")
            try:
                observation = await executor.execute(context)
            except Exception as exc:
                raise CapabilityEvaluationError(
                    f"executor failed before a complete observation for "
                    f"{arm.arm_id}/{task.task_id}"
                ) from exc
            finished_ns = clock_ns()
            if not _is_non_negative_int(finished_ns) or finished_ns < started_ns:
                raise CapabilityEvaluationError("experiment clock moved backwards")
            latency_ms = (finished_ns - started_ns + 500_000) // 1_000_000
            task_results.append(
                _validate_observation(
                    observation,
                    arm=arm,
                    task=task,
                    latency_ms=latency_ms,
                    budget=budget.snapshot(),
                    identity=executor_identity,
                )
            )
        metrics = _summarize_arm(arm, task_results)
        arms.append(
            CapabilityArmResult(
                arm=arm,
                metrics=metrics,
                tasks=tuple(task_results),
            )
        )
    if tuple(result.arm for result in arms) != CAPABILITY_ARMS:
        raise CapabilityEvaluationError("capability experiment is missing a fixed arm")
    return CapabilityRun(
        run_id=_run_id(
            dataset=dataset,
            executor=executor_identity,
            policy=budget_policy,
            provenance=measured_provenance,
        ),
        dataset=dataset,
        executor=executor_identity,
        budget_policy=budget_policy,
        arms=tuple(arms),
        provenance=measured_provenance,
    )


def _parse_executor(value: object) -> CapabilityExecutorIdentity:
    raw = _mapping(
        value,
        location="run.executor",
        keys=frozenset({"executor_id", "model_id", "pricing", "random_seed"}),
    )
    pricing = _mapping(
        raw["pricing"],
        location="run.executor.pricing",
        keys=frozenset(
            {
                "input_usd_micros_per_million_tokens",
                "output_usd_micros_per_million_tokens",
            }
        ),
    )
    try:
        return CapabilityExecutorIdentity(
            executor_id=_text(
                raw["executor_id"],
                location="run.executor.executor_id",
            ),
            model_id=_text(raw["model_id"], location="run.executor.model_id"),
            random_seed=_integer(
                raw["random_seed"],
                location="run.executor.random_seed",
            ),
            input_usd_micros_per_million_tokens=_integer(
                pricing["input_usd_micros_per_million_tokens"],
                location=("run.executor.pricing.input_usd_micros_per_million_tokens"),
            ),
            output_usd_micros_per_million_tokens=_integer(
                pricing["output_usd_micros_per_million_tokens"],
                location=("run.executor.pricing.output_usd_micros_per_million_tokens"),
            ),
        )
    except ValueError as exc:
        raise CapabilityEvaluationError(str(exc)) from exc


def _parse_policy(value: object) -> RunBudgetPolicy:
    expected_keys = frozenset(RunBudgetPolicy.__dataclass_fields__)
    raw = _mapping(
        value,
        location="run.budget_policy",
        keys=expected_keys,
    )
    values: dict[str, object] = {
        "policy_id": _text(
            raw["policy_id"],
            location="run.budget_policy.policy_id",
        )
    }
    for key in sorted(expected_keys - {"policy_id"}):
        values[key] = _integer(
            raw[key],
            location=f"run.budget_policy.{key}",
        )
    try:
        return RunBudgetPolicy(**values)
    except (TypeError, ValueError) as exc:
        raise CapabilityEvaluationError("run budget policy is invalid") from exc


def _parse_budget(
    value: object,
    *,
    location: str,
    policy: RunBudgetPolicy,
) -> BudgetSnapshot:
    raw = _mapping(
        value,
        location=location,
        keys=frozenset(BudgetSnapshot.__dataclass_fields__),
    )
    snapshot = BudgetSnapshot(
        policy_id=_text(raw["policy_id"], location=f"{location}.policy_id"),
        model_calls=_integer(
            raw["model_calls"],
            location=f"{location}.model_calls",
        ),
        tool_calls=_integer(raw["tool_calls"], location=f"{location}.tool_calls"),
        quickjs_calls=_integer(
            raw["quickjs_calls"],
            location=f"{location}.quickjs_calls",
        ),
        quickjs_in_flight=_integer(
            raw["quickjs_in_flight"],
            location=f"{location}.quickjs_in_flight",
        ),
        quickjs_output_bytes=_integer(
            raw["quickjs_output_bytes"],
            location=f"{location}.quickjs_output_bytes",
        ),
        task_calls=_integer(raw["task_calls"], location=f"{location}.task_calls"),
        tasks_in_flight=_integer(
            raw["tasks_in_flight"],
            location=f"{location}.tasks_in_flight",
        ),
        charged_tokens=_integer(
            raw["charged_tokens"],
            location=f"{location}.charged_tokens",
        ),
        elapsed_ms=_integer(raw["elapsed_ms"], location=f"{location}.elapsed_ms"),
        exhausted=_boolean(raw["exhausted"], location=f"{location}.exhausted"),
    )
    limits = {
        "model_calls": policy.max_model_calls,
        "tool_calls": policy.max_tool_calls,
        "quickjs_calls": policy.max_quickjs_calls,
        "quickjs_in_flight": policy.max_quickjs_in_flight,
        "quickjs_output_bytes": policy.max_quickjs_total_output_bytes,
        "task_calls": policy.max_task_calls,
        "tasks_in_flight": policy.max_tasks_in_flight,
        "charged_tokens": policy.max_total_tokens,
        "elapsed_ms": policy.max_elapsed_seconds * 1_000,
    }
    if snapshot.policy_id != policy.policy_id or any(
        getattr(snapshot, field) > maximum for field, maximum in limits.items()
    ):
        raise CapabilityEvaluationError(
            f"{location} exceeds or differs from its RunBudgetPolicy"
        )
    return snapshot


def _parse_task_result(
    value: object,
    *,
    location: str,
    arm: CapabilityArm,
    task: CapabilityTask,
    policy: RunBudgetPolicy,
    identity: CapabilityExecutorIdentity,
) -> CapabilityTaskResult:
    raw = _mapping(
        value,
        location=location,
        keys=frozenset(
            {
                "answer",
                "budget",
                "citation_correct",
                "citations",
                "estimated_cost_usd_micros",
                "failure_code",
                "input_tokens",
                "latency_ms",
                "output_tokens",
                "status",
                "task_id",
                "task_success",
            }
        ),
    )
    if raw["task_id"] != task.task_id:
        raise CapabilityEvaluationError(f"{location}.task_id is missing or reordered")
    citations = _doc_ids(raw["citations"], location=f"{location}.citations")
    status = _text(raw["status"], location=f"{location}.status")
    failure_code = raw["failure_code"]
    if failure_code is not None and not isinstance(failure_code, str):
        raise CapabilityEvaluationError(f"{location}.failure_code is malformed")
    observation = CapabilityObservation(
        status=status,
        answer=(
            None
            if raw["answer"] is None
            else _canonical_object(raw["answer"], location=f"{location}.answer")
        ),
        citations=citations,
        input_tokens=_integer(
            raw["input_tokens"],
            location=f"{location}.input_tokens",
        ),
        output_tokens=_integer(
            raw["output_tokens"],
            location=f"{location}.output_tokens",
        ),
        failure_code=cast(str | None, failure_code),
    )
    result = _validate_observation(
        observation,
        arm=arm,
        task=task,
        latency_ms=_integer(raw["latency_ms"], location=f"{location}.latency_ms"),
        budget=_parse_budget(
            raw["budget"],
            location=f"{location}.budget",
            policy=policy,
        ),
        identity=identity,
    )
    if (
        raw["task_success"] is not result.task_success
        or raw["citation_correct"] is not result.citation_correct
        or raw["estimated_cost_usd_micros"] != result.estimated_cost_usd_micros
    ):
        raise CapabilityEvaluationError(f"{location} derived scoring is inconsistent")
    return result


def parse_capability_run(
    value: object,
    *,
    dataset: CapabilityTaskSet,
) -> CapabilityRun:
    """Parse and fully recompute a recorded four-arm capability run."""

    raw = _mapping(
        value,
        location="capability run",
        keys=frozenset(
            {
                "arms",
                "budget_policy",
                "dataset",
                "executor",
                "provenance",
                "run_id",
                "runner",
                "schema",
            }
        ),
    )
    if raw["schema"] != CAPABILITY_RUN_SCHEMA or raw["runner"] != CAPABILITY_RUNNER_ID:
        raise CapabilityEvaluationError("capability run schema/runner is unsupported")
    expected_dataset = {
        "checksum": dataset.checksum,
        "content_tree_sha": dataset.content_tree_sha,
        "dataset_id": dataset.dataset_id,
        "label_status": dataset.label_status,
        "task_count": len(dataset.tasks),
    }
    if raw["dataset"] != expected_dataset:
        raise CapabilityEvaluationError(
            "capability run dataset identity differs from the supplied task-set"
        )
    identity = _parse_executor(raw["executor"])
    policy = _parse_policy(raw["budget_policy"])
    try:
        provenance = parse_run_provenance(raw["provenance"])
    except ProvenanceError as exc:
        raise CapabilityEvaluationError(str(exc)) from exc

    raw_arms = _array(raw["arms"], location="run.arms")
    if len(raw_arms) != len(CAPABILITY_ARMS):
        raise CapabilityEvaluationError("capability run must contain exactly four arms")
    arms: list[CapabilityArmResult] = []
    for arm_index, (arm_value, expected_arm) in enumerate(
        zip(raw_arms, CAPABILITY_ARMS, strict=True)
    ):
        location = f"run.arms[{arm_index}]"
        arm_record = _mapping(
            arm_value,
            location=location,
            keys=frozenset({"arm", "metrics", "tasks"}),
        )
        if arm_record["arm"] != expected_arm.as_dict():
            raise CapabilityEvaluationError(
                f"{location}.arm is missing, reordered, or duplicated"
            )
        raw_tasks = _array(arm_record["tasks"], location=f"{location}.tasks")
        if len(raw_tasks) != len(dataset.tasks):
            raise CapabilityEvaluationError(
                f"{location} does not contain every task exactly once"
            )
        tasks = tuple(
            _parse_task_result(
                task_value,
                location=f"{location}.tasks[{task_index}]",
                arm=expected_arm,
                task=task,
                policy=policy,
                identity=identity,
            )
            for task_index, (task_value, task) in enumerate(
                zip(raw_tasks, dataset.tasks, strict=True)
            )
        )
        metrics = _summarize_arm(expected_arm, tasks)
        if arm_record["metrics"] != metrics.as_dict():
            raise CapabilityEvaluationError(
                f"{location}.metrics differs from recomputed task observations"
            )
        arms.append(
            CapabilityArmResult(
                arm=expected_arm,
                metrics=metrics,
                tasks=tasks,
            )
        )

    expected_run_id = _run_id(
        dataset=dataset,
        executor=identity,
        policy=policy,
        provenance=provenance,
    )
    if raw["run_id"] != expected_run_id:
        raise CapabilityEvaluationError(
            "capability run ID differs from its canonical experiment inputs"
        )
    return CapabilityRun(
        run_id=expected_run_id,
        dataset=dataset,
        executor=identity,
        budget_policy=policy,
        arms=tuple(arms),
        provenance=provenance,
    )


def _markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _percent(ppm: int) -> str:
    whole, remainder = divmod(ppm, 10_000)
    return f"{whole}.{remainder // 100:02d}%"


def _usd(micros: int) -> str:
    whole, remainder = divmod(micros, 1_000_000)
    return f"${whole}.{remainder:06d}"


def _milliseconds(millis: int) -> str:
    whole, remainder = divmod(millis, 1_000)
    return f"{whole}.{remainder:03d} ms"


def render_capability_report(run: CapabilityRun) -> str:
    """Render a deterministic report that cannot be mistaken for a leaderboard."""

    lines = [
        f"# Capability 2×2 report: {_markdown(run.dataset.dataset_id)}",
        "",
        "> Agent-capability experiment only. This report is intentionally excluded "
        "from the retrieval leaderboard.",
        "",
        f"- Run ID: `{run.run_id}`",
        f"- Task-set checksum: `{run.dataset.checksum}`",
        f"- Label status: `{run.dataset.label_status}`",
        f"- Content tree: `{run.dataset.content_tree_sha}`",
        f"- Executor: `{_markdown(run.executor.executor_id)}`",
        f"- Model: `{_markdown(run.executor.model_id)}`",
        f"- Random seed: `{run.executor.random_seed}`",
        f"- Shared budget policy: `{_markdown(run.budget_policy.policy_id)}`",
        "",
        "## Arm summary",
        "",
        "| Arm | QuickJS | Subagents | Task success | Citation correctness | "
        "Mean latency | Model/tool/task calls | Tokens | Estimated cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in run.arms:
        metrics = arm.metrics
        lines.append(
            f"| `{arm.arm.arm_id}` | "
            f"{'on' if arm.arm.quickjs_enabled else 'off'} | "
            f"{'on' if arm.arm.subagents_enabled else 'off'} | "
            f"{metrics.task_success_count}/{metrics.task_count} "
            f"({_percent(metrics.task_success_rate_ppm)}) | "
            f"{metrics.citation_correct_count}/{metrics.task_count} "
            f"({_percent(metrics.citation_correctness_rate_ppm)}) | "
            f"{_milliseconds(metrics.latency_ms_mean_milli)} | "
            f"{metrics.model_calls}/{metrics.tool_calls}/{metrics.task_calls} | "
            f"{metrics.total_tokens} | "
            f"{_usd(metrics.estimated_cost_usd_micros)} |"
        )

    lines.extend(["", "## Per-task observations", ""])
    for arm in run.arms:
        lines.extend(
            [
                f"### `{arm.arm.arm_id}`",
                "",
                "| Task | Status | Success | Citations | Latency | "
                "Model/tool/QuickJS/task | Tokens | Cost |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for task in arm.tasks:
            lines.append(
                f"| `{task.task_id}` | {task.status} | "
                f"{'yes' if task.task_success else 'no'} | "
                f"{'correct' if task.citation_correct else 'incorrect'} | "
                f"{task.latency_ms} ms | "
                f"{task.budget.model_calls}/{task.budget.tool_calls}/"
                f"{task.budget.quickjs_calls}/{task.budget.task_calls} | "
                f"{task.input_tokens + task.output_tokens} | "
                f"{_usd(task.estimated_cost_usd_micros)} |"
            )
        lines.append("")
    lines.extend(
        [
            "Latency is monotonic elapsed time rounded to the nearest millisecond. "
            "Rates use integer parts-per-million; model cost is rounded up per task "
            "to the nearest micro-US-dollar from the recorded input/output pricing.",
            "",
            "The canonical source of record is `run.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def _result_inventory(payloads: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [
        {
            "bytes": len(payloads[path]),
            "path": path,
            "sha256": json_checksum(payloads[path]),
        }
        for path in CAPABILITY_RESULT_FILES
    ]


def _result_digest(files: Sequence[Mapping[str, object]]) -> str:
    return json_checksum(
        canonical_json_bytes(
            {
                "files": list(files),
                "schema": CAPABILITY_RESULT_DIGEST_SCHEMA,
            }
        )
    )


def _artifact_payloads(run: CapabilityRun) -> tuple[dict[str, bytes], bytes, str]:
    payloads = {
        "capability-report.md": render_capability_report(run).encode("utf-8"),
        "run.json": canonical_json_bytes(run.as_dict()),
    }
    files = _result_inventory(payloads)
    result_digest = _result_digest(files)
    manifest = canonical_json_bytes(
        {
            "files": files,
            "result_digest": result_digest,
            "schema": CAPABILITY_MANIFEST_SCHEMA,
        }
    )
    return payloads, manifest, result_digest


def _inventory(directory: Path) -> tuple[str, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise CapabilityEvaluationError(
            "capability result directory must be a real directory"
        )
    entries: list[str] = []
    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise CapabilityEvaluationError(
                f"capability result contains an unsupported entry: {entry.name}"
            )
        entries.append(entry.name)
    return tuple(sorted(entries))


def verify_capability_run_directory(
    directory: Path,
    *,
    dataset: CapabilityTaskSet,
) -> VerifiedCapabilityRun:
    """Verify exact inventory, canonical run data, scores, and report bytes."""

    expected_entries = tuple(sorted((*CAPABILITY_RESULT_FILES, "manifest.json")))
    if _inventory(directory) != expected_entries:
        raise CapabilityEvaluationError(
            "capability result directory file inventory mismatch"
        )
    try:
        manifest_value, _ = load_canonical_json(directory / "manifest.json")
    except StrictJsonError as exc:
        raise CapabilityEvaluationError(str(exc)) from exc
    manifest = _mapping(
        manifest_value,
        location="capability result manifest",
        keys=frozenset({"files", "result_digest", "schema"}),
    )
    if manifest["schema"] != CAPABILITY_MANIFEST_SCHEMA:
        raise CapabilityEvaluationError("unsupported capability result manifest schema")
    raw_files = _array(
        manifest["files"],
        location="capability result manifest.files",
    )
    if len(raw_files) != len(CAPABILITY_RESULT_FILES):
        raise CapabilityEvaluationError(
            "capability result manifest file set is incomplete"
        )
    files: list[Mapping[str, object]] = []
    payloads: dict[str, bytes] = {}
    for index, raw_file in enumerate(raw_files):
        location = f"capability result manifest.files[{index}]"
        record = _mapping(
            raw_file,
            location=location,
            keys=frozenset({"bytes", "path", "sha256"}),
        )
        path = record["path"]
        size = record["bytes"]
        checksum = record["sha256"]
        if path != CAPABILITY_RESULT_FILES[index]:
            raise CapabilityEvaluationError(
                "capability result manifest file set is reordered"
            )
        if (
            not _is_non_negative_int(size)
            or not isinstance(checksum, str)
            or _SHA256_RE.fullmatch(checksum) is None
        ):
            raise CapabilityEvaluationError(f"{location} is malformed")
        try:
            payload = (directory / cast(str, path)).read_bytes()
        except OSError as exc:
            raise CapabilityEvaluationError(
                f"cannot read capability result file {path}"
            ) from exc
        if len(payload) != size or json_checksum(payload) != checksum:
            raise CapabilityEvaluationError(
                f"capability result checksum/size mismatch: {path}"
            )
        files.append(record)
        payloads[cast(str, path)] = payload
    expected_digest = _result_digest(files)
    if manifest["result_digest"] != expected_digest:
        raise CapabilityEvaluationError(
            "capability result digest differs from its manifest"
        )
    try:
        run_value, run_payload = load_canonical_json(directory / "run.json")
    except StrictJsonError as exc:
        raise CapabilityEvaluationError(str(exc)) from exc
    if run_payload != payloads["run.json"]:
        raise CapabilityEvaluationError("capability run changed during verification")
    run = parse_capability_run(run_value, dataset=dataset)
    regenerated, _, regenerated_digest = _artifact_payloads(run)
    if regenerated_digest != expected_digest:
        raise CapabilityEvaluationError(
            "capability result differs from regenerated observations"
        )
    for path in CAPABILITY_RESULT_FILES:
        if payloads[path] != regenerated[path]:
            raise CapabilityEvaluationError(
                f"capability result projection does not regenerate: {path}"
            )
    return VerifiedCapabilityRun(run=run, result_digest=expected_digest)


def _write_fsynced(path: Path, payload: bytes) -> None:
    flags = (
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _exclusive_capability_lock(output_root: Path):
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".blogeval-capability-write.lock"
    if lock_path.is_symlink():
        raise CapabilityEvaluationError("capability result lock must not be a symlink")
    descriptor = os.open(
        lock_path,
        os.O_CREAT
        | os.O_RDWR
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CapabilityEvaluationError(
                "capability result lock must be a regular file"
            )
        flock(descriptor, LOCK_EX)
        yield
    finally:
        flock(descriptor, LOCK_UN)
        os.close(descriptor)


def write_capability_artifacts(
    run: CapabilityRun,
    *,
    output_root: Path,
) -> CapabilityArtifacts:
    """Atomically publish one complete capability report outside leaderboards."""

    run = parse_capability_run(run.as_dict(), dataset=run.dataset)
    capability_root = output_root / "capabilities"
    dataset_directory = capability_root / run.dataset.dataset_id
    run_slug = run.run_id.removeprefix("sha256:")
    directory = dataset_directory / run_slug
    payloads, manifest_payload, result_digest = _artifact_payloads(run)
    if output_root.is_symlink() or capability_root.is_symlink():
        raise CapabilityEvaluationError("capability result roots must not be symlinks")
    dataset_directory.mkdir(parents=True, exist_ok=True)
    if dataset_directory.is_symlink():
        raise CapabilityEvaluationError(
            "capability dataset result directory must not be a symlink"
        )
    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{run_slug}.staged-",
            dir=dataset_directory,
        )
    )
    try:
        for path, payload in payloads.items():
            _write_fsynced(staged / path, payload)
        _write_fsynced(staged / "manifest.json", manifest_payload)
        _fsync_directory(staged)
        with _exclusive_capability_lock(capability_root):
            if os.path.lexists(directory):
                verified = verify_capability_run_directory(
                    directory,
                    dataset=run.dataset,
                )
                if verified.result_digest != result_digest:
                    raise CapabilityEvaluationError(
                        "refusing to replace a non-identical capability result"
                    )
            else:
                try:
                    os.rename(staged, directory)
                except OSError as exc:
                    raise CapabilityEvaluationError(
                        "cannot atomically commit capability result directory"
                    ) from exc
                _fsync_directory(dataset_directory)
        return CapabilityArtifacts(
            directory=directory,
            run_json=directory / "run.json",
            report_markdown=directory / "capability-report.md",
            result_manifest=directory / "manifest.json",
            result_digest=result_digest,
        )
    finally:
        if staged.exists():
            shutil.rmtree(staged)


__all__ = [
    "CAPABILITY_ARMS",
    "CAPABILITY_RUNNER_ID",
    "CAPABILITY_RUN_SCHEMA",
    "CAPABILITY_TASKSET_SCHEMA",
    "CapabilityArm",
    "CapabilityArtifacts",
    "CapabilityEvaluationError",
    "CapabilityExecutionContext",
    "CapabilityExecutor",
    "CapabilityExecutorIdentity",
    "CapabilityObservation",
    "CapabilityRun",
    "CapabilityTask",
    "CapabilityTaskSet",
    "VerifiedCapabilityRun",
    "build_capability_graph",
    "load_capability_taskset",
    "parse_capability_run",
    "parse_capability_taskset",
    "render_capability_report",
    "run_capability_experiment",
    "verify_capability_run_directory",
    "write_capability_artifacts",
]
