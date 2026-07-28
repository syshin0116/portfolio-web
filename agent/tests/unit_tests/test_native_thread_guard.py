"""Native APv2 single-process mutation guard tests."""

from __future__ import annotations

import asyncio
import time

import httpx
import jwt
import pytest
from starlette.responses import JSONResponse

from agent import http as http_extension
from agent.auth import AGENT_AUTH_SECRET, TOKEN_AUDIENCE, TOKEN_ISSUER
from agent.http import NativeThreadGuard


async def _ok_app(scope, receive, send):
    await JSONResponse({"ok": True})(scope, receive, send)


def _authorization(subject="owner"):
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


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/threads/thread-1/runs"),
        ("POST", "/threads/thread-1/runs/stream"),
        ("POST", "/threads/thread-1/runs/wait"),
        ("POST", "/threads/thread-1/state"),
        ("POST", "/runs"),
        ("POST", "/runs/stream"),
        ("POST", "/runs/wait"),
        ("POST", "/runs/crons"),
        ("POST", "/threads/thread-1/runs/crons"),
        ("PATCH", "/runs/crons/cron-1"),
    ],
    ids=[
        "thread-run",
        "thread-stream",
        "thread-wait",
        "thread-state",
        "stateless-run",
        "stateless-stream",
        "stateless-wait",
        "stateless-cron",
        "thread-cron",
        "enable-cron",
    ],
)
async def test_legacy_model_or_state_mutation_is_hidden_before_downstream(
    method,
    path,
):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await _ok_app(scope, receive, send)

    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.request(
            method,
            path,
            headers=_authorization(),
            json={},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert not called


async def test_hidden_legacy_mutation_does_not_reveal_thread_ownership():
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await _ok_app(scope, receive, send)

    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        owner = await client.post(
            "/threads/shared-thread/runs",
            headers=_authorization("alice"),
            json={},
        )
        foreign = await client.post(
            "/threads/shared-thread/runs",
            headers=_authorization("bob"),
            json={},
        )
        anonymous = await client.post("/threads/shared-thread/runs", json={})

    assert [
        (response.status_code, response.json())
        for response in (owner, foreign, anonymous)
    ] == [
        (404, {"detail": "Not Found"}),
        (404, {"detail": "Not Found"}),
        (404, {"detail": "Not Found"}),
    ]
    assert not called


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/live"),
        ("GET", "/threads/thread-1/runs"),
        ("POST", "/threads/search"),
        ("POST", "/threads/thread-1/history"),
        ("POST", "/threads/thread-1/state/checkpoint"),
        ("POST", "/runs/crons/search"),
        ("POST", "/runs/crons/count"),
        ("POST", "/threads/thread-1/runs/run-1/cancel"),
        ("DELETE", "/runs/crons/cron-1"),
    ],
    ids=[
        "health",
        "list-runs",
        "search-threads",
        "thread-history",
        "checkpoint-read",
        "search-crons",
        "count-crons",
        "cancel-run",
        "delete-cron",
    ],
)
async def test_health_read_and_cleanup_compatibility_reaches_downstream(method, path):
    received = []

    async def downstream(scope, receive, send):
        received.append((scope["method"], scope["path"]))
        await _ok_app(scope, receive, send)

    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.request(method, path, json={})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert received == [(method, path)]


async def test_update_and_goto_are_rejected_instead_of_silently_ignored(
    monkeypatch,
):
    async def new_thread(_thread_id, _user_id):
        return True, None

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        new_thread,
    )
    app = NativeThreadGuard(_ok_app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for unsupported in ("update", "goto"):
            response = await client.post(
                "/threads/thread-1/commands",
                headers=_authorization(),
                json={
                    "id": 7,
                    "method": "input.respond",
                    "params": {"response": "yes", unsupported: {}},
                },
            )

            assert response.status_code == 200
            assert response.json()["type"] == "error"
            assert response.json()["error"] == "invalid_argument"
            assert unsupported in response.json()["message"]


async def test_owner_resume_preserves_native_interrupt_validation(monkeypatch):
    received = None

    async def interrupted(_thread_id, _user_id):
        return True, "interrupted"

    async def guest_only_validation(_thread_id, _user):
        raise AssertionError("owner resumes must remain Aegra's responsibility")

    async def downstream(scope, receive, send):
        nonlocal received
        received = (await receive())["body"]
        await _ok_app(scope, receive, send)

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        interrupted,
    )
    monkeypatch.setattr(
        http_extension,
        "_current_guest_root_interrupt_id",
        guest_only_validation,
    )
    raw_command = (
        b'{ "params": {"response":"owner-native-response", "namespace":[], '
        b'"interrupt_id":"ffffffffffffffffffffffffffffffff"}, '
        b'"method":"input.respond", "id":9 }'
    )
    app = NativeThreadGuard(downstream)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers={
                **_authorization(),
                "Content-Type": "application/json",
            },
            content=raw_command,
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert received == raw_command


async def test_same_process_same_thread_cross_owner_creation_race_is_rejected(
    monkeypatch,
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_app(scope, receive, send):
        started.set()
        await release.wait()
        await _ok_app(scope, receive, send)

    async def new_thread(_thread_id, _user_id):
        return True, None

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        new_thread,
    )
    app = NativeThreadGuard(blocking_app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = asyncio.create_task(
            client.post(
                "/threads/shared-id/commands",
                headers=_authorization("alice"),
                json={"id": 1, "method": "run.start", "params": {}},
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        try:
            second = await asyncio.wait_for(
                client.post(
                    "/threads/shared-id/commands",
                    headers=_authorization("bob"),
                    json={"id": 2, "method": "run.start", "params": {}},
                ),
                timeout=1,
            )
        finally:
            release.set()
        first_response = await asyncio.wait_for(first, timeout=1)

    assert first_response.status_code == 200
    assert second.status_code == 404
    assert second.json() == {"detail": "Not Found"}


async def test_new_run_is_rejected_while_aegra_thread_is_busy(monkeypatch):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await _ok_app(scope, receive, send)

    async def busy(_thread_id, _user_id):
        return True, "busy"

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        busy,
    )
    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers=_authorization(),
            json={"id": 1, "method": "run.start", "params": {}},
        )

    assert response.status_code == 409
    assert not called


async def test_non_run_command_reaches_native_route_with_body_intact():
    received = None

    async def downstream(scope, receive, send):
        nonlocal received
        message = await receive()
        received = message["body"]
        await _ok_app(scope, receive, send)

    body = b'{"id":3,"method":"thread.inspect","params":{"depth":2}}'
    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers=_authorization(),
            content=body,
        )

    assert response.status_code == 200
    assert received == body


async def test_malformed_command_body_is_left_for_native_validation():
    received = None

    async def downstream(scope, receive, send):
        nonlocal received
        message = await receive()
        received = message["body"]
        await JSONResponse(
            {"error": "native-validation"},
            status_code=422,
        )(scope, receive, send)

    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers=_authorization(),
            content=b"{not-json",
        )

    assert response.status_code == 422
    assert response.json() == {"error": "native-validation"}
    assert received == b"{not-json"


async def test_command_body_above_bound_is_rejected_before_native_route():
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await _ok_app(scope, receive, send)

    app = NativeThreadGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers=_authorization(),
            content=b"x" * (64 * 1024 + 1),
        )

    assert response.status_code == 413
    assert response.json() == {
        "error": "invalid_argument",
        "message": "Command body is too large",
    }
    assert not called


async def test_guard_capacity_is_fail_closed_for_run_mutation(monkeypatch):
    called = False

    async def new_thread(_thread_id, _user_id):
        return True, None

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await _ok_app(scope, receive, send)

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        new_thread,
    )
    app = NativeThreadGuard(downstream, max_active_threads=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers=_authorization(),
            json={"id": 1, "method": "run.start", "params": {}},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": "service_unavailable",
        "message": "The thread mutation guard is at capacity",
    }
    assert not called


async def test_invalid_auth_bypasses_guard_database_checks(monkeypatch):
    async def forbidden_status(_thread_id, _user_id):
        raise AssertionError("unauthenticated requests must not access the database")

    async def native_auth_failure(scope, receive, send):
        await JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )(scope, receive, send)

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        forbidden_status,
    )
    app = NativeThreadGuard(native_auth_failure)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/thread-1/commands",
            headers={"Authorization": "Bearer forged"},
            json={"id": 1, "method": "run.start", "params": {}},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


async def test_foreign_owned_busy_thread_preserves_native_not_found(monkeypatch):
    seen = {}

    async def foreign_thread(thread_id, user_id):
        seen["thread_id"] = thread_id
        seen["user_id"] = user_id
        return False, None

    async def native_not_found(scope, receive, send):
        await JSONResponse(
            {"detail": "Thread not found"},
            status_code=404,
        )(scope, receive, send)

    monkeypatch.setattr(
        http_extension,
        "_owned_or_new_thread_status",
        foreign_thread,
    )
    app = NativeThreadGuard(native_not_found, max_active_threads=0)
    app._active.add("alice-thread")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/alice-thread/commands",
            headers=_authorization("bob"),
            json={
                "id": 1,
                "method": "run.start",
                "params": {"assistant_id": "agent"},
            },
        )

    assert seen == {"thread_id": "alice-thread", "user_id": "bob"}
    assert response.status_code == 404
    assert response.json() == {"detail": "Thread not found"}
