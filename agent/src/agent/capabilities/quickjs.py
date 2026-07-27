"""Owner/eval-only, async, bounded wrapper around native LangChain QuickJS."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from xml.etree import ElementTree

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.tools import ToolRuntime
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_quickjs import CodeInterpreterMiddleware
from langgraph_sdk.runtime import ServerRuntime

from agent.capabilities.budget import CapabilityDeniedError

QUICKJS_TOOL_NAME = "eval"
QUICKJS_PERMISSIONS = frozenset({"admin", "eval"})
QUICKJS_MEMORY_LIMIT_BYTES = 16 * 1024 * 1024
# quickjs-rs 0.2.5 applies this default to every Runtime constructed by
# langchain-quickjs 0.3.4. The upstream middleware does not expose the setting.
QUICKJS_STACK_LIMIT_BYTES = 1 * 1024 * 1024
QUICKJS_TIMEOUT_SECONDS = 1.0
QUICKJS_OUTER_TIMEOUT_SECONDS = 1.5
QUICKJS_MAX_SOURCE_BYTES = 16 * 1024
QUICKJS_MAX_OUTPUT_BYTES = 4 * 1024
QUICKJS_NATIVE_MAX_RESULT_CHARS = 8 * 1024
QUICKJS_MAX_SNAPSHOT_BYTES = 64 * 1024
QUICKJS_RESULT_SCHEMA = "syshin.quickjs.result.v1"

_NATIVE_TRUNCATION = re.compile(r"… \[truncated \d+ chars\]$")
_QUICKJS_HARDENING_PRELUDE = """\
(() => {
  const deterministicMath = globalThis.Math;
  Object.defineProperty(deterministicMath, "random", {
    value: undefined,
    writable: false,
    configurable: false,
    enumerable: false
  });
  Object.freeze(deterministicMath);
  Object.defineProperty(globalThis, "Math", {
    value: deterministicMath,
    writable: false,
    configurable: false,
    enumerable: false
  });
  for (const name of [
    "Date",
    "performance",
    "crypto",
    "Temporal",
    "WeakRef",
    "FinalizationRegistry"
  ]) {
    Object.defineProperty(globalThis, name, {
      value: undefined,
      writable: false,
      configurable: false,
      enumerable: false
    });
  }
})();
"""
_ALLOWED_STATUSES = frozenset(
    {
        "ok",
        "truncated",
        "timeout",
        "out_of_memory",
        "invalid_input",
        "invalid_result",
    }
)

QUICKJS_SYSTEM_PROMPT = f"""\
### Bounded JavaScript data transforms

`{QUICKJS_TOOL_NAME}` runs JavaScript asynchronously in a fresh, isolated QuickJS-WASM
context. Use it only when code materially helps transform already-retrieved pure data:
ranked-list comparison, metrics, table transforms, or citation validation. Do not use it
for ordinary prose.

- No state persists across calls.
- No filesystem, environment, network, module loader, console, Python/host callable,
  LangChain tool, or subagent/task bridge is available.
- Use only deterministic JavaScript pure-data built-ins such as arrays, objects,
  strings, deterministic Math functions, and JSON. Host time and entropy are
  unavailable: Date, performance, crypto, Temporal, Math.random, weak references, and
  finalizers cannot be used or redefined.
- Source is capped at {QUICKJS_MAX_SOURCE_BYTES} UTF-8 bytes and serialized output at
  {QUICKJS_MAX_OUTPUT_BYTES} UTF-8 bytes.
- Each call has a {QUICKJS_TIMEOUT_SECONDS:.1f}s native execution deadline, a
  {QUICKJS_MEMORY_LIMIT_BYTES // (1024 * 1024)} MiB heap ceiling, and a
  {QUICKJS_STACK_LIMIT_BYTES // 1024} KiB stack ceiling.
"""


def _permission_set(permissions: object) -> frozenset[str]:
    if not isinstance(permissions, Sequence) or isinstance(
        permissions,
        (str, bytes, bytearray),
    ):
        return frozenset()
    if any(
        not isinstance(permission, str) or not permission for permission in permissions
    ):
        return frozenset()
    return frozenset(permissions)


def server_quickjs_enabled() -> bool:
    """Resolve the fail-closed deployment opt-in from server environment only."""
    value = os.environ.get("QUICKJS_ENABLED", "false")
    if value == "true":
        return True
    if value == "false":
        return False
    raise RuntimeError("QUICKJS_ENABLED must be exactly 'true' or 'false'")


def quickjs_allowed(
    runtime: ServerRuntime[Any],
    *,
    server_enabled: bool | None = None,
) -> bool:
    """Authorize from deployment opt-in plus authenticated runtime permissions."""
    enabled = server_quickjs_enabled() if server_enabled is None else server_enabled
    if not isinstance(enabled, bool):
        raise TypeError("server_enabled must be a boolean")
    if (
        not enabled
        or runtime.user is None
        or getattr(runtime.user, "is_authenticated", False) is not True
    ):
        return False
    return bool(
        _permission_set(getattr(runtime.user, "permissions", None))
        & QUICKJS_PERMISSIONS
    )


def _utf8_size(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _serialize_payload(
    *,
    status: str,
    output: str = "",
    truncated: bool = False,
) -> str:
    if status not in _ALLOWED_STATUSES:
        raise ValueError("QuickJS result status is not allowlisted")
    return json.dumps(
        {
            "output": output,
            "schema": QUICKJS_RESULT_SCHEMA,
            "status": status,
            "truncated": truncated,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _bounded_payload(*, status: str, output: str = "") -> str:
    """Serialize one canonical result without splitting UTF-8 or JSON escapes."""
    payload = _serialize_payload(status=status, output=output)
    if len(payload.encode("utf-8")) <= QUICKJS_MAX_OUTPUT_BYTES:
        return payload

    low = 0
    high = len(output)
    best = _serialize_payload(status="truncated", truncated=True)
    while low <= high:
        midpoint = (low + high) // 2
        candidate = _serialize_payload(
            status="truncated",
            output=output[:midpoint],
            truncated=True,
        )
        if len(candidate.encode("utf-8")) <= QUICKJS_MAX_OUTPUT_BYTES:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def _fixed_result(status: str) -> str:
    return _bounded_payload(status=status)


def _normalize_native_message(message: object) -> str:
    """Allowlist native outcomes and discard every raw guest/host error detail."""
    if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return _fixed_result("invalid_result")
    try:
        root = ElementTree.fromstring(message.content)
    except (ElementTree.ParseError, ValueError):
        return _fixed_result("invalid_result")

    if root.tag == "error":
        error_type = root.attrib.get("type")
        if error_type == "Timeout":
            return _fixed_result("timeout")
        if error_type == "OutOfMemory":
            return _fixed_result("out_of_memory")
        return _fixed_result("invalid_result")

    if root.tag != "result" or root.attrib.get("kind") is not None:
        return _fixed_result("invalid_result")
    output = root.text or ""
    if _NATIVE_TRUNCATION.search(output):
        return _bounded_payload(status="truncated", output=output)
    return _bounded_payload(status="ok", output=output)


def _tool_name(tool: object) -> str | None:
    if isinstance(tool, Mapping):
        name = tool.get("name")
        if isinstance(name, str):
            return name
        function = tool.get("function")
        if isinstance(function, Mapping) and isinstance(function.get("name"), str):
            return function["name"]
        return None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def _without_quickjs(request: ModelRequest[Any]) -> ModelRequest[Any]:
    return request.override(
        tools=[tool for tool in request.tools if _tool_name(tool) != QUICKJS_TOOL_NAME]
    )


def _append_system_prompt(
    system_message: SystemMessage | None,
    prompt: str,
) -> SystemMessage:
    if system_message is None:
        return SystemMessage(content=prompt)
    blocks = [*system_message.content_blocks, {"type": "text", "text": prompt}]
    return system_message.model_copy(update={"content": blocks})


class BoundedQuickJSMiddleware(CodeInterpreterMiddleware):
    """Native CodeInterpreterMiddleware with an async-only, fail-closed surface."""

    def __init__(self, *, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self._enabled = enabled
        self._close_task: asyncio.Task[None] | None = None
        super().__init__(
            memory_limit=QUICKJS_MEMORY_LIMIT_BYTES,
            timeout=QUICKJS_TIMEOUT_SECONDS,
            max_ptc_calls=1,
            tool_name=QUICKJS_TOOL_NAME,
            max_result_chars=QUICKJS_NATIVE_MAX_RESULT_CHARS,
            capture_console=False,
            subagents=False,
            ptc=None,
            mode="call",
            max_snapshot_bytes=QUICKJS_MAX_SNAPSHOT_BYTES,
        )

        if len(self.tools) != 1:
            raise RuntimeError(
                "native QuickJS middleware exposed an unexpected tool set"
            )
        native_tool = self.tools[0]
        native_coroutine = native_tool.coroutine
        if native_coroutine is None or native_tool.args_schema is None:
            raise RuntimeError("native QuickJS middleware has no async tool contract")

        async def async_eval(
            runtime: ToolRuntime[None, Any],
            code: str,
        ) -> ToolMessage:
            if not self._enabled:
                raise CapabilityDeniedError(
                    "QuickJS requires server opt-in and owner or eval permission"
                )
            source_bytes = _utf8_size(code)
            if source_bytes is None or source_bytes > QUICKJS_MAX_SOURCE_BYTES:
                return ToolMessage(
                    content=_fixed_result("invalid_input"),
                    tool_call_id=runtime.tool_call_id,
                    name=QUICKJS_TOOL_NAME,
                )
            try:
                async with asyncio.timeout(QUICKJS_OUTER_TIMEOUT_SECONDS):
                    native_message = await native_coroutine(
                        runtime,
                        f"{_QUICKJS_HARDENING_PRELUDE}\n{code}",
                    )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                content = _fixed_result("timeout")
            except Exception:
                content = _fixed_result("invalid_result")
            else:
                try:
                    content = _normalize_native_message(native_message)
                except Exception:
                    content = _fixed_result("invalid_result")
            return ToolMessage(
                content=content,
                tool_call_id=runtime.tool_call_id,
                name=QUICKJS_TOOL_NAME,
            )

        # StructuredTool discovers injected arguments from the raw signature rather
        # than get_type_hints(). Materialize this nested function's postponed
        # annotation so ToolRuntime remains trusted ToolNode input, not model input.
        async_eval.__annotations__["runtime"] = ToolRuntime[None, Any]
        async_eval.__annotations__["code"] = str
        async_eval.__annotations__["return"] = ToolMessage
        self.tools = [
            StructuredTool.from_function(
                name=native_tool.name,
                description=(
                    f"{native_tool.description} Use only for bounded pure-data "
                    "transforms, never ordinary prose."
                ),
                coroutine=async_eval,
                infer_schema=False,
                args_schema=native_tool.args_schema,
                metadata=dict(native_tool.metadata or {}),
            )
        ]

    @property
    def enabled(self) -> bool:
        """Return the immutable server authorization used at construction."""
        return self._enabled

    async def aclose(self) -> None:
        """Idempotently close every native runtime and worker without blocking."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                asyncio.to_thread(self._registry.close)
            )
        await asyncio.shield(self._close_task)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Never advertise QuickJS on a synchronous agent execution path."""
        return handler(_without_quickjs(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[
            [ModelRequest[Any]],
            Awaitable[ModelResponse[Any]],
        ],
    ) -> ModelResponse[Any]:
        """Advertise the async tool only for a server-authorized graph factory."""
        if not self._enabled:
            return await handler(_without_quickjs(request))
        return await handler(
            request.override(
                system_message=_append_system_prompt(
                    request.system_message,
                    QUICKJS_SYSTEM_PROMPT,
                )
            )
        )


__all__ = [
    "QUICKJS_MAX_OUTPUT_BYTES",
    "QUICKJS_MAX_SOURCE_BYTES",
    "QUICKJS_MEMORY_LIMIT_BYTES",
    "QUICKJS_OUTER_TIMEOUT_SECONDS",
    "QUICKJS_PERMISSIONS",
    "QUICKJS_RESULT_SCHEMA",
    "QUICKJS_STACK_LIMIT_BYTES",
    "QUICKJS_SYSTEM_PROMPT",
    "QUICKJS_TIMEOUT_SECONDS",
    "QUICKJS_TOOL_NAME",
    "BoundedQuickJSMiddleware",
    "quickjs_allowed",
    "server_quickjs_enabled",
]
