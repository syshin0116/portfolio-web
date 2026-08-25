"""Reproducible QuickJS × dynamic-subagent capability experiments.

Capability experiments are deliberately separate from retrieval evaluation. The runner
owns the four factorial arms, one real :class:`RunBudget` per attempt, strict scoring,
and immutable report bytes. A caller supplies the provider/agent executor; tests fake
only the provider while executing the production graph.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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
from types import MappingProxyType
from typing import Any, Protocol, cast
from uuid import UUID, uuid5

from agent.capabilities.budget import (
    TASK_TOOL_NAME,
    BudgetSnapshot,
    RunBudget,
    RunBudgetExceededError,
    RunBudgetPolicy,
    RunBudgetUnsettledError,
)
from agent.capabilities.quickjs import QUICKJS_TOOL_NAME
from agent.capabilities.subagents import validate_capability_config
from agent.retrieval.protocol import DocId
from langchain_core.messages import ToolMessage

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
CAPABILITY_RUN_SCHEMA = "blogeval-capability-run-v5"
CAPABILITY_RUNNER_ID = "blogeval.capability_runner@5"
CAPABILITY_EVIDENCE_STATUS = "synthetic-provider-free"
CAPABILITY_PROVIDER_EVIDENCE_STATUS = "provider-backed-local-unattested"
CAPABILITY_EVIDENCE_STATUSES = frozenset(
    {CAPABILITY_EVIDENCE_STATUS, CAPABILITY_PROVIDER_EVIDENCE_STATUS}
)
CAPABILITY_MANIFEST_SCHEMA = "blogeval-capability-result-manifest-v1"
CAPABILITY_RESULT_DIGEST_SCHEMA = "blogeval-capability-result-digest-v1"
CAPABILITY_RESULT_FILES = ("capability-report.md", "run.json")
CAPABILITY_EVAL_SUBAGENT_NAMES = frozenset({"evidence-checker"})
CAPABILITY_GENERATION_COST_SCOPE = "generation-token-usage-only"
OPENAI_INPUT_TOKEN_COUNT_ENDPOINT = "/responses/input_tokens"
OPENAI_INPUT_TOKEN_COUNT_BILLING_STATUS = "provider-pricing-undocumented"
OPENAI_CAPABILITY_EXECUTOR_ID = "blogeval.openai_responses_capability_executor@2"
OPENAI_CAPABILITY_MODEL_ID = "openai:gpt-5.6-luna"
OPENAI_CAPABILITY_PROVIDER_CONTRACT = (
    "openai-responses:gpt-5.6-luna@2026-08-02:"
    "reasoning-none-current-turn:store-false:"
    "official-api-openai-v1:no-ambient-routing:"
    "langchain-openai-1.3.5:openai-2.53.0"
)
OPENAI_CAPABILITY_CACHE_MODE = "openai-implicit-recorded"
OPENAI_CAPABILITY_MAX_ATTEMPTS = 1
OPENAI_CAPABILITY_PRICING = MappingProxyType(
    {
        "uncached_input_usd_micros_per_million_tokens": 200_000,
        "cache_read_input_usd_micros_per_million_tokens": 20_000,
        "cache_write_input_usd_micros_per_million_tokens": 250_000,
        "output_usd_micros_per_million_tokens": 1_200_000,
    }
)
_DATASET_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TASK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_DATASET_ID_BYTES = 128
_MAX_PROMPT_BYTES = 16_000
_MAX_TASKS = 32
_MAX_ROOT_TOOL_CALL_ID_BYTES = 1_024
_MAX_ROOT_TOOL_NAME_BYTES = 128
_RATE_SCALE = 1_000_000
_MAX_ATTEMPTS = 3
_MAX_GENERATION_COST_USD_MICROS = 25_000_000
_MAX_PRICE_USD_MICROS_PER_MILLION_TOKENS = 100_000_000
_CACHE_MODES = frozenset(
    {
        "disabled",
        "anthropic-ephemeral-5m-recorded",
        "openai-implicit-recorded",
    }
)
_CAPABILITY_POLICY_MAXIMA = {
    "max_model_calls": 12,
    "max_tool_calls": 24,
    "max_quickjs_calls": 4,
    "max_quickjs_in_flight": 1,
    "max_quickjs_output_bytes": 4_096,
    "max_quickjs_total_output_bytes": 16_384,
    "max_task_calls": 1,
    "max_tasks_in_flight": 1,
    "max_depth": 1,
    "max_output_tokens": 2_048,
    "max_total_tokens": 48_000,
    "max_count_risk_tokens_per_attempt": 48_000,
    "max_count_risk_tokens_per_run": 48_000,
    "max_elapsed_seconds": 90,
}
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


_EXECUTOR_DIAGNOSTIC_PHASES = frozenset(
    {
        "final_json",
        "graph_build",
        "graph_invoke",
        "persistence_preflight",
        "quickjs_cleanup",
        "result_shape",
        "root_trace",
        "subtype_trace",
    }
)
_EXECUTOR_DIAGNOSTIC_REASONS = frozenset(
    {
        "budget",
        "cleanup",
        "delegation_contract",
        "graph_other",
        "input_count",
        "provider",
        "result_shape",
        "root_tool_denied",
        "strict_json",
        "trace",
    }
)
_EXECUTOR_DIAGNOSTIC_ROOT_EVENTS = frozenset(
    {
        "call:eval",
        "call:other",
        "call:task",
        "completion:eval",
        "completion:other",
        "completion:task",
    }
)


class CapabilityExecutorDiagnosticError(RuntimeError):
    """Carry only bounded structural executor diagnostics across the runner boundary."""

    def __init__(
        self,
        *,
        phase: str,
        reason_code: str = "graph_other",
        root_tool_events: tuple[str, ...] = (),
    ) -> None:
        if phase not in _EXECUTOR_DIAGNOSTIC_PHASES:
            raise ValueError("executor diagnostic phase is unsupported")
        if reason_code not in _EXECUTOR_DIAGNOSTIC_REASONS:
            raise ValueError("executor diagnostic reason is unsupported")
        if (
            not isinstance(root_tool_events, tuple)
            or len(root_tool_events) > _CAPABILITY_POLICY_MAXIMA["max_tool_calls"] * 2
            or any(
                event not in _EXECUTOR_DIAGNOSTIC_ROOT_EVENTS
                for event in root_tool_events
            )
        ):
            raise ValueError("executor diagnostic root events are malformed")
        self.phase = phase
        self.reason_code = reason_code
        self.root_tool_events = root_tool_events
        super().__init__("capability executor failed with redacted diagnostics")


def _sanitized_executor_diagnostic(
    error: CapabilityExecutorDiagnosticError,
) -> tuple[str, str, tuple[str, ...]]:
    """Copy only fixed enum values so the original exception can be discarded."""

    phase = error.phase
    reason_code = error.reason_code
    root_tool_events = error.root_tool_events
    if phase not in _EXECUTOR_DIAGNOSTIC_PHASES:
        phase = "graph_invoke"
    if reason_code not in _EXECUTOR_DIAGNOSTIC_REASONS:
        reason_code = "graph_other"
    if (
        not isinstance(root_tool_events, tuple)
        or len(root_tool_events) > _CAPABILITY_POLICY_MAXIMA["max_tool_calls"] * 2
        or any(
            event not in _EXECUTOR_DIAGNOSTIC_ROOT_EVENTS for event in root_tool_events
        )
    ):
        root_tool_events = ()
    return phase, reason_code, root_tool_events


@dataclass(frozen=True, slots=True)
class RootToolTraceEvent:
    """One root call or its matching ToolMessage completion boundary."""

    message_index: int
    phase: str
    tool_call_id: str
    tool_name: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


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
    content_tree_sha: str
    model_id: str
    provider_contract: str
    random_seed: int
    max_attempts: int
    cache_mode: str
    max_generation_cost_usd_micros: int
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
            or not isinstance(self.content_tree_sha, str)
            or _SHA1_RE.fullmatch(self.content_tree_sha) is None
            or not isinstance(self.model_id, str)
            or not self.model_id
            or self.model_id != self.model_id.strip()
            or not isinstance(self.provider_contract, str)
            or not self.provider_contract
            or self.provider_contract != self.provider_contract.strip()
            or not self.provider_contract.isascii()
            or len(self.provider_contract) > 512
            or any(character.isspace() for character in self.provider_contract)
            or not _is_non_negative_int(self.random_seed)
            or not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 1 <= self.max_attempts <= _MAX_ATTEMPTS
            or not isinstance(self.cache_mode, str)
            or self.cache_mode not in _CACHE_MODES
            or not _is_positive_int(self.max_generation_cost_usd_micros)
            or (self.max_generation_cost_usd_micros > _MAX_GENERATION_COST_USD_MICROS)
            or not _is_positive_int(self.uncached_input_usd_micros_per_million_tokens)
            or not _is_positive_int(self.output_usd_micros_per_million_tokens)
            or not _is_positive_int(self.cache_read_input_usd_micros_per_million_tokens)
            or not _is_positive_int(
                self.cache_write_input_usd_micros_per_million_tokens
            )
            or max(
                self.uncached_input_usd_micros_per_million_tokens,
                self.output_usd_micros_per_million_tokens,
                self.cache_read_input_usd_micros_per_million_tokens,
                self.cache_write_input_usd_micros_per_million_tokens,
            )
            > _MAX_PRICE_USD_MICROS_PER_MILLION_TOKENS
        ):
            raise ValueError("capability executor identity is malformed")

    def as_dict(self) -> dict[str, object]:
        return {
            "cache_mode": self.cache_mode,
            "content_tree_sha": self.content_tree_sha,
            "execution_id": self.execution_id,
            "executor_id": self.executor_id,
            "max_attempts": self.max_attempts,
            "max_generation_cost_usd_micros": self.max_generation_cost_usd_micros,
            "model_id": self.model_id,
            "provider_contract": self.provider_contract,
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
    delegated_subagent_types: tuple[str, ...] = ()
    root_tool_trace: tuple[RootToolTraceEvent, ...] = ()
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityExecutionContext:
    """Server-owned arm and budget passed to one executor invocation."""

    arm: CapabilityArm
    task: CapabilityTask
    budget: RunBudget
    content_tree_sha: str
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
    estimated_generation_cost_usd_micros: int
    delegated_subagent_types: tuple[str, ...]
    delegated_tool_calls: int
    root_tool_trace: tuple[RootToolTraceEvent, ...]
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
            "delegated_subagent_types": list(self.delegated_subagent_types),
            "delegated_tool_calls": self.delegated_tool_calls,
            "estimated_generation_cost_usd_micros": (
                self.estimated_generation_cost_usd_micros
            ),
            "failure_code": self.failure_code,
            "graph_run_id": self.graph_run_id,
            "input_tokens": self.input_tokens,
            "latency_ms": self.latency_ms,
            "output_tokens": self.output_tokens,
            "persistence_empty": self.persistence_empty,
            "root_tool_trace": [event.as_dict() for event in self.root_tool_trace],
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
    estimated_generation_cost_usd_micros: int

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
    evidence_status: str
    budget_policy: RunBudgetPolicy
    arms: tuple[CapabilityArmResult, ...]
    provenance: RunProvenance

    def as_dict(self) -> dict[str, object]:
        return {
            "arms": [arm.as_dict() for arm in self.arms],
            "budget_policy": asdict(self.budget_policy),
            "cost_accounting": _cost_accounting(
                evidence_status=self.evidence_status,
                identity=self.executor,
                policy=self.budget_policy,
                task_count=len(self.dataset.tasks),
            ),
            "dataset": {
                "checksum": self.dataset.checksum,
                "content_tree_sha": self.dataset.content_tree_sha,
                "dataset_id": self.dataset.dataset_id,
                "label_status": self.dataset.label_status,
                "task_count": len(self.dataset.tasks),
            },
            "evidence_status": self.evidence_status,
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


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _evidence_status(value: object, *, location: str) -> str:
    if not isinstance(value, str) or value not in CAPABILITY_EVIDENCE_STATUSES:
        raise CapabilityEvaluationError(f"{location} is unsupported")
    return value


def _validate_evidence_contract(
    evidence_status: str,
    identity: CapabilityExecutorIdentity,
) -> None:
    if evidence_status == CAPABILITY_EVIDENCE_STATUS:
        if identity.provider_contract != "synthetic:provider-free":
            raise CapabilityEvaluationError(
                "synthetic evidence requires the provider-free contract"
            )
        return
    if evidence_status == CAPABILITY_PROVIDER_EVIDENCE_STATUS:
        expected = {
            "executor_id": OPENAI_CAPABILITY_EXECUTOR_ID,
            "model_id": OPENAI_CAPABILITY_MODEL_ID,
            "provider_contract": OPENAI_CAPABILITY_PROVIDER_CONTRACT,
            "cache_mode": OPENAI_CAPABILITY_CACHE_MODE,
            "max_attempts": OPENAI_CAPABILITY_MAX_ATTEMPTS,
            **OPENAI_CAPABILITY_PRICING,
        }
        observed = {
            "executor_id": identity.executor_id,
            "model_id": identity.model_id,
            "provider_contract": identity.provider_contract,
            "cache_mode": identity.cache_mode,
            "max_attempts": identity.max_attempts,
            "uncached_input_usd_micros_per_million_tokens": (
                identity.uncached_input_usd_micros_per_million_tokens
            ),
            "cache_read_input_usd_micros_per_million_tokens": (
                identity.cache_read_input_usd_micros_per_million_tokens
            ),
            "cache_write_input_usd_micros_per_million_tokens": (
                identity.cache_write_input_usd_micros_per_million_tokens
            ),
            "output_usd_micros_per_million_tokens": (
                identity.output_usd_micros_per_million_tokens
            ),
        }
        if observed != expected:
            raise CapabilityEvaluationError(
                "local provider evidence requires the exact reviewed OpenAI identity"
            )
        return
    raise CapabilityEvaluationError("capability evidence status is unsupported")


def _reviewed_provider_executor_type() -> type:
    """Resolve the one code-owned live adapter lazily to avoid an import cycle."""

    from blogeval.capability_openai import OpenAICapabilityExecutor

    return OpenAICapabilityExecutor


def _validate_executor_evidence_contract(
    evidence_status: str,
    executor: CapabilityExecutor,
) -> None:
    if (
        evidence_status == CAPABILITY_PROVIDER_EVIDENCE_STATUS
        and type(executor) is not _reviewed_provider_executor_type()
    ):
        raise CapabilityEvaluationError(
            "local provider evidence requires the exact reviewed executor implementation"
        )


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
    if len(raw_tasks) > _MAX_TASKS:
        raise CapabilityEvaluationError(
            f"capability task-set cannot contain more than {_MAX_TASKS} tasks"
        )

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
    model_provider: str | None = None,
    expected_response_models: frozenset[str] | None = None,
    quickjs_middleware: Any | None = None,
):
    """Compile the actual topology-stable agent graph for one server-owned arm."""

    from agent.graph import create_graph

    quickjs_active, subagents_active = activated_capabilities(context)
    root_tool_allowlist = frozenset(
        tool_name
        for tool_name, enabled in (
            (QUICKJS_TOOL_NAME, quickjs_active),
            (TASK_TOOL_NAME, subagents_active),
        )
        if enabled
    )

    return create_graph(
        runtime=runtime,
        config=context.run_config,
        budget=context.budget,
        model=model,
        input_token_counter=input_token_counter,
        model_provider=model_provider,
        expected_response_models=expected_response_models,
        quickjs_enabled=quickjs_active,
        dynamic_subagents_enabled=subagents_active,
        quickjs_middleware=quickjs_middleware,
        root_tool_allowlist=root_tool_allowlist,
        experiment_subagent_allowlist=CAPABILITY_EVAL_SUBAGENT_NAMES,
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


def activated_capabilities(
    context: CapabilityExecutionContext,
) -> tuple[bool, bool]:
    """Return the arm capabilities authorized for this canonical task."""
    if not isinstance(context, CapabilityExecutionContext):
        raise TypeError("context must be a CapabilityExecutionContext")
    quickjs_required, subagents_required = _task_capabilities(context.task)
    if (
        quickjs_required
        and not context.arm.quickjs_enabled
        or subagents_required
        and not context.arm.subagents_enabled
    ):
        return False, False
    return (
        context.arm.quickjs_enabled and quickjs_required,
        context.arm.subagents_enabled and subagents_required,
    )


def _root_tool_trace_text(
    value: object,
    *,
    location: str,
    maximum_bytes: int,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityEvaluationError(f"{location} is malformed")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CapabilityEvaluationError(f"{location} is malformed") from exc
    if size > maximum_bytes:
        raise CapabilityEvaluationError(f"{location} is malformed")
    return value


def _validated_root_tool_trace(
    value: object,
    *,
    location: str,
) -> tuple[RootToolTraceEvent, ...]:
    if not isinstance(value, tuple):
        raise CapabilityEvaluationError(f"{location} is not an auditable tuple")
    if len(value) > _CAPABILITY_POLICY_MAXIMA["max_tool_calls"] * 2:
        raise CapabilityEvaluationError(f"{location} exceeds the root tool-call budget")

    calls: dict[str, tuple[str, int]] = {}
    completed: set[str] = set()
    previous_message_index = -1
    previous_phase: str | None = None
    for index, event in enumerate(value):
        event_location = f"{location}[{index}]"
        if not isinstance(event, RootToolTraceEvent):
            raise CapabilityEvaluationError(f"{event_location} is malformed")
        if (
            not _is_non_negative_int(event.message_index)
            or event.message_index < previous_message_index
            or (
                event.message_index == previous_message_index
                and (event.phase != "call" or previous_phase != "call")
            )
        ):
            raise CapabilityEvaluationError(
                f"{location} does not preserve root message chronology"
            )
        phase = _root_tool_trace_text(
            event.phase,
            location=f"{event_location}.phase",
            maximum_bytes=16,
        )
        if phase not in {"call", "completion"}:
            raise CapabilityEvaluationError(f"{event_location}.phase is unsupported")
        tool_call_id = _root_tool_trace_text(
            event.tool_call_id,
            location=f"{event_location}.tool_call_id",
            maximum_bytes=_MAX_ROOT_TOOL_CALL_ID_BYTES,
        )
        tool_name = _root_tool_trace_text(
            event.tool_name,
            location=f"{event_location}.tool_name",
            maximum_bytes=_MAX_ROOT_TOOL_NAME_BYTES,
        )
        if phase == "call":
            if tool_call_id in calls:
                raise CapabilityEvaluationError(
                    f"{location} repeats a root tool-call ID"
                )
            calls[tool_call_id] = (tool_name, event.message_index)
        else:
            call = calls.get(tool_call_id)
            if (
                call is None
                or tool_call_id in completed
                or call[0] != tool_name
                or call[1] >= event.message_index
            ):
                raise CapabilityEvaluationError(
                    f"{location} has an unmatched ToolMessage completion"
                )
            completed.add(tool_call_id)
        previous_message_index = event.message_index
        previous_phase = phase
    if completed != set(calls):
        raise CapabilityEvaluationError(
            f"{location} has a root call without a ToolMessage completion"
        )
    return value


def recorded_root_tool_trace(messages: object) -> tuple[RootToolTraceEvent, ...]:
    """Record root calls and their actual ToolMessage completion boundaries."""

    if not isinstance(messages, Sequence) or isinstance(
        messages,
        (str, bytes, bytearray),
    ):
        raise CapabilityEvaluationError("graph messages are not an auditable sequence")
    events: list[RootToolTraceEvent] = []
    calls: dict[str, str] = {}
    completed: set[str] = set()
    for message_index, message in enumerate(messages):
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is not None:
            if not isinstance(tool_calls, list):
                raise CapabilityEvaluationError("graph tool calls are not auditable")
            for tool_call in tool_calls:
                if not isinstance(tool_call, Mapping):
                    raise CapabilityEvaluationError("graph tool call is not auditable")
                tool_call_id = _root_tool_trace_text(
                    tool_call.get("id"),
                    location="graph root tool-call ID",
                    maximum_bytes=_MAX_ROOT_TOOL_CALL_ID_BYTES,
                )
                tool_name = _root_tool_trace_text(
                    tool_call.get("name"),
                    location="graph root tool name",
                    maximum_bytes=_MAX_ROOT_TOOL_NAME_BYTES,
                )
                if tool_call_id in calls:
                    raise CapabilityEvaluationError("graph repeats a root tool-call ID")
                calls[tool_call_id] = tool_name
                events.append(
                    RootToolTraceEvent(
                        message_index=message_index,
                        phase="call",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )
                )
        if isinstance(message, ToolMessage):
            tool_call_id = _root_tool_trace_text(
                message.tool_call_id,
                location="graph ToolMessage tool-call ID",
                maximum_bytes=_MAX_ROOT_TOOL_CALL_ID_BYTES,
            )
            tool_name = _root_tool_trace_text(
                message.name,
                location="graph ToolMessage tool name",
                maximum_bytes=_MAX_ROOT_TOOL_NAME_BYTES,
            )
            expected_name = calls.get(tool_call_id)
            if (
                expected_name is None
                or expected_name != tool_name
                or tool_call_id in completed
            ):
                raise CapabilityEvaluationError(
                    "graph ToolMessage does not complete one prior root call"
                )
            completed.add(tool_call_id)
            events.append(
                RootToolTraceEvent(
                    message_index=message_index,
                    phase="completion",
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                )
            )
    return _validated_root_tool_trace(
        tuple(events),
        location="recorded root tool trace",
    )


def recorded_subagent_types(messages: object) -> tuple[str, ...]:
    """Extract the actual root task-call subtype sequence from graph messages."""

    if not isinstance(messages, Sequence) or isinstance(
        messages,
        (str, bytes, bytearray),
    ):
        raise CapabilityEvaluationError("graph messages are not an auditable sequence")
    result: list[str] = []
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None:
            continue
        if not isinstance(tool_calls, list):
            raise CapabilityEvaluationError("graph tool calls are not auditable")
        for tool_call in tool_calls:
            if not isinstance(tool_call, Mapping):
                raise CapabilityEvaluationError("graph tool call is not auditable")
            if tool_call.get("name") != TASK_TOOL_NAME:
                continue
            args = tool_call.get("args")
            subagent_type = (
                args.get("subagent_type") if isinstance(args, Mapping) else None
            )
            if (
                not isinstance(subagent_type, str)
                or not subagent_type
                or subagent_type != subagent_type.strip()
            ):
                raise CapabilityEvaluationError(
                    "graph task call has no auditable subagent type"
                )
            result.append(subagent_type)
    return tuple(result)


def _isolated_task(task: CapabilityTask) -> CapabilityTask:
    """Give one attempt its own nested JSON values so arms cannot contaminate peers."""

    inputs = json.loads(canonical_json_bytes(task.inputs))
    expected_answer = json.loads(canonical_json_bytes(task.expected_answer))
    if not isinstance(inputs, dict) or not isinstance(expected_answer, dict):
        raise CapabilityEvaluationError("capability task JSON isolation failed")
    return CapabilityTask(
        task_id=task.task_id,
        prompt=task.prompt,
        inputs=inputs,
        expected_answer=expected_answer,
        expected_citations=task.expected_citations,
        tags=task.tags,
    )


def _require_task_unchanged(
    task: CapabilityTask,
    *,
    expected_payload: bytes,
) -> None:
    try:
        actual_payload = canonical_json_bytes(task.as_dict())
    except (StrictJsonError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise CapabilityEvaluationError(
            "executor mutated its isolated capability task"
        ) from exc
    if actual_payload != expected_payload:
        raise CapabilityEvaluationError("executor mutated its isolated capability task")


def _validated_capability_policy(policy: object) -> RunBudgetPolicy:
    if not isinstance(policy, RunBudgetPolicy):
        raise CapabilityEvaluationError("RunBudgetPolicy is required")
    if any(
        getattr(policy, field) > maximum
        for field, maximum in _CAPABILITY_POLICY_MAXIMA.items()
    ):
        raise CapabilityEvaluationError(
            "RunBudgetPolicy exceeds the capability experiment maxima"
        )
    return policy


def _worst_case_generation_cost(
    identity: CapabilityExecutorIdentity,
    *,
    policy: RunBudgetPolicy,
    task_count: int,
) -> int:
    maximum_rate = max(
        identity.uncached_input_usd_micros_per_million_tokens,
        identity.output_usd_micros_per_million_tokens,
        identity.cache_read_input_usd_micros_per_million_tokens,
        identity.cache_write_input_usd_micros_per_million_tokens,
    )
    maximum_task_cost = (policy.max_total_tokens * maximum_rate + 999_999) // 1_000_000
    return maximum_task_cost * task_count * len(CAPABILITY_ARMS)


def _estimated_generation_cost(
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


def _cost_accounting(
    *,
    evidence_status: str,
    identity: CapabilityExecutorIdentity,
    policy: RunBudgetPolicy,
    task_count: int,
) -> dict[str, object]:
    excluded_request_billing: list[dict[str, object]] = []
    if evidence_status == CAPABILITY_PROVIDER_EVIDENCE_STATUS:
        excluded_request_billing.append(
            {
                "billing_status": OPENAI_INPUT_TOKEN_COUNT_BILLING_STATUS,
                "endpoint": OPENAI_INPUT_TOKEN_COUNT_ENDPOINT,
                "included_in_generation_cost_ceiling": False,
                "maximum_request_count": (
                    policy.max_model_calls
                    * identity.max_attempts
                    * task_count
                    * len(CAPABILITY_ARMS)
                ),
            }
        )
    return {
        "excluded_request_billing": excluded_request_billing,
        "generation_cost_ceiling_usd_micros": (identity.max_generation_cost_usd_micros),
        "scope": CAPABILITY_GENERATION_COST_SCOPE,
    }


def _parse_cost_accounting(value: object) -> dict[str, object]:
    location = "run.cost_accounting"
    raw = _mapping(
        value,
        location=location,
        keys=frozenset(
            {
                "excluded_request_billing",
                "generation_cost_ceiling_usd_micros",
                "scope",
            }
        ),
    )
    excluded: list[dict[str, object]] = []
    for index, exclusion_value in enumerate(
        _array(
            raw["excluded_request_billing"],
            location=f"{location}.excluded_request_billing",
        )
    ):
        exclusion_location = f"{location}.excluded_request_billing[{index}]"
        exclusion = _mapping(
            exclusion_value,
            location=exclusion_location,
            keys=frozenset(
                {
                    "billing_status",
                    "endpoint",
                    "included_in_generation_cost_ceiling",
                    "maximum_request_count",
                }
            ),
        )
        excluded.append(
            {
                "billing_status": _text(
                    exclusion["billing_status"],
                    location=f"{exclusion_location}.billing_status",
                ),
                "endpoint": _text(
                    exclusion["endpoint"],
                    location=f"{exclusion_location}.endpoint",
                ),
                "included_in_generation_cost_ceiling": _boolean(
                    exclusion["included_in_generation_cost_ceiling"],
                    location=(
                        f"{exclusion_location}.included_in_generation_cost_ceiling"
                    ),
                ),
                "maximum_request_count": _integer(
                    exclusion["maximum_request_count"],
                    location=f"{exclusion_location}.maximum_request_count",
                ),
            }
        )
    return {
        "excluded_request_billing": excluded,
        "generation_cost_ceiling_usd_micros": _integer(
            raw["generation_cost_ceiling_usd_micros"],
            location=f"{location}.generation_cost_ceiling_usd_micros",
        ),
        "scope": _text(raw["scope"], location=f"{location}.scope"),
    }


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
            "capability result requires complete provider-native usage buckets"
        )
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens = cast(
        tuple[int, int, int, int],
        provider_buckets,
    )
    if identity.cache_mode == "disabled" and (
        cache_read_tokens != 0 or cache_write_tokens != 0
    ):
        raise CapabilityEvaluationError(
            "disabled cache mode cannot record cache token buckets"
        )
    if (
        budget.model_calls < 1
        or budget.charged_tokens
        != input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    ):
        raise CapabilityEvaluationError(
            "provider-native usage differs from the shared RunBudget ledger"
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
    root_capability_calls = budget.quickjs_calls + budget.task_calls
    if budget.tool_calls < root_capability_calls:
        raise CapabilityEvaluationError(
            "shared RunBudget undercounts root capability calls"
        )
    delegated_tool_calls = budget.tool_calls - root_capability_calls
    if budget.task_calls == 0 and delegated_tool_calls != 0:
        raise CapabilityEvaluationError(
            "capability task recorded a non-allowlisted root tool call"
        )
    quickjs_required, subagents_required = _task_capabilities(task)
    missing_required_capability = (
        quickjs_required
        and not arm.quickjs_enabled
        or subagents_required
        and not arm.subagents_enabled
    )
    structured_unavailable = (
        observation.status == "failed"
        and observation.failure_code == "capability_unavailable"
    )
    if structured_unavailable is not missing_required_capability:
        raise CapabilityEvaluationError(
            "structured capability availability differs from the requested arm "
            f"for {arm.arm_id}/{task.task_id}"
        )
    expected_quickjs = (
        not missing_required_capability and arm.quickjs_enabled and quickjs_required
    )
    expected_subagents = (
        not missing_required_capability and arm.subagents_enabled and subagents_required
    )
    if budget.quickjs_calls != int(expected_quickjs):
        raise CapabilityEvaluationError(
            "task-level QuickJS activity differs from its requested arm capability "
            f"for {arm.arm_id}/{task.task_id}"
        )
    if budget.task_calls != int(expected_subagents):
        raise CapabilityEvaluationError(
            "task-level evidence-checker activity differs from its requested arm "
            f"capability for {arm.arm_id}/{task.task_id}"
        )
    if expected_subagents and delegated_tool_calls < 1:
        raise CapabilityEvaluationError(
            "evidence-checker completed without delegated child tool activity"
        )
    root_tool_trace = _validated_root_tool_trace(
        observation.root_tool_trace,
        location="observation.root_tool_trace",
    )
    trace_calls = tuple(event for event in root_tool_trace if event.phase == "call")
    if any(
        event.tool_name not in {QUICKJS_TOOL_NAME, TASK_TOOL_NAME}
        for event in trace_calls
    ):
        raise CapabilityEvaluationError(
            "capability task recorded a non-allowlisted root tool call"
        )
    if (
        len(trace_calls) != root_capability_calls
        or sum(event.tool_name == QUICKJS_TOOL_NAME for event in trace_calls)
        != budget.quickjs_calls
        or sum(event.tool_name == TASK_TOOL_NAME for event in trace_calls)
        != budget.task_calls
    ):
        raise CapabilityEvaluationError(
            "recorded root tool trace differs from the shared RunBudget ledger"
        )
    expected_trace_signature: list[tuple[str, str]] = []
    if expected_quickjs:
        expected_trace_signature.extend(
            (("call", QUICKJS_TOOL_NAME), ("completion", QUICKJS_TOOL_NAME))
        )
    if expected_subagents:
        expected_trace_signature.extend(
            (("call", TASK_TOOL_NAME), ("completion", TASK_TOOL_NAME))
        )
    actual_trace_signature = tuple(
        (event.phase, event.tool_name) for event in root_tool_trace
    )
    if actual_trace_signature != tuple(expected_trace_signature):
        raise CapabilityEvaluationError(
            "root tool trace differs from the exact capability chronology for "
            f"{arm.arm_id}/{task.task_id}"
        )
    delegated_subagent_types = observation.delegated_subagent_types
    if (
        not isinstance(delegated_subagent_types, tuple)
        or any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in delegated_subagent_types
        )
        or len(delegated_subagent_types) != budget.task_calls
    ):
        raise CapabilityEvaluationError(
            "recorded subagent types differ from the shared RunBudget ledger"
        )
    expected_subagent_types = ("evidence-checker",) if expected_subagents else ()
    if delegated_subagent_types != expected_subagent_types:
        raise CapabilityEvaluationError(
            "task-level evidence-checker delegation differs from its requested "
            "arm capability "
            f"for {arm.arm_id}/{task.task_id}"
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
        estimated_generation_cost_usd_micros=_estimated_generation_cost(
            identity,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_tokens,
            cache_write_input_tokens=cache_write_tokens,
        ),
        delegated_subagent_types=delegated_subagent_types,
        delegated_tool_calls=delegated_tool_calls,
        root_tool_trace=root_tool_trace,
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
        estimated_generation_cost_usd_micros=sum(
            task.estimated_generation_cost_usd_micros for task in tasks
        ),
    )


def _run_id(
    *,
    dataset: CapabilityTaskSet,
    executor: CapabilityExecutorIdentity,
    policy: RunBudgetPolicy,
    provenance: RunProvenance,
    evidence_status: str,
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
        "evidence_status": evidence_status,
        "executor": executor.as_dict(),
        "provenance": provenance.as_dict(),
        "runner": CAPABILITY_RUNNER_ID,
        "schema": CAPABILITY_RUN_SCHEMA,
    }
    return json_checksum(canonical_json_bytes(payload))


def _terminal_attempt_budget(
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
    return snapshot


def _finalize_attempt_budget(
    budget: RunBudget,
    *,
    arm: CapabilityArm,
    task: CapabilityTask,
) -> BudgetSnapshot:
    """Finalize a successful observation and require exact provider usage."""

    label = f"{arm.arm_id}/{task.task_id}"
    snapshot = _terminal_attempt_budget(budget, arm=arm, task=task)
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
            f"executor returned incomplete provider-native usage for {label}"
        )
    if sum(cast(tuple[int, int, int, int], provider_buckets)) != (
        snapshot.charged_tokens
    ):
        raise CapabilityEvaluationError(
            f"executor provider usage differs from RunBudget for {label}"
        )
    return snapshot


def _finalize_failed_attempt_budget(
    budget: RunBudget,
    *,
    arm: CapabilityArm,
    task: CapabilityTask,
) -> BudgetSnapshot:
    """Finalize failure counters without claiming unavailable provider usage."""

    return _terminal_attempt_budget(budget, arm=arm, task=task)


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
    evidence_status: str = CAPABILITY_EVIDENCE_STATUS,
    provenance: RunProvenance | None = None,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    budget_factory: Callable[[RunBudgetPolicy], RunBudget] = RunBudget,
) -> CapabilityRun:
    """Run all four arms or fail without returning a partial experiment."""

    dataset = _validated_taskset(dataset, location="experiment dataset")
    if not isinstance(executor_identity, CapabilityExecutorIdentity):
        raise CapabilityEvaluationError("executor identity is required")
    evidence_status = _evidence_status(
        evidence_status,
        location="experiment evidence status",
    )
    _validate_evidence_contract(evidence_status, executor_identity)
    _validate_executor_evidence_contract(evidence_status, executor)
    budget_policy = _validated_capability_policy(budget_policy)
    worst_case_cost = _worst_case_generation_cost(
        executor_identity,
        policy=budget_policy,
        task_count=len(dataset.tasks),
    )
    if worst_case_cost > executor_identity.max_generation_cost_usd_micros:
        raise CapabilityEvaluationError(
            "worst-case generation-token cost exceeds the explicit ceiling"
        )
    measured_provenance = provenance or collect_run_provenance()

    task_results_by_arm: dict[str, list[CapabilityTaskResult]] = {
        arm.arm_id: [] for arm in CAPABILITY_ARMS
    }
    seen_attempt_ids: set[str] = set()
    seen_thread_ids: set[str] = set()
    seen_graph_run_ids: set[UUID] = set()
    for task_index, task in enumerate(dataset.tasks):
        expected_task_payload = canonical_json_bytes(task.as_dict())
        for arm in _counterbalanced_arms(
            executor_identity,
            task_index=task_index,
        ):
            for attempt_number in range(1, executor_identity.max_attempts + 1):
                attempt_task = _isolated_task(task)
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
                    task=attempt_task,
                    budget=budget,
                    content_tree_sha=dataset.content_tree_sha,
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
                failure_cause: Exception | None = None
                failure_diagnostic: tuple[str, str, tuple[str, ...]] | None = None
                try:
                    async with asyncio.timeout(budget.remaining_seconds()):
                        observation = await executor.execute(context)
                except TimeoutError as exc:
                    _require_task_unchanged(
                        attempt_task,
                        expected_payload=expected_task_payload,
                    )
                    budget.exhaust()
                    raise CapabilityEvaluationError(
                        "executor exceeded the complete RunBudget deadline for "
                        f"{arm.arm_id}/{task.task_id}"
                    ) from exc
                except Exception as exc:
                    if isinstance(exc, CapabilityExecutorDiagnosticError):
                        failure_diagnostic = _sanitized_executor_diagnostic(exc)
                    else:
                        failure_cause = exc
                if failure_cause is not None or failure_diagnostic is not None:
                    _require_task_unchanged(
                        attempt_task,
                        expected_payload=expected_task_payload,
                    )
                    snapshot = _finalize_failed_attempt_budget(
                        budget,
                        arm=arm,
                        task=task,
                    )
                    if (
                        attempt_number < executor_identity.max_attempts
                        and _attempt_has_zero_spend(snapshot)
                    ):
                        failure_cause = None
                        continue
                    diagnostic = ""
                    if failure_diagnostic is not None:
                        phase, reason_code, safe_root_events = failure_diagnostic
                        root_events = ",".join(safe_root_events) or "none"
                        diagnostic = (
                            f"; phase={phase}; reason={reason_code}; "
                            "budget_counts="
                            f"model:{snapshot.model_calls},"
                            f"tool:{snapshot.tool_calls},"
                            f"quickjs:{snapshot.quickjs_calls},"
                            f"task:{snapshot.task_calls}; "
                            f"root_tool_events={root_events}"
                        )
                    failure_message = (
                        "executor failed before a complete observation for "
                        f"{arm.arm_id}/{task.task_id}{diagnostic}"
                    )
                    if failure_diagnostic is not None:
                        failure_diagnostic = None
                        raise CapabilityEvaluationError(failure_message)
                    assert failure_cause is not None
                    raise CapabilityEvaluationError(failure_message) from failure_cause
                _require_task_unchanged(
                    attempt_task,
                    expected_payload=expected_task_payload,
                )
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
    actual_cost = sum(arm.metrics.estimated_generation_cost_usd_micros for arm in arms)
    if actual_cost > executor_identity.max_generation_cost_usd_micros:
        raise CapabilityEvaluationError(
            "capability generation-token cost exceeds the explicit ceiling"
        )
    return CapabilityRun(
        run_id=_run_id(
            dataset=dataset,
            executor=executor_identity,
            policy=budget_policy,
            provenance=measured_provenance,
            evidence_status=evidence_status,
        ),
        dataset=dataset,
        executor=executor_identity,
        evidence_status=evidence_status,
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
                "content_tree_sha",
                "execution_id",
                "executor_id",
                "max_attempts",
                "max_generation_cost_usd_micros",
                "model_id",
                "pricing",
                "provider_contract",
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
            content_tree_sha=_text(
                raw["content_tree_sha"],
                location="run.executor.content_tree_sha",
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
            max_generation_cost_usd_micros=_integer(
                raw["max_generation_cost_usd_micros"],
                location="run.executor.max_generation_cost_usd_micros",
            ),
            model_id=_text(raw["model_id"], location="run.executor.model_id"),
            provider_contract=_text(
                raw["provider_contract"],
                location="run.executor.provider_contract",
            ),
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
        return _validated_capability_policy(RunBudgetPolicy(**values))
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
        count_risk_tokens=_integer(
            raw["count_risk_tokens"],
            location=f"{location}.count_risk_tokens",
        ),
        count_risk_tokens_in_flight=_integer(
            raw["count_risk_tokens_in_flight"],
            location=f"{location}.count_risk_tokens_in_flight",
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
        "count_risk_tokens": policy.max_count_risk_tokens_per_run,
        "count_risk_tokens_in_flight": policy.max_count_risk_tokens_per_run,
    }
    if (
        snapshot.policy_id != policy.policy_id
        or any(getattr(snapshot, field) > maximum for field, maximum in limits.items())
        or snapshot.elapsed_ms >= policy.max_elapsed_seconds * 1_000
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


def _parse_root_tool_trace(
    value: object,
    *,
    location: str,
) -> tuple[RootToolTraceEvent, ...]:
    events: list[RootToolTraceEvent] = []
    for index, event_value in enumerate(_array(value, location=location)):
        event_location = f"{location}[{index}]"
        raw = _mapping(
            event_value,
            location=event_location,
            keys=frozenset({"message_index", "phase", "tool_call_id", "tool_name"}),
        )
        events.append(
            RootToolTraceEvent(
                message_index=_integer(
                    raw["message_index"],
                    location=f"{event_location}.message_index",
                ),
                phase=_text(raw["phase"], location=f"{event_location}.phase"),
                tool_call_id=_text(
                    raw["tool_call_id"],
                    location=f"{event_location}.tool_call_id",
                ),
                tool_name=_text(
                    raw["tool_name"],
                    location=f"{event_location}.tool_name",
                ),
            )
        )
    return _validated_root_tool_trace(
        tuple(events),
        location=location,
    )


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
                "delegated_subagent_types",
                "delegated_tool_calls",
                "estimated_generation_cost_usd_micros",
                "failure_code",
                "graph_run_id",
                "input_tokens",
                "latency_ms",
                "output_tokens",
                "persistence_empty",
                "root_tool_trace",
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
        delegated_subagent_types=tuple(
            _text(
                item,
                location=f"{location}.delegated_subagent_types[{index}]",
            )
            for index, item in enumerate(
                _array(
                    raw["delegated_subagent_types"],
                    location=f"{location}.delegated_subagent_types",
                )
            )
        ),
        root_tool_trace=_parse_root_tool_trace(
            raw["root_tool_trace"],
            location=f"{location}.root_tool_trace",
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
    estimated_generation_cost = _integer(
        raw["estimated_generation_cost_usd_micros"],
        location=f"{location}.estimated_generation_cost_usd_micros",
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
    delegated_tool_calls = _integer(
        raw["delegated_tool_calls"],
        location=f"{location}.delegated_tool_calls",
    )
    if (
        task_success is not result.task_success
        or citation_correct is not result.citation_correct
        or estimated_generation_cost != result.estimated_generation_cost_usd_micros
        or input_tokens != result.input_tokens
        or output_tokens != result.output_tokens
        or cache_read_tokens != result.cache_read_input_tokens
        or cache_write_tokens != result.cache_write_input_tokens
        or delegated_tool_calls != result.delegated_tool_calls
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
                "cost_accounting",
                "dataset",
                "evidence_status",
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
    evidence_status = _evidence_status(
        raw["evidence_status"],
        location="run.evidence_status",
    )
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
    _validate_evidence_contract(evidence_status, identity)
    policy = _parse_policy(raw["budget_policy"])
    expected_cost_accounting = _cost_accounting(
        evidence_status=evidence_status,
        identity=identity,
        policy=policy,
        task_count=len(dataset.tasks),
    )
    if _parse_cost_accounting(raw["cost_accounting"]) != expected_cost_accounting:
        raise CapabilityEvaluationError(
            "capability run cost accounting differs from its scoped contract"
        )
    if identity.content_tree_sha != dataset.content_tree_sha:
        raise CapabilityEvaluationError(
            "executor content tree differs from the supplied task-set"
        )
    if (
        _worst_case_generation_cost(
            identity,
            policy=policy,
            task_count=len(dataset.tasks),
        )
        > identity.max_generation_cost_usd_micros
    ):
        raise CapabilityEvaluationError(
            "worst-case generation-token cost exceeds the explicit ceiling"
        )
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
        evidence_status=evidence_status,
    )
    if raw["run_id"] != expected_run_id:
        raise CapabilityEvaluationError(
            "capability run ID differs from its canonical experiment inputs"
        )
    if (
        sum(arm.metrics.estimated_generation_cost_usd_micros for arm in arms)
        > identity.max_generation_cost_usd_micros
    ):
        raise CapabilityEvaluationError(
            "capability generation-token cost exceeds the explicit ceiling"
        )
    return CapabilityRun(
        run_id=expected_run_id,
        dataset=dataset,
        executor=identity,
        evidence_status=evidence_status,
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


def _root_tool_trace_summary(trace: tuple[RootToolTraceEvent, ...]) -> str:
    if not trace:
        return "—"
    return " → ".join(
        f"{event.message_index}:{event.phase}:{event.tool_name}" for event in trace
    )


def render_capability_report(run: CapabilityRun) -> str:
    """Render a deterministic report that cannot be mistaken for a leaderboard."""

    if run.evidence_status == CAPABILITY_EVIDENCE_STATUS:
        evidence_banner = (
            "> **SYNTHETIC PROVIDER-FREE EVIDENCE ONLY.** This report is not "
            "provider quality/cost evidence, does not satisfy P4.5 acceptance, "
            "cannot enable a public capability, and is intentionally excluded "
            "from the retrieval leaderboard."
        )
    else:
        evidence_banner = (
            "> **PROVIDER-BACKED LOCAL EVIDENCE; UNATTESTED.** This report records "
            "bounded live provider calls, but it was not produced by a signed CI "
            "publication job, cannot enable a public capability, and remains "
            "outside the retrieval leaderboard."
        )
    cost_accounting = _cost_accounting(
        evidence_status=run.evidence_status,
        identity=run.executor,
        policy=run.budget_policy,
        task_count=len(run.dataset.tasks),
    )
    exclusions = cast(
        list[dict[str, object]],
        cost_accounting["excluded_request_billing"],
    )
    excluded_billing_line = "- Excluded request billing: none"
    if exclusions:
        exclusion = exclusions[0]
        excluded_billing_line = (
            f"- Excluded request billing: `{exclusion['endpoint']}` "
            f"(`{exclusion['billing_status']}`; outside the generation-token "
            f"ceiling; at most {exclusion['maximum_request_count']} requests)"
        )
    lines = [
        f"# Capability 2×2 report: {_markdown(run.dataset.dataset_id)}",
        "",
        evidence_banner,
        "",
        f"- Evidence status: `{run.evidence_status}`",
        f"- Run ID: `{run.run_id}`",
        f"- Task-set checksum: `{run.dataset.checksum}`",
        f"- Label status: `{run.dataset.label_status}`",
        f"- Content tree: `{run.dataset.content_tree_sha}`",
        f"- Executor: `{_markdown(run.executor.executor_id)}`",
        f"- Execution ID: `{run.executor.execution_id}`",
        f"- Model: `{_markdown(run.executor.model_id)}`",
        f"- Provider contract: `{_markdown(run.executor.provider_contract)}`",
        f"- Random seed: `{run.executor.random_seed}`",
        f"- Maximum zero-spend attempts: `{run.executor.max_attempts}`",
        f"- Cache mode: `{run.executor.cache_mode}`",
        f"- Cost scope: `{CAPABILITY_GENERATION_COST_SCOPE}`",
        f"- Explicit generation-token cost ceiling: "
        f"`{_usd(run.executor.max_generation_cost_usd_micros)}`",
        f"- Conservative worst-case generation-token cost: "
        f"`{_usd(_worst_case_generation_cost(run.executor, policy=run.budget_policy, task_count=len(run.dataset.tasks)))}`",
        excluded_billing_line,
        f"- Shared budget policy: `{_markdown(run.budget_policy.policy_id)}`",
        "",
        "## Arm summary",
        "",
        "| Arm | QuickJS | Subagents | Task success | Citation correctness | "
        "Mean latency | Model/tool/task calls | Tokens (in/out/read/write/total) | "
        "Estimated generation-token cost |",
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
            f"{_usd(metrics.estimated_generation_cost_usd_micros)} |"
        )

    lines.extend(["", "## Per-task observations", ""])
    for arm in run.arms:
        lines.extend(
            [
                f"### `{arm.arm.arm_id}`",
                "",
                "| Task | Status | Success | Citations | Latency | "
                "Model/tool/QuickJS/task/delegated | Delegated subagent types | "
                "Root tool trace | Tokens (in/out/read/write/total) | "
                "Generation-token cost |",
                "|---|---|---:|---:|---:|---:|---|---|---:|---:|",
            ]
        )
        for task in arm.tasks:
            lines.append(
                f"| `{task.task_id}` | {task.status} | "
                f"{'yes' if task.task_success else 'no'} | "
                f"{'correct' if task.citation_correct else 'incorrect'} | "
                f"{task.latency_ms} ms | "
                f"{task.budget.model_calls}/{task.budget.tool_calls}/"
                f"{task.budget.quickjs_calls}/{task.budget.task_calls}/"
                f"{task.delegated_tool_calls} | "
                f"{', '.join(task.delegated_subagent_types) or '—'} | "
                f"{_root_tool_trace_summary(task.root_tool_trace)} | "
                f"{task.input_tokens}/{task.output_tokens}/"
                f"{task.cache_read_input_tokens}/"
                f"{task.cache_write_input_tokens}/"
                f"{task.budget.charged_tokens} | "
                f"{_usd(task.estimated_generation_cost_usd_micros)} |"
            )
        lines.append("")
    lines.extend(
        [
            "Latency is monotonic elapsed time rounded to the nearest millisecond. "
            "Rates use integer parts-per-million; model cost is rounded up once per "
            "task to the nearest micro-US-dollar from finalized provider-native uncached "
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
            "evidence_status": run.evidence_status,
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
        keys=frozenset({"evidence_status", "files", "result_digest", "schema"}),
    )
    if manifest["schema"] != CAPABILITY_MANIFEST_SCHEMA:
        raise CapabilityEvaluationError("unsupported capability result manifest schema")
    manifest_evidence_status = _evidence_status(
        manifest["evidence_status"],
        location="capability result manifest.evidence_status",
    )
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
    if run.evidence_status != manifest_evidence_status:
        raise CapabilityEvaluationError(
            "capability result manifest evidence differs from the run"
        )
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
    "CAPABILITY_EVAL_SUBAGENT_NAMES",
    "CAPABILITY_EVIDENCE_STATUS",
    "CAPABILITY_GENERATION_COST_SCOPE",
    "CAPABILITY_PROVIDER_EVIDENCE_STATUS",
    "CAPABILITY_RUNNER_ID",
    "CAPABILITY_RUN_SCHEMA",
    "CAPABILITY_TASKSET_SCHEMA",
    "CapabilityArm",
    "CapabilityArtifacts",
    "CapabilityEvaluationError",
    "CapabilityExecutorDiagnosticError",
    "CapabilityExecutionContext",
    "CapabilityExecutor",
    "CapabilityExecutorIdentity",
    "CapabilityObservation",
    "CapabilityRun",
    "CapabilityTask",
    "CapabilityTaskSet",
    "RootToolTraceEvent",
    "VerifiedCapabilityRun",
    "activated_capabilities",
    "build_capability_graph",
    "load_capability_taskset",
    "parse_capability_run",
    "parse_capability_taskset",
    "recorded_root_tool_trace",
    "render_capability_report",
    "recorded_subagent_types",
    "run_capability_experiment",
    "verify_capability_run_directory",
    "write_capability_artifacts",
]
