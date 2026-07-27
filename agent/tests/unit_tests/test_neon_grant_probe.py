from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from agent.neon_grant_probe import (
    GrantBoundaryError,
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
