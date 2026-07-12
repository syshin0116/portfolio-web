"""Authorization boundaries for user-owned API resources."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from api.auth import create_agent_token
from api.resource_scope import scoped_checkpoint_thread_id

TEST_SECRET = "test-secret-that-is-at-least-thirty-two-bytes"
ALICE = "alice"
BOB = "bob"
THREAD_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
CRON_ID = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 7, 11, tzinfo=UTC)


def _thread_row() -> dict:
    return {
        "thread_id": THREAD_ID,
        "owner_id": ALICE,
        "created_at": NOW,
        "updated_at": NOW,
        "metadata": {"owner": "alice"},
        "status": "idle",
    }


def _run_row() -> dict:
    return {
        "run_id": RUN_ID,
        "thread_id": THREAD_ID,
        "assistant_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "status": "success",
        "metadata": {},
        "multitask_strategy": "reject",
    }


def _cron_row() -> dict:
    return {
        "cron_id": CRON_ID,
        "owner_id": ALICE,
        "assistant_id": None,
        "thread_id": THREAD_ID,
        "schedule": "0 0 * * *",
        "timezone": "UTC",
        "end_time": None,
        "created_at": NOW,
        "updated_at": NOW,
        "next_run_date": None,
        "metadata": {},
        "enabled": True,
    }


class _OwnedDB:
    def __init__(self):
        self.thread = _thread_row()
        self.run = _run_row()
        self.cron = _cron_row()
        self.store = {(ALICE, ("private",), "secret"): {"message": "alice"}}

    async def create_thread(self, *, thread_id=None, owner_id, **kwargs):
        if thread_id == THREAD_ID and owner_id != ALICE:
            return None
        raise AssertionError("unexpected thread creation")

    async def get_thread(self, thread_id, owner_id):
        if (
            self.thread
            and thread_id == THREAD_ID
            and owner_id == self.thread["owner_id"]
        ):
            return self.thread.copy()
        return None

    async def update_thread(self, thread_id, owner_id, **kwargs):
        if not await self.get_thread(thread_id, owner_id):
            return None
        self.thread["metadata"] = kwargs.get("metadata") or self.thread["metadata"]
        return self.thread.copy()

    async def delete_thread(self, thread_id, owner_id):
        if not await self.get_thread(thread_id, owner_id):
            return False
        self.thread = None
        return True

    async def search_threads(self, *, owner_id, **kwargs):
        if self.thread and owner_id == self.thread["owner_id"]:
            return [self.thread.copy()]
        return []

    async def get_run(self, thread_id, run_id, owner_id):
        if (
            self.run
            and thread_id == THREAD_ID
            and run_id == RUN_ID
            and owner_id == ALICE
        ):
            return self.run.copy()
        return None

    async def list_runs(self, thread_id, *, owner_id, **kwargs):
        if self.run and thread_id == THREAD_ID and owner_id == ALICE:
            return [self.run.copy()]
        return []

    async def delete_run(self, thread_id, run_id, owner_id):
        if not await self.get_run(thread_id, run_id, owner_id):
            return False
        self.run = None
        return True

    async def store_put(self, namespace, key, value, *, owner_id):
        self.store[(owner_id, tuple(namespace), key)] = value

    async def store_get(self, namespace, key, *, owner_id):
        value = self.store.get((owner_id, tuple(namespace), key))
        if value is None:
            return None
        return {
            "namespace": namespace,
            "key": key,
            "value": value,
            "created_at": NOW,
            "updated_at": NOW,
        }

    async def store_delete(self, namespace, key, *, owner_id):
        return self.store.pop((owner_id, tuple(namespace), key), None) is not None

    async def store_search(self, namespace_prefix, *, owner_id, **kwargs):
        items = []
        prefix = tuple(namespace_prefix)
        for (item_owner, namespace, key), value in self.store.items():
            if item_owner != owner_id or namespace[: len(prefix)] != prefix:
                continue
            items.append(
                {
                    "namespace": list(namespace),
                    "key": key,
                    "value": value,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            )
        return items

    async def store_list_namespaces(self, *, owner_id, **kwargs):
        return [
            list(namespace)
            for item_owner, namespace, _key in self.store
            if item_owner == owner_id
        ]

    async def create_cron(self, **kwargs):
        raise AssertionError("unexpected cron creation")

    async def update_cron(self, cron_id, owner_id, **kwargs):
        if not self.cron or cron_id != CRON_ID or owner_id != ALICE:
            return None
        self.cron.update(kwargs)
        return self.cron.copy()

    async def delete_cron(self, cron_id, owner_id):
        if not self.cron or cron_id != CRON_ID or owner_id != ALICE:
            return False
        self.cron = None
        return True

    async def search_crons(self, *, owner_id, **kwargs):
        return [self.cron.copy()] if self.cron and owner_id == ALICE else []


@pytest.fixture
def authorization_app(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_SECRET", TEST_SECRET)

    from api.main import app

    app.state.checkpointer = AsyncMock()
    app.state.db = _OwnedDB()
    app.state.graphs = {"agent": MagicMock()}
    app.state.run_manager = AsyncMock()
    return app


@asynccontextmanager
async def _client(app, subject: str):
    token = create_agent_token(subject, TEST_SECRET)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_user_cannot_access_another_users_thread(authorization_app):
    async with _client(authorization_app, BOB) as bob:
        assert (await bob.get(f"/threads/{THREAD_ID}")).status_code == 404
        assert (
            await bob.patch(f"/threads/{THREAD_ID}", json={"metadata": {"x": 1}})
        ).status_code == 404
        assert (await bob.delete(f"/threads/{THREAD_ID}")).status_code == 404
        assert (await bob.post("/threads/search", json={})).json() == []
        assert (await bob.get(f"/threads/{THREAD_ID}/state")).status_code == 404
        assert (
            await bob.post(f"/threads/{THREAD_ID}/state", json={"values": {"x": 1}})
        ).status_code == 404
        assert (await bob.post(f"/threads/{THREAD_ID}/history")).status_code == 404

    async with _client(authorization_app, ALICE) as alice:
        response = await alice.get(f"/threads/{THREAD_ID}")
        assert response.status_code == 200
        assert response.json()["metadata"] == {"owner": "alice"}


@pytest.mark.asyncio
async def test_thread_delete_removes_only_owner_scoped_checkpoint(authorization_app):
    async with _client(authorization_app, ALICE) as alice:
        response = await alice.delete(f"/threads/{THREAD_ID}")

    assert response.status_code == 200
    authorization_app.state.checkpointer.adelete_thread.assert_awaited_once_with(
        scoped_checkpoint_thread_id(ALICE, THREAD_ID)
    )
    assert authorization_app.state.db.thread is None


@pytest.mark.asyncio
async def test_recreated_thread_id_cannot_read_previous_owners_checkpoint(
    authorization_app,
):
    alice_checkpoint = scoped_checkpoint_thread_id(ALICE, THREAD_ID)
    bob_checkpoint = scoped_checkpoint_thread_id(BOB, THREAD_ID)
    authorization_app.state.db.thread = {
        **_thread_row(),
        "owner_id": BOB,
        "metadata": {"owner": "bob"},
    }

    async def get_state(config):
        if config["configurable"]["thread_id"] == alice_checkpoint:
            raise AssertionError("Bob accessed Alice's checkpoint identity")
        return None

    graph = authorization_app.state.graphs["agent"]
    graph.aget_state = AsyncMock(side_effect=get_state)

    async with _client(authorization_app, BOB) as bob:
        response = await bob.get(f"/threads/{THREAD_ID}/state")

    assert response.status_code == 200
    assert response.json()["thread_id"] == THREAD_ID
    assert response.json()["values"] == {}
    graph.aget_state.assert_awaited_once_with(
        {"configurable": {"thread_id": bob_checkpoint, "user_id": BOB}}
    )


@pytest.mark.asyncio
async def test_user_cannot_access_another_users_runs(authorization_app):
    run_manager = authorization_app.state.run_manager

    async with _client(authorization_app, BOB) as bob:
        assert (
            await bob.post(
                f"/threads/{THREAD_ID}/runs", json={"if_not_exists": "reject"}
            )
        ).status_code == 404
        assert (await bob.get(f"/threads/{THREAD_ID}/runs")).json() == []
        assert (await bob.get(f"/threads/{THREAD_ID}/runs/{RUN_ID}")).status_code == 404
        assert (
            await bob.get(f"/threads/{THREAD_ID}/runs/{RUN_ID}/stream")
        ).status_code == 404
        assert (
            await bob.post(f"/threads/{THREAD_ID}/runs/{RUN_ID}/cancel")
        ).status_code == 404
        assert (
            await bob.get(f"/threads/{THREAD_ID}/runs/{RUN_ID}/join")
        ).status_code == 404
        assert (
            await bob.delete(f"/threads/{THREAD_ID}/runs/{RUN_ID}")
        ).status_code == 404

    run_manager.create_run.assert_not_awaited()
    run_manager.cancel_run.assert_not_awaited()
    run_manager.join_run.assert_not_awaited()
    run_manager.join_stream.assert_not_called()

    async with _client(authorization_app, ALICE) as alice:
        assert (
            await alice.get(f"/threads/{THREAD_ID}/runs/{RUN_ID}")
        ).status_code == 200


@pytest.mark.asyncio
async def test_user_store_namespace_cannot_enumerate_or_mutate_another_user(
    authorization_app,
):
    async with _client(authorization_app, BOB) as bob:
        assert (
            await bob.get(
                "/store/items", params={"namespace": "private", "key": "secret"}
            )
        ).status_code == 404
        assert (
            await bob.post("/store/items/search", json={"namespace_prefix": []})
        ).json() == []
        assert (await bob.post("/store/namespaces", json={})).json() == {
            "namespaces": []
        }
        assert (
            await bob.put(
                "/store/items",
                json={
                    "namespace": ["private"],
                    "key": "secret",
                    "value": {"message": "bob"},
                },
            )
        ).status_code == 200
        assert (
            await bob.request(
                "DELETE",
                "/store/items",
                json={"namespace": ["private"], "key": "secret"},
            )
        ).status_code == 200

    async with _client(authorization_app, ALICE) as alice:
        response = await alice.get(
            "/store/items", params={"namespace": "private", "key": "secret"}
        )
        assert response.status_code == 200
        assert response.json()["value"] == {"message": "alice"}


@pytest.mark.asyncio
async def test_user_cannot_access_another_users_crons(authorization_app):
    async with _client(authorization_app, BOB) as bob:
        assert (
            await bob.post(
                f"/threads/{THREAD_ID}/runs/crons", json={"schedule": "0 0 * * *"}
            )
        ).status_code == 404
        assert (await bob.post("/runs/crons/search", json={})).json() == []
        assert (
            await bob.patch(f"/runs/crons/{CRON_ID}", json={"schedule": "1 0 * * *"})
        ).status_code == 404
        assert (await bob.delete(f"/runs/crons/{CRON_ID}")).status_code == 404

    async with _client(authorization_app, ALICE) as alice:
        response = await alice.post("/runs/crons/search", json={})
        assert response.status_code == 200
        assert [cron["cron_id"] for cron in response.json()] == [CRON_ID]
