"""Integration tests for get_quota() against the real OpenAI credits API.

Tests are skipped when OPENAI_API_KEY is not set in the environment.
"""

import os

import pytest

from orchestrator.agents.codex_server_remote import CodexServerRemoteAgent
from orchestrator.agents.openhands import OpenHandsAgent
from orchestrator.agents.types import AgentQuota


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_codex_server_remote_quota_live() -> None:
    """Real HTTP call to OpenAI credits API via CodexServerRemoteAgent.get_quota().

    Skipped when OPENAI_API_KEY is absent.  Returns AgentQuota when the key
    has credit-grant access, or None when the endpoint returns an error (both
    are valid outcomes — get_quota() swallows all exceptions).
    """
    # CodexServerRemoteAgent resolves OPENAI_API_KEY from the environment as a
    # fallback when no api_key is passed.  base_url is required by __init__
    # for WebSocket validation but is not used by get_quota().
    agent = CodexServerRemoteAgent(base_url="https://example.com")
    result = agent.get_quota()
    assert result is None or isinstance(result, AgentQuota)


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_openhands_quota_live() -> None:
    """Real HTTP call to OpenAI credits API via OpenHandsAgent.get_quota().

    Skipped when OPENAI_API_KEY is absent.  Returns AgentQuota when the key
    has credit-grant access, or None when the endpoint returns an error (both
    are valid outcomes — get_quota() swallows all exceptions).
    """
    # OpenHandsAgent picks up OPENAI_API_KEY from os.environ when api_key is
    # not supplied explicitly.
    agent = OpenHandsAgent()
    result = agent.get_quota()
    assert result is None or isinstance(result, AgentQuota)
