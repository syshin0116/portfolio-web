"""Integration tests for the API endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from api.auth import create_agent_token

TEST_SECRET = "test-secret-that-is-at-least-thirty-two-bytes"


@pytest.fixture
def mock_app(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_SECRET", TEST_SECRET)

    from api.main import app

    app.state.checkpointer = AsyncMock()
    app.state.db = AsyncMock()
    app.state.graphs = {"agent": MagicMock(name="ReAct Agent")}
    app.state.run_manager = AsyncMock()

    return app


@pytest.fixture
async def client(mock_app):
    token = create_agent_token("test-user", TEST_SECRET, scopes=["admin"])
    async with AsyncClient(
        transport=ASGITransport(app=mock_app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


async def test_health(client: AsyncClient):
    response = await client.get("/ok")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_info(client: AsyncClient):
    response = await client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert "agent" in data["graphs"]


async def test_health_is_public_without_token(mock_app):
    async with AsyncClient(
        transport=ASGITransport(app=mock_app), base_url="http://test"
    ) as anonymous:
        response = await anonymous.get("/ok")
    assert response.status_code == 200


async def test_protected_route_requires_token(mock_app):
    async with AsyncClient(
        transport=ASGITransport(app=mock_app), base_url="http://test"
    ) as anonymous:
        response = await anonymous.get("/threads/test-id")
    assert response.status_code == 401


async def test_stream_rejoin_cors_preflight_allows_sdk_headers(mock_app):
    async with AsyncClient(
        transport=ASGITransport(app=mock_app), base_url="http://test"
    ) as browser:
        response = await browser.options(
            "/threads/test-id/runs/run-id/stream",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,last-event-id",
            },
        )

    assert response.status_code == 200
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "last-event-id" in allowed_headers


async def test_create_thread(client: AsyncClient, mock_app):
    mock_app.state.db.create_thread.return_value = {
        "thread_id": "test-id",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "metadata": {},
        "status": "idle",
    }
    response = await client.post("/threads", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


async def test_create_assistant(client: AsyncClient, mock_app):
    mock_app.state.db.create_assistant.return_value = {
        "assistant_id": "test-id",
        "graph_id": "agent",
        "config": {},
        "context": {},
        "metadata": {},
        "name": "Test",
        "description": None,
        "version": 1,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    response = await client.post(
        "/assistants", json={"graph_id": "agent", "name": "Test"}
    )
    assert response.status_code == 200
    assert response.json()["graph_id"] == "agent"


async def test_shared_configuration_mutations_require_admin(mock_app):
    token = create_agent_token("regular-user", TEST_SECRET)
    async with AsyncClient(
        transport=ASGITransport(app=mock_app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as regular_user:
        responses = [
            await regular_user.post(
                "/assistants", json={"graph_id": "agent", "name": "Forbidden"}
            ),
            await regular_user.patch("/assistants/shared", json={"name": "Forbidden"}),
            await regular_user.delete("/assistants/shared"),
            await regular_user.post(
                "/models",
                json={
                    "provider": "openai",
                    "model_id": "openai/test",
                    "display_name": "Forbidden",
                },
            ),
            await regular_user.patch(
                "/models/shared", json={"display_name": "Forbidden"}
            ),
            await regular_user.delete("/models/shared"),
        ]

    assert {response.status_code for response in responses} == {403}
    mock_app.state.db.create_assistant.assert_not_awaited()
    mock_app.state.db.update_assistant.assert_not_awaited()
    mock_app.state.db.delete_assistant.assert_not_awaited()
    mock_app.state.db.create_model.assert_not_awaited()
    mock_app.state.db.update_model.assert_not_awaited()
    mock_app.state.db.delete_model.assert_not_awaited()
