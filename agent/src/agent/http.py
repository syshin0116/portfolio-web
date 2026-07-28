"""Minimal Aegra HTTP extension for native APv2 owner-preview traffic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl
from uuid import UUID

from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.core.orm import get_session_maker
from aegra_api.models import User as AegraUser
from aegra_api.models.event_streaming import ThreadCommand
from aegra_api.services.event_streaming.protocol import build_error
from aegra_api.services.langgraph_service import (
    create_thread_config,
    get_langgraph_service,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent.auth import (
    ANONYMOUS_PERMISSION,
    authenticate,
    is_anonymous_identity,
    server_anonymous_access_enabled,
)
from agent.guest_budget import (
    GuestDailyBudgetExhaustedError,
    GuestSpendLedger,
    PostgresGuestSpendLedger,
    guest_budget_config,
)
from agent.guest_thread_lock import (
    COMMAND_GUEST_THREAD_LOCK_TIMEOUT_SECONDS,
    GuestThreadLockUnavailableError,
    guest_thread_advisory_lock,
)
from agent.maintenance import GUEST_RETENTION_POLICY, collect_expired_guest_threads
from agent.preflight import validate_runtime_preflight
from agent.public_wire import (
    GuestJSONResponseSend,
    GuestSSEResponseSend,
    GuestStreamLimitError,
    GuestWireProjectionError,
)

logger = logging.getLogger(__name__)

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
_GUEST_MAX_BODY_BYTES = 32 * 1024
_GUEST_MAX_STREAM_BODY_BYTES = 2 * 1024
_GUEST_MAX_IDENTITIES = 1_024
_GUEST_RATE_CAPACITY = 4
_GUEST_RATE_WINDOW_SECONDS = 60.0
_GUEST_GLOBAL_RATE_CAPACITY = 24
_GUEST_GLOBAL_RATE_WINDOW_SECONDS = 60.0
_GUEST_INTERRUPT_VALIDATION_TIMEOUT_SECONDS = 5.0
_GUEST_THREAD_LOCK_SCOPE_KEY = "agent.guest_thread_lock"
_GUEST_SESSION_RETENTION_DAYS = 14
_GUEST_SUBMIT_NONCE_KEY = "syshin_ui_submit_nonce"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_NONCE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SAFE_INTERRUPT_ID = re.compile(r"^[0-9a-f]{32}$")
_GUEST_THREAD_PATH = re.compile(r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})$")
_GUEST_STATE_PATH = re.compile(r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/state$")
_GUEST_HISTORY_PATH = re.compile(
    r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/history$"
)
_GUEST_RUNS_PATH = re.compile(r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/runs$")
_GUEST_RUN_PATH = re.compile(
    r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/"
    r"runs/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})$"
)
_GUEST_CANCEL_PATH = re.compile(
    r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/"
    r"runs/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/cancel$"
)
_GUEST_STREAM_PATH = re.compile(
    r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/stream/events$"
)
_GUEST_COMMAND_PATH = re.compile(
    r"^/threads/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/commands$"
)
_FORBIDDEN_GUEST_KEYS = frozenset(
    {
        "assistant",
        "budget",
        "checkpoint",
        "checkpoint_id",
        "configurable",
        "dynamic_subagents",
        "dynamic_subagents_enabled",
        "model",
        "multitask_strategy",
        "multitaskStrategy",
        "quickjs",
        "quickjs_enabled",
        "response_format",
        "subagents",
        "user_id",
    }
)


class GuestRequestError(ValueError):
    """Raised when a guest request crosses the public wire contract."""


class _GuestThreadNotFoundError(LookupError):
    """Raised when a guest thread disappears or no longer belongs to its caller."""


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class _OwnedGuestThread:
    status: str
    graph_id: str | None
    updated_at: datetime


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _content_length(scope: Scope) -> int | None:
    value = _headers(scope).get("content-length")
    if value is None:
        return None
    if not value.isascii() or not value.isdecimal():
        raise GuestRequestError("invalid content length")
    parsed = int(value)
    if parsed < 0:
        raise GuestRequestError("invalid content length")
    return parsed


def _require_json_content_type(scope: Scope) -> None:
    content_type = _headers(scope).get("content-type", "")
    media_type, _separator, parameters = content_type.partition(";")
    if media_type.strip().lower() != "application/json":
        raise GuestRequestError("JSON content type is required")
    if parameters and parameters.strip().lower() != "charset=utf-8":
        raise GuestRequestError("unsupported JSON content type")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GuestRequestError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise GuestRequestError("non-finite JSON number")


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        decoded = body.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise GuestRequestError("invalid JSON body") from exc
    if not isinstance(value, dict):
        raise GuestRequestError("JSON body must be an object")
    return value


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _bounded_string(
    value: object,
    *,
    max_bytes: int,
    field: str,
    allow_newlines: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > max_bytes
        or any(
            ord(character) < 32
            and (not allow_newlines or character not in {"\n", "\r", "\t"})
            for character in value
        )
    ):
        raise GuestRequestError(f"{field} is invalid")
    return value


def _bounded_json_value(
    value: Any,
    *,
    depth: int = 0,
    containers: list[int] | None = None,
) -> Any:
    if containers is None:
        containers = [0]
    if depth > 6:
        raise GuestRequestError("JSON nesting is too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > 2**53 - 1:
            raise GuestRequestError("JSON integer is out of range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GuestRequestError("JSON number is invalid")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 16 * 1024:
            raise GuestRequestError("JSON string is too large")
        return value
    if isinstance(value, list):
        containers[0] += 1
        if containers[0] > 256 or len(value) > 128:
            raise GuestRequestError("JSON collection is too large")
        return [
            _bounded_json_value(item, depth=depth + 1, containers=containers)
            for item in value
        ]
    if isinstance(value, dict):
        containers[0] += 1
        if containers[0] > 256 or len(value) > 64:
            raise GuestRequestError("JSON object is too large")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key.encode("utf-8")) > 128
                or key in _FORBIDDEN_GUEST_KEYS
            ):
                raise GuestRequestError("JSON object key is invalid")
            normalized[key] = _bounded_json_value(
                item,
                depth=depth + 1,
                containers=containers,
            )
        return normalized
    raise GuestRequestError("JSON value type is unsupported")


def _safe_nonce(value: object) -> str:
    if not isinstance(value, str) or _SAFE_NONCE.fullmatch(value) is None:
        raise GuestRequestError("run nonce is invalid")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise GuestRequestError("run nonce is invalid") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise GuestRequestError("run nonce is invalid")
    return value


def _run_nonce(
    params: dict[str, Any],
) -> tuple[str, dict[str, str], dict[str, dict[str, str]]]:
    metadata = params.get("metadata")
    config = params.get("config")
    if not isinstance(metadata, dict) or not isinstance(config, dict):
        raise GuestRequestError("run correlation metadata is required")
    config_metadata = config.get("metadata")
    if not isinstance(config_metadata, dict):
        raise GuestRequestError("run correlation metadata is required")
    if set(metadata) != {_GUEST_SUBMIT_NONCE_KEY} or set(config) != {"metadata"}:
        raise GuestRequestError("run metadata is not allowed")
    if set(config_metadata) != {_GUEST_SUBMIT_NONCE_KEY}:
        raise GuestRequestError("run config metadata is not allowed")
    nonce = _safe_nonce(metadata[_GUEST_SUBMIT_NONCE_KEY])
    if config_metadata[_GUEST_SUBMIT_NONCE_KEY] != nonce:
        raise GuestRequestError("run correlation metadata does not match")
    normalized_metadata = {_GUEST_SUBMIT_NONCE_KEY: nonce}
    return nonce, normalized_metadata, {"metadata": normalized_metadata.copy()}


def _guest_messages(value: object) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict) or set(value) != {"messages"}:
        raise GuestRequestError("run input must contain only messages")
    messages = value["messages"]
    if not isinstance(messages, list) or not messages or len(messages) > 64:
        raise GuestRequestError("run messages are invalid")
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise GuestRequestError("run message is invalid")
        allowed = {"role", "content", "id", "name", "tool_call_id"}
        if not set(message) <= allowed or not {"role", "content", "id"} <= set(message):
            raise GuestRequestError("run message fields are invalid")
        role = message["role"]
        if not isinstance(role, str) or role not in {"user", "assistant", "tool"}:
            raise GuestRequestError("run message role is invalid")
        message_id = _bounded_string(
            message["id"],
            max_bytes=128,
            field="message id",
        )
        normalized_message: dict[str, Any] = {
            "content": _bounded_json_value(message["content"]),
            "id": message_id,
            "role": role,
        }
        if role == "tool":
            normalized_message["name"] = _bounded_string(
                message.get("name"),
                max_bytes=128,
                field="tool name",
            )
            normalized_message["tool_call_id"] = _bounded_string(
                message.get("tool_call_id"),
                max_bytes=128,
                field="tool call id",
            )
        elif "name" in message or "tool_call_id" in message:
            raise GuestRequestError("tool fields are not allowed for this role")
        normalized.append(normalized_message)
    if normalized[-1]["role"] != "user":
        raise GuestRequestError("the final run message must be from the user")
    return {"messages": normalized}


def _guest_command(body: bytes) -> tuple[bytes, bool]:
    command = _json_object(body)
    if set(command) != {"id", "method", "params"}:
        raise GuestRequestError("command fields are invalid")
    command_id = command["id"]
    if (
        not isinstance(command_id, int)
        or isinstance(command_id, bool)
        or not 0 <= command_id <= 2**31 - 1
    ):
        raise GuestRequestError("command id is invalid")
    method = command["method"]
    params = command["params"]
    if (
        not isinstance(method, str)
        or method not in _RUN_METHODS
        or not isinstance(params, dict)
    ):
        raise GuestRequestError("command method is not allowed")
    if method == "run.start":
        allowed = {
            "assistant_id",
            "config",
            "input",
            "metadata",
            "multitaskStrategy",
            "multitask_strategy",
        }
        if not set(params) <= allowed or not {"input", "config", "metadata"} <= set(
            params
        ):
            raise GuestRequestError("run.start fields are invalid")
        assistant_id = params.get("assistant_id", "agent")
        if assistant_id != "agent":
            raise GuestRequestError("assistant id is invalid")
        _nonce, metadata, config = _run_nonce(params)
        normalized = {
            "id": command_id,
            "method": method,
            "params": {
                "assistant_id": "agent",
                "config": config,
                "input": _guest_messages(params["input"]),
                "metadata": metadata,
                "multitask_strategy": "reject",
            },
        }
        return _canonical_json(normalized), True

    allowed = {
        "config",
        "interrupt_id",
        "metadata",
        "namespace",
        "response",
    }
    if set(params) != allowed:
        raise GuestRequestError("input.respond fields are invalid")
    _nonce, metadata, config = _run_nonce(params)
    namespace = params["namespace"]
    if namespace != []:
        raise GuestRequestError("interrupt namespace is invalid")
    interrupt_id = _bounded_string(
        params["interrupt_id"],
        max_bytes=32,
        field="interrupt id",
    )
    if _SAFE_INTERRUPT_ID.fullmatch(interrupt_id) is None:
        raise GuestRequestError("interrupt id is invalid")
    normalized = {
        "id": command_id,
        "method": method,
        "params": {
            "config": config,
            "interrupt_id": interrupt_id,
            "metadata": metadata,
            "namespace": [],
            "response": _bounded_json_value(params["response"]),
        },
    }
    return _canonical_json(normalized), True


def _guest_stream_subscription(body: bytes) -> bytes:
    value = _json_object(body)
    if not set(value) <= {"channels", "depth", "namespaces"}:
        raise GuestRequestError("stream fields are invalid")
    channels = value.get("channels")
    if (
        not isinstance(channels, list)
        or not channels
        or len(channels) > 5
        or any(not isinstance(channel, str) for channel in channels)
        or len(set(channels)) != len(channels)
        or any(
            channel not in {"messages", "lifecycle", "input", "tools", "custom"}
            for channel in channels
        )
    ):
        raise GuestRequestError("stream channels are invalid")
    normalized: dict[str, Any] = {
        "channels": channels,
        "depth": 0,
        "namespaces": [[]],
    }
    if "depth" in value and (type(value["depth"]) is not int or value["depth"] != 0):
        raise GuestRequestError("stream depth is invalid")
    if "namespaces" in value and value["namespaces"] != [[]]:
        raise GuestRequestError("stream namespaces are invalid")
    return _canonical_json(normalized)


def _guest_thread_metadata(
    value: object,
    *,
    expires_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GuestRequestError("thread metadata is invalid")
    if not set(value) <= {
        "archived",
        "custom",
        "graph_id",
        "title",
        "title_status",
    }:
        raise GuestRequestError("thread metadata fields are invalid")
    normalized: dict[str, Any] = {}
    if "graph_id" in value:
        if value["graph_id"] != "agent":
            raise GuestRequestError("thread graph id is invalid")
        normalized["graph_id"] = "agent"
    if "title" in value:
        normalized["title"] = _bounded_string(
            value["title"],
            max_bytes=512,
            field="thread title",
        )
    if "title_status" in value:
        if not isinstance(value["title_status"], str) or value["title_status"] not in {
            "pending",
            "manual",
            "generated",
        }:
            raise GuestRequestError("thread title status is invalid")
        normalized["title_status"] = value["title_status"]
    if "archived" in value:
        if type(value["archived"]) is not bool:
            raise GuestRequestError("thread archived flag is invalid")
        normalized["archived"] = value["archived"]
    if "custom" in value:
        custom = _bounded_json_value(value["custom"])
        if not isinstance(custom, dict) or len(_canonical_json(custom)) > 2_048:
            raise GuestRequestError("thread custom metadata is invalid")
        normalized["custom"] = custom
    if expires_at is not None:
        normalized["guest_expires_at"] = expires_at
        normalized["guest_retention_policy"] = GUEST_RETENTION_POLICY
    return normalized


def _guest_route_body(
    kind: str,
    body: bytes,
    *,
    expires_at: str,
) -> tuple[bytes, bool]:
    if kind == "command":
        return _guest_command(body)
    if kind == "stream":
        return _guest_stream_subscription(body), False
    value = _json_object(body)
    if kind == "thread-create":
        if not set(value) <= {"if_exists", "metadata", "thread_id"}:
            raise GuestRequestError("thread creation fields are invalid")
        thread_id = value.get("thread_id")
        if not isinstance(thread_id, str) or _SAFE_ID.fullmatch(thread_id) is None:
            raise GuestRequestError("thread id is invalid")
        if value.get("if_exists") != "do_nothing":
            raise GuestRequestError("thread creation policy is invalid")
        normalized = {
            "if_exists": "do_nothing",
            "metadata": _guest_thread_metadata(
                value.get("metadata"),
                expires_at=expires_at,
            ),
            "thread_id": thread_id,
        }
        return _canonical_json(normalized), False
    if kind == "thread-update":
        if set(value) != {"metadata"}:
            raise GuestRequestError("thread update fields are invalid")
        return (
            _canonical_json({"metadata": _guest_thread_metadata(value["metadata"])}),
            False,
        )
    if kind == "thread-search":
        if not set(value) <= {"limit", "offset", "sort_by", "sort_order"}:
            raise GuestRequestError("thread search fields are invalid")
        limit = value.get("limit", 10)
        offset = value.get("offset", 0)
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset <= 1_000
            or value.get("sort_by", "updated_at") != "updated_at"
            or value.get("sort_order", "desc") != "desc"
        ):
            raise GuestRequestError("thread search bounds are invalid")
        return (
            _canonical_json(
                {
                    "limit": limit,
                    "offset": offset,
                    "sort_by": "updated_at",
                    "sort_order": "desc",
                }
            ),
            False,
        )
    if kind == "history":
        if not set(value) <= {"limit"}:
            raise GuestRequestError("history fields are invalid")
        limit = value.get("limit", 10)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise GuestRequestError("history limit is invalid")
        return _canonical_json({"limit": limit}), False
    raise GuestRequestError("request body is not allowed")


def _query(scope: Scope) -> dict[str, str]:
    raw = scope.get("query_string", b"")
    try:
        decoded = raw.decode("ascii")
        pairs = parse_qsl(
            decoded,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=8,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GuestRequestError("query string is invalid") from exc
    if len({key for key, _value in pairs}) != len(pairs):
        raise GuestRequestError("duplicate query field")
    return dict(pairs)


def _guest_route_kind(scope: Scope) -> str | None:
    method = scope.get("method", "")
    path = scope.get("path", "")
    query = _query(scope)
    if method == "POST" and path == "/threads" and not query:
        return "thread-create"
    if method == "POST" and path == "/threads/search" and not query:
        return "thread-search"
    if _GUEST_THREAD_PATH.fullmatch(path):
        if method == "GET" and not query:
            return "thread-read"
        if method == "PATCH" and not query:
            return "thread-update"
        return None
    if method == "GET" and _GUEST_STATE_PATH.fullmatch(path) and not query:
        return "state"
    if method == "POST" and _GUEST_HISTORY_PATH.fullmatch(path) and not query:
        return "history"
    if method == "GET" and _GUEST_RUNS_PATH.fullmatch(path):
        if query in ({}, {"limit": "10", "offset": "0"}):
            return "runs"
        return None
    if method == "GET" and _GUEST_RUN_PATH.fullmatch(path) and not query:
        return "run"
    if method == "POST" and _GUEST_CANCEL_PATH.fullmatch(path):
        if query == {"action": "interrupt", "wait": "0"}:
            return "cancel"
        return None
    if method == "POST" and _GUEST_STREAM_PATH.fullmatch(path) and not query:
        return "stream"
    if method == "POST" and _GUEST_COMMAND_PATH.fullmatch(path) and not query:
        return "command"
    return None


def _is_guest_user(user: object) -> bool:
    if not isinstance(user, dict):
        return False
    return (
        user.get("is_authenticated") is True
        and is_anonymous_identity(user.get("identity"))
        and user.get("permissions") == [ANONYMOUS_PERMISSION]
    )


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


async def _owned_guest_thread(
    thread_id: str,
    user_id: str,
) -> _OwnedGuestThread | None:
    """Read the guest-owned thread fields that fence a root-state lookup."""
    maker = get_session_maker()
    async with maker() as session:
        row = (
            await session.execute(
                select(
                    ThreadORM.user_id,
                    ThreadORM.status,
                    ThreadORM.metadata_json,
                    ThreadORM.updated_at,
                ).where(ThreadORM.thread_id == thread_id)
            )
        ).one_or_none()
    if row is None or row.user_id != user_id:
        return None
    metadata = row.metadata_json
    graph_id = metadata.get("graph_id") if isinstance(metadata, dict) else None
    return _OwnedGuestThread(
        status=row.status,
        graph_id=graph_id if isinstance(graph_id, str) and graph_id else None,
        updated_at=row.updated_at,
    )


async def _current_guest_root_interrupt_id(
    thread_id: str,
    user: dict[str, Any],
) -> str | None:
    """Return one stable pending interrupt ID from the official root state.

    The two metadata reads form an optimistic fence around LangGraph's public
    ``aget_state`` API. ``NativeThreadGuard`` keeps its PostgreSQL advisory
    claim across this lookup, the spend reservation, and Aegra's downstream
    busy-state commit. A changed status/timestamp therefore fails closed
    without holding a PostgreSQL row lock that would deadlock that commit.
    """
    identity = user.get("identity")
    if not isinstance(identity, str) or not identity:
        raise _GuestThreadNotFoundError

    before = await _owned_guest_thread(thread_id, identity)
    if before is None:
        raise _GuestThreadNotFoundError
    if before.status != "interrupted":
        return None
    if before.graph_id is None:
        raise RuntimeError("guest thread graph metadata is unavailable")

    aegra_user = AegraUser.model_validate(user)
    config = create_thread_config(thread_id, aegra_user)
    service = get_langgraph_service()
    async with service.get_graph(
        before.graph_id,
        config=config,
        access_context="threads.read",
        user=aegra_user,
    ) as graph:
        graph = graph.with_config(config)
        state = await graph.aget_state(config, subgraphs=False)

    interrupts = getattr(state, "interrupts", ())
    current_id: str | None = None
    if isinstance(interrupts, tuple) and len(interrupts) == 1:
        candidate = getattr(interrupts[0], "id", None)
        if (
            isinstance(candidate, str)
            and _SAFE_INTERRUPT_ID.fullmatch(candidate) is not None
        ):
            current_id = candidate

    after = await _owned_guest_thread(thread_id, identity)
    if after is None:
        raise _GuestThreadNotFoundError
    if after != before:
        return None
    return current_id


async def _authenticated_user(scope: Scope) -> dict[str, Any] | None:
    try:
        user = await authenticate(_headers(scope))
    except Exception:
        return None
    return user if isinstance(user, dict) else None


def _native_command(body: bytes) -> dict[str, Any] | None:
    """Parse only bodies Aegra's native ThreadCommand model would accept."""
    try:
        parsed = json.loads(body)
        command = ThreadCommand.model_validate(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValidationError):
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


async def _read_body(
    receive: Receive, *, max_bytes: int = _MAX_COMMAND_BODY_BYTES
) -> bytes:
    parts: list[bytes] = []
    size = 0
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b""
        body = message.get("body", b"")
        size += len(body)
        if size > max_bytes:
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
    headers: dict[str, str] | None = None,
) -> None:
    response_headers = {"Cache-Control": "no-store"}
    if headers is not None:
        response_headers.update(headers)
    await JSONResponse(
        status_code=status_code,
        content=content,
        headers=response_headers,
    )(
        scope,
        receive,
        send,
    )


class GuestRunGuard:
    """Pure-ASGI public guest boundary outside every Aegra route.

    The limiter is deliberately process-local. Cloud Run remains fixed to one instance
    until the durable P5 spend ledger and a distributed serialization primitive land.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        clock: Any = time.monotonic,
        wall_clock: Any = time.time,
        max_identities: int = _GUEST_MAX_IDENTITIES,
        identity_capacity: int = _GUEST_RATE_CAPACITY,
        identity_window_seconds: float = _GUEST_RATE_WINDOW_SECONDS,
        global_capacity: int = _GUEST_GLOBAL_RATE_CAPACITY,
        global_window_seconds: float = _GUEST_GLOBAL_RATE_WINDOW_SECONDS,
        spend_ledger: GuestSpendLedger | None = None,
        enforce_daily_budget: bool = False,
    ) -> None:
        integer_values = (
            max_identities,
            identity_capacity,
            global_capacity,
        )
        numeric_values = (identity_window_seconds, global_window_seconds)
        if any(type(value) is not int or value < 1 for value in integer_values) or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
            for value in numeric_values
        ):
            raise ValueError("guest guard limits must be positive")
        if not isinstance(enforce_daily_budget, bool):
            raise TypeError("enforce_daily_budget must be a boolean")
        if (
            enforce_daily_budget
            and spend_ledger is None
            and server_anonymous_access_enabled()
        ):
            config = guest_budget_config(required=True)
            if config is None:
                raise RuntimeError("guest daily budget configuration is missing")
            spend_ledger = PostgresGuestSpendLedger(config)
        self.app = app
        self._clock = clock
        self._wall_clock = wall_clock
        self._max_identities = max_identities
        self._identity_capacity = identity_capacity
        self._identity_refill_per_second = identity_capacity / identity_window_seconds
        self._global_capacity = global_capacity
        self._global_refill_per_second = global_capacity / global_window_seconds
        now = float(clock())
        self._global_bucket = _Bucket(float(global_capacity), now)
        self._identity_buckets: dict[str, _Bucket] = {}
        self._lock = Lock()
        self._spend_ledger = spend_ledger

    @staticmethod
    def _identity_key(identity: str) -> str:
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _refill(
        bucket: _Bucket,
        *,
        now: float,
        capacity: int,
        rate: float,
    ) -> float:
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(float(capacity), bucket.tokens + elapsed * rate)
        bucket.updated_at = now
        return bucket.tokens

    def _consume_run(self, identity: str) -> tuple[bool, int]:
        now = float(self._clock())
        if not math.isfinite(now):
            return False, 1
        identity_key = self._identity_key(identity)
        with self._lock:
            bucket = self._identity_buckets.get(identity_key)
            if bucket is None:
                if len(self._identity_buckets) >= self._max_identities:
                    return False, 60
                bucket = _Bucket(float(self._identity_capacity), now)
                self._identity_buckets[identity_key] = bucket
            identity_tokens = self._refill(
                bucket,
                now=now,
                capacity=self._identity_capacity,
                rate=self._identity_refill_per_second,
            )
            global_tokens = self._refill(
                self._global_bucket,
                now=now,
                capacity=self._global_capacity,
                rate=self._global_refill_per_second,
            )
            if identity_tokens >= 1.0 and global_tokens >= 1.0:
                bucket.tokens -= 1.0
                self._global_bucket.tokens -= 1.0
                return True, 0
            identity_wait = (
                0.0
                if identity_tokens >= 1.0
                else (1.0 - identity_tokens) / self._identity_refill_per_second
            )
            global_wait = (
                0.0
                if global_tokens >= 1.0
                else (1.0 - global_tokens) / self._global_refill_per_second
            )
        return False, max(1, min(60, math.ceil(max(identity_wait, global_wait))))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        user = await _authenticated_user(scope)
        if user is None:
            # Aegra owns the canonical authentication error and public health routes.
            await self.app(scope, receive, send)
            return
        if not _is_guest_user(user):
            await self.app(scope, receive, send)
            return

        try:
            kind = _guest_route_kind(scope)
        except GuestRequestError:
            kind = None
        if kind is None:
            await _json_response(
                scope,
                receive,
                send,
                status_code=404,
                content={"detail": "Not Found"},
            )
            return

        body_kinds = {
            "command",
            "history",
            "stream",
            "thread-create",
            "thread-search",
            "thread-update",
        }
        spends = False
        if kind in body_kinds:
            max_bytes = (
                _GUEST_MAX_STREAM_BODY_BYTES
                if kind == "stream"
                else _GUEST_MAX_BODY_BYTES
            )
            try:
                _require_json_content_type(scope)
                length = _content_length(scope)
                if length is not None and length > max_bytes:
                    raise GuestRequestError("request body is too large")
                body = await _read_body(receive, max_bytes=max_bytes)
                expires_at = datetime.fromtimestamp(
                    float(self._wall_clock()),
                    tz=UTC,
                ) + timedelta(days=_GUEST_SESSION_RETENTION_DAYS)
                body, spends = _guest_route_body(
                    kind,
                    body,
                    expires_at=expires_at.isoformat().replace("+00:00", "Z"),
                )
            except (GuestRequestError, ValueError, OverflowError, OSError):
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    content={
                        "error": "invalid_argument",
                        "message": "Guest request is invalid",
                    },
                )
                return
            receive = _replay(body)

        identity = user["identity"]
        if spends:
            allowed, retry_after = self._consume_run(identity)
            if not allowed:
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "message": "Guest run rate limit exceeded",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
                return
            if self._spend_ledger is not None:
                try:
                    await self._spend_ledger.reserve_run()
                except GuestDailyBudgetExhaustedError:
                    now = datetime.fromtimestamp(
                        float(self._wall_clock()),
                        tz=UTC,
                    )
                    next_day = (now + timedelta(days=1)).replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    retry_after = max(
                        1,
                        math.ceil((next_day - now).total_seconds()),
                    )
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=429,
                        content={
                            "error": "daily_budget_exhausted",
                            "message": "Guest daily run budget is exhausted",
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
                    return
                except Exception as error:
                    logger.error(
                        "guest spend ledger reservation failed error_type=%s",
                        type(error).__name__,
                    )
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=503,
                        content={
                            "error": "service_unavailable",
                            "message": "Guest run budget is unavailable",
                        },
                        headers={"Retry-After": "60"},
                    )
                    return

        projected_send: Send
        if kind == "stream":
            projected_send = GuestSSEResponseSend(send)
        else:
            projected_send = GuestJSONResponseSend(send, kind=kind)
        await self.app(scope, receive, projected_send)


class NativeThreadGuard:
    """Enforce owner-safe APv2 mutations with guest-only PostgreSQL serialization."""

    def __init__(self, app: ASGIApp, *, max_active_threads: int = 64) -> None:
        self.app = app
        self.max_active_threads = max_active_threads
        self._active: set[str] = set()
        self._active_owners: dict[str, str] = {}

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
        user = await _authenticated_user(scope)
        identity = user.get("identity") if user is not None else None
        if not isinstance(identity, str) or not identity:
            # Let Aegra's registered dependency produce the canonical 401.
            await self.app(scope, receive, send)
            return
        is_guest = is_anonymous_identity(identity)

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
        command_method = command.get("method") if command is not None else None
        if (
            command is None
            or not isinstance(command_method, str)
            or command_method not in _RUN_METHODS
        ):
            await self.app(scope, receive, send)
            return

        thread_id = command_match.group(1)
        if is_guest and _SAFE_ID.fullmatch(thread_id) is None:
            await _json_response(
                scope,
                receive,
                send,
                status_code=404,
                content={"detail": "Not Found"},
            )
            return

        guest_resume_id: str | None = None
        if is_guest:
            try:
                normalized_body, _spends = _guest_command(body)
            except GuestRequestError:
                # Invalid paid guest wires never take either the PostgreSQL or local
                # mutation claim. Preserve the hidden-resource response for a foreign
                # thread, then let the inner guest boundary own its canonical 400.
                owned_or_new, _thread_status = await _owned_or_new_thread_status(
                    thread_id,
                    identity,
                )
                if not owned_or_new:
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=404,
                        content={"detail": "Not Found"},
                    )
                    return
                await self.app(scope, receive, send)
                return
            if command.get("method") == "input.respond":
                normalized = json.loads(normalized_body)
                guest_resume_id = normalized["params"]["interrupt_id"]

            if scope.get(_GUEST_THREAD_LOCK_SCOPE_KEY) != thread_id:
                lock_context = guest_thread_advisory_lock(
                    thread_id,
                    timeout_seconds=COMMAND_GUEST_THREAD_LOCK_TIMEOUT_SECONDS,
                )
                try:
                    await lock_context.__aenter__()
                except GuestThreadLockUnavailableError as error:
                    logger.error(
                        "guest thread serialization failed error_type=%s",
                        type(error.__cause__).__name__
                        if error.__cause__ is not None
                        else type(error).__name__,
                    )
                    try:
                        (
                            owned_or_new,
                            _thread_status,
                        ) = await _owned_or_new_thread_status(
                            thread_id,
                            identity,
                        )
                    except Exception:
                        owned_or_new = True
                    if not owned_or_new:
                        await _json_response(
                            scope,
                            receive,
                            send,
                            status_code=404,
                            content={"detail": "Not Found"},
                        )
                        return
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=503,
                        content={
                            "error": "service_unavailable",
                            "message": "Guest thread scheduling is unavailable",
                        },
                        headers={"Retry-After": "1"},
                    )
                    return
                try:
                    locked_scope = dict(scope)
                    locked_scope[_GUEST_THREAD_LOCK_SCOPE_KEY] = thread_id
                    await self(locked_scope, _replay(body), send)
                finally:
                    await lock_context.__aexit__(None, None, None)
                return

        owned_or_new, thread_status = await _owned_or_new_thread_status(
            thread_id,
            identity,
        )
        if not owned_or_new:
            if is_guest:
                # Ownership is both a privacy and spend boundary for guests:
                # reject before the inner rate/budget guard can reserve a run.
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=404,
                    content={"detail": "Not Found"},
                )
                return
            # Preserve Aegra's native owner-preview behavior.
            await self.app(scope, receive, send)
            return

        if is_guest and thread_status is None:
            # Public commands operate only on a thread created through the guest
            # boundary. In particular, a command waiting behind retention GC may
            # not resurrect the just-deleted identifier as a fresh thread.
            await _json_response(
                scope,
                receive,
                send,
                status_code=404,
                content={"detail": "Not Found"},
            )
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

        if is_guest:
            if (
                command.get("method") == "input.respond"
                and thread_status != "interrupted"
            ):
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=409,
                    content={
                        "error": "conflict",
                        "message": "The thread is not waiting for guest input",
                    },
                )
                return
            if command.get("method") == "run.start" and thread_status == "interrupted":
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=409,
                    content={
                        "error": "conflict",
                        "message": "The thread is waiting for guest input",
                    },
                )
                return

        if thread_id in self._active:
            active_owner = self._active_owners.get(thread_id)
            if (
                active_owner is not None
                and active_owner != hashlib.sha256(identity.encode("utf-8")).hexdigest()
            ):
                await _json_response(
                    scope,
                    receive,
                    send,
                    status_code=404,
                    content={"detail": "Not Found"},
                )
                return
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
        self._active_owners[thread_id] = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()
        try:
            if guest_resume_id is not None:
                try:
                    async with asyncio.timeout(
                        _GUEST_INTERRUPT_VALIDATION_TIMEOUT_SECONDS
                    ):
                        current_interrupt_id = await _current_guest_root_interrupt_id(
                            thread_id,
                            user,
                        )
                except _GuestThreadNotFoundError:
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=404,
                        content={"detail": "Not Found"},
                    )
                    return
                except Exception as error:
                    logger.error(
                        "guest interrupt validation failed error_type=%s",
                        type(error).__name__,
                    )
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=503,
                        content={
                            "error": "service_unavailable",
                            "message": "Guest interrupt validation is unavailable",
                        },
                        headers={"Retry-After": "1"},
                    )
                    return
                if current_interrupt_id != guest_resume_id:
                    await _json_response(
                        scope,
                        receive,
                        send,
                        status_code=409,
                        content={
                            "error": "conflict",
                            "message": "The guest interrupt is no longer current",
                        },
                    )
                    return
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
            self._active_owners.pop(thread_id, None)


validate_runtime_preflight()

app = FastAPI(title="syshin0116.dev Aegra extensions")


@app.post("/admin/gc", include_in_schema=False)
async def collect_guest_threads(request: Request) -> JSONResponse:
    """Run one owner-authorized, bounded checkpoint-first retention sweep."""
    user = await _authenticated_user(request.scope)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"Cache-Control": "no-store"},
        )
    permissions = user.get("permissions")
    if not isinstance(permissions, list) or "admin" not in permissions:
        return JSONResponse(
            status_code=403,
            content={"detail": "Forbidden"},
            headers={"Cache-Control": "no-store"},
        )
    try:
        result = await collect_expired_guest_threads()
    except Exception as error:
        logger.error(
            "guest retention sweep failed error_type=%s",
            type(error).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_unavailable",
                "message": "Guest retention sweep is unavailable",
            },
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        content={
            "lock_acquired": result.lock_acquired,
            "deleted_threads": result.deleted_threads,
            "batch_limit": result.batch_limit,
        },
        headers={"Cache-Control": "no-store"},
    )


app.add_middleware(GuestRunGuard, enforce_daily_budget=True)
app.add_middleware(NativeThreadGuard)

__all__ = [
    "GuestRequestError",
    "GuestRunGuard",
    "GuestStreamLimitError",
    "GuestWireProjectionError",
    "NativeThreadGuard",
    "app",
]
