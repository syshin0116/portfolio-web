"""Fail-closed tests for the public anonymous Agent Protocol boundary."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent import http as http_extension
from agent.auth import (
    AGENT_AUTH_SECRET,
    ANONYMOUS_PERMISSION,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
)
from agent.guest_budget import GuestDailyBudgetExhaustedError
from agent.http import (
    GuestRunGuard,
    GuestStreamLimitError,
)
from agent.maintenance import GUEST_RETENTION_POLICY

_NONCE = "123e4567-e89b-42d3-a456-426614174000"


@pytest.fixture(autouse=True)
def _enable_guest_agent(monkeypatch):
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")
    monkeypatch.setenv("GUEST_MODEL", "anthropic:claude-haiku-4-5")
    monkeypatch.setenv("GUEST_DAILY_BUDGET_MICRO_USD", "500000")
    monkeypatch.setenv("GUEST_RUN_RESERVATION_MICRO_USD", "25000")


def _token_headers(
    subject: str,
    *,
    scope: str = ANONYMOUS_PERMISSION,
    ttl_seconds: int = 300,
) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": subject,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + ttl_seconds,
            "scope": scope,
        },
        AGENT_AUTH_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _guest_headers(subject: str | None = None) -> dict[str, str]:
    return _token_headers(subject or f"anon:{uuid4()}")


def _owner_headers(subject: str = "owner") -> dict[str, str]:
    return _token_headers(subject, scope="admin", ttl_seconds=900)


async def _request_body(receive) -> bytes:
    parts: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        parts.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(parts)


def _capturing_app(records: list[dict[str, Any]]):
    async def app(scope, receive, send):
        records.append(
            {
                "body": await _request_body(receive),
                "method": scope["method"],
                "path": scope["path"],
                "query": scope.get("query_string", b""),
            }
        )
        await JSONResponse({"ok": True})(scope, receive, send)

    return app


def _run_command(
    *,
    nonce: str = _NONCE,
    input_content: Any = "공개 RAG를 테스트해줘",
) -> dict[str, Any]:
    metadata = {"syshin_ui_submit_nonce": nonce}
    return {
        "id": 7,
        "method": "run.start",
        "params": {
            "assistant_id": "agent",
            "config": {"metadata": metadata.copy()},
            "input": {
                "messages": [
                    {
                        "content": input_content,
                        "id": "guest-message-1",
                        "role": "user",
                    }
                ]
            },
            "metadata": metadata,
        },
    }


def _input_respond_command(
    *,
    nonce: str = _NONCE,
) -> dict[str, Any]:
    metadata = {"syshin_ui_submit_nonce": nonce}
    return {
        "id": 8,
        "method": "input.respond",
        "params": {
            "config": {"metadata": metadata.copy()},
            "interrupt_id": "interrupt-1",
            "metadata": metadata,
            "namespace": ["nested-agent:task-1"],
            "response": "approve",
        },
    }


async def test_disabled_gate_leaves_rejection_to_the_registered_aegra_auth(
    monkeypatch,
):
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "false")
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(_capturing_app(records))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/guest-thread/commands",
            headers=_guest_headers(),
            json=_run_command(),
        )

    assert response.status_code == 200
    assert len(records) == 1
    assert json.loads(records[0]["body"]) == _run_command()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/store/items"),
        ("POST", "/assistants/search"),
        ("POST", "/runs"),
        ("POST", "/threads/thread-1/state"),
        ("DELETE", "/threads/thread-1"),
        ("GET", "/threads/thread-1/stream"),
    ],
    ids=[
        "store",
        "assistants",
        "legacy-run",
        "state-mutation",
        "delete",
        "legacy-stream",
    ],
)
async def test_guest_route_allowlist_hides_every_other_surface(method, path):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await JSONResponse({"ok": True})(scope, receive, send)

    app = GuestRunGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.request(
            method,
            path,
            headers=_guest_headers(),
            json={} if method == "POST" else None,
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert not called


async def test_owner_requests_reach_downstream_byte_for_byte():
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(_capturing_app(records))
    body = b'{"model":"owner-controlled-by-server-contract","duplicate":1}'

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/assistants/search?limit=7",
            headers={
                **_owner_headers(),
                "Content-Type": "application/json",
            },
            content=body,
        )

    assert response.status_code == 200
    assert records == [
        {
            "body": body,
            "method": "POST",
            "path": "/assistants/search",
            "query": b"limit=7",
        }
    ]


async def test_thread_create_is_canonicalized_and_receives_server_expiry():
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(
        _capturing_app(records),
        wall_clock=lambda: 0.0,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads",
            headers=_guest_headers(),
            json={
                "if_exists": "do_nothing",
                "metadata": {
                    "archived": False,
                    "graph_id": "agent",
                    "title": "새 대화",
                    "title_status": "pending",
                },
                "thread_id": "guest-thread-1",
            },
        )

    assert response.status_code == 200
    assert json.loads(records[0]["body"]) == {
        "if_exists": "do_nothing",
        "metadata": {
            "archived": False,
            "graph_id": "agent",
            "guest_expires_at": "1970-01-15T00:00:00Z",
            "guest_retention_policy": GUEST_RETENTION_POLICY,
            "title": "새 대화",
            "title_status": "pending",
        },
        "thread_id": "guest-thread-1",
    }


@pytest.mark.parametrize(
    "body",
    [
        b'{"if_exists":"do_nothing","metadata":{},"thread_id":"a","thread_id":"b"}',
        b'{"if_exists":"raise","metadata":{},"thread_id":"guest-thread"}',
        b'{"if_exists":"do_nothing","metadata":{"user_id":"owner"},"thread_id":"guest-thread"}',
        b'{"if_exists":"do_nothing","metadata":{},"thread_id":"../escape"}',
    ],
    ids=["duplicate-key", "unsafe-upsert", "server-metadata", "unsafe-id"],
)
async def test_thread_create_rejects_ambiguous_or_server_owned_fields(body):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await JSONResponse({"ok": True})(scope, receive, send)

    app = GuestRunGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads",
            headers={
                **_guest_headers(),
                "Content-Type": "application/json",
            },
            content=body,
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_argument"
    assert not called


async def test_run_start_is_rebuilt_from_the_public_wire_contract():
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(_capturing_app(records))
    command = _run_command()
    command["params"]["multitaskStrategy"] = "interrupt"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/guest-thread/commands",
            headers=_guest_headers(),
            json=command,
        )

    assert response.status_code == 200
    assert json.loads(records[0]["body"]) == {
        **_run_command(),
        "params": {
            **_run_command()["params"],
            "multitask_strategy": "reject",
        },
    }


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("configurable", {"thread_id": "forged"}),
        ("model", "anthropic:expensive"),
        ("quickjs", True),
        ("capability", "admin"),
    ],
)
async def test_run_start_rejects_client_capability_or_model_overrides(
    location,
    value,
):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await JSONResponse({"ok": True})(scope, receive, send)

    command = _run_command()
    command["params"]["config"][location] = value
    app = GuestRunGuard(downstream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/threads/guest-thread/commands",
            headers=_guest_headers(),
            json=command,
        )

    assert response.status_code == 400
    assert not called


async def test_per_identity_rate_limit_refills_without_resetting_global_state():
    now = [0.0]
    records: list[dict[str, Any]] = []
    headers = _guest_headers()
    app = GuestRunGuard(
        _capturing_app(records),
        clock=lambda: now[0],
        identity_capacity=2,
        identity_window_seconds=60,
        global_capacity=10,
        global_window_seconds=60,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_run_command(),
        )
        second = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_run_command(),
        )
        rejected = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_run_command(),
        )
        now[0] = 30.0
        refilled = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_run_command(),
        )

    assert [first.status_code, second.status_code, rejected.status_code] == [
        200,
        200,
        429,
    ]
    assert rejected.headers["retry-after"] == "30"
    assert rejected.headers["cache-control"] == "no-store"
    assert refilled.status_code == 200
    assert len(records) == 3


async def test_global_rate_limit_survives_guest_identity_rotation():
    app = GuestRunGuard(
        _capturing_app([]),
        clock=lambda: 0.0,
        identity_capacity=4,
        identity_window_seconds=60,
        global_capacity=2,
        global_window_seconds=60,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        responses = [
            await client.post(
                "/threads/guest-thread/commands",
                headers=_guest_headers(),
                json=_run_command(),
            )
            for _index in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[-1].headers["retry-after"] == "30"


async def test_identity_bucket_cardinality_fails_closed():
    first_subject = f"anon:{UUID(int=1, version=4)}"
    second_subject = f"anon:{UUID(int=2, version=4)}"
    app = GuestRunGuard(
        _capturing_app([]),
        clock=lambda: 0.0,
        max_identities=1,
        global_capacity=10,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/threads/guest-thread/commands",
            headers=_guest_headers(first_subject),
            json=_run_command(),
        )
        second = await client.post(
            "/threads/guest-thread/commands",
            headers=_guest_headers(second_subject),
            json=_run_command(),
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


async def test_native_stream_filters_allow_only_reviewed_public_channels():
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(_capturing_app(records))
    headers = _guest_headers()
    accepted = [
        {
            "channels": ["messages", "lifecycle", "input", "tools", "custom"],
            "depth": 0,
            "namespaces": [[]],
        },
        {"channels": ["lifecycle", "input"]},
    ]
    rejected = [
        {"channels": ["values"]},
        {"channels": ["updates"]},
        {"channels": ["messages"], "depth": 1},
        {"channels": ["messages"], "namespaces": []},
        {"channels": ["messages", "messages"]},
    ]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        accepted_responses = [
            await client.post(
                "/threads/guest-thread/stream/events",
                headers=headers,
                json=body,
            )
            for body in accepted
        ]
        rejected_responses = [
            await client.post(
                "/threads/guest-thread/stream/events",
                headers=headers,
                json=body,
            )
            for body in rejected
        ]

    assert [response.status_code for response in accepted_responses] == [200, 200]
    assert all(response.status_code == 400 for response in rejected_responses)
    assert [json.loads(record["body"]) for record in records] == accepted


async def test_guest_stream_response_has_chunk_and_total_byte_limits():
    async def oversized_stream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"x" * (64 * 1024 + 1),
                "more_body": True,
            }
        )

    app = GuestRunGuard(oversized_stream)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        with pytest.raises(GuestStreamLimitError):
            await client.post(
                "/threads/guest-thread/stream/events",
                headers=_guest_headers(),
                json={"channels": ["messages"]},
            )


async def test_declared_or_actual_oversized_request_is_rejected_before_aegra():
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await JSONResponse({"ok": True})(scope, receive, send)

    app = GuestRunGuard(downstream)
    headers = {
        **_guest_headers(),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        declared = await client.post(
            "/threads/guest-thread/commands",
            headers={**headers, "Content-Length": str(32 * 1024 + 1)},
            content=b"{}",
        )
        actual = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            content=b" " * (32 * 1024 + 1),
        )

    assert declared.status_code == 400
    assert actual.status_code == 400
    assert not called


async def test_input_respond_accepts_one_exact_resume_and_rejects_state_mutation():
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(_capturing_app(records))
    headers = _guest_headers()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        accepted = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_input_respond_command(),
        )
        for forbidden in ("goto", "update", "responses"):
            command = _input_respond_command()
            command["params"][forbidden] = [] if forbidden != "update" else {}
            rejected = await client.post(
                "/threads/guest-thread/commands",
                headers=headers,
                json=command,
            )
            assert rejected.status_code == 400

    assert accepted.status_code == 200
    assert json.loads(records[0]["body"]) == _input_respond_command()
    assert len(records) == 1


async def test_input_respond_consumes_the_same_paid_run_rate_limit():
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(
        _capturing_app(records),
        clock=lambda: 0.0,
        identity_capacity=1,
        identity_window_seconds=60,
        global_capacity=10,
    )
    headers = _guest_headers()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resumed = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_input_respond_command(),
        )
        bypass_attempt = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_input_respond_command(),
        )

    assert resumed.status_code == 200
    assert bypass_attempt.status_code == 429
    assert len(records) == 1


async def test_paid_commands_reserve_the_durable_daily_budget():
    class Ledger:
        def __init__(self):
            self.calls = 0

        async def reserve_run(self):
            self.calls += 1

    records: list[dict[str, Any]] = []
    ledger = Ledger()
    app = GuestRunGuard(
        _capturing_app(records),
        spend_ledger=ledger,
        global_capacity=10,
    )
    headers = _guest_headers()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        started = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_run_command(),
        )
        resumed = await client.post(
            "/threads/guest-thread/commands",
            headers=headers,
            json=_input_respond_command(),
        )
        read = await client.get(
            "/threads/guest-thread",
            headers=headers,
        )

    assert [started.status_code, resumed.status_code, read.status_code] == [
        200,
        200,
        200,
    ]
    assert ledger.calls == 2
    assert len(records) == 3


async def test_exhausted_or_unavailable_daily_budget_fails_closed():
    class ExhaustedLedger:
        async def reserve_run(self):
            raise GuestDailyBudgetExhaustedError

    class BrokenLedger:
        async def reserve_run(self):
            raise RuntimeError("database details must not cross the boundary")

    async def request(ledger):
        app = GuestRunGuard(
            _capturing_app([]),
            spend_ledger=ledger,
            wall_clock=lambda: 0.0,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/threads/guest-thread/commands",
                headers=_guest_headers(),
                json=_run_command(),
            )

    exhausted = await request(ExhaustedLedger())
    unavailable = await request(BrokenLedger())

    assert exhausted.status_code == 429
    assert exhausted.json() == {
        "error": "daily_budget_exhausted",
        "message": "Guest daily run budget is exhausted",
    }
    assert exhausted.headers["retry-after"] == "86400"
    assert exhausted.headers["cache-control"] == "no-store"
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "error": "service_unavailable",
        "message": "Guest run budget is unavailable",
    }
    assert unavailable.headers["retry-after"] == "60"
    assert unavailable.headers["cache-control"] == "no-store"


async def test_admin_gc_route_requires_owner_admin_and_returns_bounded_counts(
    monkeypatch,
):
    async def collect():
        return type(
            "Result",
            (),
            {
                "lock_acquired": True,
                "deleted_threads": 3,
                "batch_limit": 1000,
            },
        )()

    monkeypatch.setattr(http_extension, "collect_expired_guest_threads", collect)

    def request(headers):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/admin/gc",
                "headers": [
                    (key.lower().encode("latin-1"), value.encode("latin-1"))
                    for key, value in headers.items()
                ],
            }
        )

    missing = await http_extension.collect_guest_threads(request({}))
    guest = await http_extension.collect_guest_threads(request(_guest_headers()))
    owner = await http_extension.collect_guest_threads(request(_owner_headers()))

    assert missing.status_code == 401
    assert guest.status_code == 403
    assert owner.status_code == 200
    assert json.loads(owner.body) == {
        "lock_acquired": True,
        "deleted_threads": 3,
        "batch_limit": 1000,
    }
    assert owner.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        (
            "GET",
            "/threads/guest-thread/runs?limit=10&offset=0",
            200,
        ),
        (
            "GET",
            "/threads/guest-thread/runs?limit=100&offset=0",
            404,
        ),
        (
            "POST",
            "/threads/guest-thread/runs/run-1/cancel?action=interrupt&wait=0",
            200,
        ),
        (
            "POST",
            "/threads/guest-thread/runs/run-1/cancel?action=rollback&wait=0",
            404,
        ),
    ],
)
async def test_guest_query_contract_is_exact(method, path, expected):
    records: list[dict[str, Any]] = []
    app = GuestRunGuard(_capturing_app(records))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.request(
            method,
            path,
            headers=_guest_headers(),
        )

    assert response.status_code == expected
    assert len(records) == (1 if expected == 200 else 0)
