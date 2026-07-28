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
from agent.quarantine import (
    DRAIN_PROOF_ATTEMPT_LIMIT,
    mark_guest_execution_drained,
)

GUEST_RUN_MAX_ELAPSED_SECONDS = 45
STALE_GUEST_RUN_THRESHOLD_SECONDS = 15 * 60
MIN_STALE_TO_GUEST_BUDGET_MULTIPLIER = 10
GUEST_EXECUTION_SLOT_LIMIT = 4
FENCE_CONNECT_ATTEMPT_LIMIT = 4
FENCE_CONNECT_QUEUE_TIMEOUT_SECONDS = 0.25
FENCE_CONNECT_TIMEOUT_SECONDS = 2.0
FENCE_QUERY_TIMEOUT_SECONDS = 2.0
OWNER_HEARTBEAT_MIN_SECONDS = 1.0
OWNER_HEARTBEAT_MAX_SECONDS = 5.0
OWNER_TERMINAL_GRACE_SECONDS = 0.25
OWNER_TASK_DRAIN_TIMEOUT_SECONDS = 5.0
PENDING_QUERY_DRAIN_TIMEOUT_SECONDS = 2.0
FENCE_CLEANUP_TIMEOUT_SECONDS = 2.0
MONITOR_CLEANUP_TIMEOUT_SECONDS = 20.0
MAX_GUEST_LIVENESS_QUERY_QPS = GUEST_EXECUTION_SLOT_LIMIT / OWNER_HEARTBEAT_MIN_SECONDS
MAX_GUEST_FENCE_CONNECTIONS_PER_PROCESS = (
    GUEST_EXECUTION_SLOT_LIMIT + FENCE_CONNECT_ATTEMPT_LIMIT
)
MAX_GUEST_EXTRA_CONNECTIONS_PER_PROCESS = (
    MAX_GUEST_FENCE_CONNECTIONS_PER_PROCESS + DRAIN_PROOF_ATTEMPT_LIMIT
)

_LOCK_DOMAIN = b"syshin0116.dev/guest-run-liveness/v1\0"
_SLOT_DOMAIN = b"syshin0116.dev/guest-execution-slot/v1\0"
_HEARTBEAT_DOMAIN = b"syshin0116.dev/guest-heartbeat/v1\0"
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
_fence_connect_attempts = asyncio.BoundedSemaphore(FENCE_CONNECT_ATTEMPT_LIMIT)


class GuestExecutionFenceUnavailableError(RuntimeError):
    """Another liveness owner fenced this exact guest execution."""


class GuestExecutionFenceRejectedError(RuntimeError):
    """The persisted run/thread no longer permits guest execution."""


class GuestExecutionFenceReleaseError(RuntimeError):
    """A session lock could not be proven released."""


class GuestExecutionSlotUnavailableError(RuntimeError):
    """Every cross-instance guest execution slot is already held."""


class GuestExecutionDrainError(RuntimeError):
    """The old owner could not be proven terminal within the monitor bound."""


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


def _slot_lock_key(slot: int) -> int:
    digest = hashlib.sha256(
        _SLOT_DOMAIN + slot.to_bytes(2, "big", signed=False)
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


_GUEST_EXECUTION_SLOT_KEYS = tuple(
    _slot_lock_key(slot) for slot in range(GUEST_EXECUTION_SLOT_LIMIT)
)


def _ordered_slot_keys(execution_lock_key: int) -> tuple[int, ...]:
    start = execution_lock_key % GUEST_EXECUTION_SLOT_LIMIT
    return _GUEST_EXECUTION_SLOT_KEYS[start:] + _GUEST_EXECUTION_SLOT_KEYS[:start]


def guest_owner_heartbeat_seconds(execution_lock_key: int) -> float:
    """Return stable 1-5 second jitter without process-local randomness."""
    if (
        not isinstance(execution_lock_key, int)
        or isinstance(execution_lock_key, bool)
        or not -(2**63) <= execution_lock_key < 2**63
    ):
        raise ValueError("execution lock key must be a signed PostgreSQL bigint")
    digest = hashlib.sha256(
        _HEARTBEAT_DOMAIN + execution_lock_key.to_bytes(8, "big", signed=True)
    ).digest()
    span_milliseconds = int(
        (OWNER_HEARTBEAT_MAX_SECONDS - OWNER_HEARTBEAT_MIN_SECONDS) * 1_000
    )
    offset = int.from_bytes(digest[:4], "big") % (span_milliseconds + 1)
    return OWNER_HEARTBEAT_MIN_SECONDS + offset / 1_000


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
        async with asyncio.timeout(FENCE_CLEANUP_TIMEOUT_SECONDS):
            await connection.invalidate()


async def _close(connection: AsyncConnection) -> None:
    with suppress(BaseException):
        async with asyncio.timeout(FENCE_CLEANUP_TIMEOUT_SECONDS):
            await connection.close()


async def _dispose(engine: AsyncEngine) -> None:
    with suppress(BaseException):
        async with asyncio.timeout(FENCE_CLEANUP_TIMEOUT_SECONDS):
            await engine.dispose()


def _create_dedicated_fence_engine() -> AsyncEngine:
    """Build an unpooled physical-connection owner outside Aegra's ORM pool."""
    return create_async_engine(
        db_manager.get_engine().url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={
            "command_timeout": FENCE_QUERY_TIMEOUT_SECONDS,
            "prepared_statement_cache_size": 0,
            "timeout": FENCE_CONNECT_TIMEOUT_SECONDS,
        },
    )


@dataclass(slots=True)
class GuestExecutionFence:
    """One dedicated physical connection that owns a session advisory lock."""

    engine: AsyncEngine
    connection: AsyncConnection
    lock_key: int
    slot_key: int
    run_id: str
    thread_id: str
    identity: str
    lock_held: bool = True
    slot_held: bool = True
    _closed: bool = False
    _close_guard: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def execution_is_active(self) -> bool:
        async with asyncio.timeout(FENCE_QUERY_TIMEOUT_SECONDS):
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
                raise RuntimeError(
                    "guest execution liveness query returned invalid data"
                )
            await self.connection.commit()
        return active

    async def aclose(self, *, force_invalidate: bool = False) -> None:
        """Unlock or invalidate before disposing the dedicated connection."""
        async with self._close_guard:
            if self._closed:
                return
            self._closed = True
            if force_invalidate:
                self.lock_held = False
                self.slot_held = False
                await _invalidate(self.connection)
                await _close(self.connection)
                await _dispose(self.engine)
                return
            if not self.lock_held and not self.slot_held:
                await _close(self.connection)
                await _dispose(self.engine)
                return

            try:
                async with asyncio.timeout(FENCE_QUERY_TIMEOUT_SECONDS):
                    if self.lock_held:
                        result = await self.connection.execute(
                            _UNLOCK_SESSION_SQL,
                            {"lock_key": self.lock_key},
                        )
                        if result.scalar_one() is not True:
                            raise GuestExecutionFenceReleaseError(
                                "guest execution advisory lock was not held"
                            )
                        self.lock_held = False
                    if self.slot_held:
                        result = await self.connection.execute(
                            _UNLOCK_SESSION_SQL,
                            {"lock_key": self.slot_key},
                        )
                        if result.scalar_one() is not True:
                            raise GuestExecutionFenceReleaseError(
                                "guest execution slot lock was not held"
                            )
                        self.slot_held = False
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


async def _await_cleanup(
    awaitable: Any,
    *,
    timeout_seconds: float = MONITOR_CLEANUP_TIMEOUT_SECONDS,
) -> None:
    """Finish cleanup through repeated cancellation, but never without a deadline."""
    cleanup = asyncio.create_task(awaitable)
    interrupted: asyncio.CancelledError | None = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while not cleanup.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            cleanup.cancel()
            raise TimeoutError("guest execution monitor cleanup exceeded its bound")
        try:
            async with asyncio.timeout(remaining):
                await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:
            interrupted = error
        except TimeoutError:
            cleanup.cancel()
            raise TimeoutError(
                "guest execution monitor cleanup exceeded its bound"
            ) from None
    cleanup.result()
    if interrupted is not None:
        raise interrupted


async def _cancel_and_drain_task(
    task: asyncio.Task[Any] | None,
    *,
    timeout_seconds: float,
) -> bool:
    if task is None:
        return True
    if not task.done():
        task.cancel()
    done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
    if task not in done:
        return False
    with suppress(BaseException):
        task.result()
    return True


async def _close_fence_bounded(
    fence: GuestExecutionFence,
    *,
    force_invalidate: bool,
) -> None:
    async with asyncio.timeout(FENCE_CLEANUP_TIMEOUT_SECONDS):
        await fence.aclose(force_invalidate=force_invalidate)


async def _persist_drain_proof(fence: GuestExecutionFence) -> None:
    await mark_guest_execution_drained(
        run_id=fence.run_id,
        thread_id=fence.thread_id,
        identity=fence.identity,
    )


async def _finish_abnormal_monitor(
    fence: GuestExecutionFence,
    *,
    owner_task: asyncio.Task[Any],
    pending_operation: asyncio.Task[Any] | None,
) -> None:
    """Cancel and fully drain both tasks before writing the durable proof."""
    pending_drained, owner_drained = await asyncio.gather(
        _cancel_and_drain_task(
            pending_operation,
            timeout_seconds=PENDING_QUERY_DRAIN_TIMEOUT_SECONDS,
        ),
        _cancel_and_drain_task(
            owner_task,
            timeout_seconds=OWNER_TASK_DRAIN_TIMEOUT_SECONDS,
        ),
    )
    if not pending_drained:
        await _close_fence_bounded(fence, force_invalidate=True)
        pending_drained = await _cancel_and_drain_task(
            pending_operation,
            timeout_seconds=PENDING_QUERY_DRAIN_TIMEOUT_SECONDS,
        )
    if not owner_drained:
        if not fence._closed:
            await _close_fence_bounded(fence, force_invalidate=True)
        owner_drained = await _cancel_and_drain_task(
            owner_task,
            timeout_seconds=OWNER_TASK_DRAIN_TIMEOUT_SECONDS,
        )
    if not pending_drained or not owner_drained:
        if not fence._closed:
            await _close_fence_bounded(fence, force_invalidate=True)
        raise GuestExecutionDrainError(
            "guest execution owner or database operation did not drain"
        )

    try:
        await _persist_drain_proof(fence)
    finally:
        if not fence._closed:
            # An abnormal monitor cannot prove that the transaction state on
            # its dedicated connection is reusable. Persist the drain proof
            # while any surviving locks are still held, then drop the physical
            # session so both locks are released without another query.
            await _close_fence_bounded(fence, force_invalidate=True)


async def _finish_normal_monitor(
    fence: GuestExecutionFence,
    *,
    pending_operation: asyncio.Task[Any] | None,
    needs_drain_proof: bool,
    force_invalidate_after_proof: bool,
) -> None:
    operation_was_pending = (
        pending_operation is not None and not pending_operation.done()
    )
    pending_drained = await _cancel_and_drain_task(
        pending_operation,
        timeout_seconds=PENDING_QUERY_DRAIN_TIMEOUT_SECONDS,
    )
    if not pending_drained:
        await _close_fence_bounded(fence, force_invalidate=True)
        pending_drained = await _cancel_and_drain_task(
            pending_operation,
            timeout_seconds=PENDING_QUERY_DRAIN_TIMEOUT_SECONDS,
        )
        needs_drain_proof = True
    if not pending_drained:
        raise GuestExecutionDrainError(
            "guest execution database operation did not drain"
        )
    force_invalidate_after_proof = force_invalidate_after_proof or operation_was_pending
    try:
        if needs_drain_proof:
            await _persist_drain_proof(fence)
    finally:
        if not fence._closed:
            await _close_fence_bounded(
                fence,
                force_invalidate=force_invalidate_after_proof,
            )


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
    permit_acquired = False
    try:
        async with asyncio.timeout(FENCE_CONNECT_QUEUE_TIMEOUT_SECONDS):
            await _fence_connect_attempts.acquire()
        permit_acquired = True
    except TimeoutError as error:
        raise GuestExecutionSlotUnavailableError(
            "guest execution connection attempts are at capacity"
        ) from error

    engine: AsyncEngine | None = None
    fence: GuestExecutionFence | None = None
    active_error: BaseException | None = None
    try:
        engine = _create_dedicated_fence_engine()
        try:
            async with asyncio.timeout(FENCE_CONNECT_TIMEOUT_SECONDS):
                connection = await engine.connect()
        except BaseException:
            await _dispose(engine)
            raise
        fence = GuestExecutionFence(
            engine=engine,
            connection=connection,
            lock_key=lock_key,
            slot_key=_GUEST_EXECUTION_SLOT_KEYS[0],
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
            lock_held=False,
            slot_held=False,
        )
        try:
            async with asyncio.timeout(FENCE_QUERY_TIMEOUT_SECONDS):
                result = await connection.execute(
                    _TRY_SESSION_LOCK_SQL,
                    {"lock_key": lock_key},
                )
                acquired = result.scalar_one()
            if acquired is not True:
                if acquired is not False:
                    raise RuntimeError(
                        "guest execution advisory lock returned invalid data"
                    )
                raise GuestExecutionFenceUnavailableError(
                    "guest execution liveness fence is already held"
                )
            fence.lock_held = True
            if not await fence.execution_is_active():
                raise GuestExecutionFenceRejectedError(
                    "guest execution is no longer active"
                )

            async with asyncio.timeout(FENCE_QUERY_TIMEOUT_SECONDS):
                for slot_key in _ordered_slot_keys(lock_key):
                    result = await connection.execute(
                        _TRY_SESSION_LOCK_SQL,
                        {"lock_key": slot_key},
                    )
                    slot_acquired = result.scalar_one()
                    if slot_acquired is True:
                        fence.slot_key = slot_key
                        fence.slot_held = True
                        break
                    if slot_acquired is not False:
                        raise RuntimeError(
                            "guest execution slot lock returned invalid data"
                        )
                await connection.commit()
            if not fence.slot_held:
                raise GuestExecutionSlotUnavailableError(
                    "guest execution slots are at capacity"
                )
            return fence
        except BaseException as error:
            active_error = error
            raise
        finally:
            if active_error is not None:
                try:
                    await _await_cleanup(
                        fence.aclose(),
                        timeout_seconds=FENCE_CLEANUP_TIMEOUT_SECONDS * 2,
                    )
                except BaseException:
                    logger.exception(
                        "guest execution fence cleanup failed during acquisition"
                    )
    finally:
        if permit_acquired:
            _fence_connect_attempts.release()


async def _hold_for_owner_lifetime(
    fence: GuestExecutionFence,
    *,
    owner_task: asyncio.Task[Any],
    owner_done: asyncio.Event,
) -> None:
    active_error: BaseException | None = None
    poll_task: asyncio.Task[bool] | None = None
    owner_wait_task = asyncio.create_task(owner_done.wait())
    needs_drain_proof = False
    force_invalidate_after_proof = False
    try:
        while True:
            if owner_task.done():
                break
            poll_task = asyncio.create_task(fence.execution_is_active())
            done, _pending = await asyncio.wait(
                {owner_wait_task, poll_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if owner_wait_task in done:
                if poll_task.done():
                    try:
                        needs_drain_proof = poll_task.result() is not True
                    except BaseException:
                        needs_drain_proof = True
                        force_invalidate_after_proof = True
                break

            execution_is_active = poll_task.result()
            poll_task = None
            if not execution_is_active:
                try:
                    async with asyncio.timeout(OWNER_TERMINAL_GRACE_SECONDS):
                        await owner_done.wait()
                except TimeoutError:
                    raise GuestExecutionFenceRejectedError(
                        "guest execution became inactive before its owner drained"
                    ) from None
                needs_drain_proof = True
                break
            try:
                async with asyncio.timeout(
                    guest_owner_heartbeat_seconds(fence.lock_key)
                ):
                    await owner_done.wait()
            except TimeoutError:
                pass
    except BaseException as error:
        active_error = error
        raise
    finally:
        owner_wait_task.cancel()
        with suppress(BaseException):
            await owner_wait_task
        cleanup = (
            _finish_abnormal_monitor(
                fence,
                owner_task=owner_task,
                pending_operation=poll_task,
            )
            if active_error is not None
            else _finish_normal_monitor(
                fence,
                pending_operation=poll_task,
                needs_drain_proof=needs_drain_proof,
                force_invalidate_after_proof=force_invalidate_after_proof,
            )
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
    "FENCE_CONNECT_ATTEMPT_LIMIT",
    "FENCE_CONNECT_TIMEOUT_SECONDS",
    "FENCE_QUERY_TIMEOUT_SECONDS",
    "GUEST_EXECUTION_SLOT_LIMIT",
    "GUEST_RUN_MAX_ELAPSED_SECONDS",
    "MAX_GUEST_EXTRA_CONNECTIONS_PER_PROCESS",
    "MAX_GUEST_FENCE_CONNECTIONS_PER_PROCESS",
    "MAX_GUEST_LIVENESS_QUERY_QPS",
    "MIN_STALE_TO_GUEST_BUDGET_MULTIPLIER",
    "OWNER_HEARTBEAT_MAX_SECONDS",
    "OWNER_HEARTBEAT_MIN_SECONDS",
    "STALE_GUEST_RUN_THRESHOLD_SECONDS",
    "GuestExecutionDrainError",
    "GuestExecutionFence",
    "GuestExecutionFenceRejectedError",
    "GuestExecutionFenceReleaseError",
    "GuestExecutionFenceUnavailableError",
    "GuestExecutionSlotUnavailableError",
    "acquire_guest_execution_fence",
    "guest_execution_lock_key",
    "guest_owner_heartbeat_seconds",
    "validate_guest_execution_fencing_factory",
    "validate_guest_liveness_policy",
    "wait_for_guest_execution_fence_monitors",
]
