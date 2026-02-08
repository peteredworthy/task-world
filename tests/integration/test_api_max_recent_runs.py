"""Integration tests for max_recent_runs config."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db


FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create test client with in-memory database."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Create 10 test runs via API
        for i in range(10):
            response = await c.post(
                "/api/runs",
                json={"routine_id": "simple-routine", "repo_name": f"proj-{i}", "branch": "main"},
            )
            assert response.status_code == 201

        yield c
    await app.state.engine.dispose()


async def test_list_runs_default_limit(client: AsyncClient) -> None:
    """GET /api/runs without filters applies max_recent_runs limit."""
    # The global config default is max_recent_runs=50
    # We created 10 runs, so all should be returned
    response = await client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == 10


async def test_list_runs_explicit_limit(client: AsyncClient) -> None:
    """GET /api/runs?limit=N overrides the config default."""
    response = await client.get("/api/runs?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == 3


async def test_list_runs_with_filter_ignores_limit(client: AsyncClient) -> None:
    """Filters like status or project_id are not affected by max_recent_runs."""
    # When a specific filter is applied, the limit is not used
    # All runs are in DRAFT status, so all 10 should be returned
    response = await client.get("/api/runs?status=draft")
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == 10
