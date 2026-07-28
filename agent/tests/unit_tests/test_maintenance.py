"""Checkpoint-first retention behavior for anonymous guest threads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent import maintenance
from agent.maintenance import (
    GUEST_RETENTION_POLICY,
    MAX_GC_BATCH_SIZE,
    collect_expired_guest_threads,
)


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _ScalarsResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return iter(self.values)


class _Session:
    def __init__(self, events, *, lock_acquired=True, thread_ids=()):
        self.events = events
        self.lock_acquired = lock_acquired
        self.thread_ids = thread_ids
        self.selection_parameters = None

    def begin(self):
        return _AsyncContext(None)

    async def execute(self, statement, parameters):
        sql = str(statement)
        if "pg_try_advisory_xact_lock" in sql:
            self.events.append("lock")
            return _ScalarResult(self.lock_acquired)
        if "SELECT thread_id" in sql:
            self.events.append("select")
            self.selection_parameters = parameters
            return _ScalarsResult(self.thread_ids)
        if "DELETE FROM thread" in sql:
            self.events.append("delete-parents")
            return SimpleNamespace(rowcount=len(self.thread_ids))
        raise AssertionError(f"unexpected SQL: {sql}")


class _Checkpointer:
    def __init__(self, events):
        self.events = events

    async def adelete_thread(self, thread_id):
        self.events.append(f"delete-checkpoints:{thread_id}")


async def test_gc_deletes_checkpoint_children_before_thread_parents(monkeypatch):
    events = []
    session = _Session(
        events,
        thread_ids=("guest-thread-a", "guest-thread-b"),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await collect_expired_guest_threads(
        batch_size=7,
        checkpointer=_Checkpointer(events),
    )

    assert result.lock_acquired is True
    assert result.deleted_threads == 2
    assert events == [
        "lock",
        "select",
        "delete-checkpoints:guest-thread-a",
        "delete-checkpoints:guest-thread-b",
        "delete-parents",
    ]
    assert session.selection_parameters == {
        "batch_size": 7,
        "retention_policy": GUEST_RETENTION_POLICY,
    }


async def test_gc_lock_contention_is_a_clean_noop(monkeypatch):
    events = []
    session = _Session(events, lock_acquired=False)
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await collect_expired_guest_threads(
        checkpointer=_Checkpointer(events),
    )

    assert result.lock_acquired is False
    assert result.deleted_threads == 0
    assert events == ["lock"]


@pytest.mark.parametrize("batch_size", [0, -1, True, MAX_GC_BATCH_SIZE + 1])
async def test_gc_batch_size_is_bounded(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        await collect_expired_guest_threads(
            batch_size=batch_size,
            checkpointer=_Checkpointer([]),
        )


async def test_maintenance_always_closes_the_database_manager(monkeypatch):
    events = []

    async def initialize():
        events.append("initialize")

    async def collect():
        events.append("collect")
        raise RuntimeError("sweep failed")

    async def close():
        events.append("close")

    monkeypatch.setattr(maintenance.db_manager, "initialize", initialize)
    monkeypatch.setattr(maintenance, "collect_expired_guest_threads", collect)
    monkeypatch.setattr(maintenance.db_manager, "close", close)

    with pytest.raises(RuntimeError, match="sweep failed"):
        await maintenance.run_maintenance()

    assert events == ["initialize", "collect", "close"]
