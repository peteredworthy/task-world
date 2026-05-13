"""Unit tests for ToolDetector quota attachment."""

from __future__ import annotations

import asyncio
import time

from orchestrator.config import AgentRunnerType
from orchestrator.runners import ToolDetector
from orchestrator.runners.types import AgentOption, AgentQuota

_MINIMAL_OPTIONS = [
    AgentOption(
        agent_runner_type=AgentRunnerType.USER_MANAGED,
        name="User Managed",
        available=True,
        detail="stub",
        config_schema=[],
    ),
]


async def _with_quotas(
    detector: ToolDetector,
    options: list[AgentOption] | None = None,
) -> list[AgentOption]:
    """Attach quotas to synthetic options without running backend detection."""
    return await detector._attach_quotas(  # pyright: ignore[reportPrivateUsage]
        list(options or _MINIMAL_OPTIONS)
    )


class _AgentStub:
    """Minimal stub used as a named quota provider for the detector."""

    def __init__(self, name: str, quota: AgentQuota | None = None) -> None:
        self.name = name
        self._quota = quota

    def get_quota(self) -> AgentQuota | None:
        return self._quota


class _RaisingAgentStub:
    """Agent stub whose get_quota() always raises an exception."""

    def __init__(self, name: str) -> None:
        self.name = name

    def get_quota(self) -> AgentQuota | None:
        raise RuntimeError("quota fetch failed")


class _SlowAgentStub:
    """Agent stub whose get_quota() raises TimeoutError to simulate a slow quota fetch.

    Instead of actually sleeping (which would block a background thread for the
    full sleep duration after asyncio cancels the wait_for), we directly raise
    asyncio.TimeoutError.  _fetch_quota_for_option catches all exceptions the
    same way, so this exercises the identical code path without wall-clock cost.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def get_quota(self) -> AgentQuota | None:
        raise asyncio.TimeoutError("simulated quota timeout")


async def test_quota_populated_for_available_agent() -> None:
    """Quota attachment uses the quota from a registered available agent."""
    quota = AgentQuota(balance_usd=42.0)
    # "claude" is a CLI tool that detect_cli_tools() always returns (available or not).
    # On this test machine claude is installed, so we can use its real name.
    # We use "User Managed" which is always available and has a stable name.
    stub = _AgentStub(name="User Managed", quota=quota)
    detector = ToolDetector(agents=[stub])

    options = await _with_quotas(detector)
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is not None
    assert um.quota.balance_usd == 42.0


async def test_quota_none_for_unavailable_agent() -> None:
    """Quota attachment sets quota=None for unavailable agents without calling get_quota()."""
    detector = ToolDetector(agents=[_RaisingAgentStub(name="Unavailable")])
    options = await _with_quotas(
        detector,
        [
            AgentOption(
                agent_runner_type=AgentRunnerType.USER_MANAGED,
                name="Unavailable",
                available=False,
            )
        ],
    )

    for option in options:
        if not option.available:
            assert option.quota is None, f"Unavailable agent {option.name!r} should have quota=None"


async def test_quota_none_when_get_quota_returns_none() -> None:
    """Agent with get_quota() that returns None (default) yields quota=None on the option.

    This covers the protocol default: agents that do not override get_quota() return
    None, and quota attachment must propagate that as quota=None (not omit it or error).
    """
    stub = _AgentStub(name="User Managed", quota=None)
    detector = ToolDetector(agents=[stub])

    options = await _with_quotas(detector)
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is None


async def test_exception_in_get_quota_yields_none() -> None:
    """Exceptions from get_quota() are swallowed and result in quota=None on first failure (no prior success)."""
    stub = _RaisingAgentStub(name="User Managed")
    detector = ToolDetector(agents=[stub])

    options = await _with_quotas(detector)
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is None


async def test_slow_get_quota_times_out_and_yields_none() -> None:
    """A get_quota() that times out results in quota=None on first failure (no prior success).

    The stub raises asyncio.TimeoutError directly, exercising the same exception
    handler as a real timeout without blocking any background thread.
    """
    stub = _SlowAgentStub(name="User Managed")
    detector = ToolDetector(agents=[stub])

    options = await _with_quotas(detector)
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is None


async def test_quota_cached_between_calls() -> None:
    """A second quota attachment call within the TTL returns the cached quota."""
    call_count = 0

    class _CountingStub:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count
            call_count += 1
            return AgentQuota(balance_usd=10.0)

    detector = ToolDetector(agents=[_CountingStub()])

    await _with_quotas(detector)
    assert call_count == 1

    await _with_quotas(detector)
    # Cache should still be fresh — get_quota must not be called again
    assert call_count == 1


async def test_quota_refetched_after_ttl_expiry() -> None:
    """After the cache TTL expires, quota attachment re-invokes get_quota().

    Time is simulated by directly manipulating the cached_at field on the
    _QuotaCacheEntry — no mocking framework required.
    """
    call_count = 0

    class _CountingStubExpiry:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count
            call_count += 1
            return AgentQuota(balance_usd=20.0)

    detector = ToolDetector(agents=[_CountingStubExpiry()])

    # First call populates the cache
    await _with_quotas(detector)
    assert call_count == 1

    # Directly manipulate cached_at to simulate TTL expiry.
    # Active-entry TTL is 60s; setting cached_at 400s in the past makes it stale.
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call must re-invoke get_quota() because the cache is stale
    await _with_quotas(detector)
    assert call_count == 2


async def test_no_agents_registered_all_quota_none() -> None:
    """When no agents are passed to ToolDetector, all quotas are None."""
    detector = ToolDetector()
    options = await _with_quotas(detector)

    for option in options:
        assert option.quota is None, (
            f"Agent {option.name!r} should have quota=None when no agents registered"
        )


async def test_failure_preserves_last_successful_quota() -> None:
    """After a successful fetch, a subsequent failure returns the stale quota with fetched_at."""
    call_count = 0

    class _FailSecondTimeStub:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AgentQuota(balance_usd=42.0)
            raise RuntimeError("rate limited")

    detector = ToolDetector(agents=[_FailSecondTimeStub()])

    # First call succeeds
    options1 = await _with_quotas(detector)
    um1 = next(o for o in options1 if o.name == "User Managed")
    assert um1.quota is not None
    assert um1.quota.balance_usd == 42.0
    assert um1.quota.fetched_at is not None

    # Expire the cache so second call attempts a fetch
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call fails — should return stale quota
    options2 = await _with_quotas(detector)
    um2 = next(o for o in options2 if o.name == "User Managed")
    assert um2.quota is not None
    assert um2.quota.balance_usd == 42.0
    assert um2.quota.fetched_at is not None


async def test_retry_backoff_after_failure() -> None:
    """After a failure, a second call within 5min doesn't re-call get_quota()."""
    call_count = 0

    class _FailOnceStub:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AgentQuota(balance_usd=10.0)
            raise RuntimeError("rate limited")

    detector = ToolDetector(agents=[_FailOnceStub()])

    # First call succeeds
    await _with_quotas(detector)
    assert call_count == 1

    # Expire cache to trigger fetch
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call fails, sets retry_after
    await _with_quotas(detector)
    assert call_count == 2

    # Third call: cache is stale but within retry_after backoff — should NOT call get_quota
    cache_entry2 = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry2.cached_at = time.monotonic() - 400  # expire cache again
    # retry_after should still be in the future (set ~300s from now)

    await _with_quotas(detector)
    assert call_count == 2  # no additional call


async def test_fetched_at_set_on_success() -> None:
    """A successful fetch populates fetched_at as an ISO 8601 string."""
    from datetime import datetime

    stub = _AgentStub(name="User Managed", quota=AgentQuota(balance_usd=5.0))
    detector = ToolDetector(agents=[stub])

    options = await _with_quotas(detector)
    um = next(o for o in options if o.name == "User Managed")

    assert um.quota is not None
    assert um.quota.fetched_at is not None
    # Verify it parses as ISO 8601
    parsed = datetime.fromisoformat(um.quota.fetched_at)
    assert parsed is not None


async def test_fetched_at_preserved_after_failure() -> None:
    """fetched_at reflects the last success time, not the failure time."""
    call_count = 0

    class _TimedFailStub:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AgentQuota(balance_usd=7.0)
            raise RuntimeError("rate limited")

    detector = ToolDetector(agents=[_TimedFailStub()])

    # First call succeeds
    options1 = await _with_quotas(detector)
    um1 = next(o for o in options1 if o.name == "User Managed")
    assert um1.quota is not None
    fetched_at_1 = um1.quota.fetched_at
    assert fetched_at_1 is not None

    # Expire cache
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call fails
    options2 = await _with_quotas(detector)
    um2 = next(o for o in options2 if o.name == "User Managed")
    assert um2.quota is not None
    # fetched_at should be the same as after the first (successful) call
    assert um2.quota.fetched_at == fetched_at_1
