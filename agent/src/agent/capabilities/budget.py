"""One atomic, non-persistent resource ledger for a Deep Agents run."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Literal

from langchain.agents.middleware import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain.agents.middleware.types import ToolCallRequest
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.types import Command

from agent.capabilities.token_counting import (
    InputTokenCounter,
    InputTokenCountError,
    InputTokenCountPreparer,
    PreparedInputTokenCount,
)

TASK_TOOL_NAME = "task"
MAX_TASK_DESCRIPTION_BYTES = 16_000
REQUIRED_TASK_SECTIONS = (
    "Question:",
    "Allowed corpus/method scope:",
    "Expected output schema:",
    "Stopping condition:",
)


class RunBudgetExceededError(RuntimeError):
    """Raised before a run could exceed an atomic resource limit."""


class CapabilityDeniedError(PermissionError):
    """Raised when a caller tries to use a server-disabled capability."""


class InvalidDelegationError(ValueError):
    """Raised when a task dispatch is not a complete stateless envelope."""


class RunBudgetUnsettledError(RuntimeError):
    """Raised when finalization finds an open model or task reservation."""


@dataclass(frozen=True, slots=True)
class RunBudgetPolicy:
    """Immutable limits applied to one root run and every nested specialist."""

    policy_id: str
    max_model_calls: int
    max_tool_calls: int
    max_quickjs_calls: int
    max_quickjs_in_flight: int
    max_quickjs_output_bytes: int
    max_quickjs_total_output_bytes: int
    max_task_calls: int
    max_tasks_in_flight: int
    max_depth: int
    max_output_tokens: int
    max_total_tokens: int
    max_count_risk_tokens_per_attempt: int
    max_count_risk_tokens_per_run: int
    max_elapsed_seconds: int

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_model_calls,
            self.max_tool_calls,
            self.max_quickjs_calls,
            self.max_quickjs_in_flight,
            self.max_quickjs_output_bytes,
            self.max_quickjs_total_output_bytes,
            self.max_task_calls,
            self.max_tasks_in_flight,
            self.max_depth,
            self.max_output_tokens,
            self.max_total_tokens,
            self.max_count_risk_tokens_per_attempt,
            self.max_count_risk_tokens_per_run,
            self.max_elapsed_seconds,
        )
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 1
                for value in integer_limits
            )
            or self.max_output_tokens > self.max_total_tokens
            or self.max_count_risk_tokens_per_attempt
            > self.max_count_risk_tokens_per_run
            or self.max_quickjs_output_bytes > self.max_quickjs_total_output_bytes
        ):
            raise ValueError("run budget policy limits must be positive and coherent")


DEFAULT_RUN_BUDGET_POLICY = RunBudgetPolicy(
    policy_id="owner-capability-lab-v3",
    max_model_calls=12,
    max_tool_calls=24,
    max_quickjs_calls=4,
    max_quickjs_in_flight=1,
    max_quickjs_output_bytes=4_096,
    max_quickjs_total_output_bytes=16_384,
    max_task_calls=2,
    max_tasks_in_flight=2,
    max_depth=1,
    max_output_tokens=2_048,
    max_total_tokens=48_000,
    max_count_risk_tokens_per_attempt=48_000,
    max_count_risk_tokens_per_run=48_000,
    max_elapsed_seconds=90,
)


@dataclass(frozen=True, slots=True)
class ModelReservation:
    """Opaque handle used to settle exactly one model reservation."""

    reservation_id: int
    reserved_tokens: int
    phase: Literal["attempt", "counted"]
    ledger_id: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class TaskReservation:
    """Opaque task slot whose token tranche may fund its first child model call."""

    reservation_id: int
    reserved_tokens: int
    ledger_id: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class _ProviderTokenUsage:
    """Trusted provider pricing buckets parsed inside model middleware."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_write_input_tokens: int

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_write_input_tokens
        )

    @property
    def total_input_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_read_input_tokens
            + self.cache_write_input_tokens
        )


@dataclass(frozen=True, slots=True)
class QuickJSReservation:
    """Opaque interpreter slot with a reserved serialized-output tranche."""

    reservation_id: int
    reserved_output_bytes: int
    ledger_id: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Bounded, serializable observation of a run ledger.

    Provider buckets are populated only when every settled model call carried
    complete provider metadata; otherwise all four are ``None`` and
    ``provider_usage_complete`` is false. ``count_risk_tokens`` records exact
    successful counts plus conservative reservations retained by failed count
    attempts; ``count_risk_tokens_in_flight`` is the still-open subset. Only
    :meth:`RunBudget.finalize` produces ``finalized=True``.
    """

    policy_id: str
    model_calls: int
    model_reservations_in_flight: int
    tool_calls: int
    quickjs_calls: int
    quickjs_in_flight: int
    quickjs_output_bytes: int
    task_calls: int
    tasks_in_flight: int
    charged_tokens: int
    count_risk_tokens: int
    count_risk_tokens_in_flight: int
    provider_input_tokens: int | None
    provider_output_tokens: int | None
    provider_cache_read_input_tokens: int | None
    provider_cache_write_input_tokens: int | None
    provider_usage_complete: bool
    elapsed_ms: int
    exhausted: bool
    finalized: bool


class RunBudget:
    """Thread-safe ledger shared by root and child middleware.

    The lock and monotonic clock deliberately make this object runtime-only.
    Only :class:`BudgetSnapshot` may cross the graph-factory boundary.
    """

    __slots__ = (
        "_charged_tokens",
        "_charged_count_risk_tokens",
        "_clock",
        "_exhausted",
        "_finalized_snapshot",
        "_ledger_id",
        "_lock",
        "_model_calls",
        "_model_count_risk_reservations",
        "_model_reservations_needing_input",
        "_next_reservation_id",
        "_next_quickjs_reservation_id",
        "_next_task_reservation_id",
        "_open_model_reservations",
        "_open_quickjs_reservations",
        "_open_task_reservations",
        "_policy",
        "_provider_cache_read_input_tokens",
        "_provider_cache_write_input_tokens",
        "_provider_input_tokens",
        "_provider_output_tokens",
        "_provider_usage_complete",
        "_started_at",
        "_quickjs_calls",
        "_quickjs_in_flight",
        "_quickjs_output_bytes",
        "_task_calls",
        "_tasks_in_flight",
        "_terminal",
        "_tool_calls",
    )

    def __init__(
        self,
        policy: RunBudgetPolicy = DEFAULT_RUN_BUDGET_POLICY,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(policy, RunBudgetPolicy):
            raise TypeError("policy must be a RunBudgetPolicy")
        self._policy = policy
        self._clock = clock
        self._started_at = clock()
        self._ledger_id = object()
        self._lock = Lock()
        self._model_calls = 0
        self._tool_calls = 0
        self._quickjs_calls = 0
        self._quickjs_in_flight = 0
        self._quickjs_output_bytes = 0
        self._task_calls = 0
        self._tasks_in_flight = 0
        self._charged_tokens = 0
        self._charged_count_risk_tokens = 0
        self._next_reservation_id = 0
        self._open_model_reservations: dict[int, int] = {}
        self._model_reservations_needing_input: set[int] = set()
        self._model_count_risk_reservations: dict[int, int] = {}
        self._next_quickjs_reservation_id = 0
        self._open_quickjs_reservations: dict[int, int] = {}
        self._next_task_reservation_id = 0
        self._open_task_reservations: dict[int, bool] = {}
        self._exhausted = False
        self._terminal = False
        self._finalized_snapshot: BudgetSnapshot | None = None
        self._provider_input_tokens = 0
        self._provider_output_tokens = 0
        self._provider_cache_read_input_tokens = 0
        self._provider_cache_write_input_tokens = 0
        self._provider_usage_complete = True

    @property
    def policy(self) -> RunBudgetPolicy:
        return self._policy

    def __getstate__(self) -> None:
        raise TypeError("RunBudget is run-local and must not be serialized")

    def _elapsed_locked(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def _require_time_locked(self) -> None:
        if self._elapsed_locked() >= self._policy.max_elapsed_seconds:
            self._exhausted = True
            raise RunBudgetExceededError("run elapsed-time budget exhausted")

    def _require_active_locked(self) -> None:
        if self._exhausted:
            raise RunBudgetExceededError("run budget is already exhausted")
        if self._finalized_snapshot is not None:
            raise RunBudgetExceededError("run budget is already finalized")
        if self._terminal:
            raise RunBudgetExceededError("run budget is already terminal")
        self._require_time_locked()

    def remaining_seconds(self) -> float:
        with self._lock:
            self._require_active_locked()
            return self._policy.max_elapsed_seconds - self._elapsed_locked()

    def reserve_model(
        self,
        *,
        input_tokens: int = 0,
        task_reservation: TaskReservation | None = None,
    ) -> ModelReservation:
        """Atomically reserve one call, its exact input, and maximum output."""
        with self._lock:
            self._require_active_locked()
            if (
                not isinstance(input_tokens, int)
                or isinstance(input_tokens, bool)
                or input_tokens < 0
            ):
                raise ValueError("input_tokens must be a non-negative integer")
            task_tranche = self._task_tranche_locked(task_reservation)
            if self._model_calls >= self._policy.max_model_calls:
                self._exhausted = True
                raise RunBudgetExceededError("model-call budget exhausted")
            reserved = input_tokens + self._policy.max_output_tokens
            additional_charge = reserved - task_tranche
            if self._charged_tokens + additional_charge > self._policy.max_total_tokens:
                self._exhausted = True
                raise RunBudgetExceededError("token budget exhausted")

            self._model_calls += 1
            self._charged_tokens += additional_charge
            if task_tranche:
                self._open_task_reservations[task_reservation.reservation_id] = False
            self._next_reservation_id += 1
            reservation = ModelReservation(
                self._next_reservation_id,
                reserved,
                "counted",
                self._ledger_id,
            )
            self._open_model_reservations[reservation.reservation_id] = reserved
            return reservation

    def reserve_model_attempt(
        self,
        *,
        input_upper_bound: int | None = None,
        task_reservation: TaskReservation | None = None,
    ) -> ModelReservation:
        """Reserve actual output and optional count risk before remote count.

        ``None`` preserves the exact-count extension flow used by providers whose
        preparer is absent. An integer atomically reserves that amount in the
        separate count-risk ledger while output stays in the actual token ledger;
        settlement may only shrink risk after an exact count and parity check.
        """
        with self._lock:
            self._require_active_locked()
            if input_upper_bound is not None and (
                not isinstance(input_upper_bound, int)
                or isinstance(input_upper_bound, bool)
                or input_upper_bound < 0
            ):
                raise ValueError("input_upper_bound must be a non-negative integer")
            task_tranche = self._task_tranche_locked(task_reservation)
            if self._model_calls >= self._policy.max_model_calls:
                self._exhausted = True
                raise RunBudgetExceededError("model-call budget exhausted")
            if input_upper_bound is not None and (
                input_upper_bound > self._policy.max_count_risk_tokens_per_attempt
                or self._charged_count_risk_tokens + input_upper_bound
                > self._policy.max_count_risk_tokens_per_run
            ):
                self._exhausted = True
                raise RunBudgetExceededError("input count-risk budget exhausted")
            reserved = self._policy.max_output_tokens
            additional_charge = reserved - task_tranche
            if self._charged_tokens + additional_charge > self._policy.max_total_tokens:
                self._exhausted = True
                raise RunBudgetExceededError("token budget exhausted")

            self._model_calls += 1
            self._charged_tokens += additional_charge
            if task_tranche:
                self._open_task_reservations[task_reservation.reservation_id] = False
            self._next_reservation_id += 1
            reservation = ModelReservation(
                self._next_reservation_id,
                reserved,
                "attempt",
                self._ledger_id,
            )
            self._open_model_reservations[reservation.reservation_id] = reserved
            self._model_reservations_needing_input.add(reservation.reservation_id)
            if input_upper_bound is not None:
                self._charged_count_risk_tokens += input_upper_bound
                self._model_count_risk_reservations[reservation.reservation_id] = (
                    input_upper_bound
                )
            return reservation

    def reserve_model_input(
        self,
        reservation: ModelReservation,
        *,
        input_tokens: int,
    ) -> ModelReservation:
        """Extend a pre-count attempt with its exact provider-counted input."""
        with self._lock:
            self._require_active_locked()
            if (
                not isinstance(reservation, ModelReservation)
                or not isinstance(reservation.reservation_id, int)
                or isinstance(reservation.reservation_id, bool)
                or not isinstance(reservation.reserved_tokens, int)
                or isinstance(reservation.reserved_tokens, bool)
                or reservation.phase != "attempt"
                or reservation.ledger_id is not self._ledger_id
            ):
                raise TypeError("reservation must be a ModelReservation")
            if (
                reservation.reservation_id not in self._model_reservations_needing_input
                or self._open_model_reservations.get(reservation.reservation_id)
                != reservation.reserved_tokens
            ):
                raise RuntimeError(
                    "model attempt reservation is unknown or already extended"
                )
            if (
                not isinstance(input_tokens, int)
                or isinstance(input_tokens, bool)
                or input_tokens < 0
            ):
                raise ValueError("input_tokens must be a non-negative integer")
            input_upper_bound = self._model_count_risk_reservations.get(
                reservation.reservation_id
            )
            if input_upper_bound is None:
                if reservation.reserved_tokens != self._policy.max_output_tokens:
                    raise RuntimeError(
                        "model attempt reservation has an invalid output tranche"
                    )
                if self._charged_tokens + input_tokens > self._policy.max_total_tokens:
                    self._exhausted = True
                    raise RunBudgetExceededError("token budget exhausted")
                reserved = reservation.reserved_tokens + input_tokens
                self._charged_tokens += input_tokens
            else:
                if reservation.reserved_tokens != self._policy.max_output_tokens:
                    raise RuntimeError(
                        "count-risk model attempt has an invalid output tranche"
                    )
                if input_tokens > input_upper_bound:
                    self._exhausted = True
                    raise RunBudgetExceededError(
                        "provider input count exceeded the local reservation"
                    )
                if self._charged_tokens + input_tokens > self._policy.max_total_tokens:
                    self._exhausted = True
                    raise RunBudgetExceededError("token budget exhausted")
                refund = input_upper_bound - input_tokens
                reserved = reservation.reserved_tokens + input_tokens
                self._charged_tokens += input_tokens
                self._charged_count_risk_tokens -= refund
            self._open_model_reservations[reservation.reservation_id] = reserved
            self._model_reservations_needing_input.remove(reservation.reservation_id)
            self._model_count_risk_reservations.pop(
                reservation.reservation_id,
                None,
            )
            return ModelReservation(
                reservation.reservation_id,
                reserved,
                "counted",
                self._ledger_id,
            )

    def _task_tranche_locked(
        self,
        task_reservation: TaskReservation | None,
    ) -> int:
        if task_reservation is None:
            return 0
        if (
            not isinstance(task_reservation, TaskReservation)
            or not isinstance(task_reservation.reservation_id, int)
            or isinstance(task_reservation.reservation_id, bool)
            or not isinstance(task_reservation.reserved_tokens, int)
            or isinstance(task_reservation.reserved_tokens, bool)
            or task_reservation.ledger_id is not self._ledger_id
        ):
            raise TypeError("task_reservation must be a TaskReservation")
        reservation_id = task_reservation.reservation_id
        if (
            reservation_id not in self._open_task_reservations
            or task_reservation.reserved_tokens != self._policy.max_output_tokens
        ):
            raise RuntimeError("task reservation is unknown or invalid")
        if self._open_task_reservations[reservation_id]:
            return task_reservation.reserved_tokens
        return 0

    def settle_model(
        self,
        reservation: ModelReservation,
        *,
        actual_tokens: int | None,
    ) -> None:
        """Settle a caller-known total without claiming trusted provider buckets."""
        self._settle_model(
            reservation,
            actual_tokens=actual_tokens,
            provider_usage=None,
        )

    def _settle_model_response(
        self,
        reservation: ModelReservation,
        response: Any,
        *,
        model_provider: str,
        expected_response_models: frozenset[str],
    ) -> None:
        """Settle totals and pricing buckets parsed from the provider response."""
        try:
            provider_usage = _provider_token_usage(
                response,
                model_provider=model_provider,
                expected_response_models=expected_response_models,
            )
            actual_tokens = _actual_token_usage(response)
        except Exception as exc:
            try:
                self._settle_model(
                    reservation,
                    actual_tokens=None,
                    provider_usage=None,
                    require_provider_usage=True,
                )
            except RunBudgetExceededError as failure:
                raise failure from exc
            raise AssertionError("fail-closed settlement did not raise") from exc
        self._settle_model(
            reservation,
            actual_tokens=actual_tokens,
            provider_usage=provider_usage,
            require_provider_usage=model_provider == "openai",
            expected_provider_input_tokens=(
                reservation.reserved_tokens - self._policy.max_output_tokens
                if model_provider == "openai"
                else None
            ),
        )

    def _settle_model(
        self,
        reservation: ModelReservation,
        *,
        actual_tokens: int | None,
        provider_usage: _ProviderTokenUsage | None,
        require_provider_usage: bool = False,
        expected_provider_input_tokens: int | None = None,
    ) -> None:
        """Settle one reservation; missing usage retains the full charge."""
        with self._lock:
            if (
                not isinstance(reservation, ModelReservation)
                or not isinstance(reservation.reservation_id, int)
                or isinstance(reservation.reservation_id, bool)
                or not isinstance(reservation.reserved_tokens, int)
                or isinstance(reservation.reserved_tokens, bool)
                or reservation.phase not in {"attempt", "counted"}
                or reservation.ledger_id is not self._ledger_id
            ):
                raise TypeError("reservation must be a ModelReservation")
            reserved = self._open_model_reservations.get(reservation.reservation_id)
            needs_input = (
                reservation.reservation_id in self._model_reservations_needing_input
            )
            expected_phase = "attempt" if needs_input else "counted"
            if (
                reserved is None
                or reserved != reservation.reserved_tokens
                or reservation.phase != expected_phase
            ):
                raise RuntimeError("model reservation is unknown or already settled")
            del self._open_model_reservations[reservation.reservation_id]
            self._model_reservations_needing_input.discard(reservation.reservation_id)
            self._model_count_risk_reservations.pop(
                reservation.reservation_id,
                None,
            )
            if needs_input and (
                actual_tokens is not None or provider_usage is not None
            ):
                self._provider_usage_complete = False
                self._exhausted = True
                raise RunBudgetExceededError(
                    "model response arrived without an exact input reservation"
                )
            if provider_usage is None:
                self._provider_usage_complete = False
                if require_provider_usage:
                    self._exhausted = True
                    raise RunBudgetExceededError(
                        "provider response left the exact usage contract"
                    )
            elif (
                not isinstance(provider_usage, _ProviderTokenUsage)
                or actual_tokens != provider_usage.total_tokens
                or (
                    expected_provider_input_tokens is not None
                    and provider_usage.total_input_tokens
                    != expected_provider_input_tokens
                )
            ):
                self._provider_usage_complete = False
                self._exhausted = True
                raise RunBudgetExceededError(
                    "provider returned inconsistent token usage buckets"
                )
            else:
                self._provider_input_tokens += provider_usage.input_tokens
                self._provider_output_tokens += provider_usage.output_tokens
                self._provider_cache_read_input_tokens += (
                    provider_usage.cache_read_input_tokens
                )
                self._provider_cache_write_input_tokens += (
                    provider_usage.cache_write_input_tokens
                )
            if actual_tokens is None:
                return
            if (
                not isinstance(actual_tokens, int)
                or isinstance(actual_tokens, bool)
                or actual_tokens < 0
            ):
                self._exhausted = True
                raise RunBudgetExceededError("provider returned invalid token usage")

            settled = self._charged_tokens - reserved + actual_tokens
            if actual_tokens > reserved:
                self._charged_tokens = min(
                    settled,
                    self._policy.max_total_tokens,
                )
                self._exhausted = True
                raise RunBudgetExceededError(
                    "provider usage exceeded the exact model reservation"
                )
            if settled > self._policy.max_total_tokens:
                self._charged_tokens = self._policy.max_total_tokens
                self._exhausted = True
                raise RunBudgetExceededError("provider usage exceeded the token budget")
            self._charged_tokens = settled

    def reserve_tool(self) -> None:
        """Atomically reserve one non-task tool call."""
        with self._lock:
            self._require_active_locked()
            if self._tool_calls >= self._policy.max_tool_calls:
                self._exhausted = True
                raise RunBudgetExceededError("tool-call budget exhausted")
            self._tool_calls += 1

    def reserve_quickjs(self) -> QuickJSReservation:
        """Jointly reserve tool, execution, concurrency, time, and output bytes."""
        with self._lock:
            self._require_active_locked()
            if self._tool_calls >= self._policy.max_tool_calls:
                self._exhausted = True
                raise RunBudgetExceededError("tool-call budget exhausted")
            if self._quickjs_calls >= self._policy.max_quickjs_calls:
                self._exhausted = True
                raise RunBudgetExceededError("QuickJS execution budget exhausted")
            if self._quickjs_in_flight >= self._policy.max_quickjs_in_flight:
                self._exhausted = True
                raise RunBudgetExceededError("QuickJS concurrency budget exhausted")
            reserved = self._policy.max_quickjs_output_bytes
            if (
                self._quickjs_output_bytes + reserved
                > self._policy.max_quickjs_total_output_bytes
            ):
                self._exhausted = True
                raise RunBudgetExceededError("QuickJS output budget exhausted")

            self._tool_calls += 1
            self._quickjs_calls += 1
            self._quickjs_in_flight += 1
            self._quickjs_output_bytes += reserved
            self._next_quickjs_reservation_id += 1
            reservation = QuickJSReservation(
                self._next_quickjs_reservation_id,
                reserved,
                self._ledger_id,
            )
            self._open_quickjs_reservations[reservation.reservation_id] = reserved
            return reservation

    def settle_quickjs(
        self,
        reservation: QuickJSReservation,
        *,
        actual_output_bytes: int | None,
    ) -> None:
        """Release the execution slot and refund only measured unused output."""
        with self._lock:
            if (
                not isinstance(reservation, QuickJSReservation)
                or not isinstance(reservation.reservation_id, int)
                or isinstance(reservation.reservation_id, bool)
                or not isinstance(reservation.reserved_output_bytes, int)
                or isinstance(reservation.reserved_output_bytes, bool)
                or reservation.ledger_id is not self._ledger_id
            ):
                raise TypeError("reservation must be a QuickJSReservation")
            reserved = self._open_quickjs_reservations.pop(
                reservation.reservation_id,
                None,
            )
            if reserved is None or reserved != reservation.reserved_output_bytes:
                raise RuntimeError("QuickJS reservation is unknown or already settled")
            if self._quickjs_in_flight < 1:
                raise RuntimeError("QuickJS in-flight reservation underflow")
            self._quickjs_in_flight -= 1
            if actual_output_bytes is None:
                return
            if (
                not isinstance(actual_output_bytes, int)
                or isinstance(actual_output_bytes, bool)
                or actual_output_bytes < 0
                or actual_output_bytes > reserved
            ):
                self._exhausted = True
                raise RunBudgetExceededError(
                    "QuickJS returned output outside its reservation"
                )
            self._quickjs_output_bytes -= reserved - actual_output_bytes

    def reserve_task(self, *, depth: int) -> TaskReservation:
        """Jointly reserve tool, task-total, fan-out, depth, time, and tokens."""
        with self._lock:
            self._require_active_locked()
            if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
                raise ValueError("depth must be a positive integer")
            if depth > self._policy.max_depth:
                self._exhausted = True
                raise RunBudgetExceededError("subagent depth budget exhausted")
            if self._tool_calls >= self._policy.max_tool_calls:
                self._exhausted = True
                raise RunBudgetExceededError("tool-call budget exhausted")
            if self._task_calls >= self._policy.max_task_calls:
                self._exhausted = True
                raise RunBudgetExceededError("subagent task budget exhausted")
            if self._tasks_in_flight >= self._policy.max_tasks_in_flight:
                self._exhausted = True
                raise RunBudgetExceededError("subagent fan-out budget exhausted")
            if (
                self._charged_tokens + self._policy.max_output_tokens
                > self._policy.max_total_tokens
            ):
                self._exhausted = True
                raise RunBudgetExceededError(
                    "token budget cannot fund a subagent response"
                )

            self._tool_calls += 1
            self._task_calls += 1
            self._tasks_in_flight += 1
            self._charged_tokens += self._policy.max_output_tokens
            self._next_task_reservation_id += 1
            reservation = TaskReservation(
                self._next_task_reservation_id,
                self._policy.max_output_tokens,
                self._ledger_id,
            )
            self._open_task_reservations[reservation.reservation_id] = True
            return reservation

    def finish_task(self, reservation: TaskReservation) -> None:
        """Return only the in-flight slot; totals remain spent."""
        with self._lock:
            if (
                not isinstance(reservation, TaskReservation)
                or not isinstance(reservation.reservation_id, int)
                or isinstance(reservation.reservation_id, bool)
                or not isinstance(reservation.reserved_tokens, int)
                or isinstance(reservation.reserved_tokens, bool)
                or reservation.ledger_id is not self._ledger_id
                or reservation.reservation_id not in self._open_task_reservations
                or reservation.reserved_tokens != self._policy.max_output_tokens
            ):
                raise RuntimeError("task reservation is unknown or already finished")
            if self._tasks_in_flight < 1:
                raise RuntimeError("subagent in-flight reservation underflow")
            self._tasks_in_flight -= 1
            del self._open_task_reservations[reservation.reservation_id]

    def _snapshot_locked(
        self,
        *,
        finalized: bool,
        elapsed: float | None = None,
    ) -> BudgetSnapshot:
        observed_elapsed = self._elapsed_locked() if elapsed is None else elapsed
        elapsed_ms = min(
            int(observed_elapsed * 1_000),
            int(self._policy.max_elapsed_seconds * 1_000),
        )
        if self._provider_usage_complete:
            provider_input_tokens = self._provider_input_tokens
            provider_output_tokens = self._provider_output_tokens
            provider_cache_read_input_tokens = self._provider_cache_read_input_tokens
            provider_cache_write_input_tokens = self._provider_cache_write_input_tokens
        else:
            provider_input_tokens = None
            provider_output_tokens = None
            provider_cache_read_input_tokens = None
            provider_cache_write_input_tokens = None
        return BudgetSnapshot(
            policy_id=self._policy.policy_id,
            model_calls=min(self._model_calls, self._policy.max_model_calls),
            model_reservations_in_flight=len(self._open_model_reservations),
            tool_calls=min(self._tool_calls, self._policy.max_tool_calls),
            quickjs_calls=min(
                self._quickjs_calls,
                self._policy.max_quickjs_calls,
            ),
            quickjs_in_flight=min(
                self._quickjs_in_flight,
                self._policy.max_quickjs_in_flight,
            ),
            quickjs_output_bytes=min(
                self._quickjs_output_bytes,
                self._policy.max_quickjs_total_output_bytes,
            ),
            task_calls=min(self._task_calls, self._policy.max_task_calls),
            tasks_in_flight=min(
                self._tasks_in_flight,
                self._policy.max_tasks_in_flight,
            ),
            charged_tokens=min(
                self._charged_tokens,
                self._policy.max_total_tokens,
            ),
            count_risk_tokens=min(
                self._charged_count_risk_tokens,
                self._policy.max_count_risk_tokens_per_run,
            ),
            count_risk_tokens_in_flight=min(
                sum(self._model_count_risk_reservations.values()),
                self._policy.max_count_risk_tokens_per_run,
            ),
            provider_input_tokens=provider_input_tokens,
            provider_output_tokens=provider_output_tokens,
            provider_cache_read_input_tokens=provider_cache_read_input_tokens,
            provider_cache_write_input_tokens=provider_cache_write_input_tokens,
            provider_usage_complete=self._provider_usage_complete,
            elapsed_ms=elapsed_ms,
            exhausted=self._exhausted,
            finalized=finalized,
        )

    def snapshot(self) -> BudgetSnapshot:
        """Observe current state without making the run terminal."""
        with self._lock:
            if self._finalized_snapshot is not None:
                return self._finalized_snapshot
            return self._snapshot_locked(finalized=False)

    def finalize(self) -> BudgetSnapshot:
        """Atomically terminalize, assert settlement, and freeze one snapshot.

        Settlement remains available after an unsettled failure so in-flight
        ``finally`` blocks can release their reservations before a retry.
        """
        with self._lock:
            if self._finalized_snapshot is not None:
                return self._finalized_snapshot

            self._terminal = True
            elapsed = self._elapsed_locked()
            elapsed_expired = elapsed >= self._policy.max_elapsed_seconds
            if elapsed_expired:
                self._exhausted = True

            open_models = len(self._open_model_reservations)
            open_quickjs = len(self._open_quickjs_reservations)
            open_tasks = len(self._open_task_reservations)
            count_risk_reservation_ids = set(self._model_count_risk_reservations)
            if (
                not count_risk_reservation_ids.issubset(
                    self._model_reservations_needing_input
                )
                or not count_risk_reservation_ids.issubset(
                    self._open_model_reservations
                )
                or self._charged_count_risk_tokens
                < sum(self._model_count_risk_reservations.values())
                or self._charged_count_risk_tokens
                > self._policy.max_count_risk_tokens_per_run
            ):
                self._exhausted = True
                raise RunBudgetUnsettledError(
                    "run budget count-risk ledger is inconsistent"
                )
            if open_models or open_quickjs or open_tasks:
                raise RunBudgetUnsettledError(
                    "run budget has "
                    f"{open_models} model, {open_quickjs} QuickJS, and "
                    f"{open_tasks} task reservations in flight"
                )
            if elapsed_expired:
                raise RunBudgetExceededError("run elapsed-time budget exhausted")

            snapshot = self._snapshot_locked(finalized=True, elapsed=elapsed)
            self._finalized_snapshot = snapshot
            return snapshot

    def exhaust(self) -> None:
        """Mark a fail-closed preflight failure without spending a counter."""
        with self._lock:
            if self._finalized_snapshot is not None:
                raise RunBudgetExceededError("run budget is already finalized")
            self._exhausted = True


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, Mapping):
        name = tool.get("name")
        if isinstance(name, str):
            return name
        function = tool.get("function")
        if isinstance(function, Mapping) and isinstance(function.get("name"), str):
            return function["name"]
        return None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def _model_messages(response: Any) -> list[BaseMessage]:
    if isinstance(response, ExtendedModelResponse):
        response = response.model_response
    if isinstance(response, ModelResponse):
        return list(response.result)
    if isinstance(response, AIMessage):
        return [response]
    return []


def _actual_token_usage(response: Any) -> int | None:
    messages = _model_messages(response)
    if not messages:
        return None
    totals: list[int] = []
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, Mapping):
            return None
        total = usage.get("total_tokens")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            return None
        if "input_tokens" in usage or "output_tokens" in usage:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if (
                not isinstance(input_tokens, int)
                or isinstance(input_tokens, bool)
                or input_tokens < 0
                or not isinstance(output_tokens, int)
                or isinstance(output_tokens, bool)
                or output_tokens < 0
                or input_tokens + output_tokens != total
            ):
                return None
        totals.append(total)
    return sum(totals)


_ANTHROPIC_CACHE_CREATION_TTL_KEYS = (
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
)
_ANTHROPIC_INPUT_DETAIL_KEYS = frozenset(
    {
        "cache_creation",
        "cache_read",
        *_ANTHROPIC_CACHE_CREATION_TTL_KEYS,
    }
)
_OPENAI_INPUT_DETAIL_KEYS = frozenset({"cache_creation", "cache_read"})
_OPENAI_OUTPUT_DETAIL_KEYS = frozenset({"reasoning"})


def _provider_token_usage(
    response: Any,
    *,
    model_provider: str,
    expected_response_models: frozenset[str],
) -> _ProviderTokenUsage | None:
    """Dispatch only from the server-owned provider, never metadata shape."""
    if model_provider == "anthropic":
        return _anthropic_provider_token_usage(response)
    if model_provider == "openai":
        return _openai_provider_token_usage(
            response,
            expected_response_models=expected_response_models,
        )
    return None


def _anthropic_provider_token_usage(response: Any) -> _ProviderTokenUsage | None:
    """Parse exact Anthropic pricing buckets from normalized message metadata.

    LangChain's ``input_tokens`` includes uncached input, cache reads, and cache
    writes. Cache creation may be reported as one generic bucket or as the
    current Anthropic five-minute and one-hour TTL buckets. Any missing,
    negative, unknown, or internally inconsistent detail makes the complete
    aggregate unavailable.
    """
    messages = _model_messages(response)
    if not messages:
        return None

    input_tokens_total = 0
    output_tokens_total = 0
    cache_read_total = 0
    cache_write_total = 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, Mapping):
            return None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        if (
            not _is_non_negative_integer(input_tokens)
            or not _is_non_negative_integer(output_tokens)
            or not _is_non_negative_integer(total_tokens)
            or input_tokens + output_tokens != total_tokens
        ):
            return None

        details = usage.get("input_token_details")
        if (
            not isinstance(details, Mapping)
            or any(not isinstance(key, str) for key in details)
            or not set(details).issubset(_ANTHROPIC_INPUT_DETAIL_KEYS)
        ):
            return None
        cache_read = details.get("cache_read")
        generic_cache_write = details.get("cache_creation")
        if not _is_non_negative_integer(cache_read) or not _is_non_negative_integer(
            generic_cache_write
        ):
            return None

        ttl_values: list[int] = []
        for key in _ANTHROPIC_CACHE_CREATION_TTL_KEYS:
            if key not in details:
                continue
            value = details[key]
            if not _is_non_negative_integer(value):
                return None
            ttl_values.append(value)
        if ttl_values and len(ttl_values) != len(_ANTHROPIC_CACHE_CREATION_TTL_KEYS):
            return None
        specific_cache_write = sum(ttl_values)
        if specific_cache_write > 0:
            if generic_cache_write != 0:
                return None
            cache_write = specific_cache_write
        else:
            cache_write = generic_cache_write

        if cache_read + cache_write > input_tokens:
            return None
        input_tokens_total += input_tokens - cache_read - cache_write
        output_tokens_total += output_tokens
        cache_read_total += cache_read
        cache_write_total += cache_write

    return _ProviderTokenUsage(
        input_tokens=input_tokens_total,
        output_tokens=output_tokens_total,
        cache_read_input_tokens=cache_read_total,
        cache_write_input_tokens=cache_write_total,
    )


def _openai_provider_token_usage(
    response: Any,
    *,
    expected_response_models: frozenset[str],
) -> _ProviderTokenUsage | None:
    """Parse exact OpenAI Responses pricing buckets for the pinned guest model."""
    messages = _model_messages(response)
    if not messages or not expected_response_models:
        return None

    input_tokens_total = 0
    output_tokens_total = 0
    cache_read_total = 0
    cache_write_total = 0
    for message in messages:
        response_metadata = getattr(message, "response_metadata", None)
        response_model = (
            response_metadata.get("model_name")
            if isinstance(response_metadata, Mapping)
            else None
        )
        if (
            not isinstance(response_metadata, Mapping)
            or response_metadata.get("model_provider") != "openai"
            or not isinstance(response_model, str)
            or response_model not in expected_response_models
        ):
            return None

        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, Mapping):
            return None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        if (
            not _is_non_negative_integer(input_tokens)
            or not _is_non_negative_integer(output_tokens)
            or not _is_non_negative_integer(total_tokens)
            or input_tokens + output_tokens != total_tokens
        ):
            return None

        input_details = usage.get("input_token_details")
        output_details = usage.get("output_token_details")
        if (
            not isinstance(input_details, Mapping)
            or set(input_details) != _OPENAI_INPUT_DETAIL_KEYS
            or not isinstance(output_details, Mapping)
            or set(output_details) != _OPENAI_OUTPUT_DETAIL_KEYS
        ):
            return None
        cache_read = input_details.get("cache_read")
        cache_creation = input_details.get("cache_creation")
        reasoning = output_details.get("reasoning")
        if (
            not _is_non_negative_integer(cache_read)
            or not _is_non_negative_integer(cache_creation)
            or reasoning != 0
            or cache_read + cache_creation > input_tokens
        ):
            return None

        input_tokens_total += input_tokens - cache_read - cache_creation
        output_tokens_total += output_tokens
        cache_read_total += cache_read
        cache_write_total += cache_creation

    return _ProviderTokenUsage(
        input_tokens=input_tokens_total,
        output_tokens=output_tokens_total,
        cache_read_input_tokens=cache_read_total,
        cache_write_input_tokens=cache_write_total,
    )


def _is_non_negative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _tool_message_output_bytes(result: object) -> int | None:
    if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
        return None
    try:
        return len(result.content.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _validate_task_call(
    tool_call: Mapping[str, Any],
    *,
    allowed_subagents: frozenset[str],
) -> None:
    args = tool_call.get("args")
    if not isinstance(args, Mapping) or set(args) != {
        "description",
        "subagent_type",
    }:
        raise InvalidDelegationError(
            "task requires exactly description and subagent_type"
        )
    description = args.get("description")
    subagent_type = args.get("subagent_type")
    if not isinstance(description, str) or not description.strip():
        raise InvalidDelegationError("task description is empty or too large")
    try:
        description_size = len(description.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InvalidDelegationError("task description is not valid UTF-8") from exc
    if description_size > MAX_TASK_DESCRIPTION_BYTES:
        raise InvalidDelegationError("task description is empty or too large")
    if not isinstance(subagent_type, str) or subagent_type not in allowed_subagents:
        raise InvalidDelegationError("task subagent_type is not server-declared")

    lines = description.splitlines()
    section_indexes: list[int] = []
    for section in REQUIRED_TASK_SECTIONS:
        matches = [index for index, line in enumerate(lines) if line == section]
        if len(matches) != 1:
            raise InvalidDelegationError(
                "task description must contain each exact section once"
            )
        section_indexes.append(matches[0])
    if section_indexes != sorted(section_indexes) or any(
        line.strip() for line in lines[: section_indexes[0]]
    ):
        raise InvalidDelegationError(
            "task description must contain the complete stateless envelope"
        )
    section_ends = [*section_indexes[1:], len(lines)]
    for start, end in zip(section_indexes, section_ends, strict=True):
        if not any(line.strip() for line in lines[start + 1 : end]):
            raise InvalidDelegationError(
                "task description sections require non-whitespace content"
            )


_ACTIVE_TASK_RESERVATION: ContextVar[TaskReservation | None] = ContextVar(
    "active_run_budget_task_reservation",
    default=None,
)


class RunBudgetMiddleware(AgentMiddleware[Any, Any, Any]):
    """Apply one shared ledger to async root and child model/tool calls."""

    def __init__(
        self,
        budget: RunBudget,
        *,
        depth: int,
        allow_subagents: bool,
        allowed_subagents: frozenset[str],
        input_token_counter: InputTokenCounter,
        input_token_count_preparer: InputTokenCountPreparer | None = None,
        model_provider: str = "anthropic",
        expected_response_models: frozenset[str] = frozenset(),
        quickjs_tool_name: str | None = None,
        allow_quickjs: bool = False,
        root_tool_allowlist: frozenset[str] | None = None,
        root_tool_denylist: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        if quickjs_tool_name is not None and (
            not isinstance(quickjs_tool_name, str) or not quickjs_tool_name
        ):
            raise ValueError("quickjs_tool_name must be a non-empty string or None")
        if not isinstance(allow_quickjs, bool):
            raise TypeError("allow_quickjs must be a boolean")
        if allow_quickjs and quickjs_tool_name is None:
            raise ValueError("allow_quickjs requires quickjs_tool_name")
        if input_token_count_preparer is not None and not callable(
            input_token_count_preparer
        ):
            raise TypeError("input_token_count_preparer must be callable or None")
        if root_tool_allowlist is not None and (
            depth != 0
            or not isinstance(root_tool_allowlist, frozenset)
            or any(
                not isinstance(tool_name, str) or not tool_name
                for tool_name in root_tool_allowlist
            )
        ):
            raise ValueError(
                "root_tool_allowlist must be a root-only frozenset of tool names"
            )
        if (
            not isinstance(root_tool_denylist, frozenset)
            or any(
                not isinstance(tool_name, str) or not tool_name
                for tool_name in root_tool_denylist
            )
            or (root_tool_denylist and depth != 0)
            or (
                root_tool_allowlist is not None
                and not root_tool_allowlist.isdisjoint(root_tool_denylist)
            )
        ):
            raise ValueError(
                "root_tool_denylist must be a disjoint root-only frozenset of "
                "tool names"
            )
        if model_provider not in {"anthropic", "openai"}:
            raise ValueError("model_provider must be anthropic or openai")
        if (
            not isinstance(expected_response_models, frozenset)
            or any(
                not isinstance(model, str) or not model
                for model in expected_response_models
            )
            or (model_provider == "openai") is not bool(expected_response_models)
        ):
            raise ValueError(
                "OpenAI middleware requires exact expected response models"
            )
        self._budget = budget
        self._depth = depth
        self._allow_subagents = allow_subagents
        self._allowed_subagents = allowed_subagents
        self._input_token_counter = input_token_counter
        self._input_token_count_preparer = input_token_count_preparer
        self._model_provider = model_provider
        self._expected_response_models = expected_response_models
        self._prompt_caching = AnthropicPromptCachingMiddleware(
            unsupported_model_behavior="ignore"
        )
        self._quickjs_tool_name = quickjs_tool_name
        self._allow_quickjs = allow_quickjs
        self._root_tool_allowlist = root_tool_allowlist
        self._root_tool_denylist = root_tool_denylist

    def _remove_unauthorized_subagent_surface(
        self,
        request: ModelRequest[Any],
    ) -> ModelRequest[Any]:
        """Remove the native Deep Agents 0.7 task tool from unauthorized calls."""
        return request.override(
            tools=[tool for tool in request.tools if _tool_name(tool) != TASK_TOOL_NAME]
        )

    async def _count_input_tokens(self, request: ModelRequest[Any]) -> int:
        try:
            async with asyncio.timeout(self._budget.remaining_seconds()):
                token_count = await self._input_token_counter(request)
        except TimeoutError as exc:
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token counting exceeded the run deadline"
            ) from exc
        except InputTokenCountError:
            self._budget.exhaust()
            raise
        except Exception as exc:
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token counting failed before generation"
            ) from exc

        if (
            not isinstance(token_count, int)
            or isinstance(token_count, bool)
            or token_count < 0
        ):
            self._budget.exhaust()
            raise InputTokenCountError("input token counter returned a malformed value")
        return token_count

    async def _prepare_input_token_count(
        self,
        request: ModelRequest[Any],
    ) -> PreparedInputTokenCount:
        preparer = self._input_token_count_preparer
        if preparer is None:
            raise AssertionError("input token count preparer is not configured")
        try:
            async with asyncio.timeout(self._budget.remaining_seconds()):
                prepared = await preparer(request)
        except TimeoutError as exc:
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token count preparation exceeded the run deadline"
            ) from exc
        except InputTokenCountError:
            self._budget.exhaust()
            raise
        except Exception as exc:
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token count preparation failed before provider I/O"
            ) from exc
        if not isinstance(prepared, PreparedInputTokenCount):
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token count preparer returned a malformed value"
            )
        return prepared

    async def _count_prepared_input_tokens(
        self,
        prepared: PreparedInputTokenCount,
    ) -> int:
        try:
            async with asyncio.timeout(self._budget.remaining_seconds()):
                token_count = await prepared.count()
        except TimeoutError as exc:
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token counting exceeded the run deadline"
            ) from exc
        except InputTokenCountError:
            self._budget.exhaust()
            raise
        except Exception as exc:
            self._budget.exhaust()
            raise InputTokenCountError(
                "input token counting failed before generation"
            ) from exc
        if (
            not isinstance(token_count, int)
            or isinstance(token_count, bool)
            or token_count < 0
            or token_count > prepared.reserved_input_tokens
        ):
            self._budget.exhaust()
            raise InputTokenCountError(
                "prepared input token count exceeded its local reservation"
            )
        return token_count

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> Any:
        if self._root_tool_denylist:
            request = request.override(
                tools=[
                    tool
                    for tool in request.tools
                    if _tool_name(tool) not in self._root_tool_denylist
                ]
            )
        if not self._allow_subagents:
            request = self._remove_unauthorized_subagent_surface(request)
        if self._quickjs_tool_name is not None and not self._allow_quickjs:
            request = request.override(
                tools=[
                    tool
                    for tool in request.tools
                    if _tool_name(tool) != self._quickjs_tool_name
                ]
            )
        if self._root_tool_allowlist is not None:
            request = request.override(
                tools=[
                    tool
                    for tool in request.tools
                    if _tool_name(tool) in self._root_tool_allowlist
                ]
            )

        async def count_then_generate(
            final_request: ModelRequest[Any],
        ) -> ModelResponse[Any]:
            prepared = (
                await self._prepare_input_token_count(final_request)
                if self._input_token_count_preparer is not None
                else None
            )
            attempt = self._budget.reserve_model_attempt(
                input_upper_bound=(
                    prepared.reserved_input_tokens if prepared is not None else None
                ),
                task_reservation=(
                    _ACTIVE_TASK_RESERVATION.get() if self._depth > 0 else None
                ),
            )
            try:
                input_tokens = (
                    await self._count_prepared_input_tokens(prepared)
                    if prepared is not None
                    else await self._count_input_tokens(final_request)
                )
                if prepared is not None:
                    try:
                        async with asyncio.timeout(self._budget.remaining_seconds()):
                            await prepared.verify_generation_request(final_request)
                    except TimeoutError as exc:
                        self._budget.exhaust()
                        raise InputTokenCountError(
                            "generation parity verification exceeded the run deadline"
                        ) from exc
                    except InputTokenCountError:
                        self._budget.exhaust()
                        raise
                    except Exception as exc:
                        self._budget.exhaust()
                        raise InputTokenCountError(
                            "generation parity verification failed closed"
                        ) from exc
                reservation = self._budget.reserve_model_input(
                    attempt,
                    input_tokens=input_tokens,
                )
            except BaseException:
                if prepared is not None:
                    self._budget.exhaust()
                self._budget.settle_model(attempt, actual_tokens=None)
                raise
            try:
                async with asyncio.timeout(self._budget.remaining_seconds()):
                    response = await handler(final_request)
            except BaseException:
                self._budget.settle_model(reservation, actual_tokens=None)
                raise
            self._budget._settle_model_response(
                reservation,
                response,
                model_provider=self._model_provider,
                expected_response_models=self._expected_response_models,
            )
            return response

        # Deep Agents appends this native middleware after user middleware.
        # Apply it once here as well so the official count and generation see
        # the same token-bearing request. The downstream application is
        # idempotent, and compiled children now receive the same cache shape.
        return await self._prompt_caching.awrap_model_call(
            request,
            count_then_generate,
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name")
        if tool_name in self._root_tool_denylist:
            raise CapabilityDeniedError(
                "root tool is outside the reviewed root tool surface"
            )
        if (
            self._root_tool_allowlist is not None
            and tool_name not in self._root_tool_allowlist
        ):
            raise CapabilityDeniedError(
                "root tool is outside the server-owned root tool allowlist"
            )
        if self._quickjs_tool_name is not None and tool_name == self._quickjs_tool_name:
            if not self._allow_quickjs:
                raise CapabilityDeniedError(
                    "QuickJS requires server opt-in and owner or eval permission"
                )
            reservation = self._budget.reserve_quickjs()
            try:
                async with asyncio.timeout(self._budget.remaining_seconds()):
                    result = await handler(request)
            except BaseException:
                self._budget.settle_quickjs(
                    reservation,
                    actual_output_bytes=None,
                )
                raise
            self._budget.settle_quickjs(
                reservation,
                actual_output_bytes=_tool_message_output_bytes(result),
            )
            return result

        if tool_name == TASK_TOOL_NAME:
            if not self._allow_subagents:
                raise CapabilityDeniedError(
                    "dynamic subagents require an owner or eval permission"
                )
            configurable = request.runtime.config.get("configurable", {})
            if (
                isinstance(configurable, Mapping)
                and "__deepagents_subagent_response_format" in configurable
            ):
                raise CapabilityDeniedError(
                    "dynamic subagent response formats are server-owned"
                )
            _validate_task_call(
                request.tool_call,
                allowed_subagents=self._allowed_subagents,
            )
            reservation = self._budget.reserve_task(depth=self._depth + 1)
            context_token = _ACTIVE_TASK_RESERVATION.set(reservation)
            try:
                async with asyncio.timeout(self._budget.remaining_seconds()):
                    return await handler(request)
            finally:
                try:
                    _ACTIVE_TASK_RESERVATION.reset(context_token)
                finally:
                    self._budget.finish_task(reservation)

        self._budget.reserve_tool()
        async with asyncio.timeout(self._budget.remaining_seconds()):
            return await handler(request)


__all__ = [
    "DEFAULT_RUN_BUDGET_POLICY",
    "MAX_TASK_DESCRIPTION_BYTES",
    "REQUIRED_TASK_SECTIONS",
    "BudgetSnapshot",
    "CapabilityDeniedError",
    "InvalidDelegationError",
    "InputTokenCountError",
    "InputTokenCounter",
    "ModelReservation",
    "QuickJSReservation",
    "RunBudget",
    "RunBudgetExceededError",
    "RunBudgetMiddleware",
    "RunBudgetPolicy",
    "RunBudgetUnsettledError",
    "TaskReservation",
]
