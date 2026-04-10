"""Integration tests for API health and basic setup."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app


@pytest.fixture
async def client(tmp_path: object) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:")
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_unknown_route_returns_404(client: AsyncClient) -> None:
    response = await client.get("/nonexistent")
    assert response.status_code == 404
