"""Concurrency tests for in-process per-thread run serialization."""

import asyncio

import pytest

from api.run_manager import RunManager


class _DB:
    def __init__(self):
        self.created: list[str] = []
        self.statuses: dict[str, str] = {}
        self.third_created = asyncio.Event()

    async def create_run(self, **kwargs):
        run_id = f"run-{len(self.created) + 1}"
        self.created.append(run_id)
        if len(self.created) == 3:
            self.third_created.set()
        self.statuses[run_id] = kwargs["status"]
        return {"run_id": run_id}

    async def update_run_status(self, run_id, status, owner_id):
        self.statuses[run_id] = status

    async def set_thread_status(self, thread_id, status, owner_id):
        return None

    async def get_active_run_for_thread(self, thread_id, owner_id):
        return None


class _Graph:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.order: list[str] = []
        self.started = {
            "first": asyncio.Event(),
            "second": asyncio.Event(),
        }
        self.release = {
            "first": asyncio.Event(),
            "second": asyncio.Event(),
        }

    async def _run(self, graph_input):
        name = graph_input["name"]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.order.append(name)
        try:
            if name in self.started:
                self.started[name].set()
                await self.release[name].wait()
            return {"name": name}
        finally:
            self.active -= 1

    async def astream(self, graph_input, **kwargs):
        result = await self._run(graph_input)
        stream_mode = kwargs["stream_mode"]
        if isinstance(stream_mode, list):
            yield stream_mode[0], result
        else:
            yield result

    async def ainvoke(self, graph_input, **kwargs):
        return await self._run(graph_input)


async def _consume(events):
    return [event async for event in events]


@pytest.mark.asyncio
async def test_all_local_run_modes_share_fifo_thread_execution():
    db = _DB()
    graph = _Graph()
    manager = RunManager(db, None, {"agent": graph})

    first = await manager.create_run(
        "thread-1",
        user_id="user-1",
        run_input={"name": "first"},
        multitask_strategy="enqueue",
    )
    first_task = manager._active_tasks[first["run_id"]]
    await asyncio.wait_for(graph.started["first"].wait(), timeout=1)

    second = await manager.create_run(
        "thread-1",
        user_id="user-1",
        run_input={"name": "second"},
        multitask_strategy="enqueue",
    )
    second_task = manager._active_tasks[second["run_id"]]

    wait_task = asyncio.create_task(
        manager.wait_run(
            "thread-1",
            user_id="user-1",
            run_input={"name": "third"},
            multitask_strategy="enqueue",
        )
    )
    await asyncio.wait_for(db.third_created.wait(), timeout=1)

    _, stream = await manager.stream_run(
        "thread-1",
        user_id="user-1",
        run_input={"name": "fourth"},
        multitask_strategy="enqueue",
    )
    stream_task = asyncio.create_task(_consume(stream))

    await asyncio.sleep(0.01)
    assert graph.order == ["first"]

    graph.release["first"].set()
    await asyncio.wait_for(graph.started["second"].wait(), timeout=1)
    assert graph.order == ["first", "second"]

    graph.release["second"].set()
    await asyncio.wait_for(
        asyncio.gather(first_task, second_task, wait_task, stream_task),
        timeout=1,
    )

    assert graph.order == ["first", "second", "third", "fourth"]
    assert graph.max_active == 1
    assert all(status == "success" for status in db.statuses.values())


@pytest.mark.asyncio
async def test_cancel_before_task_entry_releases_fifo_turn():
    db = _DB()
    graph = _Graph()
    manager = RunManager(db, None, {"agent": graph})

    cancelled = await manager.create_run(
        "thread-1",
        user_id="user-1",
        run_input={"name": "never-started"},
        multitask_strategy="enqueue",
    )
    await manager.cancel_run(
        "thread-1",
        cancelled["run_id"],
        user_id="user-1",
    )

    result = await asyncio.wait_for(
        manager.wait_run(
            "thread-1",
            user_id="user-1",
            run_input={"name": "after-cancel"},
            multitask_strategy="enqueue",
        ),
        timeout=1,
    )

    assert result == {"name": "after-cancel"}
    assert graph.order == ["after-cancel"]
