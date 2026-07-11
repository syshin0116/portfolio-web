"""Optional ARQ execution tests for server-owned checkpoint identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.resource_scope import scoped_checkpoint_thread_id

ArqRunManager = pytest.importorskip("api.arq_run_manager").ArqRunManager
execute_run = pytest.importorskip("worker").execute_run


def _untrusted_config(source: str) -> dict:
    return {
        "configurable": {
            "thread_id": f"{source}-thread",
            "user_id": f"{source}-user",
            "checkpoint_id": f"{source}-checkpoint",
            "checkpoint_ns": f"{source}-namespace",
            "checkpoint_map": {"forged": source},
            "model": source,
        }
    }


def test_arq_run_manager_uses_shared_config_policy():
    manager = ArqRunManager(MagicMock(), MagicMock(), {}, "redis://localhost")
    checkpoint_thread_id = scoped_checkpoint_thread_id("server-user", "server-thread")

    config = manager._build_config(
        "server-thread",
        user_id="server-user",
        assistant_config=_untrusted_config("assistant"),
        run_config=_untrusted_config("run"),
        checkpoint_id="server-checkpoint",
    )

    assert config["configurable"] == {
        "thread_id": checkpoint_thread_id,
        "user_id": "server-user",
        "checkpoint_id": "server-checkpoint",
        "model": "run",
    }


class _Graph:
    config = None

    async def astream(self, graph_input, *, config, stream_mode, context):
        self.config = config
        yield {"done": True}


class _PubSub:
    subscribe = AsyncMock()
    unsubscribe = AsyncMock()
    aclose = AsyncMock()

    async def listen(self):
        if False:
            yield None


@pytest.mark.asyncio
async def test_worker_uses_shared_config_policy():
    graph = _Graph()
    pubsub = _PubSub()
    lock = SimpleNamespace(
        acquire=AsyncMock(return_value=True),
        extend=AsyncMock(return_value=True),
        release=AsyncMock(),
    )
    redis = SimpleNamespace(
        pubsub=lambda: pubsub,
        rpush=AsyncMock(),
        publish=AsyncMock(),
        expire=AsyncMock(),
        lindex=AsyncMock(return_value="run-id"),
        lock=lambda *args, **kwargs: lock,
        eval=AsyncMock(),
        set=AsyncMock(),
    )
    db = AsyncMock()
    db.get_run.return_value = {"status": "pending"}
    checkpoint_thread_id = scoped_checkpoint_thread_id("server-user", "server-thread")
    db.get_run.return_value = {"status": "pending"}

    await execute_run(
        {"db": db, "graphs": {"agent": graph}, "redis": redis},
        "run-id",
        "server-thread",
        user_id="server-user",
        config=_untrusted_config("run"),
        assistant_config=_untrusted_config("assistant"),
        checkpoint_id="server-checkpoint",
        stream_mode=["values"],
    )

    assert graph.config["configurable"] == {
        "thread_id": checkpoint_thread_id,
        "user_id": "server-user",
        "checkpoint_id": "server-checkpoint",
        "model": "run",
    }
