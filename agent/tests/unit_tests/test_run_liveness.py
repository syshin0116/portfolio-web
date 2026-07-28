"""Fail-closed PostgreSQL fencing for anonymous graph execution."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import NullPool

from agent import run_liveness
from agent.graph import graph
from agent.run_liveness import (
    GuestExecutionFenceRejectedError,
    GuestExecutionFenceReleaseError,
    GuestExecutionFenceUnavailableError,
    GuestExecutionSlotUnavailableError,
    acquire_guest_execution_fence,
    guest_execution_lock_key,
    validate_guest_execution_fencing_factory,
    validate_guest_liveness_policy,
)

_IDENTITY = "anon:123e4567-e89b-42d3-a456-426614174000"
_RUN_ID = "run-liveness-proof"
_THREAD_ID = "thread-liveness-proof"


@pytest.fixture(autouse=True)
def _durable_drain_proof(monkeypatch):
    async def mark_drained(*, run_id, thread_id, identity):
        assert run_id == _RUN_ID
        assert thread_id == _THREAD_ID
        assert identity == _IDENTITY

    monkeypatch.setattr(
        run_liveness,
        "mark_guest_execution_drained",
        mark_drained,
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _Connection:
    def __init__(
        self,
        *,
        active_values=(True,),
        active_gate: asyncio.Event | None = None,
        lock_acquired=True,
        slot_values=(),
        unlock_result=True,
        unlock_error: BaseException | None = None,
    ):
        self.active_values = iter(active_values)
        self.active_gate = active_gate
        self.lock_acquired = lock_acquired
        self.slot_values = iter(slot_values)
        self.unlock_result = unlock_result
        self.unlock_error = unlock_error
        self.events = []
        self.parameters = []
        self.invalidated = False
        self.closed = False
        self.active_calls = 0
        self.monitor_active = asyncio.Event()
        self.active_cancelled = asyncio.Event()

    async def execute(self, statement, parameters):
        sql = str(statement)
        self.parameters.append(parameters)
        if "pg_advisory_unlock" in sql:
            self.events.append("unlock")
            if self.unlock_error is not None:
                raise self.unlock_error
            return _ScalarResult(self.unlock_result)
        if "pg_try_advisory_lock" in sql:
            self.events.append("try-lock")
            if parameters["lock_key"] in run_liveness._GUEST_EXECUTION_SLOT_KEYS:
                return _ScalarResult(next(self.slot_values, True))
            return _ScalarResult(self.lock_acquired)
        if "SELECT EXISTS" in sql:
            self.events.append("active")
            self.active_calls += 1
            if self.active_calls >= 2:
                self.monitor_active.set()
                if self.active_gate is not None:
                    try:
                        await self.active_gate.wait()
                    except asyncio.CancelledError:
                        self.active_cancelled.set()
                        raise
            value = next(self.active_values)
            if isinstance(value, BaseException):
                raise value
            return _ScalarResult(value)
        raise AssertionError(f"unexpected SQL: {sql}")

    async def commit(self):
        self.events.append("commit")

    async def invalidate(self):
        self.events.append("invalidate")
        self.invalidated = True

    async def close(self):
        self.events.append("close")
        self.closed = True


class _Engine:
    def __init__(self, connection, *, connect_error=None):
        self.connection = connection
        self.connect_error = connect_error
        self.connect_calls = 0
        self.disposed = False

    async def connect(self):
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        return self.connection

    async def dispose(self):
        self.disposed = True


def _install_engine(monkeypatch, connection, *, connect_error=None):
    shared_engine = SimpleNamespace(url="postgresql+asyncpg://db.example/agent")
    dedicated_engine = _Engine(connection, connect_error=connect_error)
    created = {}
    monkeypatch.setattr(
        run_liveness.db_manager,
        "get_engine",
        lambda: shared_engine,
    )

    def create_engine(url, **kwargs):
        created["url"] = url
        created["kwargs"] = kwargs
        return dedicated_engine

    monkeypatch.setattr(run_liveness, "create_async_engine", create_engine)
    return dedicated_engine, created


def test_liveness_policy_uses_literal_reviewed_boundaries():
    assert run_liveness.GUEST_RUN_MAX_ELAPSED_SECONDS == 45
    assert run_liveness.STALE_GUEST_RUN_THRESHOLD_SECONDS == 900
    assert run_liveness.MIN_STALE_TO_GUEST_BUDGET_MULTIPLIER == 10
    assert 900 >= 45 * 10


def test_execution_slots_and_heartbeat_have_static_global_bounds():
    assert run_liveness.GUEST_EXECUTION_SLOT_LIMIT == 4
    assert run_liveness.FENCE_CONNECT_ATTEMPT_LIMIT == 4
    assert run_liveness.OWNER_HEARTBEAT_MIN_SECONDS == 1.0
    assert run_liveness.OWNER_HEARTBEAT_MAX_SECONDS == 5.0
    assert run_liveness.MAX_GUEST_LIVENESS_QUERY_QPS == 4.0
    assert run_liveness.MAX_GUEST_FENCE_CONNECTIONS_PER_PROCESS == 8

    intervals = {
        run_liveness.guest_owner_heartbeat_seconds(lock_key)
        for lock_key in range(-32, 33)
    }
    assert min(intervals) >= 1.0
    assert max(intervals) <= 5.0
    assert len(intervals) > 1


def test_liveness_policy_rejects_an_unsafe_stale_multiplier(monkeypatch):
    monkeypatch.setattr(run_liveness, "STALE_GUEST_RUN_THRESHOLD_SECONDS", 449)

    with pytest.raises(RuntimeError, match="safe multiple"):
        validate_guest_liveness_policy()


def test_execution_lock_key_is_deterministic_signed_64_bit():
    first = guest_execution_lock_key(
        run_id=_RUN_ID,
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )
    second = guest_execution_lock_key(
        run_id=_RUN_ID,
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )

    assert first == second == 3503767190158055938
    assert -(2**63) <= first < 2**63
    assert first != guest_execution_lock_key(
        run_id=f"{_RUN_ID}-other",
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )


async def test_acquire_holds_a_separate_connection_after_exact_state_recheck(
    monkeypatch,
):
    connection = _Connection()
    engine, created = _install_engine(monkeypatch, connection)

    fence = await acquire_guest_execution_fence(
        run_id=_RUN_ID,
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )

    assert engine.connect_calls == 1
    assert created == {
        "url": "postgresql+asyncpg://db.example/agent",
        "kwargs": {
            "connect_args": {
                "command_timeout": 2.0,
                "prepared_statement_cache_size": 0,
                "timeout": 2.0,
            },
            "pool_pre_ping": True,
            "poolclass": NullPool,
        },
    }
    assert connection.events == [
        "try-lock",
        "active",
        "commit",
        "try-lock",
        "commit",
    ]
    assert connection.parameters[1] == {
        "identity": _IDENTITY,
        "run_id": _RUN_ID,
        "thread_id": _THREAD_ID,
    }
    assert not connection.closed

    await fence.aclose()

    assert connection.events[-4:] == ["unlock", "unlock", "commit", "close"]
    assert connection.closed
    assert engine.disposed


async def test_acquire_rejects_a_run_reconciled_before_graph_execution(monkeypatch):
    connection = _Connection(active_values=(False,))
    engine, _created = _install_engine(monkeypatch, connection)

    with pytest.raises(GuestExecutionFenceRejectedError, match="no longer active"):
        await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )

    assert connection.events == [
        "try-lock",
        "active",
        "commit",
        "unlock",
        "commit",
        "close",
    ]
    assert engine.disposed


async def test_dedicated_engine_is_disposed_when_physical_connect_fails(monkeypatch):
    connection = _Connection()
    engine, _created = _install_engine(
        monkeypatch,
        connection,
        connect_error=RuntimeError("physical connect failed"),
    )

    with pytest.raises(RuntimeError, match="physical connect failed"):
        await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )

    assert engine.connect_calls == 1
    assert engine.disposed
    assert connection.events == []


async def test_acquire_fails_closed_when_maintenance_owns_the_fence(monkeypatch):
    connection = _Connection(lock_acquired=False)
    engine, _created = _install_engine(monkeypatch, connection)

    with pytest.raises(GuestExecutionFenceUnavailableError, match="already held"):
        await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )

    assert connection.events == ["try-lock", "close"]
    assert engine.disposed


async def test_acquire_releases_execution_fence_when_all_global_slots_are_busy(
    monkeypatch,
):
    connection = _Connection(slot_values=(False, False, False, False))
    engine, _created = _install_engine(monkeypatch, connection)

    with pytest.raises(GuestExecutionSlotUnavailableError, match="at capacity"):
        await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )

    assert connection.events == [
        "try-lock",
        "active",
        "commit",
        "try-lock",
        "try-lock",
        "try-lock",
        "try-lock",
        "commit",
        "unlock",
        "commit",
        "close",
    ]
    assert connection.invalidated is False
    assert engine.disposed


async def test_unlock_failure_invalidates_before_pool_return(monkeypatch):
    connection = _Connection(unlock_result=False)
    engine, _created = _install_engine(monkeypatch, connection)
    fence = await acquire_guest_execution_fence(
        run_id=_RUN_ID,
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )

    with pytest.raises(GuestExecutionFenceReleaseError):
        await fence.aclose()

    assert connection.invalidated
    assert connection.closed
    assert connection.events[-3:] == ["unlock", "invalidate", "close"]
    assert engine.disposed


async def test_cancelled_owner_monitor_invalidates_after_drain_proof(
    monkeypatch,
):
    release_poll = asyncio.Event()
    connection = _Connection(
        active_values=(True, True),
        active_gate=release_poll,
        unlock_error=RuntimeError("connection lost before unlock"),
    )
    engine, _created = _install_engine(monkeypatch, connection)
    owner_cancelled = asyncio.Event()
    release_owner = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()

    async def owner():
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            owner_cancelled.set()
            await release_owner.wait()

    owner_task = asyncio.create_task(owner())
    monitor = await monitor_ready
    await connection.monitor_active.wait()
    monitor.cancel()

    await owner_cancelled.wait()
    assert not owner_task.done()
    assert "unlock" not in connection.events
    assert not connection.closed
    assert connection.active_cancelled.is_set()

    release_owner.set()
    await owner_task
    with pytest.raises(asyncio.CancelledError):
        await monitor

    assert connection.active_cancelled.is_set()
    assert connection.invalidated
    assert connection.closed
    assert connection.events[-2:] == ["invalidate", "close"]
    assert engine.disposed


async def test_lost_fence_session_cancels_and_drains_owner_before_cleanup(
    monkeypatch,
):
    connection = _Connection(
        active_values=(True, RuntimeError("fence session lost")),
        unlock_error=RuntimeError("dead connection"),
    )
    engine, _created = _install_engine(monkeypatch, connection)
    owner_cancelled = asyncio.Event()
    release_owner = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()
    proof_written = asyncio.Event()
    owner_task: asyncio.Task[None]

    async def mark_drained(*, run_id, thread_id, identity):
        assert (run_id, thread_id, identity) == (
            _RUN_ID,
            _THREAD_ID,
            _IDENTITY,
        )
        assert owner_task.done()
        connection.events.append("drain-proof")
        proof_written.set()

    monkeypatch.setattr(
        run_liveness,
        "mark_guest_execution_drained",
        mark_drained,
    )

    async def owner():
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            owner_cancelled.set()
            await release_owner.wait()

    owner_task = asyncio.create_task(owner())
    monitor = await monitor_ready
    await owner_cancelled.wait()

    assert not owner_task.done()
    assert not monitor.done()
    assert "unlock" not in connection.events
    assert not connection.closed

    release_owner.set()
    await owner_task
    with pytest.raises(RuntimeError, match="fence session lost"):
        await monitor

    assert proof_written.is_set()
    assert connection.events.index("drain-proof") < connection.events.index(
        "invalidate"
    )
    assert connection.invalidated
    assert connection.closed
    assert connection.events[-2:] == ["invalidate", "close"]
    assert engine.disposed


async def test_hung_poll_times_out_then_proves_owner_and_query_are_drained(
    monkeypatch,
):
    never_release_poll = asyncio.Event()
    connection = _Connection(
        active_values=(True, True),
        active_gate=never_release_poll,
    )
    engine, _created = _install_engine(monkeypatch, connection)
    monkeypatch.setattr(run_liveness, "FENCE_QUERY_TIMEOUT_SECONDS", 0.01)
    owner_cancelled = asyncio.Event()
    proof_written = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()
    owner_task: asyncio.Task[None]

    async def mark_drained(*, run_id, thread_id, identity):
        assert (run_id, thread_id, identity) == (
            _RUN_ID,
            _THREAD_ID,
            _IDENTITY,
        )
        assert owner_task.done()
        assert connection.active_cancelled.is_set()
        proof_written.set()

    monkeypatch.setattr(
        run_liveness,
        "mark_guest_execution_drained",
        mark_drained,
    )

    async def owner():
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            owner_cancelled.set()
            raise

    owner_task = asyncio.create_task(owner())
    monitor = await monitor_ready

    await asyncio.wait_for(owner_cancelled.wait(), timeout=1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(monitor, timeout=1)

    assert owner_task.cancelled()
    assert proof_written.is_set()
    assert connection.active_cancelled.is_set()
    assert connection.events[-2:] == ["invalidate", "close"]
    assert engine.disposed


async def test_owner_monitor_keeps_lock_while_owner_and_db_are_active(
    monkeypatch,
):
    connection = _Connection(active_values=(True, True))
    engine, _created = _install_engine(monkeypatch, connection)
    release_owner = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()

    async def owner():
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        await release_owner.wait()

    owner_task = asyncio.create_task(owner())
    monitor = await monitor_ready
    await connection.monitor_active.wait()

    assert not owner_task.done()
    assert not monitor.done()
    assert "unlock" not in connection.events

    release_owner.set()
    await owner_task
    await monitor

    assert connection.events[-4:] == ["unlock", "unlock", "commit", "close"]
    assert engine.disposed


async def test_owner_completion_cancels_and_drains_a_hung_liveness_poll(
    monkeypatch,
):
    never_release_poll = asyncio.Event()
    connection = _Connection(
        active_values=(True, True),
        active_gate=never_release_poll,
    )
    engine, _created = _install_engine(monkeypatch, connection)
    release_owner = asyncio.Event()
    monitor_ready = asyncio.get_running_loop().create_future()

    async def owner():
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        await release_owner.wait()

    owner_task = asyncio.create_task(owner())
    monitor = await monitor_ready
    await connection.monitor_active.wait()
    release_owner.set()

    await asyncio.wait_for(owner_task, timeout=1)
    await asyncio.wait_for(monitor, timeout=1)

    assert connection.active_cancelled.is_set()
    assert connection.invalidated is True
    assert connection.events[-2:] == ["invalidate", "close"]
    assert engine.disposed


async def test_owner_monitor_persists_proof_before_releasing_active_db_lock(
    monkeypatch,
):
    connection = _Connection(active_values=(True, True))
    engine, _created = _install_engine(monkeypatch, connection)
    monitor_ready = asyncio.get_running_loop().create_future()
    proof_written = asyncio.Event()
    owner_task: asyncio.Task[None]

    async def mark_drained(*, run_id, thread_id, identity):
        assert (run_id, thread_id, identity) == (
            _RUN_ID,
            _THREAD_ID,
            _IDENTITY,
        )
        assert owner_task.done()
        connection.events.append("drain-proof")
        proof_written.set()

    monkeypatch.setattr(
        run_liveness,
        "mark_guest_execution_drained",
        mark_drained,
    )

    async def failed_owner():
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        monitor_ready.set_result(fence.start_owner_monitor())
        raise RuntimeError("Aegra finalizer failed")

    owner_task = asyncio.create_task(failed_owner())
    monitor = await monitor_ready
    with pytest.raises(RuntimeError, match="finalizer failed"):
        await owner_task
    await monitor

    assert proof_written.is_set()
    assert connection.events[-5:] == [
        "drain-proof",
        "unlock",
        "unlock",
        "commit",
        "close",
    ]
    assert engine.disposed


def test_real_graph_factory_has_fail_closed_fencing_registration():
    validate_guest_execution_fencing_factory(graph)


def test_factory_registration_rejects_a_context_without_fencing():
    @asynccontextmanager
    async def unfenced_factory(_config, _runtime):
        yield SimpleNamespace()

    with pytest.raises(RuntimeError, match="start.*monitor before yielding"):
        validate_guest_execution_fencing_factory(unfenced_factory)


def test_factory_registration_rejects_monitor_start_after_graph_yield():
    @asynccontextmanager
    async def late_monitor_factory(_config, _runtime):
        fence = await acquire_guest_execution_fence(
            run_id=_RUN_ID,
            thread_id=_THREAD_ID,
            identity=_IDENTITY,
        )
        try:
            yield SimpleNamespace()
        finally:
            fence.start_owner_monitor()

    with pytest.raises(RuntimeError, match="start.*monitor before yielding"):
        validate_guest_execution_fencing_factory(late_monitor_factory)
