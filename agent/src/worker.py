"""ARQ worker — executes background runs in a separate process.

Usage:
    cd backend && REDIS_URL=redis://localhost:6379 uv run arq worker.WorkerSettings

The worker shares the same graph registry and DB as the web process.
Events are published to Redis pub/sub so any web process can serve SSE.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis
from arq.connections import RedisSettings
from dotenv import load_dotenv
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from agent.graph import create_graph
from api.logging_config import setup_logging
from api.run_manager_base import (
    DEFAULT_BG_STREAM_MODES,
    format_stream_event,
    normalize_stream_modes,
    resolve_input,
)
from db import DB

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

# Redis key templates
_EVT_CHANNEL = "run:{run_id}:events"
_EVT_BUFFER = "run:{run_id}:buffer"
_CTL_CHANNEL = "run:{run_id}:control"
_BUFFER_TTL = 300


def _key(template: str, run_id: str) -> str:
    return template.format(run_id=run_id)


async def execute_run(
    ctx: dict,
    run_id: str,
    thread_id: str,
    *,
    graph_id: str = "agent",
    run_input: dict | None = None,
    command: dict | None = None,
    config: dict | None = None,
    assistant_config: dict | None = None,
    stream_mode: list[str] | None = None,
    checkpoint_id: str | None = None,
) -> None:
    """Execute a run in the worker, publishing events to Redis."""
    db: DB = ctx["db"]
    graphs = ctx["graphs"]
    redis: aioredis.Redis = ctx["redis"]

    graph = graphs.get(graph_id)
    if not graph:
        logger.error("Unknown graph_id: %s", graph_id)
        return

    # Build LangGraph config
    configurable: dict = {"thread_id": thread_id}
    if assistant_config:
        configurable.update(assistant_config.get("configurable", {}))
    if config:
        configurable.update(config.get("configurable", {}))
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    lg_config = {"configurable": configurable}

    graph_input = resolve_input(run_input, command)

    raw_modes = stream_mode or DEFAULT_BG_STREAM_MODES
    modes = normalize_stream_modes(raw_modes)

    evt_channel = _key(_EVT_CHANNEL, run_id)
    buf_key = _key(_EVT_BUFFER, run_id)
    ctl_channel = _key(_CTL_CHANNEL, run_id)

    async def publish(event: dict | None) -> None:
        raw = json.dumps(event)
        await redis.rpush(buf_key, raw)
        await redis.publish(evt_channel, raw)

    # Listen for cancel signals
    cancelled = asyncio.Event()
    pubsub = redis.pubsub()
    await pubsub.subscribe(ctl_channel)

    async def _cancel_listener() -> None:
        async for msg in pubsub.listen():
            if msg["type"] == "message" and msg["data"] == "cancel":
                cancelled.set()
                break

    cancel_task = asyncio.create_task(_cancel_listener())

    try:
        await db.update_run_status(run_id, "running")
        await db.set_thread_status(thread_id, "busy")

        # Metadata event
        await publish(
            {"event": "metadata", "data": json.dumps({"run_id": run_id, "attempt": 1})}
        )

        if len(modes) == 1:
            async for chunk in graph.astream(
                graph_input, config=lg_config, stream_mode=modes[0], context={}
            ):
                if cancelled.is_set():
                    raise asyncio.CancelledError()
                await publish(format_stream_event(modes[0], chunk))
        else:
            async for mode, chunk in graph.astream(
                graph_input, config=lg_config, stream_mode=modes, context={}
            ):
                if cancelled.is_set():
                    raise asyncio.CancelledError()
                await publish(format_stream_event(mode, chunk))

        await db.update_run_status(run_id, "success")
        await db.set_thread_status(thread_id, "idle")

    except asyncio.CancelledError:
        await db.update_run_status(run_id, "interrupted")
        await db.set_thread_status(thread_id, "interrupted")

    except Exception as e:
        logger.exception("Run %s failed: %s", run_id, e)
        await db.update_run_status(run_id, "error")
        await db.set_thread_status(thread_id, "error")
        await publish({"event": "error", "data": json.dumps({"error": str(e)})})

    finally:
        # Sentinel — end of stream
        await publish(None)
        # Set TTL on buffer so Redis self-cleans
        await redis.expire(buf_key, _BUFFER_TTL)
        # Cleanup cancel listener
        cancel_task.cancel()
        await pubsub.unsubscribe(ctl_channel)
        await pubsub.aclose()


async def startup(ctx: dict) -> None:
    """ARQ worker startup — initialize DB, checkpointer, graphs."""
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
    )
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    pool = AsyncConnectionPool(
        conninfo=database_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    db = DB(pool)
    await db.setup()

    compiled_graphs = {
        "agent": create_graph(checkpointer=checkpointer),
    }

    redis = aioredis.from_url(redis_url, decode_responses=True)

    ctx["pool"] = pool
    ctx["db"] = db
    ctx["checkpointer"] = checkpointer
    ctx["graphs"] = compiled_graphs
    ctx["redis"] = redis

    logger.info("Worker started — graphs: %s", list(compiled_graphs.keys()))


async def shutdown(ctx: dict) -> None:
    """ARQ worker shutdown — close connections."""
    redis: aioredis.Redis | None = ctx.get("redis")
    if redis:
        await redis.aclose()
    pool = ctx.get("pool")
    if pool:
        await pool.close()
    logger.info("Worker shut down")


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [execute_run]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    max_jobs = 10
    job_timeout = 600  # 10 minutes
