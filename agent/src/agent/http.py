"""Minimal Aegra HTTP extension for native APv2 owner-preview traffic."""

from __future__ import annotations

import json
import re
from typing import Any

from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.core.orm import get_session_maker
from aegra_api.models.event_streaming import ThreadCommand
from aegra_api.services.event_streaming.protocol import build_error
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent.auth import authenticate
from agent.preflight import validate_runtime_preflight

_COMMAND_PATH = re.compile(r"^/threads/([^/]+)/commands$")
_THREAD_LEGACY_MUTATION_PATH = re.compile(
    r"^/threads/[^/]+/(?:runs(?:/(?:stream|wait|crons))?|state)$"
)
_CRON_UPDATE_PATH = re.compile(r"^/runs/crons/[^/]+$")
_STATELESS_LEGACY_MUTATION_PATHS = frozenset(
    {
        "/runs",
        "/runs/stream",
        "/runs/wait",
        "/runs/crons",
    }
)
_MAX_COMMAND_BODY_BYTES = 64 * 1024
_RUN_METHODS = frozenset({"run.start", "input.respond"})


async def _owned_or_new_thread_status(
    thread_id: str,
    user_id: str,
) -> tuple[bool, str | None]:
    """Match Aegra's owned-or-new check without exposing another owner's status."""
    maker = get_session_maker()
    async with maker() as session:
        row = (
            await session.execute(
                select(ThreadORM.user_id, ThreadORM.status).where(
                    ThreadORM.thread_id == thread_id
                )
            )
        ).one_or_none()
    if row is None:
        return True, None
    if row.user_id != user_id:
        return False, None
    return True, row.status


async def _authenticated_identity(scope: Scope) -> str | None:
    headers = {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    try:
        user = await authenticate(headers)
    except Exception:
        return None
    identity = user.get("identity")
    return identity if isinstance(identity, str) and identity else None


def _native_command(body: bytes) -> dict[str, Any] | None:
    """Parse only bodies Aegra's native ThreadCommand model would accept."""
    try:
        parsed = json.loads(body)
        command = ThreadCommand.model_validate(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        return None
    return command.model_dump()


def _is_hidden_legacy_mutation(method: str, path: str) -> bool:
    """Hide model-spending and checkpoint-mutating REST compatibility routes."""
    if method == "POST":
        return (
            path in _STATELESS_LEGACY_MUTATION_PATHS
            or _THREAD_LEGACY_MUTATION_PATH.fullmatch(path) is not None
        )
    return method == "PATCH" and _CRON_UPDATE_PATH.fullmatch(path) is not None


async def _read_body(receive: Receive) -> bytes:
    parts: list[bytes] = []
    size = 0
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b""
        body = message.get("body", b"")
        size += len(body)
        if size > _MAX_COMMAND_BODY_BYTES:
            raise ValueError("command body is too large")
        parts.append(body)
        more = bool(message.get("more_body", False))
    return b"".join(parts)


def _replay(body: bytes) -> Receive:
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


async def _json_response(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    content: dict[str, Any],
) -> None:
    await JSONResponse(status_code=status_code, content=content)(
        scope,
        receive,
        send,
    )


class NativeThreadGuard:
    """Enforce owner-preview APv2 mutations inside one process.

    This is deliberately a single-process guard, not a distributed lock. Production
    deployment must keep one application instance until Aegra exposes a supported
    cross-instance serialization primitive.
    """

    def __init__(self, app: ASGIApp, *, max_active_threads: int = 64) -> None:
        self.app = app
        self.max_active_threads = max_active_threads
        self._active: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        if _is_hidden_legacy_mutation(method, path):
            await _json_response(
                scope,
                receive,
                send,
                status_code=404,
                content={"detail": "Not Found"},
            )
            return
        command_match = _COMMAND_PATH.fullmatch(path) if method == "POST" else None
        if command_match is None:
            await self.app(scope, receive, send)
            return
        identity = await _authenticated_identity(scope)
        if identity is None:
            # Let Aegra's registered dependency produce the canonical 401.
            await self.app(scope, receive, send)
            return

        body = b""
        try:
            body = await _read_body(receive)
        except ValueError:
            await _json_response(
                scope,
                receive,
                send,
                status_code=413,
                content={
                    "error": "invalid_argument",
                    "message": "Command body is too large",
                },
            )
            return
        receive = _replay(body)
        command = _native_command(body)
        if command is None or command.get("method") not in _RUN_METHODS:
            await self.app(scope, receive, send)
            return

        thread_id = command_match.group(1)
        owned_or_new, thread_status = await _owned_or_new_thread_status(
            thread_id,
            identity,
        )
        if not owned_or_new:
            # Preserve Aegra's native 404 for another user's existing thread.
            await self.app(scope, receive, send)
            return

        if (
            command.get("method") == "input.respond"
            and {
                "update",
                "goto",
            }
            & command["params"].keys()
        ):
            command_id = command.get("id")
            envelope = build_error(
                command_id if isinstance(command_id, int) else None,
                "invalid_argument",
                "Aegra 0.9.24 does not support input.respond update or goto",
            )
            await _json_response(
                scope,
                receive,
                send,
                status_code=200,
                content=envelope,
            )
            return

        if thread_id in self._active:
            await _json_response(
                scope,
                receive,
                send,
                status_code=409,
                content={
                    "error": "conflict",
                    "message": "A mutation is already active for this thread",
                },
            )
            return
        if len(self._active) >= self.max_active_threads:
            await _json_response(
                scope,
                receive,
                send,
                status_code=503,
                content={
                    "error": "service_unavailable",
                    "message": "The thread mutation guard is at capacity",
                },
            )
            return

        self._active.add(thread_id)
        try:
            if command.get("method") == "run.start" and thread_status == "busy":
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=409,
                    content={
                        "error": "conflict",
                        "message": "The thread already has an active run",
                    },
                )
                return
            await self.app(scope, receive, send)
        finally:
            self._active.discard(thread_id)


validate_runtime_preflight()

app = FastAPI(title="syshin0116.dev Aegra extensions")
app.add_middleware(NativeThreadGuard)

__all__ = ["NativeThreadGuard", "app"]
