"""Actual-PostgreSQL proofs for guest recovery quarantine and liveness."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
from aegra_api.core import orm as aegra_orm
from aegra_api.core.database import db_manager
from aegra_api.settings import settings
from sqlalchemy import text
from starlette.responses import JSONResponse

from agent import maintenance as maintenance_module
from agent import run_liveness as run_liveness_module
from agent.auth import (
    AGENT_AUTH_SECRET,
    ANONYMOUS_PERMISSION,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
)
from agent.guest_thread_lock import guest_thread_lock_key
from agent.http import GuestRunGuard, NativeThreadGuard
from agent.maintenance import (
    GUEST_RETENTION_POLICY,
    MAX_GC_BATCH_SIZE,
    MAX_RECONCILE_BATCH_SIZE,
    collect_expired_guest_threads,
    reconcile_stale_guest_runs,
)
from agent.migrate import migrate_database
from agent.quarantine import mark_guest_execution_drained
from agent.run_liveness import (
    GUEST_EXECUTION_SLOT_LIMIT,
    GuestExecutionFence,
    GuestExecutionSlotUnavailableError,
    acquire_guest_execution_fence,
    guest_execution_lock_key,
)

POSTGRES_URL = os.environ.get("AEGRA_POSTGRES_TEST_URL")
_GUEST_SUBMIT_NONCE = "123e4567-e89b-42d3-a456-426614174000"

if os.environ.get("CI", "").lower() == "true" and not POSTGRES_URL:
    raise RuntimeError(
        "CI requires AEGRA_POSTGRES_TEST_URL; PostgreSQL integration may not skip"
    )

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="AEGRA_POSTGRES_TEST_URL is required for PostgreSQL integration",
)


@dataclass
class _PostgresCase:
    url: str
    thread_ids: list[str] = field(default_factory=list)

    def track(self, *thread_ids: str) -> None:
        self.thread_ids.extend(thread_ids)


@dataclass
class _RecordingCheckpointer:
    deleted_thread_ids: list[str] = field(default_factory=list)

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_thread_ids.append(thread_id)


async def _delete_test_threads(url: str, thread_ids: list[str]) -> None:
    async with await psycopg.AsyncConnection.connect(url) as connection:
        await connection.execute(
            """
            DELETE FROM agent_guest_execution_quarantine
            WHERE thread_id = ANY(%s)
            """,
            (thread_ids,),
        )
        await connection.execute(
            "DELETE FROM thread WHERE thread_id = ANY(%s)",
            (thread_ids,),
        )


@pytest.fixture
async def postgres_case():
    assert POSTGRES_URL is not None
    previous_url = settings.db.DATABASE_URL
    previous_manager_url = db_manager._database_url
    settings.db.DATABASE_URL = POSTGRES_URL
    db_manager._database_url = settings.db.database_url
    case = _PostgresCase(POSTGRES_URL)

    try:
        await migrate_database()
        await db_manager.initialize()
        yield case
    finally:
        if db_manager.engine is None:
            await db_manager.initialize()
        for thread_id in case.thread_ids:
            with suppress(BaseException):
                await db_manager.get_checkpointer().adelete_thread(thread_id)
        if case.thread_ids:
            async with await psycopg.AsyncConnection.connect(
                POSTGRES_URL
            ) as connection:
                await connection.execute(
                    """
                    DELETE FROM agent_guest_execution_quarantine
                    WHERE thread_id = ANY(%s)
                    """,
                    (case.thread_ids,),
                )
                await connection.execute(
                    "DELETE FROM thread WHERE thread_id = ANY(%s)",
                    (case.thread_ids,),
                )
        await db_manager.close()
        aegra_orm.async_session_maker = None
        settings.db.DATABASE_URL = previous_url
        db_manager._database_url = previous_manager_url


def _guest_authorization(subject: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "aud": TOKEN_AUDIENCE,
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "iss": TOKEN_ISSUER,
            "scope": ANONYMOUS_PERMISSION,
            "sub": subject,
        },
        AGENT_AUTH_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _run_start_command() -> dict[str, object]:
    metadata = {"syshin_ui_submit_nonce": _GUEST_SUBMIT_NONCE}
    return {
        "id": 1,
        "method": "run.start",
        "params": {
            "assistant_id": "agent",
            "config": {"metadata": metadata.copy()},
            "input": {
                "messages": [
                    {
                        "content": "quarantine boundary proof",
                        "id": "guest-message-1",
                        "role": "user",
                    }
                ]
            },
            "metadata": metadata,
        },
    }


def _retention(*, expired: bool) -> str:
    return json.dumps(
        {
            "graph_id": "agent",
            "guest_expires_at": (
                "2000-01-01T00:00:00Z" if expired else "2999-01-01T00:00:00Z"
            ),
            "guest_retention_policy": GUEST_RETENTION_POLICY,
        }
    )


async def test_hard_crash_quarantine_blocks_guest_and_gc_until_drain_proof(
    monkeypatch,
    postgres_case,
):
    monkeypatch.setenv("AGENT_ANONYMOUS_ACCESS_ENABLED", "true")
    unique = uuid4().hex
    run_id = f"hard-crash-run-{unique}"
    thread_id = f"hard-crash-thread-{unique}"
    identity = f"anon:{uuid4()}"
    postgres_case.track(thread_id)

    class Ledger:
        calls = 0

        async def reserve_run(self):
            self.calls += 1

    ledger = Ledger()
    downstream_calls = 0

    async def downstream(scope, receive, send):
        nonlocal downstream_calls
        downstream_calls += 1
        await receive()

        await JSONResponse(
            {
                "id": 1,
                "meta": {"applied_through_seq": 0},
                "result": {"run_id": "replacement"},
                "type": "success",
            }
        )(scope, receive, send)

    async with await psycopg.AsyncConnection.connect(postgres_case.url) as connection:
        await connection.execute(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id
            )
            VALUES (%s, 'idle', %s::jsonb, %s)
            """,
            (thread_id, _retention(expired=True), identity),
        )
        await connection.execute(
            """
            INSERT INTO agent_guest_execution_quarantine (
                run_id,
                thread_id,
                identity,
                recovered_at
            )
            VALUES (%s, %s, %s, '2000-01-01T00:00:00Z')
            """,
            (run_id, thread_id, identity),
        )

    guarded = NativeThreadGuard(
        GuestRunGuard(
            downstream,
            spend_ledger=ledger,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=guarded),
        base_url="http://test",
    ) as client:
        blocked = await client.post(
            f"/threads/{thread_id}/commands",
            headers=_guest_authorization(identity),
            json=_run_start_command(),
        )

        assert blocked.status_code == 409
        assert blocked.json()["message"] == (
            "The prior guest execution is still quarantined"
        )
        assert ledger.calls == 0
        assert downstream_calls == 0

        aged_sweep = await collect_expired_guest_threads(batch_size=1)
        assert aged_sweep.deleted_threads == 0

        blocked_again = await client.post(
            f"/threads/{thread_id}/commands",
            headers=_guest_authorization(identity),
            json=_run_start_command(),
        )
        assert blocked_again.status_code == 409
        assert ledger.calls == 0
        assert downstream_calls == 0

        await mark_guest_execution_drained(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        admitted = await client.post(
            f"/threads/{thread_id}/commands",
            headers=_guest_authorization(identity),
            json=_run_start_command(),
        )

    assert admitted.status_code == 200
    assert ledger.calls == 1
    assert downstream_calls == 1
    after_proof = await collect_expired_guest_threads(batch_size=1)
    assert after_proof.deleted_threads == 1


async def test_initial_gc_candidates_skip_unresolved_rows_without_starvation(
    postgres_case,
):
    unique = uuid4().hex
    blocked_thread = f"000-blocked-{unique}"
    eligible_thread = f"999-eligible-{unique}"
    blocked_identity = f"anon:{uuid4()}"
    eligible_identity = f"anon:{uuid4()}"
    postgres_case.track(blocked_thread, eligible_thread)

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.executemany(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id
            )
            VALUES (%s, 'idle', %s::jsonb, %s)
            """,
            [
                (
                    blocked_thread,
                    _retention(expired=True),
                    blocked_identity,
                ),
                (
                    eligible_thread,
                    _retention(expired=True),
                    eligible_identity,
                ),
            ],
        )
        await connection.execute(
            """
            INSERT INTO agent_guest_execution_quarantine (
                run_id,
                thread_id,
                identity,
                recovered_at
            )
            VALUES (%s, %s, %s, clock_timestamp())
            """,
            (f"blocked-run-{unique}", blocked_thread, blocked_identity),
        )

    result = await collect_expired_guest_threads(batch_size=1)
    assert result.deleted_threads == 1

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            "SELECT thread_id FROM thread WHERE thread_id = ANY(%s)",
            ([blocked_thread, eligible_thread],),
        )
        assert await cursor.fetchall() == [(blocked_thread,)]


async def test_locked_recovery_candidate_does_not_consume_batch_size_one(
    postgres_case,
):
    unique = uuid4().hex
    first_thread = f"locked-first-thread-{unique}"
    second_thread = f"locked-second-thread-{unique}"
    first_run = f"000-locked-run-{unique}"
    second_run = f"999-free-run-{unique}"
    first_identity = f"anon:{uuid4()}"
    second_identity = f"anon:{uuid4()}"
    postgres_case.track(first_thread, second_thread)
    stale = datetime.now(UTC) - timedelta(minutes=40)

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.executemany(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
            """,
            [
                (
                    first_thread,
                    _retention(expired=False),
                    first_identity,
                    stale,
                    stale,
                ),
                (
                    second_thread,
                    _retention(expired=False),
                    second_identity,
                    stale,
                    stale,
                ),
            ],
        )
        await cursor.executemany(
            """
            INSERT INTO runs (
                run_id,
                thread_id,
                status,
                user_id,
                created_at,
                updated_at,
                execution_params,
                claimed_by,
                lease_expires_at
            )
            VALUES (
                %s,
                %s,
                'running',
                %s,
                %s,
                %s,
                '{}'::jsonb,
                NULL,
                NULL
            )
            """,
            [
                (
                    first_run,
                    first_thread,
                    first_identity,
                    stale - timedelta(minutes=1),
                    stale - timedelta(minutes=1),
                ),
                (
                    second_run,
                    second_thread,
                    second_identity,
                    stale,
                    stale,
                ),
            ],
        )

    async with await psycopg.AsyncConnection.connect(
        postgres_case.url
    ) as locked_connection:
        await locked_connection.execute(
            """
            SELECT 1
            FROM thread AS t
            JOIN runs AS r ON r.thread_id = t.thread_id
            WHERE t.thread_id = %s AND r.run_id = %s
            FOR UPDATE OF t, r
            """,
            (first_thread, first_run),
        )
        first_sweep = await reconcile_stale_guest_runs(batch_size=1)
        assert first_sweep.reconciled_runs == 1
        assert first_sweep.released_threads == 1
        assert first_sweep.liveness_skipped_runs == 0

        async with (
            await psycopg.AsyncConnection.connect(postgres_case.url) as observation,
            observation.cursor() as cursor,
        ):
            await cursor.execute(
                """
                SELECT run_id, status
                FROM runs
                WHERE run_id = ANY(%s)
                ORDER BY run_id
                """,
                ([first_run, second_run],),
            )
            assert await cursor.fetchall() == [
                (first_run, "running"),
                (second_run, "error"),
            ]

    second_sweep = await reconcile_stale_guest_runs(batch_size=10)
    assert second_sweep.reconciled_runs == 1
    assert second_sweep.released_threads == 1


async def test_contended_liveness_candidate_does_not_consume_batch_size_one(
    postgres_case,
):
    unique = uuid4().hex
    first_thread = f"live-first-thread-{unique}"
    second_thread = f"live-second-thread-{unique}"
    first_run = f"000-live-run-{unique}"
    second_run = f"999-free-run-{unique}"
    first_identity = f"anon:{uuid4()}"
    second_identity = f"anon:{uuid4()}"
    postgres_case.track(first_thread, second_thread)
    stale = datetime.now(UTC) - timedelta(minutes=40)

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.executemany(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
            """,
            [
                (
                    first_thread,
                    _retention(expired=False),
                    first_identity,
                    stale,
                    stale,
                ),
                (
                    second_thread,
                    _retention(expired=False),
                    second_identity,
                    stale,
                    stale,
                ),
            ],
        )
        await cursor.executemany(
            """
            INSERT INTO runs (
                run_id,
                thread_id,
                status,
                user_id,
                created_at,
                updated_at,
                execution_params,
                claimed_by,
                lease_expires_at
            )
            VALUES (
                %s,
                %s,
                'running',
                %s,
                %s,
                %s,
                '{}'::jsonb,
                NULL,
                NULL
            )
            """,
            [
                (
                    first_run,
                    first_thread,
                    first_identity,
                    stale - timedelta(minutes=1),
                    stale - timedelta(minutes=1),
                ),
                (
                    second_run,
                    second_thread,
                    second_identity,
                    stale,
                    stale,
                ),
            ],
        )

    fence = await acquire_guest_execution_fence(
        run_id=first_run,
        thread_id=first_thread,
        identity=first_identity,
    )
    try:
        result = await reconcile_stale_guest_runs(batch_size=1)
    finally:
        await fence.aclose()

    assert result.reconciled_runs == 1
    assert result.released_threads == 1
    assert result.liveness_skipped_runs == 1
    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            """
            SELECT run_id, status
            FROM runs
            WHERE run_id = ANY(%s)
            ORDER BY run_id
            """,
            ([first_run, second_run],),
        )
        assert await cursor.fetchall() == [
            (first_run, "running"),
            (second_run, "error"),
        ]


async def test_contended_gc_candidate_does_not_consume_batch_size_one(
    postgres_case,
):
    unique = uuid4().hex
    first_thread = f"000-live-thread-{unique}"
    second_thread = f"999-free-thread-{unique}"
    first_identity = f"anon:{uuid4()}"
    second_identity = f"anon:{uuid4()}"
    postgres_case.track(first_thread, second_thread)

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.executemany(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id
            )
            VALUES (%s, 'idle', %s::jsonb, %s)
            """,
            [
                (first_thread, _retention(expired=True), first_identity),
                (second_thread, _retention(expired=True), second_identity),
            ],
        )

    async with await psycopg.AsyncConnection.connect(
        postgres_case.url
    ) as locked_connection:
        lock_key = guest_thread_lock_key(first_thread)
        await locked_connection.execute(
            "SELECT pg_advisory_lock(%s)",
            (lock_key,),
        )
        result = await collect_expired_guest_threads(batch_size=1)

        assert result.deleted_threads == 1
        async with (
            await psycopg.AsyncConnection.connect(postgres_case.url) as observation,
            observation.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT thread_id FROM thread WHERE thread_id = ANY(%s)",
                ([first_thread, second_thread],),
            )
            assert await cursor.fetchall() == [(first_thread,)]


async def test_max_recovery_batch_replaces_one_contended_head_candidate(
    postgres_case,
):
    unique = uuid4().hex
    identity = f"anon:{uuid4()}"
    head_run = f"000-head-run-{unique}"
    head_thread = f"000-head-thread-{unique}"
    successors = [
        (
            f"successor-run-{index:04d}-{unique}",
            f"successor-thread-{index:04d}-{unique}",
        )
        for index in range(MAX_RECONCILE_BATCH_SIZE)
    ]
    thread_ids = [head_thread, *(thread_id for _run_id, thread_id in successors)]
    stale = datetime.now(UTC) - timedelta(minutes=40)

    try:
        async with (
            await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.executemany(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
                """,
                [
                    (
                        thread_id,
                        _retention(expired=False),
                        identity,
                        stale,
                        stale,
                    )
                    for thread_id in thread_ids
                ],
            )
            await cursor.executemany(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    status,
                    user_id,
                    created_at,
                    updated_at,
                    execution_params,
                    claimed_by,
                    lease_expires_at
                )
                VALUES (
                    %s,
                    %s,
                    'running',
                    %s,
                    %s,
                    %s,
                    '{}'::jsonb,
                    NULL,
                    NULL
                )
                """,
                [
                    (
                        head_run,
                        head_thread,
                        identity,
                        stale - timedelta(minutes=1),
                        stale - timedelta(minutes=1),
                    ),
                    *[
                        (run_id, thread_id, identity, stale, stale)
                        for run_id, thread_id in successors
                    ],
                ],
            )

        async with await psycopg.AsyncConnection.connect(
            postgres_case.url
        ) as locked_connection:
            await locked_connection.execute(
                "SELECT pg_advisory_lock(%s)",
                (
                    guest_execution_lock_key(
                        run_id=head_run,
                        thread_id=head_thread,
                        identity=identity,
                    ),
                ),
            )

            result = await reconcile_stale_guest_runs(
                batch_size=MAX_RECONCILE_BATCH_SIZE
            )

            assert result.liveness_skipped_runs == 1
            assert result.reconciled_runs == MAX_RECONCILE_BATCH_SIZE
            assert result.released_threads == MAX_RECONCILE_BATCH_SIZE
            async with (
                await psycopg.AsyncConnection.connect(postgres_case.url) as observation,
                observation.cursor() as cursor,
            ):
                await cursor.execute(
                    """
                    SELECT status, count(*)
                    FROM runs
                    WHERE thread_id = ANY(%s)
                    GROUP BY status
                    ORDER BY status
                    """,
                    (thread_ids,),
                )
                assert await cursor.fetchall() == [
                    ("error", MAX_RECONCILE_BATCH_SIZE),
                    ("running", 1),
                ]
                await cursor.execute(
                    """
                    SELECT count(*)
                    FROM agent_guest_execution_quarantine
                    WHERE
                        thread_id = ANY(%s)
                        AND recovered_at IS NOT NULL
                        AND drained_at IS NULL
                    """,
                    (thread_ids,),
                )
                assert (await cursor.fetchone())[0] == MAX_RECONCILE_BATCH_SIZE
    finally:
        await _delete_test_threads(postgres_case.url, thread_ids)


async def test_max_gc_batch_replaces_one_contended_head_candidate(
    postgres_case,
):
    unique = uuid4().hex
    identity = f"anon:{uuid4()}"
    head_thread = f"000-head-gc-thread-{unique}"
    successor_threads = [
        f"successor-gc-thread-{index:04d}-{unique}"
        for index in range(MAX_GC_BATCH_SIZE)
    ]
    thread_ids = [head_thread, *successor_threads]
    checkpointer = _RecordingCheckpointer()
    head_retention = _retention(expired=True).replace(
        "2000-01-01T00:00:00Z",
        "1999-01-01T00:00:00Z",
    )

    try:
        async with (
            await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.executemany(
                """
                INSERT INTO thread (
                    thread_id,
                    status,
                    metadata_json,
                    user_id
                )
                VALUES (%s, 'idle', %s::jsonb, %s)
                """,
                [
                    (head_thread, head_retention, identity),
                    *[
                        (thread_id, _retention(expired=True), identity)
                        for thread_id in successor_threads
                    ],
                ],
            )

        async with await psycopg.AsyncConnection.connect(
            postgres_case.url
        ) as locked_connection:
            await locked_connection.execute(
                "SELECT pg_advisory_lock(%s)",
                (guest_thread_lock_key(head_thread),),
            )

            result = await collect_expired_guest_threads(
                batch_size=MAX_GC_BATCH_SIZE,
                checkpointer=checkpointer,
            )

            assert result.deleted_threads == MAX_GC_BATCH_SIZE
            assert len(checkpointer.deleted_thread_ids) == MAX_GC_BATCH_SIZE
            assert head_thread not in checkpointer.deleted_thread_ids
            async with (
                await psycopg.AsyncConnection.connect(postgres_case.url) as observation,
                observation.cursor() as cursor,
            ):
                await cursor.execute(
                    """
                    SELECT thread_id
                    FROM thread
                    WHERE thread_id = ANY(%s)
                    """,
                    (thread_ids,),
                )
                assert await cursor.fetchall() == [(head_thread,)]
    finally:
        await _delete_test_threads(postgres_case.url, thread_ids)


async def test_recovery_uses_statement_clock_and_preserves_prior_drain_proof(
    monkeypatch,
    postgres_case,
):
    unique = uuid4().hex
    run_id = f"proof-first-run-{unique}"
    thread_id = f"proof-first-thread-{unique}"
    identity = f"anon:{uuid4()}"
    postgres_case.track(thread_id)
    stale = datetime.now(UTC) - timedelta(minutes=40)

    async with await psycopg.AsyncConnection.connect(postgres_case.url) as connection:
        await connection.execute(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
            """,
            (
                thread_id,
                _retention(expired=False),
                identity,
                stale,
                stale,
            ),
        )
        await connection.execute(
            """
            INSERT INTO runs (
                run_id,
                thread_id,
                status,
                user_id,
                created_at,
                updated_at,
                execution_params,
                claimed_by,
                lease_expires_at
            )
            VALUES (
                %s,
                %s,
                'running',
                %s,
                %s,
                %s,
                '{}'::jsonb,
                NULL,
                NULL
            )
            """,
            (run_id, thread_id, identity, stale, stale),
        )

    await mark_guest_execution_drained(
        run_id=run_id,
        thread_id=thread_id,
        identity=identity,
    )

    original_sql = str(maintenance_module._UPSERT_RECOVERED_GUEST_QUARANTINES_SQL)
    delayed_sql = original_sql.replace(
        "    INSERT INTO agent_guest_execution_quarantine (",
        (
            "    WITH delayed AS MATERIALIZED (SELECT pg_sleep(1.0))\n"
            "    INSERT INTO agent_guest_execution_quarantine ("
        ),
        1,
    ).replace(
        "    ) AS recovered(run_id, thread_id, identity)\n    ON CONFLICT",
        (
            "    ) AS recovered(run_id, thread_id, identity)\n"
            "    CROSS JOIN delayed\n"
            "    ON CONFLICT"
        ),
        1,
    )
    assert delayed_sql != original_sql
    assert "CROSS JOIN delayed" in delayed_sql
    monkeypatch.setattr(
        maintenance_module,
        "_UPSERT_RECOVERED_GUEST_QUARANTINES_SQL",
        text(delayed_sql),
    )

    started = time.monotonic()
    recovered = await reconcile_stale_guest_runs(batch_size=1)
    elapsed = time.monotonic() - started
    assert recovered.reconciled_runs == 1
    assert elapsed >= 1.0

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            """
            SELECT
                recovered_at IS NOT NULL,
                drained_at IS NOT NULL,
                EXTRACT(
                    EPOCH FROM (clock_timestamp() - recovered_at)
                )
            FROM agent_guest_execution_quarantine
            WHERE
                run_id = %s
                AND thread_id = %s
                AND identity = %s
            """,
            (run_id, thread_id, identity),
        )
        recovered_present, drained_present, recovered_age = await cursor.fetchone()
        assert recovered_present is True
        assert drained_present is True
        assert float(recovered_age) < 0.5


async def test_postgres_session_slots_cap_cross_instance_guest_execution(
    postgres_case,
):
    unique = uuid4().hex
    stale = datetime.now(UTC) - timedelta(minutes=1)
    executions = [
        (
            f"slot-run-{index}-{unique}",
            f"slot-thread-{index}-{unique}",
            f"anon:{uuid4()}",
        )
        for index in range(GUEST_EXECUTION_SLOT_LIMIT + 1)
    ]
    postgres_case.track(*(thread_id for _run_id, thread_id, _identity in executions))

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.executemany(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
            """,
            [
                (
                    thread_id,
                    _retention(expired=False),
                    identity,
                    stale,
                    stale,
                )
                for _run_id, thread_id, identity in executions
            ],
        )
        await cursor.executemany(
            """
            INSERT INTO runs (
                run_id,
                thread_id,
                status,
                user_id,
                created_at,
                updated_at,
                claimed_by,
                lease_expires_at
            )
            VALUES (%s, %s, 'running', %s, %s, %s, NULL, NULL)
            """,
            [
                (run_id, thread_id, identity, stale, stale)
                for run_id, thread_id, identity in executions
            ],
        )

    fences: list[GuestExecutionFence] = []
    replacement: GuestExecutionFence | None = None
    try:
        fences = list(
            await asyncio.gather(
                *(
                    acquire_guest_execution_fence(
                        run_id=run_id,
                        thread_id=thread_id,
                        identity=identity,
                    )
                    for run_id, thread_id, identity in executions[
                        :GUEST_EXECUTION_SLOT_LIMIT
                    ]
                )
            )
        )
        backend_pids = []
        for fence in fences:
            result = await fence.connection.execute(text("SELECT pg_backend_pid()"))
            backend_pids.append(result.scalar_one())
            await fence.connection.commit()
        assert len(set(backend_pids)) == GUEST_EXECUTION_SLOT_LIMIT

        final_run, final_thread, final_identity = executions[-1]
        with pytest.raises(
            GuestExecutionSlotUnavailableError,
            match="at capacity",
        ):
            await acquire_guest_execution_fence(
                run_id=final_run,
                thread_id=final_thread,
                identity=final_identity,
            )

        await fences.pop(0).aclose()
        replacement = await acquire_guest_execution_fence(
            run_id=final_run,
            thread_id=final_thread,
            identity=final_identity,
        )
    finally:
        if replacement is not None:
            await replacement.aclose()
        for fence in fences:
            await fence.aclose()


async def test_owner_completion_cancels_actual_hung_postgres_poll_within_bound(
    monkeypatch,
    postgres_case,
):
    unique = uuid4().hex
    run_id = f"hung-poll-run-{unique}"
    thread_id = f"hung-poll-thread-{unique}"
    identity = f"anon:{uuid4()}"
    postgres_case.track(thread_id)
    stale = datetime.now(UTC) - timedelta(minutes=1)
    fence_ready = asyncio.get_running_loop().create_future()
    monitor_ready = asyncio.get_running_loop().create_future()
    start_monitor = asyncio.Event()
    finish_owner = asyncio.Event()

    async with await psycopg.AsyncConnection.connect(postgres_case.url) as connection:
        await connection.execute(
            """
            INSERT INTO thread (
                thread_id,
                status,
                metadata_json,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, 'busy', %s::jsonb, %s, %s, %s)
            """,
            (
                thread_id,
                _retention(expired=False),
                identity,
                stale,
                stale,
            ),
        )
        await connection.execute(
            """
            INSERT INTO runs (
                run_id,
                thread_id,
                status,
                user_id,
                created_at,
                updated_at,
                claimed_by,
                lease_expires_at
            )
            VALUES (%s, %s, 'running', %s, %s, %s, NULL, NULL)
            """,
            (run_id, thread_id, identity, stale, stale),
        )

    async def owner() -> None:
        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        backend_pid = (
            await fence.connection.execute(text("SELECT pg_backend_pid()"))
        ).scalar_one()
        await fence.connection.commit()
        fence_ready.set_result(backend_pid)
        await start_monitor.wait()
        monitor_ready.set_result(fence.start_owner_monitor())
        await finish_owner.wait()
        async with await psycopg.AsyncConnection.connect(
            postgres_case.url
        ) as connection:
            await connection.execute(
                """
                UPDATE runs
                SET status = 'success', updated_at = clock_timestamp()
                WHERE run_id = %s
                """,
                (run_id,),
            )
            await connection.execute(
                """
                UPDATE thread
                SET status = 'idle', updated_at = clock_timestamp()
                WHERE thread_id = %s
                """,
                (thread_id,),
            )

    owner_task = asyncio.create_task(owner())
    monitor: asyncio.Task[None] | None = None
    try:
        backend_pid = await fence_ready
        monkeypatch.setattr(
            run_liveness_module,
            "_EXECUTION_IS_ACTIVE_SQL",
            text(
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
                        AND pg_sleep(30) IS NULL
                )
                """
            ),
        )
        start_monitor.set()
        monitor = await monitor_ready

        observed_hung_query = False
        async with await psycopg.AsyncConnection.connect(
            postgres_case.url
        ) as observation:
            for _attempt in range(100):
                row = await observation.execute(
                    """
                    SELECT state, query
                    FROM pg_stat_activity
                    WHERE pid = %s
                    """,
                    (backend_pid,),
                )
                activity = await row.fetchone()
                if (
                    activity is not None
                    and activity[0] == "active"
                    and "pg_sleep(30)" in activity[1]
                ):
                    observed_hung_query = True
                    break
                await asyncio.sleep(0.02)
        assert observed_hung_query is True

        started = time.monotonic()
        finish_owner.set()
        async with asyncio.timeout(6):
            await owner_task
            await monitor
        assert time.monotonic() - started < 5
    finally:
        start_monitor.set()
        finish_owner.set()
        if not owner_task.done():
            owner_task.cancel()
        await asyncio.gather(owner_task, return_exceptions=True)
        if monitor is not None and not monitor.done():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

    async with (
        await psycopg.AsyncConnection.connect(postgres_case.url) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            """
            SELECT t.status, r.status, r.error_message
            FROM thread AS t
            JOIN runs AS r ON r.thread_id = t.thread_id
            WHERE t.thread_id = %s AND r.run_id = %s
            """,
            (thread_id, run_id),
        )
        assert await cursor.fetchone() == ("idle", "success", None)
