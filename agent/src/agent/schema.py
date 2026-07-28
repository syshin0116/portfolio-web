"""Versioned project-owned PostgreSQL schema migrations."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.recovery import (
    RECOVERED_GUEST_RUN_FENCE_KEY,
    RECOVERED_GUEST_RUN_FENCE_VALUE,
)

_MIGRATION_LOCK_KEY = 6005912693769056305
_CREATE_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS agent_schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
_RECOVERY_FENCE_FUNCTION_BODY = f"""BEGIN
    IF OLD.execution_params ->> '{RECOVERED_GUEST_RUN_FENCE_KEY}'
        = '{RECOVERED_GUEST_RUN_FENCE_VALUE}'
    THEN
        RAISE EXCEPTION
            'recovered guest run is immutable: %',
            OLD.run_id
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END"""
_VERIFY_SCHEMA_INTEGRITY = """
SELECT
    (
        SELECT count(*) = 1
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace
            ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language
            ON language.oid = procedure.prolang
        WHERE
            namespace.nspname = 'public'
            AND procedure.proname =
                'agent_reject_recovered_guest_run_update'
            AND procedure.pronargs = 0
            AND procedure.prorettype = 'trigger'::regtype
            AND procedure.prokind = 'f'
            AND procedure.prosecdef IS FALSE
            AND procedure.prosrc = :recovery_fence_function_body
            AND language.lanname = 'plpgsql'
    )
    AND
    (
        SELECT count(*) = 1
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation
            ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS procedure
            ON procedure.oid = trigger.tgfoid
        WHERE
            namespace.nspname = 'public'
            AND relation.relname = 'runs'
            AND trigger.tgname =
                'agent_recovered_guest_run_update_guard'
            AND trigger.tgtype = 19
            AND trigger.tgenabled = 'O'
            AND trigger.tgisinternal IS FALSE
            AND trigger.tgqual IS NULL
            AND trigger.tgnargs = 0
            AND trigger.tgattr = ''::int2vector
            AND procedure.proname =
                'agent_reject_recovered_guest_run_update'
            AND procedure.pronargs = 0
            AND procedure.prosrc = :recovery_fence_function_body
    )
"""
_MIGRATIONS: Sequence[tuple[str, Sequence[str]]] = (
    (
        "0001_guest_daily_budget",
        (
            """
            CREATE TABLE IF NOT EXISTS agent_guest_daily_budget (
                budget_date date PRIMARY KEY,
                reserved_micro_usd bigint NOT NULL,
                run_count bigint NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT agent_guest_daily_budget_reserved_nonnegative
                    CHECK (reserved_micro_usd >= 0),
                CONSTRAINT agent_guest_daily_budget_run_count_positive
                    CHECK (run_count >= 1)
            )
            """,
        ),
    ),
    (
        "0002_recovered_guest_run_fence",
        (
            f"""
            CREATE OR REPLACE FUNCTION agent_reject_recovered_guest_run_update()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function${_RECOVERY_FENCE_FUNCTION_BODY}$function$
            """,
            """
            DROP TRIGGER IF EXISTS agent_recovered_guest_run_update_guard
            ON runs
            """,
            """
            CREATE TRIGGER agent_recovered_guest_run_update_guard
            BEFORE UPDATE ON runs
            FOR EACH ROW
            EXECUTE FUNCTION agent_reject_recovered_guest_run_update()
            """,
        ),
    ),
)


class AgentSchemaMigrationError(RuntimeError):
    """The database's project-owned schema is newer or internally inconsistent."""


async def migrate_agent_schema(engine: AsyncEngine) -> None:
    """Apply ordered project migrations under one transaction-scoped advisory lock."""
    known_versions = tuple(version for version, _statements in _MIGRATIONS)
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _MIGRATION_LOCK_KEY},
        )
        await connection.execute(text(_CREATE_MIGRATION_TABLE))
        result = await connection.execute(
            text(
                """
                SELECT version
                FROM agent_schema_migrations
                ORDER BY version
                """
            )
        )
        applied_versions = tuple(result.scalars())
        unknown = sorted(set(applied_versions) - set(known_versions))
        if unknown:
            raise AgentSchemaMigrationError(
                "database contains unknown agent schema migrations"
            )

        applied = set(applied_versions)
        for version, statements in _MIGRATIONS:
            if version in applied:
                continue
            for statement in statements:
                await connection.execute(text(statement))
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_schema_migrations (version)
                    VALUES (:version)
                    """
                ),
                {"version": version},
            )

        integrity = await connection.execute(
            text(_VERIFY_SCHEMA_INTEGRITY),
            {"recovery_fence_function_body": (_RECOVERY_FENCE_FUNCTION_BODY)},
        )
        if integrity.scalar_one() is not True:
            raise AgentSchemaMigrationError(
                "project schema recovery fence is missing or altered"
            )


__all__ = ["AgentSchemaMigrationError", "migrate_agent_schema"]
