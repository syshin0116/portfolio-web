"""Offline compatibility checks for the pinned Aegra runtime."""

import asyncio
import inspect
import json
import runpy
import socket
import time
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
import uvicorn
from aegra_api.core.orm import get_session
from aegra_api.core.sse import format_sse_message, get_sse_headers
from aegra_api.main import app
from aegra_api.services.event_streaming.capabilities import (
    _probe_runtime_symbols,
    get_v2_capabilities,
)
from aegra_api.services.event_streaming.native_stream import stream_native_v3_events
from aegra_api.services.event_streaming.protocol import build_event
from aegra_api.services.event_streaming.session import ThreadEventSession
from aegra_api.services.thread_state_service import ThreadStateService
from aegra_api.settings import settings
from aegra_api.utils.assistants import resolve_assistant_id
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from starlette.responses import JSONResponse

from agent import http as http_extension
from agent.auth import AGENT_AUTH_SECRET, TOKEN_AUDIENCE, TOKEN_ISSUER
from agent.graph import graph
from agent.http import GuestIngressGuard, GuestRunGuard, NativeThreadGuard
from agent.inspection import INSPECTION_EVENT_NAME

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
INSPECTION_FIXTURE = REPO_ROOT / "protocol" / "fixtures" / "inspection-events-v1.json"


def _canonical_inspection_payload() -> dict[str, object]:
    fixture = json.loads(INSPECTION_FIXTURE.read_text(encoding="utf-8"))
    return fixture["records"][0]["payload"]["params"]["data"]["payload"]


def _authorization(subject: str = "owner") -> dict[str, str]:
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


def _anonymous_authorization() -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": f"anon:{uuid4()}",
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + 300,
            "scope": "anon",
        },
        AGENT_AUTH_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_runtime_dependencies_are_the_spike_versions():
    assert {
        package: version(package)
        for package in (
            "aegra-api",
            "aegra-cli",
            "deepagents",
            "langchain",
            "langchain-core",
            "langgraph",
            "langgraph-checkpoint-postgres",
            "langgraph-sdk",
            "langsmith",
            "uvicorn",
        )
    } == {
        "aegra-api": "0.9.24",
        "aegra-cli": "0.9.24",
        "deepagents": "0.6.12",
        "langchain": "1.3.14",
        "langchain-core": "1.4.9",
        "langgraph": "1.2.9",
        "langgraph-checkpoint-postgres": "3.1.0",
        "langgraph-sdk": "0.4.2",
        "langsmith": "0.10.10",
        "uvicorn": "0.51.0",
    }
    assert (
        resolve_assistant_id("agent", {"agent": object()})
        == "fe096781-5601-53d2-b2f6-0d3403f7e9ca"
    )


def test_psycopg_family_is_the_verified_compatible_set():
    assert {
        package: version(package)
        for package in ("psycopg", "psycopg-binary", "psycopg-pool")
    } == {
        "psycopg": "3.3.4",
        "psycopg-binary": "3.3.4",
        "psycopg-pool": "3.3.1",
    }


def test_aegra_config_registers_the_compiled_graph():
    config = json.loads((REPO_ROOT / "aegra.json").read_text())

    assert config == {
        "dependencies": ["./agent/src"],
        "graphs": {"agent": "./agent/src/agent/graph.py:graph"},
        "auth": {
            "path": "agent.auth:auth",
            "disable_studio_auth": False,
        },
        "http": {
            "app": "agent.http:app",
            "enable_custom_route_auth": False,
        },
    }
    assert tuple(inspect.signature(graph).parameters) == ("config", "runtime")


def test_pinned_runtime_supports_aegra_v2_dialect(monkeypatch):
    monkeypatch.setattr(settings.event_streaming, "FF_V2_EVENT_STREAMING", True)
    _probe_runtime_symbols.cache_clear()

    capabilities = get_v2_capabilities()

    assert capabilities.ok
    assert capabilities.missing == ()
    route_paths = set(app.openapi()["paths"])
    assert "/threads/{thread_id}/stream/events" in route_paths
    assert "/threads/{thread_id}/commands" in route_paths
    assert "/threads/{thread_id}/stream" not in route_paths


async def test_custom_http_app_guard_wraps_native_v2_command_route(monkeypatch):
    async def busy(_thread_id: str, _user_id: str) -> tuple[bool, str]:
        return True, "busy"

    monkeypatch.setattr(http_extension, "_owned_or_new_thread_status", busy)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/native-guard-proof/commands",
            headers=_authorization(),
            json={
                "id": 1,
                "method": "run.start",
                "params": {"assistant_id": "agent"},
            },
        )

    assert any(
        middleware.cls is NativeThreadGuard for middleware in app.user_middleware
    )
    assert any(
        middleware.cls is GuestIngressGuard for middleware in app.user_middleware
    )
    assert any(middleware.cls is GuestRunGuard for middleware in app.user_middleware)
    assert [
        middleware.cls
        for middleware in app.user_middleware
        if middleware.cls in {GuestIngressGuard, GuestRunGuard, NativeThreadGuard}
    ] == [GuestIngressGuard, NativeThreadGuard, GuestRunGuard]
    guest_middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is GuestRunGuard
    )
    guest_ingress_middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is GuestIngressGuard
    )
    assert guest_middleware.kwargs == {"enforce_daily_budget": True}
    assert guest_ingress_middleware.kwargs == {}
    assert response.status_code == 409
    assert response.json() == {
        "error": "conflict",
        "message": "The thread already has an active run",
    }


async def test_guest_public_wire_projects_pinned_aegra_sse_frames(
    monkeypatch,
):
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")
    secret = "PINNED-AEGRA-REASONING-SENTINEL"
    unknown_custom_secret = "PINNED-AEGRA-UNKNOWN-CUSTOM-SENTINEL"
    request_body = b""
    events = [
        build_event(
            "messages",
            {
                "event": "message-start",
                "role": "ai",
                "id": "assistant-1",
            },
            seq=1,
            event_id="run-integration_event_1:0",
        ),
        build_event(
            "messages",
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "reasoning", "reasoning": secret},
            },
            seq=2,
            event_id="run-integration_event_2:0",
        ),
        build_event(
            "messages",
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {"type": "reasoning", "reasoning": secret},
            },
            seq=3,
            event_id="run-integration_event_3:0",
        ),
        build_event(
            "messages",
            {
                "event": "content-block-start",
                "index": 1,
                "content": {"type": "text", "text": "공개 답변"},
            },
            seq=4,
            event_id="run-integration_event_4:0",
        ),
        build_event(
            "messages",
            {
                "event": "content-block-finish",
                "index": 1,
                "content": {"type": "text", "text": "공개 답변"},
            },
            seq=5,
            event_id="run-integration_event_5:0",
        ),
        build_event(
            "messages",
            {"event": "message-finish"},
            seq=6,
            event_id="run-integration_event_6:0",
        ),
        build_event(
            "custom",
            {
                "name": INSPECTION_EVENT_NAME,
                "payload": _canonical_inspection_payload(),
            },
            seq=7,
            event_id="run-integration_event_7:0",
        ),
        build_event(
            "custom",
            {
                "name": "unreviewed.debug.event",
                "payload": {"private": unknown_custom_secret},
            },
            seq=8,
            event_id="run-integration_event_8:0",
        ),
    ]
    wire = "".join(
        format_sse_message(
            event["method"],
            event,
            str(event["seq"]),
        )
        for event in events
    ).encode()

    async def downstream(scope, receive, send):
        nonlocal request_body
        request_body = (await receive()).get("body", b"")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (key.lower().encode(), value.encode())
                    for key, value in get_sse_headers().items()
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": wire,
                "more_body": False,
            }
        )

    guarded = GuestRunGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=guarded),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/guest-thread/stream/events",
            headers=_anonymous_authorization(),
            json={"channels": ["messages", "custom"]},
        )

    assert response.status_code == 200
    assert json.loads(request_body) == {
        "channels": ["messages", "custom"],
        "depth": 0,
        "namespaces": [[]],
    }
    assert secret.encode() not in response.content
    assert unknown_custom_secret.encode() not in response.content
    assert "공개 답변".encode() in response.content
    assert b'"reasoning"' not in response.content
    assert b'"index":0' in response.content
    assert b'"index":1' not in response.content
    assert INSPECTION_EVENT_NAME.encode() in response.content


async def test_guest_sse_frame_budget_contains_a_max_contract_inspection_event(
    monkeypatch,
):
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")
    payload = deepcopy(_canonical_inspection_payload())
    source = payload["sources"][0]
    payload["hit_count"] = 50
    payload["corpus_document_count"] = 50
    payload["sources_truncated"] = False
    payload["sources"] = []
    for rank in range(1, 51):
        expanded = deepcopy(source)
        expanded["doc_id"] = f"AI/{'a' * 705}-{rank}.md"
        expanded["rank"] = rank
        expanded["title"] = "T" * 300
        payload["sources"].append(expanded)
    payload["stages"][0]["application"]["output_count"] = 50
    canonical_payload = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    event = build_event(
        "custom",
        {
            "name": INSPECTION_EVENT_NAME,
            "payload": payload,
        },
        seq=1,
        event_id="run-boundary_event_1:0",
    )
    wire = format_sse_message("custom", event, "1").encode()
    assert len(canonical_payload) <= 65_536
    assert len(wire) > 65_536
    assert len(wire) < 512 * 1_024

    async def downstream(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (key.lower().encode(), value.encode())
                    for key, value in get_sse_headers().items()
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": wire,
                "more_body": False,
            }
        )

    guarded = GuestRunGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=guarded),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/guest-thread/stream/events",
            headers=_anonymous_authorization(),
            json={"channels": ["custom"]},
        )

    assert response.status_code == 200
    assert INSPECTION_EVENT_NAME.encode() in response.content
    assert len(response.content) > 65_536


@pytest.mark.filterwarnings(
    f"ignore:The v3 streaming protocol on Pregel is experimental:{LangChainBetaWarning.__module__}.{LangChainBetaWarning.__name__}"
)
async def test_guest_public_wire_projects_pinned_aegra_thread_state(
    monkeypatch,
):
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")
    fixture = runpy.run_path(FIXTURE_ROOT / "aegra_graph.py")
    fixture_graph = fixture["graph"]
    private_state_sentinel = fixture["PRIVATE_STATE_SENTINEL"]
    runtime_graph = fixture_graph.copy(
        update={
            "checkpointer": InMemorySaver(),
            "store": InMemoryStore(),
        }
    )
    config = {"configurable": {"thread_id": "guest-state-projection"}}
    raw_events = [
        event
        async for event in stream_native_v3_events(
            graph=runtime_graph,
            input_data={"messages": [HumanMessage(content="fixture request")]},
            config=config,
        )
    ]

    async def no_runs():
        return []

    root_session = ThreadEventSession(
        "guest-state-projection",
        channels={"input", "lifecycle"},
        list_run_ids=no_runs,
        namespaces=[[]],
        depth=0,
    )
    root_events = [
        projected
        for index, raw_event in enumerate(raw_events)
        for projected in root_session._project(  # noqa: SLF001 - pinned compatibility
            f"fixture-{index}",
            raw_event,
        )
    ]
    root_events.extend(
        root_session._project(  # noqa: SLF001 - pinned compatibility
            "fixture-end",
            ("end", {"status": "interrupted"}),
        )
    )
    assert any(
        event["method"] == "lifecycle"
        and event["params"]["data"]["event"] == "interrupted"
        for event in root_events
    )
    # Aegra 0.9.24 records the nested copy of this interrupt before namespace
    # filtering and then suppresses the root copy as a duplicate.
    assert not any(event["method"] == "input.requested" for event in root_events)

    snapshot = await runtime_graph.aget_state(config)
    native_state = ThreadStateService().convert_snapshot_to_thread_state(
        snapshot,
        "guest-state-projection",
    )

    async def downstream(scope, receive, send):
        await JSONResponse(native_state.model_dump(mode="json"))(
            scope,
            receive,
            send,
        )

    guarded = GuestRunGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=guarded),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/threads/guest-state-projection/state",
            headers=_anonymous_authorization(),
        )

    assert response.status_code == 200
    assert private_state_sentinel.encode() not in response.content
    assert response.json()["values"]["messages"][0]["content"] == "fixture request"
    assert response.json()["tasks"] == []
    assert response.json()["metadata"] == {}
    assert response.json()["interrupts"][0]["value"] == {
        "kind": "approval",
        "prompt": "Continue the deterministic Aegra fixture?",
        "schema": "syshin.rag.interrupt.v1",
        "title": "Deterministic fixture approval",
    }


async def test_v2_stream_and_commands_deny_missing_or_forged_auth():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for headers in ({}, {"Authorization": "Bearer forged"}):
            stream = await client.post(
                "/threads/thread-1/stream/events",
                headers=headers,
                json={"channels": ["messages"]},
            )
            command = await client.post(
                "/threads/thread-1/commands",
                headers=headers,
                json={
                    "id": 1,
                    "method": "run.start",
                    "params": {"assistant_id": "agent"},
                },
            )

            assert stream.status_code == 401
            assert command.status_code == 401


async def test_anonymous_agent_gate_is_independent_and_hides_nonpublic_routes(
    monkeypatch,
):
    headers = _anonymous_authorization()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "false")
        disabled = await client.post(
            "/threads/thread-1/commands",
            headers=headers,
            json={
                "id": 1,
                "method": "run.start",
                "params": {"assistant_id": "agent"},
            },
        )

        monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")
        hidden = await client.post(
            "/assistants/search",
            headers=headers,
            json={},
        )

    assert disabled.status_code == 401
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "Not Found"}


async def test_native_thread_delete_is_denied_and_checkpoint_is_preserved():
    fixture_graph = runpy.run_path(FIXTURE_ROOT / "aegra_graph.py")["graph"]
    checkpointer = InMemorySaver()
    runtime_graph = fixture_graph.copy(update={"checkpointer": checkpointer})
    config = {"configurable": {"thread_id": "delete-disabled-proof"}}
    await runtime_graph.ainvoke(
        {"messages": [HumanMessage(content="persist before denied delete")]},
        config,
    )
    before = await checkpointer.aget_tuple(config)
    assert before is not None

    async def unused_session():
        yield object()

    app.dependency_overrides[get_session] = unused_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.delete(
                "/threads/delete-disabled-proof",
                headers=_authorization(),
            )
    finally:
        app.dependency_overrides.pop(get_session, None)

    after = await checkpointer.aget_tuple(config)
    assert response.status_code == 403
    assert response.json() == {
        "error": "forbidden",
        "message": "Forbidden",
        "details": None,
    }
    assert after == before


async def test_health_routes_are_not_globally_authenticated():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        live = await client.get("/live")
        ready = await client.get("/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 503


async def test_uvicorn_serves_and_stops_the_aegra_app():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(128)
    host, port = server_socket.getsockname()
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    server_task = asyncio.create_task(server.serve(sockets=[server_socket]))

    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            response = await client.get("/info")

        assert response.status_code == 200
        assert response.json()["version"] == "0.9.24"
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=5)
        server_socket.close()

    assert server_task.done()


@pytest.mark.filterwarnings(
    f"ignore:The v3 streaming protocol on Pregel is experimental:{LangChainBetaWarning.__module__}.{LangChainBetaWarning.__name__}"
)
async def test_native_stream_fixture_covers_tools_nested_interrupt_and_content_blocks():
    fixture_graph = runpy.run_path(FIXTURE_ROOT / "aegra_graph.py")["graph"]
    runtime_graph = fixture_graph.copy(
        update={
            "checkpointer": InMemorySaver(),
            "store": InMemoryStore(),
        }
    )
    config = {"configurable": {"thread_id": "deterministic-runtime-test"}}

    first_events = [
        event
        async for event in stream_native_v3_events(
            graph=runtime_graph,
            input_data={"messages": [HumanMessage(content="fixture request")]},
            config=config,
        )
    ]

    tool_events = [
        event["params"]["data"]["event"]
        for method, event in first_events
        if method == "tools"
    ]
    namespaces = {
        tuple(event["params"]["namespace"]) for _method, event in first_events
    }
    assert tool_events == ["tool-started", "tool-finished"]
    assert any(
        namespace and namespace[0].startswith("nested_subgraph:")
        for namespace in namespaces
    )
    assert any(event["params"].get("interrupts") for _method, event in first_events)
    inspection_events = [
        event
        for method, event in first_events
        if method == f"custom:{INSPECTION_EVENT_NAME}"
    ]
    assert len(inspection_events) == 1
    assert inspection_events[0]["params"]["data"] == _canonical_inspection_payload()

    resumed_events = [
        event
        async for event in stream_native_v3_events(
            graph=runtime_graph,
            input_data=Command(resume="approved"),
            config=config,
        )
    ]
    message_events = [
        event["params"]["data"]
        for method, event in resumed_events
        if method == "messages"
    ]
    assert message_events[0]["event"] == "message-start"
    assert any(
        event["event"] == "content-block-delta"
        and event["delta"]["type"] == "text-delta"
        for event in message_events
    )
    assert message_events[-1]["event"] == "message-finish"

    snapshot = await runtime_graph.aget_state(config)
    assert not snapshot.interrupts
    assert snapshot.values["nested_result"] == "nested-ok"
    assert snapshot.values["approval"] == "approved"
    assert any(
        isinstance(message, ToolMessage) and message.content == "fixture-result:aegra"
        for message in snapshot.values["messages"]
    )
    assert snapshot.values["messages"][-1].text == "fixture-complete"
