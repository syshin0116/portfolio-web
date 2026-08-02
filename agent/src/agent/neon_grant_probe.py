"""Real-Neon runtime grant acceptance probe for the Cloud Run deployment gate."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

from aegra_api.core.database import db_manager
from aegra_api.settings import settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.database_url import require_direct_neon_database_url

INSUFFICIENT_PRIVILEGE_SQLSTATE = "42501"


class GrantBoundaryError(RuntimeError):
    """The runtime credential is either too weak or more privileged than reviewed."""


def _require_direct_database_url() -> None:
    for configured in {
        settings.db.database_url,
        settings.db.database_url_sync,
    }:
        require_direct_neon_database_url(
            configured,
            purpose="Neon runtime grant probe",
        )


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


async def _expect_insufficient_privilege(
    engine: AsyncEngine,
    statement: str,
) -> None:
    """Execute a transactional privilege probe and always roll it back."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        denied = False
        try:
            await connection.execute(text(statement))
        except DBAPIError as exc:
            if _sqlstate(exc) != INSUFFICIENT_PRIVILEGE_SQLSTATE:
                raise GrantBoundaryError(
                    "runtime denial probe failed for a reason other than "
                    "insufficient privilege"
                ) from exc
            denied = True
        finally:
            if transaction.is_active:
                await transaction.rollback()
        if not denied:
            raise GrantBoundaryError(
                "runtime credential unexpectedly passed a forbidden privilege probe"
            )


async def _require_non_admin_role(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication
                FROM pg_catalog.pg_roles
                WHERE rolname = current_user
                """
            )
        )
        row = result.mappings().one_or_none()
    if row is None:
        raise GrantBoundaryError("current database role was not visible in pg_roles")
    flags = ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication")
    if any(row.get(flag) is not False for flag in flags):
        raise GrantBoundaryError(
            "runtime database role has an administrative role attribute"
        )


async def _exercise_store_dml() -> None:
    store = db_manager.get_store()
    namespace = ("deployment-grant-probe",)
    key = uuid.uuid4().hex
    value: Mapping[str, Any] = {"probe": "runtime-dml"}
    await store.aput(namespace, key, dict(value), index=False)
    try:
        loaded = await store.aget(namespace, key)
        if loaded is None or loaded.value != value:
            raise GrantBoundaryError("runtime store DML round trip was inconsistent")
    finally:
        await store.adelete(namespace, key)


async def _exercise_guest_quarantine_dml(engine: AsyncEngine) -> None:
    """Prove the runtime/maintenance credential can own the safety boundary."""
    suffix = uuid.uuid4().hex
    run_id = f"grant-probe-run-{suffix}"
    thread_id = f"grant-probe-thread-{suffix}"
    identity = f"anon:{uuid.uuid4()}"
    parameters = {
        "identity": identity,
        "run_id": run_id,
        "thread_id": thread_id,
    }
    async with engine.begin() as connection:
        inserted = await connection.execute(
            text(
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
                RETURNING run_id, thread_id, identity
                """
            ),
            parameters,
        )
        if tuple(inserted.one()) != (run_id, thread_id, identity):
            raise GrantBoundaryError(
                "runtime quarantine INSERT result was inconsistent"
            )

        selected = await connection.execute(
            text(
                """
                SELECT recovered_at, drained_at
                FROM agent_guest_execution_quarantine
                WHERE
                    run_id = :run_id
                    AND thread_id = :thread_id
                    AND identity = :identity
                """
            ),
            parameters,
        )
        recovered_at, drained_at = selected.one()
        if recovered_at is not None or drained_at is None:
            raise GrantBoundaryError(
                "runtime quarantine SELECT result was inconsistent"
            )

        updated = await connection.execute(
            text(
                """
                UPDATE agent_guest_execution_quarantine
                SET recovered_at = clock_timestamp()
                WHERE
                    run_id = :run_id
                    AND thread_id = :thread_id
                    AND identity = :identity
                RETURNING recovered_at, drained_at
                """
            ),
            parameters,
        )
        recovered_at, drained_at = updated.one()
        if recovered_at is None or drained_at is None:
            raise GrantBoundaryError(
                "runtime quarantine UPDATE result was inconsistent"
            )

        deleted = await connection.execute(
            text(
                """
                DELETE FROM agent_guest_execution_quarantine
                WHERE
                    run_id = :run_id
                    AND thread_id = :thread_id
                    AND identity = :identity
                RETURNING run_id, thread_id, identity
                """
            ),
            parameters,
        )
        if tuple(deleted.one()) != (run_id, thread_id, identity):
            raise GrantBoundaryError(
                "runtime quarantine DELETE result was inconsistent"
            )


async def probe_runtime_grants() -> None:
    """Require setup/DML while rejecting cross-schema and role administration."""
    _require_direct_database_url()
    try:
        # Aegra 0.9.25 calls saver/store setup during every runtime lifespan.
        # Successful initialization is therefore the exact temporary DDL allow-gate.
        await db_manager.initialize()
        engine = db_manager.get_engine()
        await _exercise_store_dml()
        await _exercise_guest_quarantine_dml(engine)
        await _require_non_admin_role(engine)

        suffix = uuid.uuid4().hex
        await _expect_insufficient_privilege(
            engine,
            f'CREATE SCHEMA "agent_forbidden_{suffix}"',
        )
        await _expect_insufficient_privilege(
            engine,
            f'CREATE ROLE "agent_forbidden_{suffix}"',
        )
    finally:
        await db_manager.close()


def main() -> None:
    asyncio.run(probe_runtime_grants())
    print("Neon runtime grant probe passed.")


if __name__ == "__main__":
    main()


__all__ = [
    "GrantBoundaryError",
    "INSUFFICIENT_PRIVILEGE_SQLSTATE",
    "probe_runtime_grants",
]
