#!/usr/bin/env python3
"""Offline fixture gate and optional live Agent Protocol v2 smoke test.

Running without ``--base-url`` is deliberately offline. A live server is
contacted only when its URL is supplied explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

from protocol_contract import (
    ContractError,
    load_lock,
    normalize_aegra_event,
    validate_all,
    validate_event_lifecycles,
    validate_protocol_command,
    validate_protocol_event,
    validate_protocol_response,
)

ALL_CHANNELS = [
    "values",
    "updates",
    "messages",
    "tools",
    "lifecycle",
    "input",
    "checkpoints",
    "tasks",
    "custom",
]
TERMINAL_LIFECYCLES = frozenset({"completed", "failed", "interrupted"})


class SmokeError(RuntimeError):
    """The live server failed a required smoke assertion."""


@dataclass(frozen=True)
class TransportProfile:
    name: str
    stream_path: str
    command_path: str
    sse_id: str


@dataclass(frozen=True)
class SSEFrame:
    event: str | None
    event_id: str | None
    data: dict[str, Any]


@dataclass
class StreamResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    disconnected: bool = False
    terminal: str | None = None
    hitl_responses: int = 0


@dataclass(frozen=True)
class TurnResult:
    events: list[dict[str, Any]]
    last_seq: int
    coverage: frozenset[str]
    visible_text: str
    hitl_responses: int


def _profiles(lock: dict[str, Any]) -> dict[str, TransportProfile]:
    official = lock["protocol"]["transport"]
    aegra = lock["aegra"]["runtimeTransport"]
    return {
        "aegra-0.9.24": TransportProfile(
            name="aegra-0.9.24",
            stream_path=aegra["sse"].removeprefix("POST "),
            command_path=aegra["commands"].removeprefix("POST "),
            sse_id="sequence",
        ),
        "upstream-0.0.18": TransportProfile(
            name="upstream-0.0.18",
            stream_path=official["sse"].removeprefix("POST "),
            command_path=official["commands"].removeprefix("POST "),
            sse_id="event_id",
        ),
    }


def _url(base_url: str, path: str, thread_id: str) -> str:
    rendered = path.replace("{thread_id}", thread_id)
    return urljoin(f"{base_url.rstrip('/')}/", rendered.lstrip("/"))


async def iter_sse_frames(response: httpx.Response) -> AsyncIterator[SSEFrame]:
    """Parse SSE framing, including multi-line data fields and comments."""
    event: str | None = None
    event_id: str | None = None
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                raw_data = "\n".join(data_lines)
                try:
                    payload = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    raise SmokeError(f"SSE data is not JSON: {raw_data!r}") from exc
                if not isinstance(payload, dict):
                    raise SmokeError("SSE data must be a protocol object")
                yield SSEFrame(event=event, event_id=event_id, data=payload)
            event = None
            event_id = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue

        field_name, separator, value = line.partition(":")
        if not separator:
            value = ""
        elif value.startswith(" "):
            value = value[1:]
        if field_name == "event":
            event = value
        elif field_name == "id":
            event_id = value
        elif field_name == "data":
            data_lines.append(value)

    if data_lines:
        raw_data = "\n".join(data_lines)
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise SmokeError(f"SSE data is not JSON: {raw_data!r}") from exc
        if not isinstance(payload, dict):
            raise SmokeError("SSE data must be a protocol object")
        yield SSEFrame(event=event, event_id=event_id, data=payload)


class LiveSmoke:
    def __init__(
        self,
        *,
        base_url: str,
        assistant_id: str,
        profile: TransportProfile,
        token: str | None,
        timeout: float,
        hitl_response: Any,
    ) -> None:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        )
        self._base_url = base_url
        self._assistant_id = assistant_id
        self._profile = profile
        self._timeout = timeout
        self._hitl_response = hitl_response
        self._next_command_id = 1
        self._responded_interrupts: set[tuple[tuple[str, ...], str]] = set()

    async def __aenter__(self) -> LiveSmoke:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._client.aclose()

    async def _command(
        self,
        thread_id: str,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        command_id = self._next_command_id
        self._next_command_id += 1
        command = {"id": command_id, "method": method, "params": params}
        validate_protocol_command(command, source=f"live:{method}")
        response = await self._client.post(
            _url(
                self._base_url,
                self._profile.command_path,
                thread_id,
            ),
            json=command,
        )
        if response.status_code != 200:
            body = (await response.aread()).decode(errors="replace")[:500]
            raise SmokeError(f"{method} returned HTTP {response.status_code}: {body}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise SmokeError(f"{method} response is not JSON") from exc
        if not isinstance(payload, dict):
            raise SmokeError(f"{method} response must be an object")
        validate_protocol_response(payload, source=f"live:{method}")
        if payload["id"] != command_id:
            raise SmokeError(f"{method} response id {payload['id']!r} != {command_id}")
        return payload

    def _normalize_sse_frame(
        self,
        frame: SSEFrame,
        index: int,
    ) -> dict[str, Any]:
        if self._profile.name == "aegra-0.9.24":
            normalized = normalize_aegra_event(frame.data)
        else:
            normalized = frame.data
        validate_protocol_event(normalized, source="live:sse", record=index)
        if frame.event != frame.data["method"]:
            raise SmokeError(
                f"SSE event {frame.event!r} != envelope method {frame.data['method']!r}"
            )
        if self._profile.sse_id == "sequence":
            expected_id = str(frame.data["seq"])
        else:
            expected_id = frame.data["event_id"]
        if frame.event_id != expected_id:
            raise SmokeError(
                f"SSE id {frame.event_id!r} != expected {expected_id!r} "
                f"for profile {self._profile.name}"
            )
        return normalized

    async def _respond_to_interrupt(
        self,
        thread_id: str,
        event: dict[str, Any],
    ) -> bool:
        params = event["params"]
        data = params["data"]
        key = (tuple(params["namespace"]), data["interrupt_id"])
        if key in self._responded_interrupts:
            return False
        response = await self._command(
            thread_id,
            "input.respond",
            {
                "namespace": list(key[0]),
                "interrupt_id": key[1],
                "response": self._hitl_response,
            },
        )
        if response["type"] != "success":
            raise SmokeError(f"input.respond failed: {response}")
        self._responded_interrupts.add(key)
        return True

    async def _collect(
        self,
        *,
        thread_id: str,
        since: int | None,
        disconnect_on_delta: bool,
        ready: asyncio.Event,
    ) -> StreamResult:
        body: dict[str, Any] = {
            "channels": ALL_CHANNELS,
            "namespaces": [[]],
            "depth": 4,
        }
        if since is not None:
            body["since"] = since
        result = StreamResult()
        stream_url = _url(
            self._base_url,
            self._profile.stream_path,
            thread_id,
        )

        async with self._client.stream(
            "POST",
            stream_url,
            headers={"Accept": "text/event-stream"},
            json=body,
        ) as response:
            if response.status_code != 200:
                body_bytes = await response.aread()
                ready.set()
                raise SmokeError(
                    f"stream returned HTTP {response.status_code}: "
                    f"{body_bytes.decode(errors='replace')[:500]}"
                )
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                ready.set()
                raise SmokeError(
                    f"stream content-type is {content_type!r}, expected text/event-stream"
                )
            ready.set()

            async for frame in iter_sse_frames(response):
                index = len(result.events)
                event = self._normalize_sse_frame(frame, index)
                result.events.append(event)

                if event["method"] == "input.requested":
                    if await self._respond_to_interrupt(thread_id, event):
                        result.hitl_responses += 1

                data = event["params"]["data"]
                if (
                    disconnect_on_delta
                    and event["method"] == "messages"
                    and data.get("event") == "content-block-delta"
                ):
                    result.disconnected = True
                    break

                if (
                    event["method"] == "lifecycle"
                    and not event["params"]["namespace"]
                    and data.get("event") in TERMINAL_LIFECYCLES
                ):
                    terminal = data["event"]
                    if terminal == "interrupted" and self._responded_interrupts:
                        continue
                    result.terminal = terminal
                    break
        return result

    async def _open_stream(
        self,
        *,
        thread_id: str,
        since: int | None,
        disconnect_on_delta: bool,
    ) -> tuple[asyncio.Task[StreamResult], asyncio.Event]:
        ready = asyncio.Event()
        task = asyncio.create_task(
            self._collect(
                thread_id=thread_id,
                since=since,
                disconnect_on_delta=disconnect_on_delta,
                ready=ready,
            )
        )
        ready_task = asyncio.create_task(ready.wait())
        done, _pending = await asyncio.wait(
            {task, ready_task},
            timeout=min(self._timeout, 15.0),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            ready_task.cancel()
            task.cancel()
            raise SmokeError("stream did not open before timeout")
        if task in done:
            ready_task.cancel()
            await task
            raise SmokeError("stream closed before becoming ready")
        ready_task.result()
        return task, ready

    async def _wait_stream(
        self,
        task: asyncio.Task[StreamResult],
    ) -> StreamResult:
        try:
            return await asyncio.wait_for(task, timeout=self._timeout)
        except TimeoutError as exc:
            task.cancel()
            raise SmokeError("stream did not reach the expected boundary") from exc

    async def run_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        since: int | None,
        exercise_replay: bool,
    ) -> TurnResult:
        task, _ready = await self._open_stream(
            thread_id=thread_id,
            since=since,
            disconnect_on_delta=exercise_replay,
        )
        try:
            response = await self._command(
                thread_id,
                "run.start",
                {
                    "assistant_id": self._assistant_id,
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                            }
                        ]
                    },
                },
            )
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        if response["type"] != "success":
            task.cancel()
            raise SmokeError(f"run.start failed: {response}")

        first = await self._wait_stream(task)
        events = list(first.events)
        hitl_responses = first.hitl_responses
        if not events:
            raise SmokeError("stream produced no events")

        if exercise_replay:
            if not first.disconnected:
                raise SmokeError(
                    "run reached a terminal state before a content delta; "
                    "disconnect/replay was not exercised"
                )
            cursor = events[-1]["seq"]
            resumed_task, _ready = await self._open_stream(
                thread_id=thread_id,
                since=cursor,
                disconnect_on_delta=False,
            )
            resumed = await self._wait_stream(resumed_task)
            if not resumed.events:
                raise SmokeError("reconnected stream produced no events")
            if min(event["seq"] for event in resumed.events) <= cursor:
                raise SmokeError(f"reconnected stream replayed seq <= cursor {cursor}")
            if resumed.terminal is None:
                raise SmokeError("reconnected stream did not reach root terminal")
            events.extend(resumed.events)
            hitl_responses += resumed.hitl_responses
            terminal = resumed.terminal
        else:
            terminal = first.terminal

        if terminal != "completed":
            raise SmokeError(f"turn ended with lifecycle {terminal!r}")
        sequences = [event["seq"] for event in events]
        event_ids = [event["event_id"] for event in events]
        if sequences != sorted(set(sequences)):
            raise SmokeError("turn has duplicate or out-of-order sequence numbers")
        if len(event_ids) != len(set(event_ids)):
            raise SmokeError("turn has duplicate event_id values")

        coverage = validate_event_lifecycles(events, source="live:turn")
        visible_text = _assemble_visible_text(events)
        return TurnResult(
            events=events,
            last_seq=sequences[-1],
            coverage=coverage,
            visible_text=visible_text,
            hitl_responses=hitl_responses,
        )

    async def assert_thread_reload(self, thread_id: str) -> None:
        response = await self._client.get(
            _url(self._base_url, "/threads/{thread_id}", thread_id)
        )
        if response.status_code != 200:
            raise SmokeError(f"thread reload returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("thread_id") != thread_id:
            raise SmokeError("thread reload did not return the requested thread")

    async def assert_structured_error(self, thread_id: str) -> None:
        response = await self._command(
            thread_id,
            "state.fork",
            {"checkpoint_id": "missing-checkpoint-for-protocol-smoke"},
        )
        if response["type"] != "error":
            raise SmokeError(
                "state.fork unexpectedly succeeded for a missing checkpoint"
            )
        if response["error"] not in {
            "unknown_command",
            "not_supported",
            "permission_denied",
            "no_such_checkpoint",
        }:
            raise SmokeError(
                f"state.fork returned unexpected error code {response['error']!r}"
            )


def _assemble_visible_text(events: list[dict[str, Any]]) -> str:
    active_messages: dict[
        tuple[tuple[str, ...], str | None], dict[int, str | None]
    ] = {}
    visible: list[str] = []

    for event in events:
        if event["method"] != "messages":
            continue
        params = event["params"]
        data = params["data"]
        key = (tuple(params["namespace"]), params.get("node"))
        event_name = data["event"]

        if event_name == "message-start":
            active_messages[key] = {}
        elif event_name == "content-block-start":
            content = data["content"]
            active_messages[key][data["index"]] = (
                content.get("text") if content.get("type") == "text" else None
            )
        elif event_name == "content-block-delta":
            delta = data["delta"]
            current = active_messages[key][data["index"]]
            if current is not None and delta["type"] == "text-delta":
                active_messages[key][data["index"]] = current + delta["text"]
        elif event_name == "content-block-finish":
            content = data["content"]
            accumulated = active_messages[key].pop(data["index"])
            if content["type"] == "text":
                if accumulated != content["text"]:
                    raise SmokeError(
                        "text content after replay differs from content-block-finish"
                    )
                visible.append(accumulated or "")
        elif event_name in {"message-finish", "error"}:
            active_messages.pop(key, None)

    if active_messages:
        raise SmokeError("visible message assembly ended with open messages")
    text = "".join(visible)
    if not text:
        raise SmokeError("turn produced no visible text content")
    return text


async def run_live(args: argparse.Namespace, lock: dict[str, Any]) -> None:
    profiles = _profiles(lock)
    profile = profiles[args.profile]
    token = os.environ.get(args.token_env) if args.token_env else None
    if args.token_env and token is None:
        raise SmokeError(f"token environment variable {args.token_env!r} is not set")
    try:
        hitl_response = json.loads(args.hitl_response)
    except json.JSONDecodeError as exc:
        raise SmokeError("--hitl-response must be valid JSON") from exc

    thread_id = str(uuid.uuid4())
    async with LiveSmoke(
        base_url=args.base_url,
        assistant_id=args.assistant_id,
        profile=profile,
        token=token,
        timeout=args.timeout,
        hitl_response=hitl_response,
    ) as smoke:
        first = await smoke.run_turn(
            thread_id=thread_id,
            prompt=args.turn_one,
            since=None,
            exercise_replay=True,
        )
        second = await smoke.run_turn(
            thread_id=thread_id,
            prompt=args.turn_two,
            since=first.last_seq,
            exercise_replay=False,
        )
        await smoke.assert_thread_reload(thread_id)
        await smoke.assert_structured_error(thread_id)

    combined_coverage = first.coverage | second.coverage
    if not args.allow_no_tool and "tool_lifecycle" not in combined_coverage:
        raise SmokeError("two-turn smoke did not exercise a tool lifecycle")
    if args.require_nested and "nested_namespace" not in combined_coverage:
        raise SmokeError("two-turn smoke did not exercise a nested namespace")
    total_hitl = first.hitl_responses + second.hitl_responses
    if args.require_hitl and total_hitl == 0:
        raise SmokeError("two-turn smoke did not exercise input.requested/respond")

    print(
        f"live AP v2 smoke ok: profile={profile.name}, thread={thread_id}, "
        f"events={len(first.events) + len(second.events)}, "
        f"hitl_responses={total_hitl}"
    )
    print(f"visible text: turn1={first.visible_text!r}, turn2={second.visible_text!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        help="Explicit live server URL. Omit for offline fixture validation only.",
    )
    parser.add_argument(
        "--assistant-id",
        help="Assistant/graph id for live run.start commands.",
    )
    parser.add_argument(
        "--profile",
        choices=("aegra-0.9.24", "upstream-0.0.18"),
        default="aegra-0.9.24",
        help="Transport path and SSE id profile for the live server.",
    )
    parser.add_argument(
        "--token-env",
        default=None,
        help="Environment variable containing a bearer token. Its value is never printed.",
    )
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--turn-one",
        default="도커 관련 글을 검색하고 근거와 함께 한 문장으로 답해줘.",
    )
    parser.add_argument(
        "--turn-two",
        default="방금 찾은 글의 핵심을 더 짧게 요약해줘.",
    )
    parser.add_argument(
        "--hitl-response",
        default='{"action":"approve"}',
        help="JSON value sent when input.requested is observed.",
    )
    parser.add_argument(
        "--allow-no-tool",
        action="store_true",
        help="Diagnostic only: do not require a tools-channel lifecycle.",
    )
    parser.add_argument(
        "--require-nested",
        action="store_true",
        help="Require at least one event below the root namespace.",
    )
    parser.add_argument(
        "--require-hitl",
        action="store_true",
        help="Require input.requested followed by input.respond.",
    )
    args = parser.parse_args(argv)
    if args.base_url and not args.assistant_id:
        parser.error("--assistant-id is required with --base-url")
    if not args.base_url and args.assistant_id:
        parser.error("--assistant-id has no effect without --base-url")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        reports = validate_all()
        lock = load_lock()
        print(
            f"offline AP v2 fixtures ok: {len(reports)} files, "
            f"{sum(report.events for report in reports)} events"
        )
        if args.base_url:
            asyncio.run(run_live(args, lock))
        else:
            print("live smoke skipped: pass --base-url explicitly to contact a server")
    except (ContractError, SmokeError, httpx.HTTPError) as exc:
        print(f"AP v2 smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
