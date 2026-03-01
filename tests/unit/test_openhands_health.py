"""Tests for OpenHands agent health check and metadata."""

from orchestrator.agents.openhands import OpenHandsAgent, _SDK_AVAILABLE  # pyright: ignore[reportPrivateUsage]
from orchestrator.config.enums import AgentType


async def test_health_check_with_api_key() -> None:
    """check_health returns True when SDK is available and API key is set."""
    agent = OpenHandsAgent(api_key="test-key-123")
    result = await agent.check_health()
    # True only if SDK is installed AND api_key is set
    assert result == _SDK_AVAILABLE


async def test_health_check_no_api_key() -> None:
    """check_health still returns True without API key (local LLM supported)."""
    import os

    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        agent = OpenHandsAgent(api_key="")
        # API key is not required when using a local LLM
        assert await agent.check_health() == _SDK_AVAILABLE
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


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
