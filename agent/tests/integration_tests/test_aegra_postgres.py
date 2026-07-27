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
from aegra_api.services import graph_factory
from aegra_api.services.event_streaming.session import ThreadEventSession
from aegra_api.services.langgraph_service import (
    LangGraphService,
    create_run_config,
    get_langgraph_service,
)
from aegra_api.settings import settings
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import Field

from agent.auth import (
    AGENT_AUTH_SECRET,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
)
from agent.graph import graph as production_graph
from agent.inspection import INSPECTION_EVENT_NAME
from agent.migrate import migrate_database

POSTGRES_URL = os.environ.get("AEGRA_POSTGRES_TEST_URL")
RUN_JS_SDK_E2E = os.environ.get("AEGRA_JS_SDK_E2E") == "1"
FIXTURE_GRAPH = Path(__file__).resolve().parents[1] / "fixtures" / "aegra_graph.py"
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
INSPECTION_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "protocol"
    / "fixtures"
    / "inspection-events-v1.json"
)


def _canonical_inspection_payload() -> dict[str, object]:
    fixture = json.loads(INSPECTION_FIXTURE.read_text(encoding="utf-8"))
    return fixture["records"][0]["payload"]["params"]["data"]["payload"]


if os.environ.get("CI", "").lower() == "true" and not POSTGRES_URL:
    raise RuntimeError(
        "CI requires AEGRA_POSTGRES_TEST_URL; PostgreSQL integration may not skip"
    )

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="AEGRA_POSTGRES_TEST_URL is required for PostgreSQL integration",
)


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """Provider-free model for the production graph-factory persistence proof."""

    bound_tool_names: list[frozenset[str]] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        self.bound_tool_names.append(
            frozenset(
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in tools
            )
        )
        return self


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


def _factory_service(factory, *, graph_id: str) -> LangGraphService:
    service = LangGraphService()
    service._graph_registry = {
        graph_id: {
            "file_path": "./agent/src/agent/graph.py",
            "export_name": "graph",
        }
    }
    service._graph_factories[graph_id] = factory
    graph_factory.clear_factory_registry(graph_id)
    graph_factory.classify_factory(factory, graph_id)
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


async def _run_official_js_sdk_e2e(
    *,
    base_url: str,
    headers: dict[str, str],
    thread_id: str,
) -> dict[str, object]:
    authorization = headers["Authorization"]
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise AssertionError("test authorization must use Bearer")
    process = await asyncio.create_subprocess_exec(
        "bun",
        "run",
        "test:aegra-sdk",
        cwd=WEB_ROOT,
        env={
            **os.environ,
            "AEGRA_JS_E2E_BASE_URL": base_url,
            "AEGRA_JS_E2E_THREAD_ID": thread_id,
            "AEGRA_JS_E2E_TOKEN": authorization.removeprefix(prefix),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        raise AssertionError(
            "official JavaScript SDK APv2 integration timed out\n"
            f"stdout:\n{stdout.decode('utf-8')}\n"
            f"stderr:\n{stderr.decode('utf-8')}"
        ) from None
    output = stdout.decode("utf-8")
    error_output = stderr.decode("utf-8")
    assert process.returncode == 0, (
        "official JavaScript SDK APv2 integration failed\n"
        f"stdout:\n{output}\nstderr:\n{error_output}"
    )
    lines = [line for line in output.splitlines() if line.startswith("{")]
    assert lines, f"JavaScript SDK integration returned no summary: {output}"
    summary = json.loads(lines[-1])
    assert isinstance(summary, dict)
    return summary


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
    js_sdk_thread_id = f"postgres-js-sdk-{unique}"
    stream_sessions: list[ThreadEventSession] = []
    use_short_js_stream_grace = False

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
        if use_short_js_stream_grace:
            instance._idle_grace = 0.05
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
                        f"custom:{INSPECTION_EVENT_NAME}",
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
                "schema": "syshin.rag.interrupt.v1",
                "kind": "approval",
                "title": "Deterministic fixture approval",
                "prompt": "Continue the deterministic Aegra fixture?",
            }
            interrupt_namespace = interrupt_envelope["params"]["namespace"]
            assert interrupt_namespace
            assert interrupt_namespace[0].startswith("nested_subgraph:")

            resume_response = await command_client.post(
                f"/threads/{thread_id}/commands",
                headers=headers,
                json={
                    "id": 2,
                    "method": "input.respond",
                    "params": {
                        "namespace": interrupt_namespace,
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
        inspection = [
            envelope
            for envelope in observed
            if envelope["method"] == "custom"
            and envelope["params"]["data"].get("name") == INSPECTION_EVENT_NAME
        ]
        assert len(inspection) == 1
        assert inspection[0]["params"]["namespace"] == []
        assert (
            inspection[0]["params"]["data"]["payload"]
            == _canonical_inspection_payload()
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
        assert values["private_state"] == {
            "todos": [{"content": "PRIVATE_DEEP_AGENT_STATE_MUST_NOT_REACH_UI"}],
            "files": {
                "/memories/private.txt": "PRIVATE_DEEP_AGENT_STATE_MUST_NOT_REACH_UI"
            },
            "scratch": {
                "chain_of_thought": "PRIVATE_DEEP_AGENT_STATE_MUST_NOT_REACH_UI"
            },
        }
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

        if RUN_JS_SDK_E2E:
            use_short_js_stream_grace = True
            summary = await _run_official_js_sdk_e2e(
                base_url=base_url,
                headers=headers,
                thread_id=js_sdk_thread_id,
            )
            assert summary == {
                "aegraAppliedThroughSeq": 0,
                "assistantText": "fixture-complete",
                "inspectionEvents": 1,
                "interruptProjectionRecognized": True,
                "nestedInputOnContent": False,
                "nestedInterruptNamespace": True,
                "protocol": "v2",
                "rawPrivateStateObserved": False,
                "replayDroppedByRunIdentity": True,
                "runCorrelationUsesEventIdentity": True,
                "runCorrelationPersisted": True,
                "runtimeBoundarySafe": True,
                "sawNestedLifecycle": True,
                "sawToolFinish": True,
                "sawToolStart": True,
                "streamConnections": 4,
                "threadId": js_sdk_thread_id,
            }
            js_checkpoint = await db_manager.get_checkpointer().aget_tuple(
                {"configurable": {"thread_id": js_sdk_thread_id}}
            )
            assert js_checkpoint is not None
            js_values = js_checkpoint.checkpoint["channel_values"]
            assert js_values["approval"] == "approved-via-js-sdk"
            assert js_values["nested_result"] == "nested-ok"
            assert (
                js_values["private_state"]["scratch"]["chain_of_thought"]
                == "PRIVATE_DEEP_AGENT_STATE_MUST_NOT_REACH_UI"
            )
            assert js_values["messages"][-1].text == "fixture-complete"
            async with (
                await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute(
                    "SELECT status FROM runs WHERE thread_id = %s "
                    "ORDER BY created_at ASC",
                    (js_sdk_thread_id,),
                )
                assert [row[0] for row in await cursor.fetchall()] == [
                    "interrupted",
                    "success",
                ]
                await cursor.execute(
                    "SELECT status FROM thread WHERE thread_id = %s",
                    (js_sdk_thread_id,),
                )
                assert (await cursor.fetchone())[0] == "idle"
            await asyncio.sleep(0)
            assert db_manager.get_engine().sync_engine.pool.checkedout() == 0
    finally:
        if server_task is not None:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
        server_socket.close()

        if db_manager.engine is None:
            await db_manager.initialize()
        await db_manager.get_checkpointer().adelete_thread(thread_id)
        if RUN_JS_SDK_E2E:
            await db_manager.get_checkpointer().adelete_thread(js_sdk_thread_id)
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = ANY(%s)",
                (
                    [
                        thread_id,
                        *([js_sdk_thread_id] if RUN_JS_SDK_E2E else []),
                    ],
                ),
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


async def test_postgres_migration_factory_static_and_pool_restart_persistence(
    monkeypatch,
):
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
    budget_thread = f"postgres-budget-{unique}"
    isolation_thread = f"postgres-isolation-{unique}"
    isolation_memory_thread = f"postgres-isolation-memory-{unique}"
    budget_graph_id = f"budget_factory_{unique}"
    isolation_graph_id = f"isolation_factory_{unique}"
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
    isolation_namespace = (
        "users",
        hashlib.sha256(b"isolation-owner").hexdigest(),
        "filesystem",
    )
    alice = User(identity="alice")
    bob = User(identity="bob")
    isolation_owner = User(
        identity="isolation-owner",
        permissions=["admin"],
    )
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
    isolation_memory_config = create_run_config(
        f"memory-isolation-{unique}",
        isolation_memory_thread,
        isolation_owner,
    )
    isolation_memory_read_config = create_run_config(
        f"memory-isolation-read-{unique}",
        isolation_memory_thread,
        isolation_owner,
    )
    isolation_config = create_run_config(
        f"isolation-run-{unique}",
        isolation_thread,
        isolation_owner,
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

        budget_model = ToolCapableFakeModel(
            responses=[
                AIMessage(
                    content="budget checkpoint persisted",
                    usage_metadata={
                        "input_tokens": 9,
                        "output_tokens": 1,
                        "total_tokens": 10,
                    },
                )
            ]
        )
        monkeypatch.setattr(
            "agent.graph._bounded_model",
            lambda _spec: budget_model,
        )

        async def fixed_input_count(_request):
            return 1

        monkeypatch.setattr(
            "agent.graph.count_anthropic_input_tokens",
            fixed_input_count,
        )
        budget_owner = User(identity="budget-owner", permissions=[])
        budget_config = create_run_config(
            f"budget-run-{unique}",
            budget_thread,
            budget_owner,
        )
        budget_service = _factory_service(
            production_graph,
            graph_id=budget_graph_id,
        )
        async with budget_service.get_graph(
            budget_graph_id,
            config=budget_config,
            user=budget_owner,
        ) as budget_graph:
            budget_result = await budget_graph.ainvoke(
                {"messages": [HumanMessage(content="persist without budget state")]},
                budget_config,
            )

        budget_checkpoint = await db_manager.get_checkpointer().aget_tuple(
            budget_config
        )
        assert budget_checkpoint is not None
        encoding, payload = db_manager.get_checkpointer().serde.dumps_typed(
            budget_checkpoint.checkpoint
        )
        assert (
            db_manager.get_checkpointer().serde.loads_typed((encoding, payload))
            == budget_checkpoint.checkpoint
        )
        assert b"RunBudget" not in payload
        assert b"owner-dynamic-subagents-v1" not in payload
        assert all("budget" not in key.casefold() for key in budget_result)
        assert len(budget_model.bound_tool_names) == 1
        assert "task" not in budget_model.bound_tool_names[0]

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

        assert alice_first["__interrupt__"][0].value["kind"] == "approval"
        assert bob_first["__interrupt__"][0].value["kind"] == "approval"
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

        async with memory_service.get_graph(
            "memory_fixture",
            config=isolation_memory_config,
            user=isolation_owner,
        ) as isolation_memory_graph:
            isolation_memory_write = await isolation_memory_graph.ainvoke(
                {"operation": "write", "content": "PERSISTENT_ONLY_SECRET"},
                isolation_memory_config,
            )
        assert isolation_memory_write["result"] == "/memories/preference.txt"

        descriptions = [
            """\
Question:
Check PostgreSQL sibling A.
Allowed corpus/method scope:
Published exact retrieval evidence only.
Expected output schema:
One bounded verdict.
Stopping condition:
Stop after one verdict.
""",
            """\
Question:
Check PostgreSQL sibling B.
Allowed corpus/method scope:
Published exact retrieval evidence only.
Expected output schema:
One bounded verdict.
Stopping condition:
Stop after one verdict.
""",
        ]
        isolation_model = ToolCapableFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {
                                "description": description,
                                "subagent_type": "evidence-checker",
                            },
                            "id": f"postgres-isolation-task-{index}",
                            "type": "tool_call",
                        }
                        for index, description in enumerate(descriptions)
                    ],
                    usage_metadata={
                        "input_tokens": 9,
                        "output_tokens": 1,
                        "total_tokens": 10,
                    },
                ),
                AIMessage(
                    content="isolated child result",
                    usage_metadata={
                        "input_tokens": 9,
                        "output_tokens": 1,
                        "total_tokens": 10,
                    },
                ),
                AIMessage(
                    content="isolated child result",
                    usage_metadata={
                        "input_tokens": 9,
                        "output_tokens": 1,
                        "total_tokens": 10,
                    },
                ),
                AIMessage(
                    content="isolated root result",
                    usage_metadata={
                        "input_tokens": 9,
                        "output_tokens": 1,
                        "total_tokens": 10,
                    },
                ),
            ]
        )
        observed_child_requests = []

        async def capture_isolation_count(request):
            tool_names = {
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in request.tools
            }
            if "task" not in tool_names:
                observed_child_requests.append(request)
            return 1

        monkeypatch.setattr(
            "agent.graph._bounded_model",
            lambda _spec: isolation_model,
        )
        monkeypatch.setattr(
            "agent.graph.count_anthropic_input_tokens",
            capture_isolation_count,
        )
        isolation_service = _factory_service(
            production_graph,
            graph_id=isolation_graph_id,
        )
        parent_files = {
            "/parent-secret.txt": {
                "content": "PARENT_ONLY_SECRET",
                "encoding": "utf-8",
            },
            "/sibling-a.txt": {
                "content": "SIBLING_A_SECRET",
                "encoding": "utf-8",
            },
            "/sibling-b.txt": {
                "content": "SIBLING_B_SECRET",
                "encoding": "utf-8",
            },
        }
        async with isolation_service.get_graph(
            isolation_graph_id,
            config=isolation_config,
            user=isolation_owner,
        ) as isolation_graph:
            isolation_result = await isolation_graph.ainvoke(
                {
                    "messages": [
                        HumanMessage(content="delegate isolated PostgreSQL tasks")
                    ],
                    "files": parent_files,
                },
                isolation_config,
            )

        assert len(observed_child_requests) == 2
        assert {
            request.messages[0].content for request in observed_child_requests
        } == set(descriptions)
        for request in observed_child_requests:
            assert "files" not in request.state
            assert "memory_contents" not in request.state
            tool_names = {
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in request.tools
            }
            assert "read_blog_retrieval_skill" in tool_names
            assert {
                "task",
                "ls",
                "read_file",
                "write_file",
                "edit_file",
                "glob",
                "grep",
                "execute",
            }.isdisjoint(tool_names)
        assert isolation_result["files"] == parent_files
        assert "skills_metadata" not in isolation_result
        async with isolation_service.get_graph(
            isolation_graph_id,
            config=isolation_config,
            user=isolation_owner,
        ) as persisted_isolation_graph:
            isolation_state = await persisted_isolation_graph.aget_state(
                isolation_config
            )
        assert isolation_state.values["files"] == parent_files
        async with memory_service.get_graph(
            "memory_fixture",
            config=isolation_memory_read_config,
            user=isolation_owner,
        ) as isolation_memory_graph:
            isolation_memory_read = await isolation_memory_graph.ainvoke(
                {"operation": "read"},
                isolation_memory_read_config,
            )
        assert isolation_memory_read["result"] == "PERSISTENT_ONLY_SECRET"

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
        await db_manager.get_checkpointer().adelete_thread(budget_thread)
        await db_manager.get_checkpointer().adelete_thread(isolation_thread)
        await db_manager.get_checkpointer().adelete_thread(isolation_memory_thread)
        await db_manager.get_store().adelete(alice_namespace, "/preference.txt")
        await db_manager.get_store().adelete(bob_namespace, "/preference.txt")
        await db_manager.get_store().adelete(
            isolation_namespace,
            "/preference.txt",
        )
    finally:
        graph_factory.clear_factory_registry(budget_graph_id)
        graph_factory.clear_factory_registry(isolation_graph_id)
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url
