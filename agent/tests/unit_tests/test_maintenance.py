"""Checkpoint-first retention behavior for anonymous guest threads."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import maintenance
from agent.guest_thread_lock import guest_thread_lock_key
from agent.identity import CANONICAL_ANONYMOUS_SUBJECT_PATTERN
from agent.maintenance import (
    GUEST_RETENTION_POLICY,
    MAX_GC_BATCH_SIZE,
    MAX_RECONCILE_BATCH_SIZE,
    STALE_GUEST_RUN_ERROR,
    STALE_GUEST_RUN_THRESHOLD_SECONDS,
    GuestGCResult,
    MaintenanceResult,
    StaleGuestRunResult,
    collect_expired_guest_threads,
    reconcile_stale_guest_runs,
)
from agent.recovery import (
    RECOVERED_GUEST_RUN_FENCE_KEY,
    RECOVERED_GUEST_RUN_FENCE_VALUE,
)

_IDENTITY_A = "anon:123e4567-e89b-42d3-a456-426614174000"
_IDENTITY_B = "anon:123e4567-e89b-42d3-a456-426614174001"


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


class _RowsResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _OptionalRowResult:
    def __init__(self, value):
        self.value = value

    def one_or_none(self):
        return self.value


class _Session:
    def __init__(
        self,
        events,
        *,
        lock_acquired=True,
        thread_ids=(),
        eligible_thread_ids=None,
        contended_thread_ids=(),
        candidate_rows=(),
        liveness_lock_results=(),
        locked_rows=(),
        failed_run_ids=(),
        quarantined_keys=None,
        released_thread_ids=(),
    ):
        self.events = events
        self.lock_acquired = lock_acquired
        self.thread_ids = thread_ids
        self.eligible_thread_ids = (
            set(thread_ids) if eligible_thread_ids is None else set(eligible_thread_ids)
        )
        self.contended_thread_ids = set(contended_thread_ids)
        self.thread_ids_by_lock_key = {
            guest_thread_lock_key(thread_id): thread_id
            for thread_id in {
                *thread_ids,
                *(row[1] for row in candidate_rows),
            }
        }
        self.selection_parameters = None
        self.candidate_sql = None
        self.recheck_sql = []
        self.recheck_parameters = []
        self.candidate_rows = candidate_rows
        self.liveness_lock_results = iter(liveness_lock_results)
        self.locked_rows = iter(locked_rows or candidate_rows)
        self.failed_run_ids = failed_run_ids
        self.quarantined_keys = (
            tuple(candidate_rows)
            if quarantined_keys is None
            else tuple(quarantined_keys)
        )
        self.released_thread_ids = released_thread_ids
        self.liveness_parameters = []
        self.locked_parameters = []
        self.failed_parameters = None
        self.quarantine_parameters = None
        self.released_parameters = None

    def begin(self):
        return _AsyncContext(None)

    async def execute(self, statement, parameters):
        sql = str(statement)
        if "pg_try_advisory_xact_lock" in sql:
            lock_key = parameters["lock_key"]
            if lock_key in {
                maintenance._GC_LOCK_KEY,
                maintenance._RECONCILE_LOCK_KEY,
            }:
                self.events.append("lock")
                return _ScalarResult(self.lock_acquired)
            thread_id = self.thread_ids_by_lock_key.get(lock_key)
            if thread_id is not None:
                self.events.append(f"thread-lock:{thread_id}")
                return _ScalarResult(thread_id not in self.contended_thread_ids)
            self.events.append("try-candidate-lock")
            self.liveness_parameters.append(parameters)
            return _ScalarResult(next(self.liveness_lock_results, True))
        if "r.run_id = :run_id" in sql:
            self.events.append("recheck-stale-run")
            self.locked_parameters.append(parameters)
            return _OptionalRowResult(next(self.locked_rows, None))
        if "SELECT r.run_id, r.thread_id, r.user_id" in sql:
            self.events.append("select-stale-runs")
            self.selection_parameters = parameters
            return _RowsResult(self.candidate_rows)
        if "UPDATE runs" in sql:
            self.events.append("fail-stale-runs")
            self.failed_parameters = parameters
            return _ScalarsResult(self.failed_run_ids)
        if "INSERT INTO agent_guest_execution_quarantine" in sql:
            self.events.append("quarantine-stale-runs")
            self.quarantine_parameters = parameters
            return _RowsResult(self.quarantined_keys)
        if "UPDATE thread AS t" in sql:
            self.events.append("release-threads")
            self.released_parameters = parameters
            return _ScalarsResult(self.released_thread_ids)
        if "SELECT thread_id" in sql and "thread_id" not in parameters:
            self.events.append("select")
            self.selection_parameters = parameters
            self.candidate_sql = sql
            return _ScalarsResult(self.thread_ids)
        if "SELECT thread_id" in sql:
            thread_id = parameters["thread_id"]
            self.events.append(f"recheck:{thread_id}")
            self.recheck_sql.append(sql)
            self.recheck_parameters.append(parameters)
            return _OptionalScalarResult(
                thread_id if thread_id in self.eligible_thread_ids else None
            )
        if "DELETE FROM agent_guest_execution_quarantine" in sql:
            thread_id = parameters["thread_id"]
            self.events.append(f"delete-quarantine:{thread_id}")
            return SimpleNamespace(rowcount=1)
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


async def test_reconcile_fails_only_selected_stale_local_guest_runs(monkeypatch):
    events = []
    session = _Session(
        events,
        candidate_rows=(
            ("run-a", "guest-thread-a", _IDENTITY_A),
            ("run-b", "guest-thread-b", _IDENTITY_B),
        ),
        liveness_lock_results=(True, True),
        failed_run_ids=("run-a", "run-b"),
        released_thread_ids=("guest-thread-a", "guest-thread-b"),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await reconcile_stale_guest_runs(batch_size=7)

    assert result == StaleGuestRunResult(
        lock_acquired=True,
        liveness_skipped_runs=0,
        reconciled_runs=2,
        released_threads=2,
        batch_limit=7,
        stale_after_seconds=STALE_GUEST_RUN_THRESHOLD_SECONDS,
    )
    assert events == [
        "lock",
        "select-stale-runs",
        "try-candidate-lock",
        "thread-lock:guest-thread-a",
        "recheck-stale-run",
        "try-candidate-lock",
        "thread-lock:guest-thread-b",
        "recheck-stale-run",
        "fail-stale-runs",
        "quarantine-stale-runs",
        "release-threads",
    ]
    assert session.selection_parameters == {
        "candidate_limit": MAX_RECONCILE_BATCH_SIZE,
        "guest_subject_pattern": maintenance._CANONICAL_GUEST_SUBJECT_PATTERN,
        "retention_policy": GUEST_RETENTION_POLICY,
        "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
    }
    assert len(session.liveness_parameters) == 2
    assert all(
        isinstance(parameters["lock_key"], int)
        for parameters in session.liveness_parameters
    )
    assert (
        session.liveness_parameters[0]["lock_key"]
        != session.liveness_parameters[1]["lock_key"]
    )
    assert session.locked_parameters == [
        {
            "guest_subject_pattern": maintenance._CANONICAL_GUEST_SUBJECT_PATTERN,
            "identity": _IDENTITY_A,
            "retention_policy": GUEST_RETENTION_POLICY,
            "run_id": "run-a",
            "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
            "thread_id": "guest-thread-a",
        },
        {
            "guest_subject_pattern": maintenance._CANONICAL_GUEST_SUBJECT_PATTERN,
            "identity": _IDENTITY_B,
            "retention_policy": GUEST_RETENTION_POLICY,
            "run_id": "run-b",
            "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
            "thread_id": "guest-thread-b",
        },
    ]
    assert session.failed_parameters == {
        "error_message": STALE_GUEST_RUN_ERROR,
        "guest_subject_pattern": maintenance._CANONICAL_GUEST_SUBJECT_PATTERN,
        "recovery_fence_key": RECOVERED_GUEST_RUN_FENCE_KEY,
        "recovery_fence_value": RECOVERED_GUEST_RUN_FENCE_VALUE,
        "run_ids": ["run-a", "run-b"],
        "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
    }
    assert session.quarantine_parameters == {
        "identities": [_IDENTITY_A, _IDENTITY_B],
        "run_ids": ["run-a", "run-b"],
        "thread_ids": ["guest-thread-a", "guest-thread-b"],
    }
    assert session.released_parameters == {
        "guest_subject_pattern": maintenance._CANONICAL_GUEST_SUBJECT_PATTERN,
        "retention_policy": GUEST_RETENTION_POLICY,
        "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
        "thread_ids": ["guest-thread-a", "guest-thread-b"],
    }


async def test_reconcile_lock_contention_is_a_clean_noop(monkeypatch):
    events = []
    session = _Session(events, lock_acquired=False)
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await reconcile_stale_guest_runs()

    assert result.lock_acquired is False
    assert result.liveness_skipped_runs == 0
    assert result.reconciled_runs == 0
    assert result.released_threads == 0
    assert events == ["lock"]


async def test_reconcile_skips_a_candidate_with_a_live_execution_fence(
    monkeypatch,
):
    events = []
    session = _Session(
        events,
        candidate_rows=(("run-live", "thread-live", _IDENTITY_A),),
        liveness_lock_results=(False,),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await reconcile_stale_guest_runs()

    assert result == StaleGuestRunResult(
        lock_acquired=True,
        liveness_skipped_runs=1,
        reconciled_runs=0,
        released_threads=0,
        batch_limit=1_000,
        stale_after_seconds=900,
    )
    assert events == ["lock", "select-stale-runs", "try-candidate-lock"]


async def test_reconcile_rejects_a_partial_candidate_update(monkeypatch):
    session = _Session(
        [],
        candidate_rows=(
            ("run-a", "guest-thread-a", _IDENTITY_A),
            ("run-b", "guest-thread-b", _IDENTITY_B),
        ),
        liveness_lock_results=(True, True),
        failed_run_ids=("run-a",),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    with pytest.raises(RuntimeError, match="reconciliation count changed"):
        await reconcile_stale_guest_runs()


async def test_reconcile_skips_one_locked_row_and_recovers_the_next_candidate(
    monkeypatch,
):
    candidate_b = ("run-b", "guest-thread-b", _IDENTITY_B)
    events = []
    session = _Session(
        events,
        candidate_rows=(
            ("run-a", "guest-thread-a", _IDENTITY_A),
            candidate_b,
        ),
        liveness_lock_results=(True, True),
        locked_rows=(None, candidate_b),
        failed_run_ids=("run-b",),
        quarantined_keys=(candidate_b,),
        released_thread_ids=("guest-thread-b",),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await reconcile_stale_guest_runs(batch_size=1)

    assert result == StaleGuestRunResult(
        lock_acquired=True,
        liveness_skipped_runs=0,
        reconciled_runs=1,
        released_threads=1,
        batch_limit=1,
        stale_after_seconds=STALE_GUEST_RUN_THRESHOLD_SECONDS,
    )
    assert events == [
        "lock",
        "select-stale-runs",
        "try-candidate-lock",
        "thread-lock:guest-thread-a",
        "recheck-stale-run",
        "try-candidate-lock",
        "thread-lock:guest-thread-b",
        "recheck-stale-run",
        "fail-stale-runs",
        "quarantine-stale-runs",
        "release-threads",
    ]
    assert session.quarantine_parameters == {
        "identities": [_IDENTITY_B],
        "run_ids": ["run-b"],
        "thread_ids": ["guest-thread-b"],
    }


async def test_reconcile_batch_size_caps_successes_after_bounded_overfetch(
    monkeypatch,
):
    candidate_a = ("run-a", "guest-thread-a", _IDENTITY_A)
    candidate_b = ("run-b", "guest-thread-b", _IDENTITY_B)
    events = []
    session = _Session(
        events,
        candidate_rows=(candidate_a, candidate_b),
        liveness_lock_results=(True,),
        locked_rows=(candidate_a,),
        failed_run_ids=("run-a",),
        quarantined_keys=(candidate_a,),
        released_thread_ids=("guest-thread-a",),
    )
    monkeypatch.setattr(
        maintenance,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    result = await reconcile_stale_guest_runs(batch_size=1)

    assert result.reconciled_runs == 1
    assert result.batch_limit == 1
    assert session.failed_parameters["run_ids"] == ["run-a"]
    assert "thread-lock:guest-thread-b" not in events


def test_reconcile_sql_excludes_fresh_leased_and_non_guest_rows():
    selection_sql = str(maintenance._STALE_LOCAL_GUEST_RUNS_SQL)
    recheck_sql = str(maintenance._LOCKED_STALE_LOCAL_GUEST_RUN_SQL)
    failure_sql = str(maintenance._FAIL_STALE_LOCAL_GUEST_RUNS_SQL)
    release_sql = str(maintenance._RELEASE_RECONCILED_GUEST_THREADS_SQL)

    assert "t.status = 'busy'" in selection_sql
    assert "t.user_id ~ :guest_subject_pattern" in selection_sql
    assert "guest_retention_policy" in selection_sql
    assert "active.updated_at >" in selection_sql
    assert "active.claimed_by IS NOT NULL" in selection_sql
    assert "active.lease_expires_at IS NOT NULL" in selection_sql
    assert "r.claimed_by IS NULL" in selection_sql
    assert "r.lease_expires_at IS NULL" in selection_sql
    assert "FOR UPDATE" not in selection_sql
    assert "LIMIT :candidate_limit" in selection_sql
    assert "r.run_id = :run_id" in recheck_sql
    assert "r.thread_id = :thread_id" in recheck_sql
    assert "r.user_id = :identity" in recheck_sql
    assert "FOR UPDATE OF t, r" in recheck_sql
    assert "user_id ~ :guest_subject_pattern" in failure_sql
    assert "execution_params" in failure_sql
    assert "jsonb_build_object" in failure_sql
    assert "claimed_by IS NULL" in failure_sql
    assert "lease_expires_at IS NULL" in failure_sql
    assert "t.status = 'busy'" in release_sql
    assert "guest_retention_policy" in release_sql
    assert "active.status IN ('pending', 'running')" in release_sql


def test_recovery_recheck_skips_locked_rows_and_records_statement_time_quarantine():
    recheck_sql = str(maintenance._LOCKED_STALE_LOCAL_GUEST_RUN_SQL)
    failure_sql = str(maintenance._FAIL_STALE_LOCAL_GUEST_RUNS_SQL)
    quarantine_sql = str(maintenance._UPSERT_RECOVERED_GUEST_QUARANTINES_SQL)

    assert "FOR UPDATE OF t, r SKIP LOCKED" in recheck_sql
    assert "updated_at = clock_timestamp()" in failure_sql
    assert "recovered_at" in quarantine_sql
    assert "clock_timestamp()" in quarantine_sql
    assert "ON CONFLICT (run_id, thread_id, identity)" in quarantine_sql
    assert "drained_at" not in quarantine_sql.partition("DO UPDATE SET")[2]


def test_gc_candidate_and_exact_recheck_both_exclude_unresolved_quarantine():
    candidate_sql = str(maintenance._EXPIRED_GUEST_THREADS_SQL)
    recheck_sql = str(maintenance._EXPIRED_GUEST_THREAD_FOR_UPDATE_SQL)

    for sql in (candidate_sql, recheck_sql):
        assert "agent_guest_execution_quarantine" in sql
        assert "recovered_at IS NOT NULL" in sql
        assert "drained_at IS NULL" in sql
    assert "recovery_gc_grace_seconds" not in recheck_sql


def test_stale_policy_uses_the_reviewed_900_second_boundary():
    assert STALE_GUEST_RUN_THRESHOLD_SECONDS == 900
    for statement in (
        maintenance._STALE_LOCAL_GUEST_RUNS_SQL,
        maintenance._LOCKED_STALE_LOCAL_GUEST_RUN_SQL,
        maintenance._FAIL_STALE_LOCAL_GUEST_RUNS_SQL,
        maintenance._RELEASE_RECONCILED_GUEST_THREADS_SQL,
    ):
        assert "<=" in str(statement)


def test_maintenance_uses_the_pure_canonical_anonymous_identity_contract():
    assert (
        maintenance._CANONICAL_GUEST_SUBJECT_PATTERN
        == CANONICAL_ANONYMOUS_SUBJECT_PATTERN
    )


def test_gc_sql_keeps_the_canonical_fractional_second_quantifier():
    assert "[0-9]{1,6}" in str(maintenance._EXPIRED_GUEST_THREADS_SQL)


@pytest.mark.parametrize(
    "batch_size",
    [0, -1, True, MAX_RECONCILE_BATCH_SIZE + 1],
)
async def test_reconcile_batch_size_is_bounded(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        await reconcile_stale_guest_runs(batch_size=batch_size)


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
        "delete-quarantine:guest-thread-a",
        "delete-parent:guest-thread-a",
        "thread-lock:guest-thread-b",
        "recheck:guest-thread-b",
        "delete-checkpoints:guest-thread-b",
        "delete-quarantine:guest-thread-b",
        "delete-parent:guest-thread-b",
    ]
    assert session.selection_parameters == {
        "candidate_limit": MAX_GC_BATCH_SIZE,
        "retention_policy": GUEST_RETENTION_POLICY,
    }
    assert "FOR UPDATE" not in session.candidate_sql
    assert len(session.recheck_sql) == 2
    assert all("FOR UPDATE" in sql for sql in session.recheck_sql)
    assert session.recheck_parameters == [
        {
            "retention_policy": GUEST_RETENTION_POLICY,
            "thread_id": thread_id,
        }
        for thread_id in ("guest-thread-a", "guest-thread-b")
    ]


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
        "delete-quarantine:guest-expired",
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


async def test_gc_batch_size_caps_successes_after_bounded_overfetch(monkeypatch):
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
        batch_size=1,
        checkpointer=_Checkpointer(events),
    )

    assert result.deleted_threads == 1
    assert result.batch_limit == 1
    assert "thread-lock:guest-thread-b" not in events


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

    async def reconcile():
        events.append("reconcile")
        return StaleGuestRunResult(
            lock_acquired=True,
            liveness_skipped_runs=0,
            reconciled_runs=1,
            released_threads=1,
            batch_limit=MAX_RECONCILE_BATCH_SIZE,
            stale_after_seconds=STALE_GUEST_RUN_THRESHOLD_SECONDS,
        )

    async def collect():
        events.append("collect")
        raise RuntimeError("sweep failed")

    async def close():
        events.append("close")

    monkeypatch.setattr(maintenance.db_manager, "initialize", initialize)
    monkeypatch.setattr(maintenance, "reconcile_stale_guest_runs", reconcile)
    monkeypatch.setattr(maintenance, "collect_expired_guest_threads", collect)
    monkeypatch.setattr(maintenance.db_manager, "close", close)

    with pytest.raises(RuntimeError, match="sweep failed"):
        await maintenance.run_maintenance()

    assert events == ["initialize", "reconcile", "collect", "close"]


async def test_maintenance_reports_reconciliation_before_gc(monkeypatch):
    events = []
    stale_result = StaleGuestRunResult(
        lock_acquired=True,
        liveness_skipped_runs=1,
        reconciled_runs=2,
        released_threads=1,
        batch_limit=MAX_RECONCILE_BATCH_SIZE,
        stale_after_seconds=STALE_GUEST_RUN_THRESHOLD_SECONDS,
    )
    gc_result = GuestGCResult(
        lock_acquired=True,
        deleted_threads=1,
        batch_limit=MAX_GC_BATCH_SIZE,
    )

    async def initialize():
        events.append("initialize")

    async def reconcile():
        events.append("reconcile")
        return stale_result

    async def collect():
        events.append("collect")
        return gc_result

    async def close():
        events.append("close")

    monkeypatch.setattr(maintenance.db_manager, "initialize", initialize)
    monkeypatch.setattr(maintenance, "reconcile_stale_guest_runs", reconcile)
    monkeypatch.setattr(maintenance, "collect_expired_guest_threads", collect)
    monkeypatch.setattr(maintenance.db_manager, "close", close)

    result = await maintenance.run_maintenance()

    assert result.stale_guest_runs is stale_result
    assert result == MaintenanceResult(
        lock_acquired=True,
        deleted_threads=1,
        batch_limit=MAX_GC_BATCH_SIZE,
        stale_guest_runs=stale_result,
    )
    assert events == ["initialize", "reconcile", "collect", "close"]


def test_maintenance_cli_preserves_gc_keys_and_adds_exact_stale_counts(
    monkeypatch,
    capsys,
):
    async def run():
        return MaintenanceResult(
            lock_acquired=True,
            deleted_threads=3,
            batch_limit=1_000,
            stale_guest_runs=StaleGuestRunResult(
                lock_acquired=True,
                liveness_skipped_runs=2,
                reconciled_runs=1,
                released_threads=1,
                batch_limit=1_000,
                stale_after_seconds=900,
            ),
        )

    monkeypatch.setattr(maintenance, "run_maintenance", run)

    maintenance.main()

    assert capsys.readouterr().out == (
        '{"batch_limit":1000,"deleted_threads":3,"lock_acquired":true,'
        '"stale_guest_runs":{"batch_limit":1000,"liveness_skipped_runs":2,'
        '"lock_acquired":true,"reconciled_runs":1,"released_threads":1,'
        '"stale_after_seconds":900}}\n'
    )


def test_maintenance_module_cli_runs_without_agent_auth_secret(
    tmp_path: Path,
):
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        textwrap.dedent(
            """
            import asyncio
            from dataclasses import dataclass

            @dataclass
            class StaleResult:
                lock_acquired: bool = True
                liveness_skipped_runs: int = 2
                reconciled_runs: int = 1
                released_threads: int = 1
                batch_limit: int = 1000
                stale_after_seconds: int = 900

            @dataclass
            class MaintenanceResult:
                lock_acquired: bool = True
                deleted_threads: int = 3
                batch_limit: int = 1000
                stale_guest_runs: StaleResult = None

                def __post_init__(self):
                    if self.stale_guest_runs is None:
                        self.stale_guest_runs = StaleResult()

            def run_without_database(coroutine):
                coroutine.close()
                return MaintenanceResult()

            asyncio.run = run_without_database
            """
        ),
        encoding="utf-8",
    )
    agent_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("AGENT_AUTH_SECRET", None)
    python_path = [str(tmp_path), str(agent_root / "src")]
    if environment.get("PYTHONPATH"):
        python_path.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path)

    result = subprocess.run(
        [sys.executable, "-m", "agent.maintenance"],
        cwd=agent_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == (
        '{"batch_limit":1000,"deleted_threads":3,"lock_acquired":true,'
        '"stale_guest_runs":{"batch_limit":1000,"liveness_skipped_runs":2,'
        '"lock_acquired":true,"reconciled_runs":1,"released_threads":1,'
        '"stale_after_seconds":900}}\n'
    )
