"""Integration tests for project API endpoints."""

from pathlib import Path
from typing import Any

from collections.abc import AsyncGenerator

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


async def _create_run(client: AsyncClient, project_id: str = "proj-1") -> dict[str, Any]:
    """Helper: create a run with the given project_id."""
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "project_id": project_id},
    )
    assert response.status_code == 201
    return response.json()


async def test_list_projects_empty(client: AsyncClient) -> None:
    """No runs exist -> empty project_ids list."""
    response = await client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert data["project_ids"] == []


async def test_list_projects_returns_unique_ids(client: AsyncClient) -> None:
    """Create runs with different project_ids, verify unique list returned."""
    await _create_run(client, project_id="alpha")
    await _create_run(client, project_id="beta")
    await _create_run(client, project_id="gamma")

    response = await client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert sorted(data["project_ids"]) == ["alpha", "beta", "gamma"]


async def test_list_projects_deduplicates(client: AsyncClient) -> None:
    """Multiple runs with same project_id -> it appears only once."""
    await _create_run(client, project_id="shared-project")
    await _create_run(client, project_id="shared-project")
    await _create_run(client, project_id="other-project")

    response = await client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert sorted(data["project_ids"]) == ["other-project", "shared-project"]
