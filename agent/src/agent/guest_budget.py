"""Durable, fail-closed daily spend reservations for public guest runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from aegra_api.core.orm import get_session_maker
from sqlalchemy import text

GUEST_DAILY_BUDGET_ENV = "GUEST_DAILY_BUDGET_MICRO_USD"
GUEST_RUN_RESERVATION_ENV = "GUEST_RUN_RESERVATION_MICRO_USD"
MAX_GUEST_BUDGET_MICRO_USD = 1_000_000_000
_MICRO_USD_PER_USD = 1_000_000
_OPENAI_GUEST_INPUT_USD_MICROS_PER_MILLION_TOKENS = 200_000
_OPENAI_GUEST_CACHED_INPUT_USD_MICROS_PER_MILLION_TOKENS = 20_000
_OPENAI_GUEST_CACHE_WRITE_USD_MICROS_PER_MILLION_TOKENS = 250_000
_OPENAI_GUEST_OUTPUT_USD_MICROS_PER_MILLION_TOKENS = 1_200_000
_OPENAI_GUEST_MAX_MODEL_CALLS = 4
_OPENAI_GUEST_MAX_OUTPUT_TOKENS_PER_CALL = 1_024
_OPENAI_GUEST_MAX_TOTAL_TOKENS = 12_000

_RESERVE_GUEST_BUDGET_SQL = text(
    """
    INSERT INTO agent_guest_daily_budget (
        budget_date,
        reserved_micro_usd,
        run_count,
        updated_at
    )
    VALUES (
        CAST(timezone('UTC', CURRENT_TIMESTAMP) AS date),
        :reservation_micro_usd,
        1,
        CURRENT_TIMESTAMP
    )
    ON CONFLICT (budget_date) DO UPDATE
    SET
        reserved_micro_usd =
            agent_guest_daily_budget.reserved_micro_usd
            + EXCLUDED.reserved_micro_usd,
        run_count = agent_guest_daily_budget.run_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE
        agent_guest_daily_budget.reserved_micro_usd
        + EXCLUDED.reserved_micro_usd
        <= :daily_limit_micro_usd
    RETURNING budget_date, reserved_micro_usd, run_count
    """
)


class GuestBudgetConfigurationError(RuntimeError):
    """Guest spend configuration is missing, malformed, or incoherent."""


class GuestDailyBudgetExhaustedError(RuntimeError):
    """The atomic UTC-day reservation would cross the configured hard ceiling."""


class GuestBudgetUnavailableError(RuntimeError):
    """The durable ledger could not make a reservation safely."""


@dataclass(frozen=True, slots=True)
class GuestBudgetConfig:
    """Exact integer micro-dollar limits reviewed for the configured guest model."""

    daily_limit_micro_usd: int
    run_reservation_micro_usd: int


@dataclass(frozen=True, slots=True)
class GuestBudgetReservation:
    """Committed aggregate after one conservative run reservation."""

    budget_date: date
    reserved_micro_usd: int
    run_count: int


class GuestSpendLedger(Protocol):
    """Async boundary used by the pure-ASGI guard and deterministic tests."""

    async def reserve_run(self) -> GuestBudgetReservation: ...


def minimum_guest_generation_cost_micro_usd(
    *,
    max_model_calls: int,
    max_output_tokens: int,
    max_total_tokens: int,
) -> int:
    """Return the conservative gpt-5.6-luna generation cost for one run."""
    values = (max_model_calls, max_output_tokens, max_total_tokens)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise TypeError("guest generation limits must be integers")
    if max_model_calls < 1 or max_output_tokens < 1 or max_total_tokens < 1:
        raise ValueError("guest generation limits must be positive")
    output_tokens = max_model_calls * max_output_tokens
    if output_tokens > max_total_tokens:
        raise ValueError("guest output reservation exceeds the total-token budget")
    # Price every possible input token at the most expensive input bucket.
    # GPT-5.6 implicit cache writes cost 1.25x uncached input. Cache reads may
    # lower actual cost, but neither outcome can lower a pre-dispatch
    # worst-case reservation.
    input_tokens = max_total_tokens - output_tokens
    input_rate = max(
        _OPENAI_GUEST_INPUT_USD_MICROS_PER_MILLION_TOKENS,
        _OPENAI_GUEST_CACHED_INPUT_USD_MICROS_PER_MILLION_TOKENS,
        _OPENAI_GUEST_CACHE_WRITE_USD_MICROS_PER_MILLION_TOKENS,
    )
    numerator = (
        input_tokens * input_rate
        + output_tokens * _OPENAI_GUEST_OUTPUT_USD_MICROS_PER_MILLION_TOKENS
    )
    return (numerator + _MICRO_USD_PER_USD - 1) // _MICRO_USD_PER_USD


GUEST_MIN_RUN_RESERVATION_MICRO_USD = minimum_guest_generation_cost_micro_usd(
    max_model_calls=_OPENAI_GUEST_MAX_MODEL_CALLS,
    max_output_tokens=_OPENAI_GUEST_MAX_OUTPUT_TOKENS_PER_CALL,
    max_total_tokens=_OPENAI_GUEST_MAX_TOTAL_TOKENS,
)


def _positive_micro_usd(name: str, *, required: bool) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if required:
            raise GuestBudgetConfigurationError(
                f"{name} is required when anonymous agent access is enabled"
            )
        return None
    if not raw.isascii() or not raw.isdecimal() or raw.startswith("0") or len(raw) > 10:
        raise GuestBudgetConfigurationError(
            f"{name} must be a canonical positive integer"
        )
    value = int(raw)
    if value > MAX_GUEST_BUDGET_MICRO_USD:
        raise GuestBudgetConfigurationError(
            f"{name} exceeds the reviewed configuration bound"
        )
    return value


def guest_budget_config(*, required: bool) -> GuestBudgetConfig | None:
    """Parse the two-value budget atomically; partial configuration is invalid."""
    daily = _positive_micro_usd(GUEST_DAILY_BUDGET_ENV, required=required)
    reservation = _positive_micro_usd(
        GUEST_RUN_RESERVATION_ENV,
        required=required,
    )
    if daily is None and reservation is None:
        return None
    if daily is None or reservation is None:
        raise GuestBudgetConfigurationError(
            "guest daily and per-run spend limits must be configured together"
        )
    if reservation > daily:
        raise GuestBudgetConfigurationError(
            "guest per-run spend reservation cannot exceed the daily limit"
        )
    if reservation < GUEST_MIN_RUN_RESERVATION_MICRO_USD:
        raise GuestBudgetConfigurationError(
            "guest per-run spend reservation is below the reviewed "
            "gpt-5.6-luna generation floor"
        )
    return GuestBudgetConfig(
        daily_limit_micro_usd=daily,
        run_reservation_micro_usd=reservation,
    )


class PostgresGuestSpendLedger:
    """Reserve a worst-case run cost with one PostgreSQL upsert."""

    def __init__(self, config: GuestBudgetConfig) -> None:
        if not isinstance(config, GuestBudgetConfig):
            raise TypeError("config must be GuestBudgetConfig")
        self._config = config

    async def reserve_run(self) -> GuestBudgetReservation:
        maker = get_session_maker()
        try:
            async with maker() as session, session.begin():
                result = await session.execute(
                    _RESERVE_GUEST_BUDGET_SQL,
                    {
                        "daily_limit_micro_usd": (self._config.daily_limit_micro_usd),
                        "reservation_micro_usd": (
                            self._config.run_reservation_micro_usd
                        ),
                    },
                )
                row = result.mappings().one_or_none()
        except Exception as exc:
            raise GuestBudgetUnavailableError(
                "guest spend ledger reservation failed"
            ) from exc
        if row is None:
            raise GuestDailyBudgetExhaustedError(
                "guest daily spend reservation is exhausted"
            )
        budget_date = row.get("budget_date")
        reserved = row.get("reserved_micro_usd")
        run_count = row.get("run_count")
        if (
            not isinstance(budget_date, date)
            or not isinstance(reserved, int)
            or isinstance(reserved, bool)
            or not isinstance(run_count, int)
            or isinstance(run_count, bool)
            or reserved < self._config.run_reservation_micro_usd
            or reserved > self._config.daily_limit_micro_usd
            or run_count < 1
        ):
            raise GuestBudgetUnavailableError(
                "guest spend ledger returned an invalid reservation"
            )
        return GuestBudgetReservation(
            budget_date=budget_date,
            reserved_micro_usd=reserved,
            run_count=run_count,
        )


__all__ = [
    "GUEST_DAILY_BUDGET_ENV",
    "GUEST_MIN_RUN_RESERVATION_MICRO_USD",
    "GUEST_RUN_RESERVATION_ENV",
    "GuestBudgetConfig",
    "GuestBudgetConfigurationError",
    "GuestBudgetReservation",
    "GuestBudgetUnavailableError",
    "GuestDailyBudgetExhaustedError",
    "GuestSpendLedger",
    "PostgresGuestSpendLedger",
    "guest_budget_config",
    "minimum_guest_generation_cost_micro_usd",
]
