"""Fail-closed response projection for the public guest Agent Protocol wire.

The browser is not a security boundary. Guest checkpoint responses and SSE
events therefore cross this module before any response body bytes are sent.
Only the small state, interrupt, message, tool-lifecycle, and inspection
contracts needed by the public chat survive the projection.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from starlette.types import Message, Send

from agent.inspection import (
    INSPECTION_EVENT_NAME,
    InspectionContractError,
    normalize_retrieval_inspection,
)

GUEST_MAX_SSE_TOTAL_BYTES = 512 * 1024
GUEST_MAX_SSE_CHUNK_BYTES = GUEST_MAX_SSE_TOTAL_BYTES
_MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_PROJECTED_JSON_BYTES = 512 * 1024
_MAX_HISTORY_STATES = 50
_MAX_THREADS = 50
_MAX_RUNS = 10
_MAX_STATE_MESSAGES = 128
_MAX_CONTENT_BLOCKS = 64
_MAX_TEXT_BYTES = 64 * 1024
_MAX_ID_BYTES = 256
_MAX_CITATIONS = 32
_MAX_TIMESTAMP = 2**53 - 1
_MAX_PUBLIC_CUSTOM_BYTES = 2 * 1024
_MAX_PUBLIC_JSON_CONTAINERS = 256
_MAX_PUBLIC_JSON_DEPTH = 6
_MAX_PUBLIC_JSON_ITEMS = 128
_MAX_PUBLIC_JSON_KEYS = 64
_MAX_PUBLIC_JSON_KEY_BYTES = 128
_MAX_PUBLIC_JSON_STRING_BYTES = 16 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,255}$")
_SAFE_SUBMIT_NONCE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-"
    r"[0-9a-f]{12}$"
)
_SAFE_INTERRUPT_ID = re.compile(r"^[0-9a-f]{32}$")
_GUEST_STORED_USER_MESSAGE_ID = re.compile(
    r"^guest-user:([A-Za-z0-9][A-Za-z0-9._:-]{0,127}):[0-9a-f]{32}$"
)
_THREAD_STATUSES = frozenset({"idle", "busy", "interrupted", "error"})
_RUN_STATUSES = frozenset(
    {"pending", "running", "error", "success", "timeout", "interrupted"}
)
_COMMAND_ERRORS = frozenset(
    {
        "invalid_argument",
        "unknown_command",
        "unknown_error",
        "no_such_run",
        "no_such_interrupt",
        "permission_denied",
        "not_supported",
    }
)
_COMMAND_ERROR_MESSAGES = {
    "invalid_argument": "Guest command is invalid",
    "unknown_command": "Guest command is not supported",
    "unknown_error": "Guest command failed",
    "no_such_run": "No resumable guest run was found",
    "no_such_interrupt": "No matching guest interrupt was found",
    "permission_denied": "Guest command is not permitted",
    "not_supported": "Guest command is not supported",
}
_SUBMIT_NONCE_KEY = "syshin_ui_submit_nonce"
_AGENT_ASSISTANT_ID = "fe096781-5601-53d2-b2f6-0d3403f7e9ca"
_LIFECYCLE_EVENTS = frozenset(
    {"started", "running", "completed", "failed", "interrupted"}
)
_SAFE_FORWARD_HEADERS = frozenset(
    {
        b"access-control-allow-credentials",
        b"access-control-allow-headers",
        b"access-control-allow-origin",
        b"access-control-expose-headers",
        b"vary",
        b"x-accel-buffering",
    }
)


class GuestWireProjectionError(RuntimeError):
    """A downstream response cannot safely cross the public guest wire."""


class GuestStreamLimitError(GuestWireProjectionError):
    """A guest SSE connection crossed its reviewed response byte budget."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GuestWireProjectionError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise GuestWireProjectionError("non-finite JSON number")


def _load_json(body: bytes) -> Any:
    try:
        decoded = body.decode("utf-8")
        return json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (
        GuestWireProjectionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as error:
        if isinstance(error, GuestWireProjectionError):
            raise
        raise GuestWireProjectionError("invalid downstream JSON") from error


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeEncodeError,
        ValueError,
    ) as error:
        raise GuestWireProjectionError("projected JSON is invalid") from error


def _record(value: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise GuestWireProjectionError(f"{field_name} must be an object")
    return value


def _bounded_text(
    value: object,
    *,
    field_name: str,
    max_bytes: int = _MAX_TEXT_BYTES,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise GuestWireProjectionError(f"{field_name} must be text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise GuestWireProjectionError(
            f"{field_name} contains invalid Unicode"
        ) from error
    if len(encoded) > max_bytes or "\x00" in value:
        raise GuestWireProjectionError(f"{field_name} is outside its bound")
    return value


def _safe_id(value: object, *, field_name: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = _bounded_text(
        value,
        field_name=field_name,
        max_bytes=_MAX_ID_BYTES,
        allow_empty=False,
    )
    if _SAFE_ID.fullmatch(text) is None:
        raise GuestWireProjectionError(f"{field_name} is not a safe identifier")
    return text


def _project_message_id(value: object, *, message_type: str, field_name: str) -> str:
    """Keep checkpoint IDs server-owned while preserving assistant-ui correlation."""
    message_id = _safe_id(value, field_name=field_name)
    assert message_id is not None
    if message_type == "human":
        match = _GUEST_STORED_USER_MESSAGE_ID.fullmatch(message_id)
        if match is not None:
            return match.group(1)
    return message_id


def _safe_optional_text(
    value: object,
    *,
    field_name: str,
    max_bytes: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(
        value,
        field_name=field_name,
        max_bytes=max_bytes,
        allow_empty=False,
    )


def _enum_text(
    value: object,
    *,
    field_name: str,
    allowed: frozenset[str] | set[str],
) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GuestWireProjectionError(f"{field_name} is invalid")
    return value


def _project_public_json(
    value: object,
    *,
    field_name: str,
    depth: int = 0,
    containers: list[int] | None = None,
) -> Any:
    """Copy one bounded JSON value without preserving object identity."""

    if containers is None:
        containers = [0]
    if depth > _MAX_PUBLIC_JSON_DEPTH:
        raise GuestWireProjectionError(f"{field_name} is nested too deeply")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not -_MAX_TIMESTAMP <= value <= _MAX_TIMESTAMP:
            raise GuestWireProjectionError(f"{field_name} integer is outside its bound")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise GuestWireProjectionError(f"{field_name} number is not finite")
        return value
    if isinstance(value, str):
        return _bounded_text(
            value,
            field_name=field_name,
            max_bytes=_MAX_PUBLIC_JSON_STRING_BYTES,
        )
    if isinstance(value, list):
        containers[0] += 1
        if (
            containers[0] > _MAX_PUBLIC_JSON_CONTAINERS
            or len(value) > _MAX_PUBLIC_JSON_ITEMS
        ):
            raise GuestWireProjectionError(f"{field_name} list is outside its bound")
        return [
            _project_public_json(
                item,
                field_name=field_name,
                depth=depth + 1,
                containers=containers,
            )
            for item in value
        ]
    if isinstance(value, dict):
        containers[0] += 1
        if (
            containers[0] > _MAX_PUBLIC_JSON_CONTAINERS
            or len(value) > _MAX_PUBLIC_JSON_KEYS
        ):
            raise GuestWireProjectionError(f"{field_name} object is outside its bound")
        projected: dict[str, Any] = {}
        for key, item in value.items():
            projected_key = _bounded_text(
                key,
                field_name=f"{field_name} key",
                max_bytes=_MAX_PUBLIC_JSON_KEY_BYTES,
                allow_empty=False,
            )
            projected[projected_key] = _project_public_json(
                item,
                field_name=field_name,
                depth=depth + 1,
                containers=containers,
            )
        return projected
    raise GuestWireProjectionError(f"{field_name} is not JSON")


def _safe_submit_nonce(value: object, *, field_name: str) -> str:
    nonce = _bounded_text(
        value,
        field_name=field_name,
        max_bytes=36,
        allow_empty=False,
    )
    if _SAFE_SUBMIT_NONCE.fullmatch(nonce) is None:
        raise GuestWireProjectionError(f"{field_name} is invalid")
    try:
        parsed = UUID(nonce)
    except ValueError as error:
        raise GuestWireProjectionError(f"{field_name} is invalid") from error
    if parsed.version != 4 or str(parsed) != nonce:
        raise GuestWireProjectionError(f"{field_name} is invalid")
    return nonce


def _safe_interrupt_id(value: object, *, field_name: str) -> str:
    interrupt_id = _bounded_text(
        value,
        field_name=field_name,
        max_bytes=32,
        allow_empty=False,
    )
    if _SAFE_INTERRUPT_ID.fullmatch(interrupt_id) is None:
        raise GuestWireProjectionError(f"{field_name} is invalid")
    return interrupt_id


def _safe_citation(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("type") != "citation":
        return None
    result: dict[str, Any] = {"type": "citation"}
    for key, limit in (
        ("id", 1_000),
        ("title", 300),
        ("cited_text", 2_000),
    ):
        try:
            text = _safe_optional_text(
                value.get(key),
                field_name=f"citation {key}",
                max_bytes=limit,
            )
        except GuestWireProjectionError:
            return None
        if text is not None:
            result[key] = text
    raw_url = value.get("url")
    if raw_url is not None:
        try:
            url = _bounded_text(
                raw_url,
                field_name="citation URL",
                max_bytes=2_000,
                allow_empty=False,
            )
            parsed = urlsplit(url)
        except (GuestWireProjectionError, ValueError):
            return None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        result["url"] = url
    for key in ("start_index", "end_index"):
        index = value.get(key)
        if index is not None:
            if type(index) is not int or index < 0 or index > _MAX_TIMESTAMP:
                return None
            result[key] = index
    if len(result) == 1:
        return None
    return result


def _safe_annotations(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_CITATIONS:
        return []
    return [
        citation
        for candidate in value
        if (citation := _safe_citation(candidate)) is not None
    ]


def _project_text_block(value: object, *, field_name: str) -> dict[str, Any]:
    block = _record(value, field_name=field_name)
    if block.get("type") != "text":
        raise GuestWireProjectionError(f"{field_name} is not a text block")
    projected: dict[str, Any] = {
        "type": "text",
        "text": _bounded_text(
            block.get("text"),
            field_name=f"{field_name} text",
        ),
    }
    annotations = _safe_annotations(block.get("annotations"))
    if annotations:
        projected["annotations"] = annotations
    return projected


def _project_state_content(value: object) -> str | list[dict[str, Any]] | None:
    if isinstance(value, str):
        return _bounded_text(value, field_name="message content")
    if not isinstance(value, list) or len(value) > _MAX_CONTENT_BLOCKS:
        return None
    projected: list[dict[str, Any]] = []
    for candidate in value:
        if isinstance(candidate, str):
            projected.append(
                {
                    "type": "text",
                    "text": _bounded_text(
                        candidate,
                        field_name="message text block",
                    ),
                }
            )
            continue
        if not isinstance(candidate, dict):
            continue
        candidate_type = candidate.get("type")
        if isinstance(candidate_type, str) and candidate_type in {
            "text",
            "text_delta",
        }:
            text = _bounded_text(
                candidate.get("text"),
                field_name="message text block",
            )
            block: dict[str, Any] = {"type": "text", "text": text}
            annotations = _safe_annotations(candidate.get("annotations"))
            if annotations:
                block["annotations"] = annotations
            projected.append(block)
        # Reasoning, thinking, tools, data, and unknown blocks are omitted.
    return projected or None


def _project_state_messages(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_STATE_MESSAGES:
        raise GuestWireProjectionError("state messages are outside their bound")
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(value):
        if not isinstance(candidate, dict):
            continue
        raw_type = candidate.get("type", candidate.get("role"))
        message_type = (
            {
                "assistant": "ai",
                "ai": "ai",
                "human": "human",
                "user": "human",
            }.get(raw_type)
            if isinstance(raw_type, str)
            else None
        )
        if message_type is None:
            continue
        content = _project_state_content(candidate.get("content"))
        if content is None:
            continue
        try:
            message_id = _project_message_id(
                candidate.get("id"),
                message_type=message_type,
                field_name="state message id",
            )
        except GuestWireProjectionError:
            message_id = f"checkpoint-message-{index}"
        result.append(
            {
                "content": content,
                "id": message_id,
                "type": message_type,
            }
        )
    return result


def _project_interrupt_payload(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = {"schema", "kind", "title", "prompt", "input_hint"}
    if (
        not all(isinstance(key, str) for key in value)
        or set(value) - allowed
        or value.get("schema") != "syshin.rag.interrupt.v1"
        or not isinstance(value.get("kind"), str)
        or value.get("kind") not in {"approval", "input"}
    ):
        return None
    try:
        projected: dict[str, Any] = {
            "schema": "syshin.rag.interrupt.v1",
            "kind": value["kind"],
            "prompt": _bounded_text(
                value.get("prompt"),
                field_name="interrupt prompt",
                max_bytes=480,
                allow_empty=False,
            ),
        }
        for key, limit in (("title", 160), ("input_hint", 160)):
            text = _safe_optional_text(
                value.get(key),
                field_name=f"interrupt {key}",
                max_bytes=limit,
            )
            if text is not None:
                projected[key] = text
        return projected
    except GuestWireProjectionError:
        return None


def _project_state_interrupts(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1:
        raise GuestWireProjectionError("state interrupts are ambiguous")
    if not value:
        return []
    candidate = _record(value[0], field_name="state interrupt")
    interrupt_id = _safe_interrupt_id(
        candidate.get("interrupt_id", candidate.get("id")),
        field_name="interrupt id",
    )
    namespace = candidate.get("ns", [])
    if namespace != []:
        raise GuestWireProjectionError("only root interrupts are public")
    result: dict[str, Any] = {
        "id": interrupt_id,
        "ns": [],
        "resumable": candidate.get("resumable") is not False,
        "when": "before" if candidate.get("when") == "before" else "during",
    }
    payload = _project_interrupt_payload(
        candidate.get("value", candidate.get("payload"))
    )
    if payload is not None:
        result["value"] = payload
    return [result]


def _project_datetime(
    value: object,
    *,
    field_name: str,
    allow_none: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    text = _bounded_text(
        value,
        field_name=field_name,
        max_bytes=64,
        allow_empty=False,
    )
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise GuestWireProjectionError(f"{field_name} is invalid") from error
    if timestamp.tzinfo is None:
        raise GuestWireProjectionError(f"{field_name} must include a timezone")
    return text


def _project_checkpoint(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    checkpoint = _record(value, field_name="checkpoint")
    checkpoint_id = _safe_id(
        checkpoint.get("checkpoint_id"),
        field_name="checkpoint id",
        allow_none=True,
    )
    namespace = checkpoint.get("checkpoint_ns", "")
    if namespace is not None and namespace != "":
        raise GuestWireProjectionError("only root checkpoints are public")
    return {
        "checkpoint_id": checkpoint_id,
        "checkpoint_ns": "",
    }


def _project_state(value: object, *, include_interrupts: bool) -> dict[str, Any]:
    state = _record(value, field_name="thread state")
    values = _record(state.get("values"), field_name="thread state values")
    checkpoint = _project_checkpoint(state.get("checkpoint"))
    if checkpoint is None:
        checkpoint = {"checkpoint_id": None, "checkpoint_ns": ""}
    parent_checkpoint = _project_checkpoint(state.get("parent_checkpoint"))
    return {
        "checkpoint": checkpoint,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "created_at": _project_datetime(
            state.get("created_at"),
            field_name="state created_at",
            allow_none=True,
        ),
        "interrupts": (
            _project_state_interrupts(state.get("interrupts", []))
            if include_interrupts
            else []
        ),
        "metadata": {},
        "next": [],
        "parent_checkpoint": parent_checkpoint,
        "parent_checkpoint_id": (
            parent_checkpoint["checkpoint_id"]
            if parent_checkpoint is not None
            else None
        ),
        "tasks": [],
        "values": {
            "messages": _project_state_messages(values.get("messages", [])),
        },
    }


def _project_thread_metadata(value: object) -> dict[str, Any]:
    metadata = _record(value, field_name="thread metadata")
    projected: dict[str, Any] = {}
    if "archived" in metadata:
        archived = metadata["archived"]
        if type(archived) is not bool:
            raise GuestWireProjectionError("thread archived flag is invalid")
        projected["archived"] = archived
    if "title" in metadata:
        projected["title"] = _bounded_text(
            metadata["title"],
            field_name="thread title",
            max_bytes=512,
            allow_empty=False,
        )
    if "title_status" in metadata:
        projected["title_status"] = _enum_text(
            metadata["title_status"],
            field_name="thread title status",
            allowed={"pending", "manual", "generated"},
        )
    if "graph_id" in metadata and metadata["graph_id"] is not None:
        if metadata["graph_id"] != "agent":
            raise GuestWireProjectionError("thread graph id is invalid")
        projected["graph_id"] = "agent"
    if "custom" in metadata:
        custom = _project_public_json(
            metadata["custom"],
            field_name="thread custom metadata",
        )
        if not isinstance(custom, dict):
            raise GuestWireProjectionError("thread custom metadata must be an object")
        if len(_canonical_json(custom)) > _MAX_PUBLIC_CUSTOM_BYTES:
            raise GuestWireProjectionError(
                "thread custom metadata exceeded its byte budget"
            )
        projected["custom"] = custom
    return projected


def _project_thread(value: object) -> dict[str, Any]:
    thread = _record(value, field_name="thread")
    status = _enum_text(
        thread.get("status"),
        field_name="thread status",
        allowed=_THREAD_STATUSES,
    )
    return {
        "created_at": _project_datetime(
            thread.get("created_at"),
            field_name="thread created_at",
        ),
        "metadata": _project_thread_metadata(thread.get("metadata")),
        "status": status,
        "thread_id": _safe_id(
            thread.get("thread_id"),
            field_name="thread id",
        ),
        "updated_at": _project_datetime(
            thread.get("updated_at"),
            field_name="thread updated_at",
        ),
    }


def _project_run_nonce(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    record = _record(value, field_name=field_name)
    if _SUBMIT_NONCE_KEY not in record:
        return None
    return _safe_submit_nonce(
        record[_SUBMIT_NONCE_KEY],
        field_name=f"{field_name} submit nonce",
    )


def _project_run(value: object) -> dict[str, Any]:
    run = _record(value, field_name="run")
    status = _enum_text(
        run.get("status"),
        field_name="run status",
        allowed=_RUN_STATUSES,
    )
    if run.get("assistant_id") != _AGENT_ASSISTANT_ID:
        raise GuestWireProjectionError("run assistant id is invalid")

    config = run.get("config")
    config_record = {} if config is None else _record(config, field_name="run config")
    config_nonce = _project_run_nonce(
        config_record.get("metadata"),
        field_name="run config metadata",
    )
    top_level_nonce = _project_run_nonce(
        run.get("metadata"),
        field_name="run metadata",
    )
    observed_nonces = {
        nonce for nonce in (config_nonce, top_level_nonce) if nonce is not None
    }
    if len(observed_nonces) > 1:
        raise GuestWireProjectionError("run submit nonce is ambiguous")

    projected_config: dict[str, Any] = {}
    if config_nonce is not None:
        projected_config = {"metadata": {_SUBMIT_NONCE_KEY: config_nonce}}

    projected: dict[str, Any] = {
        "assistant_id": "agent",
        "config": projected_config,
        "created_at": _project_datetime(
            run.get("created_at"),
            field_name="run created_at",
        ),
        "run_id": _safe_id(run.get("run_id"), field_name="run id"),
        "status": status,
        "thread_id": _safe_id(
            run.get("thread_id"),
            field_name="run thread id",
        ),
        "updated_at": _project_datetime(
            run.get("updated_at"),
            field_name="run updated_at",
        ),
    }
    if top_level_nonce is not None:
        projected["metadata"] = {_SUBMIT_NONCE_KEY: top_level_nonce}
    return projected


def _project_command_response(value: object) -> dict[str, Any]:
    response = _record(value, field_name="command response")
    command_id = response.get("id")
    if command_id is not None and (
        type(command_id) is not int or not 0 <= command_id <= 2**31 - 1
    ):
        raise GuestWireProjectionError("command response id is invalid")
    response_type = response.get("type")
    if response_type == "success":
        if command_id is None:
            raise GuestWireProjectionError("command success id is missing")
        result = _record(response.get("result"), field_name="command result")
        if set(result) != {"run_id"}:
            raise GuestWireProjectionError("command result fields are invalid")
        projected: dict[str, Any] = {
            "id": command_id,
            "result": {
                "run_id": _safe_id(
                    result.get("run_id"),
                    field_name="command run id",
                )
            },
            "type": "success",
        }
        if "meta" in response:
            meta = _record(response["meta"], field_name="command metadata")
            if set(meta) != {"applied_through_seq"}:
                raise GuestWireProjectionError("command metadata fields are invalid")
            applied = meta["applied_through_seq"]
            if type(applied) is not int or not 0 <= applied <= _MAX_TIMESTAMP:
                raise GuestWireProjectionError("command applied sequence is invalid")
            projected["meta"] = {"applied_through_seq": applied}
        return projected
    if response_type == "error":
        error = _enum_text(
            response.get("error"),
            field_name="command error code",
            allowed=_COMMAND_ERRORS,
        )
        return {
            "error": error,
            "id": command_id,
            "message": _COMMAND_ERROR_MESSAGES[error],
            "type": "error",
        }
    raise GuestWireProjectionError("command response type is invalid")


def project_guest_json_response(kind: str, body: bytes) -> bytes:
    """Project one successful pinned-Aegra JSON response."""

    value = _load_json(body)
    if kind == "state":
        projected: Any = _project_state(value, include_interrupts=True)
    elif kind == "history":
        if not isinstance(value, list) or len(value) > _MAX_HISTORY_STATES:
            raise GuestWireProjectionError("thread history is outside its bound")
        projected = [_project_state(state, include_interrupts=False) for state in value]
    elif kind in {"thread-create", "thread-read", "thread-update"}:
        projected = _project_thread(value)
    elif kind == "thread-search":
        if not isinstance(value, list) or len(value) > _MAX_THREADS:
            raise GuestWireProjectionError("thread search is outside its bound")
        projected = [_project_thread(thread) for thread in value]
    elif kind in {"run", "cancel"}:
        projected = _project_run(value)
    elif kind == "runs":
        if not isinstance(value, list) or len(value) > _MAX_RUNS:
            raise GuestWireProjectionError("run list is outside its bound")
        projected = [_project_run(run) for run in value]
    elif kind == "command":
        projected = _project_command_response(value)
    else:
        raise GuestWireProjectionError("unsupported JSON projection")
    encoded = _canonical_json(projected)
    if len(encoded) > _MAX_PROJECTED_JSON_BYTES:
        raise GuestWireProjectionError("projected JSON exceeded its byte budget")
    return encoded


def _project_tool_content(
    value: object,
    *,
    field_name: str,
    finalized: bool,
) -> dict[str, Any]:
    block = _record(value, field_name=field_name)
    _enum_text(
        block.get("type"),
        field_name=f"{field_name} type",
        allowed={"tool_call", "tool_call_chunk"},
    )
    raw_id = block.get("id")
    tool_call_id = (
        _safe_id(raw_id, field_name="tool call id", allow_none=True)
        if raw_id is not None
        else None
    )
    raw_name = block.get("name")
    tool_name = (
        _safe_id(raw_name, field_name="tool name", allow_none=True)
        if raw_name is not None
        else None
    )
    if finalized and (tool_call_id is None or tool_name is None):
        raise GuestWireProjectionError("final tool call identity is missing")
    return {
        "type": "tool_call" if finalized else "tool_call_chunk",
        "id": tool_call_id,
        "name": tool_name,
        "args": {} if finalized else "",
    }


@dataclass(slots=True)
class _MessageProjectionState:
    suppressed: bool
    blocks: dict[int, tuple[str, int | None]] = field(default_factory=dict)
    next_public_index: int = 0


class GuestEventProjector:
    """Project complete pinned-Aegra event envelopes to the public subset."""

    def __init__(self) -> None:
        self._message: _MessageProjectionState | None = None

    def project(self, value: object) -> dict[str, Any] | None:
        envelope = _record(value, field_name="event envelope")
        if set(envelope) - {"event_id", "method", "params", "seq", "type"}:
            raise GuestWireProjectionError("event envelope fields are invalid")
        if envelope.get("type") != "event":
            raise GuestWireProjectionError("event envelope type is invalid")
        method = _enum_text(
            envelope.get("method"),
            field_name="event method",
            allowed={
                "custom",
                "input.requested",
                "lifecycle",
                "messages",
                "tools",
            },
        )
        seq = envelope.get("seq")
        if type(seq) is not int or not 0 <= seq <= _MAX_TIMESTAMP:
            raise GuestWireProjectionError("event sequence is invalid")
        event_id = _safe_id(
            envelope.get("event_id"),
            field_name="event id",
        )
        params = _record(envelope.get("params"), field_name="event params")
        if set(params) - {"data", "namespace", "node", "timestamp"}:
            raise GuestWireProjectionError("event params fields are invalid")
        if params.get("namespace") != []:
            raise GuestWireProjectionError("only root events are public")
        timestamp = params.get("timestamp")
        if type(timestamp) is not int or not 0 <= timestamp <= _MAX_TIMESTAMP:
            raise GuestWireProjectionError("event timestamp is invalid")
        data = _record(params.get("data"), field_name="event data")

        projected_data = self._project_data(method, data)
        if projected_data is None:
            return None
        return {
            "event_id": event_id,
            "method": method,
            "params": {
                "data": projected_data,
                "namespace": [],
                "timestamp": timestamp,
            },
            "seq": seq,
            "type": "event",
        }

    def _project_data(
        self,
        method: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if method == "lifecycle":
            return self._project_lifecycle(data)
        if method == "messages":
            return self._project_message(data)
        if method == "tools":
            return self._project_tool(data)
        if method == "input.requested":
            return self._project_input(data)
        return self._project_custom(data)

    @staticmethod
    def _project_lifecycle(data: dict[str, Any]) -> dict[str, Any]:
        event = _enum_text(
            data.get("event"),
            field_name="lifecycle status",
            allowed=_LIFECYCLE_EVENTS,
        )
        projected = {"event": event}
        if data.get("graph_name") == "agent":
            projected["graph_name"] = "agent"
        return projected

    def _project_message(self, data: dict[str, Any]) -> dict[str, Any] | None:
        event = data.get("event")
        if not isinstance(event, str):
            raise GuestWireProjectionError("message event type is invalid")
        if event == "message-start":
            if self._message is not None:
                raise GuestWireProjectionError("message streams overlap")
            role = data.get("role")
            normalized_role = (
                {
                    "assistant": "ai",
                    "ai": "ai",
                    "human": "human",
                    "user": "human",
                    "system": "system",
                }.get(role)
                if isinstance(role, str)
                else None
            )
            if normalized_role is None:
                raise GuestWireProjectionError("message role is invalid")
            message_id = _project_message_id(
                data.get("id"),
                message_type=normalized_role,
                field_name="message id",
            )
            suppressed = normalized_role == "system"
            self._message = _MessageProjectionState(suppressed=suppressed)
            if suppressed:
                return None
            return {
                "event": "message-start",
                "role": normalized_role,
                "id": message_id,
            }

        message = self._message
        if message is None:
            raise GuestWireProjectionError("message event has no active message")
        if event == "content-block-start":
            index = self._block_index(data.get("index"))
            if index in message.blocks:
                raise GuestWireProjectionError("message block index was reused")
            if message.suppressed:
                message.blocks[index] = ("suppressed", None)
                return None
            content = _record(
                data.get("content"),
                field_name="message content block",
            )
            block_type = content.get("type")
            if not isinstance(block_type, str):
                raise GuestWireProjectionError("message block type is invalid")
            if block_type in {"reasoning", "thinking", "redacted_thinking"}:
                message.blocks[index] = ("suppressed", None)
                return None
            public_index = message.next_public_index
            message.next_public_index += 1
            if block_type == "text":
                message.blocks[index] = ("text", public_index)
                projected = _project_text_block(
                    content,
                    field_name="message content block",
                )
            elif block_type in {"tool_call", "tool_call_chunk"}:
                message.blocks[index] = ("tool", public_index)
                projected = _project_tool_content(
                    content,
                    field_name="message tool block",
                    finalized=False,
                )
            else:
                raise GuestWireProjectionError("message block type is not public")
            return {
                "event": "content-block-start",
                "index": public_index,
                "content": projected,
            }
        if event == "content-block-delta":
            index = self._block_index(data.get("index"))
            block = message.blocks.get(index)
            if block is None:
                raise GuestWireProjectionError("message delta has no open block")
            block_type, public_index = block
            if block_type == "suppressed" or message.suppressed:
                return None
            if public_index is None:
                raise GuestWireProjectionError("public message block index is missing")
            delta = _record(data.get("delta"), field_name="message delta")
            if block_type == "text":
                if delta.get("type") != "text-delta":
                    raise GuestWireProjectionError("text delta type is invalid")
                projected_delta = {
                    "type": "text-delta",
                    "text": _bounded_text(
                        delta.get("text"),
                        field_name="message text delta",
                    ),
                }
            else:
                if delta.get("type") != "block-delta":
                    raise GuestWireProjectionError("tool delta type is invalid")
                fields = _record(
                    delta.get("fields"),
                    field_name="tool delta fields",
                )
                _enum_text(
                    fields.get("type"),
                    field_name="tool delta fields type",
                    allowed={"tool_call", "tool_call_chunk"},
                )
                projected_fields: dict[str, Any] = {
                    "type": "tool_call_chunk",
                    "args": "",
                }
                if fields.get("id") is not None:
                    projected_fields["id"] = _safe_id(
                        fields["id"],
                        field_name="tool delta id",
                    )
                if fields.get("name") is not None:
                    projected_fields["name"] = _safe_id(
                        fields["name"],
                        field_name="tool delta name",
                    )
                projected_delta = {
                    "type": "block-delta",
                    "fields": projected_fields,
                }
            return {
                "event": "content-block-delta",
                "index": public_index,
                "delta": projected_delta,
            }
        if event == "content-block-finish":
            index = self._block_index(data.get("index"))
            block = message.blocks.pop(index, None)
            if block is None:
                raise GuestWireProjectionError("message finish has no open block")
            block_type, public_index = block
            if block_type == "suppressed" or message.suppressed:
                return None
            if public_index is None:
                raise GuestWireProjectionError("public message block index is missing")
            if block_type == "text":
                projected = _project_text_block(
                    data.get("content"),
                    field_name="final message text block",
                )
            else:
                projected = _project_tool_content(
                    data.get("content"),
                    field_name="final message tool block",
                    finalized=True,
                )
            return {
                "event": "content-block-finish",
                "index": public_index,
                "content": projected,
            }
        if event == "message-finish":
            if message.blocks:
                raise GuestWireProjectionError("message finished with open blocks")
            self._message = None
            return None if message.suppressed else {"event": "message-finish"}
        if event in {"error", "message-error"}:
            self._message = None
            if message.suppressed:
                return None
            return {
                "event": "error",
                "message": "The assistant message could not be completed",
            }
        raise GuestWireProjectionError("message event type is invalid")

    @staticmethod
    def _block_index(value: object) -> int:
        if type(value) is not int or not 0 <= value < _MAX_CONTENT_BLOCKS:
            raise GuestWireProjectionError("message block index is invalid")
        return value

    @staticmethod
    def _project_tool(data: dict[str, Any]) -> dict[str, Any] | None:
        event = data.get("event")
        tool_call_id = _safe_id(
            data.get("tool_call_id"),
            field_name="tool event id",
        )
        if event == "tool-started":
            tool_name = _safe_id(data.get("tool_name"), field_name="tool name")
            return {
                "event": "tool-started",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
            }
        if event == "tool-output-delta":
            return None
        if event == "tool-finished":
            return {
                "event": "tool-finished",
                "tool_call_id": tool_call_id,
                "output": None,
            }
        if event == "tool-error":
            return {
                "event": "tool-error",
                "tool_call_id": tool_call_id,
                "message": "The tool could not be completed",
            }
        raise GuestWireProjectionError("tool event type is invalid")

    @staticmethod
    def _project_input(data: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {
            "interrupt_id": _safe_interrupt_id(
                data.get("interrupt_id"),
                field_name="input interrupt id",
            )
        }
        payload = _project_interrupt_payload(data.get("payload", data.get("value")))
        if payload is not None:
            # Aegra's direct event consumers read ``value`` while the pinned
            # LangGraph SDK ThreadStream records ``payload`` in `interrupts`.
            # Both aliases carry the exact same already-sanitized object.
            projected["payload"] = payload
            projected["value"] = payload
        return projected

    @staticmethod
    def _project_custom(data: dict[str, Any]) -> dict[str, Any] | None:
        if data.get("name") != INSPECTION_EVENT_NAME:
            return None
        try:
            payload = normalize_retrieval_inspection(data.get("payload"))
        except InspectionContractError as error:
            raise GuestWireProjectionError(
                "inspection event failed its public contract"
            ) from error
        return {
            "name": INSPECTION_EVENT_NAME,
            "payload": payload,
        }


def _header_values(
    headers: list[tuple[bytes, bytes]],
    name: bytes,
) -> list[bytes]:
    return [value for key, value in headers if key.lower() == name]


def _forward_response_headers(
    headers: list[tuple[bytes, bytes]],
) -> list[tuple[bytes, bytes]]:
    result: list[tuple[bytes, bytes]] = []
    for key, value in headers:
        lower = key.lower()
        if lower not in _SAFE_FORWARD_HEADERS:
            continue
        if (
            len(key) > 128
            or len(value) > 2_048
            or b"\r" in key
            or b"\n" in key
            or b"\r" in value
            or b"\n" in value
        ):
            continue
        result.append((lower, value))
    return result


def _validate_content_type(
    headers: list[tuple[bytes, bytes]],
    *,
    expected: bytes,
) -> None:
    values = _header_values(headers, b"content-type")
    if len(values) != 1:
        raise GuestWireProjectionError("downstream content type is ambiguous")
    media_type, separator, parameters = values[0].partition(b";")
    if media_type.strip().lower() != expected:
        raise GuestWireProjectionError("downstream content type is invalid")
    if parameters and parameters.strip().lower() != b"charset=utf-8":
        raise GuestWireProjectionError("downstream content charset is invalid")
    if separator and not parameters:
        raise GuestWireProjectionError("downstream content type is invalid")


def _safe_error(status: int) -> tuple[int, bytes]:
    if status == 404:
        return 404, _canonical_json({"detail": "Not Found"})
    if 400 <= status < 500:
        return status, _canonical_json(
            {
                "error": "request_failed",
                "message": "Guest request failed",
            }
        )
    return 503, _canonical_json(
        {
            "error": "service_unavailable",
            "message": "Guest response is unavailable",
        }
    )


def _json_start(
    status: int,
    body: bytes,
    original_headers: list[tuple[bytes, bytes]],
) -> Message:
    headers = _forward_response_headers(original_headers)
    headers.extend(
        [
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"content-type", b"application/json"),
        ]
    )
    return {
        "type": "http.response.start",
        "status": status,
        "headers": headers,
    }


class GuestJSONResponseSend:
    """Buffer and replace one allowlisted guest JSON response before first bytes."""

    def __init__(self, send: Send, *, kind: str) -> None:
        self._send = send
        self._kind = kind
        self._start: Message | None = None
        self._body = bytearray()

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            if self._start is not None:
                raise GuestWireProjectionError("duplicate response start")
            self._start = message
            return
        if message["type"] != "http.response.body":
            raise GuestWireProjectionError("unexpected response message")
        if self._start is None:
            raise GuestWireProjectionError("response body preceded response start")
        chunk = message.get("body", b"")
        self._body.extend(chunk)
        if len(self._body) > _MAX_JSON_RESPONSE_BYTES:
            raise GuestWireProjectionError("downstream JSON exceeded its byte budget")
        if message.get("more_body", False):
            return

        status = int(self._start["status"])
        original_headers = list(self._start.get("headers", []))
        if 200 <= status < 300:
            _validate_content_type(original_headers, expected=b"application/json")
            projected = project_guest_json_response(
                self._kind,
                bytes(self._body),
            )
            output_status = status
        else:
            output_status, projected = _safe_error(status)
        await self._send(_json_start(output_status, projected, original_headers))
        await self._send(
            {
                "type": "http.response.body",
                "body": projected,
                "more_body": False,
            }
        )


class GuestSSEResponseSend:
    """Frame-aware SSE projection that never forwards unvalidated event bytes."""

    def __init__(self, send: Send) -> None:
        self._send = send
        self._projector = GuestEventProjector()
        self._started = False
        self._streaming = False
        self._start: Message | None = None
        self._error_body = bytearray()
        self._buffer = bytearray()
        self._raw_total = 0
        self._output_total = 0

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            await self._response_start(message)
            return
        if message["type"] != "http.response.body":
            raise GuestWireProjectionError("unexpected SSE response message")
        if not self._started or self._start is None:
            raise GuestWireProjectionError("SSE body preceded response start")
        if not self._streaming:
            await self._error_response_body(message)
            return

        body = message.get("body", b"")
        self._raw_total += len(body)
        if (
            len(body) > GUEST_MAX_SSE_CHUNK_BYTES
            or self._raw_total > GUEST_MAX_SSE_TOTAL_BYTES
        ):
            raise GuestStreamLimitError("guest SSE response exceeded its byte budget")
        self._buffer.extend(body)
        output = self._project_complete_frames()
        if not message.get("more_body", False) and self._buffer:
            raise GuestWireProjectionError("SSE stream ended inside a frame")
        self._output_total += len(output)
        if self._output_total > GUEST_MAX_SSE_TOTAL_BYTES:
            raise GuestStreamLimitError("projected guest SSE exceeded its byte budget")
        if output or not message.get("more_body", False):
            await self._send(
                {
                    "type": "http.response.body",
                    "body": output,
                    "more_body": bool(message.get("more_body", False)),
                }
            )

    async def _response_start(self, message: Message) -> None:
        if self._started:
            raise GuestWireProjectionError("duplicate SSE response start")
        self._started = True
        self._start = message
        status = int(message["status"])
        headers = list(message.get("headers", []))
        if not 200 <= status < 300:
            return
        _validate_content_type(headers, expected=b"text/event-stream")
        projected_headers = [
            header
            for header in _forward_response_headers(headers)
            if header[0] != b"x-accel-buffering"
        ]
        projected_headers.extend(
            [
                (b"cache-control", b"no-store"),
                (b"content-type", b"text/event-stream"),
                (b"x-accel-buffering", b"no"),
            ]
        )
        self._streaming = True
        await self._send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": projected_headers,
            }
        )

    async def _error_response_body(self, message: Message) -> None:
        chunk = message.get("body", b"")
        self._error_body.extend(chunk)
        if len(self._error_body) > GUEST_MAX_SSE_CHUNK_BYTES:
            raise GuestStreamLimitError(
                "guest SSE error response exceeded its byte budget"
            )
        if message.get("more_body", False):
            return
        assert self._start is not None
        status, body = _safe_error(int(self._start["status"]))
        headers = list(self._start.get("headers", []))
        await self._send(_json_start(status, body, headers))
        await self._send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )

    def _project_complete_frames(self) -> bytes:
        output = bytearray()
        while True:
            separator = _frame_separator(self._buffer)
            if separator is None:
                if len(self._buffer) > GUEST_MAX_SSE_CHUNK_BYTES:
                    raise GuestStreamLimitError(
                        "guest SSE frame exceeded its byte budget"
                    )
                return bytes(output)
            index, width = separator
            frame = bytes(self._buffer[:index])
            del self._buffer[: index + width]
            projected = self._project_frame(frame)
            output.extend(projected)

    def _project_frame(self, frame: bytes) -> bytes:
        if frame in {b": heartbeat", b": heartbeat\r"}:
            return b": heartbeat\n\n"
        try:
            text = frame.decode("utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError as error:
            raise GuestWireProjectionError("SSE frame is not UTF-8") from error
        if "\r" in text:
            raise GuestWireProjectionError("SSE frame uses invalid line endings")
        fields: dict[str, str] = {}
        for line in text.split("\n"):
            name, separator, raw_value = line.partition(":")
            if not separator or name not in {"data", "event", "id"}:
                raise GuestWireProjectionError("SSE frame field is invalid")
            if name in fields:
                raise GuestWireProjectionError("SSE frame field is duplicated")
            fields[name] = raw_value[1:] if raw_value.startswith(" ") else raw_value
        if set(fields) != {"data", "event", "id"}:
            raise GuestWireProjectionError("SSE frame fields are incomplete")
        event_name = fields["event"]
        event_id = fields["id"]
        if (
            not event_id.isascii()
            or not event_id.isdecimal()
            or int(event_id) > _MAX_TIMESTAMP
        ):
            raise GuestWireProjectionError("SSE id is invalid")
        envelope = _load_json(fields["data"].encode("utf-8"))
        projected = self._projector.project(envelope)
        if projected is None:
            return b""
        if projected["method"] != event_name or projected["seq"] != int(event_id):
            raise GuestWireProjectionError("SSE frame does not match its envelope")
        return (
            f"event: {event_name}\n"
            f"data: {_canonical_json(projected).decode('utf-8')}\n"
            f"id: {event_id}\n\n"
        ).encode()


def _frame_separator(buffer: bytearray) -> tuple[int, int] | None:
    lf_index = buffer.find(b"\n\n")
    crlf_index = buffer.find(b"\r\n\r\n")
    candidates = [
        candidate for candidate in ((lf_index, 2), (crlf_index, 4)) if candidate[0] >= 0
    ]
    return min(candidates, default=None)


__all__ = [
    "GUEST_MAX_SSE_CHUNK_BYTES",
    "GUEST_MAX_SSE_TOTAL_BYTES",
    "GuestEventProjector",
    "GuestJSONResponseSend",
    "GuestSSEResponseSend",
    "GuestStreamLimitError",
    "GuestWireProjectionError",
    "project_guest_json_response",
]
