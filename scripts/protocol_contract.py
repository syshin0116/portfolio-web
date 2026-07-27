#!/usr/bin/env python3
"""Validate the locked Agent Protocol v2 bindings and replay fixtures.

The payload adapters come from the exact generated Python binding committed
under ``protocol/generated``. This module adds only transport and lifecycle
invariants that the upstream TypedDict package intentionally does not enforce.
It never fetches the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import TypeAdapter, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = REPO_ROOT / "protocol"
LOCK_PATH = PROTOCOL_ROOT / "agent-protocol.lock.json"
FIXTURES_ROOT = PROTOCOL_ROOT / "fixtures"
PYTHON_BINDING_PATH = PROTOCOL_ROOT / "generated/python/protocol.py"

REQUIRED_COVERAGE = frozenset(
    {
        "content_blocks",
        "tool_lifecycle",
        "run_lifecycle",
        "nested_namespace",
        "replay_disconnect",
        "hitl",
        "hitl_update_goto",
        "structured_error",
        "aegra_translation",
    }
)


class ContractError(ValueError):
    """A locked artifact or fixture does not satisfy the protocol contract."""


@dataclass(frozen=True)
class FixtureReport:
    path: Path
    records: int
    events: int
    coverage: frozenset[str]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(
    condition: bool,
    message: str,
    *,
    path: Path | None = None,
    record: int | None = None,
) -> None:
    if condition:
        return
    location = ""
    if path is not None:
        location = _display_path(path)
    if record is not None:
        location = f"{location}:record[{record}]"
    raise ContractError(f"{location}: {message}" if location else message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock() -> dict[str, Any]:
    try:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {LOCK_PATH}: {exc}") from exc

    _require(lock.get("lockVersion") == 1, "unsupported protocol lock version")
    protocol = lock.get("protocol")
    _require(isinstance(protocol, dict), "protocol lock is missing protocol")
    commit = protocol.get("commit")
    _require(
        isinstance(commit, str)
        and len(commit) == 40
        and all(character in "0123456789abcdef" for character in commit),
        "protocol commit must be a full lowercase SHA-1",
    )

    artifacts = protocol.get("artifacts")
    _require(isinstance(artifacts, dict), "protocol lock is missing artifacts")
    for artifact_name in ("openapi", "cddl", "pythonBinding", "typescriptBinding"):
        artifact = artifacts.get(artifact_name)
        _require(isinstance(artifact, dict), f"missing locked artifact {artifact_name}")
        digest = artifact.get("sha256")
        _require(
            isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest),
            f"{artifact_name} must have a lowercase SHA-256",
        )
        vendored_path = artifact.get("vendoredPath")
        if vendored_path is not None:
            path = REPO_ROOT / vendored_path
            _require(path.is_file(), f"vendored artifact is missing: {vendored_path}")
            _require(
                _sha256(path) == digest,
                f"vendored artifact hash differs from lock: {vendored_path}",
            )

    matrix = lock.get("aegra", {}).get("supportMatrix")
    _require(isinstance(matrix, list) and matrix, "Aegra support matrix is empty")
    _require(
        any(
            isinstance(item, dict)
            and item.get("capability") == "Thread-centric SSE stream"
            and item.get("status") == "path-divergence"
            for item in matrix
        ),
        "Aegra /stream/events path divergence must remain explicit",
    )
    return lock


def _load_binding() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "syshin0116_locked_agent_protocol",
        PYTHON_BINDING_PATH,
    )
    _require(spec is not None and spec.loader is not None, "cannot load Python binding")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_BINDING = _load_binding()
_ADAPTERS = {
    "stream_request": TypeAdapter(_BINDING.EventStreamRequest),
    "command": TypeAdapter(_BINDING.Command),
    "command_success": TypeAdapter(_BINDING.CommandResponse),
    "command_error": TypeAdapter(_BINDING.ErrorResponse),
    "event": TypeAdapter(_BINDING.Event),
    "lifecycle": TypeAdapter(_BINDING.LifecycleData),
    "messages": TypeAdapter(_BINDING.MessagesData),
    "tools": TypeAdapter(_BINDING.ToolsData),
    "input.requested": TypeAdapter(_BINDING.InputRequestedData),
    "updates": TypeAdapter(_BINDING.UpdatesData),
    "checkpoints": TypeAdapter(_BINDING.Checkpoint),
    "custom": TypeAdapter(_BINDING.CustomData),
}


def _validate_with_binding(
    adapter_name: str,
    payload: object,
    *,
    path: Path,
    record: int,
) -> None:
    try:
        _ADAPTERS[adapter_name].validate_python(payload)
    except ValidationError as exc:
        raise ContractError(
            f"{_display_path(path)}:record[{record}]: "
            f"{adapter_name} does not match the locked generated binding: {exc}"
        ) from exc


def _validate_event(
    payload: dict[str, Any],
    *,
    path: Path,
    record: int,
) -> None:
    _validate_with_binding("event", payload, path=path, record=record)
    _require(
        _is_int(payload.get("seq")) and payload["seq"] >= 0,
        "fixtures require a non-negative seq for replay",
        path=path,
        record=record,
    )
    _require(
        isinstance(payload.get("event_id"), str) and payload["event_id"],
        "fixtures require event_id for deduplication",
        path=path,
        record=record,
    )

    params = payload.get("params")
    _require(
        isinstance(params, dict),
        "event params must be an object",
        path=path,
        record=record,
    )
    namespace = params.get("namespace")
    _require(
        isinstance(namespace, list)
        and all(isinstance(part, str) and part for part in namespace),
        "event namespace must be a string path",
        path=path,
        record=record,
    )
    timestamp = params.get("timestamp")
    _require(
        _is_int(timestamp) and timestamp >= 0,
        "event timestamp must be non-negative epoch milliseconds",
        path=path,
        record=record,
    )
    method = payload.get("method")
    data = params.get("data")
    if method in _ADAPTERS:
        _validate_with_binding(method, data, path=path, record=record)
    elif method not in {"values", "tasks"} and not (
        isinstance(method, str) and method.startswith("custom:")
    ):
        raise ContractError(
            f"{_display_path(path)}:record[{record}]: unsupported event method {method!r}"
        )


def _message_key(payload: dict[str, Any]) -> tuple[tuple[str, ...], str | None]:
    params = payload["params"]
    return tuple(params["namespace"]), params.get("node")


def _validate_lifecycle_invariants(
    path: Path,
    event_payloads: list[dict[str, Any]],
) -> set[str]:
    coverage: set[str] = set()
    active_messages: dict[tuple[tuple[str, ...], str | None], dict[str, Any]] = {}
    active_tools: set[tuple[tuple[str, ...], str]] = set()
    lifecycle_seen: dict[tuple[str, ...], str] = {}

    for payload in event_payloads:
        method = payload["method"]
        params = payload["params"]
        namespace = tuple(params["namespace"])
        data = params["data"]

        if namespace:
            coverage.add("nested_namespace")

        if method == "lifecycle":
            coverage.add("run_lifecycle")
            event = data["event"]
            previous = lifecycle_seen.get(namespace)
            if event in {"started", "running"}:
                # A thread stream spans multiple runs. A namespace can therefore
                # start again after its previous run reached a terminal state.
                pass
            elif event in {"completed", "failed", "interrupted"}:
                _require(
                    previous in {"started", "running"},
                    f"namespace {namespace!r} terminated without a start",
                    path=path,
                )
            lifecycle_seen[namespace] = event
            continue

        if method == "messages":
            coverage.add("content_blocks")
            key = _message_key(payload)
            event = data["event"]
            if event == "message-start":
                _require(
                    key not in active_messages,
                    "message-start interleaves messages",
                    path=path,
                )
                active_messages[key] = {
                    "id": data["id"],
                    "block": None,
                    "text": None,
                }
            elif event == "content-block-start":
                _require(
                    key in active_messages,
                    "content block starts outside a message",
                    path=path,
                )
                _require(
                    active_messages[key]["block"] is None,
                    "content blocks interleave within a message",
                    path=path,
                )
                active_messages[key]["block"] = data["index"]
                content = data["content"]
                active_messages[key]["text"] = (
                    content["text"] if content["type"] == "text" else None
                )
            elif event == "content-block-delta":
                _require(
                    key in active_messages
                    and active_messages[key]["block"] == data["index"],
                    "content delta has no matching active block",
                    path=path,
                )
                delta = data["delta"]
                if (
                    active_messages[key]["text"] is not None
                    and delta["type"] == "text-delta"
                ):
                    active_messages[key]["text"] += delta["text"]
            elif event == "content-block-finish":
                _require(
                    key in active_messages
                    and active_messages[key]["block"] == data["index"],
                    "content block finish has no matching active block",
                    path=path,
                )
                content = data["content"]
                if content["type"] == "text":
                    _require(
                        active_messages[key]["text"] == content["text"],
                        "assembled text differs from content-block-finish",
                        path=path,
                    )
                active_messages[key]["block"] = None
                active_messages[key]["text"] = None
            elif event in {"message-finish", "error"}:
                _require(
                    key in active_messages,
                    "message terminal has no message-start",
                    path=path,
                )
                _require(
                    active_messages[key]["block"] is None,
                    "message finished with an open content block",
                    path=path,
                )
                del active_messages[key]
            continue

        if method == "tools":
            coverage.add("tool_lifecycle")
            tool_key = (namespace, data["tool_call_id"])
            event = data["event"]
            if event == "tool-started":
                _require(
                    tool_key not in active_tools, "duplicate tool-started", path=path
                )
                active_tools.add(tool_key)
            elif event == "tool-output-delta":
                _require(
                    tool_key in active_tools,
                    "tool delta before tool-started",
                    path=path,
                )
            elif event in {"tool-finished", "tool-error"}:
                _require(
                    tool_key in active_tools,
                    "tool terminal before tool-started",
                    path=path,
                )
                active_tools.remove(tool_key)

    _require(
        not active_messages,
        f"unclosed message lifecycles: {active_messages!r}",
        path=path,
    )
    _require(not active_tools, f"unclosed tool lifecycles: {active_tools!r}", path=path)
    _require(
        all(
            state in {"completed", "failed", "interrupted"}
            for state in lifecycle_seen.values()
        ),
        f"unclosed run lifecycles: {lifecycle_seen!r}",
        path=path,
    )
    return coverage


def _validate_replay(
    path: Path,
    records: list[dict[str, Any]],
    expectations: dict[str, Any],
) -> set[str]:
    replay = expectations.get("replay")
    if replay is None:
        return set()
    _require(
        isinstance(replay, dict), "replay expectation must be an object", path=path
    )
    disconnect_after = replay.get("disconnect_after_seq")
    reconnect_since = replay.get("reconnect_since")
    _require(
        _is_int(disconnect_after) and disconnect_after >= 0,
        "disconnect_after_seq must be non-negative",
        path=path,
    )
    _require(
        reconnect_since == disconnect_after,
        "reconnect_since must equal the last processed sequence",
        path=path,
    )

    initial_sequences: list[int] = []
    resumed_sequences: list[int] = []
    for record in records:
        if record.get("kind") != "event":
            continue
        connection = record.get("connection")
        sequence = record["payload"]["seq"]
        if connection == "initial":
            initial_sequences.append(sequence)
        elif connection == "resumed":
            resumed_sequences.append(sequence)
    _require(
        initial_sequences and max(initial_sequences) == disconnect_after,
        "initial connection must stop exactly at disconnect_after_seq",
        path=path,
    )
    _require(
        resumed_sequences and min(resumed_sequences) > reconnect_since,
        "resumed connection replayed an already processed sequence",
        path=path,
    )

    stream_requests = [
        record["payload"]
        for record in records
        if record.get("kind") == "stream_request"
        and record.get("connection") == "resumed"
    ]
    _require(
        len(stream_requests) == 1
        and stream_requests[0].get("since") == reconnect_since,
        "resumed stream request must carry the replay cursor",
        path=path,
    )
    expected_text = replay.get("visible_text")
    if expected_text is not None:
        _require(
            isinstance(expected_text, str),
            "replay visible_text must be a string",
            path=path,
        )
        visible_text = "".join(
            record["payload"]["params"]["data"]["content"]["text"]
            for record in records
            if record.get("kind") in {"event", "normalized_event"}
            and record["payload"].get("method") == "messages"
            and record["payload"]["params"]["data"].get("event")
            == "content-block-finish"
            and record["payload"]["params"]["data"]["content"].get("type") == "text"
        )
        _require(
            visible_text == expected_text,
            f"replayed visible text {visible_text!r} != {expected_text!r}",
            path=path,
        )
    return {"replay_disconnect"}


def validate_fixture(path: Path, *, protocol_commit: str) -> FixtureReport:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read fixture {path}: {exc}") from exc

    _require(
        fixture.get("fixture_version") == 1, "unsupported fixture version", path=path
    )
    _require(
        fixture.get("protocol_commit") == protocol_commit,
        "fixture protocol_commit differs from lock",
        path=path,
    )
    _require(
        fixture.get("wire_profile") == "official-generated-snake-case",
        "fixture must use the locked generated wire profile",
        path=path,
    )
    _require(
        isinstance(fixture.get("name"), str) and fixture["name"],
        "fixture needs a name",
        path=path,
    )
    records = fixture.get("records")
    _require(
        isinstance(records, list) and records,
        "fixture records must be non-empty",
        path=path,
    )
    expectations = fixture.get("expectations", {})
    _require(
        isinstance(expectations, dict),
        "fixture expectations must be an object",
        path=path,
    )

    event_payloads: list[dict[str, Any]] = []
    sequences: list[int] = []
    event_ids: list[str] = []
    command_ids: list[int] = []
    response_ids: list[int] = []
    requested_interrupts: set[tuple[tuple[str, ...], str]] = set()
    responded_interrupts: set[tuple[tuple[str, ...], str]] = set()
    derived_coverage: set[str] = set()
    raw_translations: dict[str, dict[str, Any]] = {}
    normalized_translations: dict[str, dict[str, Any]] = {}

    for index, record in enumerate(records):
        _require(
            isinstance(record, dict),
            "record must be an object",
            path=path,
            record=index,
        )
        kind = record.get("kind")
        payload = record.get("payload")
        _require(
            isinstance(payload, dict),
            "record payload must be an object",
            path=path,
            record=index,
        )

        if kind == "stream_request":
            _validate_with_binding("stream_request", payload, path=path, record=index)
        elif kind == "command":
            _validate_with_binding("command", payload, path=path, record=index)
            command_ids.append(payload["id"])
            if payload["method"] == "input.respond":
                params = payload["params"]
                if "update" in params or "goto" in params:
                    derived_coverage.add("hitl_update_goto")
                if "responses" in params:
                    for response in params["responses"]:
                        responded_interrupts.add(
                            (tuple(response["namespace"]), response["interrupt_id"])
                        )
                else:
                    responded_interrupts.add(
                        (tuple(params["namespace"]), params["interrupt_id"])
                    )
        elif kind == "command_response":
            response_type = payload.get("type")
            _require(
                response_type in {"success", "error"},
                "command response type must be success or error",
                path=path,
                record=index,
            )
            _validate_with_binding(
                f"command_{response_type}",
                payload,
                path=path,
                record=index,
            )
            if _is_int(payload.get("id")):
                response_ids.append(payload["id"])
            if response_type == "error":
                derived_coverage.add("structured_error")
        elif kind == "aegra_raw_event":
            translation_id = record.get("translation_id")
            _require(
                isinstance(translation_id, str) and translation_id,
                "raw Aegra event needs translation_id",
                path=path,
                record=index,
            )
            _require(
                translation_id not in raw_translations,
                "duplicate raw Aegra translation_id",
                path=path,
                record=index,
            )
            sse = record.get("sse")
            _require(
                isinstance(sse, dict)
                and sse.get("id") == str(payload.get("seq"))
                and sse.get("event") == payload.get("method"),
                "raw Aegra SSE id must carry seq and event must carry method",
                path=path,
                record=index,
            )
            normalized = normalize_aegra_event(payload)
            _validate_event(normalized, path=path, record=index)
            raw_translations[translation_id] = normalized
        elif kind == "normalized_event":
            translation_id = record.get("translation_id")
            _require(
                isinstance(translation_id, str) and translation_id,
                "normalized event needs translation_id",
                path=path,
                record=index,
            )
            _require(
                translation_id not in normalized_translations,
                "duplicate normalized translation_id",
                path=path,
                record=index,
            )
            _validate_event(payload, path=path, record=index)
            normalized_translations[translation_id] = payload
            event_payloads.append(payload)
            sequences.append(payload["seq"])
            event_ids.append(payload["event_id"])
            if payload["method"] == "input.requested":
                data = payload["params"]["data"]
                requested_interrupts.add(
                    (tuple(payload["params"]["namespace"]), data["interrupt_id"])
                )
        elif kind == "event":
            _validate_event(payload, path=path, record=index)
            event_payloads.append(payload)
            sequences.append(payload["seq"])
            event_ids.append(payload["event_id"])
            sse = record.get("sse")
            _require(
                isinstance(sse, dict),
                "event record needs SSE metadata",
                path=path,
                record=index,
            )
            _require(
                sse.get("id") == payload["event_id"]
                and sse.get("event") == payload["method"],
                "SSE id/event must mirror the protocol envelope",
                path=path,
                record=index,
            )
            if payload["method"] == "input.requested":
                data = payload["params"]["data"]
                requested_interrupts.add(
                    (tuple(payload["params"]["namespace"]), data["interrupt_id"])
                )
        else:
            raise ContractError(
                f"{_display_path(path)}:record[{index}]: unknown record kind {kind!r}"
            )

    _require(
        raw_translations.keys() == normalized_translations.keys(),
        "every raw Aegra event must have exactly one normalized fixture event",
        path=path,
    )
    for translation_id, translated in raw_translations.items():
        _require(
            translated == normalized_translations[translation_id],
            f"Aegra translation {translation_id!r} differs from normalized fixture",
            path=path,
        )
    if raw_translations:
        derived_coverage.add("aegra_translation")

    _require(
        sequences == sorted(sequences) and len(sequences) == len(set(sequences)),
        "event sequences must be strictly increasing",
        path=path,
    )
    _require(
        len(event_ids) == len(set(event_ids)),
        "event_id values must be unique",
        path=path,
    )
    _require(
        set(response_ids).issubset(command_ids),
        "every command response id must correlate with a command",
        path=path,
    )
    if requested_interrupts or responded_interrupts:
        _require(
            requested_interrupts == responded_interrupts,
            "input.respond must match every input.requested interrupt and namespace",
            path=path,
        )
        derived_coverage.add("hitl")

    derived_coverage.update(_validate_lifecycle_invariants(path, event_payloads))
    derived_coverage.update(_validate_replay(path, records, expectations))

    declared_coverage = expectations.get("coverage")
    _require(
        isinstance(declared_coverage, list)
        and all(isinstance(item, str) for item in declared_coverage),
        "expectations.coverage must be a string array",
        path=path,
    )
    _require(
        set(declared_coverage).issubset(derived_coverage),
        f"declared coverage is not demonstrated: {set(declared_coverage) - derived_coverage}",
        path=path,
    )
    return FixtureReport(
        path=path,
        records=len(records),
        events=len(event_payloads),
        coverage=frozenset(declared_coverage),
    )


def fixture_paths() -> list[Path]:
    return sorted(
        path for path in FIXTURES_ROOT.glob("*.json") if path.name != "README.json"
    )


def validate_protocol_event(
    payload: dict[str, Any],
    *,
    source: str = "live",
    record: int = 0,
) -> None:
    """Validate one generated-binding wire event outside a fixture file."""
    _validate_event(
        payload,
        path=REPO_ROOT / f"<{source}>",
        record=record,
    )


def normalize_aegra_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate the verified Aegra 0.9.24 event dialect at one boundary.

    Aegra emits ``input.requested.params.data.value`` for the stock LangGraph
    SDK. The locked official generated binding calls the same opaque interrupt
    value ``payload``. No other field is rewritten here.
    """
    normalized = deepcopy(payload)
    if normalized.get("method") != "input.requested":
        return normalized
    params = normalized.get("params")
    data = params.get("data") if isinstance(params, dict) else None
    if not isinstance(data, dict):
        return normalized
    if "value" in data and "payload" in data:
        raise ContractError(
            "Aegra input.requested contains both value and payload; "
            "the dialect translation is ambiguous"
        )
    if "value" in data:
        data["payload"] = data.pop("value")
    return normalized


def validate_protocol_command(
    payload: dict[str, Any],
    *,
    source: str = "live",
    record: int = 0,
) -> None:
    """Validate one generated-binding command outside a fixture file."""
    _validate_with_binding(
        "command",
        payload,
        path=REPO_ROOT / f"<{source}>",
        record=record,
    )


def validate_protocol_response(
    payload: dict[str, Any],
    *,
    source: str = "live",
    record: int = 0,
) -> None:
    """Validate one generated-binding command response outside a fixture."""
    response_type = payload.get("type")
    _require(
        response_type in {"success", "error"},
        "command response type must be success or error",
        path=REPO_ROOT / f"<{source}>",
        record=record,
    )
    _validate_with_binding(
        f"command_{response_type}",
        payload,
        path=REPO_ROOT / f"<{source}>",
        record=record,
    )


def validate_event_lifecycles(
    events: list[dict[str, Any]],
    *,
    source: str = "live",
) -> frozenset[str]:
    """Validate ordering/lifecycle invariants across a live event sequence."""
    return frozenset(_validate_lifecycle_invariants(REPO_ROOT / f"<{source}>", events))


def validate_all(paths: Iterable[Path] | None = None) -> list[FixtureReport]:
    lock = load_lock()
    selected = list(paths) if paths is not None else fixture_paths()
    _require(bool(selected), "no protocol fixtures found")
    reports = [
        validate_fixture(path, protocol_commit=lock["protocol"]["commit"])
        for path in selected
    ]
    if paths is None:
        coverage = frozenset().union(*(report.coverage for report in reports))
        _require(
            REQUIRED_COVERAGE.issubset(coverage),
            f"fixture suite is missing coverage: {sorted(REQUIRED_COVERAGE - coverage)}",
        )
    return reports


def main() -> int:
    try:
        reports = validate_all()
    except ContractError as exc:
        print(f"protocol contract failed: {exc}", file=sys.stderr)
        return 1

    total_records = sum(report.records for report in reports)
    total_events = sum(report.events for report in reports)
    coverage = sorted(frozenset().union(*(report.coverage for report in reports)))
    print(
        f"protocol contract ok: {len(reports)} fixtures, "
        f"{total_records} records, {total_events} events"
    )
    print(f"coverage: {', '.join(coverage)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
