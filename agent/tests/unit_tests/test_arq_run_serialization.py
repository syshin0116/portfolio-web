"""Concurrency tests for Redis-backed per-thread run serialization."""

import asyncio
import contextlib
from collections import defaultdict, deque

import pytest

arq = pytest.importorskip("arq")
Retry = arq.Retry
run_queue = pytest.importorskip("api.run_queue")
RedisRunTurn = run_queue.RedisRunTurn
register_run = run_queue.register_run
arq_run_queue = pytest.importorskip("api.arq_run_queue")
worker = pytest.importorskip("worker")


class _State:
    def __init__(self):
        self.queues = defaultdict(deque)
        self.locks = defaultdict(asyncio.Lock)
        self.values = {}
        self.queued_jobs = set()
        self.data_lock = asyncio.Lock()


class _Lock:
    def __init__(self, lock):
        self.lock = lock

    async def acquire(self):
        await self.lock.acquire()
        return True

    async def extend(self, additional_time, *, replace_ttl):
        return True

    async def release(self):
        self.lock.release()


class _Redis:
    def __init__(self, state):
        self.state = state

    async def lindex(self, key, index):
        async with self.state.data_lock:
            queue = self.state.queues[key]
            return queue[index] if queue else None

    async def eval(self, script, numkeys, *args):
        async with self.state.data_lock:
            if "RPUSH" in script:
                key, heartbeat_key, run_id, _ttl = args
                self.state.queues[key].append(run_id)
                self.state.values[heartbeat_key] = "1"
                return 1

            key, heartbeat_key, run_id = args
            queue = self.state.queues[key]
            if queue and queue[0] == run_id:
                queue.popleft()
            else:
                with contextlib.suppress(ValueError):
                    queue.remove(run_id)
            self.state.values.pop(heartbeat_key, None)
            return 1

    async def set(self, key, value, **kwargs):
        async with self.state.data_lock:
            self.state.values[key] = value

    async def exists(self, key):
        async with self.state.data_lock:
            return key in self.state.values

    async def zscore(self, key, member):
        return 1 if member in self.state.queued_jobs else None

    def lock(self, key, **kwargs):
        return _Lock(self.state.locks[key])


class _DB:
    def __init__(self):
        self.records = {"stale": {"status": "pending"}}
        self.statuses = {}

    async def get_run(self, thread_id, run_id, user_id):
        return self.records.get(run_id)

    async def update_run_status(self, run_id, status, user_id):
        self.statuses[run_id] = status


@pytest.mark.asyncio
async def test_redis_turn_is_fifo_across_worker_connections():
    state = _State()
    first_redis = _Redis(state)
    second_redis = _Redis(state)
    await register_run(first_redis, "thread-1", "first")
    await register_run(second_redis, "thread-1", "second")

    order = []
    active = 0
    max_active = 0
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def run(redis, run_id):
        nonlocal active, max_active
        turn = RedisRunTurn(redis, "thread-1", run_id)
        try:
            await turn.acquire()
            active += 1
            max_active = max(max_active, active)
            order.append(run_id)
            if run_id == "first":
                first_started.set()
                await release_first.wait()
            active -= 1
        finally:
            await turn.release()

    # Let the later worker contend first; Redis queue order must still win.
    second_task = asyncio.create_task(run(second_redis, "second"))
    await asyncio.sleep(0)
    first_task = asyncio.create_task(run(first_redis, "first"))

    await asyncio.wait_for(first_started.wait(), timeout=1)
    assert order == ["first"]

    release_first.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1)

    assert order == ["first", "second"]
    assert max_active == 1


@pytest.mark.asyncio
async def test_worker_recovers_queue_head_with_no_executor():
    state = _State()
    redis = _Redis(state)
    db = _DB()
    await register_run(redis, "scoped-thread", "stale")
    await register_run(redis, "scoped-thread", "current")

    # Simulate a web process dying after registration but before ARQ enqueue.
    stale_heartbeat = next(key for key in state.values if "stale" in key)
    state.values.pop(stale_heartbeat)

    await worker._wait_for_fifo_turn(
        db,
        redis,
        thread_id="public-thread",
        thread_key="scoped-thread",
        run_id="current",
        user_id="user-1",
    )

    assert await run_queue.get_run_head(redis, "scoped-thread") == "current"
    assert db.statuses == {"stale": "error"}


@pytest.mark.asyncio
async def test_worker_defers_live_non_head_job_without_holding_slot():
    state = _State()
    redis = _Redis(state)
    db = _DB()
    await register_run(redis, "scoped-thread", "stale")
    await register_run(redis, "scoped-thread", "current")
    stale_heartbeat = next(key for key in state.values if "stale" in key)
    state.values.pop(stale_heartbeat)
    state.queued_jobs.add("run:stale")

    with pytest.raises(Retry):
        await worker._wait_for_fifo_turn(
            db,
            redis,
            thread_id="public-thread",
            thread_key="scoped-thread",
            run_id="current",
            user_id="user-1",
        )

    assert await run_queue.get_run_head(redis, "scoped-thread") == "stale"
    assert worker.WorkerSettings.max_tries == 2_147_483_647


@pytest.mark.asyncio
async def test_inline_turn_prunes_predecessor_after_heartbeat_expires():
    state = _State()
    redis = _Redis(state)
    db = _DB()
    await register_run(redis, "scoped-thread", "stale")
    await register_run(redis, "scoped-thread", "current")
    stale_heartbeat = next(key for key in state.values if "stale" in key)
    state.values.pop(stale_heartbeat)

    async def prune():
        await arq_run_queue.prune_stale_heads(
            db,
            redis,
            thread_id="public-thread",
            thread_key="scoped-thread",
            run_id="current",
            user_id="user-1",
        )

    turn = RedisRunTurn(redis, "scoped-thread", "current")
    try:
        await asyncio.wait_for(turn.acquire(on_wait=prune), timeout=1)
        assert db.statuses == {"stale": "error"}
    finally:
        await turn.release()
