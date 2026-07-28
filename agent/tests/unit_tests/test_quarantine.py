"""Durable quarantine and drain-proof boundaries for guest executions."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.pool import NullPool

from agent import quarantine
from agent.quarantine import (
    guest_thread_has_unresolved_quarantine,
    mark_guest_execution_drained,
)

_IDENTITY = "anon:123e4567-e89b-42d3-a456-426614174000"
_RUN_ID = "run-quarantine-proof"
_THREAD_ID = "thread-quarantine-proof"


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _RowResult:
    def __init__(self, value):
        self.value = value

    def one(self):
        return self.value


class _ReadSession:
    def __init__(self, unresolved):
        self.unresolved = unresolved
        self.sql = None
        self.parameters = None

    async def execute(self, statement, parameters):
        self.sql = str(statement)
        self.parameters = parameters
        return _ScalarResult(self.unresolved)


class _ProofConnection:
    def __init__(self):
        self.sql = None
        self.parameters = None

    async def execute(self, statement, parameters):
        self.sql = str(statement)
        self.parameters = parameters
        return _RowResult((_RUN_ID, _THREAD_ID, _IDENTITY))


class _ProofEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def begin(self):
        return _AsyncContext(self.connection)

    async def dispose(self):
        self.disposed = True


async def test_unresolved_quarantine_read_uses_exact_execution_owner_boundary(
    monkeypatch,
):
    session = _ReadSession(True)
    monkeypatch.setattr(
        quarantine,
        "get_session_maker",
        lambda: lambda: _AsyncContext(session),
    )

    unresolved = await guest_thread_has_unresolved_quarantine(
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )

    assert unresolved is True
    assert session.parameters == {
        "identity": _IDENTITY,
        "thread_id": _THREAD_ID,
    }
    assert "recovered_at IS NOT NULL" in session.sql
    assert "drained_at IS NULL" in session.sql


async def test_drain_proof_uses_bounded_unpooled_connection_and_preserves_recovery(
    monkeypatch,
):
    connection = _ProofConnection()
    engine = _ProofEngine(connection)
    created = {}
    monkeypatch.setattr(
        quarantine.db_manager,
        "get_engine",
        lambda: SimpleNamespace(url="postgresql+asyncpg://db.example/agent"),
    )

    def create_engine(url, **kwargs):
        created["url"] = url
        created["kwargs"] = kwargs
        return engine

    monkeypatch.setattr(quarantine, "create_async_engine", create_engine)

    await mark_guest_execution_drained(
        run_id=_RUN_ID,
        thread_id=_THREAD_ID,
        identity=_IDENTITY,
    )

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
    assert connection.parameters == {
        "identity": _IDENTITY,
        "run_id": _RUN_ID,
        "thread_id": _THREAD_ID,
    }
    assert "drained_at = COALESCE" in connection.sql
    assert "recovered_at =" not in connection.sql.partition("DO UPDATE SET")[2]
    assert engine.disposed is True
