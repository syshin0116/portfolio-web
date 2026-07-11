"""Run manager — asyncio-based background task execution (default, no Redis).

Architecture:
    Web request → RunManager.create_run()   → asyncio.Task (background)
    Web request → RunManager.stream_run()   → graph.astream() inline (SSE)
    Web request → RunManager.wait_run()     → graph.ainvoke() inline
    Web request → RunManager.join_stream()  → rejoin existing run's SSE

For Redis + ARQ scaling, see arq_run_manager.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph

from api.resource_scope import scoped_checkpoint_thread_id
from api.run_manager_base import (
    DEFAULT_BG_STREAM_MODES,
    RunConflictError,
    RunManagerBase,
    build_graph_config,
    format_stream_event,
    normalize_stream_modes,
    resolve_input,
)
from db import DB

# Re-export for backwards compatibility
__all__ = ["RunConflictError", "RunManager"]

logger = logging.getLogger(__name__)


class RunManager(RunManagerBase):
    """Manages run lifecycle with asyncio tasks (no Redis required)."""

    def __init__(
        self,
        db: DB,
        checkpointer: AsyncPostgresSaver,
        graphs: dict[str, CompiledStateGraph],
    ):
        self.db = db
        self.checkpointer = checkpointer
        self.graphs = graphs
        self._active_tasks: dict[str, asyncio.Task] = {}  # run_id → Task
        self._turn_cleanup_tasks: set[asyncio.Task[None]] = set()
        self._thread_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._thread_conditions: dict[str, asyncio.Condition] = defaultdict(
            asyncio.Condition
        )
        self._thread_queues: dict[str, deque[object]] = defaultdict(deque)
        self._event_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._run_threads: dict[str, str] = {}  # run_id → thread_id
        self._event_buffers: dict[
            str, list[dict | None]
        ] = {}  # run_id → buffered events

    def _get_graph(self, graph_id: str = "agent") -> CompiledStateGraph:
        graph = self.graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Unknown graph_id: {graph_id}")
        return graph

    def _build_config(
        self,
        thread_id: str,
        *,
        user_id: str,
        assistant_config: dict | None = None,
        run_config: dict | None = None,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        """Build the LangGraph config dict."""
        return build_graph_config(
            thread_id,
            user_id=user_id,
            assistant_config=assistant_config,
            run_config=run_config,
            checkpoint_id=checkpoint_id,
        )

    async def _handle_multitask(
        self, thread_id: str, user_id: str, strategy: str
    ) -> None:
        """Handle multitask strategy before starting a new run."""
        active_run = await self.db.get_active_run_for_thread(thread_id, user_id)
        if not active_run:
            return

        run_id = str(active_run["run_id"])

        if strategy == "reject":
            raise RunConflictError(
                f"Thread {thread_id} already has an active run {run_id}"
            )
        elif strategy in ("interrupt", "rollback"):
            await self.cancel_run(thread_id, run_id, user_id=user_id)
        # enqueue: handled by the per-thread FIFO execution queue

    def _register_thread_run(self, thread_id: str) -> object:
        """Reserve a FIFO execution turn before the run task is scheduled."""
        ticket = object()
        self._thread_queues[thread_id].append(ticket)
        return ticket

    async def _wait_for_thread_turn(
        self, thread_id: str, ticket: object
    ) -> asyncio.Lock:
        condition = self._thread_conditions[thread_id]
        async with condition:
            await condition.wait_for(
                lambda: self._thread_queues[thread_id][0] is ticket
            )

        lock = self._thread_locks[thread_id]
        await lock.acquire()
        return lock

    async def _finish_thread_turn(
        self,
        thread_id: str,
        ticket: object,
        lock: asyncio.Lock | None,
    ) -> None:
        condition = self._thread_conditions.get(thread_id)
        queue = self._thread_queues.get(thread_id)
        if condition is None or queue is None:
            if lock and lock.locked():
                lock.release()
            return

        async with condition:
            if ticket in queue:
                queue.remove(ticket)
            condition.notify_all()

        if lock and lock.locked():
            lock.release()

        if not queue:
            self._thread_queues.pop(thread_id, None)
            self._thread_conditions.pop(thread_id, None)
            self._thread_locks.pop(thread_id, None)

    # ---- Background run ----

    async def create_run(
        self,
        thread_id: str,
        *,
        user_id: str,
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
    ) -> dict[str, Any]:
        """Create a run — executes in background asyncio.Task."""
        if multitask_strategy != "enqueue":
            await self._handle_multitask(thread_id, user_id, multitask_strategy)

        run_record = await self.db.create_run(
            thread_id=thread_id,
            owner_id=user_id,
            assistant_id=assistant_id,
            input=run_input,
            command=command,
            config=config,
            metadata=metadata,
            kwargs={
                "interrupt_before": interrupt_before,
                "interrupt_after": interrupt_after,
                "webhook": webhook,
                "graph_id": graph_id,
            },
            multitask_strategy=multitask_strategy,
            status="pending",
        )
        if run_record is None:
            raise ValueError(f"Thread {thread_id} is not owned by the current user")

        run_id = str(run_record["run_id"])
        thread_key = scoped_checkpoint_thread_id(user_id, thread_id)
        ticket = self._register_thread_run(thread_key)
        self._run_threads[run_id] = thread_id
        self._event_buffers[run_id] = []  # buffer events for late-joining subscribers

        task = asyncio.create_task(
            self._execute_run(
                run_id,
                thread_id,
                user_id=user_id,
                graph_id=graph_id,
                run_input=run_input,
                command=command,
                config=config,
                assistant_config=assistant_config,
                stream_mode=stream_mode,
                checkpoint_id=checkpoint_id,
                ticket=ticket,
                thread_key=thread_key,
            )
        )
        self._active_tasks[run_id] = task

        def _cleanup(t: asyncio.Task) -> None:
            self._active_tasks.pop(run_id, None)
            self._run_threads.pop(run_id, None)
            if t.cancelled():
                # A Task cancelled before its first coroutine step never enters
                # _execute_run's finally block, so release its reserved turn here.
                self._publish_event(run_id, None)
                self._event_queues.pop(run_id, None)
                cleanup_task = asyncio.create_task(
                    self._finish_thread_turn(thread_key, ticket, None)
                )
                self._turn_cleanup_tasks.add(cleanup_task)
                cleanup_task.add_done_callback(self._turn_cleanup_tasks.discard)
            # Keep _event_buffers for late join_stream calls; cleaned up in join_stream

        task.add_done_callback(_cleanup)

        return run_record

    def _publish_event(self, run_id: str, event: dict | None) -> None:
        """Push an event to all subscriber queues and buffer for late joiners."""
        buf = self._event_buffers.get(run_id)
        if buf is not None:
            buf.append(event)
        for q in self._event_queues.get(run_id, []):
            q.put_nowait(event)

    async def _execute_run(
        self,
        run_id: str,
        thread_id: str,
        *,
        user_id: str,
        graph_id: str = "agent",
        run_input: dict | None = None,
        command: dict | None = None,
        config: dict | None = None,
        assistant_config: dict | None = None,
        stream_mode: list[str] | str | None = None,
        checkpoint_id: str | None = None,
        ticket: object,
        thread_key: str,
    ) -> None:
        """Execute a run in the background, publishing events to subscribers."""
        lock: asyncio.Lock | None = None
        try:
            lock = await self._wait_for_thread_turn(thread_key, ticket)
            graph = self._get_graph(graph_id)
            lg_config = self._build_config(
                thread_id,
                user_id=user_id,
                assistant_config=assistant_config,
                run_config=config,
                checkpoint_id=checkpoint_id,
            )
            graph_input = resolve_input(run_input, command)

            raw_modes = (
                [stream_mode]
                if isinstance(stream_mode, str)
                else list(stream_mode or DEFAULT_BG_STREAM_MODES)
            )
            modes = normalize_stream_modes(raw_modes)

            await self.db.update_run_status(run_id, "running", user_id)
            await self.db.set_thread_status(thread_id, "busy", user_id)

            # Publish metadata event
            self._publish_event(
                run_id,
                {
                    "event": "metadata",
                    "data": json.dumps({"run_id": run_id, "attempt": 1}),
                },
            )

            if len(modes) == 1:
                async for chunk in graph.astream(
                    graph_input, config=lg_config, stream_mode=modes[0], context={}
                ):
                    event = format_stream_event(modes[0], chunk)
                    self._publish_event(run_id, event)
            else:
                async for mode, chunk in graph.astream(
                    graph_input, config=lg_config, stream_mode=modes, context={}
                ):
                    event = format_stream_event(mode, chunk)
                    self._publish_event(run_id, event)

            await self.db.update_run_status(run_id, "success", user_id)
            await self.db.set_thread_status(thread_id, "idle", user_id)
        except asyncio.CancelledError:
            await self.db.update_run_status(run_id, "interrupted", user_id)
            await self.db.set_thread_status(thread_id, "interrupted", user_id)
        except Exception as e:
            logger.exception("Run %s failed: %s", run_id, e)
            await self.db.update_run_status(run_id, "error", user_id)
            await self.db.set_thread_status(thread_id, "error", user_id)
            self._publish_event(
                run_id, {"event": "error", "data": json.dumps({"error": str(e)})}
            )
        finally:
            self._publish_event(run_id, None)  # sentinel — end of stream
            self._event_queues.pop(run_id, None)
            await self._finish_thread_turn(thread_key, ticket, lock)

    # ---- Join stream (rejoin existing run) ----

    async def join_stream(
        self,
        thread_id: str,
        run_id: str,
        *,
        user_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to events from an existing run (for SSE rejoin after disconnect).

        Uses an event buffer to replay events that fired before the subscriber
        connected — this prevents the race condition where create_run() completes
        before the client calls GET /runs/{run_id}/stream.
        """
        yield {
            "event": "metadata",
            "data": json.dumps({"run_id": run_id, "attempt": 1}),
        }

        buf = self._event_buffers.get(run_id)

        if buf is not None:
            # Subscribe to live events FIRST (single-threaded asyncio: no
            # events fire between append and len snapshot)
            queue: asyncio.Queue = asyncio.Queue()
            self._event_queues[run_id].append(queue)
            snapshot_len = len(buf)

            try:
                # Replay buffered events (everything before subscription)
                for i in range(snapshot_len):
                    event = buf[i]
                    if event is None:  # run already finished
                        return
                    yield event

                # Drain live queue (events after subscription point)
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield event
            finally:
                queues = self._event_queues.get(run_id, [])
                if queue in queues:
                    queues.remove(queue)
                # Clean up buffer if run is done and no more subscribers
                if not self._event_queues.get(run_id):
                    self._event_buffers.pop(run_id, None)
            return

        # No buffer — run was not created via create_run (legacy path)
        task = self._active_tasks.get(run_id)

        if not task or task.done():
            config = build_graph_config(thread_id, user_id=user_id)
            snapshot = await self.checkpointer.aget_tuple(config)
            if snapshot:
                state = snapshot.checkpoint.get("channel_values", {})
                yield format_stream_event("values", state)
            return

        queue = asyncio.Queue()
        self._event_queues[run_id].append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            queues = self._event_queues.get(run_id, [])
            if queue in queues:
                queues.remove(queue)

    # ---- Stream run ----

    async def stream_run(
        self,
        thread_id: str,
        *,
        user_id: str,
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
    ) -> tuple[str, AsyncIterator[dict[str, Any]]]:
        """Create a streaming run. Returns (run_id, event_generator).

        The run_id is returned eagerly so callers can set the Location header
        for SSE reconnection support.
        """
        if multitask_strategy != "enqueue":
            await self._handle_multitask(thread_id, user_id, multitask_strategy)

        run_record = await self.db.create_run(
            thread_id=thread_id,
            owner_id=user_id,
            assistant_id=assistant_id,
            input=run_input,
            command=command,
            config=config,
            metadata=metadata,
            multitask_strategy=multitask_strategy,
            status="pending",
        )
        if run_record is None:
            raise ValueError(f"Thread {thread_id} is not owned by the current user")
        run_id = str(run_record["run_id"])
        thread_key = scoped_checkpoint_thread_id(user_id, thread_id)
        ticket = self._register_thread_run(thread_key)

        async def _generate() -> AsyncIterator[dict[str, Any]]:
            lock: asyncio.Lock | None = None
            try:
                lock = await self._wait_for_thread_turn(thread_key, ticket)
                graph = self._get_graph(graph_id)
                lg_config = self._build_config(
                    thread_id,
                    user_id=user_id,
                    assistant_config=assistant_config,
                    run_config=config,
                    checkpoint_id=checkpoint_id,
                )
                graph_input = resolve_input(run_input, command)
                modes = (
                    [stream_mode] if isinstance(stream_mode, str) else list(stream_mode)
                )
                modes = normalize_stream_modes(modes)

                await self.db.update_run_status(run_id, "running", user_id)
                await self.db.set_thread_status(thread_id, "busy", user_id)

                yield {
                    "event": "metadata",
                    "data": json.dumps({"run_id": run_id, "attempt": 1}),
                }

                if len(modes) == 1:
                    async for chunk in graph.astream(
                        graph_input, config=lg_config, stream_mode=modes[0], context={}
                    ):
                        yield format_stream_event(modes[0], chunk)
                else:
                    async for mode, chunk in graph.astream(
                        graph_input, config=lg_config, stream_mode=modes, context={}
                    ):
                        yield format_stream_event(mode, chunk)

                await self.db.update_run_status(run_id, "success", user_id)
                await self.db.set_thread_status(thread_id, "idle", user_id)
            except asyncio.CancelledError:
                await self.db.update_run_status(run_id, "interrupted", user_id)
                await self.db.set_thread_status(thread_id, "interrupted", user_id)
                raise
            except Exception as e:
                logger.exception("Stream run %s failed: %s", run_id, e)
                await self.db.update_run_status(run_id, "error", user_id)
                await self.db.set_thread_status(thread_id, "error", user_id)
                yield {"event": "error", "data": json.dumps({"error": str(e)})}
            finally:
                await self._finish_thread_turn(thread_key, ticket, lock)

        return run_id, _generate()

    # ---- Wait run ----

    async def wait_run(
        self,
        thread_id: str,
        *,
        user_id: str,
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
    ) -> dict[str, Any]:
        """Execute a run and wait for the result (synchronous from caller's perspective)."""
        if multitask_strategy != "enqueue":
            await self._handle_multitask(thread_id, user_id, multitask_strategy)

        run_record = await self.db.create_run(
            thread_id=thread_id,
            owner_id=user_id,
            assistant_id=assistant_id,
            input=run_input,
            command=command,
            config=config,
            metadata=metadata,
            multitask_strategy=multitask_strategy,
            status="pending",
        )
        if run_record is None:
            raise ValueError(f"Thread {thread_id} is not owned by the current user")
        run_id = str(run_record["run_id"])
        thread_key = scoped_checkpoint_thread_id(user_id, thread_id)
        ticket = self._register_thread_run(thread_key)
        lock: asyncio.Lock | None = None

        try:
            lock = await self._wait_for_thread_turn(thread_key, ticket)
            graph = self._get_graph(graph_id)
            lg_config = self._build_config(
                thread_id,
                user_id=user_id,
                assistant_config=assistant_config,
                run_config=config,
                checkpoint_id=checkpoint_id,
            )
            graph_input = resolve_input(run_input, command)

            await self.db.update_run_status(run_id, "running", user_id)
            await self.db.set_thread_status(thread_id, "busy", user_id)

            result = await graph.ainvoke(graph_input, config=lg_config, context={})
            await self.db.update_run_status(run_id, "success", user_id)
            await self.db.set_thread_status(thread_id, "idle", user_id)
            return result
        except asyncio.CancelledError:
            await self.db.update_run_status(run_id, "interrupted", user_id)
            await self.db.set_thread_status(thread_id, "interrupted", user_id)
            return {"__error__": "Run was cancelled"}
        except Exception as e:
            logger.exception("Wait run %s failed: %s", run_id, e)
            await self.db.update_run_status(run_id, "error", user_id)
            await self.db.set_thread_status(thread_id, "error", user_id)
            return {"__error__": str(e)}
        finally:
            await self._finish_thread_turn(thread_key, ticket, lock)

    # ---- Cancel / Join ----

    async def cancel_run(self, thread_id: str, run_id: str, *, user_id: str) -> None:
        """Cancel an active run."""
        task = self._active_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await self.db.update_run_status(run_id, "interrupted", user_id)
        await self.db.set_thread_status(thread_id, "interrupted", user_id)

    async def join_run(
        self, thread_id: str, run_id: str, *, user_id: str
    ) -> dict[str, Any] | None:
        """Wait for a background run to complete, return thread state."""
        task = self._active_tasks.get(run_id)
        if task and not task.done():
            await task

        config = build_graph_config(thread_id, user_id=user_id)
        snapshot = await self.checkpointer.aget_tuple(config)
        if snapshot:
            return snapshot.checkpoint.get("channel_values", {})
        return None
