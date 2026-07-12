"""Database operations for assistants, threads, runs, store, crons, and models."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_SETUP_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS assistants (
        assistant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        graph_id TEXT NOT NULL,
        config JSONB NOT NULL DEFAULT '{}',
        context JSONB NOT NULL DEFAULT '{}',
        metadata JSONB NOT NULL DEFAULT '{}',
        name TEXT NOT NULL DEFAULT 'Untitled',
        description TEXT,
        version INT NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS threads (
        thread_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        owner_id TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'idle',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS runs (
        run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        thread_id UUID REFERENCES threads(thread_id) ON DELETE CASCADE,
        assistant_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        input JSONB,
        command JSONB,
        config JSONB NOT NULL DEFAULT '{}',
        metadata JSONB NOT NULL DEFAULT '{}',
        kwargs JSONB NOT NULL DEFAULT '{}',
        multitask_strategy TEXT DEFAULT 'reject',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS crons (
        cron_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        owner_id TEXT NOT NULL,
        assistant_id UUID,
        thread_id UUID REFERENCES threads(thread_id) ON DELETE SET NULL,
        schedule TEXT NOT NULL,
        timezone TEXT,
        end_time TIMESTAMPTZ,
        input JSONB,
        config JSONB NOT NULL DEFAULT '{}',
        metadata JSONB NOT NULL DEFAULT '{}',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        next_run_date TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS store_items (
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        value JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (namespace, key)
    )""",
    """CREATE TABLE IF NOT EXISTS models (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        provider TEXT NOT NULL,
        model_id TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        is_default BOOLEAN NOT NULL DEFAULT FALSE,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "ALTER TABLE threads ADD COLUMN IF NOT EXISTS owner_id TEXT",
    "ALTER TABLE crons ADD COLUMN IF NOT EXISTS owner_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_threads_owner_id ON threads(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_thread_id ON runs(thread_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_crons_enabled ON crons(enabled)",
    "CREATE INDEX IF NOT EXISTS idx_crons_owner_id ON crons(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_store_namespace ON store_items(namespace)",
    "CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider)",
    "CREATE INDEX IF NOT EXISTS idx_models_enabled ON models(enabled)",
]

_SEED_MODELS = [
    ("openai", "openai/gpt-5.4", "GPT-5.4", True),
    ("openai", "openai/gpt-4.1", "GPT-4.1", False),
    ("openai", "openai/gpt-4.1-mini", "GPT-4.1 Mini", False),
    ("openai", "openai/o3", "o3", False),
    ("openai", "openai/o3-mini", "o3 Mini", False),
    ("anthropic", "anthropic/claude-sonnet-4-6", "Claude Sonnet 4.6", False),
    ("anthropic", "anthropic/claude-opus-4-6", "Claude Opus 4.6", False),
    ("anthropic", "anthropic/claude-haiku-4-5", "Claude Haiku 4.5", False),
    ("google_genai", "google_genai/gemini-2.5-pro", "Gemini 2.5 Pro", False),
    ("google_genai", "google_genai/gemini-2.5-flash", "Gemini 2.5 Flash", False),
]


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _ns_to_str(namespace: list[str]) -> str:
    return ".".join(namespace)


def _str_to_ns(s: str) -> list[str]:
    return s.split(".") if s else []


_USER_NAMESPACE_ROOT = "__users__"


def _user_namespace(user_id: str) -> list[str]:
    digest = hashlib.sha256(user_id.encode()).hexdigest()
    return [_USER_NAMESPACE_ROOT, digest]


def _scope_namespace(user_id: str, namespace: list[str]) -> list[str]:
    return [*_user_namespace(user_id), *namespace]


def _unscope_namespace(user_id: str, namespace: list[str]) -> list[str]:
    prefix = _user_namespace(user_id)
    if namespace[: len(prefix)] != prefix:
        raise ValueError("namespace does not belong to user")
    return namespace[len(prefix) :]


class _DictRowConnection:
    """Async context manager wrapper that sets row_factory=dict_row on acquire."""

    def __init__(self, conn_ctx):
        self._ctx = conn_ctx
        self._conn = None

    async def __aenter__(self):
        self._conn = await self._ctx.__aenter__()
        self._conn.row_factory = dict_row
        return self._conn

    async def __aexit__(self, *args):
        return await self._ctx.__aexit__(*args)


class DB:
    """Database access layer."""

    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    def _conn(self):
        """Get a connection with dict_row factory."""
        conn = self.pool.connection()
        # Wrap to set row_factory on the acquired connection
        return _DictRowConnection(conn)

    async def setup(self) -> None:
        async with self.pool.connection() as conn:
            for stmt in _SETUP_STATEMENTS:
                await conn.execute(stmt)
            # Seed default models
            for provider, model_id, display_name, is_default in _SEED_MODELS:
                await conn.execute(
                    """INSERT INTO models (provider, model_id, display_name, is_default)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (model_id) DO NOTHING""",
                    (provider, model_id, display_name, is_default),
                )
            # Seed default assistant
            await conn.execute(
                """INSERT INTO assistants (graph_id, name, metadata)
                SELECT 'agent', 'Blog Assistant', '{"name": "Blog Assistant"}'::jsonb
                WHERE NOT EXISTS (SELECT 1 FROM assistants WHERE graph_id = 'agent')"""
            )

    # ---- Assistants ----

    async def create_assistant(
        self,
        *,
        graph_id: str,
        config: dict | None = None,
        context: dict | None = None,
        metadata: dict | None = None,
        assistant_id: str | None = None,
        if_exists: str | None = None,
        name: str = "Untitled",
        description: str | None = None,
    ) -> dict[str, Any]:
        aid = assistant_id or _uuid()
        now = _now()
        async with self._conn() as conn:
            if if_exists == "do_nothing":
                row = await (
                    await conn.execute(
                        "SELECT * FROM assistants WHERE assistant_id = %s", (aid,)
                    )
                ).fetchone()
                if row:
                    return dict(row)

            row = await (
                await conn.execute(
                    """INSERT INTO assistants
                    (assistant_id, graph_id, config, context, metadata, name, description, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (assistant_id) DO UPDATE SET
                        graph_id = EXCLUDED.graph_id,
                        config = EXCLUDED.config,
                        context = EXCLUDED.context,
                        metadata = EXCLUDED.metadata,
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        version = assistants.version + 1,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *""",
                    (
                        aid,
                        graph_id,
                        json.dumps(config or {}),
                        json.dumps(context or {}),
                        json.dumps(metadata or {}),
                        name,
                        description,
                        now,
                        now,
                    ),
                )
            ).fetchone()
            return dict(row)

    async def get_assistant(self, assistant_id: str) -> dict[str, Any] | None:
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM assistants WHERE assistant_id = %s",
                    (assistant_id,),
                )
            ).fetchone()
            return dict(row) if row else None

    async def update_assistant(
        self, assistant_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        sets = []
        vals = []
        for k, v in kwargs.items():
            if v is not None:
                if k in ("config", "context", "metadata"):
                    sets.append(f"{k} = %s")
                    vals.append(json.dumps(v))
                else:
                    sets.append(f"{k} = %s")
                    vals.append(v)
        if not sets:
            return await self.get_assistant(assistant_id)
        sets.append("version = version + 1")
        sets.append("updated_at = %s")
        vals.append(_now())
        vals.append(assistant_id)
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    f"UPDATE assistants SET {', '.join(sets)} WHERE assistant_id = %s RETURNING *",
                    vals,
                )
            ).fetchone()
            return dict(row) if row else None

    async def delete_assistant(self, assistant_id: str) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "DELETE FROM assistants WHERE assistant_id = %s", (assistant_id,)
            )

    async def search_assistants(
        self,
        *,
        metadata: dict | None = None,
        graph_id: str | None = None,
        name: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = []
        vals: list[Any] = []
        if graph_id:
            where.append("graph_id = %s")
            vals.append(graph_id)
        if name:
            where.append("name ILIKE %s")
            vals.append(f"%{name}%")
        if metadata:
            where.append("metadata @> %s")
            vals.append(json.dumps(metadata))
        clause = " AND ".join(where) if where else "TRUE"
        vals.extend([limit, offset])
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT * FROM assistants WHERE {clause} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                    vals,
                )
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- Threads ----

    async def create_thread(
        self,
        *,
        owner_id: str,
        thread_id: str | None = None,
        metadata: dict | None = None,
        if_exists: str | None = None,
    ) -> dict[str, Any] | None:
        tid = thread_id or _uuid()
        now = _now()
        async with self._conn() as conn:
            if if_exists == "do_nothing":
                row = await (
                    await conn.execute(
                        "SELECT * FROM threads WHERE thread_id = %s AND owner_id = %s",
                        (tid, owner_id),
                    )
                ).fetchone()
                if row:
                    return dict(row)
            row = await (
                await conn.execute(
                    """INSERT INTO threads
                    (thread_id, owner_id, metadata, status, created_at, updated_at)
                    VALUES (%s, %s, %s, 'idle', %s, %s)
                    ON CONFLICT (thread_id) DO UPDATE SET
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    WHERE threads.owner_id = EXCLUDED.owner_id
                    RETURNING *""",
                    (tid, owner_id, json.dumps(metadata or {}), now, now),
                )
            ).fetchone()
            return dict(row) if row else None

    async def get_thread(self, thread_id: str, owner_id: str) -> dict[str, Any] | None:
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM threads WHERE thread_id = %s AND owner_id = %s",
                    (thread_id, owner_id),
                )
            ).fetchone()
            return dict(row) if row else None

    async def update_thread(
        self, thread_id: str, owner_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        sets = []
        vals = []
        for k, v in kwargs.items():
            if v is not None:
                if k == "metadata":
                    sets.append(f"{k} = %s")
                    vals.append(json.dumps(v))
                else:
                    sets.append(f"{k} = %s")
                    vals.append(v)
        if not sets:
            return await self.get_thread(thread_id, owner_id)
        sets.append("updated_at = %s")
        vals.append(_now())
        vals.append(thread_id)
        vals.append(owner_id)
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    f"UPDATE threads SET {', '.join(sets)} "
                    "WHERE thread_id = %s AND owner_id = %s RETURNING *",
                    vals,
                )
            ).fetchone()
            return dict(row) if row else None

    async def delete_thread(self, thread_id: str, owner_id: str) -> bool:
        async with self._conn() as conn:
            cursor = await conn.execute(
                "DELETE FROM threads WHERE thread_id = %s AND owner_id = %s",
                (thread_id, owner_id),
            )
            return cursor.rowcount > 0

    async def search_threads(
        self,
        *,
        owner_id: str,
        metadata: dict | None = None,
        status: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["owner_id = %s"]
        vals: list[Any] = [owner_id]
        if status:
            where.append("status = %s")
            vals.append(status)
        if metadata:
            where.append("metadata @> %s")
            vals.append(json.dumps(metadata))
        clause = " AND ".join(where) if where else "TRUE"
        vals.extend([limit, offset])
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT * FROM threads WHERE {clause} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                    vals,
                )
            ).fetchall()
            return [dict(r) for r in rows]

    async def set_thread_status(
        self, thread_id: str, status: str, owner_id: str
    ) -> None:
        async with self._conn() as conn:
            await conn.execute(
                """UPDATE threads SET status = %s, updated_at = %s
                WHERE thread_id = %s AND owner_id = %s""",
                (status, _now(), thread_id, owner_id),
            )

    # ---- Runs ----

    async def create_run(
        self,
        *,
        thread_id: str,
        owner_id: str,
        assistant_id: str | None = None,
        input: dict | None = None,
        command: dict | None = None,
        config: dict | None = None,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
        status: str = "pending",
    ) -> dict[str, Any] | None:
        run_id = _uuid()
        now = _now()
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    """INSERT INTO runs
                    (run_id, thread_id, assistant_id, status, input, command, config, metadata, kwargs, multitask_strategy, created_at, updated_at)
                    SELECT %s, thread_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    FROM threads WHERE thread_id = %s AND owner_id = %s
                    RETURNING *""",
                    (
                        run_id,
                        assistant_id,
                        status,
                        json.dumps(input) if input else None,
                        json.dumps(command) if command else None,
                        json.dumps(config or {}),
                        json.dumps(metadata or {}),
                        json.dumps(kwargs or {}),
                        multitask_strategy,
                        now,
                        now,
                        thread_id,
                        owner_id,
                    ),
                )
            ).fetchone()
            return dict(row) if row else None

    async def get_run(
        self, thread_id: str, run_id: str, owner_id: str
    ) -> dict[str, Any] | None:
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    """SELECT r.* FROM runs r
                    JOIN threads t ON t.thread_id = r.thread_id
                    WHERE r.run_id = %s AND r.thread_id = %s AND t.owner_id = %s""",
                    (run_id, thread_id, owner_id),
                )
            ).fetchone()
            return dict(row) if row else None

    async def update_run_status(self, run_id: str, status: str, owner_id: str) -> None:
        async with self._conn() as conn:
            await conn.execute(
                """UPDATE runs AS r SET status = %s, updated_at = %s
                FROM threads AS t WHERE r.run_id = %s
                AND t.thread_id = r.thread_id AND t.owner_id = %s""",
                (status, _now(), run_id, owner_id),
            )

    async def list_runs(
        self,
        thread_id: str,
        *,
        owner_id: str,
        limit: int = 10,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["r.thread_id = %s", "t.owner_id = %s"]
        vals: list[Any] = [thread_id, owner_id]
        if status:
            where.append("r.status = %s")
            vals.append(status)
        clause = " AND ".join(where)
        vals.extend([limit, offset])
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT r.* FROM runs r JOIN threads t ON t.thread_id = r.thread_id "
                    f"WHERE {clause} ORDER BY r.created_at DESC LIMIT %s OFFSET %s",
                    vals,
                )
            ).fetchall()
            return [dict(r) for r in rows]

    async def delete_run(self, thread_id: str, run_id: str, owner_id: str) -> bool:
        async with self._conn() as conn:
            cursor = await conn.execute(
                """DELETE FROM runs r USING threads t
                WHERE r.run_id = %s AND r.thread_id = %s
                AND t.thread_id = r.thread_id AND t.owner_id = %s""",
                (run_id, thread_id, owner_id),
            )
            return cursor.rowcount > 0

    async def get_active_run_for_thread(
        self, thread_id: str, owner_id: str
    ) -> dict[str, Any] | None:
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    """SELECT r.* FROM runs r
                    JOIN threads t ON t.thread_id = r.thread_id
                    WHERE r.thread_id = %s AND t.owner_id = %s
                    AND r.status IN ('pending', 'running')
                    ORDER BY r.created_at DESC LIMIT 1""",
                    (thread_id, owner_id),
                )
            ).fetchone()
            return dict(row) if row else None

    # ---- Store ----

    async def store_put(
        self,
        namespace: list[str],
        key: str,
        value: dict[str, Any],
        *,
        owner_id: str,
    ) -> None:
        ns = _ns_to_str(_scope_namespace(owner_id, namespace))
        now = _now()
        async with self._conn() as conn:
            await conn.execute(
                """INSERT INTO store_items (namespace, key, value, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (namespace, key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at""",
                (ns, key, json.dumps(value), now, now),
            )

    async def store_get(
        self, namespace: list[str], key: str, *, owner_id: str
    ) -> dict[str, Any] | None:
        ns = _ns_to_str(_scope_namespace(owner_id, namespace))
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM store_items WHERE namespace = %s AND key = %s",
                    (ns, key),
                )
            ).fetchone()
            if not row:
                return None
            r = dict(row)
            r["namespace"] = _unscope_namespace(owner_id, _str_to_ns(r["namespace"]))
            return r

    async def store_delete(
        self, namespace: list[str], key: str, *, owner_id: str
    ) -> bool:
        ns = _ns_to_str(_scope_namespace(owner_id, namespace))
        async with self._conn() as conn:
            cursor = await conn.execute(
                "DELETE FROM store_items WHERE namespace = %s AND key = %s",
                (ns, key),
            )
            return cursor.rowcount > 0

    async def store_search(
        self,
        namespace_prefix: list[str],
        *,
        owner_id: str,
        filter: dict | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        prefix = _ns_to_str(_scope_namespace(owner_id, namespace_prefix))
        where = ["(namespace = %s OR namespace LIKE %s)"]
        vals: list[Any] = [prefix, f"{prefix}.%"]
        if filter:
            where.append("value @> %s")
            vals.append(json.dumps(filter))
        clause = " AND ".join(where)
        vals.extend([limit, offset])
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT * FROM store_items WHERE {clause} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                    vals,
                )
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["namespace"] = _unscope_namespace(
                    owner_id, _str_to_ns(d["namespace"])
                )
                result.append(d)
            return result

    async def store_list_namespaces(
        self,
        *,
        owner_id: str,
        prefix: list[str] | None = None,
        suffix: list[str] | None = None,
        max_depth: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[list[str]]:
        user_prefix = _ns_to_str(_user_namespace(owner_id))
        where = ["(namespace = %s OR namespace LIKE %s)"]
        vals: list[Any] = [user_prefix, f"{user_prefix}.%"]
        if prefix:
            p = _ns_to_str(_scope_namespace(owner_id, prefix))
            where.append("(namespace = %s OR namespace LIKE %s)")
            vals.extend([p, f"{p}.%"])
        if suffix:
            s = _ns_to_str(suffix)
            where.append("namespace LIKE %s")
            vals.append(f"%.{s}")
        clause = " AND ".join(where)
        vals.extend([limit, offset])
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT DISTINCT namespace FROM store_items WHERE {clause} ORDER BY namespace LIMIT %s OFFSET %s",
                    vals,
                )
            ).fetchall()
            namespaces = [
                _unscope_namespace(owner_id, _str_to_ns(r["namespace"])) for r in rows
            ]
            if max_depth is not None:
                seen: set[tuple[str, ...]] = set()
                filtered = []
                for ns in namespaces:
                    truncated = tuple(ns[:max_depth])
                    if truncated not in seen:
                        seen.add(truncated)
                        filtered.append(list(truncated))
                namespaces = filtered
            return namespaces

    # ---- Crons ----

    async def create_cron(
        self,
        *,
        owner_id: str,
        schedule: str,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        input: dict | None = None,
        config: dict | None = None,
        metadata: dict | None = None,
        enabled: bool = True,
        timezone: str | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        cron_id = _uuid()
        now = _now()
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    """INSERT INTO crons
                    (cron_id, owner_id, assistant_id, thread_id, schedule, timezone, end_time, input, config, metadata, enabled, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *""",
                    (
                        cron_id,
                        owner_id,
                        assistant_id,
                        thread_id,
                        schedule,
                        timezone,
                        end_time,
                        json.dumps(input) if input else None,
                        json.dumps(config or {}),
                        json.dumps(metadata or {}),
                        enabled,
                        now,
                        now,
                    ),
                )
            ).fetchone()
            return dict(row)

    async def get_cron(self, cron_id: str, owner_id: str) -> dict[str, Any] | None:
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM crons WHERE cron_id = %s AND owner_id = %s",
                    (cron_id, owner_id),
                )
            ).fetchone()
            return dict(row) if row else None

    async def update_cron(
        self, cron_id: str, owner_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        sets = []
        vals = []
        for k, v in kwargs.items():
            if v is not None:
                if k in ("config", "metadata", "input"):
                    sets.append(f"{k} = %s")
                    vals.append(json.dumps(v))
                else:
                    sets.append(f"{k} = %s")
                    vals.append(v)
        if not sets:
            return await self.get_cron(cron_id, owner_id)
        sets.append("updated_at = %s")
        vals.append(_now())
        vals.append(cron_id)
        vals.append(owner_id)
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    f"UPDATE crons SET {', '.join(sets)} "
                    "WHERE cron_id = %s AND owner_id = %s RETURNING *",
                    vals,
                )
            ).fetchone()
            return dict(row) if row else None

    async def delete_cron(self, cron_id: str, owner_id: str) -> bool:
        async with self._conn() as conn:
            cursor = await conn.execute(
                "DELETE FROM crons WHERE cron_id = %s AND owner_id = %s",
                (cron_id, owner_id),
            )
            return cursor.rowcount > 0

    async def search_crons(
        self,
        *,
        owner_id: str,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        enabled: bool | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["owner_id = %s"]
        vals: list[Any] = [owner_id]
        if assistant_id:
            where.append("assistant_id = %s")
            vals.append(assistant_id)
        if thread_id:
            where.append("thread_id = %s")
            vals.append(thread_id)
        if enabled is not None:
            where.append("enabled = %s")
            vals.append(enabled)
        clause = " AND ".join(where) if where else "TRUE"
        vals.extend([limit, offset])
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT * FROM crons WHERE {clause} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    vals,
                )
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- Models ----

    async def list_models(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        where = "enabled = TRUE" if enabled_only else "TRUE"
        async with self._conn() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT * FROM models WHERE {where} ORDER BY provider, display_name",
                )
            ).fetchall()
            return [dict(r) for r in rows]

    async def get_model(self, model_id: str) -> dict[str, Any] | None:
        async with self._conn() as conn:
            row = await (
                await conn.execute("SELECT * FROM models WHERE id = %s", (model_id,))
            ).fetchone()
            return dict(row) if row else None

    async def create_model(
        self,
        *,
        provider: str,
        model_id: str,
        display_name: str,
        is_default: bool = False,
        enabled: bool = True,
    ) -> dict[str, Any]:
        now = _now()
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    """INSERT INTO models (provider, model_id, display_name, is_default, enabled, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *""",
                    (provider, model_id, display_name, is_default, enabled, now, now),
                )
            ).fetchone()
            return dict(row)

    async def update_model(self, id: str, **kwargs: Any) -> dict[str, Any] | None:
        sets = []
        vals = []
        for k, v in kwargs.items():
            if v is not None:
                sets.append(f"{k} = %s")
                vals.append(v)
        if not sets:
            return await self.get_model(id)
        sets.append("updated_at = %s")
        vals.append(_now())
        vals.append(id)
        async with self._conn() as conn:
            row = await (
                await conn.execute(
                    f"UPDATE models SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    vals,
                )
            ).fetchone()
            return dict(row) if row else None

    async def delete_model(self, id: str) -> None:
        async with self._conn() as conn:
            await conn.execute("DELETE FROM models WHERE id = %s", (id,))
