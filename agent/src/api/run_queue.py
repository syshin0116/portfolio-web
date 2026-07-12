"""Redis-backed FIFO serialization for runs that share a thread."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.exceptions import LockError, RedisError

logger = logging.getLogger(__name__)

_QUEUE_KEY = "thread:{{{thread_id}}}:run-queue"
_LOCK_KEY = "thread:{{{thread_id}}}:run-lock"
_HEARTBEAT_KEY = "thread:{{{thread_id}}}:run:{run_id}:queue-heartbeat"
_LOCK_TTL_SECONDS = 30
_LOCK_RENEW_SECONDS = 10
_HEARTBEAT_TTL_SECONDS = 30
_HEARTBEAT_RENEW_SECONDS = 10
_LOCK_WAIT_SECONDS = 1
_QUEUE_POLL_SECONDS = 0.05
_STALE_CHECK_SECONDS = 1

_REGISTER_RUN_SCRIPT = """
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
return 1
"""

_REMOVE_RUN_SCRIPT = """
if redis.call('LINDEX', KEYS[1], 0) == ARGV[1] then
    redis.call('LPOP', KEYS[1])
else
    redis.call('LREM', KEYS[1], 1, ARGV[1])
end
redis.call('DEL', KEYS[2])
return 1
"""


def _queue_key(thread_id: str) -> str:
    return _QUEUE_KEY.format(thread_id=thread_id)


def _lock_key(thread_id: str) -> str:
    return _LOCK_KEY.format(thread_id=thread_id)


def _heartbeat_key(thread_id: str, run_id: str) -> str:
    return _HEARTBEAT_KEY.format(thread_id=thread_id, run_id=run_id)


async def register_run(redis: Any, thread_id: str, run_id: str) -> None:
    """Append a run to its thread's execution queue."""
    await redis.eval(
        _REGISTER_RUN_SCRIPT,
        2,
        _queue_key(thread_id),
        _heartbeat_key(thread_id, run_id),
        run_id,
        _HEARTBEAT_TTL_SECONDS,
    )


async def unregister_run(redis: Any, thread_id: str, run_id: str) -> None:
    """Remove a run that will not be executed."""
    await redis.eval(
        _REMOVE_RUN_SCRIPT,
        2,
        _queue_key(thread_id),
        _heartbeat_key(thread_id, run_id),
        run_id,
    )


async def is_run_head(redis: Any, thread_id: str, run_id: str) -> bool:
    """Return whether a run currently owns the next FIFO queue position."""
    return await redis.lindex(_queue_key(thread_id), 0) == run_id


async def get_run_head(redis: Any, thread_id: str) -> str | None:
    """Return the run at the front of a thread queue."""
    return await redis.lindex(_queue_key(thread_id), 0)


async def has_run_heartbeat(redis: Any, thread_id: str, run_id: str) -> bool:
    """Return whether the run's registering or executing process is alive."""
    return bool(await redis.exists(_heartbeat_key(thread_id, run_id)))


class RedisRunTurn:
    """Acquire a renewable distributed lock in Redis FIFO queue order."""

    def __init__(self, redis: Any, thread_id: str, run_id: str):
        self.redis = redis
        self.thread_id = thread_id
        self.run_id = run_id
        self._lock: Any | None = None
        self._renew_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def acquire(
        self, on_wait: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        """Wait until this run is queue head, then acquire the thread lease."""
        queue_key = _queue_key(self.thread_id)
        owner = asyncio.current_task()
        self._heartbeat_task = asyncio.create_task(self._heartbeat(owner))
        loop = asyncio.get_running_loop()
        next_stale_check = 0.0

        while True:
            if await self.redis.lindex(queue_key, 0) != self.run_id:
                now = loop.time()
                if on_wait and now >= next_stale_check:
                    await on_wait()
                    next_stale_check = now + _STALE_CHECK_SECONDS
                await asyncio.sleep(_QUEUE_POLL_SECONDS)
                continue

            lock = self.redis.lock(
                _lock_key(self.thread_id),
                timeout=_LOCK_TTL_SECONDS,
                blocking_timeout=_LOCK_WAIT_SECONDS,
            )
            if not await lock.acquire():
                await asyncio.sleep(_QUEUE_POLL_SECONDS)
                continue

            self._lock = lock
            if await self.redis.lindex(queue_key, 0) == self.run_id:
                self._renew_task = asyncio.create_task(self._renew(owner))
                return

            await self._release_lock()

    async def release(self) -> None:
        """Advance the queue and release the distributed lease."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        if self._renew_task:
            self._renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renew_task
            self._renew_task = None

        try:
            await self.redis.eval(
                _REMOVE_RUN_SCRIPT,
                2,
                _queue_key(self.thread_id),
                _heartbeat_key(self.thread_id, self.run_id),
                self.run_id,
            )
        finally:
            await self._release_lock()

    async def _renew(self, owner: asyncio.Task[Any] | None) -> None:
        try:
            while True:
                await asyncio.sleep(_LOCK_RENEW_SECONDS)
                await self._lock.extend(
                    _LOCK_TTL_SECONDS,
                    replace_ttl=True,
                )
        except asyncio.CancelledError:
            raise
        except (LockError, RedisError):
            logger.exception(
                "Lost Redis run lock for thread %s and run %s",
                self.thread_id,
                self.run_id,
            )
            if owner:
                owner.cancel()

    async def _heartbeat(self, owner: asyncio.Task[Any] | None) -> None:
        try:
            while True:
                await self.redis.set(
                    _heartbeat_key(self.thread_id, self.run_id),
                    "1",
                    ex=_HEARTBEAT_TTL_SECONDS,
                )
                await asyncio.sleep(_HEARTBEAT_RENEW_SECONDS)
        except asyncio.CancelledError:
            raise
        except RedisError:
            logger.exception("Lost Redis queue heartbeat for run %s", self.run_id)
            if owner:
                owner.cancel()

    async def _release_lock(self) -> None:
        if not self._lock:
            return
        lock, self._lock = self._lock, None
        with contextlib.suppress(LockError, RedisError):
            await lock.release()
