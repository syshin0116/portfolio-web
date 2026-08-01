"""Cross-process serialization for one public guest thread."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from aegra_api.settings import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncTransaction,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

COMMAND_GUEST_THREAD_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_DOMAIN = b"syshin0116.dev:guest-thread-lock:v1\0"
_CREATE_LOCK_DOMAIN = b"syshin0116.dev:guest-thread-create-lock:v1\0"
_LOCK_POLL_SECONDS = 0.025
_TRY_LOCK_SQL = text("SELECT pg_try_advisory_xact_lock(:lock_key)")


class GuestThreadLockUnavailableError(RuntimeError):
    """The per-thread PostgreSQL serialization boundary could not be acquired."""


def guest_thread_lock_key(thread_id: str) -> int:
    """Map one exact thread ID to a stable signed PostgreSQL bigint key."""
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("thread_id must be a non-empty string")
    digest = hashlib.sha256(_LOCK_DOMAIN + thread_id.encode("utf-8")).digest()
    unsigned = int.from_bytes(digest[:8], "big")
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def guest_thread_create_lock_key() -> int:
    """Return the one domain-separated key serializing public thread creation."""
    digest = hashlib.sha256(_CREATE_LOCK_DOMAIN).digest()
    unsigned = int.from_bytes(digest[:8], "big")
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def _create_lock_engine() -> AsyncEngine:
    """Create a connection outside Aegra's small shared ORM pool."""
    return create_async_engine(
        settings.db.database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"prepared_statement_cache_size": 0},
    )


class _GuestThreadTransactionLock:
    """One dedicated transaction that owns a transaction-scoped advisory lock."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        connection: AsyncConnection,
        transaction: AsyncTransaction,
    ) -> None:
        self._engine = engine
        self._connection = connection
        self._transaction = transaction
        self._close_task: asyncio.Task[None] | None = None

    @classmethod
    async def acquire(
        cls,
        lock_key: int,
        *,
        timeout_seconds: float,
    ) -> _GuestThreadTransactionLock:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")

        if type(lock_key) is not int or not -(2**63) <= lock_key < 2**63:
            raise ValueError("lock_key must be a signed PostgreSQL bigint")
        try:
            engine = _create_lock_engine()
        except Exception as error:
            raise GuestThreadLockUnavailableError(
                "guest thread serialization is unavailable"
            ) from error
        connection: AsyncConnection | None = None
        transaction: AsyncTransaction | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_seconds)
        try:
            async with asyncio.timeout(float(timeout_seconds)):
                connection = await engine.connect()
                transaction = await connection.begin()
                while True:
                    acquired = await connection.scalar(
                        _TRY_LOCK_SQL,
                        {"lock_key": lock_key},
                    )
                    if acquired is True:
                        return cls(
                            engine=engine,
                            connection=connection,
                            transaction=transaction,
                        )
                    remaining = deadline - loop.time()
                    await asyncio.sleep(min(_LOCK_POLL_SECONDS, max(0.0, remaining)))
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(
                _close_resources(
                    engine=engine,
                    connection=connection,
                    transaction=transaction,
                )
            )
            with suppress(asyncio.CancelledError):
                await _drain_cleanup_task(cleanup)
            raise
        except Exception as error:
            cleanup = asyncio.create_task(
                _close_resources(
                    engine=engine,
                    connection=connection,
                    transaction=transaction,
                )
            )
            await _drain_cleanup_task(cleanup)
            raise GuestThreadLockUnavailableError(
                "guest thread serialization is unavailable"
            ) from error

    async def aclose(self) -> None:
        """Drain rollback/close even if the request receives another cancel."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                _close_resources(
                    engine=self._engine,
                    connection=self._connection,
                    transaction=self._transaction,
                )
            )
        await _drain_cleanup_task(self._close_task)

    @property
    def connection(self) -> AsyncConnection:
        """Expose only the connection whose transaction owns the advisory lock."""
        return self._connection


async def _drain_cleanup_task(cleanup: asyncio.Task[None]) -> None:
    """Wait through repeated cancellation until one DB cleanup task is terminal."""
    interrupted: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:
            interrupted = error
    cleanup.result()
    if interrupted is not None:
        raise interrupted


async def _close_resources(
    *,
    engine: AsyncEngine,
    connection: AsyncConnection | None,
    transaction: AsyncTransaction | None,
) -> None:
    """Release the transaction lock without masking the protected operation."""
    if transaction is not None and transaction.is_active:
        try:
            await transaction.rollback()
        except Exception as error:
            logger.error(
                "guest thread lock rollback failed error_type=%s",
                type(error).__name__,
            )
    if connection is not None:
        try:
            await connection.close()
        except Exception as error:
            logger.error(
                "guest thread lock connection close failed error_type=%s",
                type(error).__name__,
            )
    try:
        await engine.dispose()
    except Exception as error:
        logger.error(
            "guest thread lock engine disposal failed error_type=%s",
            type(error).__name__,
        )


@asynccontextmanager
async def guest_thread_advisory_lock(
    thread_id: str,
    *,
    timeout_seconds: float,
) -> AsyncIterator[None]:
    """Hold one dedicated PostgreSQL transaction lock for the context lifetime."""
    lock = await _GuestThreadTransactionLock.acquire(
        guest_thread_lock_key(thread_id),
        timeout_seconds=timeout_seconds,
    )
    try:
        yield
    finally:
        await lock.aclose()


@asynccontextmanager
async def guest_thread_create_advisory_lock(
    *,
    timeout_seconds: float,
) -> AsyncIterator[AsyncConnection]:
    """Hold the dedicated global creation lock and expose its read transaction."""
    lock = await _GuestThreadTransactionLock.acquire(
        guest_thread_create_lock_key(),
        timeout_seconds=timeout_seconds,
    )
    try:
        yield lock.connection
    finally:
        await lock.aclose()


__all__ = [
    "COMMAND_GUEST_THREAD_LOCK_TIMEOUT_SECONDS",
    "GuestThreadLockUnavailableError",
    "guest_thread_advisory_lock",
    "guest_thread_create_advisory_lock",
    "guest_thread_create_lock_key",
    "guest_thread_lock_key",
]
