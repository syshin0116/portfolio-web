"""Opt-in black-box persistence checks against an actual PostgreSQL server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import runpy
import socket
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
import uvicorn
from aegra_api.core import orm as aegra_orm
from aegra_api.core.database import db_manager
from aegra_api.models.auth import User
from aegra_api.services.event_streaming.session import ThreadEventSession
from aegra_api.services.langgraph_service import (
    LangGraphService,
    create_run_config,
    get_langgraph_service,
)
from aegra_api.settings import settings
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.auth import (
    AGENT_AUTH_SECRET,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
)
from agent.migrate import migrate_database

POSTGRES_URL = os.environ.get("AEGRA_POSTGRES_TEST_URL")
FIXTURE_GRAPH = Path(__file__).resolve().parents[1] / "fixtures" / "aegra_graph.py"

if os.environ.get("CI", "").lower() == "true" and not POSTGRES_URL:
    raise RuntimeError(
        "CI requires AEGRA_POSTGRES_TEST_URL; PostgreSQL integration may not skip"
    )

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="AEGRA_POSTGRES_TEST_URL is required for PostgreSQL integration",
)


def _service(
    base_graph,
    *,
    graph_id: str = "fixture",
    export_name: str = "graph",
) -> LangGraphService:
    service = LangGraphService()
    service._graph_registry = {
        graph_id: {
            "file_path": str(FIXTURE_GRAPH),
            "export_name": export_name,
        }
    }
    service._base_graph_cache[graph_id] = base_graph
    return service


def _authorization(subject: str) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": subject,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + 900,
        },
        AGENT_AUTH_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def _database_tables(url: str) -> tuple[set[str], list[str]]:
    async with (
        await psycopg.AsyncConnection.connect(url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        tables = {row[0] for row in await cursor.fetchall()}
        await cursor.execute("SELECT version_num FROM alembic_version")
        versions = [row[0] for row in await cursor.fetchall()]
    return tables, versions


async def _next_sse_envelope(
    lines,
    *,
    observed: list[dict[str, Any]],
    method: str,
    lifecycle_event: str | None = None,
) -> dict[str, Any]:
    async with asyncio.timeout(15):
        while True:
            line = await anext(lines)
            if not line.startswith("data:"):
                continue
            envelope = json.loads(line.removeprefix("data:").lstrip())
            observed.append(envelope)
            if envelope["method"] != method:
                continue
            if lifecycle_event is None:
                return envelope
            params = envelope.get("params", {})
            if (
                params.get("namespace") == []
                and params.get("data", {}).get("event") == lifecycle_event
            ):
                return envelope


async def test_native_v2_http_interrupt_resume_persists_checkpoint(
    monkeypatch,
):
    """Exercise the complete APv2 transport through Aegra's native executor."""
    assert POSTGRES_URL is not None
    from aegra_api.main import app as aegra_app

    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    previous_startup_migrations = settings.app.RUN_MIGRATIONS_ON_STARTUP
    previous_cron_enabled = settings.cron.CRON_ENABLED

    service = get_langgraph_service()
    previous_service_state = (
        service.config_path,
        service.config,
        dict(service._graph_registry),
        dict(service._base_graph_cache),
        dict(service._graph_factories),
    )
    unique = uuid4().hex
    thread_id = f"postgres-http-{unique}"
    stream_sessions: list[ThreadEventSession] = []

    def load_fixture_registry() -> None:
        service._graph_registry = {
            "fixture": {
                "file_path": str(FIXTURE_GRAPH),
                "export_name": "graph",
            }
        }

    original_session_init = ThreadEventSession.__init__

    def capture_stream_session(
        instance: ThreadEventSession,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        original_session_init(instance, *args, **kwargs)
        stream_sessions.append(instance)

    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url
    settings.app.RUN_MIGRATIONS_ON_STARTUP = False
    settings.cron.CRON_ENABLED = False
    service._graph_registry = {}
    service._base_graph_cache = {}
    service._graph_factories = {}
    monkeypatch.setattr(service, "_load_graph_registry", load_fixture_registry)
    monkeypatch.setattr(ThreadEventSession, "__init__", capture_stream_session)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(128)
    host, port = server_socket.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(aegra_app, lifespan="on", log_level="warning")
    )
    server_task = None

    try:
        await migrate_database()
        server_task = asyncio.create_task(server.serve(sockets=[server_socket]))
        for _ in range(500):
            if server.started:
                break
            if server_task.done():
                await server_task
            await asyncio.sleep(0.01)
        assert server.started

        observed: list[dict[str, Any]] = []
        base_url = f"http://{host}:{port}"
        headers = _authorization("http-owner")
        async with (
            httpx.AsyncClient(base_url=base_url, timeout=20) as command_client,
            httpx.AsyncClient(base_url=base_url, timeout=None) as stream_client,
            stream_client.stream(
                "POST",
                f"/threads/{thread_id}/stream/events",
                headers=headers,
                json={
                    "channels": [
                        "values",
                        "updates",
                        "messages",
                        "tools",
                        "lifecycle",
                        "input",
                    ]
                },
            ) as stream_response,
        ):
            assert stream_response.status_code == 200
            assert stream_response.headers["content-type"].startswith(
                "text/event-stream"
            )
            assert len(stream_sessions) == 1
            lines = stream_response.aiter_lines()

            start_response = await command_client.post(
                f"/threads/{thread_id}/commands",
                headers=headers,
                json={
                    "id": 1,
                    "method": "run.start",
                    "params": {
                        "assistant_id": "fixture",
                        "input": {
                            "messages": [
                                {
                                    "type": "human",
                                    "content": "HTTP persistence proof",
                                }
                            ]
                        },
                    },
                },
            )
            assert start_response.status_code == 200
            start_envelope = start_response.json()
            assert start_envelope["type"] == "success"
            assert start_envelope["id"] == 1
            first_run_id = start_envelope["result"]["run_id"]

            interrupt_envelope = await _next_sse_envelope(
                lines,
                observed=observed,
                method="input.requested",
            )
            interrupt = interrupt_envelope["params"]["data"]
            assert interrupt["value"] == {
                "kind": "fixture-approval",
                "question": "Continue the deterministic Aegra fixture?",
            }

            resume_response = await command_client.post(
                f"/threads/{thread_id}/commands",
                headers=headers,
                json={
                    "id": 2,
                    "method": "input.respond",
                    "params": {
                        "interrupt_id": interrupt["interrupt_id"],
                        "response": "approved-over-http",
                    },
                },
            )
            assert resume_response.status_code == 200
            resume_envelope = resume_response.json()
            assert resume_envelope["type"] == "success"
            assert resume_envelope["id"] == 2
            second_run_id = resume_envelope["result"]["run_id"]
            assert second_run_id != first_run_id

            # Preserve Aegra's normal 30-second gap while the interrupt is
            # pending, then shorten only the post-completion idle grace so the
            # SSE response can close naturally inside a fast integration test.
            stream_sessions[0]._idle_grace = 0.1
            terminal = await _next_sse_envelope(
                lines,
                observed=observed,
                method="lifecycle",
                lifecycle_event="completed",
            )
            assert terminal["params"]["data"]["graph_name"] == "fixture"
            async with asyncio.timeout(2):
                async for line in lines:
                    if line.startswith("data:"):
                        observed.append(json.loads(line.removeprefix("data:").lstrip()))

        # Natural stream exhaustion must return every short-lived DB session.
        await asyncio.sleep(0)
        assert db_manager.get_engine().sync_engine.pool.checkedout() == 0

        assert any(
            envelope["method"] == "messages"
            and envelope["params"]["data"].get("event") == "message-finish"
            for envelope in observed
        )
        assert any(
            envelope["method"] == "lifecycle"
            and envelope["params"]["namespace"] == []
            and envelope["params"]["data"]["event"] == "interrupted"
            for envelope in observed
        )
        assert [envelope["seq"] for envelope in observed] == sorted(
            {envelope["seq"] for envelope in observed}
        )

        checkpoint = await db_manager.get_checkpointer().aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        assert checkpoint is not None
        values = checkpoint.checkpoint["channel_values"]
        assert values["approval"] == "approved-over-http"
        assert values["nested_result"] == "nested-ok"
        assert values["messages"][-1].text == "fixture-complete"

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT status FROM runs WHERE thread_id = %s ORDER BY created_at ASC",
                (thread_id,),
            )
            assert [row[0] for row in await cursor.fetchall()] == [
                "interrupted",
                "success",
            ]
            await cursor.execute(
                "SELECT status FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
            assert (await cursor.fetchone())[0] == "idle"
    finally:
        if server_task is not None:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
        server_socket.close()

        if db_manager.engine is None:
            await db_manager.initialize()
        await db_manager.get_checkpointer().adelete_thread(thread_id)
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None

        service.invalidate_cache("fixture")
        (
            service.config_path,
            service.config,
            service._graph_registry,
            service._base_graph_cache,
            service._graph_factories,
        ) = previous_service_state
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url
        settings.app.RUN_MIGRATIONS_ON_STARTUP = previous_startup_migrations
        settings.cron.CRON_ENABLED = previous_cron_enabled


async def test_postgres_migration_static_injection_and_pool_restart_persistence():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    alice_thread = f"postgres-alice-{unique}"
    bob_thread = f"postgres-bob-{unique}"
    alice_memory_thread = f"postgres-memory-alice-{unique}"
    bob_memory_thread = f"postgres-memory-bob-{unique}"
    alice_namespace = (
        "users",
        hashlib.sha256(b"alice").hexdigest(),
        "filesystem",
    )
    bob_namespace = (
        "users",
        hashlib.sha256(b"bob").hexdigest(),
        "filesystem",
    )
    alice = User(identity="alice")
    bob = User(identity="bob")
    alice_config = create_run_config(
        f"run-alice-{unique}",
        alice_thread,
        alice,
    )
    bob_config = create_run_config(
        f"run-bob-{unique}",
        bob_thread,
        bob,
    )
    alice_memory_config = create_run_config(
        f"memory-alice-{unique}",
        alice_memory_thread,
        alice,
        additional_config={"configurable": {"user_id": "bob"}},
    )
    bob_memory_config = create_run_config(
        f"memory-bob-{unique}",
        bob_memory_thread,
        bob,
    )
    alice_memory_read_config = create_run_config(
        f"memory-alice-read-{unique}",
        alice_memory_thread,
        alice,
        additional_config={"configurable": {"user_id": "bob"}},
    )
    bob_memory_read_config = create_run_config(
        f"memory-bob-read-{unique}",
        bob_memory_thread,
        bob,
    )

    try:
        # The same-image entrypoint must be safe to retry.
        await migrate_database()
        await migrate_database()
        tables, versions = await _database_tables(settings.db.database_url_sync)
        assert {
            "alembic_version",
            "assistant",
            "thread",
            "runs",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
            "store",
            "store_migrations",
        } <= tables
        assert len(versions) == 1

        await db_manager.initialize()
        fixture_module = runpy.run_path(FIXTURE_GRAPH)
        base_graph = fixture_module["graph"]
        memory_base_graph = fixture_module["memory_graph"]
        service = _service(base_graph)

        async with service.get_graph(
            "fixture",
            config=alice_config,
            user=alice,
        ) as alice_graph:
            assert alice_graph.checkpointer is db_manager.get_checkpointer()
            assert alice_graph.store is db_manager.get_store()
            alice_first = await alice_graph.ainvoke(
                {"messages": [HumanMessage(content="alice request")]},
                alice_config,
            )

        async with service.get_graph(
            "fixture",
            config=bob_config,
            user=bob,
        ) as bob_graph:
            bob_first = await bob_graph.ainvoke(
                {"messages": [HumanMessage(content="bob request")]},
                bob_config,
            )

        assert alice_first["__interrupt__"][0].value["kind"] == "fixture-approval"
        assert bob_first["__interrupt__"][0].value["kind"] == "fixture-approval"
        assert alice_config["configurable"]["langgraph_auth_user"].identity == "alice"
        assert bob_config["configurable"]["langgraph_auth_user"].identity == "bob"
        assert alice_memory_config["configurable"]["user_id"] == "bob"
        assert (
            alice_memory_config["configurable"]["langgraph_auth_user"].identity
            == "alice"
        )

        memory_service = _service(
            memory_base_graph,
            graph_id="memory_fixture",
            export_name="memory_graph",
        )
        async with memory_service.get_graph(
            "memory_fixture",
            config=alice_memory_config,
            user=alice,
        ) as alice_memory_graph:
            alice_memory_write = await alice_memory_graph.ainvoke(
                {"operation": "write", "content": "alice-only"},
                alice_memory_config,
            )
        async with memory_service.get_graph(
            "memory_fixture",
            config=bob_memory_config,
            user=bob,
        ) as bob_memory_graph:
            bob_memory_write = await bob_memory_graph.ainvoke(
                {"operation": "write", "content": "bob-only"},
                bob_memory_config,
            )

        assert alice_memory_write["result"] == "/memories/preference.txt"
        assert bob_memory_write["result"] == "/memories/preference.txt"
        first_checkpointer = db_manager.get_checkpointer()
        first_store = db_manager.get_store()

        # Recreate every pool and Aegra service object in the same process.
        await db_manager.close()
        await db_manager.initialize()
        assert db_manager.get_checkpointer() is not first_checkpointer
        assert db_manager.get_store() is not first_store

        restarted_service = _service(base_graph)
        async with restarted_service.get_graph(
            "fixture",
            config=alice_config,
            user=alice,
        ) as restarted_alice_graph:
            alice_resumed = await restarted_alice_graph.ainvoke(
                Command(resume="approved-after-restart"),
                alice_config,
            )

        async with restarted_service.get_graph(
            "fixture",
            config=bob_config,
            user=bob,
        ) as restarted_bob_graph:
            bob_state = await restarted_bob_graph.aget_state(bob_config)

        assert alice_resumed["approval"] == "approved-after-restart"
        assert "approval" not in bob_state.values
        assert bob_state.next == ("request_approval",)

        restarted_memory_service = _service(
            memory_base_graph,
            graph_id="memory_fixture",
            export_name="memory_graph",
        )
        async with restarted_memory_service.get_graph(
            "memory_fixture",
            config=alice_memory_read_config,
            user=alice,
        ) as restarted_alice_memory_graph:
            alice_memory = await restarted_alice_memory_graph.ainvoke(
                {"operation": "read"},
                alice_memory_read_config,
            )
        async with restarted_memory_service.get_graph(
            "memory_fixture",
            config=bob_memory_read_config,
            user=bob,
        ) as restarted_bob_memory_graph:
            bob_memory = await restarted_bob_memory_graph.ainvoke(
                {"operation": "read"},
                bob_memory_read_config,
            )

        assert alice_memory["result"] == "alice-only"
        assert bob_memory["result"] == "bob-only"

        # The actual native route is disabled before it can strand the real
        # PostgreSQL checkpoint.
        from aegra_api.main import app as aegra_app

        before_delete = await db_manager.get_checkpointer().aget_tuple(alice_config)
        assert before_delete is not None

        # The outer guard must not turn a foreign owner's busy thread into a
        # distinguishable 409. Aegra's native owned-or-new check remains the
        # response authority and returns its normal 404.
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (thread_id, status, user_id)
                VALUES (%s, 'busy', 'alice')
                """,
                (alice_thread,),
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=aegra_app),
            base_url="http://test",
        ) as client:
            foreign_command = await client.post(
                f"/threads/{alice_thread}/commands",
                headers=_authorization("bob"),
                json={
                    "id": 1,
                    "method": "run.start",
                    "params": {"assistant_id": "fixture"},
                },
            )
            delete_response = await client.delete(
                f"/threads/{alice_thread}",
                headers=_authorization("alice"),
            )
        after_delete = await db_manager.get_checkpointer().aget_tuple(alice_config)
        assert foreign_command.status_code == 404
        assert delete_response.status_code == 403
        assert after_delete == before_delete

        await db_manager.get_checkpointer().adelete_thread(alice_thread)
        await db_manager.get_checkpointer().adelete_thread(bob_thread)
        await db_manager.get_checkpointer().adelete_thread(alice_memory_thread)
        await db_manager.get_checkpointer().adelete_thread(bob_memory_thread)
        await db_manager.get_store().adelete(alice_namespace, "/preference.txt")
        await db_manager.get_store().adelete(bob_namespace, "/preference.txt")
    finally:
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url
