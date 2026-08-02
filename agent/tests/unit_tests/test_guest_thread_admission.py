"""Durable anonymous-thread admission contracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from agent import guest_thread_admission
from agent.guest_thread_admission import (
    GuestThreadAdmissionUnavailableError,
    GuestThreadCreateDecision,
    _guest_thread_create_decision,
    admit_guest_thread_creation,
)
from agent.identity import CANONICAL_ANONYMOUS_SUBJECT_PATTERN

_IDENTITY = f"anon:{UUID(int=1, version=4)}"


class _Result:
    def __init__(self, value, *, singular: bool) -> None:
        self.value = value
        self.singular = singular

    def one_or_none(self):
        assert self.singular
        return self.value

    def one(self):
        assert not self.singular
        return self.value


class _Connection:
    def __init__(self, *, owner: str | None, counts: tuple[int, int] = (0, 0)):
        self.results = [
            _Result(
                None if owner is None else SimpleNamespace(user_id=owner),
                singular=True,
            ),
            _Result(counts, singular=False),
        ]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


@pytest.mark.parametrize(
    ("owner", "counts", "expected"),
    [
        (_IDENTITY, (999, 999), GuestThreadCreateDecision.EXISTING_OWNED),
        ("someone-else", (0, 0), GuestThreadCreateDecision.FOREIGN),
        (None, (5, 255), GuestThreadCreateDecision.NEW),
        (None, (6, 1), GuestThreadCreateDecision.IDENTITY_LIMIT),
        (None, (1, 256), GuestThreadCreateDecision.GLOBAL_LIMIT),
    ],
    ids=[
        "existing-owned-idempotent-at-cap",
        "foreign-hidden",
        "new-below-both-caps",
        "identity-cap-six",
        "global-cap-256",
    ],
)
async def test_guest_thread_create_decision_enforces_exact_durable_caps(
    owner,
    counts,
    expected,
):
    connection = _Connection(owner=owner, counts=counts)

    decision = await _guest_thread_create_decision(
        connection,  # type: ignore[arg-type]
        thread_id="guest-thread",
        identity=_IDENTITY,
    )

    assert decision == expected
    assert len(connection.statements) == (1 if owner is not None else 2)


async def test_global_count_uses_the_exact_canonical_anonymous_regex():
    connection = _Connection(owner=None, counts=(0, 0))

    await _guest_thread_create_decision(
        connection,  # type: ignore[arg-type]
        thread_id="guest-thread",
        identity=_IDENTITY,
    )

    compiled = connection.statements[1].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert " ~ " in sql
    assert " LIKE " not in sql
    assert CANONICAL_ANONYMOUS_SUBJECT_PATTERN in compiled.params.values()


async def test_guest_thread_admission_holds_global_lock_through_caller_response(
    monkeypatch,
):
    timeline: list[str] = []
    connection = _Connection(owner=None, counts=(5, 255))

    @asynccontextmanager
    async def creation_lock(*, timeout_seconds):
        assert timeout_seconds == 5.0
        timeline.append("lock-enter")
        try:
            yield connection
        finally:
            timeline.append("lock-exit")

    monkeypatch.setattr(
        guest_thread_admission,
        "guest_thread_create_advisory_lock",
        creation_lock,
    )

    async with admit_guest_thread_creation(
        thread_id="guest-thread",
        identity=_IDENTITY,
    ) as decision:
        timeline.append("response-complete")
        assert decision == GuestThreadCreateDecision.NEW

    assert timeline == ["lock-enter", "response-complete", "lock-exit"]


async def test_guest_thread_admission_query_failure_fails_closed_and_releases_lock(
    monkeypatch,
):
    timeline: list[str] = []

    class BrokenConnection:
        async def execute(self, _statement):
            raise RuntimeError("private database detail")

    @asynccontextmanager
    async def creation_lock(*, timeout_seconds):
        assert timeout_seconds == 5.0
        timeline.append("lock-enter")
        try:
            yield BrokenConnection()
        finally:
            timeline.append("lock-exit")

    monkeypatch.setattr(
        guest_thread_admission,
        "guest_thread_create_advisory_lock",
        creation_lock,
    )

    with pytest.raises(GuestThreadAdmissionUnavailableError):
        async with admit_guest_thread_creation(
            thread_id="guest-thread",
            identity=_IDENTITY,
        ):
            raise AssertionError("a failed durable count must not admit")

    assert timeline == ["lock-enter", "lock-exit"]
