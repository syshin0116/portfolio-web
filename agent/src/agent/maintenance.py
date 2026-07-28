"""Bounded guest-thread maintenance for Postgres-backed Aegra."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from aegra_api.core.database import db_manager
from aegra_api.core.orm import get_session_maker
from sqlalchemy import text

from agent.guest_thread_lock import guest_thread_lock_key
from agent.identity import (
    CANONICAL_ANONYMOUS_SUBJECT_PATTERN as _CANONICAL_GUEST_SUBJECT_PATTERN,
)
from agent.recovery import (
    RECOVERED_GUEST_RUN_FENCE_KEY,
    RECOVERED_GUEST_RUN_FENCE_VALUE,
)
from agent.run_liveness import (
    STALE_GUEST_RUN_THRESHOLD_SECONDS,
    guest_execution_lock_key,
)

GUEST_RETENTION_POLICY = "anonymous-14d-v1"
MAX_GC_BATCH_SIZE = 1_000
MAX_RECONCILE_BATCH_SIZE = 1_000
_GC_CANDIDATE_SCAN_LIMIT = MAX_GC_BATCH_SIZE
_RECONCILE_CANDIDATE_SCAN_LIMIT = MAX_RECONCILE_BATCH_SIZE
STALE_GUEST_RUN_ERROR = (
    "Anonymous run stopped after the local executor became unavailable"
)
_GC_LOCK_KEY = 6005912693769056306
_UNRESOLVED_GUEST_QUARANTINE_PREDICATE = """
    NOT EXISTS (
        SELECT 1
        FROM agent_guest_execution_quarantine AS quarantine
        WHERE
            quarantine.thread_id = thread.thread_id
            AND quarantine.recovered_at IS NOT NULL
            AND quarantine.drained_at IS NULL
    )
"""
_EXPIRED_GUEST_THREAD_PREDICATE = r"""
    status <> 'busy'
    AND user_id ~
        '^anon:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    AND metadata_json ->> 'guest_retention_policy' = :retention_policy
    AND metadata_json ->> 'guest_expires_at' ~
        '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?Z$'
    AND metadata_json ->> 'guest_expires_at' <=
        to_char(
            timezone('UTC', CURRENT_TIMESTAMP),
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        )
"""
_RECONCILE_LOCK_KEY = 6005912693769056307
_TRY_CANDIDATE_LIVENESS_LOCK_SQL = text("SELECT pg_try_advisory_xact_lock(:lock_key)")
_EXPIRED_GUEST_THREADS_SQL = text(
    f"""
    SELECT thread_id
    FROM thread
    WHERE
        {_EXPIRED_GUEST_THREAD_PREDICATE}
        AND {_UNRESOLVED_GUEST_QUARANTINE_PREDICATE}
    ORDER BY metadata_json ->> 'guest_expires_at', thread_id
    LIMIT :candidate_limit
    """
)
_EXPIRED_GUEST_THREAD_FOR_UPDATE_SQL = text(
    f"""
    SELECT thread_id
    FROM thread
    WHERE
        thread_id = :thread_id
        AND {_EXPIRED_GUEST_THREAD_PREDICATE}
        AND {_UNRESOLVED_GUEST_QUARANTINE_PREDICATE}
    FOR UPDATE SKIP LOCKED
    """
)
_STALE_LOCAL_GUEST_RUNS_SQL = text(
    r"""
    SELECT r.run_id, r.thread_id, r.user_id
    FROM runs AS r
    JOIN thread AS t
        ON t.thread_id = r.thread_id
        AND t.user_id = r.user_id
    WHERE
        t.status = 'busy'
        AND t.user_id ~ :guest_subject_pattern
        AND t.metadata_json ->> 'guest_retention_policy' = :retention_policy
        AND t.updated_at <=
            CURRENT_TIMESTAMP - make_interval(secs => :stale_after_seconds)
        AND r.status IN ('pending', 'running')
        AND r.updated_at <=
            CURRENT_TIMESTAMP - make_interval(secs => :stale_after_seconds)
        AND r.claimed_by IS NULL
        AND r.lease_expires_at IS NULL
        AND NOT EXISTS (
            SELECT 1
            FROM runs AS active
            WHERE
                active.thread_id = t.thread_id
                AND active.status IN ('pending', 'running')
                AND (
                    active.updated_at >
                        CURRENT_TIMESTAMP
                        - make_interval(secs => :stale_after_seconds)
                    OR active.claimed_by IS NOT NULL
                    OR active.lease_expires_at IS NOT NULL
                )
        )
    ORDER BY r.updated_at, r.run_id
    LIMIT :candidate_limit
    """
)
_LOCKED_STALE_LOCAL_GUEST_RUN_SQL = text(
    r"""
    SELECT r.run_id, r.thread_id, r.user_id
    FROM runs AS r
    JOIN thread AS t
        ON t.thread_id = r.thread_id
        AND t.user_id = r.user_id
    WHERE
        r.run_id = :run_id
        AND r.thread_id = :thread_id
        AND r.user_id = :identity
        AND t.status = 'busy'
        AND t.user_id ~ :guest_subject_pattern
        AND t.metadata_json ->> 'guest_retention_policy' = :retention_policy
        AND t.updated_at <=
            CURRENT_TIMESTAMP - make_interval(secs => :stale_after_seconds)
        AND r.status IN ('pending', 'running')
        AND r.updated_at <=
            CURRENT_TIMESTAMP - make_interval(secs => :stale_after_seconds)
        AND r.claimed_by IS NULL
        AND r.lease_expires_at IS NULL
        AND NOT EXISTS (
            SELECT 1
            FROM runs AS active
            WHERE
                active.thread_id = t.thread_id
                AND active.status IN ('pending', 'running')
                AND (
                    active.updated_at >
                        CURRENT_TIMESTAMP
                        - make_interval(secs => :stale_after_seconds)
                    OR active.claimed_by IS NOT NULL
                    OR active.lease_expires_at IS NOT NULL
                )
        )
    FOR UPDATE OF t, r SKIP LOCKED
    """
)
_FAIL_STALE_LOCAL_GUEST_RUNS_SQL = text(
    r"""
    UPDATE runs
    SET
        status = 'error',
        error_message = :error_message,
        execution_params =
            COALESCE(execution_params, '{}'::jsonb)
            || jsonb_build_object(
                CAST(:recovery_fence_key AS text),
                CAST(:recovery_fence_value AS text)
            ),
        claimed_by = NULL,
        lease_expires_at = NULL,
        updated_at = clock_timestamp()
    WHERE
        run_id = ANY(:run_ids)
        AND status IN ('pending', 'running')
        AND user_id ~ :guest_subject_pattern
        AND updated_at <=
            CURRENT_TIMESTAMP - make_interval(secs => :stale_after_seconds)
        AND claimed_by IS NULL
        AND lease_expires_at IS NULL
    RETURNING run_id
    """
)
_UPSERT_RECOVERED_GUEST_QUARANTINES_SQL = text(
    r"""
    INSERT INTO agent_guest_execution_quarantine (
        run_id,
        thread_id,
        identity,
        recovered_at
    )
    SELECT
        recovered.run_id,
        recovered.thread_id,
        recovered.identity,
        clock_timestamp()
    FROM unnest(
        CAST(:run_ids AS text[]),
        CAST(:thread_ids AS text[]),
        CAST(:identities AS text[])
    ) AS recovered(run_id, thread_id, identity)
    ON CONFLICT (run_id, thread_id, identity)
    DO UPDATE SET
        recovered_at = COALESCE(
            agent_guest_execution_quarantine.recovered_at,
            EXCLUDED.recovered_at
        )
    RETURNING run_id, thread_id, identity
    """
)
_RELEASE_RECONCILED_GUEST_THREADS_SQL = text(
    r"""
    UPDATE thread AS t
    SET
        status = 'error',
        updated_at = clock_timestamp()
    WHERE
        t.thread_id = ANY(:thread_ids)
        AND t.status = 'busy'
        AND t.user_id ~ :guest_subject_pattern
        AND t.metadata_json ->> 'guest_retention_policy' = :retention_policy
        AND t.updated_at <=
            CURRENT_TIMESTAMP - make_interval(secs => :stale_after_seconds)
        AND NOT EXISTS (
            SELECT 1
            FROM runs AS active
            WHERE
                active.thread_id = t.thread_id
                AND active.status IN ('pending', 'running')
        )
    RETURNING thread_id
    """
)
_DELETE_GUEST_QUARANTINES_SQL = text(
    """
    DELETE FROM agent_guest_execution_quarantine
    WHERE thread_id = :thread_id
    """
)


@dataclass(frozen=True, slots=True)
class GuestGCResult:
    """One bounded sweep result without visitor identifiers."""

    lock_acquired: bool
    deleted_threads: int
    batch_limit: int


@dataclass(frozen=True, slots=True)
class StaleGuestRunResult:
    """One local-executor recovery sweep without visitor identifiers."""

    lock_acquired: bool
    liveness_skipped_runs: int
    reconciled_runs: int
    released_threads: int
    batch_limit: int
    stale_after_seconds: int


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    """Backward-compatible GC counts plus stale-run observations."""

    lock_acquired: bool
    deleted_threads: int
    batch_limit: int
    stale_guest_runs: StaleGuestRunResult


def _validate_batch_size(batch_size: int, *, maximum: int) -> None:
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= maximum
    ):
        raise ValueError(f"batch_size must be between 1 and {maximum}")


async def reconcile_stale_guest_runs(
    *,
    batch_size: int = MAX_RECONCILE_BATCH_SIZE,
) -> StaleGuestRunResult:
    """Fail orphaned Redis-off guest runs and release their busy threads.

    Aegra 0.9.24's local executor has no crash reaper. A hard process exit can
    therefore leave ``pending``/``running`` runs and ``busy`` threads forever.
    Redis worker rows carry lease state and are deliberately outside this
    project-owned recovery path. ``batch_size`` caps successful reconciliations;
    one bounded overfetch lets locked or contended candidates yield their place
    to eligible rows later in the same ordered scan.
    """
    _validate_batch_size(batch_size, maximum=MAX_RECONCILE_BATCH_SIZE)
    result_kwargs = {
        "batch_limit": batch_size,
        "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
    }

    maker = get_session_maker()
    async with maker() as session, session.begin():
        lock_result = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": _RECONCILE_LOCK_KEY},
        )
        if lock_result.scalar_one() is not True:
            return StaleGuestRunResult(
                lock_acquired=False,
                liveness_skipped_runs=0,
                reconciled_runs=0,
                released_threads=0,
                **result_kwargs,
            )

        parameters = {
            "candidate_limit": _RECONCILE_CANDIDATE_SCAN_LIMIT,
            "guest_subject_pattern": _CANONICAL_GUEST_SUBJECT_PATTERN,
            "retention_policy": GUEST_RETENTION_POLICY,
            "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
        }
        candidates = await session.execute(
            _STALE_LOCAL_GUEST_RUNS_SQL,
            parameters,
        )
        candidate_rows = tuple(candidates.all())
        if len(candidate_rows) > _RECONCILE_CANDIDATE_SCAN_LIMIT:
            raise RuntimeError("stale guest recovery exceeded its candidate scan limit")
        locked_candidates: list[tuple[str, str, str]] = []
        liveness_skipped_runs = 0
        for row in candidate_rows:
            if len(locked_candidates) >= batch_size:
                break
            run_id, thread_id, identity = row
            if not isinstance(run_id, str) or not run_id:
                raise RuntimeError("stale guest recovery selected an invalid run id")
            if not isinstance(thread_id, str) or not thread_id:
                raise RuntimeError("stale guest recovery selected an invalid thread id")
            if not isinstance(identity, str) or not identity:
                raise RuntimeError("stale guest recovery selected an invalid identity")
            liveness_lock = await session.execute(
                _TRY_CANDIDATE_LIVENESS_LOCK_SQL,
                {
                    "lock_key": guest_execution_lock_key(
                        run_id=run_id,
                        thread_id=thread_id,
                        identity=identity,
                    )
                },
            )
            acquired = liveness_lock.scalar_one()
            if acquired is False:
                liveness_skipped_runs += 1
                continue
            if acquired is not True:
                raise RuntimeError("guest liveness lock returned invalid data")
            thread_lock = await session.execute(
                _TRY_CANDIDATE_LIVENESS_LOCK_SQL,
                {"lock_key": guest_thread_lock_key(thread_id)},
            )
            thread_acquired = thread_lock.scalar_one()
            if thread_acquired is False:
                liveness_skipped_runs += 1
                continue
            if thread_acquired is not True:
                raise RuntimeError("guest thread lock returned invalid data")
            locked = await session.execute(
                _LOCKED_STALE_LOCAL_GUEST_RUN_SQL,
                {
                    "guest_subject_pattern": _CANONICAL_GUEST_SUBJECT_PATTERN,
                    "identity": identity,
                    "retention_policy": GUEST_RETENTION_POLICY,
                    "run_id": run_id,
                    "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
                    "thread_id": thread_id,
                },
            )
            locked_row = locked.one_or_none()
            if locked_row is None:
                continue
            if tuple(locked_row) != (run_id, thread_id, identity):
                raise RuntimeError("stale guest recovery recheck identity changed")
            locked_candidates.append((run_id, thread_id, identity))

        if not locked_candidates:
            return StaleGuestRunResult(
                lock_acquired=True,
                liveness_skipped_runs=liveness_skipped_runs,
                reconciled_runs=0,
                released_threads=0,
                **result_kwargs,
            )

        run_ids = [run_id for run_id, _thread_id, _identity in locked_candidates]
        thread_ids = [thread_id for _run_id, thread_id, _identity in locked_candidates]
        failed = await session.execute(
            _FAIL_STALE_LOCAL_GUEST_RUNS_SQL,
            {
                "error_message": STALE_GUEST_RUN_ERROR,
                "guest_subject_pattern": _CANONICAL_GUEST_SUBJECT_PATTERN,
                "recovery_fence_key": RECOVERED_GUEST_RUN_FENCE_KEY,
                "recovery_fence_value": RECOVERED_GUEST_RUN_FENCE_VALUE,
                "run_ids": run_ids,
                "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
            },
        )
        failed_run_ids = tuple(failed.scalars())
        if len(failed_run_ids) != len(run_ids) or set(failed_run_ids) != set(run_ids):
            raise RuntimeError("stale guest run reconciliation count changed")

        quarantined = await session.execute(
            _UPSERT_RECOVERED_GUEST_QUARANTINES_SQL,
            {
                "identities": [
                    identity for _run_id, _thread_id, identity in locked_candidates
                ],
                "run_ids": run_ids,
                "thread_ids": thread_ids,
            },
        )
        quarantined_keys = {tuple(row) for row in quarantined.all()}
        expected_quarantine_keys = set(locked_candidates)
        if quarantined_keys != expected_quarantine_keys:
            raise RuntimeError("stale guest quarantine identity changed")

        unique_thread_ids = list(dict.fromkeys(thread_ids))
        released = await session.execute(
            _RELEASE_RECONCILED_GUEST_THREADS_SQL,
            {
                "guest_subject_pattern": _CANONICAL_GUEST_SUBJECT_PATTERN,
                "retention_policy": GUEST_RETENTION_POLICY,
                "stale_after_seconds": STALE_GUEST_RUN_THRESHOLD_SECONDS,
                "thread_ids": unique_thread_ids,
            },
        )
        released_thread_ids = tuple(released.scalars())
        if len(released_thread_ids) != len(set(released_thread_ids)) or not set(
            released_thread_ids
        ).issubset(unique_thread_ids):
            raise RuntimeError("stale guest thread release count changed")

    return StaleGuestRunResult(
        lock_acquired=True,
        liveness_skipped_runs=liveness_skipped_runs,
        reconciled_runs=len(failed_run_ids),
        released_threads=len(released_thread_ids),
        **result_kwargs,
    )


async def collect_expired_guest_threads(
    *,
    batch_size: int = MAX_GC_BATCH_SIZE,
    checkpointer: Any | None = None,
) -> GuestGCResult:
    """Delete up to ``batch_size`` eligible checkpoint/parent pairs.

    The ordered candidate scan is independently bounded so lock contention or
    an exact-recheck miss does not consume the successful-deletion budget.
    """
    _validate_batch_size(batch_size, maximum=MAX_GC_BATCH_SIZE)
    active_checkpointer = checkpointer or db_manager.get_checkpointer()
    if not callable(getattr(active_checkpointer, "adelete_thread", None)):
        raise TypeError("checkpointer must provide adelete_thread")

    maker = get_session_maker()
    async with maker() as session, session.begin():
        lock_result = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": _GC_LOCK_KEY},
        )
        if lock_result.scalar_one() is not True:
            return GuestGCResult(
                lock_acquired=False,
                deleted_threads=0,
                batch_limit=batch_size,
            )
        candidates = await session.execute(
            _EXPIRED_GUEST_THREADS_SQL,
            {
                "candidate_limit": _GC_CANDIDATE_SCAN_LIMIT,
                "retention_policy": GUEST_RETENTION_POLICY,
            },
        )
        thread_ids = tuple(candidates.scalars())
        if len(thread_ids) > _GC_CANDIDATE_SCAN_LIMIT:
            raise RuntimeError("guest GC exceeded its candidate scan limit")
        deleted_threads = 0
        for thread_id in thread_ids:
            if deleted_threads >= batch_size:
                break
            if not isinstance(thread_id, str) or not thread_id:
                raise RuntimeError("guest GC selected an invalid thread id")
            thread_lock = await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": guest_thread_lock_key(thread_id)},
            )
            if thread_lock.scalar_one() is not True:
                continue
            current = await session.execute(
                _EXPIRED_GUEST_THREAD_FOR_UPDATE_SQL,
                {
                    "retention_policy": GUEST_RETENTION_POLICY,
                    "thread_id": thread_id,
                },
            )
            if current.scalar_one_or_none() is None:
                continue
            await active_checkpointer.adelete_thread(thread_id)
            await session.execute(
                _DELETE_GUEST_QUARANTINES_SQL,
                {"thread_id": thread_id},
            )
            deleted = await session.execute(
                text(
                    """
                    DELETE FROM thread
                    WHERE thread_id = :thread_id
                    """
                ),
                {"thread_id": thread_id},
            )
            if deleted.rowcount != 1:
                raise RuntimeError("guest GC parent deletion count changed")
            deleted_threads += 1

    return GuestGCResult(
        lock_acquired=True,
        deleted_threads=deleted_threads,
        batch_limit=batch_size,
    )


async def run_maintenance() -> MaintenanceResult:
    """Initialize persistence once, recover stale runs, then reap expired guests."""
    try:
        await db_manager.initialize()
        stale_guest_runs = await reconcile_stale_guest_runs()
        guest_gc = await collect_expired_guest_threads()
        return MaintenanceResult(
            lock_acquired=guest_gc.lock_acquired,
            deleted_threads=guest_gc.deleted_threads,
            batch_limit=guest_gc.batch_limit,
            stale_guest_runs=stale_guest_runs,
        )
    finally:
        await db_manager.close()


def main() -> None:
    result = asyncio.run(run_maintenance())
    print(json.dumps(asdict(result), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "GUEST_RETENTION_POLICY",
    "MAX_GC_BATCH_SIZE",
    "MAX_RECONCILE_BATCH_SIZE",
    "STALE_GUEST_RUN_ERROR",
    "STALE_GUEST_RUN_THRESHOLD_SECONDS",
    "GuestGCResult",
    "MaintenanceResult",
    "StaleGuestRunResult",
    "collect_expired_guest_threads",
    "reconcile_stale_guest_runs",
    "run_maintenance",
]
