"""Unit tests for OpenHandsAgent.get_quota() using FakeQuotaFetcher.

No MagicMock, no network access. All test cases use FakeQuotaFetcher or
a simple inline stub for the "raises exception" case.

The sixth test confirms UserManagedAgent has no get_quota() override without
constructing the agent (which requires WorkflowService — see GAP-09).
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.openhands import OpenHandsAgent
from orchestrator.runners.quota import FakeQuotaFetcher
from orchestrator.runners.types import AgentQuota
from orchestrator.runners.user_managed import UserManagedAgent

_API_KEY = "sk-test-openhands-quota"  # pragma: allowlist secret


def _make_agent(api_key: str = _API_KEY) -> OpenHandsAgent:
    """Construct a minimal OpenHandsAgent with an explicit api_key."""
    return OpenHandsAgent(api_key=api_key)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_valid_response_returns_correct_quota() -> None:
    """FakeQuotaFetcher with valid response returns the correct AgentQuota.

    {"total_granted": 100.0, "total_used": 25.0}
    → balance_usd=75.0, max_balance_usd=100.0, label="OpenAI credit balance"
    """
    agent = _make_agent()
    fetcher = FakeQuotaFetcher(response={"total_granted": 100.0, "total_used": 25.0})

    result = agent.get_quota(fetcher=fetcher)

    assert result is not None
    assert isinstance(result, AgentQuota)
    assert result.balance_usd == 75.0
    assert result.max_balance_usd == 100.0
    assert result.label == "OpenAI credit balance"
    assert result.balance_pct is None


def test_missing_api_key_returns_none_without_calling_fetcher() -> None:
    """When the API key is absent, get_quota() returns None and the fetcher is not called."""

    class _CountingFetcher:
        def __init__(self) -> None:
            self.call_count = 0

        def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
            self.call_count += 1
            return {"total_granted": 100.0, "total_used": 0.0}

    agent = _make_agent()
    # Simulate a missing key by clearing _api_key after construction.
    agent._api_key = ""  # pyright: ignore[reportPrivateUsage]

    fetcher = _CountingFetcher()
    result = agent.get_quota(fetcher=fetcher)

    assert result is None
    assert fetcher.call_count == 0


def test_fetcher_raises_exception_returns_none() -> None:
    """When the fetcher raises any Exception, get_quota() swallows it and returns None."""

    class _RaisingFetcher:
        def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
            raise RuntimeError("network failure")

    agent = _make_agent()
    result = agent.get_quota(fetcher=_RaisingFetcher())

    assert result is None


def test_response_missing_total_granted_returns_none() -> None:
    """When the response is missing 'total_granted', get_quota() returns None."""
    agent = _make_agent()
    fetcher = FakeQuotaFetcher(response={"total_used": 25.0})

    result = agent.get_quota(fetcher=fetcher)

    assert result is None


def test_response_missing_total_used_returns_none() -> None:
    """When the response is missing 'total_used', get_quota() returns None."""
    agent = _make_agent()
    fetcher = FakeQuotaFetcher(response={"total_granted": 100.0})

    result = agent.get_quota(fetcher=fetcher)

    assert result is None


def test_user_managed_agent_has_no_get_quota_override() -> None:
    """UserManagedAgent must not define its own get_quota() method.

    We do NOT construct the agent (it requires WorkflowService — GAP-09).
    Checking __dict__ proves no override exists.
    """
    assert "get_quota" not in UserManagedAgent.__dict__
