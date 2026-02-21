"""Unit tests for AgentExecutor._create_agent — Codex agent dispatch.

Verifies that ``AgentExecutor._create_agent`` correctly instantiates
``CodexServerAgent`` (local) and ``CodexServerRemoteAgent`` (remote) from
their respective ``AgentType`` values, and that config values are forwarded
to each agent as expected.

These tests exercise the executor dispatch path without requiring a database,
event loop, or running agent process.
"""

from __future__ import annotations

import pytest

from orchestrator.agents.codex_server import CodexServerAgent
from orchestrator.agents.codex_server_remote import CodexServerRemoteAgent
from orchestrator.agents.errors import AgentNotAvailableError
from orchestrator.agents.executor import AgentExecutor
from orchestrator.config.enums import AgentType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor() -> AgentExecutor:
    """Create an AgentExecutor with no DB session and agent spawning disabled."""
    return AgentExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]


_VALID_REMOTE_URL = "https://codex.example.com"
_VALID_API_KEY = "sk-test-key-abc123"  # pragma: allowlist secret


# ===========================================================================
# codex_server (local) — _create_agent dispatch
# ===========================================================================


def test_executor_codex_create_agent_codex_server_returns_correct_type() -> None:
    """_create_agent with CODEX_SERVER returns a CodexServerAgent instance."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)


def test_executor_codex_create_agent_codex_server_default_endpoint() -> None:
    """CodexServerAgent uses default endpoint when none supplied in config."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    # Default endpoint is http://localhost:9000
    assert agent._endpoint == "http://localhost:9000"


def test_executor_codex_create_agent_codex_server_custom_endpoint() -> None:
    """Custom endpoint in agent_config is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER,
        {"endpoint": "http://my-codex:8888"},
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._endpoint == "http://my-codex:8888"


def test_executor_codex_create_agent_codex_server_model_forwarded() -> None:
    """model in agent_config is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER,
        {"model": "o3"},
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._model == "o3"


def test_executor_codex_create_agent_codex_server_model_none_when_absent() -> None:
    """model defaults to None when not present in agent_config."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    assert agent._model is None


def test_executor_codex_create_agent_codex_server_callback_channel_default() -> None:
    """callback_channel defaults to 'rest' for CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    assert agent._callback_channel == "rest"


def test_executor_codex_create_agent_codex_server_callback_channel_mcp() -> None:
    """callback_channel='mcp' is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER,
        {"callback_channel": "mcp"},
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._callback_channel == "mcp"


def test_executor_codex_create_agent_codex_server_api_key_forwarded() -> None:
    """api_key in agent_config is forwarded to CodexServerAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER,
        {"api_key": "local-key"},  # pragma: allowlist secret
    )
    assert isinstance(agent, CodexServerAgent)
    assert agent._api_key == "local-key"  # pragma: allowlist secret


def test_executor_codex_create_agent_codex_server_agent_type_is_codex_server() -> None:
    """CodexServerAgent.info.agent_type is AgentType.CODEX_SERVER."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER, {})
    assert isinstance(agent, CodexServerAgent)
    assert agent.info.agent_type == AgentType.CODEX_SERVER


# ===========================================================================
# codex_server_remote — _create_agent dispatch
# ===========================================================================


def _remote_config(**overrides: object) -> dict:
    """Return a minimal valid agent_config for CODEX_SERVER_REMOTE."""
    base = {
        "base_url": _VALID_REMOTE_URL,
        "api_key": _VALID_API_KEY,
    }
    base.update(overrides)
    return base


def test_executor_codex_create_agent_codex_server_remote_returns_correct_type() -> None:
    """_create_agent with CODEX_SERVER_REMOTE returns a CodexServerRemoteAgent instance."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert isinstance(agent, CodexServerRemoteAgent)


def test_executor_codex_create_agent_codex_server_remote_base_url_forwarded() -> None:
    """base_url in agent_config is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(base_url="https://remote.example.com"),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._base_url == "https://remote.example.com"


def test_executor_codex_create_agent_codex_server_remote_model_forwarded() -> None:
    """model in agent_config is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(model="gpt-4o"),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._model == "gpt-4o"


def test_executor_codex_create_agent_codex_server_remote_model_none_when_absent() -> None:
    """model defaults to None when not present in agent_config."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._model is None


def test_executor_codex_create_agent_codex_server_remote_session_id_forwarded() -> None:
    """session_id in agent_config is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(session_id="sess-xyz"),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._session_id == "sess-xyz"


def test_executor_codex_create_agent_codex_server_remote_callback_channel_default() -> None:
    """callback_channel defaults to 'rest' for CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._callback_channel == "rest"


def test_executor_codex_create_agent_codex_server_remote_callback_channel_mcp() -> None:
    """callback_channel='mcp' is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(callback_channel="mcp"),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._callback_channel == "mcp"


def test_executor_codex_create_agent_codex_server_remote_api_key_forwarded() -> None:
    """api_key in agent_config is resolved as the bearer token."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(api_key="bearer-token-value"),  # pragma: allowlist secret
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._token == "bearer-token-value"


def test_executor_codex_create_agent_codex_server_remote_retry_forwarded() -> None:
    """retry in agent_config is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(retry=5),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._retry == 5


def test_executor_codex_create_agent_codex_server_remote_timeout_forwarded() -> None:
    """timeout in agent_config is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(timeout=120.0),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._timeout == 120.0


def test_executor_codex_create_agent_codex_server_remote_token_env_var_forwarded() -> None:
    """token_env_var in agent_config is forwarded to CodexServerRemoteAgent."""
    executor = _make_executor()
    agent = executor._create_agent(
        AgentType.CODEX_SERVER_REMOTE,
        _remote_config(token_env_var="MY_CUSTOM_TOKEN"),
    )
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._token_env_var == "MY_CUSTOM_TOKEN"


def test_executor_codex_create_agent_codex_server_remote_default_retry() -> None:
    """retry defaults to 3 when not present in agent_config."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._retry == 3


def test_executor_codex_create_agent_codex_server_remote_default_timeout() -> None:
    """timeout defaults to 300.0 when not present in agent_config."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent._timeout == 300.0


def test_executor_codex_create_agent_codex_server_remote_agent_type_is_remote() -> None:
    """CodexServerRemoteAgent.info.agent_type is AgentType.CODEX_SERVER_REMOTE."""
    executor = _make_executor()
    agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert isinstance(agent, CodexServerRemoteAgent)
    assert agent.info.agent_type == AgentType.CODEX_SERVER_REMOTE


# ===========================================================================
# Unsupported agent type — should raise AgentNotAvailableError
# ===========================================================================


def test_executor_codex_create_agent_unsupported_type_raises() -> None:
    """_create_agent raises AgentNotAvailableError for unsupported agent types."""
    executor = _make_executor()
    with pytest.raises(AgentNotAvailableError):
        executor._create_agent(AgentType.USER_MANAGED, {})


# ===========================================================================
# Dispatch is distinct — local vs remote produce different classes
# ===========================================================================


def test_executor_codex_local_and_remote_produce_different_agent_classes() -> None:
    """CODEX_SERVER and CODEX_SERVER_REMOTE produce distinct agent classes."""
    executor = _make_executor()
    local_agent = executor._create_agent(AgentType.CODEX_SERVER, {})
    remote_agent = executor._create_agent(AgentType.CODEX_SERVER_REMOTE, _remote_config())
    assert type(local_agent) is not type(remote_agent)
    assert isinstance(local_agent, CodexServerAgent)
    assert isinstance(remote_agent, CodexServerRemoteAgent)
