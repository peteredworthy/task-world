"""Unit tests for AgentQuota model validation and FakeQuotaFetcher behaviour."""

from __future__ import annotations

import pytest

from orchestrator.runners import FakeQuotaFetcher
from orchestrator.runners.types import AgentQuota


def test_agent_quota_balance_usd_only() -> None:
    """AgentQuota with only balance_usd set is valid."""
    quota = AgentQuota(balance_usd=42.0)
    assert quota.balance_usd == 42.0
    assert quota.balance_pct is None


def test_agent_quota_balance_pct_only() -> None:
    """AgentQuota with only balance_pct set is valid."""
    quota = AgentQuota(balance_pct=75.0)
    assert quota.balance_pct == 75.0
    assert quota.balance_usd is None


def test_agent_quota_both_fields() -> None:
    """AgentQuota with both balance_usd and balance_pct set is valid."""
    quota = AgentQuota(balance_usd=10.0, balance_pct=50.0)
    assert quota.balance_usd == 10.0
    assert quota.balance_pct == 50.0


def test_agent_quota_raises_when_both_none() -> None:
    """AgentQuota raises ValueError when neither balance_usd nor balance_pct is provided."""
    with pytest.raises(ValueError, match="At least one of balance_usd or balance_pct must be set"):
        AgentQuota()


def test_agent_quota_max_balance_usd() -> None:
    """AgentQuota stores max_balance_usd correctly."""
    quota = AgentQuota(balance_usd=30.0, max_balance_usd=100.0)
    assert quota.max_balance_usd == 100.0


def test_fake_quota_fetcher_returns_configured_dict() -> None:
    """FakeQuotaFetcher returns the pre-configured response dict."""
    expected = {"total_granted": 100.0, "total_used": 25.0, "total_available": 75.0}
    fetcher = FakeQuotaFetcher(response=expected)
    result = fetcher.fetch_openai_credits(api_key="sk-test-key")
    assert result == expected


def test_fake_quota_fetcher_ignores_api_key() -> None:
    """FakeQuotaFetcher returns the same result regardless of the api_key argument."""
    expected = {"total_granted": 50.0, "total_used": 10.0, "total_available": 40.0}
    fetcher = FakeQuotaFetcher(response=expected)
    result_a = fetcher.fetch_openai_credits(api_key="sk-key-a")
    result_b = fetcher.fetch_openai_credits(api_key="sk-key-b")
    assert result_a == result_b == expected
