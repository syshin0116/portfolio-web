"""Configuration and failure contracts for the durable guest spend ledger."""

from __future__ import annotations

from datetime import date

import pytest

from agent import guest_budget
from agent.guest_budget import (
    GUEST_DAILY_BUDGET_ENV,
    GUEST_MIN_RUN_RESERVATION_MICRO_USD,
    GUEST_RUN_RESERVATION_ENV,
    GuestBudgetConfig,
    GuestBudgetConfigurationError,
    GuestBudgetUnavailableError,
    GuestDailyBudgetExhaustedError,
    PostgresGuestSpendLedger,
    guest_budget_config,
    minimum_guest_run_reservation_micro_usd,
)


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _Result:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _Session:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.parameters = None

    def begin(self):
        return _AsyncContext(None)

    async def execute(self, _statement, parameters):
        self.parameters = parameters
        if self.error is not None:
            raise self.error
        return _Result(self.result)


@pytest.mark.parametrize(
    ("daily", "reservation", "message"),
    [
        (None, None, "required"),
        ("100000", None, "required"),
        ("100000", "0", "canonical positive integer"),
        ("100000", "01", "canonical positive integer"),
        ("100000", "100001", "cannot exceed"),
        ("100000", "6892", "conservative accounting floor"),
        ("100000", "8868", "conservative accounting floor"),
        ("100000", "17945", "conservative accounting floor"),
        ("100000", "19892", "conservative accounting floor"),
        ("100000", "47891", "conservative accounting floor"),
    ],
)
def test_required_guest_budget_configuration_fails_closed(
    monkeypatch,
    daily,
    reservation,
    message,
):
    monkeypatch.delenv(GUEST_DAILY_BUDGET_ENV, raising=False)
    monkeypatch.delenv(GUEST_RUN_RESERVATION_ENV, raising=False)
    if daily is not None:
        monkeypatch.setenv(GUEST_DAILY_BUDGET_ENV, daily)
    if reservation is not None:
        monkeypatch.setenv(GUEST_RUN_RESERVATION_ENV, reservation)

    with pytest.raises(GuestBudgetConfigurationError, match=message):
        guest_budget_config(required=True)


def test_optional_guest_budget_is_absent_or_exact(monkeypatch):
    monkeypatch.delenv(GUEST_DAILY_BUDGET_ENV, raising=False)
    monkeypatch.delenv(GUEST_RUN_RESERVATION_ENV, raising=False)
    assert guest_budget_config(required=False) is None

    monkeypatch.setenv(GUEST_DAILY_BUDGET_ENV, "500000")
    monkeypatch.setenv(GUEST_RUN_RESERVATION_ENV, "47892")
    assert guest_budget_config(required=False) == GuestBudgetConfig(
        daily_limit_micro_usd=500_000,
        run_reservation_micro_usd=47_892,
    )


def test_guest_accounting_floor_adds_count_risk_and_uses_exact_ceiling():
    assert GUEST_MIN_RUN_RESERVATION_MICRO_USD == 47_892
    assert (
        minimum_guest_run_reservation_micro_usd(
            max_model_calls=8,
            max_output_tokens=512,
            max_total_tokens=48_000,
            max_count_risk_tokens=128_000,
        )
        == GUEST_MIN_RUN_RESERVATION_MICRO_USD
    )


def test_guest_accounting_floor_is_maximized_at_the_output_ceiling():
    costs = [
        minimum_guest_run_reservation_micro_usd(
            max_model_calls=8,
            max_output_tokens=output_tokens,
            max_total_tokens=48_000,
            max_count_risk_tokens=128_000,
        )
        for output_tokens in range(1, 513)
    ]

    assert costs[0] == 44_008
    assert costs[-2] == 47_884
    assert costs[-1] == 47_892
    assert max(costs) == costs[-1]


@pytest.mark.parametrize(
    ("limits", "error"),
    [
        (
            {
                "max_model_calls": True,
                "max_output_tokens": 1,
                "max_total_tokens": 1,
                "max_count_risk_tokens": 1,
            },
            TypeError,
        ),
        (
            {
                "max_model_calls": 0,
                "max_output_tokens": 1,
                "max_total_tokens": 1,
                "max_count_risk_tokens": 1,
            },
            ValueError,
        ),
        (
            {
                "max_model_calls": 8,
                "max_output_tokens": 3_001,
                "max_total_tokens": 12_000,
                "max_count_risk_tokens": 48_000,
            },
            ValueError,
        ),
    ],
    ids=["boolean-call-limit", "zero-call-limit", "output-exceeds-total"],
)
def test_guest_accounting_floor_rejects_unreviewed_abuse_bounds(limits, error):
    with pytest.raises(error):
        minimum_guest_run_reservation_micro_usd(**limits)


async def test_postgres_ledger_returns_the_committed_aggregate(monkeypatch):
    session = _Session(
        {
            "budget_date": date(2026, 7, 28),
            "reserved_micro_usd": 50_000,
            "run_count": 2,
        }
    )
    monkeypatch.setattr(
        guest_budget,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )
    ledger = PostgresGuestSpendLedger(
        GuestBudgetConfig(
            daily_limit_micro_usd=500_000,
            run_reservation_micro_usd=25_000,
        )
    )

    reservation = await ledger.reserve_run()

    assert reservation.reserved_micro_usd == 50_000
    assert reservation.run_count == 2
    assert session.parameters == {
        "daily_limit_micro_usd": 500_000,
        "reservation_micro_usd": 25_000,
    }


async def test_postgres_ledger_distinguishes_exhaustion_and_unavailability(
    monkeypatch,
):
    session = _Session(None)
    monkeypatch.setattr(
        guest_budget,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )
    ledger = PostgresGuestSpendLedger(
        GuestBudgetConfig(
            daily_limit_micro_usd=25_000,
            run_reservation_micro_usd=25_000,
        )
    )
    with pytest.raises(GuestDailyBudgetExhaustedError):
        await ledger.reserve_run()

    broken = _Session(error=RuntimeError("database address must stay private"))
    monkeypatch.setattr(
        guest_budget,
        "get_session_maker",
        lambda: lambda: _AsyncContext(broken),
    )
    with pytest.raises(GuestBudgetUnavailableError) as error:
        await ledger.reserve_run()
    assert "database address" not in str(error.value)


async def test_postgres_ledger_rejects_malformed_database_results(monkeypatch):
    session = _Session(
        {
            "budget_date": date(2026, 7, 28),
            "reserved_micro_usd": 500_001,
            "run_count": 1,
        }
    )
    monkeypatch.setattr(
        guest_budget,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )
    ledger = PostgresGuestSpendLedger(
        GuestBudgetConfig(
            daily_limit_micro_usd=500_000,
            run_reservation_micro_usd=25_000,
        )
    )

    with pytest.raises(GuestBudgetUnavailableError, match="invalid reservation"):
        await ledger.reserve_run()
