"""Unit tests for AgentRunnerExecutor._create_agent — Codex agent dispatch.

Verifies that ``AgentRunnerExecutor._create_agent`` correctly instantiates
``CodexServerAgent`` (local) from its ``AgentRunnerType`` value, and that config
values are forwarded to the agent as expected.

These tests exercise the executor dispatch path without requiring a database,
event loop, or running agent process.
"""

from __future__ import annotations

import pytest

from orchestrator.runners import discover_agents
from orchestrator.runners import CodexServerAgent
from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.config import AgentRunnerType

# Ensure agent factories are registered before tests run
discover_agents()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor() -> AgentRunnerExecutor:
    """Create an AgentRunnerExecutor with no DB session and agent spawning disabled."""
    return AgentRunnerExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]


# ===========================================================================
# codex_server (local) — _create_agent dispatch
# ===========================================================================


def test_executor_codex_create_agent_codex_server_returns_correct_type() -> None:
    """_create_agent with CODEX_SERVER returns a CodexServerAgent instance."""
    executor = _make_executor()
    agent = executor._create_agent(AgentRunnerType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)


def test_executor_codex_create_agent_codex_server_model_forwarded() -> None:
    """model in agent_runner_config is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentRunnerType.CODEX_SERVER,
        {"model": "o3"},
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._model == "o3"


def test_executor_codex_create_agent_codex_server_model_none_when_absent() -> None:
    """model defaults to None when not present in agent_runner_config."""
    executor = _make_executor()
    agent = executor._create_agent(AgentRunnerType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    assert agent._model is None


def test_executor_codex_create_agent_codex_server_callback_channel_default() -> None:
    """callback_channel defaults to 'rest' for CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(AgentRunnerType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    assert agent._callback_channel == "rest"


def test_executor_codex_create_agent_codex_server_callback_channel_mcp() -> None:
    """callback_channel='mcp' is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentRunnerType.CODEX_SERVER,
        {"callback_channel": "mcp"},
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._callback_channel == "mcp"


def test_executor_codex_create_agent_codex_server_api_key_forwarded() -> None:
    """api_key in agent_runner_config is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentRunnerType.CODEX_SERVER,
        {"api_key": "local-key"},  # pragma: allowlist secret
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._api_key == "local-key"  # pragma: allowlist secret


def test_executor_codex_create_agent_codex_server_agent_runner_type_is_codex_server() -> None:
    """CodexServerAgent.info.agent_runner_type is AgentRunnerType.CODEX_SERVER."""
    executor = _make_executor()
    agent = executor._create_agent(AgentRunnerType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    assert agent.info.agent_runner_type == AgentRunnerType.CODEX_SERVER


# ===========================================================================
# Unsupported agent runner type — should raise AgentNotAvailableError
# ===========================================================================


def test_executor_codex_create_agent_user_managed_requires_service() -> None:
    """_create_agent for USER_MANAGED raises ValueError without service kwarg."""
    executor = _make_executor()
    with pytest.raises(ValueError, match="service"):
        executor._create_agent(AgentRunnerType.USER_MANAGED, {})
