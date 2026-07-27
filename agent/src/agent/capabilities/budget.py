"""One atomic, non-persistent resource ledger for a Deep Agents run."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import Command

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


@dataclass(frozen=True, slots=True)
class RunBudgetPolicy:
    """Immutable limits applied to one root run and every nested specialist."""

    policy_id: str
    max_model_calls: int
    max_tool_calls: int
    max_task_calls: int
    max_tasks_in_flight: int
    max_depth: int
    max_output_tokens: int
    max_total_tokens: int
    max_elapsed_seconds: int

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_model_calls,
            self.max_tool_calls,
            self.max_task_calls,
            self.max_tasks_in_flight,
            self.max_depth,
            self.max_output_tokens,
            self.max_total_tokens,
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
        ):
            raise ValueError("run budget policy limits must be positive and coherent")


DEFAULT_RUN_BUDGET_POLICY = RunBudgetPolicy(
    policy_id="owner-dynamic-subagents-v1",
    max_model_calls=12,
    max_tool_calls=24,
    max_task_calls=2,
    max_tasks_in_flight=2,
    max_depth=1,
    max_output_tokens=2_048,
    max_total_tokens=48_000,
    max_elapsed_seconds=90,
)


@dataclass(frozen=True, slots=True)
class ModelReservation:
    """Opaque handle used to settle exactly one model reservation."""

    reservation_id: int
    reserved_tokens: int


@dataclass(frozen=True, slots=True)
class TaskReservation:
    """Opaque task slot whose token tranche may fund its first child model call."""

    reservation_id: int
    reserved_tokens: int


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Bounded, serializable observation of a run ledger."""

    policy_id: str
    model_calls: int
    tool_calls: int
    task_calls: int
    tasks_in_flight: int
    charged_tokens: int
    elapsed_ms: int
    exhausted: bool


class RunBudget:
    """Thread-safe ledger shared by root and child middleware.

    The lock and monotonic clock deliberately make this object runtime-only.
    Only :class:`BudgetSnapshot` may cross the graph-factory boundary.
    """

    __slots__ = (
        "_charged_tokens",
        "_clock",
        "_exhausted",
        "_lock",
        "_model_calls",
        "_next_reservation_id",
        "_next_task_reservation_id",
        "_open_model_reservations",
        "_open_task_reservations",
        "_policy",
        "_started_at",
        "_task_calls",
        "_tasks_in_flight",
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
        self._lock = Lock()
        self._model_calls = 0
        self._tool_calls = 0
        self._task_calls = 0
        self._tasks_in_flight = 0
        self._charged_tokens = 0
        self._next_reservation_id = 0
        self._open_model_reservations: dict[int, int] = {}
        self._next_task_reservation_id = 0
        self._open_task_reservations: dict[int, bool] = {}
        self._exhausted = False

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

    def remaining_seconds(self) -> float:
        with self._lock:
            self._require_time_locked()
            return self._policy.max_elapsed_seconds - self._elapsed_locked()

    def reserve_model(
        self,
        *,
        estimated_input_tokens: int = 0,
        task_reservation: TaskReservation | None = None,
    ) -> ModelReservation:
        """Atomically reserve one call, its estimated input, and maximum output."""
        with self._lock:
            self._require_time_locked()
            if (
                not isinstance(estimated_input_tokens, int)
                or isinstance(estimated_input_tokens, bool)
                or estimated_input_tokens < 0
            ):
                raise ValueError(
                    "estimated_input_tokens must be a non-negative integer"
                )
            task_tranche = 0
            if task_reservation is not None:
                if (
                    not isinstance(task_reservation, TaskReservation)
                    or not isinstance(task_reservation.reservation_id, int)
                    or isinstance(task_reservation.reservation_id, bool)
                    or not isinstance(task_reservation.reserved_tokens, int)
                    or isinstance(task_reservation.reserved_tokens, bool)
                ):
                    raise TypeError("task_reservation must be a TaskReservation")
                reservation_id = task_reservation.reservation_id
                if (
                    reservation_id not in self._open_task_reservations
                    or task_reservation.reserved_tokens
                    != self._policy.max_output_tokens
                ):
                    raise RuntimeError("task reservation is unknown or invalid")
                if self._open_task_reservations[reservation_id]:
                    task_tranche = task_reservation.reserved_tokens
            if self._model_calls >= self._policy.max_model_calls:
                self._exhausted = True
                raise RunBudgetExceededError("model-call budget exhausted")
            reserved = estimated_input_tokens + self._policy.max_output_tokens
            additional_charge = reserved - task_tranche
            if self._charged_tokens + additional_charge > self._policy.max_total_tokens:
                self._exhausted = True
                raise RunBudgetExceededError("token budget exhausted")

            self._model_calls += 1
            self._charged_tokens += additional_charge
            if task_tranche:
                self._open_task_reservations[task_reservation.reservation_id] = False
            self._next_reservation_id += 1
            reservation = ModelReservation(self._next_reservation_id, reserved)
            self._open_model_reservations[reservation.reservation_id] = reserved
            return reservation

    def settle_model(
        self,
        reservation: ModelReservation,
        *,
        actual_tokens: int | None,
    ) -> None:
        """Settle provider usage; missing usage retains the full reservation."""
        with self._lock:
            if (
                not isinstance(reservation, ModelReservation)
                or not isinstance(reservation.reservation_id, int)
                or isinstance(reservation.reservation_id, bool)
                or not isinstance(reservation.reserved_tokens, int)
                or isinstance(reservation.reserved_tokens, bool)
            ):
                raise TypeError("reservation must be a ModelReservation")
            reserved = self._open_model_reservations.pop(
                reservation.reservation_id,
                None,
            )
            if reserved is None or reserved != reservation.reserved_tokens:
                raise RuntimeError("model reservation is unknown or already settled")
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
            if settled > self._policy.max_total_tokens:
                self._charged_tokens = self._policy.max_total_tokens
                self._exhausted = True
                raise RunBudgetExceededError("provider usage exceeded the token budget")
            self._charged_tokens = settled

    def reserve_tool(self) -> None:
        """Atomically reserve one non-task tool call."""
        with self._lock:
            self._require_time_locked()
            if self._tool_calls >= self._policy.max_tool_calls:
                self._exhausted = True
                raise RunBudgetExceededError("tool-call budget exhausted")
            self._tool_calls += 1

    def reserve_task(self, *, depth: int) -> TaskReservation:
        """Jointly reserve tool, task-total, fan-out, depth, time, and tokens."""
        with self._lock:
            self._require_time_locked()
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
                or reservation.reservation_id not in self._open_task_reservations
                or reservation.reserved_tokens != self._policy.max_output_tokens
            ):
                raise RuntimeError("task reservation is unknown or already finished")
            if self._tasks_in_flight < 1:
                raise RuntimeError("subagent in-flight reservation underflow")
            self._tasks_in_flight -= 1
            del self._open_task_reservations[reservation.reservation_id]

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            elapsed_ms = min(
                int(self._elapsed_locked() * 1_000),
                int(self._policy.max_elapsed_seconds * 1_000),
            )
            return BudgetSnapshot(
                policy_id=self._policy.policy_id,
                model_calls=min(self._model_calls, self._policy.max_model_calls),
                tool_calls=min(self._tool_calls, self._policy.max_tool_calls),
                task_calls=min(self._task_calls, self._policy.max_task_calls),
                tasks_in_flight=min(
                    self._tasks_in_flight,
                    self._policy.max_tasks_in_flight,
                ),
                charged_tokens=min(
                    self._charged_tokens,
                    self._policy.max_total_tokens,
                ),
                elapsed_ms=elapsed_ms,
                exhausted=self._exhausted,
            )


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


def _estimated_input_tokens(request: ModelRequest[Any]) -> int:
    messages: list[BaseMessage] = []
    if request.system_message is not None:
        messages.append(request.system_message)
    messages.extend(request.messages)
    return count_tokens_approximately(
        messages,
        chars_per_token=2.0,
        tools=request.tools,
        use_usage_metadata_scaling=True,
    )


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
    ) -> None:
        super().__init__()
        self._budget = budget
        self._depth = depth
        self._allow_subagents = allow_subagents
        self._allowed_subagents = allowed_subagents

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> Any:
        if not self._allow_subagents:
            request = request.override(
                tools=[
                    tool for tool in request.tools if _tool_name(tool) != TASK_TOOL_NAME
                ]
            )

        reservation = self._budget.reserve_model(
            estimated_input_tokens=_estimated_input_tokens(request),
            task_reservation=(
                _ACTIVE_TASK_RESERVATION.get() if self._depth > 0 else None
            ),
        )
        try:
            async with asyncio.timeout(self._budget.remaining_seconds()):
                response = await handler(request)
        except BaseException:
            self._budget.settle_model(reservation, actual_tokens=None)
            raise
        self._budget.settle_model(
            reservation,
            actual_tokens=_actual_token_usage(response),
        )
        return response

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name")
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
    "ModelReservation",
    "RunBudget",
    "RunBudgetExceededError",
    "RunBudgetMiddleware",
    "RunBudgetPolicy",
    "TaskReservation",
]
