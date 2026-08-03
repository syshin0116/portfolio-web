"""Opt-in black-box persistence checks against an actual PostgreSQL server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import runpy
import socket
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
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
from aegra_api.models.run_job import RunIdentity, RunJob
from aegra_api.services import graph_factory
from aegra_api.services import run_executor as aegra_run_executor
from aegra_api.services.event_streaming.session import ThreadEventSession
from aegra_api.services.langgraph_service import (
    LangGraphService,
    create_run_config,
    get_langgraph_service,
)
from aegra_api.services.run_status import finalize_run, set_thread_status
from aegra_api.settings import settings
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.store.postgres import AsyncPostgresStore
from langgraph.types import Command, StateSnapshot
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.responses import JSONResponse

from agent import http as http_extension
from agent.auth import (
    AGENT_AUTH_SECRET,
    ANONYMOUS_PERMISSION,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
)
from agent.graph import CreateOnlyStoreBackend
from agent.graph import graph as production_graph
from agent.guest_budget import (
    GuestBudgetConfig,
    GuestBudgetReservation,
    GuestDailyBudgetExhaustedError,
    PostgresGuestSpendLedger,
)
from agent.guest_thread_admission import (
    GuestThreadCreateDecision,
    admit_guest_thread_creation,
)
from agent.guest_thread_lock import (
    guest_thread_advisory_lock,
    guest_thread_create_advisory_lock,
)
from agent.http import GuestRunGuard, NativeThreadGuard
from agent.inspection import INSPECTION_EVENT_NAME
from agent.maintenance import (
    GUEST_RETENTION_POLICY,
    STALE_GUEST_RUN_ERROR,
    collect_expired_guest_threads,
    reconcile_stale_guest_runs,
)
from agent.migrate import migrate_database
from agent.recovery import (
    RECOVERED_GUEST_RUN_FENCE_KEY,
    RECOVERED_GUEST_RUN_FENCE_VALUE,
)
from agent.run_liveness import (
    GuestExecutionFence,
    GuestExecutionFenceRejectedError,
    acquire_guest_execution_fence,
    guest_execution_lock_key,
    wait_for_guest_execution_fence_monitors,
)
from agent.schema import AgentSchemaMigrationError, migrate_agent_schema

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
_GUEST_INTERRUPT_ID = "0123456789abcdef0123456789abcdef"
_GUEST_SUBMIT_NONCE = "123e4567-e89b-42d3-a456-426614174000"


def _postgres_memory_create_process(
    postgres_url: str,
    namespace: tuple[str, ...],
    file_path: str,
    content: str,
    mode: str,
    ready_queue: Any,
    start_event: Any,
    result_queue: Any,
) -> None:
    """Compete for one persistent-memory key from an independent process."""

    async def run() -> None:
        async with AsyncPostgresStore.from_conn_string(postgres_url) as store:
            backend = CreateOnlyStoreBackend(
                namespace=lambda _runtime: namespace,
                store=store,
            )
            ready_queue.put(mode)
            started = await asyncio.to_thread(start_event.wait, 15)
            if not started:
                raise TimeoutError("cross-process create start signal timed out")
            if mode == "async":
                result = await backend.awrite(file_path, content)
            elif mode == "sync":
                result = await asyncio.to_thread(backend.write, file_path, content)
            else:
                raise ValueError(f"unsupported cross-process create mode: {mode}")
            result_queue.put(
                {
                    "mode": mode,
                    "path": result.path,
                    "error": result.error,
                }
            )

    try:
        asyncio.run(run())
    except BaseException as error:
        result_queue.put(
            {
                "mode": mode,
                "exception": f"{type(error).__name__}: {error}",
            }
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


def _openai_response(
    content: str,
    *,
    tool_calls: list[dict[str, object]] | None = None,
) -> AIMessage:
    """Return provider-complete fake Luna usage for owner factory tests."""
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        response_metadata={
            "model_provider": "openai",
            "model_name": "gpt-5.6-luna",
        },
        usage_metadata={
            "input_tokens": 1,
            "output_tokens": 9,
            "total_tokens": 10,
            "input_token_details": {
                "cache_creation": 0,
                "cache_read": 0,
            },
            "output_token_details": {"reasoning": 0},
        },
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


def _guest_authorization(subject: str) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": subject,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + 300,
            "scope": ANONYMOUS_PERMISSION,
        },
        AGENT_AUTH_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _guest_paid_command(kind: str) -> dict[str, Any]:
    metadata = {"syshin_ui_submit_nonce": _GUEST_SUBMIT_NONCE}
    if kind == "run-start":
        return {
            "id": 7,
            "method": "run.start",
            "params": {
                "assistant_id": "agent",
                "config": {"metadata": metadata.copy()},
                "input": {
                    "messages": [
                        {
                            "content": "race proof",
                            "id": "guest-message-1",
                            "role": "user",
                        }
                    ]
                },
                "metadata": metadata,
            },
        }
    if kind == "input-respond":
        return {
            "id": 8,
            "method": "input.respond",
            "params": {
                "config": {"metadata": metadata.copy()},
                "interrupt_id": _GUEST_INTERRUPT_ID,
                "metadata": metadata,
                "namespace": [],
                "response": "approve",
            },
        }
    raise AssertionError(f"unknown guest command kind: {kind}")


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


@pytest.mark.parametrize(
    ("tamper_statements", "repair_version"),
    [
        (
            (
                """
                DROP TRIGGER agent_recovered_guest_run_update_guard
                ON runs
                """,
            ),
            "0002_recovered_guest_run_fence",
        ),
        (
            (
                """
                DROP TRIGGER agent_recovered_guest_run_update_guard
                ON runs
                """,
                """
                CREATE TRIGGER agent_recovered_guest_run_update_guard
                BEFORE UPDATE OF claimed_by ON runs
                FOR EACH ROW
                EXECUTE FUNCTION agent_reject_recovered_guest_run_update()
                """,
            ),
            "0002_recovered_guest_run_fence",
        ),
        (
            (
                """
                DROP INDEX
                    agent_guest_execution_quarantine_unresolved_idx
                """,
            ),
            "0003_guest_execution_quarantine",
        ),
    ],
    ids=["missing-trigger", "column-scoped-trigger", "missing-quarantine-index"],
)
async def test_project_migration_rejects_an_altered_recovery_boundary(
    tamper_statements,
    repair_version,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            for statement in tamper_statements:
                await connection.execute(statement)

        with pytest.raises(
            AgentSchemaMigrationError,
            match="recovery fence is missing or altered",
        ):
            await migrate_agent_schema(db_manager.get_engine())
    finally:
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                DELETE FROM agent_schema_migrations
                WHERE version = %s
                """,
                (repair_version,),
            )
        await migrate_agent_schema(db_manager.get_engine())
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_persistent_memory_create_is_atomic_across_processes():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    namespace = ("users", f"cross-process-{unique}", "filesystem")
    file_path = "/profile.txt"
    contenders = {
        "async": "async process contender",
        "sync": "sync process contender",
    }
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_postgres_memory_create_process,
            name=f"memory-create-{mode}-{unique}",
            args=(
                POSTGRES_URL,
                namespace,
                file_path,
                content,
                mode,
                ready_queue,
                start_event,
                result_queue,
            ),
        )
        for mode, content in contenders.items()
    ]

    try:
        await migrate_database()
        await db_manager.initialize()
        for process in processes:
            process.start()

        ready = [
            await asyncio.to_thread(ready_queue.get, True, 15) for _process in processes
        ]
        assert set(ready) == set(contenders)
        start_event.set()
        results = [
            await asyncio.to_thread(result_queue.get, True, 15)
            for _process in processes
        ]
        for process in processes:
            await asyncio.to_thread(process.join, 15)

        assert all(process.exitcode == 0 for process in processes)
        assert all("exception" not in result for result in results)
        assert {result["mode"] for result in results} == set(contenders)
        assert sum(result["path"] == file_path for result in results) == 1
        rejected = [result for result in results if result["path"] is None]
        assert len(rejected) == 1
        assert "already exists" in (rejected[0]["error"] or "")

        persisted = await db_manager.get_store().aget(namespace, file_path)
        assert persisted is not None
        assert persisted.value["content"] in set(contenders.values())

        backend = CreateOnlyStoreBackend(
            namespace=lambda _runtime: namespace,
            store=db_manager.get_store(),
        )
        edited = await backend.aedit(
            file_path,
            persisted.value["content"],
            "reviewed edit",
        )
        assert edited.path == file_path
        updated = await db_manager.get_store().aget(namespace, file_path)
        assert updated is not None
        assert updated.value["content"] == "reviewed edit"
    finally:
        start_event.set()
        for process in processes:
            if process.pid is None:
                continue
            if process.is_alive():
                await asyncio.to_thread(process.join, 2)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 2)
        ready_queue.close()
        ready_queue.cancel_join_thread()
        result_queue.close()
        result_queue.cancel_join_thread()
        if db_manager.engine is not None:
            with suppress(BaseException):
                await db_manager.get_store().adelete(namespace, file_path)
            await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


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
    alice_memory_overwrite_thread = f"postgres-memory-overwrite-alice-{unique}"
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
    alice_memory_overwrite_config = create_run_config(
        f"memory-alice-overwrite-{unique}",
        alice_memory_overwrite_thread,
        alice,
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
            "agent_schema_migrations",
            "agent_guest_daily_budget",
            "agent_guest_execution_quarantine",
        } <= tables
        assert versions == ["b88bb61be638"]

        large_assistant_id = f"large-config-{unique}"
        large_config = {
            "configurable": {
                "system_prompt": "large-aegra-config-" * 1_024,
            }
        }
        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'assistant'
                  AND indexname = 'idx_assistant_user_graph_config'
                """
            )
            index_row = await cursor.fetchone()
            assert index_row is not None
            assert "md5((config)::text)" in "".join(index_row[0].lower().split())

            await cursor.execute(
                """
                INSERT INTO assistant (
                    assistant_id,
                    name,
                    graph_id,
                    config,
                    context,
                    user_id,
                    metadata
                )
                VALUES (%s, %s, %s, %s::jsonb, '{}'::jsonb, %s, '{}'::jsonb)
                """,
                (
                    large_assistant_id,
                    "large config migration proof",
                    f"large-config-graph-{unique}",
                    json.dumps(large_config),
                    f"large-config-owner-{unique}",
                ),
            )
            await cursor.execute(
                "SELECT config FROM assistant WHERE assistant_id = %s",
                (large_assistant_id,),
            )
            inserted_config = await cursor.fetchone()
            assert inserted_config is not None
            assert inserted_config[0] == large_config
            await cursor.execute(
                "DELETE FROM assistant WHERE assistant_id = %s",
                (large_assistant_id,),
            )

        await db_manager.initialize()

        budget_model = ToolCapableFakeModel(
            responses=[_openai_response("budget checkpoint persisted")]
        )
        monkeypatch.setattr(
            "agent.graph._bounded_model",
            lambda _spec: budget_model,
        )

        async def fixed_input_count(_request):
            return 1

        monkeypatch.setattr(
            "agent.graph._OWNER_OPENAI_INPUT_TOKEN_COUNTER",
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

        with pytest.raises(
            RuntimeError,
            match=r"Cannot write to /preference\.txt because it already exists",
        ):
            async with memory_service.get_graph(
                "memory_fixture",
                config=alice_memory_overwrite_config,
                user=alice,
            ) as alice_memory_graph:
                await alice_memory_graph.ainvoke(
                    {"operation": "write", "content": "blind overwrite"},
                    alice_memory_overwrite_config,
                )
        alice_stored_memory = await db_manager.get_store().aget(
            alice_namespace,
            "/preference.txt",
        )
        assert alice_stored_memory is not None
        assert alice_stored_memory.value["content"] == "alice-only"

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
                _openai_response(
                    "",
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
                ),
                _openai_response("isolated child result"),
                _openai_response("isolated child result"),
                _openai_response("isolated root result"),
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
            "agent.graph._OWNER_OPENAI_INPUT_TOKEN_COUNTER",
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
            bob_state = await restarted_bob_graph.aget_state(
                bob_config,
                subgraphs=True,
            )

        assert alice_resumed["approval"] == "approved-after-restart"
        assert "approval" not in bob_state.values
        assert bob_state.next == ("nested_subgraph",)
        assert len(bob_state.tasks) == 1
        nested_task = bob_state.tasks[0]
        assert nested_task.name == "nested_subgraph"
        assert isinstance(nested_task.state, StateSnapshot)
        assert nested_task.state.next == ("request_approval",)
        assert nested_task.interrupts == nested_task.state.interrupts

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
        await db_manager.get_checkpointer().adelete_thread(
            alice_memory_overwrite_thread
        )
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


async def test_guest_interrupt_validation_reads_latest_postgres_root_state(
    monkeypatch,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    thread_id = f"guest-interrupt-cas-{uuid4().hex}"
    guest = User(
        identity=f"anon:{uuid4()}",
        permissions=["anon"],
    )
    run_configs = [
        create_run_config(
            f"guest-interrupt-cas-run-{uuid4().hex}",
            thread_id,
            guest,
        )
        for _index in range(3)
    ]

    try:
        await migrate_database()
        await db_manager.initialize()
        fixture_module = runpy.run_path(FIXTURE_GRAPH)
        service = _service(fixture_module["graph"])
        monkeypatch.setattr(
            http_extension,
            "get_langgraph_service",
            lambda: service,
        )

        async with service.get_graph(
            "fixture",
            config=run_configs[0],
            user=guest,
        ) as fixture_graph:
            first = await fixture_graph.ainvoke(
                {"messages": [HumanMessage(content="first guest turn")]},
                run_configs[0],
            )
        stale_id = first["__interrupt__"][0].id

        async with service.get_graph(
            "fixture",
            config=run_configs[1],
            user=guest,
        ) as fixture_graph:
            await fixture_graph.ainvoke(
                Command(resume={stale_id: "approved-first"}),
                run_configs[1],
            )

        async with service.get_graph(
            "fixture",
            config=run_configs[2],
            user=guest,
        ) as fixture_graph:
            second = await fixture_graph.ainvoke(
                {"messages": [HumanMessage(content="second guest turn")]},
                run_configs[2],
            )
            current_id = second["__interrupt__"][0].id
            root_state = await fixture_graph.aget_state(
                run_configs[2],
                subgraphs=False,
            )

        assert stale_id != current_id
        assert isinstance(root_state.interrupts, tuple)
        assert len(root_state.interrupts) == 1
        assert root_state.interrupts[0].id == current_id
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id
                )
                VALUES (%s, 'interrupted', %s::jsonb, %s)
                """,
                (
                    thread_id,
                    json.dumps({"graph_id": "fixture"}),
                    guest.identity,
                ),
            )

        observed = await http_extension._current_guest_root_interrupt_id(
            thread_id,
            guest.model_dump(),
        )
        assert observed == current_id
        assert observed != stale_id
    finally:
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
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_guest_daily_budget_and_checkpoint_first_gc_are_durable():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    expired_thread = f"guest-expired-{unique}"
    future_thread = f"guest-future-{unique}"
    busy_thread = f"guest-busy-{unique}"
    malformed_thread = f"guest-malformed-{unique}"
    owner_thread = f"owner-expired-{unique}"
    thread_ids = (
        expired_thread,
        future_thread,
        busy_thread,
        malformed_thread,
        owner_thread,
    )

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM agent_guest_daily_budget "
                "WHERE budget_date = (timezone('UTC', now()))::date"
            )
            rows = [
                (
                    expired_thread,
                    "idle",
                    json.dumps(
                        {
                            "guest_expires_at": "2000-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    f"anon:{uuid4()}",
                ),
                (
                    future_thread,
                    "idle",
                    json.dumps(
                        {
                            "guest_expires_at": "2999-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    f"anon:{uuid4()}",
                ),
                (
                    busy_thread,
                    "busy",
                    json.dumps(
                        {
                            "guest_expires_at": "2000-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    f"anon:{uuid4()}",
                ),
                (
                    malformed_thread,
                    "idle",
                    json.dumps(
                        {
                            "guest_expires_at": "not-a-date",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    f"anon:{uuid4()}",
                ),
                (
                    owner_thread,
                    "idle",
                    json.dumps(
                        {
                            "guest_expires_at": "2000-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    "owner",
                ),
            ]
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO thread (
                        thread_id,
                        status,
                        metadata_json,
                        user_id
                    )
                    VALUES (%s, %s, %s::jsonb, %s)
                    """,
                    rows,
                )

        await db_manager.get_checkpointer().aput(
            {
                "configurable": {
                    "thread_id": expired_thread,
                    "checkpoint_ns": "",
                }
            },
            empty_checkpoint(),
            {"source": "input", "step": -1, "parents": {}},
            {},
        )

        ledger = PostgresGuestSpendLedger(
            GuestBudgetConfig(
                daily_limit_micro_usd=75_000,
                run_reservation_micro_usd=25_000,
            )
        )
        reservations = await asyncio.gather(
            *(ledger.reserve_run() for _index in range(4)),
            return_exceptions=True,
        )
        committed = [
            value for value in reservations if isinstance(value, GuestBudgetReservation)
        ]
        exhausted = [
            value
            for value in reservations
            if isinstance(value, GuestDailyBudgetExhaustedError)
        ]
        assert len(committed) == 3
        assert len(exhausted) == 1
        assert max(value.reserved_micro_usd for value in committed) == 75_000
        assert max(value.run_count for value in committed) == 3

        result = await collect_expired_guest_threads(batch_size=10)
        assert result.lock_acquired is True
        assert result.deleted_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT thread_id FROM thread WHERE thread_id = ANY(%s)",
                (list(thread_ids),),
            )
            remaining_threads = {row[0] for row in await cursor.fetchall()}
            assert remaining_threads == {
                future_thread,
                busy_thread,
                malformed_thread,
                owner_thread,
            }
            for table in (
                "checkpoints",
                "checkpoint_blobs",
                "checkpoint_writes",
            ):
                await cursor.execute(
                    f"SELECT count(*) FROM {table} WHERE thread_id = %s",
                    (expired_thread,),
                )
                assert (await cursor.fetchone())[0] == 0
    finally:
        if db_manager.engine is None:
            await db_manager.initialize()
        for thread_id in thread_ids:
            await db_manager.get_checkpointer().adelete_thread(thread_id)
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = ANY(%s)",
                (list(thread_ids),),
            )
            await connection.execute(
                "DELETE FROM agent_guest_daily_budget "
                "WHERE budget_date = (timezone('UTC', now()))::date"
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


@pytest.mark.parametrize("command_kind", ["run-start", "input-respond"])
async def test_guest_command_lock_prevents_gc_until_busy_commit(
    monkeypatch,
    command_kind,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")

    thread_id = f"guest-command-wins-{command_kind}-{uuid4().hex}"
    guest_id = f"anon:{uuid4()}"
    checkpoint_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    downstream_entered = asyncio.Event()
    release_downstream = asyncio.Event()
    command_task: asyncio.Task[Any] | None = None

    class Ledger:
        def __init__(self):
            self.calls = 0

        async def reserve_run(self):
            self.calls += 1

    ledger = Ledger()
    downstream_calls = 0

    async def current_interrupt(_thread_id, _user):
        return _GUEST_INTERRUPT_ID

    async def downstream(scope, receive, send):
        nonlocal downstream_calls
        downstream_calls += 1
        await receive()
        downstream_entered.set()
        await release_downstream.wait()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            updated = await connection.execute(
                """
                UPDATE thread
                SET status = 'busy', updated_at = now()
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            assert updated.rowcount == 1
        await JSONResponse(
            {
                "id": 7 if command_kind == "run-start" else 8,
                "meta": {"applied_through_seq": 0},
                "result": {"run_id": "race-run"},
                "type": "success",
            }
        )(scope, receive, send)

    try:
        await migrate_database()
        await db_manager.initialize()
        await db_manager.get_checkpointer().aput(
            checkpoint_config,
            empty_checkpoint(),
            {"source": "input", "step": -1, "parents": {}},
            {},
        )
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id
                )
                VALUES (%s, %s, %s::jsonb, %s)
                """,
                (
                    thread_id,
                    "idle" if command_kind == "run-start" else "interrupted",
                    json.dumps(
                        {
                            "graph_id": "agent",
                            "guest_expires_at": "2000-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    guest_id,
                ),
            )
        monkeypatch.setattr(
            http_extension,
            "_current_guest_root_interrupt_id",
            current_interrupt,
        )
        guarded = NativeThreadGuard(
            GuestRunGuard(
                downstream,
                spend_ledger=ledger,
            )
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=guarded),
            base_url="http://test",
        ) as client:
            command_task = asyncio.create_task(
                client.post(
                    f"/threads/{thread_id}/commands",
                    headers=_guest_authorization(guest_id),
                    json=_guest_paid_command(command_kind),
                )
            )
            await asyncio.wait_for(downstream_entered.wait(), timeout=5)
            while_command_holds_lock = await collect_expired_guest_threads(
                batch_size=10
            )
            assert while_command_holds_lock.lock_acquired is True
            assert while_command_holds_lock.deleted_threads == 0
            async with await psycopg.AsyncConnection.connect(
                POSTGRES_URL
            ) as connection:
                row = await connection.execute(
                    "SELECT status FROM thread WHERE thread_id = %s",
                    (thread_id,),
                )
                assert await row.fetchone() == (
                    "idle" if command_kind == "run-start" else "interrupted",
                )

            release_downstream.set()
            response = await asyncio.wait_for(command_task, timeout=5)

        assert response.status_code == 200
        assert ledger.calls == 1
        assert downstream_calls == 1
        after_busy_commit = await collect_expired_guest_threads(batch_size=10)
        assert after_busy_commit.deleted_threads == 0
        assert (
            await db_manager.get_checkpointer().aget_tuple(checkpoint_config)
            is not None
        )
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            row = await connection.execute(
                "SELECT status FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
            assert await row.fetchone() == ("busy",)
    finally:
        release_downstream.set()
        if command_task is not None:
            if not command_task.done():
                command_task.cancel()
            await asyncio.gather(command_task, return_exceptions=True)
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
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


@pytest.mark.parametrize("command_kind", ["run-start", "input-respond"])
async def test_gc_commit_wins_before_guest_command_can_reacquire_thread(
    monkeypatch,
    command_kind,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")

    thread_id = f"guest-gc-wins-{command_kind}-{uuid4().hex}"
    guest_id = f"anon:{uuid4()}"
    checkpoint_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    gc_holds_thread_lock = asyncio.Event()
    release_gc = asyncio.Event()
    downstream_calls = 0
    ownership_observations = []
    command_task: asyncio.Task[Any] | None = None
    gc_task: asyncio.Task[Any] | None = None

    class Ledger:
        def __init__(self):
            self.calls = 0

        async def reserve_run(self):
            self.calls += 1

    class BlockingCheckpointer:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        async def adelete_thread(self, selected_thread_id):
            assert selected_thread_id == thread_id
            gc_holds_thread_lock.set()
            await release_gc.wait()
            await self.wrapped.adelete_thread(selected_thread_id)

    ledger = Ledger()

    async def forbidden_interrupt(_thread_id, _user):
        raise AssertionError("a GC-deleted thread must fail before state lookup")

    native_thread_status = http_extension._owned_or_new_thread_status

    async def observed_thread_status(selected_thread_id, selected_user_id):
        result = await native_thread_status(
            selected_thread_id,
            selected_user_id,
        )
        ownership_observations.append(result)
        return result

    async def downstream(scope, receive, send):
        nonlocal downstream_calls
        del scope, receive, send
        downstream_calls += 1

    try:
        await migrate_database()
        await db_manager.initialize()
        checkpointer = db_manager.get_checkpointer()
        await checkpointer.aput(
            checkpoint_config,
            empty_checkpoint(),
            {"source": "input", "step": -1, "parents": {}},
            {},
        )
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id
                )
                VALUES (%s, %s, %s::jsonb, %s)
                """,
                (
                    thread_id,
                    "idle" if command_kind == "run-start" else "interrupted",
                    json.dumps(
                        {
                            "graph_id": "agent",
                            "guest_expires_at": "2000-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    guest_id,
                ),
            )
        monkeypatch.setattr(
            http_extension,
            "_current_guest_root_interrupt_id",
            forbidden_interrupt,
        )
        monkeypatch.setattr(
            http_extension,
            "_owned_or_new_thread_status",
            observed_thread_status,
        )
        guarded = NativeThreadGuard(
            GuestRunGuard(
                downstream,
                spend_ledger=ledger,
            )
        )
        gc_task = asyncio.create_task(
            collect_expired_guest_threads(
                batch_size=10,
                checkpointer=BlockingCheckpointer(checkpointer),
            )
        )
        await asyncio.wait_for(gc_holds_thread_lock.wait(), timeout=5)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=guarded),
            base_url="http://test",
        ) as client:
            command_task = asyncio.create_task(
                client.post(
                    f"/threads/{thread_id}/commands",
                    headers=_guest_authorization(guest_id),
                    json=_guest_paid_command(command_kind),
                )
            )
            await asyncio.sleep(0.05)
            assert not command_task.done()
            release_gc.set()
            gc_result = await asyncio.wait_for(gc_task, timeout=5)
            response = await asyncio.wait_for(command_task, timeout=5)

        assert gc_result.deleted_threads == 1
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
        # The command crosses the advisory boundary only after the GC transaction
        # commits its parent DELETE, so its first ownership read sees no old row.
        assert ownership_observations == [(True, None)]
        assert ledger.calls == 0
        assert downstream_calls == 0
        assert await checkpointer.aget_tuple(checkpoint_config) is None
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            row = await connection.execute(
                "SELECT thread_id FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
            assert await row.fetchone() is None
    finally:
        release_gc.set()
        pending_tasks = [task for task in (command_task, gc_task) if task is not None]
        for task in pending_tasks:
            if not task.done():
                task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
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
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_cancelled_guest_command_releases_real_postgres_thread_lock(
    monkeypatch,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")

    thread_id = f"guest-cancel-lock-{uuid4().hex}"
    guest_id = f"anon:{uuid4()}"
    downstream_entered = asyncio.Event()

    async def downstream(_scope, _receive, _send):
        downstream_entered.set()
        await asyncio.Event().wait()

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id
                )
                VALUES (%s, 'idle', %s::jsonb, %s)
                """,
                (
                    thread_id,
                    json.dumps(
                        {
                            "graph_id": "agent",
                            "guest_expires_at": "2999-01-01T00:00:00Z",
                            "guest_retention_policy": GUEST_RETENTION_POLICY,
                        }
                    ),
                    guest_id,
                ),
            )
        guarded = NativeThreadGuard(GuestRunGuard(downstream))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=guarded),
            base_url="http://test",
        ) as client:
            command_task = asyncio.create_task(
                client.post(
                    f"/threads/{thread_id}/commands",
                    headers=_guest_authorization(guest_id),
                    json=_guest_paid_command("run-start"),
                )
            )
            await asyncio.wait_for(downstream_entered.wait(), timeout=5)
            command_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await command_task

        reacquired = False
        async with guest_thread_advisory_lock(
            thread_id,
            timeout_seconds=1,
        ):
            reacquired = True
        assert reacquired is True
    finally:
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_real_postgres_guest_creation_lock_observes_committed_cap_and_owner():
    """The second cold-start admission must count the first committed create."""
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    prefix = f"guest-admission-{unique}"
    guest_id = f"anon:{uuid4()}"
    foreign_id = f"anon:{uuid4()}"
    existing_ids = [f"{prefix}-seed-{index}" for index in range(5)]
    first_created_id = f"{prefix}-first"
    capped_id = f"{prefix}-capped"
    create_committed = asyncio.Event()
    release_first_response = asyncio.Event()
    first_task: asyncio.Task[GuestThreadCreateDecision] | None = None
    second_task: asyncio.Task[GuestThreadCreateDecision] | None = None

    metadata = json.dumps(
        {
            "graph_id": "agent",
            "guest_expires_at": "2000-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )

    async def insert_thread(thread_id: str) -> None:
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (thread_id, status, metadata_json, user_id)
                VALUES (%s, 'idle', %s::jsonb, %s)
                """,
                (thread_id, metadata, guest_id),
            )

    async def first_create() -> GuestThreadCreateDecision:
        async with admit_guest_thread_creation(
            thread_id=first_created_id,
            identity=guest_id,
        ) as decision:
            assert decision == GuestThreadCreateDecision.NEW
            # This models Aegra's downstream POST /threads transaction. Its response
            # cannot leave the admission context until the row has committed.
            await insert_thread(first_created_id)
            create_committed.set()
            await release_first_response.wait()
            return decision

    async def second_create() -> GuestThreadCreateDecision:
        async with admit_guest_thread_creation(
            thread_id=capped_id,
            identity=guest_id,
        ) as decision:
            return decision

    try:
        await migrate_database()
        for thread_id in existing_ids:
            await insert_thread(thread_id)

        first_task = asyncio.create_task(first_create())
        await asyncio.wait_for(create_committed.wait(), timeout=5)
        second_task = asyncio.create_task(second_create())
        await asyncio.sleep(0.05)
        assert second_task.done() is False

        release_first_response.set()
        assert await asyncio.wait_for(first_task, timeout=5) == (
            GuestThreadCreateDecision.NEW
        )
        assert await asyncio.wait_for(second_task, timeout=5) == (
            GuestThreadCreateDecision.IDENTITY_LIMIT
        )

        # Existing IDs remain idempotent at the cap and foreign collisions remain
        # hidden even though every row is already retention-expired.
        async with admit_guest_thread_creation(
            thread_id=first_created_id,
            identity=guest_id,
        ) as decision:
            assert decision == GuestThreadCreateDecision.EXISTING_OWNED
        async with admit_guest_thread_creation(
            thread_id=first_created_id,
            identity=foreign_id,
        ) as decision:
            assert decision == GuestThreadCreateDecision.FOREIGN
    finally:
        release_first_response.set()
        pending = [task for task in (first_task, second_task) if task is not None]
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id LIKE %s",
                (f"{prefix}%",),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_cancelled_real_postgres_creation_lock_releases_distinct_domain():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url
    entered = asyncio.Event()
    holder: asyncio.Task[None] | None = None

    async def hold_creation_lock() -> None:
        async with guest_thread_create_advisory_lock(timeout_seconds=5):
            entered.set()
            await asyncio.Event().wait()

    try:
        holder = asyncio.create_task(hold_creation_lock())
        await asyncio.wait_for(entered.wait(), timeout=5)

        # A create-wide lock must never alias an arbitrary per-thread lock.
        async with guest_thread_advisory_lock(
            f"creation-domain-proof-{uuid4().hex}",
            timeout_seconds=1,
        ):
            pass

        holder.cancel()
        with pytest.raises(asyncio.CancelledError):
            await holder

        reacquired = False
        async with guest_thread_create_advisory_lock(timeout_seconds=1):
            reacquired = True
        assert reacquired is True
    finally:
        if holder is not None and not holder.done():
            holder.cancel()
            await asyncio.gather(holder, return_exceptions=True)
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_stale_local_guest_runs_are_reconciled_without_touching_live_rows():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    now = datetime.now(UTC)
    stale = now - timedelta(minutes=40)
    less_stale = now - timedelta(minutes=30)
    fresh = now - timedelta(minutes=1)

    target_running = f"stale-running-{unique}"
    target_pending = f"stale-pending-{unique}"
    fresh_guest = f"fresh-guest-{unique}"
    owner_thread = f"owner-stale-{unique}"
    malformed_guest = f"malformed-guest-{unique}"
    leased_guest = f"leased-guest-{unique}"
    mixed_guest = f"mixed-guest-{unique}"
    wrong_policy_guest = f"wrong-policy-{unique}"
    thread_ids = (
        target_running,
        target_pending,
        fresh_guest,
        owner_thread,
        malformed_guest,
        leased_guest,
        mixed_guest,
        wrong_policy_guest,
    )
    subjects = {
        target_running: f"anon:{uuid4()}",
        target_pending: f"anon:{uuid4()}",
        fresh_guest: f"anon:{uuid4()}",
        owner_thread: "owner",
        malformed_guest: "anon:not-a-uuid",
        leased_guest: f"anon:{uuid4()}",
        mixed_guest: f"anon:{uuid4()}",
        wrong_policy_guest: f"anon:{uuid4()}",
    }
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    wrong_retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": "other-policy",
        }
    )
    runs = (
        (f"run-target-running-{unique}", target_running, "running", stale, None, None),
        (
            f"run-target-pending-{unique}",
            target_pending,
            "pending",
            less_stale,
            None,
            None,
        ),
        (f"run-fresh-{unique}", fresh_guest, "running", fresh, None, None),
        (f"run-owner-{unique}", owner_thread, "running", stale, None, None),
        (
            f"run-malformed-{unique}",
            malformed_guest,
            "running",
            stale,
            None,
            None,
        ),
        (
            f"run-leased-{unique}",
            leased_guest,
            "running",
            stale,
            "redis-worker",
            stale,
        ),
        (f"run-mixed-stale-{unique}", mixed_guest, "running", stale, None, None),
        (f"run-mixed-fresh-{unique}", mixed_guest, "pending", fresh, None, None),
        (
            f"run-wrong-policy-{unique}",
            wrong_policy_guest,
            "running",
            stale,
            None,
            None,
        ),
    )
    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            thread_rows = [
                (
                    thread_id,
                    "busy",
                    wrong_retention if thread_id == wrong_policy_guest else retention,
                    subjects[thread_id],
                    fresh if thread_id == fresh_guest else stale,
                    fresh if thread_id == fresh_guest else stale,
                )
                for thread_id in thread_ids
            ]
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO thread (
                        thread_id,
                        status,
                        metadata_json,
                        user_id,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    thread_rows,
                )
                await cursor.executemany(
                    """
                    INSERT INTO runs (
                        run_id,
                        thread_id,
                        status,
                        user_id,
                        created_at,
                        updated_at,
                        claimed_by,
                        lease_expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            thread_id,
                            status,
                            subjects[thread_id],
                            updated_at,
                            updated_at,
                            claimed_by,
                            lease_expires_at,
                        )
                        for (
                            run_id,
                            thread_id,
                            status,
                            updated_at,
                            claimed_by,
                            lease_expires_at,
                        ) in runs
                    ],
                )

        first = await reconcile_stale_guest_runs(batch_size=1)
        assert first.lock_acquired is True
        assert first.reconciled_runs == 1
        assert first.released_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT t.thread_id, t.status, r.run_id, r.status, r.error_message
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = ANY(%s)
                """,
                (list(thread_ids),),
            )
            first_rows = {
                row[2]: (row[0], row[1], row[3], row[4])
                for row in await cursor.fetchall()
            }

        assert first_rows[f"run-target-running-{unique}"] == (
            target_running,
            "error",
            "error",
            STALE_GUEST_RUN_ERROR,
        )
        assert first_rows[f"run-target-pending-{unique}"][1:3] == (
            "busy",
            "pending",
        )

        second = await reconcile_stale_guest_runs(batch_size=10)
        assert second.lock_acquired is True
        assert second.reconciled_runs == 1
        assert second.released_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT
                    t.thread_id,
                    t.status,
                    r.run_id,
                    r.status,
                    r.error_message,
                    r.claimed_by
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = ANY(%s)
                """,
                (list(thread_ids),),
            )
            final_rows = {
                row[2]: (row[0], row[1], row[3], row[4], row[5])
                for row in await cursor.fetchall()
            }

        assert final_rows[f"run-target-pending-{unique}"] == (
            target_pending,
            "error",
            "error",
            STALE_GUEST_RUN_ERROR,
            None,
        )
        for run_id in (
            f"run-fresh-{unique}",
            f"run-owner-{unique}",
            f"run-malformed-{unique}",
            f"run-mixed-stale-{unique}",
            f"run-mixed-fresh-{unique}",
            f"run-wrong-policy-{unique}",
        ):
            expected_status = next(row[2] for row in runs if row[0] == run_id)
            assert final_rows[run_id][1:4] == (
                "busy",
                expected_status,
                None,
            )
        assert final_rows[f"run-leased-{unique}"] == (
            leased_guest,
            "busy",
            "running",
            None,
            "redis-worker",
        )
    finally:
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = ANY(%s)",
                (list(thread_ids),),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_live_guest_execution_fence_blocks_reconciliation_until_release():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    thread_id = f"live-fenced-thread-{unique}"
    run_id = f"live-fenced-run-{unique}"
    identity = f"anon:{uuid4()}"
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    fence = None
    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                (thread_id, retention, identity, stale, stale),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (%s, %s, 'running', %s, %s, %s, NULL, NULL)
                """,
                (run_id, thread_id, identity, stale, stale),
            )

        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )

        while_held = await reconcile_stale_guest_runs(batch_size=10)
        assert while_held.lock_acquired is True
        assert while_held.liveness_skipped_runs == 1
        assert while_held.reconciled_runs == 0
        assert while_held.released_threads == 0
        assert while_held.stale_after_seconds == 900

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT t.status, r.status, r.error_message
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = %s AND r.run_id = %s
                """,
                (thread_id, run_id),
            )
            assert await cursor.fetchone() == ("busy", "running", None)

        await fence.aclose()
        fence = None

        after_release = await reconcile_stale_guest_runs(batch_size=10)
        assert after_release.lock_acquired is True
        assert after_release.liveness_skipped_runs == 0
        assert after_release.reconciled_runs == 1
        assert after_release.released_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT t.status, r.status, r.error_message
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = %s AND r.run_id = %s
                """,
                (thread_id, run_id),
            )
            assert await cursor.fetchone() == (
                "error",
                "error",
                STALE_GUEST_RUN_ERROR,
            )
    finally:
        if fence is not None:
            await fence.aclose()
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_killed_factory_fence_quarantines_until_durable_owner_drain(
    monkeypatch,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    run_id = f"killed-factory-run-{unique}"
    thread_id = f"killed-factory-thread-{unique}"
    identity = f"anon:{uuid4()}"
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2000-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    acquisition_done = asyncio.Event()
    graph_entered = asyncio.Event()
    second_poll_waiting = asyncio.Event()
    allow_second_poll = asyncio.Event()
    allow_gap_checkpoint = asyncio.Event()
    gap_checkpoint_written = asyncio.Event()
    allow_post_cancel_checkpoint = asyncio.Event()
    post_cancel_checkpoint_started = asyncio.Event()
    owner_cancelled = asyncio.Event()
    fence_ready = asyncio.get_running_loop().create_future()
    monitor_ready = asyncio.get_running_loop().create_future()
    owner_task = None
    monitor = None
    original_acquire = acquire_guest_execution_fence
    original_start_monitor = GuestExecutionFence.start_owner_monitor
    original_execution_is_active = GuestExecutionFence.execution_is_active
    monitor_poll_count = 0

    async def capture_fence(**kwargs):
        fence = await original_acquire(**kwargs)
        backend_pid = (
            await fence.connection.execute(text("SELECT pg_backend_pid()"))
        ).scalar_one()
        await fence.connection.commit()
        acquisition_done.set()
        fence_ready.set_result((fence, backend_pid))
        return fence

    def capture_monitor(fence):
        monitor_task = original_start_monitor(fence)
        monitor_ready.set_result(monitor_task)
        return monitor_task

    async def gate_second_monitor_poll(fence):
        nonlocal monitor_poll_count
        if not acquisition_done.is_set():
            return await original_execution_is_active(fence)
        monitor_poll_count += 1
        if monitor_poll_count == 2:
            second_poll_waiting.set()
            await allow_second_poll.wait()
        return await original_execution_is_active(fence)

    def provider_free_graph(**_kwargs):
        return object()

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                (thread_id, retention, identity, stale, stale),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    execution_params,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (
                    %s,
                    %s,
                    'running',
                    %s,
                    %s,
                    %s,
                    '{}'::jsonb,
                    NULL,
                    NULL
                )
                """,
                (run_id, thread_id, identity, stale, stale),
            )

        guest = User(identity=identity, permissions=["anon"])
        config = create_run_config(run_id, thread_id, guest)
        checkpoint_config = {
            **config,
            "configurable": {
                **config["configurable"],
                "checkpoint_ns": "",
            },
        }
        runtime = graph_factory.build_server_runtime(
            access_context="threads.create_run",
            store=db_manager.get_store(),
            user=guest,
            context=None,
        )
        checkpointer = db_manager.get_checkpointer()
        monkeypatch.setenv("GUEST_MODEL", "openai:gpt-5.6-luna")
        monkeypatch.setattr(
            "agent.graph.acquire_guest_execution_fence",
            capture_fence,
        )
        monkeypatch.setattr("agent.graph.create_graph", provider_free_graph)
        monkeypatch.setattr(
            GuestExecutionFence,
            "start_owner_monitor",
            capture_monitor,
        )
        monkeypatch.setattr(
            GuestExecutionFence,
            "execution_is_active",
            gate_second_monitor_poll,
        )

        async def graph_owner():
            try:
                async with production_graph(config, runtime):
                    graph_entered.set()
                    await allow_gap_checkpoint.wait()
                    await checkpointer.aput(
                        checkpoint_config,
                        empty_checkpoint(),
                        {"source": "input", "step": -1, "parents": {}},
                        {},
                    )
                    gap_checkpoint_written.set()
                    await allow_post_cancel_checkpoint.wait()
                    post_cancel_checkpoint_started.set()
                    await checkpointer.aput(
                        checkpoint_config,
                        empty_checkpoint(),
                        {"source": "loop", "step": 0, "parents": {}},
                        {},
                    )
            except asyncio.CancelledError:
                owner_cancelled.set()
                raise

        owner_task = asyncio.create_task(graph_owner())
        _fence, backend_pid = await fence_ready
        monitor = await monitor_ready
        async with asyncio.timeout(5):
            await graph_entered.wait()
            await second_poll_waiting.wait()

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT pg_terminate_backend(%s)", (backend_pid,))
            assert (await cursor.fetchone())[0] is True

        allow_gap_checkpoint.set()
        async with asyncio.timeout(5):
            await gap_checkpoint_written.wait()

        recovered = await reconcile_stale_guest_runs(batch_size=10)
        assert recovered.liveness_skipped_runs == 0
        assert recovered.reconciled_runs == 1
        assert recovered.released_threads == 1

        same_sweep = await collect_expired_guest_threads(batch_size=10)
        assert same_sweep.deleted_threads == 0

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT
                    t.status,
                    r.status,
                    r.execution_params ->> %s
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = %s AND r.run_id = %s
                """,
                (RECOVERED_GUEST_RUN_FENCE_KEY, thread_id, run_id),
            )
            assert await cursor.fetchone() == (
                "error",
                "error",
                RECOVERED_GUEST_RUN_FENCE_VALUE,
            )
            await cursor.execute(
                "SELECT count(*) FROM checkpoints WHERE thread_id = %s",
                (thread_id,),
            )
            checkpoint_count_before_cancel = (await cursor.fetchone())[0]
            assert checkpoint_count_before_cancel >= 1
            await cursor.execute(
                """
                SELECT recovered_at IS NOT NULL, drained_at
                FROM agent_guest_execution_quarantine
                WHERE
                    run_id = %s
                    AND thread_id = %s
                    AND identity = %s
                """,
                (run_id, thread_id, identity),
            )
            assert await cursor.fetchone() == (True, None)
            await cursor.execute(
                """
                UPDATE agent_guest_execution_quarantine
                SET recovered_at = '2000-01-01T00:00:00Z'
                WHERE
                    run_id = %s
                    AND thread_id = %s
                    AND identity = %s
                """,
                (run_id, thread_id, identity),
            )

        after_arbitrary_age = await collect_expired_guest_threads(batch_size=10)
        assert after_arbitrary_age.deleted_threads == 0

        allow_second_poll.set()
        async with asyncio.timeout(5):
            await owner_cancelled.wait()
        with pytest.raises(asyncio.CancelledError):
            await owner_task
        with pytest.raises(DBAPIError):
            await monitor
        monitor = None

        allow_post_cancel_checkpoint.set()
        await asyncio.sleep(0)
        assert post_cancel_checkpoint_started.is_set() is False
        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT count(*) FROM checkpoints WHERE thread_id = %s",
                (thread_id,),
            )
            assert (await cursor.fetchone())[0] == checkpoint_count_before_cancel
            await cursor.execute(
                """
                SELECT recovered_at, drained_at
                FROM agent_guest_execution_quarantine
                WHERE
                    run_id = %s
                    AND thread_id = %s
                    AND identity = %s
                """,
                (run_id, thread_id, identity),
            )
            recovered_at, drained_at = await cursor.fetchone()
            assert recovered_at is not None
            assert drained_at is not None

        after_drain_proof = await collect_expired_guest_threads(batch_size=10)
        assert after_drain_proof.deleted_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            for table, column in (
                ("thread", "thread_id"),
                ("runs", "thread_id"),
                ("checkpoints", "thread_id"),
                ("checkpoint_blobs", "thread_id"),
                ("checkpoint_writes", "thread_id"),
            ):
                await cursor.execute(
                    f"SELECT count(*) FROM {table} WHERE {column} = %s",
                    (thread_id,),
                )
                assert (await cursor.fetchone())[0] == 0
    finally:
        allow_second_poll.set()
        allow_gap_checkpoint.set()
        allow_post_cancel_checkpoint.set()
        if owner_task is not None and not owner_task.done():
            owner_task.cancel()
            with suppress(BaseException):
                await owner_task
        if monitor is not None and not monitor.done():
            monitor.cancel()
            with suppress(BaseException):
                await monitor
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
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


@pytest.mark.parametrize("late_outcome", ["success", "error", "cancel"])
async def test_killed_fence_backend_blocks_each_late_aegra_execute_run_finalizer(
    monkeypatch,
    late_outcome,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    run_id = f"killed-fence-{late_outcome}-run-{unique}"
    replacement_run_id = f"killed-fence-{late_outcome}-replacement-{unique}"
    thread_id = f"killed-fence-{late_outcome}-thread-{unique}"
    identity = f"anon:{uuid4()}"
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    owner_cancelled = asyncio.Event()
    allow_late_finalize = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()
    owner_task = None
    monitor = None
    job = RunJob(
        identity=RunIdentity(
            run_id=run_id,
            thread_id=thread_id,
            graph_id="fixture",
        ),
        user=User(identity=identity, permissions=["anon"]),
    )

    async def controlled_stream(active_job):
        assert active_job is job
        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        backend_pid = (
            await fence.connection.execute(text("SELECT pg_backend_pid()"))
        ).scalar_one()
        await fence.connection.commit()
        monitor_ready.set_result((fence.start_owner_monitor(), backend_pid))
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            owner_cancelled.set()
            await allow_late_finalize.wait()
            if late_outcome == "cancel":
                raise
        if late_outcome == "error":
            raise RuntimeError("late graph failure")
        result = aegra_run_executor._GraphResult()
        result.data = {"late": True}
        return result

    async def no_op(*_args, **_kwargs):
        return None

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                (thread_id, retention, identity, stale, stale),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    execution_params,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (%s, %s, 'pending', %s, %s, %s, %s::jsonb, NULL, NULL)
                """,
                (
                    run_id,
                    thread_id,
                    identity,
                    stale,
                    stale,
                    json.dumps(job.to_execution_params()),
                ),
            )

        monkeypatch.setattr(aegra_run_executor, "_stream_graph", controlled_stream)
        monkeypatch.setattr(aegra_run_executor, "_best_effort_signal", no_op)
        monkeypatch.setattr(aegra_run_executor, "_signal_run_done", no_op)
        monkeypatch.setattr(
            aegra_run_executor.streaming_service,
            "cleanup_run",
            no_op,
        )
        owner_task = asyncio.create_task(aegra_run_executor.execute_run(job))
        monitor, backend_pid = await monitor_ready
        assert isinstance(backend_pid, int)

        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                UPDATE runs
                SET updated_at = %s
                WHERE run_id = %s
                """,
                (stale, run_id),
            )
            await connection.execute(
                """
                UPDATE thread
                SET updated_at = %s
                WHERE thread_id = %s
                """,
                (stale, thread_id),
            )

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT pg_terminate_backend(%s)", (backend_pid,))
            assert (await cursor.fetchone())[0] is True

        async with asyncio.timeout(5):
            await owner_cancelled.wait()
        assert not owner_task.done()
        assert not monitor.done()

        recovered = await reconcile_stale_guest_runs(batch_size=10)
        assert recovered.liveness_skipped_runs == 0
        assert recovered.reconciled_runs == 1
        assert recovered.released_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT
                    t.status,
                    r.status,
                    r.error_message,
                    r.execution_params ->> %s
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = %s AND r.run_id = %s
                """,
                (RECOVERED_GUEST_RUN_FENCE_KEY, thread_id, run_id),
            )
            assert await cursor.fetchone() == (
                "error",
                "error",
                STALE_GUEST_RUN_ERROR,
                RECOVERED_GUEST_RUN_FENCE_VALUE,
            )

        allow_late_finalize.set()
        with pytest.raises(DBAPIError, match="recovered guest run is immutable"):
            await owner_task
        with pytest.raises(DBAPIError):
            await monitor
        monitor = None

        maker = aegra_orm.get_session_maker()
        async with maker() as session:
            await set_thread_status(session, thread_id, "busy")
            await session.commit()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    execution_params
                )
                VALUES (%s, %s, 'running', %s, '{}'::jsonb)
                """,
                (replacement_run_id, thread_id, identity),
            )

        await finalize_run(
            replacement_run_id,
            thread_id,
            status="success",
            thread_status="idle",
            output={"replacement": True},
        )

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT t.status, old.status, replacement.status
                FROM thread AS t
                JOIN runs AS old
                    ON old.thread_id = t.thread_id AND old.run_id = %s
                JOIN runs AS replacement
                    ON replacement.thread_id = t.thread_id
                    AND replacement.run_id = %s
                WHERE t.thread_id = %s
                """,
                (run_id, replacement_run_id, thread_id),
            )
            assert await cursor.fetchone() == ("idle", "error", "success")
    finally:
        allow_late_finalize.set()
        if owner_task is not None and not owner_task.done():
            owner_task.cancel()
            with suppress(BaseException):
                await owner_task
        if monitor is not None and not monitor.done():
            monitor.cancel()
            with suppress(BaseException):
                await monitor
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_cancelled_monitor_quarantines_until_live_owner_is_drained():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    run_id = f"cancelled-monitor-run-{unique}"
    thread_id = f"cancelled-monitor-thread-{unique}"
    identity = f"anon:{uuid4()}"
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    owner_cancelled = asyncio.Event()
    allow_owner_finalize = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()
    owner_task = None
    monitor = None

    async def cancelled_aegra_owner():
        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            owner_cancelled.set()
            await allow_owner_finalize.wait()
        await finalize_run(
            run_id,
            thread_id,
            status="interrupted",
            thread_status="idle",
            output={},
        )

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                (thread_id, retention, identity, stale, stale),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    execution_params,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (%s, %s, 'running', %s, %s, %s, '{}'::jsonb, NULL, NULL)
                """,
                (run_id, thread_id, identity, stale, stale),
            )

        owner_task = asyncio.create_task(cancelled_aegra_owner())
        monitor = await monitor_ready
        monitor.cancel()
        async with asyncio.timeout(5):
            await owner_cancelled.wait()

        while_draining = await reconcile_stale_guest_runs(batch_size=10)
        assert while_draining.liveness_skipped_runs == 0
        assert while_draining.reconciled_runs == 1
        assert while_draining.released_threads == 1
        assert not owner_task.done()
        assert not monitor.done()

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT recovered_at IS NOT NULL, drained_at
                FROM agent_guest_execution_quarantine
                WHERE
                    run_id = %s
                    AND thread_id = %s
                    AND identity = %s
                """,
                (run_id, thread_id, identity),
            )
            assert await cursor.fetchone() == (True, None)

        allow_owner_finalize.set()
        with pytest.raises(DBAPIError, match="recovered guest run is immutable"):
            await owner_task
        with pytest.raises(asyncio.CancelledError):
            await monitor
        monitor = None

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT
                    t.status,
                    r.status,
                    r.error_message,
                    quarantine.recovered_at IS NOT NULL,
                    quarantine.drained_at IS NOT NULL
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                JOIN agent_guest_execution_quarantine AS quarantine
                    ON quarantine.run_id = r.run_id
                    AND quarantine.thread_id = r.thread_id
                    AND quarantine.identity = r.user_id
                WHERE t.thread_id = %s AND r.run_id = %s
                """,
                (thread_id, run_id),
            )
            status_row = await cursor.fetchone()
            assert status_row[:2] == ("error", "error")
            assert status_row[2] == STALE_GUEST_RUN_ERROR
            assert status_row[3:] == (True, True)
            await cursor.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (
                    guest_execution_lock_key(
                        run_id=run_id,
                        thread_id=thread_id,
                        identity=identity,
                    ),
                ),
            )
            assert (await cursor.fetchone())[0] is True
    finally:
        allow_owner_finalize.set()
        if owner_task is not None and not owner_task.done():
            owner_task.cancel()
            with suppress(BaseException):
                await owner_task
        if monitor is not None and not monitor.done():
            monitor.cancel()
            with suppress(BaseException):
                await monitor
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_dedicated_fences_leave_size_two_orm_pool_for_finalizers():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    executions = tuple(
        (
            f"pool-two-run-{index}-{unique}",
            f"pool-two-thread-{index}-{unique}",
            f"anon:{uuid4()}",
        )
        for index in range(2)
    )
    begin_finalization = asyncio.Event()
    owner_tasks: list[asyncio.Task[None]] = []
    monitors: list[asyncio.Task[None]] = []
    owner_monitors_active = False

    async def fenced_finalizer(
        run_id: str,
        thread_id: str,
        identity: str,
        monitor_ready: asyncio.Future[asyncio.Task[None]],
    ) -> None:
        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        await begin_finalization.wait()
        await finalize_run(
            run_id,
            thread_id,
            status="success",
            thread_status="idle",
            output={"completed": True},
        )

    try:
        await migrate_database()
        await db_manager.initialize()
        await db_manager.get_engine().dispose()
        db_manager.engine = create_async_engine(
            settings.db.database_url,
            pool_size=2,
            max_overflow=0,
            pool_timeout=0.2,
            pool_pre_ping=True,
            connect_args={"prepared_statement_cache_size": 0},
        )
        aegra_orm.async_session_maker = None
        shared_pool = db_manager.get_engine().pool
        assert shared_pool.size() == 2
        assert shared_pool._max_overflow == 0
        assert shared_pool.timeout() == 0.2

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.executemany(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                [
                    (thread_id, retention, identity, stale, stale)
                    for _run_id, thread_id, identity in executions
                ],
            )
            await cursor.executemany(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (%s, %s, 'running', %s, %s, %s, NULL, NULL)
                """,
                [
                    (run_id, thread_id, identity, stale, stale)
                    for run_id, thread_id, identity in executions
                ],
            )

        monitor_futures = [
            asyncio.get_running_loop().create_future() for _execution in executions
        ]
        owner_tasks = [
            asyncio.create_task(
                fenced_finalizer(
                    run_id,
                    thread_id,
                    identity,
                    monitor_ready,
                )
            )
            for (run_id, thread_id, identity), monitor_ready in zip(
                executions,
                monitor_futures,
                strict=True,
            )
        ]
        monitors = list(await asyncio.gather(*monitor_futures))
        owner_monitors_active = True
        begin_finalization.set()

        async with asyncio.timeout(2):
            await asyncio.gather(*owner_tasks)
            await asyncio.gather(*monitors)
        owner_monitors_active = False

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT t.thread_id, t.status, r.run_id, r.status
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = ANY(%s)
                ORDER BY t.thread_id
                """,
                ([thread_id for _run_id, thread_id, _identity in executions],),
            )
            rows = await cursor.fetchall()
            assert {(row[1], row[3]) for row in rows} == {("idle", "success")}
            assert len(rows) == 2
            for run_id, thread_id, identity in executions:
                lock_key = guest_execution_lock_key(
                    run_id=run_id,
                    thread_id=thread_id,
                    identity=identity,
                )
                await cursor.execute(
                    "SELECT pg_try_advisory_lock(%s)",
                    (lock_key,),
                )
                assert (await cursor.fetchone())[0] is True
                await cursor.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (lock_key,),
                )
                assert (await cursor.fetchone())[0] is True
    finally:
        begin_finalization.set()
        for owner_task in owner_tasks:
            if not owner_task.done():
                owner_task.cancel()
        if owner_tasks:
            await asyncio.gather(*owner_tasks, return_exceptions=True)
        if owner_monitors_active:
            async with await psycopg.AsyncConnection.connect(
                POSTGRES_URL
            ) as connection:
                await connection.execute(
                    """
                    UPDATE runs
                    SET status = 'error', updated_at = CURRENT_TIMESTAMP
                    WHERE run_id = ANY(%s)
                    """,
                    ([run_id for run_id, _thread_id, _identity in executions],),
                )
                await connection.execute(
                    """
                    UPDATE thread
                    SET status = 'error', updated_at = CURRENT_TIMESTAMP
                    WHERE thread_id = ANY(%s)
                    """,
                    ([thread_id for _run_id, thread_id, _identity in executions],),
                )
            async with asyncio.timeout(5):
                await wait_for_guest_execution_fence_monitors()
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = ANY(%s)",
                ([thread_id for _run_id, thread_id, _identity in executions],),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_owner_failure_releases_active_fence_for_stale_recovery():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    run_id = f"failed-owner-run-{unique}"
    thread_id = f"failed-owner-thread-{unique}"
    identity = f"anon:{uuid4()}"
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    allow_owner_failure = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()
    owner_task = None
    monitor = None

    async def failed_aegra_owner():
        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        await allow_owner_failure.wait()
        raise RuntimeError("Aegra finalizer failed before terminal commit")

    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                (thread_id, retention, identity, stale, stale),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (%s, %s, 'running', %s, %s, %s, NULL, NULL)
                """,
                (run_id, thread_id, identity, stale, stale),
            )

        owner_task = asyncio.create_task(failed_aegra_owner())
        monitor = await monitor_ready
        lock_key = guest_execution_lock_key(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
            assert (await cursor.fetchone())[0] is False
        assert not owner_task.done()
        assert not monitor.done()

        allow_owner_failure.set()
        with pytest.raises(RuntimeError, match="finalizer failed"):
            await owner_task
        async with asyncio.timeout(2):
            await monitor
        monitor = None

        recovered = await reconcile_stale_guest_runs(batch_size=10)
        assert recovered.lock_acquired is True
        assert recovered.liveness_skipped_runs == 0
        assert recovered.reconciled_runs == 1
        assert recovered.released_threads == 1

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT t.status, r.status, r.error_message
                FROM thread AS t
                JOIN runs AS r ON r.thread_id = t.thread_id
                WHERE t.thread_id = %s AND r.run_id = %s
                """,
                (thread_id, run_id),
            )
            assert await cursor.fetchone() == (
                "error",
                "error",
                STALE_GUEST_RUN_ERROR,
            )
            await cursor.execute(
                """
                SELECT recovered_at IS NOT NULL, drained_at IS NOT NULL
                FROM agent_guest_execution_quarantine
                WHERE
                    run_id = %s
                    AND thread_id = %s
                    AND identity = %s
                """,
                (run_id, thread_id, identity),
            )
            assert await cursor.fetchone() == (True, True)
            await cursor.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
            assert (await cursor.fetchone())[0] is True
            await cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            assert (await cursor.fetchone())[0] is True
    finally:
        allow_owner_failure.set()
        if owner_task is not None and not owner_task.done():
            with suppress(RuntimeError):
                await owner_task
        if monitor is not None and not monitor.done():
            async with asyncio.timeout(5):
                await monitor
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


async def test_aegra_factory_keeps_the_guest_fence_until_terminal_commit(
    monkeypatch,
):
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url

    unique = uuid4().hex
    graph_id = f"guest-finalizer-{unique}"
    thread_id = f"finalizer-fenced-thread-{unique}"
    run_id = f"finalizer-fenced-run-{unique}"
    identity = f"anon:{uuid4()}"
    stale = datetime.now(UTC) - timedelta(minutes=40)
    retention = json.dumps(
        {
            "guest_expires_at": "2999-01-01T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )
    graph_factory_returned = asyncio.Event()
    allow_terminal_commit = asyncio.Event()
    owner_task: asyncio.Task[None] | None = None
    owner_monitor_active = False
    try:
        await migrate_database()
        await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                (thread_id, retention, identity, stale, stale),
            )
            await connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (%s, %s, 'running', %s, %s, %s, NULL, NULL)
                """,
                (run_id, thread_id, identity, stale, stale),
            )

        guest = User(identity=identity, permissions=["anon"])
        config = create_run_config(run_id, thread_id, guest)
        service = _factory_service(production_graph, graph_id=graph_id)
        model = ToolCapableFakeModel(
            responses=[AIMessage(content="provider-free guest factory proof")]
        )
        monkeypatch.setenv("GUEST_MODEL", "openai:gpt-5.6-luna")
        monkeypatch.setattr(
            "agent.graph._bounded_guest_model",
            lambda _model_spec, _safety_identifier: model,
        )
        lock_key = guest_execution_lock_key(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )

        async def aegra_owner() -> None:
            async with service.get_graph(
                graph_id,
                config=config,
                user=guest,
            ) as guest_graph:
                assert guest_graph is not None
            graph_factory_returned.set()
            await allow_terminal_commit.wait()
            async with await psycopg.AsyncConnection.connect(
                POSTGRES_URL
            ) as connection:
                await connection.execute(
                    """
                    UPDATE runs
                    SET status = 'success', updated_at = CURRENT_TIMESTAMP
                    WHERE run_id = %s AND thread_id = %s AND user_id = %s
                    """,
                    (run_id, thread_id, identity),
                )
                await connection.execute(
                    """
                    UPDATE thread
                    SET status = 'idle', updated_at = CURRENT_TIMESTAMP
                    WHERE thread_id = %s AND user_id = %s
                    """,
                    (thread_id, identity),
                )

        owner_task = asyncio.create_task(aegra_owner())
        async with asyncio.timeout(5):
            await graph_factory_returned.wait()
        owner_monitor_active = True

        during_finalization = await reconcile_stale_guest_runs(batch_size=10)
        assert during_finalization.liveness_skipped_runs == 1
        assert during_finalization.reconciled_runs == 0
        assert during_finalization.released_threads == 0

        allow_terminal_commit.set()
        async with asyncio.timeout(5):
            await owner_task
            await wait_for_guest_execution_fence_monitors()
        owner_monitor_active = False

        with pytest.raises(
            GuestExecutionFenceRejectedError,
            match="no longer active",
        ):
            async with service.get_graph(
                graph_id,
                config=config,
                user=guest,
            ):
                pass

        async with (
            await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
            assert (await cursor.fetchone())[0] is True
            await cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            assert (await cursor.fetchone())[0] is True
    finally:
        allow_terminal_commit.set()
        if owner_task is not None and not owner_task.done():
            owner_task.cancel()
            with suppress(BaseException):
                await owner_task
        if owner_monitor_active:
            async with await psycopg.AsyncConnection.connect(
                POSTGRES_URL
            ) as connection:
                await connection.execute(
                    """
                    UPDATE runs
                    SET status = 'error', updated_at = CURRENT_TIMESTAMP
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                await connection.execute(
                    """
                    UPDATE thread
                    SET status = 'error', updated_at = CURRENT_TIMESTAMP
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
            async with asyncio.timeout(5):
                await wait_for_guest_execution_fence_monitors()
        graph_factory.clear_factory_registry(graph_id)
        if db_manager.engine is None:
            await db_manager.initialize()
        async with await psycopg.AsyncConnection.connect(POSTGRES_URL) as connection:
            await connection.execute(
                "DELETE FROM thread WHERE thread_id = %s",
                (thread_id,),
            )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url
