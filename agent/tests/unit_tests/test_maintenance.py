"""Checkpoint-first retention behavior for anonymous guest threads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent import maintenance
from agent.guest_thread_lock import guest_thread_lock_key
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


class _OptionalScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ScalarsResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return iter(self.values)


class _Session:
    def __init__(
        self,
        events,
        *,
        lock_acquired=True,
        thread_ids=(),
        eligible_thread_ids=None,
        contended_thread_ids=(),
    ):
        self.events = events
        self.lock_acquired = lock_acquired
        self.thread_ids = thread_ids
        self.eligible_thread_ids = (
            set(thread_ids) if eligible_thread_ids is None else set(eligible_thread_ids)
        )
        self.contended_thread_ids = set(contended_thread_ids)
        self.thread_ids_by_lock_key = {
            guest_thread_lock_key(thread_id): thread_id for thread_id in thread_ids
        }
        self.selection_parameters = None
        self.candidate_sql = None
        self.recheck_sql = []

    def begin(self):
        return _AsyncContext(None)

    async def execute(self, statement, parameters):
        sql = str(statement)
        if "pg_try_advisory_xact_lock" in sql:
            lock_key = parameters["lock_key"]
            if lock_key == maintenance._GC_LOCK_KEY:
                self.events.append("lock")
                return _ScalarResult(self.lock_acquired)
            thread_id = self.thread_ids_by_lock_key[lock_key]
            self.events.append(f"thread-lock:{thread_id}")
            return _ScalarResult(thread_id not in self.contended_thread_ids)
        if "SELECT thread_id" in sql and "thread_id" not in parameters:
            self.events.append("select")
            self.selection_parameters = parameters
            self.candidate_sql = sql
            return _ScalarsResult(self.thread_ids)
        if "SELECT thread_id" in sql:
            thread_id = parameters["thread_id"]
            self.events.append(f"recheck:{thread_id}")
            self.recheck_sql.append(sql)
            return _OptionalScalarResult(
                thread_id if thread_id in self.eligible_thread_ids else None
            )
        if "DELETE FROM thread" in sql:
            thread_id = parameters["thread_id"]
            self.events.append(f"delete-parent:{thread_id}")
            return SimpleNamespace(rowcount=1)
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
        "thread-lock:guest-thread-a",
        "recheck:guest-thread-a",
        "delete-checkpoints:guest-thread-a",
        "delete-parent:guest-thread-a",
        "thread-lock:guest-thread-b",
        "recheck:guest-thread-b",
        "delete-checkpoints:guest-thread-b",
        "delete-parent:guest-thread-b",
    ]
    assert session.selection_parameters == {
        "batch_size": 7,
        "retention_policy": GUEST_RETENTION_POLICY,
    }
    assert "FOR UPDATE" not in session.candidate_sql
    assert len(session.recheck_sql) == 2
    assert all("FOR UPDATE" in sql for sql in session.recheck_sql)


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


async def test_gc_skips_contended_thread_and_rechecks_each_acquired_candidate(
    monkeypatch,
):
    events = []
    session = _Session(
        events,
        thread_ids=("guest-contended", "guest-changed", "guest-expired"),
        contended_thread_ids=("guest-contended",),
        eligible_thread_ids=("guest-expired",),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await collect_expired_guest_threads(
        checkpointer=_Checkpointer(events),
    )

    assert result.lock_acquired is True
    assert result.deleted_threads == 1
    assert events == [
        "lock",
        "select",
        "thread-lock:guest-contended",
        "thread-lock:guest-changed",
        "recheck:guest-changed",
        "thread-lock:guest-expired",
        "recheck:guest-expired",
        "delete-checkpoints:guest-expired",
        "delete-parent:guest-expired",
    ]
    assert all(
        fragment in session.recheck_sql[0]
        for fragment in (
            "status <> 'busy'",
            "user_id ~",
            "guest_retention_policy",
            "guest_expires_at",
            "FOR UPDATE SKIP LOCKED",
        )
    )


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
