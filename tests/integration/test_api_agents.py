"""Integration tests for agents API endpoint."""

import os
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app

# All tests share an agents_data fixture that calls detect_all(), which spawns
# a codex app-server subprocess (15 s select timeout internally per call).
# Any test may be first in its worker process, so the whole module needs 60 s.
pytestmark = pytest.mark.timeout(60)


# ---------------------------------------------------------------------------
# Helpers for quota tests
# ---------------------------------------------------------------------------


class _NamedOpenHandsAgent:
    """Minimal named wrapper that provides deterministic quota via FakeQuotaFetcher.

    ToolDetector matches agents by ``agent.name`` against ``AgentOption.name``,
    so we expose ``name = "OpenHands (local)"`` to match the local-agent option.

    ``get_quota()`` delegates to a real ``OpenHandsAgent`` (so the
    ``OPENAI_API_KEY`` guard inside the agent is respected) but supplies a
    ``FakeQuotaFetcher`` to avoid any network I/O.  The fake returns
    pre-canned credit-grant data so the test is deterministic.
    """

    name = "OpenHands (local)"

    def get_quota(self) -> Any:
        from orchestrator.runners import OpenHandsAgent
        from orchestrator.runners import FakeQuotaFetcher

        fetcher = FakeQuotaFetcher({"total_granted": 100.0, "total_used": 20.0})
        return OpenHandsAgent().get_quota(fetcher=fetcher)


@pytest.fixture
async def client_with_quota() -> AsyncGenerator[AsyncClient, None]:
    """Client backed by a ToolDetector that has a real quota-capable agent registered."""
    from orchestrator.runners import ToolDetector

    app = create_app(db_path=":memory:")
    app.state.tool_detector = ToolDetector(agents=[_NamedOpenHandsAgent()])

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# Module-level cache to avoid creating a new app and calling detect_all()
# for every test function.
_cached_client: AsyncClient | None = None
_cached_agents_data: list[dict[str, Any]] | None = None


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    global _cached_client
    if _cached_client is None:
        app = create_app(db_path=":memory:")
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        _cached_client = AsyncClient(transport=transport, base_url="http://test")
    yield _cached_client


@pytest.fixture
async def agents_data(client: AsyncClient) -> list[dict[str, Any]]:
    """Fetch agent-runners once and cache across all tests in this module."""
    global _cached_agents_data
    if _cached_agents_data is None:
        response = await client.get("/api/agent-runners")
        assert response.status_code == 200
        _cached_agents_data = response.json()
    return _cached_agents_data


async def test_list_agents(agents_data: list[dict[str, Any]]) -> None:
    data = agents_data
    # OpenHands (local), OpenHands (Docker), and CLI runners are present at minimum.
    assert len(data) >= 4

    # Verify structure
    for agent_data in data:
        assert "agent_runner_type" in agent_data
        assert "name" in agent_data
        assert "available" in agent_data

    # OpenHands Docker availability depends on whether Docker is present
    oh_docker = [a for a in data if a["agent_runner_type"] == "openhands_docker"]
    assert len(oh_docker) == 1
    assert isinstance(oh_docker[0]["available"], bool)

    # OpenHands local should also be present
    oh_local = [a for a in data if a["agent_runner_type"] == "openhands_local"]
    assert len(oh_local) == 1


async def test_list_agents_has_both_openhands_types(agents_data: list[dict[str, Any]]) -> None:
    """Both OPENHANDS_LOCAL and OPENHANDS_DOCKER entries are present."""
    agent_runner_types = [a["agent_runner_type"] for a in agents_data]
    assert "openhands_local" in agent_runner_types
    assert "openhands_docker" in agent_runner_types


async def test_list_agents_includes_config_schema(agents_data: list[dict[str, Any]]) -> None:
    """All agent options include config_schema in JSON response."""
    for agent_data in agents_data:
        assert "config_schema" in agent_data
        assert isinstance(agent_data["config_schema"], list)
        schema = cast(list[dict[str, Any]], agent_data["config_schema"])
        assert len(schema) > 0

        # Each field has expected keys
        for field in schema:
            assert "name" in field
            assert "field_type" in field


async def test_list_agents_includes_codex_server(agents_data: list[dict[str, Any]]) -> None:
    """GET /api/agents always includes a codex_server entry."""
    cs_entries = [a for a in agents_data if a["agent_runner_type"] == "codex_server"]
    assert len(cs_entries) == 1, "Expected exactly one codex_server entry"

    cs = cs_entries[0]
    assert "available" in cs
    assert isinstance(cs["available"], bool)
    assert "detail" in cs
    assert cs["detail"] != ""


async def test_codex_server_unavailable_has_install_hint(agents_data: list[dict[str, Any]]) -> None:
    """When codex_server is unavailable, the response includes an actionable install_hint."""
    cs = next(a for a in agents_data if a["agent_runner_type"] == "codex_server")
    if not cs["available"]:
        assert "install_hint" in cs
        assert cs["install_hint"] != "", (
            "Unavailable codex_server must have a non-empty install_hint"
        )


async def test_codex_server_has_stable_shape(agents_data: list[dict[str, Any]]) -> None:
    """codex_server entry has stable response shape."""
    required_keys = {
        "agent_runner_type",
        "name",
        "title",
        "description",
        "available",
        "detail",
        "install_hint",
        "config_schema",
    }

    entry = next(a for a in agents_data if a["agent_runner_type"] == "codex_server")
    assert required_keys.issubset(entry.keys()), (
        f"codex_server missing keys: {required_keys - entry.keys()}"
    )
    # config_schema is always a non-empty list
    assert isinstance(entry["config_schema"], list)
    assert len(entry["config_schema"]) > 0


async def test_codex_server_config_fields(agents_data: list[dict[str, Any]]) -> None:
    """codex_server exposes model, restrictions, and callback_channel config fields."""
    cs = next(a for a in agents_data if a["agent_runner_type"] == "codex_server")
    schema = cast(list[dict[str, Any]], cs["config_schema"])
    field_names = [f["name"] for f in schema]

    assert "model" in field_names
    assert "restrictions" in field_names
    assert "callback_channel" in field_names

    cb_field = next(f for f in schema if f["name"] == "callback_channel")
    assert cb_field.get("options") is not None
    assert "rest" in cb_field["options"]
    assert "mcp" in cb_field["options"]


# ---------------------------------------------------------------------------
# Step-04 quota contract tests
# ---------------------------------------------------------------------------


async def test_get_agents_returns_200(client: AsyncClient) -> None:
    """GET /api/agents returns HTTP 200."""
    response = await client.get("/api/agent-runners")
    assert response.status_code == 200


async def test_every_agent_has_quota_key(agents_data: list[dict[str, Any]]) -> None:
    """Every agent object in the GET /api/agents response contains a 'quota' key.

    The value may be null (None) when no quota-capable agent is registered,
    but the key itself must always be present in the serialised response.
    """
    for agent in agents_data:
        assert "quota" in agent, f"Agent {agent.get('name')!r} is missing the 'quota' key"


async def test_non_null_quota_has_required_fields(agents_data: list[dict[str, Any]]) -> None:
    """Any non-null quota in the response exposes all 5 AgentQuota fields.

    When no agents with get_quota() are registered the test passes vacuously
    (all quotas are null).  The assertion fires only when quota data is
    present, confirming the serialisation contract.
    """
    _REQUIRED_QUOTA_FIELDS = {
        "balance_usd",
        "balance_pct",
        "max_balance_usd",
        "label",
        "supports_quota",
    }

    for agent in agents_data:
        quota = agent.get("quota")
        if quota is not None:
            missing = _REQUIRED_QUOTA_FIELDS - quota.keys()
            assert not missing, f"Agent {agent.get('name')!r} quota is missing fields: {missing}"


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
async def test_at_least_one_agent_has_non_null_quota(
    client_with_quota: AsyncClient,
) -> None:
    """At least one agent returns non-null quota when OPENAI_API_KEY is available.

    Uses a client backed by a ToolDetector that has a real OpenHandsAgent
    registered as the quota provider.  A FakeQuotaFetcher supplies pre-canned
    credit-grant data so no network I/O is performed, but the real
    OpenHandsAgent still enforces the ``OPENAI_API_KEY`` guard (returns None
    when the key is absent — which is why this test is skipped without the key).
    A non-null result confirms that quota data flows correctly through the
    GET /api/agents endpoint all the way to the JSON response.
    """
    response = await client_with_quota.get("/api/agent-runners")
    assert response.status_code == 200
    data: list[dict[str, Any]] = response.json()

    non_null_quotas = [a for a in data if a.get("quota") is not None]
    assert len(non_null_quotas) >= 1, (
        "Expected at least one agent with non-null quota when OPENAI_API_KEY is set"
    )
