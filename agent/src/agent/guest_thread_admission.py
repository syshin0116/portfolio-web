"""Durable admission for anonymous thread storage."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum

from aegra_api.core.orm import Thread as ThreadORM
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from agent.guest_thread_lock import (
    GuestThreadLockUnavailableError,
    guest_thread_create_advisory_lock,
)
from agent.identity import (
    CANONICAL_ANONYMOUS_SUBJECT_PATTERN,
    is_anonymous_identity,
)

GUEST_THREAD_CREATE_LOCK_TIMEOUT_SECONDS = 5.0
GUEST_STORED_THREAD_IDENTITY_LIMIT = 6
GUEST_STORED_THREAD_GLOBAL_LIMIT = 256


class GuestThreadAdmissionUnavailableError(RuntimeError):
    """The durable anonymous-thread admission boundary is unavailable."""


class GuestThreadCreateDecision(StrEnum):
    """Result observed while the global creation lock is still held."""

    NEW = "new"
    EXISTING_OWNED = "existing-owned"
    FOREIGN = "foreign"
    IDENTITY_LIMIT = "identity-limit"
    GLOBAL_LIMIT = "global-limit"


async def _guest_thread_create_decision(
    connection: AsyncConnection,
    *,
    thread_id: str,
    identity: str,
) -> GuestThreadCreateDecision:
    owner_row = (
        await connection.execute(
            select(ThreadORM.user_id).where(ThreadORM.thread_id == thread_id)
        )
    ).one_or_none()
    if owner_row is not None:
        return (
            GuestThreadCreateDecision.EXISTING_OWNED
            if owner_row.user_id == identity
            else GuestThreadCreateDecision.FOREIGN
        )

    identity_count, global_count = (
        await connection.execute(
            select(
                func.count().filter(ThreadORM.user_id == identity),
                func.count().filter(
                    ThreadORM.user_id.op("~")(CANONICAL_ANONYMOUS_SUBJECT_PATTERN)
                ),
            ).select_from(ThreadORM)
        )
    ).one()
    if identity_count >= GUEST_STORED_THREAD_IDENTITY_LIMIT:
        return GuestThreadCreateDecision.IDENTITY_LIMIT
    if global_count >= GUEST_STORED_THREAD_GLOBAL_LIMIT:
        return GuestThreadCreateDecision.GLOBAL_LIMIT
    return GuestThreadCreateDecision.NEW


@asynccontextmanager
async def admit_guest_thread_creation(
    *,
    thread_id: str,
    identity: str,
) -> AsyncIterator[GuestThreadCreateDecision]:
    """Serialize, count, and retain the global claim through caller completion.

    Counts intentionally include expired rows until checkpoint-first GC actually
    removes their parent thread. Existing owned IDs remain idempotent at either cap,
    while a foreign collision is reported without exposing its owner.
    """
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("thread_id must be a non-empty string")
    if not is_anonymous_identity(identity):
        raise ValueError("identity must be a canonical anonymous subject")

    try:
        async with guest_thread_create_advisory_lock(
            timeout_seconds=GUEST_THREAD_CREATE_LOCK_TIMEOUT_SECONDS,
        ) as connection:
            try:
                decision = await _guest_thread_create_decision(
                    connection,
                    thread_id=thread_id,
                    identity=identity,
                )
            except Exception as error:
                raise GuestThreadAdmissionUnavailableError(
                    "guest thread admission query failed"
                ) from error
            yield decision
    except GuestThreadLockUnavailableError as error:
        raise GuestThreadAdmissionUnavailableError(
            "guest thread admission lock failed"
        ) from error


__all__ = [
    "GUEST_STORED_THREAD_GLOBAL_LIMIT",
    "GUEST_STORED_THREAD_IDENTITY_LIMIT",
    "GUEST_THREAD_CREATE_LOCK_TIMEOUT_SECONDS",
    "GuestThreadAdmissionUnavailableError",
    "GuestThreadCreateDecision",
    "admit_guest_thread_creation",
]
