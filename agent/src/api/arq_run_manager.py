"""Run manager — Redis + ARQ-based background task execution.

Scales out by offloading create_run() to an ARQ worker process.
Events flow through Redis pub/sub so any web process can serve SSE.

Architecture:
    Web request → ArqRunManager.create_run()  → ARQ job (worker process)
    Web request → ArqRunManager.stream_run()  → graph.astream() inline (SSE)
    Web request → ArqRunManager.wait_run()    → graph.ainvoke() inline
    Web request → ArqRunManager.join_stream() → Redis pub/sub subscribe

Requires: pip install 'langgraph-fastapi-boilerplate[arq]'
          or: pip install arq redis
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph

from api.arq_run_queue import prune_stale_heads
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
from api.run_queue import RedisRunTurn, register_run, unregister_run
from db import DB

logger = logging.getLogger(__name__)

# Redis key helpers
_EVT_CHANNEL = "run:{run_id}:events"  # pub/sub channel for live events
_EVT_BUFFER = "run:{run_id}:buffer"  # list for event replay
_CTL_CHANNEL = "run:{run_id}:control"  # pub/sub channel for cancel signals
_BUFFER_TTL = 300  # seconds to keep buffer after run completes


def _key(template: str, run_id: str) -> str:
    return template.format(run_id=run_id)


class ArqRunManager(RunManagerBase):
    """Manages run lifecycle with ARQ worker + Redis pub/sub."""

    def __init__(
        self,
        db: DB,
        checkpointer: AsyncPostgresSaver,
        graphs: dict[str, CompiledStateGraph],
        redis_url: str,
    ):
        self.db = db
        self.checkpointer = checkpointer
        self.graphs = graphs
        self.redis_url = redis_url
        self._arq_pool: ArqRedis | None = None
        self._redis: aioredis.Redis | None = None

    async def setup(self) -> None:
        """Initialize ARQ pool and Redis connection. Call during app lifespan."""
        self._arq_pool = await create_pool(RedisSettings.from_dsn(self.redis_url))
        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)

    async def close(self) -> None:
        """Close connections. Call during app shutdown."""
        if self._arq_pool:
            await self._arq_pool.aclose()
        if self._redis:
            await self._redis.aclose()

    @property
    def redis(self) -> aioredis.Redis:
        assert self._redis is not None, "Call setup() first"
        return self._redis

    @property
    def arq_pool(self) -> ArqRedis:
        assert self._arq_pool is not None, "Call setup() first"
        return self._arq_pool

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

    # ---- Background run (offloaded to ARQ worker) ----

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

        raw_modes = (
            [stream_mode]
            if isinstance(stream_mode, str)
            else list(stream_mode or DEFAULT_BG_STREAM_MODES)
        )

        await register_run(self.redis, thread_key, run_id)
        try:
            # The Redis queue supplies cross-worker FIFO order; ARQ job IDs
            # prevent duplicate workers from executing the same run.
            job = await self.arq_pool.enqueue_job(
                "execute_run",
                run_id,
                thread_id,
                user_id=user_id,
                graph_id=graph_id,
                run_input=run_input,
                command=command,
                config=config,
                assistant_config=assistant_config,
                stream_mode=raw_modes,
                checkpoint_id=checkpoint_id,
                _job_id=f"run:{run_id}",
            )
            if job is None:
                raise RuntimeError(f"ARQ job for run {run_id} was not enqueued")
        except Exception:
            await unregister_run(self.redis, thread_key, run_id)
            await self.db.update_run_status(run_id, "error", user_id)
            raise

        return run_record

    # ---- Join stream (Redis pub/sub) ----

    async def join_stream(
        self, thread_id: str, run_id: str, *, user_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        yield {
            "event": "metadata",
            "data": json.dumps({"run_id": run_id, "attempt": 1}),
        }

        pubsub = self.redis.pubsub()
        channel = _key(_EVT_CHANNEL, run_id)
        buf_key = _key(_EVT_BUFFER, run_id)

        await pubsub.subscribe(channel)
        try:
            # Replay buffered events
            buffered = await self.redis.lrange(buf_key, 0, -1)
            for raw in buffered:
                event = json.loads(raw)
                if event is None:
                    return
                yield event

            # Live events from pub/sub
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                event = json.loads(msg["data"])
                if event is None:
                    break
                yield event
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    # ---- Stream run (inline, same as asyncio RunManager) ----

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
        await register_run(self.redis, thread_key, run_id)

        async def _generate() -> AsyncIterator[dict[str, Any]]:
            turn = RedisRunTurn(self.redis, thread_key, run_id)

            async def _prune_stale_predecessors() -> None:
                await prune_stale_heads(
                    self.db,
                    self.redis,
                    thread_id=thread_id,
                    thread_key=thread_key,
                    run_id=run_id,
                    user_id=user_id,
                )

            try:
                await turn.acquire(on_wait=_prune_stale_predecessors)
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
                await turn.release()

        return run_id, _generate()

    # ---- Wait run (inline) ----

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
        await register_run(self.redis, thread_key, run_id)
        turn = RedisRunTurn(self.redis, thread_key, run_id)

        async def _prune_stale_predecessors() -> None:
            await prune_stale_heads(
                self.db,
                self.redis,
                thread_id=thread_id,
                thread_key=thread_key,
                run_id=run_id,
                user_id=user_id,
            )

        try:
            await turn.acquire(on_wait=_prune_stale_predecessors)
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
            await turn.release()

    # ---- Cancel / Join ----

    async def cancel_run(self, thread_id: str, run_id: str, *, user_id: str) -> None:
        # Publish cancel signal to worker
        channel = _key(_CTL_CHANNEL, run_id)
        await self.redis.publish(channel, "cancel")
        await self.db.update_run_status(run_id, "interrupted", user_id)
        await self.db.set_thread_status(thread_id, "interrupted", user_id)

    async def join_run(
        self, thread_id: str, run_id: str, *, user_id: str
    ) -> dict[str, Any] | None:
        # Wait for run completion by subscribing to events
        pubsub = self.redis.pubsub()
        channel = _key(_EVT_CHANNEL, run_id)
        await pubsub.subscribe(channel)

        try:
            # Check if already complete (buffer has sentinel)
            buf_key = _key(_EVT_BUFFER, run_id)
            last = await self.redis.lindex(buf_key, -1)
            if last is not None and json.loads(last) is None:
                pass  # already done, fall through to checkpoint read
            else:
                # Wait for sentinel
                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue
                    if json.loads(msg["data"]) is None:
                        break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

        config = build_graph_config(thread_id, user_id=user_id)
        snapshot = await self.checkpointer.aget_tuple(config)
        if snapshot:
            return snapshot.checkpoint.get("channel_values", {})
        return None
