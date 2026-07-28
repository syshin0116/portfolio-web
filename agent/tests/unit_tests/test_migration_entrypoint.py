"""One-shot Aegra migration job contract."""

from __future__ import annotations

import pytest

from agent import migrate


async def test_migration_upgrades_aegra_then_sets_up_and_closes_langgraph(
    monkeypatch,
):
    events = []

    async def migrations():
        events.append("alembic")

    async def initialize():
        events.append("persistence-setup")

    async def close():
        events.append("close")

    async def agent_schema(engine):
        assert engine is sentinel_engine
        events.append("agent-schema")

    sentinel_engine = object()
    monkeypatch.setattr(migrate, "run_migrations_async", migrations)
    monkeypatch.setattr(migrate.db_manager, "initialize", initialize)
    monkeypatch.setattr(migrate.db_manager, "get_engine", lambda: sentinel_engine)
    monkeypatch.setattr(migrate.db_manager, "close", close)
    monkeypatch.setattr(migrate, "migrate_agent_schema", agent_schema)
    monkeypatch.setattr(migrate, "_require_direct_database_url", lambda: None)

    await migrate.migrate_database()

    assert events == [
        "alembic",
        "persistence-setup",
        "agent-schema",
        "close",
    ]


async def test_migration_closes_database_manager_when_setup_fails(monkeypatch):
    events = []

    async def migrations():
        events.append("alembic")

    async def initialize():
        events.append("persistence-setup")
        raise RuntimeError("setup failed")

    async def close():
        events.append("close")

    monkeypatch.setattr(migrate, "run_migrations_async", migrations)
    monkeypatch.setattr(migrate.db_manager, "initialize", initialize)
    monkeypatch.setattr(migrate.db_manager, "close", close)
    monkeypatch.setattr(migrate, "_require_direct_database_url", lambda: None)

    with pytest.raises(RuntimeError, match="setup failed"):
        await migrate.migrate_database()

    assert events == ["alembic", "persistence-setup", "close"]


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:pass@ep-example-pooler.us-east-1.aws.neon.tech/db",
        "postgresql://user:pass@EP-EXAMPLE-POOLER.US-EAST-1.AWS.NEON.TECH./db",
        "postgresql:///db?host=ep-example-pooler.us-east-1.aws.neon.tech",
        (
            "postgresql://user:pass@ep-direct.us-east-1.aws.neon.tech:5432,"
            "ep-example-pooler.us-east-1.aws.neon.tech:5432/db"
        ),
    ],
    ids=["standard", "case-and-trailing-dot", "query-host", "multi-host"],
)
def test_migration_rejects_neon_pooler_url(monkeypatch, database_url):
    monkeypatch.setattr(
        migrate.settings.db,
        "DATABASE_URL",
        database_url,
    )

    with pytest.raises(RuntimeError, match="direct Neon"):
        migrate._require_direct_database_url()


def test_migration_rejects_neon_pooler_component_host(monkeypatch):
    monkeypatch.setattr(migrate.settings.db, "DATABASE_URL", None)
    monkeypatch.setattr(
        migrate.settings.db,
        "POSTGRES_HOST",
        "ep-example-pooler.us-east-1.aws.neon.tech",
    )

    with pytest.raises(RuntimeError, match="direct Neon"):
        migrate._require_direct_database_url()


@pytest.mark.parametrize(
    "database_url",
    [
        None,
        "postgresql://postgres@127.0.0.1:5432/aegra",
        "postgresql://user:pass@ep-example.us-east-1.aws.neon.tech/db",
        "postgresql://user:pass@ep-example-pooler.neon.tech.attacker.invalid/db",
    ],
    ids=["default-components", "local-postgres", "direct-neon", "non-neon-lookalike"],
)
def test_migration_accepts_non_pooler_database_urls(monkeypatch, database_url):
    monkeypatch.setattr(migrate.settings.db, "DATABASE_URL", database_url)

    migrate._require_direct_database_url()
