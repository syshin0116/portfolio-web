"""Bounded guest-thread retention maintenance for Postgres-backed Aegra."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from aegra_api.core.database import db_manager
from aegra_api.core.orm import get_session_maker
from sqlalchemy import text

from agent.guest_thread_lock import guest_thread_lock_key

GUEST_RETENTION_POLICY = "anonymous-14d-v1"
MAX_GC_BATCH_SIZE = 1_000
_GC_LOCK_KEY = 6005912693769056306
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
_EXPIRED_GUEST_THREADS_SQL = text(
    f"""
    SELECT thread_id
    FROM thread
    WHERE {_EXPIRED_GUEST_THREAD_PREDICATE}
    ORDER BY metadata_json ->> 'guest_expires_at', thread_id
    LIMIT :batch_size
    """
)
_EXPIRED_GUEST_THREAD_FOR_UPDATE_SQL = text(
    f"""
    SELECT thread_id
    FROM thread
    WHERE
        thread_id = :thread_id
        AND {_EXPIRED_GUEST_THREAD_PREDICATE}
    FOR UPDATE SKIP LOCKED
    """
)


@dataclass(frozen=True, slots=True)
class GuestGCResult:
    """One bounded sweep result without visitor identifiers."""

    lock_acquired: bool
    deleted_threads: int
    batch_limit: int


def _validate_batch_size(batch_size: int) -> None:
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= MAX_GC_BATCH_SIZE
    ):
        raise ValueError(f"batch_size must be between 1 and {MAX_GC_BATCH_SIZE}")


async def collect_expired_guest_threads(
    *,
    batch_size: int = MAX_GC_BATCH_SIZE,
    checkpointer: Any | None = None,
) -> GuestGCResult:
    """Serialize, recheck, then delete expired guest checkpoint/parent pairs."""
    _validate_batch_size(batch_size)
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
                "batch_size": batch_size,
                "retention_policy": GUEST_RETENTION_POLICY,
            },
        )
        thread_ids = tuple(candidates.scalars())
        deleted_threads = 0
        for thread_id in thread_ids:
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


async def run_maintenance() -> GuestGCResult:
    """Initialize persistence once, perform one bounded sweep, and close cleanly."""
    try:
        await db_manager.initialize()
        return await collect_expired_guest_threads()
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
    "GuestGCResult",
    "collect_expired_guest_threads",
    "run_maintenance",
]
