"""Dedicated PostgreSQL guest-thread serialization behavior."""

from __future__ import annotations

import asyncio

import pytest

from agent import guest_thread_lock
from agent.guest_thread_lock import (
    GuestThreadLockUnavailableError,
    guest_thread_advisory_lock,
    guest_thread_lock_key,
)


class _Transaction:
    def __init__(self, events, *, rollback_release=None, on_rollback=None):
        self.events = events
        self.rollback_release = rollback_release
        self.on_rollback = on_rollback
        self.rollback_started = asyncio.Event()
        self.is_active = True

    async def rollback(self):
        self.events.append("rollback-start")
        self.rollback_started.set()
        if self.rollback_release is not None:
            await self.rollback_release.wait()
        self.is_active = False
        if self.on_rollback is not None:
            self.on_rollback()
        self.events.append("rollback-complete")


class _Connection:
    def __init__(self, events, transaction, *, lock_results=(True,)):
        self.events = events
        self.transaction = transaction
        self.lock_results = iter(lock_results)
        self.lock_parameters = []

    async def begin(self):
        self.events.append("begin")
        return self.transaction

    async def scalar(self, statement, parameters):
        self.events.append("try-lock")
        self.lock_parameters.append((str(statement), parameters))
        return next(self.lock_results, False)

    async def close(self):
        self.events.append("close-connection")


class _Engine:
    def __init__(self, events, connection):
        self.events = events
        self.connection = connection

    async def connect(self):
        self.events.append("connect")
        return self.connection

    async def dispose(self):
        self.events.append("dispose-engine")


class _BlockedScalarConnection(_Connection):
    def __init__(self, events, transaction, lock_state):
        super().__init__(events, transaction)
        self.lock_state = lock_state
        self.scalar_started = asyncio.Event()

    async def scalar(self, statement, parameters):
        self.events.append("try-lock")
        self.lock_parameters.append((str(statement), parameters))
        self.lock_state["held"] = True
        self.scalar_started.set()
        await asyncio.Event().wait()


def test_guest_thread_lock_key_is_stable_domain_separated_signed_bigint():
    assert guest_thread_lock_key("guest-thread") == 5981689956529361963
    assert guest_thread_lock_key("guest-thread-2") == -5711412930247158489
    assert guest_thread_lock_key("guest-thread") != guest_thread_lock_key(
        "guest-thread-2"
    )
    with pytest.raises(ValueError, match="thread_id"):
        guest_thread_lock_key("")


async def test_guest_thread_lock_uses_one_transaction_until_context_exit(
    monkeypatch,
):
    events = []
    transaction = _Transaction(events)
    connection = _Connection(events, transaction)
    engine = _Engine(events, connection)
    monkeypatch.setattr(
        guest_thread_lock,
        "_create_lock_engine",
        lambda: engine,
    )

    async with guest_thread_advisory_lock(
        "guest-thread",
        timeout_seconds=1,
    ):
        events.append("body")

    assert events == [
        "connect",
        "begin",
        "try-lock",
        "body",
        "rollback-start",
        "rollback-complete",
        "close-connection",
        "dispose-engine",
    ]
    assert connection.lock_parameters == [
        (
            "SELECT pg_try_advisory_xact_lock(:lock_key)",
            {"lock_key": 5981689956529361963},
        )
    ]


async def test_guest_thread_lock_cancellation_drains_rollback_and_close(
    monkeypatch,
):
    events = []
    rollback_release = asyncio.Event()
    transaction = _Transaction(
        events,
        rollback_release=rollback_release,
    )
    connection = _Connection(events, transaction)
    engine = _Engine(events, connection)
    monkeypatch.setattr(
        guest_thread_lock,
        "_create_lock_engine",
        lambda: engine,
    )
    body_entered = asyncio.Event()

    async def hold_lock():
        async with guest_thread_advisory_lock(
            "guest-thread",
            timeout_seconds=1,
        ):
            body_entered.set()
            await asyncio.Event().wait()

    running = asyncio.create_task(hold_lock())
    await body_entered.wait()
    running.cancel()
    await transaction.rollback_started.wait()
    running.cancel()
    await asyncio.sleep(0)
    assert not running.done()

    rollback_release.set()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert events[-4:] == [
        "rollback-start",
        "rollback-complete",
        "close-connection",
        "dispose-engine",
    ]
    assert transaction.is_active is False


async def test_guest_thread_lock_acquire_double_cancel_still_releases_unknown_lock(
    monkeypatch,
):
    events = []
    rollback_release = asyncio.Event()
    lock_state = {"held": False}
    transaction = _Transaction(
        events,
        rollback_release=rollback_release,
        on_rollback=lambda: lock_state.update(held=False),
    )
    connection = _BlockedScalarConnection(
        events,
        transaction,
        lock_state,
    )
    engine = _Engine(events, connection)
    monkeypatch.setattr(
        guest_thread_lock,
        "_create_lock_engine",
        lambda: engine,
    )

    async def acquire_lock():
        async with guest_thread_advisory_lock(
            "guest-thread",
            timeout_seconds=1,
        ):
            raise AssertionError("cancelled acquisition must not enter the body")

    running = asyncio.create_task(acquire_lock())
    await connection.scalar_started.wait()
    assert lock_state["held"] is True
    running.cancel()
    await transaction.rollback_started.wait()
    running.cancel()
    await asyncio.sleep(0)
    assert not running.done()

    rollback_release.set()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert lock_state["held"] is False
    assert transaction.is_active is False
    assert events[-3:] == [
        "rollback-complete",
        "close-connection",
        "dispose-engine",
    ]


async def test_guest_thread_lock_timeout_releases_dedicated_resources(
    monkeypatch,
):
    events = []
    transaction = _Transaction(events)
    connection = _Connection(
        events,
        transaction,
        lock_results=(False,),
    )
    engine = _Engine(events, connection)
    monkeypatch.setattr(
        guest_thread_lock,
        "_create_lock_engine",
        lambda: engine,
    )

    with pytest.raises(GuestThreadLockUnavailableError):
        async with guest_thread_advisory_lock(
            "guest-thread",
            timeout_seconds=0.01,
        ):
            raise AssertionError("a timed-out lock must not enter its body")

    assert "rollback-complete" in events
    assert events[-2:] == ["close-connection", "dispose-engine"]
