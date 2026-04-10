"""Integration tests for config API endpoint."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create test client with in-memory database."""
    app = create_app(db_path=":memory:", routine_dirs=[])
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_get_config(client: AsyncClient) -> None:
    """GET /api/config returns global configuration."""
    response = await client.get("/api/config")
    assert response.status_code == 200

    data = response.json()
    assert "dashboard_refresh_interval_seconds" in data
    assert "dashboard_max_recent_runs" in data
    assert "agents_openhands_url" in data
    assert "agents_default_type" in data

    # Check default values
    assert data["dashboard_refresh_interval_seconds"] == 5
    assert data["dashboard_max_recent_runs"] == 50
