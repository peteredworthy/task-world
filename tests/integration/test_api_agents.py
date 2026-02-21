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


async def test_list_agents_includes_codex_server(client: AsyncClient) -> None:
    """GET /api/agents always includes a codex_server entry."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    cs_entries = [a for a in data if a["agent_type"] == "codex_server"]
    assert len(cs_entries) == 1, "Expected exactly one codex_server entry"

    cs = cs_entries[0]
    assert "available" in cs
    assert isinstance(cs["available"], bool)
    assert "detail" in cs
    assert cs["detail"] != ""


async def test_list_agents_includes_codex_server_remote(client: AsyncClient) -> None:
    """GET /api/agents always includes a codex_server_remote entry that is available."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    csr_entries = [a for a in data if a["agent_type"] == "codex_server_remote"]
    assert len(csr_entries) == 1, "Expected exactly one codex_server_remote entry"

    csr = csr_entries[0]
    assert csr["available"] is True
    assert "detail" in csr
    assert csr["detail"] != ""


async def test_codex_server_unavailable_has_install_hint(client: AsyncClient) -> None:
    """When codex_server is unavailable, the response includes an actionable install_hint."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    cs = next(a for a in data if a["agent_type"] == "codex_server")
    if not cs["available"]:
        assert "install_hint" in cs
        assert cs["install_hint"] != "", (
            "Unavailable codex_server must have a non-empty install_hint"
        )


async def test_codex_server_response_shape(client: AsyncClient) -> None:
    """codex_server and codex_server_remote entries have stable response shape."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    required_keys = {
        "agent_type",
        "name",
        "title",
        "description",
        "available",
        "detail",
        "install_hint",
        "config_schema",
    }

    for agent_type in ("codex_server", "codex_server_remote"):
        entry = next(a for a in data if a["agent_type"] == agent_type)
        assert required_keys.issubset(entry.keys()), (
            f"{agent_type} missing keys: {required_keys - entry.keys()}"
        )
        # config_schema is always a non-empty list
        assert isinstance(entry["config_schema"], list)
        assert len(entry["config_schema"]) > 0


async def test_codex_server_remote_config_fields(client: AsyncClient) -> None:
    """codex_server_remote exposes required endpoint and api_key config fields."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    csr = next(a for a in data if a["agent_type"] == "codex_server_remote")
    schema = cast(list[dict[str, Any]], csr["config_schema"])
    field_names = [f["name"] for f in schema]

    assert "endpoint" in field_names
    assert "api_key" in field_names
    assert "callback_channel" in field_names

    endpoint_field = next(f for f in schema if f["name"] == "endpoint")
    assert endpoint_field.get("required") is True

    api_key_field = next(f for f in schema if f["name"] == "api_key")
    assert api_key_field.get("required") is True
    assert api_key_field["field_type"] == "secret"


async def test_codex_server_config_fields(client: AsyncClient) -> None:
    """codex_server exposes endpoint and callback_channel config fields."""
    response = await client.get("/api/agents")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    cs = next(a for a in data if a["agent_type"] == "codex_server")
    schema = cast(list[dict[str, Any]], cs["config_schema"])
    field_names = [f["name"] for f in schema]

    assert "endpoint" in field_names
    assert "callback_channel" in field_names

    cb_field = next(f for f in schema if f["name"] == "callback_channel")
    assert cb_field.get("options") is not None
    assert "rest" in cb_field["options"]
    assert "mcp" in cb_field["options"]
