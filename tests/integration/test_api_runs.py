"""Integration tests for run API endpoints."""

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


async def _create_run(client: AsyncClient) -> dict[str, Any]:
    """Helper: create a run and return the response data."""
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "project_id": "proj-1"},
    )
    assert response.status_code == 201
    return response.json()


async def test_create_run(client: AsyncClient) -> None:
    data = await _create_run(client)
    assert data["project_id"] == "proj-1"
    assert data["routine_id"] == "simple-routine"
    assert data["status"] == "draft"
    assert len(data["steps"]) == 1
    assert len(data["steps"][0]["tasks"]) == 1


async def test_create_run_routine_not_found(client: AsyncClient) -> None:
    response = await client.post(
        "/api/runs",
        json={"routine_id": "nonexistent", "project_id": "proj-1"},
    )
    assert response.status_code == 404


async def test_list_runs_empty(client: AsyncClient) -> None:
    response = await client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}


async def test_list_runs(client: AsyncClient) -> None:
    await _create_run(client)
    response = await client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == 1


async def test_list_runs_filter_by_project(client: AsyncClient) -> None:
    await _create_run(client)

    response = await client.get("/api/runs?project_id=proj-1")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    response = await client.get("/api/runs?project_id=other-project")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 0


async def test_list_runs_filter_by_status(client: AsyncClient) -> None:
    await _create_run(client)

    response = await client.get("/api/runs?status=draft")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    response = await client.get("/api/runs?status=active")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 0


async def test_get_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id
    assert data["project_id"] == "proj-1"


async def test_get_run_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/runs/nonexistent")
    assert response.status_code == 404


async def test_start_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["started_at"] is not None


async def test_start_run_invalid_state(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    # Start it first
    await client.post(f"/api/runs/{run_id}/start")

    # Try to start again -> 409
    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 409


async def test_delete_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 204

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 404


async def test_delete_run_not_found(client: AsyncClient) -> None:
    response = await client.delete("/api/runs/nonexistent")
    assert response.status_code == 404


async def test_pause_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    # Start the run first
    await client.post(f"/api/runs/{run_id}/start")

    # Pause it
    response = await client.post(f"/api/runs/{run_id}/pause")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "paused"


async def test_resume_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    # Start, then pause, then resume
    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/pause")

    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"


async def test_pause_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/runs/nonexistent/pause")
    assert response.status_code == 404


async def test_resume_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/runs/nonexistent/resume")
    assert response.status_code == 404


async def test_pause_invalid_state(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    # Try to pause a DRAFT run -> 409
    response = await client.post(f"/api/runs/{run_id}/pause")
    assert response.status_code == 409


async def test_resume_invalid_state(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    # Start the run (ACTIVE), try to resume without pausing -> 409
    await client.post(f"/api/runs/{run_id}/start")
    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409


async def test_create_run_with_agent_config(client: AsyncClient) -> None:
    """agent_config is stored and returned in the response."""
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "project_id": "proj-1",
            "agent_type": "cli_subprocess",
            "agent_config": {"model": "claude-4", "callback_channel": "mcp"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_type"] == "cli_subprocess"
    assert data["agent_config"]["model"] == "claude-4"
    assert data["agent_config"]["callback_channel"] == "mcp"


async def test_create_run_agent_config_defaults_to_empty(client: AsyncClient) -> None:
    """agent_config defaults to empty dict when not provided."""
    data = await _create_run(client)
    assert data["agent_config"] == {}
