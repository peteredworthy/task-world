"""Unit tests for ToolDetector quota-fetching integration in detect_all()."""

from __future__ import annotations

import asyncio
import time

import pytest

from orchestrator.runners.detector import ToolDetector
from orchestrator.runners.types import AgentQuota


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
    """Agent stub whose get_quota() sleeps longer than the 3-second timeout."""

    def __init__(self, name: str) -> None:
        self.name = name

    def get_quota(self) -> AgentQuota | None:
        import time

        time.sleep(5)  # blocks the thread well beyond the 3-second limit
        return AgentQuota(balance_usd=99.0)


async def test_quota_populated_for_available_agent() -> None:
    """detect_all() attaches the quota from a registered available agent."""
    quota = AgentQuota(balance_usd=42.0)
    # "claude" is a CLI tool that detect_cli_tools() always returns (available or not).
    # On this test machine claude is installed, so we can use its real name.
    # We use "User Managed" which is always available and has a stable name.
    stub = _AgentStub(name="User Managed", quota=quota)
    detector = ToolDetector(agents=[stub])

    options = await detector.detect_all()
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is not None
    assert um.quota.balance_usd == 42.0


async def test_quota_none_for_unavailable_agent() -> None:
    """detect_all() sets quota=None for unavailable agents without calling get_quota()."""
    # OpenHands Local will be unavailable if the SDK is not installed.
    # Instead, we test an unavailable CLI tool by using a name that won't
    # match any real option — verify via the general rule that unavailable
    # agents never get quota populated.
    detector = ToolDetector()
    options = await detector.detect_all()

    for option in options:
        if not option.available:
            assert option.quota is None, f"Unavailable agent {option.name!r} should have quota=None"


async def test_quota_none_when_get_quota_returns_none() -> None:
    """Agent with get_quota() that returns None (default) yields quota=None on the option.

    This covers the protocol default: agents that do not override get_quota() return
    None, and detect_all() must propagate that as quota=None (not omit it or error).
    """
    # _AgentStub with quota=None simulates the default protocol behaviour where
    # get_quota() returns None without raising.
    stub = _AgentStub(name="User Managed", quota=None)
    detector = ToolDetector(agents=[stub])

    options = await detector.detect_all()
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is None


async def test_exception_in_get_quota_yields_none() -> None:
    """Exceptions from get_quota() are swallowed and result in quota=None on first failure (no prior success)."""
    stub = _RaisingAgentStub(name="User Managed")
    detector = ToolDetector(agents=[stub])

    options = await detector.detect_all()
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is None


@pytest.mark.timeout(35)
async def test_slow_get_quota_times_out_and_yields_none() -> None:
    """A get_quota() that exceeds 3 seconds results in quota=None on first failure (no prior success).

    detect_all() is allowed to take up to 30s in total (docker detection can
    consume up to 10s); this test only verifies that the quota is None when
    get_quota() blocks longer than the 3-second threshold.
    """
    stub = _SlowAgentStub(name="User Managed")
    detector = ToolDetector(agents=[stub])

    # No outer timeout here — the per-quota 3s timeout is what we're testing.
    options = await detector.detect_all()
    um = next(o for o in options if o.name == "User Managed")

    assert um.available is True
    assert um.quota is None


async def test_quota_cached_between_calls() -> None:
    """A second detect_all() call within the TTL returns the cached quota."""
    call_count = 0

    class _CountingStub:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count
            call_count += 1
            return AgentQuota(balance_usd=10.0)

    detector = ToolDetector(agents=[_CountingStub()])

    await detector.detect_all()
    assert call_count == 1

    await detector.detect_all()
    # Cache should still be fresh — get_quota must not be called again
    assert call_count == 1


async def test_quota_refetched_after_ttl_expiry() -> None:
    """After the cache TTL expires, detect_all() re-invokes get_quota().

    Time is simulated by directly manipulating the cached_at field on the
    _QuotaCacheEntry — no patching or MagicMock required.
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
    await detector.detect_all()
    assert call_count == 1

    # Directly manipulate cached_at to simulate TTL expiry.
    # Active-entry TTL is 60s; setting cached_at 400s in the past makes it stale.
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call must re-invoke get_quota() because the cache is stale
    await detector.detect_all()
    assert call_count == 2


async def test_no_agents_registered_all_quota_none() -> None:
    """When no agents are passed to ToolDetector, all quotas are None."""
    detector = ToolDetector()
    options = await detector.detect_all()

    for option in options:
        assert option.quota is None, (
            f"Agent {option.name!r} should have quota=None when no agents registered"
        )


async def test_detect_all_concurrent_quota_fetch() -> None:
    """asyncio.gather() is used so multiple quota fetches overlap in time.

    We register the same "User Managed" agent under two different stub objects
    — only one can win the name lookup — but we verify the mechanism by
    directly calling _fetch_quota_for_option on a synthetic list of options
    backed by a set of stubs that each sleep 0.5s.  This avoids the variable
    docker-detection latency that makes a wall-clock bound on detect_all()
    unreliable in CI.
    """
    import time

    from orchestrator.runners.types import AgentOption as _AO
    from orchestrator.config.enums import AgentRunnerType

    AGENT_NAMES = ["agent-alpha", "agent-beta", "agent-gamma"]
    SLEEP_S = 0.5

    class _SleepStub:
        def __init__(self, name: str) -> None:
            self.name = name

        def get_quota(self) -> AgentQuota | None:
            time.sleep(SLEEP_S)
            return AgentQuota(balance_usd=1.0)

    stubs = [_SleepStub(n) for n in AGENT_NAMES]
    detector = ToolDetector(agents=stubs)

    fake_options = [
        _AO(agent_type=AgentRunnerType.USER_MANAGED, name=n, available=True) for n in AGENT_NAMES
    ]

    start = time.monotonic()
    quotas = await asyncio.gather(
        *[detector._fetch_quota_for_option(opt) for opt in fake_options]  # pyright: ignore[reportPrivateUsage]
    )
    elapsed = time.monotonic() - start

    # Sequential execution would take ≥ 3 × SLEEP_S = 1.5s.
    # Concurrent execution finishes in ≈ SLEEP_S ≈ 0.5s.
    # Allow generous headroom for CI scheduling jitter.
    assert elapsed < SLEEP_S * 2.5, (
        f"Quota fetches appear sequential (took {elapsed:.2f}s, expected <{SLEEP_S * 2.5:.2f}s)"
    )

    assert all(q is not None and q.balance_usd == 1.0 for q in quotas)


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
    options1 = await detector.detect_all()
    um1 = next(o for o in options1 if o.name == "User Managed")
    assert um1.quota is not None
    assert um1.quota.balance_usd == 42.0
    assert um1.quota.fetched_at is not None

    # Expire the cache so second call attempts a fetch
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call fails — should return stale quota
    options2 = await detector.detect_all()
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
    await detector.detect_all()
    assert call_count == 1

    # Expire cache to trigger fetch
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call fails, sets retry_after
    await detector.detect_all()
    assert call_count == 2

    # Third call: cache is stale but within retry_after backoff — should NOT call get_quota
    cache_entry2 = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry2.cached_at = time.monotonic() - 400  # expire cache again
    # retry_after should still be in the future (set ~300s from now)

    await detector.detect_all()
    assert call_count == 2  # no additional call


async def test_fetched_at_set_on_success() -> None:
    """A successful fetch populates fetched_at as an ISO 8601 string."""
    from datetime import datetime

    stub = _AgentStub(name="User Managed", quota=AgentQuota(balance_usd=5.0))
    detector = ToolDetector(agents=[stub])

    options = await detector.detect_all()
    um = next(o for o in options if o.name == "User Managed")

    assert um.quota is not None
    assert um.quota.fetched_at is not None
    # Verify it parses as ISO 8601
    parsed = datetime.fromisoformat(um.quota.fetched_at)
    assert parsed is not None


async def test_fetched_at_preserved_after_failure() -> None:
    """fetched_at reflects the last success time, not the failure time."""
    call_count = 0
    success_time_before: float = 0

    class _TimedFailStub:
        name = "User Managed"

        def get_quota(self) -> AgentQuota | None:
            nonlocal call_count, success_time_before
            call_count += 1
            if call_count == 1:
                success_time_before = time.time()
                return AgentQuota(balance_usd=7.0)
            raise RuntimeError("rate limited")

    detector = ToolDetector(agents=[_TimedFailStub()])

    # First call succeeds
    options1 = await detector.detect_all()
    um1 = next(o for o in options1 if o.name == "User Managed")
    assert um1.quota is not None
    fetched_at_1 = um1.quota.fetched_at
    assert fetched_at_1 is not None

    # Expire cache
    cache_entry = detector._quota_cache["User Managed"]  # pyright: ignore[reportPrivateUsage]
    cache_entry.cached_at = time.monotonic() - 400

    # Second call fails
    options2 = await detector.detect_all()
    um2 = next(o for o in options2 if o.name == "User Managed")
    assert um2.quota is not None
    # fetched_at should be the same as after the first (successful) call
    assert um2.quota.fetched_at == fetched_at_1
