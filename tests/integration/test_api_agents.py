"""Integration tests for agents API endpoint."""

from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:")

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_agents(client: AsyncClient) -> None:
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()
    # OpenHands (local), OpenHands (Docker), claude, codex, User Managed (at minimum)
    assert len(data) >= 4

    # Verify structure
    for agent_data in data:
        assert "agent_type" in agent_data
        assert "name" in agent_data
        assert "available" in agent_data

    # OpenHands Docker availability depends on whether Docker is present
    oh_docker = [a for a in data if a["agent_type"] == "openhands_docker"]
    assert len(oh_docker) == 1
    assert isinstance(oh_docker[0]["available"], bool)

    # OpenHands local should also be present
    oh_local = [a for a in data if a["agent_type"] == "openhands_local"]
    assert len(oh_local) == 1

    # User Managed always available
    um_list = [a for a in data if a["agent_type"] == "user_managed"]
    assert len(um_list) == 1
    assert um_list[0]["available"] is True


async def test_list_agents_has_both_openhands_types(client: AsyncClient) -> None:
    """Both OPENHANDS_LOCAL and OPENHANDS_DOCKER entries are present."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    agent_types = [a["agent_type"] for a in data]
    assert "openhands_local" in agent_types
    assert "openhands_docker" in agent_types


async def test_list_agents_includes_config_schema(client: AsyncClient) -> None:
    """All agent options include config_schema in JSON response."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    for agent_data in data:
        assert "config_schema" in agent_data
        assert isinstance(agent_data["config_schema"], list)
        schema = cast(list[dict[str, Any]], agent_data["config_schema"])
        assert len(schema) > 0

        # Each field has expected keys
        for field in schema:
            assert "name" in field
            assert "field_type" in field
