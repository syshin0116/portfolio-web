"""Versioned project-owned PostgreSQL schema migrations."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_MIGRATION_LOCK_KEY = 6005912693769056305
_CREATE_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS agent_schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
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


__all__ = ["AgentSchemaMigrationError", "migrate_agent_schema"]
