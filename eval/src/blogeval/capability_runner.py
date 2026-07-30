"""Reproducible QuickJS × dynamic-subagent capability experiments.

Capability experiments are deliberately separate from retrieval evaluation. The runner
owns the four factorial arms, one real :class:`RunBudget` per attempt, strict scoring,
and immutable report bytes. A caller supplies the provider/agent executor; tests fake
only the provider while executing the production graph.
"""

from __future__ import annotations

import asyncio
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
from uuid import UUID, uuid5

from agent.capabilities.budget import (
    BudgetSnapshot,
    RunBudget,
    RunBudgetExceededError,
    RunBudgetPolicy,
    RunBudgetUnsettledError,
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
CAPABILITY_RUN_SCHEMA = "blogeval-capability-run-v2"
CAPABILITY_RUNNER_ID = "blogeval.capability_runner@2"
CAPABILITY_MANIFEST_SCHEMA = "blogeval-capability-result-manifest-v1"
CAPABILITY_RESULT_DIGEST_SCHEMA = "blogeval-capability-result-digest-v1"
CAPABILITY_RESULT_FILES = ("capability-report.md", "run.json")
_DATASET_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TASK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_DATASET_ID_BYTES = 128
_MAX_PROMPT_BYTES = 16_000
_RATE_SCALE = 1_000_000
_MAX_ATTEMPTS = 3
_CACHE_MODES = frozenset({"disabled", "anthropic-ephemeral-5m-recorded"})
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
    execution_id: str
    model_id: str
    random_seed: int
    max_attempts: int
    cache_mode: str
    uncached_input_usd_micros_per_million_tokens: int
    output_usd_micros_per_million_tokens: int
    cache_read_input_usd_micros_per_million_tokens: int
    cache_write_input_usd_micros_per_million_tokens: int

    def __post_init__(self) -> None:
        try:
            execution_uuid = UUID(self.execution_id)
        except (AttributeError, TypeError, ValueError):
            execution_uuid = None
        if (
            not isinstance(self.executor_id, str)
            or not self.executor_id
            or self.executor_id != self.executor_id.strip()
            or execution_uuid is None
            or execution_uuid.version != 4
            or str(execution_uuid) != self.execution_id
            or not isinstance(self.model_id, str)
            or not self.model_id
            or self.model_id != self.model_id.strip()
            or not _is_non_negative_int(self.random_seed)
            or not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 1 <= self.max_attempts <= _MAX_ATTEMPTS
            or not isinstance(self.cache_mode, str)
            or self.cache_mode not in _CACHE_MODES
            or not _is_non_negative_int(
                self.uncached_input_usd_micros_per_million_tokens
            )
            or not _is_non_negative_int(self.output_usd_micros_per_million_tokens)
            or not _is_non_negative_int(
                self.cache_read_input_usd_micros_per_million_tokens
            )
            or not _is_non_negative_int(
                self.cache_write_input_usd_micros_per_million_tokens
            )
        ):
            raise ValueError("capability executor identity is malformed")

    def as_dict(self) -> dict[str, object]:
        return {
            "cache_mode": self.cache_mode,
            "execution_id": self.execution_id,
            "executor_id": self.executor_id,
            "max_attempts": self.max_attempts,
            "model_id": self.model_id,
            "pricing": {
                "cache_read_input_usd_micros_per_million_tokens": (
                    self.cache_read_input_usd_micros_per_million_tokens
                ),
                "cache_write_input_usd_micros_per_million_tokens": (
                    self.cache_write_input_usd_micros_per_million_tokens
                ),
                "uncached_input_usd_micros_per_million_tokens": (
                    self.uncached_input_usd_micros_per_million_tokens
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
    persistence_empty: bool
    cache_mode: str
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityExecutionContext:
    """Server-owned arm and budget passed to one executor invocation."""

    arm: CapabilityArm
    task: CapabilityTask
    budget: RunBudget
    random_seed: int
    attempt_id: str
    attempt_number: int
    thread_id: str
    graph_run_id: UUID
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
    attempt_id: str
    attempt_number: int
    thread_id: str
    graph_run_id: str
    persistence_empty: bool
    cache_mode: str
    status: str
    answer: Mapping[str, object] | None
    citations: tuple[DocId, ...]
    task_success: bool
    citation_correct: bool
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_write_input_tokens: int
    estimated_cost_usd_micros: int
    failure_code: str | None
    budget: BudgetSnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "answer": None if self.answer is None else dict(self.answer),
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "budget": asdict(self.budget),
            "cache_mode": self.cache_mode,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "citation_correct": self.citation_correct,
            "citations": [str(value) for value in self.citations],
            "estimated_cost_usd_micros": self.estimated_cost_usd_micros,
            "failure_code": self.failure_code,
            "graph_run_id": self.graph_run_id,
            "input_tokens": self.input_tokens,
            "latency_ms": self.latency_ms,
            "output_tokens": self.output_tokens,
            "persistence_empty": self.persistence_empty,
            "status": self.status,
            "task_id": self.task_id,
            "task_success": self.task_success,
            "thread_id": self.thread_id,
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
    cache_read_input_tokens: int
    cache_write_input_tokens: int
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


def _optional_integer(value: object, *, location: str) -> int | None:
    if value is None:
        return None
    return _integer(value, location=location)


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
    if (
        _DATASET_ID_RE.fullmatch(dataset_id) is None
        or len(dataset_id.encode("utf-8")) > _MAX_DATASET_ID_BYTES
    ):
        raise CapabilityEvaluationError(
            "task-set.dataset_id must be bounded lower kebab-case"
        )
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
    if not isinstance(checksum, str) or _SHA256_RE.fullmatch(checksum) is None:
        raise CapabilityEvaluationError("capability task-set checksum is malformed")
    taskset = CapabilityTaskSet(
        dataset_id=dataset_id,
        content_tree_sha=content_tree_sha,
        description=description,
        label_status=label_status,
        tasks=tuple(tasks),
        checksum=checksum,
    )
    if json_checksum(canonical_json_bytes(taskset.as_dict())) != checksum:
        raise CapabilityEvaluationError(
            "capability task-set checksum differs from canonical task-set"
        )
    return taskset


def _validated_taskset(
    dataset: object,
    *,
    location: str,
) -> CapabilityTaskSet:
    """Reparse a task-set instance instead of trusting direct construction."""

    if not isinstance(dataset, CapabilityTaskSet):
        raise CapabilityEvaluationError(f"{location} must be a capability task-set")
    try:
        value = dataset.as_dict()
    except (AttributeError, TypeError, ValueError) as exc:
        raise CapabilityEvaluationError(
            f"{location} is not a canonical capability task-set"
        ) from exc
    parsed = parse_capability_taskset(value, checksum=dataset.checksum)
    if parsed != dataset:
        raise CapabilityEvaluationError(
            f"{location} is not a canonical capability task-set"
        )
    return parsed


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
    input_token_counter: Any | None = None,
    quickjs_middleware: Any | None = None,
):
    """Compile the actual topology-stable agent graph for one server-owned arm."""

    from agent.graph import create_graph

    return create_graph(
        runtime=runtime,
        config=context.run_config,
        budget=context.budget,
        model=model,
        input_token_counter=input_token_counter,
        quickjs_enabled=context.arm.quickjs_enabled,
        dynamic_subagents_enabled=context.arm.subagents_enabled,
        quickjs_middleware=quickjs_middleware,
    )


def _derived_seed(
    identity: CapabilityExecutorIdentity,
    arm: CapabilityArm,
    task: CapabilityTask,
    *,
    attempt_number: int,
) -> int:
    payload = canonical_json_bytes(
        {
            "arm_id": arm.arm_id,
            "executor_id": identity.executor_id,
            "execution_id": identity.execution_id,
            "random_seed": identity.random_seed,
            "task_id": task.task_id,
            "attempt_number": attempt_number,
        }
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], byteorder="big")


def _attempt_identity(
    identity: CapabilityExecutorIdentity,
    arm: CapabilityArm,
    task: CapabilityTask,
    *,
    attempt_number: int,
) -> tuple[str, str, UUID]:
    payload = canonical_json_bytes(
        {
            "arm_id": arm.arm_id,
            "attempt_number": attempt_number,
            "execution_id": identity.execution_id,
            "executor_id": identity.executor_id,
            "task_id": task.task_id,
        }
    )
    digest = hashlib.sha256(payload).hexdigest()
    attempt_id = f"capability-attempt-{digest[:32]}"
    thread_id = f"capability-thread-{digest[32:]}"
    graph_run_id = uuid5(UUID(identity.execution_id), digest)
    return attempt_id, thread_id, graph_run_id


_COUNTERBALANCED_ARM_INDEXES = (
    (0, 1, 3, 2),
    (1, 2, 0, 3),
    (2, 3, 1, 0),
    (3, 0, 2, 1),
)


def _counterbalanced_arms(
    identity: CapabilityExecutorIdentity,
    *,
    task_index: int,
) -> tuple[CapabilityArm, ...]:
    row = (identity.random_seed + task_index) % len(_COUNTERBALANCED_ARM_INDEXES)
    return tuple(CAPABILITY_ARMS[index] for index in _COUNTERBALANCED_ARM_INDEXES[row])


def _task_capabilities(task: CapabilityTask) -> tuple[bool, bool]:
    quickjs_required = "quickjs" in task.tags or "combined" in task.tags
    subagents_required = "subagents" in task.tags or "combined" in task.tags
    return quickjs_required, subagents_required


def _estimated_cost(
    identity: CapabilityExecutorIdentity,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int,
    cache_write_input_tokens: int,
) -> int:
    numerator = (
        input_tokens * identity.uncached_input_usd_micros_per_million_tokens
        + output_tokens * identity.output_usd_micros_per_million_tokens
        + cache_read_input_tokens
        * identity.cache_read_input_usd_micros_per_million_tokens
        + cache_write_input_tokens
        * identity.cache_write_input_usd_micros_per_million_tokens
    )
    return (numerator + 999_999) // 1_000_000


def _validate_observation(
    observation: object,
    *,
    arm: CapabilityArm,
    task: CapabilityTask,
    attempt_id: str,
    attempt_number: int,
    thread_id: str,
    graph_run_id: UUID,
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
    if observation.persistence_empty is not True:
        raise CapabilityEvaluationError(
            "executor did not verify empty attempt persistence"
        )
    if observation.cache_mode != identity.cache_mode:
        raise CapabilityEvaluationError(
            "executor cache mode differs from the recorded execution identity"
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
    if budget.finalized is not True:
        raise CapabilityEvaluationError(
            "capability result requires a terminal RunBudget snapshot"
        )
    if (
        budget.model_reservations_in_flight != 0
        or budget.quickjs_in_flight != 0
        or budget.tasks_in_flight != 0
    ):
        raise CapabilityEvaluationError(
            "executor returned with an unsettled capability reservation"
        )
    provider_buckets = (
        budget.provider_input_tokens,
        budget.provider_output_tokens,
        budget.provider_cache_read_input_tokens,
        budget.provider_cache_write_input_tokens,
    )
    if budget.provider_usage_complete is not True or any(
        not _is_non_negative_int(value) for value in provider_buckets
    ):
        raise CapabilityEvaluationError(
            "capability result requires complete Anthropic provider usage buckets"
        )
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens = cast(
        tuple[int, int, int, int],
        provider_buckets,
    )
    if (
        budget.model_calls < 1
        or budget.charged_tokens
        != input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    ):
        raise CapabilityEvaluationError(
            "Anthropic provider usage differs from the shared RunBudget ledger"
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
    quickjs_required, subagents_required = _task_capabilities(task)
    expected_quickjs = arm.quickjs_enabled and quickjs_required
    expected_subagents = arm.subagents_enabled and subagents_required
    if (budget.quickjs_calls > 0) is not expected_quickjs:
        raise CapabilityEvaluationError(
            "task-level QuickJS activity differs from its requested arm capability"
        )
    if (budget.task_calls > 0) is not expected_subagents:
        raise CapabilityEvaluationError(
            "task-level subagent activity differs from its requested arm capability"
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
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        thread_id=thread_id,
        graph_run_id=str(graph_run_id),
        persistence_empty=observation.persistence_empty,
        cache_mode=observation.cache_mode,
        status=observation.status,
        answer=answer,
        citations=citations,
        task_success=task_success,
        citation_correct=citation_correct,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_tokens,
        cache_write_input_tokens=cache_write_tokens,
        estimated_cost_usd_micros=_estimated_cost(
            identity,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_tokens,
            cache_write_input_tokens=cache_write_tokens,
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
    successes = sum(task.task_success for task in tasks)
    correct_citations = sum(task.citation_correct for task in tasks)
    latency_total = sum(task.latency_ms for task in tasks)
    input_tokens = sum(task.input_tokens for task in tasks)
    output_tokens = sum(task.output_tokens for task in tasks)
    cache_read_tokens = sum(task.cache_read_input_tokens for task in tasks)
    cache_write_tokens = sum(task.cache_write_input_tokens for task in tasks)
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
        cache_read_input_tokens=cache_read_tokens,
        cache_write_input_tokens=cache_write_tokens,
        total_tokens=(
            input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
        ),
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


def _finalize_attempt_budget(
    budget: RunBudget,
    *,
    arm: CapabilityArm,
    task: CapabilityTask,
) -> BudgetSnapshot:
    label = f"{arm.arm_id}/{task.task_id}"
    try:
        snapshot = budget.finalize()
    except RunBudgetUnsettledError as exc:
        raise CapabilityEvaluationError(
            f"executor left an unsettled RunBudget reservation for {label}: {exc}"
        ) from exc
    except RunBudgetExceededError as exc:
        raise CapabilityEvaluationError(
            f"executor exceeded the terminal RunBudget deadline for {label}"
        ) from exc
    if snapshot.finalized is not True:
        raise CapabilityEvaluationError(
            f"executor did not return a terminal RunBudget snapshot for {label}"
        )
    if (
        snapshot.model_reservations_in_flight != 0
        or snapshot.quickjs_in_flight != 0
        or snapshot.tasks_in_flight != 0
    ):
        raise CapabilityEvaluationError(
            f"executor returned an unsettled terminal RunBudget for {label}"
        )
    provider_buckets = (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    )
    if snapshot.provider_usage_complete is not True or any(
        not _is_non_negative_int(value) for value in provider_buckets
    ):
        raise CapabilityEvaluationError(
            f"executor returned incomplete Anthropic provider usage for {label}"
        )
    if sum(cast(tuple[int, int, int, int], provider_buckets)) != (
        snapshot.charged_tokens
    ):
        raise CapabilityEvaluationError(
            f"executor provider usage differs from RunBudget for {label}"
        )
    return snapshot


def _attempt_has_zero_spend(snapshot: BudgetSnapshot) -> bool:
    return (
        snapshot.model_calls == 0
        and snapshot.tool_calls == 0
        and snapshot.quickjs_calls == 0
        and snapshot.task_calls == 0
        and snapshot.charged_tokens == 0
        and snapshot.provider_input_tokens == 0
        and snapshot.provider_output_tokens == 0
        and snapshot.provider_cache_read_input_tokens == 0
        and snapshot.provider_cache_write_input_tokens == 0
        and snapshot.exhausted is False
    )


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

    dataset = _validated_taskset(dataset, location="experiment dataset")
    if not isinstance(executor_identity, CapabilityExecutorIdentity):
        raise CapabilityEvaluationError("executor identity is required")
    if not isinstance(budget_policy, RunBudgetPolicy):
        raise CapabilityEvaluationError("RunBudgetPolicy is required")
    measured_provenance = provenance or collect_run_provenance()

    task_results_by_arm: dict[str, list[CapabilityTaskResult]] = {
        arm.arm_id: [] for arm in CAPABILITY_ARMS
    }
    seen_attempt_ids: set[str] = set()
    seen_thread_ids: set[str] = set()
    seen_graph_run_ids: set[UUID] = set()
    for task_index, task in enumerate(dataset.tasks):
        for arm in _counterbalanced_arms(
            executor_identity,
            task_index=task_index,
        ):
            for attempt_number in range(1, executor_identity.max_attempts + 1):
                budget = budget_factory(budget_policy)
                if not isinstance(budget, RunBudget) or budget.policy != budget_policy:
                    raise CapabilityEvaluationError(
                        "budget factory must return RunBudget with the requested policy"
                    )
                attempt_id, thread_id, graph_run_id = _attempt_identity(
                    executor_identity,
                    arm,
                    task,
                    attempt_number=attempt_number,
                )
                if (
                    attempt_id in seen_attempt_ids
                    or thread_id in seen_thread_ids
                    or graph_run_id in seen_graph_run_ids
                ):
                    raise CapabilityEvaluationError(
                        "capability attempts require fresh thread and run identities"
                    )
                seen_attempt_ids.add(attempt_id)
                seen_thread_ids.add(thread_id)
                seen_graph_run_ids.add(graph_run_id)
                run_config: dict[str, object] = {
                    "configurable": {"thread_id": thread_id},
                    "run_id": graph_run_id,
                }
                validate_capability_config(run_config)
                context = CapabilityExecutionContext(
                    arm=arm,
                    task=task,
                    budget=budget,
                    random_seed=_derived_seed(
                        executor_identity,
                        arm,
                        task,
                        attempt_number=attempt_number,
                    ),
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    thread_id=thread_id,
                    graph_run_id=graph_run_id,
                    run_config=run_config,
                )
                started_ns = clock_ns()
                if not _is_non_negative_int(started_ns):
                    raise CapabilityEvaluationError("experiment clock is malformed")
                try:
                    async with asyncio.timeout(budget.remaining_seconds()):
                        observation = await executor.execute(context)
                except TimeoutError as exc:
                    budget.exhaust()
                    raise CapabilityEvaluationError(
                        "executor exceeded the complete RunBudget deadline for "
                        f"{arm.arm_id}/{task.task_id}"
                    ) from exc
                except Exception as exc:
                    snapshot = _finalize_attempt_budget(
                        budget,
                        arm=arm,
                        task=task,
                    )
                    if (
                        attempt_number < executor_identity.max_attempts
                        and _attempt_has_zero_spend(snapshot)
                    ):
                        continue
                    raise CapabilityEvaluationError(
                        f"executor failed before a complete observation for "
                        f"{arm.arm_id}/{task.task_id}"
                    ) from exc
                finished_ns = clock_ns()
                if not _is_non_negative_int(finished_ns) or finished_ns < started_ns:
                    raise CapabilityEvaluationError("experiment clock moved backwards")
                latency_ms = (finished_ns - started_ns + 500_000) // 1_000_000
                snapshot = _finalize_attempt_budget(
                    budget,
                    arm=arm,
                    task=task,
                )
                task_results_by_arm[arm.arm_id].append(
                    _validate_observation(
                        observation,
                        arm=arm,
                        task=task,
                        attempt_id=attempt_id,
                        attempt_number=attempt_number,
                        thread_id=thread_id,
                        graph_run_id=graph_run_id,
                        latency_ms=latency_ms,
                        budget=snapshot,
                        identity=executor_identity,
                    )
                )
                break

    arms: list[CapabilityArmResult] = []
    for arm in CAPABILITY_ARMS:
        task_results = task_results_by_arm[arm.arm_id]
        if tuple(result.task_id for result in task_results) != tuple(
            task.task_id for task in dataset.tasks
        ):
            raise CapabilityEvaluationError(
                f"arm {arm.arm_id} is missing a canonical task result"
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
        keys=frozenset(
            {
                "cache_mode",
                "execution_id",
                "executor_id",
                "max_attempts",
                "model_id",
                "pricing",
                "random_seed",
            }
        ),
    )
    pricing = _mapping(
        raw["pricing"],
        location="run.executor.pricing",
        keys=frozenset(
            {
                "cache_read_input_usd_micros_per_million_tokens",
                "cache_write_input_usd_micros_per_million_tokens",
                "output_usd_micros_per_million_tokens",
                "uncached_input_usd_micros_per_million_tokens",
            }
        ),
    )
    try:
        return CapabilityExecutorIdentity(
            cache_mode=_text(
                raw["cache_mode"],
                location="run.executor.cache_mode",
            ),
            execution_id=_text(
                raw["execution_id"],
                location="run.executor.execution_id",
            ),
            executor_id=_text(
                raw["executor_id"],
                location="run.executor.executor_id",
            ),
            max_attempts=_integer(
                raw["max_attempts"],
                location="run.executor.max_attempts",
            ),
            model_id=_text(raw["model_id"], location="run.executor.model_id"),
            random_seed=_integer(
                raw["random_seed"],
                location="run.executor.random_seed",
            ),
            uncached_input_usd_micros_per_million_tokens=_integer(
                pricing["uncached_input_usd_micros_per_million_tokens"],
                location=(
                    "run.executor.pricing.uncached_input_usd_micros_per_million_tokens"
                ),
            ),
            output_usd_micros_per_million_tokens=_integer(
                pricing["output_usd_micros_per_million_tokens"],
                location=("run.executor.pricing.output_usd_micros_per_million_tokens"),
            ),
            cache_read_input_usd_micros_per_million_tokens=_integer(
                pricing["cache_read_input_usd_micros_per_million_tokens"],
                location=(
                    "run.executor.pricing."
                    "cache_read_input_usd_micros_per_million_tokens"
                ),
            ),
            cache_write_input_usd_micros_per_million_tokens=_integer(
                pricing["cache_write_input_usd_micros_per_million_tokens"],
                location=(
                    "run.executor.pricing."
                    "cache_write_input_usd_micros_per_million_tokens"
                ),
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
        model_reservations_in_flight=_integer(
            raw["model_reservations_in_flight"],
            location=f"{location}.model_reservations_in_flight",
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
        provider_input_tokens=_optional_integer(
            raw["provider_input_tokens"],
            location=f"{location}.provider_input_tokens",
        ),
        provider_output_tokens=_optional_integer(
            raw["provider_output_tokens"],
            location=f"{location}.provider_output_tokens",
        ),
        provider_cache_read_input_tokens=_optional_integer(
            raw["provider_cache_read_input_tokens"],
            location=f"{location}.provider_cache_read_input_tokens",
        ),
        provider_cache_write_input_tokens=_optional_integer(
            raw["provider_cache_write_input_tokens"],
            location=f"{location}.provider_cache_write_input_tokens",
        ),
        provider_usage_complete=_boolean(
            raw["provider_usage_complete"],
            location=f"{location}.provider_usage_complete",
        ),
        elapsed_ms=_integer(raw["elapsed_ms"], location=f"{location}.elapsed_ms"),
        exhausted=_boolean(raw["exhausted"], location=f"{location}.exhausted"),
        finalized=_boolean(raw["finalized"], location=f"{location}.finalized"),
    )
    limits = {
        "model_calls": policy.max_model_calls,
        "model_reservations_in_flight": policy.max_model_calls,
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
    provider_buckets = (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    )
    if snapshot.provider_usage_complete:
        if any(value is None for value in provider_buckets):
            raise CapabilityEvaluationError(
                f"{location} complete provider usage has a missing bucket"
            )
    elif any(value is not None for value in provider_buckets):
        raise CapabilityEvaluationError(
            f"{location} incomplete provider usage must redact every bucket"
        )
    return snapshot


def _parse_arm(value: object, *, location: str) -> CapabilityArm:
    raw = _mapping(
        value,
        location=location,
        keys=frozenset({"arm_id", "quickjs_enabled", "subagents_enabled"}),
    )
    return CapabilityArm(
        arm_id=_text(raw["arm_id"], location=f"{location}.arm_id"),
        quickjs_enabled=_boolean(
            raw["quickjs_enabled"],
            location=f"{location}.quickjs_enabled",
        ),
        subagents_enabled=_boolean(
            raw["subagents_enabled"],
            location=f"{location}.subagents_enabled",
        ),
    )


def _parse_arm_metrics(value: object, *, location: str) -> CapabilityArmMetrics:
    keys = frozenset(CapabilityArmMetrics.__dataclass_fields__)
    raw = _mapping(value, location=location, keys=keys)
    values = {
        key: _integer(raw[key], location=f"{location}.{key}") for key in sorted(keys)
    }
    return CapabilityArmMetrics(**values)


def _parse_dataset_identity(value: object) -> dict[str, object]:
    location = "run.dataset"
    raw = _mapping(
        value,
        location=location,
        keys=frozenset(
            {
                "checksum",
                "content_tree_sha",
                "dataset_id",
                "label_status",
                "task_count",
            }
        ),
    )
    return {
        "checksum": _text(raw["checksum"], location=f"{location}.checksum"),
        "content_tree_sha": _text(
            raw["content_tree_sha"],
            location=f"{location}.content_tree_sha",
        ),
        "dataset_id": _text(
            raw["dataset_id"],
            location=f"{location}.dataset_id",
        ),
        "label_status": _text(
            raw["label_status"],
            location=f"{location}.label_status",
        ),
        "task_count": _integer(
            raw["task_count"],
            location=f"{location}.task_count",
        ),
    }


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
                "attempt_id",
                "attempt_number",
                "budget",
                "cache_mode",
                "cache_read_input_tokens",
                "cache_write_input_tokens",
                "citation_correct",
                "citations",
                "estimated_cost_usd_micros",
                "failure_code",
                "graph_run_id",
                "input_tokens",
                "latency_ms",
                "output_tokens",
                "persistence_empty",
                "status",
                "task_id",
                "task_success",
                "thread_id",
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
    attempt_number = _integer(
        raw["attempt_number"],
        location=f"{location}.attempt_number",
    )
    if not 1 <= attempt_number <= identity.max_attempts:
        raise CapabilityEvaluationError(
            f"{location}.attempt_number exceeds the execution retry policy"
        )
    attempt_id, thread_id, graph_run_id = _attempt_identity(
        identity,
        arm,
        task,
        attempt_number=attempt_number,
    )
    if (
        raw["attempt_id"] != attempt_id
        or raw["thread_id"] != thread_id
        or raw["graph_run_id"] != str(graph_run_id)
    ):
        raise CapabilityEvaluationError(
            f"{location} attempt/thread/run identity is inconsistent"
        )
    observation = CapabilityObservation(
        status=status,
        answer=(
            None
            if raw["answer"] is None
            else _canonical_object(raw["answer"], location=f"{location}.answer")
        ),
        citations=citations,
        persistence_empty=_boolean(
            raw["persistence_empty"],
            location=f"{location}.persistence_empty",
        ),
        cache_mode=_text(
            raw["cache_mode"],
            location=f"{location}.cache_mode",
        ),
        failure_code=cast(str | None, failure_code),
    )
    result = _validate_observation(
        observation,
        arm=arm,
        task=task,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        thread_id=thread_id,
        graph_run_id=graph_run_id,
        latency_ms=_integer(raw["latency_ms"], location=f"{location}.latency_ms"),
        budget=_parse_budget(
            raw["budget"],
            location=f"{location}.budget",
            policy=policy,
        ),
        identity=identity,
    )
    task_success = _boolean(
        raw["task_success"],
        location=f"{location}.task_success",
    )
    citation_correct = _boolean(
        raw["citation_correct"],
        location=f"{location}.citation_correct",
    )
    estimated_cost = _integer(
        raw["estimated_cost_usd_micros"],
        location=f"{location}.estimated_cost_usd_micros",
    )
    input_tokens = _integer(
        raw["input_tokens"],
        location=f"{location}.input_tokens",
    )
    output_tokens = _integer(
        raw["output_tokens"],
        location=f"{location}.output_tokens",
    )
    cache_read_tokens = _integer(
        raw["cache_read_input_tokens"],
        location=f"{location}.cache_read_input_tokens",
    )
    cache_write_tokens = _integer(
        raw["cache_write_input_tokens"],
        location=f"{location}.cache_write_input_tokens",
    )
    if (
        task_success is not result.task_success
        or citation_correct is not result.citation_correct
        or estimated_cost != result.estimated_cost_usd_micros
        or input_tokens != result.input_tokens
        or output_tokens != result.output_tokens
        or cache_read_tokens != result.cache_read_input_tokens
        or cache_write_tokens != result.cache_write_input_tokens
    ):
        raise CapabilityEvaluationError(f"{location} derived scoring is inconsistent")
    return result


def parse_capability_run(
    value: object,
    *,
    dataset: CapabilityTaskSet,
) -> CapabilityRun:
    """Parse and fully recompute a recorded four-arm capability run."""

    dataset = _validated_taskset(dataset, location="run dataset")
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
    if _parse_dataset_identity(raw["dataset"]) != expected_dataset:
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
        if (
            _parse_arm(
                arm_record["arm"],
                location=f"{location}.arm",
            )
            != expected_arm
        ):
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
        if (
            _parse_arm_metrics(
                arm_record["metrics"],
                location=f"{location}.metrics",
            )
            != metrics
        ):
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
        f"- Execution ID: `{run.executor.execution_id}`",
        f"- Model: `{_markdown(run.executor.model_id)}`",
        f"- Random seed: `{run.executor.random_seed}`",
        f"- Maximum zero-spend attempts: `{run.executor.max_attempts}`",
        f"- Cache mode: `{run.executor.cache_mode}`",
        f"- Shared budget policy: `{_markdown(run.budget_policy.policy_id)}`",
        "",
        "## Arm summary",
        "",
        "| Arm | QuickJS | Subagents | Task success | Citation correctness | "
        "Mean latency | Model/tool/task calls | Tokens (in/out/read/write/total) | "
        "Estimated cost |",
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
            f"{metrics.input_tokens}/{metrics.output_tokens}/"
            f"{metrics.cache_read_input_tokens}/"
            f"{metrics.cache_write_input_tokens}/{metrics.total_tokens} | "
            f"{_usd(metrics.estimated_cost_usd_micros)} |"
        )

    lines.extend(["", "## Per-task observations", ""])
    for arm in run.arms:
        lines.extend(
            [
                f"### `{arm.arm.arm_id}`",
                "",
                "| Task | Status | Success | Citations | Latency | "
                "Model/tool/QuickJS/task | Tokens (in/out/read/write/total) | Cost |",
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
                f"{task.input_tokens}/{task.output_tokens}/"
                f"{task.cache_read_input_tokens}/"
                f"{task.cache_write_input_tokens}/"
                f"{task.budget.charged_tokens} | "
                f"{_usd(task.estimated_cost_usd_micros)} |"
            )
        lines.append("")
    lines.extend(
        [
            "Latency is monotonic elapsed time rounded to the nearest millisecond. "
            "Rates use integer parts-per-million; model cost is rounded up once per "
            "task to the nearest micro-US-dollar from finalized Anthropic uncached "
            "input, output, cache-read input, and cache-write input buckets.",
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

    dataset = _validated_taskset(dataset, location="verification dataset")
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

    if not isinstance(run, CapabilityRun):
        raise CapabilityEvaluationError("a complete capability run is required")
    dataset = _validated_taskset(run.dataset, location="artifact dataset")
    run = parse_capability_run(run.as_dict(), dataset=dataset)
    capability_root = output_root / "capabilities"
    dataset_directory = capability_root / run.dataset.dataset_id
    run_slug = run.run_id.removeprefix("sha256:")
    directory = dataset_directory / run_slug
    payloads, manifest_payload, result_digest = _artifact_payloads(run)
    if output_root.is_symlink() or capability_root.is_symlink():
        raise CapabilityEvaluationError("capability result roots must not be symlinks")
    resolved_capability_root = capability_root.resolve(strict=False)
    resolved_dataset_directory = dataset_directory.resolve(strict=False)
    if resolved_dataset_directory.parent != resolved_capability_root:
        raise CapabilityEvaluationError(
            "capability dataset result directory must be an immediate child"
        )
    dataset_directory.mkdir(parents=True, exist_ok=True)
    if dataset_directory.is_symlink() or dataset_directory.resolve(
        strict=True
    ).parent != capability_root.resolve(strict=True):
        raise CapabilityEvaluationError(
            "capability dataset result directory must be a real immediate child"
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
