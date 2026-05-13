"""Slow live quota check against the real OpenAI credits API."""

import os

import pytest

from orchestrator.runners import OpenHandsAgent
from orchestrator.runners.types import AgentQuota


@pytest.mark.slow
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_openhands_quota_live() -> None:
    """Real HTTP call to OpenAI credits API via OpenHandsAgent.get_quota()."""
    agent = OpenHandsAgent()
    result = agent.get_quota()
    assert result is None or isinstance(result, AgentQuota)
