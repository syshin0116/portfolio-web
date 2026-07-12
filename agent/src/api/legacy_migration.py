"""One-time migration of pre-authorization Agent API data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from api.resource_scope import scoped_checkpoint_thread_id
from db import _ns_to_str, _scope_namespace, _str_to_ns, _user_namespace

MIGRATION_NAME = "user_resource_ownership_v1"
_MIGRATION_LOCK_ID = 7_041_160_101
_CUSTOM_SCOPE_RE = re.compile(r"^__users__\.[0-9a-f]{64}(?:\.|$)")
_MEMORY_SCOPE_RE = re.compile(r"^users\.[0-9a-f]{64}\.filesystem$")


class LegacyMigrationError(RuntimeError):
    """Raised when legacy data cannot be migrated without guessing."""


@dataclass(frozen=True)
class MigrationResult:
    applied: bool
    owner_id: str | None = None
    threads: int = 0
    crons: int = 0
    checkpoint_threads: int = 0
    store_namespaces: int = 0
    memory_prefixes: int = 0


def resolve_legacy_owner(
    configured_owner_id: str | None,
    auth_user_ids: list[str],
    *,
    auth_users_table_exists: bool,
) -> str:
    """Resolve the only identity that can safely own unscoped legacy data."""
    configured = (configured_owner_id or "").strip()
    if configured:
        if auth_users_table_exists and configured not in auth_user_ids:
            raise LegacyMigrationError(
                "AGENT_LEGACY_OWNER_ID does not match an Auth.js users.id"
            )
        return configured
    if len(auth_user_ids) == 1:
        return auth_user_ids[0]
    if not auth_users_table_exists:
        reason = "the Auth.js users table does not exist"
    else:
        reason = f"the Auth.js users table contains {len(auth_user_ids)} users"
    raise LegacyMigrationError(
        "Legacy Agent data needs an owner, but "
        f"{reason}. Set AGENT_LEGACY_OWNER_ID to the intended Auth.js users.id."
    )


def build_checkpoint_mapping(
    checkpoint_thread_ids: set[str],
    thread_owners: dict[str, str],
    fallback_owner_id: str | None,
) -> dict[str, str]:
    """Return legacy checkpointer IDs mapped to owner-scoped internal IDs."""
    already_scoped = {
        scoped_checkpoint_thread_id(owner_id, thread_id)
        for thread_id, owner_id in thread_owners.items()
    }
    mapping: dict[str, str] = {}
    for old_id in sorted(checkpoint_thread_ids):
        if old_id in already_scoped:
            continue
        owner_id = thread_owners.get(old_id) or fallback_owner_id
        if not owner_id:
            raise LegacyMigrationError(
                f"Checkpoint thread {old_id!r} has no matching owned thread"
            )
        mapping[old_id] = scoped_checkpoint_thread_id(owner_id, old_id)
    return mapping


def build_store_item_mapping(
    namespaces: set[str], owner_id: str | None
) -> dict[str, str]:
    legacy = sorted(ns for ns in namespaces if not _CUSTOM_SCOPE_RE.match(ns))
    if legacy and not owner_id:
        raise LegacyMigrationError("Legacy store_items rows have no owner")
    return {
        namespace: _ns_to_str(_scope_namespace(owner_id, _str_to_ns(namespace)))
        for namespace in legacy
        if owner_id
    }


def legacy_memory_prefixes(prefixes: set[str]) -> list[str]:
    """Select only StoreBackend's simple legacy filesystem namespaces."""
    return sorted(
        prefix
        for prefix in prefixes
        if not _MEMORY_SCOPE_RE.match(prefix)
        and (prefix == "filesystem" or prefix.endswith(".filesystem"))
    )


def memory_prefix(owner_id: str) -> str:
    return ".".join(["users", _user_namespace(owner_id)[1], "filesystem"])


async def _fetch_all(conn: Any, query: str, params: tuple[Any, ...] = ()) -> list:
    cursor = await conn.execute(query, params)
    return list(await cursor.fetchall())


async def _fetch_one(conn: Any, query: str, params: tuple[Any, ...] = ()):
    cursor = await conn.execute(query, params)
    return await cursor.fetchone()


async def _table_exists(conn: Any, table: str) -> bool:
    row = await _fetch_one(conn, "SELECT to_regclass(%s)", (f"public.{table}",))
    return bool(row and row[0])


async def _assert_no_checkpoint_conflicts(
    conn: Any, table: str, key_columns: tuple[str, ...], old_id: str, new_id: str
) -> None:
    join = " AND ".join(f"new.{column} = old.{column}" for column in key_columns)
    row = await _fetch_one(
        conn,
        f"""SELECT EXISTS (
            SELECT 1 FROM {table} old JOIN {table} new ON {join}
            WHERE old.thread_id = %s AND new.thread_id = %s
        )""",
        (old_id, new_id),
    )
    if row and row[0]:
        raise LegacyMigrationError(
            f"Cannot migrate {table} thread {old_id}: target {new_id} conflicts"
        )


async def _migrate_checkpoints(conn: Any, mapping: dict[str, str]) -> None:
    tables = {
        "checkpoints": ("checkpoint_ns", "checkpoint_id"),
        "checkpoint_blobs": ("checkpoint_ns", "channel", "version"),
        "checkpoint_writes": (
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
        ),
    }
    for old_id, new_id in mapping.items():
        for table, keys in tables.items():
            await _assert_no_checkpoint_conflicts(conn, table, keys, old_id, new_id)
        for table in tables:
            await conn.execute(
                f"UPDATE {table} SET thread_id = %s WHERE thread_id = %s",
                (new_id, old_id),
            )


async def _migrate_store_items(conn: Any, mapping: dict[str, str]) -> None:
    for old_namespace, new_namespace in mapping.items():
        conflict = await _fetch_one(
            conn,
            """SELECT EXISTS (
                SELECT 1 FROM store_items old JOIN store_items new
                  ON new.namespace = %s AND new.key = old.key
                WHERE old.namespace = %s
            )""",
            (new_namespace, old_namespace),
        )
        if conflict and conflict[0]:
            raise LegacyMigrationError(
                f"Cannot migrate store_items namespace {old_namespace}: target conflicts"
            )
        await conn.execute(
            "UPDATE store_items SET namespace = %s WHERE namespace = %s",
            (new_namespace, old_namespace),
        )


async def _migrate_memory_store(conn: Any, prefixes: list[str], owner_id: str) -> None:
    if not prefixes:
        return
    target = memory_prefix(owner_id)
    duplicate = await _fetch_one(
        conn,
        """SELECT key FROM store WHERE prefix = ANY(%s)
        GROUP BY key HAVING COUNT(*) > 1 LIMIT 1""",
        (prefixes,),
    )
    if duplicate:
        raise LegacyMigrationError(
            "Legacy LangGraph memory prefixes contain duplicate keys"
        )
    conflict = await _fetch_one(
        conn,
        """SELECT EXISTS (
            SELECT 1 FROM store old JOIN store new
              ON new.prefix = %s AND new.key = old.key
            WHERE old.prefix = ANY(%s)
        )""",
        (target, prefixes),
    )
    if conflict and conflict[0]:
        raise LegacyMigrationError(
            "Legacy LangGraph memory conflicts with the scoped target namespace"
        )

    has_vectors = await _table_exists(conn, "store_vectors")
    for old_prefix in prefixes:
        await conn.execute(
            """INSERT INTO store
            (prefix, key, value, created_at, updated_at, expires_at, ttl_minutes)
            SELECT %s, key, value, created_at, updated_at, expires_at, ttl_minutes
            FROM store WHERE prefix = %s""",
            (target, old_prefix),
        )
        if has_vectors:
            await conn.execute(
                """INSERT INTO store_vectors
                (prefix, key, field_name, embedding, created_at, updated_at)
                SELECT %s, key, field_name, embedding, created_at, updated_at
                FROM store_vectors WHERE prefix = %s""",
                (target, old_prefix),
            )
        await conn.execute("DELETE FROM store WHERE prefix = %s", (old_prefix,))


async def migrate_legacy_data(
    pool: Any, configured_owner_id: str | None = None
) -> MigrationResult:
    """Migrate legacy resources once, atomically, before the API starts serving."""
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
        )
        marker = await _fetch_one(
            conn,
            "SELECT 1 FROM agent_migrations WHERE name = %s",
            (MIGRATION_NAME,),
        )
        if marker:
            return MigrationResult(applied=False)

        thread_rows = await _fetch_all(
            conn, "SELECT thread_id::text, owner_id FROM threads"
        )
        thread_owners_optional = {str(row[0]): row[1] for row in thread_rows}
        ownerless_threads = sum(
            owner_id is None for owner_id in thread_owners_optional.values()
        )
        cron_row = await _fetch_one(
            conn, "SELECT COUNT(*) FROM crons WHERE owner_id IS NULL"
        )
        ownerless_crons = int(cron_row[0]) if cron_row else 0
        checkpoint_rows = await _fetch_all(
            conn,
            """SELECT DISTINCT thread_id FROM (
                    SELECT thread_id FROM checkpoints
                    UNION SELECT thread_id FROM checkpoint_blobs
                    UNION SELECT thread_id FROM checkpoint_writes
                ) legacy_checkpoint_threads""",
        )
        checkpoint_ids = {str(row[0]) for row in checkpoint_rows}
        namespace_rows = await _fetch_all(
            conn, "SELECT DISTINCT namespace FROM store_items"
        )
        namespaces = {str(row[0]) for row in namespace_rows}
        store_table_exists = await _table_exists(conn, "store")
        prefix_rows = (
            await _fetch_all(conn, "SELECT DISTINCT prefix FROM store")
            if store_table_exists
            else []
        )
        prefixes = {str(row[0]) for row in prefix_rows}

        known_owners = {
            thread_id: str(owner_id)
            for thread_id, owner_id in thread_owners_optional.items()
            if owner_id is not None
        }
        known_scoped = {
            scoped_checkpoint_thread_id(owner_id, thread_id)
            for thread_id, owner_id in known_owners.items()
        }
        unmatched_checkpoints = checkpoint_ids - set(known_owners) - known_scoped
        legacy_namespaces = {
            namespace
            for namespace in namespaces
            if not _CUSTOM_SCOPE_RE.match(namespace)
        }
        memory_prefix_list = legacy_memory_prefixes(prefixes)
        needs_fallback_owner = bool(
            ownerless_threads
            or ownerless_crons
            or unmatched_checkpoints
            or legacy_namespaces
            or memory_prefix_list
        )

        owner_id: str | None = None
        if needs_fallback_owner:
            users_table_exists = await _table_exists(conn, "users")
            auth_user_rows = (
                await _fetch_all(conn, "SELECT id::text FROM users ORDER BY id")
                if users_table_exists
                else []
            )
            owner_id = resolve_legacy_owner(
                configured_owner_id,
                [str(row[0]) for row in auth_user_rows],
                auth_users_table_exists=users_table_exists,
            )
            await conn.execute(
                "UPDATE threads SET owner_id = %s WHERE owner_id IS NULL",
                (owner_id,),
            )
            await conn.execute(
                "UPDATE crons SET owner_id = %s WHERE owner_id IS NULL",
                (owner_id,),
            )

        thread_owners = {
            thread_id: str(existing_owner or owner_id)
            for thread_id, existing_owner in thread_owners_optional.items()
            if existing_owner or owner_id
        }
        checkpoint_mapping = build_checkpoint_mapping(
            checkpoint_ids, thread_owners, owner_id
        )
        store_mapping = build_store_item_mapping(namespaces, owner_id)
        await _migrate_checkpoints(conn, checkpoint_mapping)
        await _migrate_store_items(conn, store_mapping)
        if memory_prefix_list:
            if not owner_id:
                raise LegacyMigrationError("Legacy LangGraph memory has no owner")
            await _migrate_memory_store(conn, memory_prefix_list, owner_id)

        await conn.execute("ALTER TABLE threads ALTER COLUMN owner_id SET NOT NULL")
        await conn.execute("ALTER TABLE crons ALTER COLUMN owner_id SET NOT NULL")
        await conn.execute(
            "INSERT INTO agent_migrations (name) VALUES (%s)",
            (MIGRATION_NAME,),
        )
        return MigrationResult(
            applied=True,
            owner_id=owner_id,
            threads=ownerless_threads,
            crons=ownerless_crons,
            checkpoint_threads=len(checkpoint_mapping),
            store_namespaces=len(store_mapping),
            memory_prefixes=len(memory_prefix_list),
        )
