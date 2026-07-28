from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from agent.neon_grant_probe import (
    GrantBoundaryError,
    _exercise_guest_quarantine_dml,
    _expect_insufficient_privilege,
    _require_non_admin_role,
)


class _Transaction:
    def __init__(self) -> None:
        self.is_active = True
        self.rollback = AsyncMock(side_effect=self._rolled_back)

    def _rolled_back(self) -> None:
        self.is_active = False


class _ConnectionContext:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Engine:
    def __init__(self, connection) -> None:
        self.connection = connection

    def connect(self):
        return _ConnectionContext(self.connection)


class _BeginEngine(_Engine):
    def begin(self):
        return _ConnectionContext(self.connection)


class _OneResult:
    def __init__(self, row) -> None:
        self.row = row

    def one(self):
        return self.row


@pytest.mark.asyncio
async def test_runtime_grant_probe_exercises_quarantine_crud() -> None:
    now = datetime.now(UTC)

    async def execute(statement, parameters):
        sql = str(statement)
        key = (
            parameters["run_id"],
            parameters["thread_id"],
            parameters["identity"],
        )
        if "INSERT INTO" in sql or "DELETE FROM" in sql:
            return _OneResult(key)
        if "SELECT recovered_at" in sql:
            return _OneResult((None, now))
        if "UPDATE agent_guest" in sql:
            return _OneResult((now, now))
        raise AssertionError(f"unexpected quarantine probe SQL: {sql}")

    connection = SimpleNamespace(execute=AsyncMock(side_effect=execute))

    await _exercise_guest_quarantine_dml(_BeginEngine(connection))

    assert connection.execute.await_count == 4
    statements = [str(call.args[0]) for call in connection.execute.await_args_list]
    assert "INSERT INTO agent_guest_execution_quarantine" in statements[0]
    assert "SELECT recovered_at, drained_at" in statements[1]
    assert "UPDATE agent_guest_execution_quarantine" in statements[2]
    assert "DELETE FROM agent_guest_execution_quarantine" in statements[3]


@pytest.mark.asyncio
async def test_forbidden_statement_must_fail_with_insufficient_privilege() -> None:
    transaction = _Transaction()
    original = SimpleNamespace(sqlstate="42501")
    connection = SimpleNamespace(
        begin=AsyncMock(return_value=transaction),
        execute=AsyncMock(side_effect=OperationalError("probe", {}, original)),
    )

    await _expect_insufficient_privilege(_Engine(connection), "CREATE ROLE forbidden")

    transaction.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_forbidden_statement_success_is_rejected_and_rolled_back() -> None:
    transaction = _Transaction()
    connection = SimpleNamespace(
        begin=AsyncMock(return_value=transaction),
        execute=AsyncMock(return_value=None),
    )

    with pytest.raises(GrantBoundaryError, match="unexpectedly passed"):
        await _expect_insufficient_privilege(
            _Engine(connection),
            "CREATE SCHEMA forbidden",
        )

    transaction.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_denial_for_unexpected_database_error_fails_closed() -> None:
    transaction = _Transaction()
    original = SimpleNamespace(sqlstate="08006")
    connection = SimpleNamespace(
        begin=AsyncMock(return_value=transaction),
        execute=AsyncMock(side_effect=OperationalError("probe", {}, original)),
    )

    with pytest.raises(GrantBoundaryError, match="other than insufficient"):
        await _expect_insufficient_privilege(
            _Engine(connection), "CREATE ROLE forbidden"
        )


@pytest.mark.asyncio
async def test_runtime_role_must_have_no_database_admin_attributes() -> None:
    safe = {
        "rolsuper": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "rolreplication": False,
    }
    mappings = SimpleNamespace(one_or_none=lambda: safe)
    result = SimpleNamespace(mappings=lambda: mappings)
    connection = SimpleNamespace(execute=AsyncMock(return_value=result))

    await _require_non_admin_role(_Engine(connection))

    unsafe = dict(safe, rolcreaterole=True)
    mappings.one_or_none = lambda: unsafe
    with pytest.raises(GrantBoundaryError, match="administrative"):
        await _require_non_admin_role(_Engine(connection))
