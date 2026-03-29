"""Integration tests for the API endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_app():
    from backend.main import app

    app.state.checkpointer = AsyncMock()
    app.state.db = AsyncMock()
    app.state.graphs = {"agent": MagicMock(name="ReAct Agent")}
    app.state.run_manager = AsyncMock()

    return app


@pytest.fixture
async def client(mock_app):
    async with AsyncClient(
        transport=ASGITransport(app=mock_app), base_url="http://test"
    ) as ac:
        yield ac


async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_info(client: AsyncClient):
    response = await client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert "agent" in data["graphs"]


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
