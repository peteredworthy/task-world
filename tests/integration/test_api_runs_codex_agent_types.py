"""Integration tests for the codex_server agent type."""

from pathlib import Path

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def _create_run_with_agent(
    client: AsyncClient, agent_type: str, agent_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Helper: create a run with the given agent type and return the response data."""
    body: dict[str, Any] = {
        "routine_id": "simple-routine",
        "repo_name": "proj-1",
        "branch": "main",
        "agent_type": agent_type,
    }
    if agent_config is not None:
        body["agent_config"] = agent_config
    response = await client.post("/api/runs", json=body)
    assert response.status_code == 201
    return response.json()


async def test_create_run_with_codex_server(client: AsyncClient) -> None:
    """codex_server agent type is accepted and persisted on creation."""
    data = await _create_run_with_agent(client, "codex_server")
    assert data["agent_type"] == "codex_server"
    assert data["status"] == "draft"


async def test_read_run_round_trip_codex_server(client: AsyncClient) -> None:
    """A run created with codex_server returns the same agent_type on GET."""
    created = await _create_run_with_agent(
        client, "codex_server", {"endpoint": "http://localhost:9000"}
    )
    run_id = created["id"]

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_type"] == "codex_server"
    assert data["agent_config"] == {"endpoint": "http://localhost:9000"}


async def test_update_run_agent_type_to_codex_server(client: AsyncClient) -> None:
    """Resuming a paused run with codex_server updates agent_type correctly."""
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-codex",
            "branch": "main",
            "agent_type": "cli_subprocess",
            "agent_config": {"timeout": 300},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/pause")

    response = await client.post(
        f"/api/runs/{run_id}/resume",
        json={
            "agent_type": "codex_server",
            "agent_config": {"endpoint": "http://localhost:9000"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["agent_type"] == "codex_server"
    assert data["agent_config"] == {"endpoint": "http://localhost:9000"}


async def test_codex_server_display_name(client: AsyncClient) -> None:
    """codex_server agent type returns a non-empty display name."""
    data = await _create_run_with_agent(client, "codex_server")
    assert data["agent_type_display"] == "Codex Server"
    assert data["agent_icon"] == "codex"
