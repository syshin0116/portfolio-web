"""DB-independent tests for the one-time ownership migration."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

import pytest

from api.legacy_migration import (
    LegacyMigrationError,
    build_checkpoint_mapping,
    build_store_item_mapping,
    legacy_memory_prefixes,
    memory_prefix,
    migrate_legacy_data,
    resolve_legacy_owner,
)
from api.resource_scope import scoped_checkpoint_thread_id


def test_owner_resolution_prefers_explicit_auth_user():
    assert (
        resolve_legacy_owner(
            "owner-2",
            ["owner-1", "owner-2"],
            auth_users_table_exists=True,
        )
        == "owner-2"
    )


def test_owner_resolution_auto_selects_exactly_one_auth_user():
    assert (
        resolve_legacy_owner(None, ["only-owner"], auth_users_table_exists=True)
        == "only-owner"
    )


@pytest.mark.parametrize("users", [[], ["owner-1", "owner-2"]])
def test_owner_resolution_fails_when_automatic_choice_is_ambiguous(users):
    with pytest.raises(LegacyMigrationError, match="AGENT_LEGACY_OWNER_ID"):
        resolve_legacy_owner(None, users, auth_users_table_exists=True)


def test_explicit_owner_must_match_auth_user_when_table_exists():
    with pytest.raises(LegacyMigrationError, match="does not match"):
        resolve_legacy_owner(
            "missing-owner", ["real-owner"], auth_users_table_exists=True
        )


def test_checkpoint_mapping_rewrites_raw_ids_and_skips_scoped_ids():
    raw_thread = "11111111-1111-4111-8111-111111111111"
    scoped_thread = scoped_checkpoint_thread_id("owner", raw_thread)

    mapping = build_checkpoint_mapping(
        {raw_thread, scoped_thread}, {raw_thread: "owner"}, None
    )

    assert mapping == {raw_thread: scoped_thread}


def test_checkpoint_mapping_uses_fallback_for_orphaned_legacy_id():
    legacy_id = "deleted-public-thread"
    assert build_checkpoint_mapping({legacy_id}, {}, "owner") == {
        legacy_id: scoped_checkpoint_thread_id("owner", legacy_id)
    }


def test_store_planners_preserve_public_namespace_and_simple_memory_prefixes():
    custom_mapping = build_store_item_mapping(
        {"private.notes", "__users__." + "a" * 64 + ".already"}, "owner"
    )

    assert list(custom_mapping) == ["private.notes"]
    assert custom_mapping["private.notes"].endswith(".private.notes")
    assert legacy_memory_prefixes(
        {
            "filesystem",
            "assistant.filesystem",
            memory_prefix("owner"),
            "unrelated",
        }
    ) == ["assistant.filesystem", "filesystem"]


class _Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return []


class _Transaction(AbstractAsyncContextManager):
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.transaction_entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.connection.transaction_exited = True


class _Connection:
    def __init__(self):
        self.queries = []
        self.transaction_entered = False
        self.transaction_exited = False

    def transaction(self):
        return _Transaction(self)

    async def execute(self, query, params=()):
        self.queries.append((query, params))
        if "SELECT 1 FROM agent_migrations" in query:
            return _Cursor((1,))
        return _Cursor()


class _ConnectionContext(AbstractAsyncContextManager):
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class _Pool:
    def __init__(self):
        self.conn = _Connection()

    def connection(self):
        return _ConnectionContext(self.conn)


@pytest.mark.asyncio
async def test_applied_marker_makes_startup_migration_idempotent():
    pool = _Pool()

    result = await migrate_legacy_data(pool)

    assert result.applied is False
    assert pool.conn.transaction_entered is True
    assert pool.conn.transaction_exited is True
    assert not any("SELECT thread_id::text" in query for query, _ in pool.conn.queries)


@pytest.mark.asyncio
async def test_fresh_worker_migration_does_not_require_langgraph_store_table():
    class FreshConnection(_Connection):
        async def execute(self, query, params=()):
            self.queries.append((query, params))
            if "SELECT 1 FROM agent_migrations" in query:
                return _Cursor(None)
            if "SELECT thread_id::text, owner_id FROM threads" in query:
                return _Cursor()
            if "COUNT(*) FROM crons" in query:
                return _Cursor((0,))
            if "SELECT DISTINCT thread_id FROM" in query:
                return _Cursor()
            if "SELECT DISTINCT namespace FROM store_items" in query:
                return _Cursor()
            if "SELECT to_regclass" in query:
                return _Cursor((None,))
            return _Cursor()

    class FreshPool(_Pool):
        def __init__(self):
            self.conn = FreshConnection()

    pool = FreshPool()
    result = await migrate_legacy_data(pool)

    assert result.applied is True
    assert not any(
        "SELECT DISTINCT prefix FROM store" in query for query, _ in pool.conn.queries
    )
