"""PostgreSQL session fencing for Redis-off anonymous Aegra executions."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import logging
import textwrap
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from aegra_api.core.database import db_manager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from agent.identity import is_anonymous_identity

GUEST_RUN_MAX_ELAPSED_SECONDS = 45
STALE_GUEST_RUN_THRESHOLD_SECONDS = 15 * 60
MIN_STALE_TO_GUEST_BUDGET_MULTIPLIER = 10
OWNER_POLL_INTERVAL_SECONDS = 0.05

_LOCK_DOMAIN = b"syshin0116.dev/guest-run-liveness/v1\0"
_TRY_SESSION_LOCK_SQL = text("SELECT pg_try_advisory_lock(:lock_key)")
_UNLOCK_SESSION_SQL = text("SELECT pg_advisory_unlock(:lock_key)")
_EXECUTION_IS_ACTIVE_SQL = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN thread AS t
            ON t.thread_id = r.thread_id
            AND t.user_id = r.user_id
        WHERE
            r.run_id = :run_id
            AND r.thread_id = :thread_id
            AND r.user_id = :identity
            AND r.status IN ('pending', 'running')
            AND t.status = 'busy'
            AND t.user_id = :identity
    )
    """
)

logger = logging.getLogger(__name__)
_owner_monitors: set[asyncio.Task[None]] = set()


class GuestExecutionFenceUnavailableError(RuntimeError):
    """Another liveness owner fenced this exact guest execution."""


class GuestExecutionFenceRejectedError(RuntimeError):
    """The persisted run/thread no longer permits guest execution."""


class GuestExecutionFenceReleaseError(RuntimeError):
    """A session lock could not be proven released."""


def validate_guest_liveness_policy() -> None:
    """Fail closed when retention could race a bounded legitimate guest call."""
    if (
        STALE_GUEST_RUN_THRESHOLD_SECONDS
        < GUEST_RUN_MAX_ELAPSED_SECONDS * MIN_STALE_TO_GUEST_BUDGET_MULTIPLIER
    ):
        raise RuntimeError(
            "stale guest threshold must be a safe multiple of the run budget"
        )


def guest_execution_lock_key(
    *,
    run_id: str,
    thread_id: str,
    identity: str,
) -> int:
    """Derive one deterministic signed PostgreSQL bigint advisory-lock key."""
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required for guest execution fencing")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("thread_id is required for guest execution fencing")
    if not is_anonymous_identity(identity):
        raise ValueError("canonical guest identity is required for execution fencing")
    digest = hashlib.sha256()
    digest.update(_LOCK_DOMAIN)
    for value in (run_id, thread_id, identity):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return int.from_bytes(digest.digest()[:8], "big", signed=True)


def _execution_parameters(
    *,
    run_id: str,
    thread_id: str,
    identity: str,
) -> dict[str, object]:
    return {
        "identity": identity,
        "run_id": run_id,
        "thread_id": thread_id,
    }


async def _invalidate(connection: AsyncConnection) -> None:
    with suppress(BaseException):
        await connection.invalidate()


async def _close(connection: AsyncConnection) -> None:
    with suppress(BaseException):
        await connection.close()


async def _dispose(engine: AsyncEngine) -> None:
    with suppress(BaseException):
        await engine.dispose()


def _create_dedicated_fence_engine() -> AsyncEngine:
    """Build an unpooled physical-connection owner outside Aegra's ORM pool."""
    return create_async_engine(
        db_manager.get_engine().url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"prepared_statement_cache_size": 0},
    )


@dataclass(slots=True)
class GuestExecutionFence:
    """One dedicated physical connection that owns a session advisory lock."""

    engine: AsyncEngine
    connection: AsyncConnection
    lock_key: int
    run_id: str
    thread_id: str
    identity: str
    lock_held: bool = True
    _closed: bool = False
    _close_guard: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def execution_is_active(self) -> bool:
        result = await self.connection.execute(
            _EXECUTION_IS_ACTIVE_SQL,
            _execution_parameters(
                run_id=self.run_id,
                thread_id=self.thread_id,
                identity=self.identity,
            ),
        )
        active = result.scalar_one()
        if type(active) is not bool:
            raise RuntimeError("guest execution liveness query returned invalid data")
        await self.connection.commit()
        return active

    async def aclose(self) -> None:
        """Unlock or invalidate before disposing the dedicated connection."""
        async with self._close_guard:
            if self._closed:
                return
            self._closed = True
            if not self.lock_held:
                await _close(self.connection)
                await _dispose(self.engine)
                return

            try:
                result = await self.connection.execute(
                    _UNLOCK_SESSION_SQL,
                    {"lock_key": self.lock_key},
                )
                if result.scalar_one() is not True:
                    raise GuestExecutionFenceReleaseError(
                        "guest execution advisory lock was not held"
                    )
                self.lock_held = False
                await self.connection.commit()
            except BaseException:
                await _invalidate(self.connection)
                raise
            finally:
                await _close(self.connection)
                await _dispose(self.engine)

    def start_owner_monitor(self) -> asyncio.Task[None]:
        """Monitor the whole graph execution and its Aegra finalizer."""
        owner_task = asyncio.current_task()
        if owner_task is None:
            raise RuntimeError("guest execution fence requires an owning asyncio task")
        owner_done = asyncio.Event()
        owner_task.add_done_callback(lambda _task: owner_done.set())
        task = asyncio.create_task(
            _hold_for_owner_lifetime(
                self,
                owner_task=owner_task,
                owner_done=owner_done,
            ),
            name="guest-execution-owner-fence",
        )
        _owner_monitors.add(task)
        task.add_done_callback(_owner_monitor_done)
        return task


async def _await_cleanup(awaitable: Any) -> None:
    """Finish connection cleanup even if the owning task is cancelled again."""
    cleanup = asyncio.create_task(awaitable)
    cancellation: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:
            cancellation = error
    cleanup.result()
    if cancellation is not None:
        raise cancellation


async def _cancel_owner_then_close(
    fence: GuestExecutionFence,
    owner_task: asyncio.Task[Any],
    *,
    pending_operation: asyncio.Task[Any] | None,
) -> None:
    """Drain a live owner before voluntarily releasing its execution fence."""
    if not owner_task.done():
        owner_task.cancel()
        with suppress(BaseException):
            await owner_task
    if pending_operation is not None:
        pending_operation.cancel()
        with suppress(BaseException):
            await pending_operation
    await fence.aclose()


async def acquire_guest_execution_fence(
    *,
    run_id: str,
    thread_id: str,
    identity: str,
) -> GuestExecutionFence:
    """Acquire and revalidate one execution before any graph work can run."""
    lock_key = guest_execution_lock_key(
        run_id=run_id,
        thread_id=thread_id,
        identity=identity,
    )
    engine = _create_dedicated_fence_engine()
    try:
        connection = await engine.connect()
    except BaseException:
        await _dispose(engine)
        raise
    fence = GuestExecutionFence(
        engine=engine,
        connection=connection,
        lock_key=lock_key,
        run_id=run_id,
        thread_id=thread_id,
        identity=identity,
        lock_held=False,
    )
    active_error: BaseException | None = None
    try:
        result = await connection.execute(
            _TRY_SESSION_LOCK_SQL,
            {"lock_key": lock_key},
        )
        if result.scalar_one() is not True:
            raise GuestExecutionFenceUnavailableError(
                "guest execution liveness fence is already held"
            )
        fence.lock_held = True
        if not await fence.execution_is_active():
            raise GuestExecutionFenceRejectedError(
                "guest execution is no longer active"
            )
        return fence
    except BaseException as error:
        active_error = error
        raise
    finally:
        if active_error is not None:
            try:
                await _await_cleanup(fence.aclose())
            except BaseException:
                logger.exception(
                    "guest execution fence cleanup failed during acquisition"
                )


async def _hold_for_owner_lifetime(
    fence: GuestExecutionFence,
    *,
    owner_task: asyncio.Task[Any],
    owner_done: asyncio.Event,
) -> None:
    active_error: BaseException | None = None
    poll_task: asyncio.Task[bool] | None = None
    try:
        while not owner_task.done():
            poll_task = asyncio.create_task(fence.execution_is_active())
            execution_is_active = await asyncio.shield(poll_task)
            poll_task = None
            if not execution_is_active:
                break
            if owner_task.done():
                break
            try:
                async with asyncio.timeout(OWNER_POLL_INTERVAL_SECONDS):
                    await owner_done.wait()
            except TimeoutError:
                pass
    except BaseException as error:
        active_error = error
        raise
    finally:
        cleanup = (
            _cancel_owner_then_close(
                fence,
                owner_task,
                pending_operation=poll_task,
            )
            if active_error is not None
            else fence.aclose()
        )
        try:
            await _await_cleanup(cleanup)
        except BaseException:
            if active_error is None:
                raise
            logger.exception(
                "guest execution fence cleanup failed while preserving monitor error"
            )


def _owner_monitor_done(task: asyncio.Task[None]) -> None:
    _owner_monitors.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("guest execution owner fence monitor was cancelled")
    except BaseException:
        logger.exception("guest execution owner fence monitor failed")


async def wait_for_guest_execution_fence_monitors() -> None:
    """Wait for current monitor tasks; intended for deterministic shutdown/tests."""
    pending = tuple(_owner_monitors)
    if pending:
        await asyncio.gather(*pending)


def validate_guest_execution_fencing_factory(factory: Any) -> None:
    """Require the acquired fence's owner monitor before graph execution."""
    wrapped = inspect.unwrap(factory)
    if not inspect.isasyncgenfunction(wrapped):
        raise RuntimeError("guest execution graph factory must be an async context")
    tree = ast.parse(textwrap.dedent(inspect.getsource(wrapped)))

    def position(node: ast.AST) -> tuple[int, int]:
        return (node.lineno, node.col_offset)

    acquisitions: list[tuple[str, tuple[int, int]]] = []
    monitors: list[tuple[str, tuple[int, int]]] = []
    execution_boundaries = [
        position(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Yield, ast.YieldFrom))
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_graph"
        )
    ]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Await)
            and isinstance(node.value.value, ast.Call)
            and isinstance(node.value.value.func, ast.Name)
            and node.value.value.func.id == "acquire_guest_execution_fence"
        ):
            acquisitions.append((node.targets[0].id, position(node)))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start_owner_monitor"
            and isinstance(node.func.value, ast.Name)
        ):
            monitors.append((node.func.value.id, position(node)))

    first_execution = min(execution_boundaries, default=None)
    monitor_starts_before_execution = bool(
        first_execution is not None
        and any(
            acquired_name == monitored_name
            and acquired_position < monitored_position < first_execution
            for acquired_name, acquired_position in acquisitions
            for monitored_name, monitored_position in monitors
        )
    )
    if not monitor_starts_before_execution:
        raise RuntimeError(
            "guest execution graph factory must start its PostgreSQL owner "
            "monitor before yielding or compiling the graph"
        )


validate_guest_liveness_policy()

__all__ = [
    "GUEST_RUN_MAX_ELAPSED_SECONDS",
    "MIN_STALE_TO_GUEST_BUDGET_MULTIPLIER",
    "STALE_GUEST_RUN_THRESHOLD_SECONDS",
    "GuestExecutionFence",
    "GuestExecutionFenceRejectedError",
    "GuestExecutionFenceReleaseError",
    "GuestExecutionFenceUnavailableError",
    "acquire_guest_execution_fence",
    "guest_execution_lock_key",
    "validate_guest_execution_fencing_factory",
    "validate_guest_liveness_policy",
    "wait_for_guest_execution_fence_monitors",
]
