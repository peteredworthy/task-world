"""Tests for OpenHands agent health check."""

import httpx

from orchestrator.agents.openhands import OpenHandsAgent
from orchestrator.config.enums import AgentType


def _make_transport(status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"status": "ok"})

    return httpx.MockTransport(handler)


def _make_error_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    return httpx.MockTransport(handler)


async def test_health_check_success() -> None:
    client = httpx.AsyncClient(transport=_make_transport(200))
    agent = OpenHandsAgent(http_client=client)
    assert await agent.check_health() is True
    await client.aclose()


async def test_health_check_server_error() -> None:
    client = httpx.AsyncClient(transport=_make_transport(500))
    agent = OpenHandsAgent(http_client=client)
    assert await agent.check_health() is False
    await client.aclose()


async def test_health_check_unreachable() -> None:
    client = httpx.AsyncClient(transport=_make_error_transport())
    agent = OpenHandsAgent(http_client=client)
    assert await agent.check_health() is False
    await client.aclose()


async def test_health_check_custom_url() -> None:
    requests_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(str(request.url))
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    agent = OpenHandsAgent(server_url="http://my-server:5000", http_client=client)
    await agent.check_health()

    assert any("my-server:5000/api/health" in url for url in requests_seen)
    await client.aclose()


def test_agent_info() -> None:
    agent = OpenHandsAgent()
    assert agent.info.agent_type == AgentType.OPENHANDS_LOCAL
    assert agent.info.name == "OpenHands"


def test_custom_tools_parameter() -> None:
    """Custom tools list is stored on the agent."""
    agent = OpenHandsAgent(tools=["terminal", "browser", "glob"])
    assert agent._tools == ["terminal", "browser", "glob"]  # pyright: ignore[reportPrivateUsage]


def test_default_tools_parameter() -> None:
    """Default tools is None, resolved to DEFAULT_OPENHANDS_TOOLS at execute time."""
    agent = OpenHandsAgent()
    assert agent._tools is None  # pyright: ignore[reportPrivateUsage]
