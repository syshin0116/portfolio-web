"""One-shot Aegra metadata, checkpointer, and store migration entrypoint."""

from __future__ import annotations

import asyncio

from aegra_api.core.database import db_manager
from aegra_api.core.migrations import run_migrations_async
from aegra_api.settings import settings

from agent.database_url import require_direct_neon_database_url
from agent.schema import migrate_agent_schema


def _require_direct_database_url() -> None:
    for configured in {
        settings.db.database_url,
        settings.db.database_url_sync,
    }:
        require_direct_neon_database_url(
            configured,
            purpose="Aegra migrations",
        )


async def migrate_database() -> None:
    """Upgrade Aegra, LangGraph persistence, then the project-owned schema."""
    _require_direct_database_url()
    await run_migrations_async()
    try:
        await db_manager.initialize()
        await migrate_agent_schema(db_manager.get_engine())
    finally:
        await db_manager.close()


def main() -> None:
    asyncio.run(migrate_database())


if __name__ == "__main__":
    main()
