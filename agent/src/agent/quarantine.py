"""Durable quarantine and owner-drain proofs for recovered guest executions."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aegra_api.core.database import db_manager
from aegra_api.core.orm import get_session_maker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from agent.identity import is_anonymous_identity

QUARANTINE_READ_TIMEOUT_SECONDS = 2.0
DRAIN_PROOF_CONNECT_TIMEOUT_SECONDS = 2.0
DRAIN_PROOF_QUERY_TIMEOUT_SECONDS = 2.0
DRAIN_PROOF_TOTAL_TIMEOUT_SECONDS = 5.0
DRAIN_PROOF_ATTEMPT_LIMIT = 4

_UNRESOLVED_THREAD_QUARANTINE_SQL = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM agent_guest_execution_quarantine AS quarantine
        WHERE
            quarantine.thread_id = :thread_id
            AND quarantine.identity = :identity
            AND quarantine.recovered_at IS NOT NULL
            AND quarantine.drained_at IS NULL
    )
    """
)
_MARK_EXECUTION_DRAINED_SQL = text(
    """
    INSERT INTO agent_guest_execution_quarantine (
        run_id,
        thread_id,
        identity,
        drained_at
    )
    VALUES (
        :run_id,
        :thread_id,
        :identity,
        clock_timestamp()
    )
    ON CONFLICT (run_id, thread_id, identity)
    DO UPDATE SET
        drained_at = COALESCE(
            agent_guest_execution_quarantine.drained_at,
            EXCLUDED.drained_at
        )
    RETURNING run_id, thread_id, identity
    """
)

logger = logging.getLogger(__name__)
_drain_proof_attempts = asyncio.BoundedSemaphore(DRAIN_PROOF_ATTEMPT_LIMIT)


class GuestQuarantineUnavailableError(RuntimeError):
    """The durable guest quarantine boundary could not be read or updated."""


def _validate_execution_key(
    *,
    run_id: str,
    thread_id: str,
    identity: str,
) -> None:
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required for guest quarantine")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("thread_id is required for guest quarantine")
    if not is_anonymous_identity(identity):
        raise ValueError("canonical guest identity is required for guest quarantine")


def _create_drain_proof_engine() -> AsyncEngine:
    """Create one bounded unpooled proof writer outside Aegra's ORM pool."""
    return create_async_engine(
        db_manager.get_engine().url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={
            "command_timeout": DRAIN_PROOF_QUERY_TIMEOUT_SECONDS,
            "prepared_statement_cache_size": 0,
            "timeout": DRAIN_PROOF_CONNECT_TIMEOUT_SECONDS,
        },
    )


async def guest_thread_has_unresolved_quarantine(
    *,
    thread_id: str,
    identity: str,
) -> bool:
    """Read the exact fail-closed replacement boundary under the thread lock."""
    _validate_execution_key(
        run_id="quarantine-read",
        thread_id=thread_id,
        identity=identity,
    )
    try:
        async with asyncio.timeout(QUARANTINE_READ_TIMEOUT_SECONDS):
            maker = get_session_maker()
            async with maker() as session:
                result = await session.execute(
                    _UNRESOLVED_THREAD_QUARANTINE_SQL,
                    {
                        "identity": identity,
                        "thread_id": thread_id,
                    },
                )
                unresolved = result.scalar_one()
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            raise
        raise GuestQuarantineUnavailableError(
            "guest quarantine read is unavailable"
        ) from error
    if type(unresolved) is not bool:
        raise GuestQuarantineUnavailableError(
            "guest quarantine read returned invalid data"
        )
    return unresolved


async def mark_guest_execution_drained(
    *,
    run_id: str,
    thread_id: str,
    identity: str,
) -> None:
    """Persist proof only after the old owner and its DB operation are terminal."""
    _validate_execution_key(
        run_id=run_id,
        thread_id=thread_id,
        identity=identity,
    )
    acquired = False
    engine: AsyncEngine | None = None
    try:
        async with asyncio.timeout(DRAIN_PROOF_TOTAL_TIMEOUT_SECONDS):
            await _drain_proof_attempts.acquire()
            acquired = True
            engine = _create_drain_proof_engine()
            async with engine.begin() as connection:
                async with asyncio.timeout(DRAIN_PROOF_QUERY_TIMEOUT_SECONDS):
                    result = await connection.execute(
                        _MARK_EXECUTION_DRAINED_SQL,
                        {
                            "identity": identity,
                            "run_id": run_id,
                            "thread_id": thread_id,
                        },
                    )
                    persisted = result.one()
            if tuple(persisted) != (run_id, thread_id, identity):
                raise RuntimeError("guest drain proof identity changed")
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            raise
        raise GuestQuarantineUnavailableError(
            "guest owner drain proof is unavailable"
        ) from error
    finally:
        if engine is not None:
            with suppress(BaseException):
                async with asyncio.timeout(DRAIN_PROOF_CONNECT_TIMEOUT_SECONDS):
                    await engine.dispose()
        if acquired:
            _drain_proof_attempts.release()


__all__ = [
    "DRAIN_PROOF_ATTEMPT_LIMIT",
    "DRAIN_PROOF_CONNECT_TIMEOUT_SECONDS",
    "DRAIN_PROOF_QUERY_TIMEOUT_SECONDS",
    "DRAIN_PROOF_TOTAL_TIMEOUT_SECONDS",
    "QUARANTINE_READ_TIMEOUT_SECONDS",
    "GuestQuarantineUnavailableError",
    "guest_thread_has_unresolved_quarantine",
    "mark_guest_execution_drained",
]
