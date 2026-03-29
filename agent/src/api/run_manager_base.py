"""Run manager base class and shared helpers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class RunConflictError(Exception):
    """Raised when a run conflicts with multitask strategy."""

    pass


class RunManagerBase(ABC):
    """Abstract interface for run lifecycle management."""

    @abstractmethod
    async def create_run(
        self,
        thread_id: str,
        *,
        graph_id: str = "agent",
        run_input: dict | None = None,
        command: dict | None = None,
        config: dict | None = None,
        assistant_id: str | None = None,
        assistant_config: dict | None = None,
        metadata: dict | None = None,
        multitask_strategy: str = "reject",
        stream_mode: list[str] | str | None = None,
        interrupt_before: list[str] | str | None = None,
        interrupt_after: list[str] | str | None = None,
        webhook: str | None = None,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def stream_run(
        self,
        thread_id: str,
        *,
        graph_id: str = "agent",
        run_input: dict | None = None,
        command: dict | None = None,
        config: dict | None = None,
        assistant_id: str | None = None,
        assistant_config: dict | None = None,
        metadata: dict | None = None,
        stream_mode: list[str] | str = "values",
        multitask_strategy: str = "reject",
        interrupt_before: list[str] | str | None = None,
        interrupt_after: list[str] | str | None = None,
        on_disconnect: str = "cancel",
        checkpoint_id: str | None = None,
    ) -> tuple[str, AsyncIterator[dict[str, Any]]]: ...

    @abstractmethod
    async def wait_run(
        self,
        thread_id: str,
        *,
        graph_id: str = "agent",
        run_input: dict | None = None,
        command: dict | None = None,
        config: dict | None = None,
        assistant_id: str | None = None,
        assistant_config: dict | None = None,
        metadata: dict | None = None,
        multitask_strategy: str = "reject",
        interrupt_before: list[str] | str | None = None,
        interrupt_after: list[str] | str | None = None,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def join_stream(
        self, thread_id: str, run_id: str
    ) -> AsyncIterator[dict[str, Any]]: ...

    @abstractmethod
    async def cancel_run(self, thread_id: str, run_id: str) -> None: ...

    @abstractmethod
    async def join_run(self, thread_id: str, run_id: str) -> dict[str, Any] | None: ...


# ---- Shared helpers ----

# Default stream modes for background runs (matches LangGraph Platform:
# "Background runs default to having the union of all stream modes enabled")
DEFAULT_BG_STREAM_MODES = ["values", "messages-tuple", "updates"]


def resolve_input(run_input: dict | None, command: dict | None) -> Any:
    """Resolve graph input from run_input or command."""
    if command:
        from langgraph.types import Command

        return Command(**command)
    return run_input


def serialize_value(v: Any) -> Any:
    """Make a value JSON-serializable."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, dict):
        return {k: serialize_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [serialize_value(item) for item in v]
    if hasattr(v, "model_dump"):
        return v.model_dump()
    if hasattr(v, "dict"):
        return v.dict()
    return str(v)


def normalize_stream_modes(modes: list[str]) -> list[str]:
    """Map SDK stream mode names to LangGraph library names.

    The @langchain/react SDK sends 'messages-tuple' but LangGraph's
    graph.astream() only accepts 'messages'.
    """
    mapping = {"messages-tuple": "messages"}
    return [mapping.get(m, m) for m in modes]


def format_stream_event(mode: str, chunk: Any) -> dict[str, str]:
    """Format a graph stream chunk as an SSE event dict.

    The @langchain/langgraph-sdk StreamManager expects:
    - event name = stream mode name (e.g. "values", "messages")
    - messages data = [message_chunk, metadata] (array, not dict)
    """
    if mode == "messages" and isinstance(chunk, tuple) and len(chunk) == 2:
        msg, meta = chunk
        data = [serialize_value(msg), serialize_value(meta)]
        return {"event": "messages", "data": json.dumps(data, default=str)}

    return {"event": mode, "data": json.dumps(serialize_value(chunk), default=str)}
