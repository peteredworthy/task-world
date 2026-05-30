"""Unit tests for ConcurrencyStrategy and RetryWithBackoff."""

from __future__ import annotations

import pytest

from orchestrator.db import (
    ConcurrencyConflictError,
    RetryWithBackoff,
)


def _make_conflict_error() -> Exception:
    """Return a fake UNIQUE constraint violation matching _is_version_conflict."""
    return Exception(
        "UNIQUE constraint failed: events_v2.aggregate_id, uq_events_v2_aggregate_version"
    )


async def test_retry_succeeds_on_second_attempt() -> None:
    call_count = 0

    async def operation() -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_conflict_error()
        return "ok"

    strategy = RetryWithBackoff(max_attempts=3, base_delay_ms=0.0)
    result = await strategy.execute_with_retry(operation)

    assert result == "ok"
    assert call_count == 2


async def test_retry_exhausted_raises() -> None:
    call_count = 0

    async def always_conflict() -> str:
        nonlocal call_count
        call_count += 1
        raise _make_conflict_error()

    strategy = RetryWithBackoff(max_attempts=3, base_delay_ms=0.0)

    with pytest.raises(ConcurrencyConflictError):
        await strategy.execute_with_retry(always_conflict)

    assert call_count == 3


async def test_non_conflict_error_not_retried() -> None:
    call_count = 0

    async def raises_value_error() -> str:
        nonlocal call_count
        call_count += 1
        raise ValueError("something else went wrong")

    strategy = RetryWithBackoff(max_attempts=3, base_delay_ms=0.0)

    with pytest.raises(ValueError, match="something else went wrong"):
        await strategy.execute_with_retry(raises_value_error)

    assert call_count == 1


async def test_backoff_timing() -> None:
    """Sleep is called with exponentially increasing delays on successive retries."""
    sleep_calls: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    call_count = 0

    async def always_conflict() -> str:
        nonlocal call_count
        call_count += 1
        raise _make_conflict_error()

    strategy = RetryWithBackoff(max_attempts=3, base_delay_ms=10.0, _sleep_fn=record_sleep)

    with pytest.raises(ConcurrencyConflictError):
        await strategy.execute_with_retry(always_conflict)

    # 3 attempts → 2 sleeps (sleep after attempt 1 and 2, not after last)
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(0.010)  # 10ms
    assert sleep_calls[1] == pytest.approx(0.020)  # 20ms (doubled)


async def test_non_conflict_error_not_wrapped_in_concurrency_error() -> None:
    """Non-conflict exceptions must not be wrapped in ConcurrencyConflictError."""

    async def raises_runtime_error() -> str:
        raise RuntimeError("db connection lost")

    strategy = RetryWithBackoff(max_attempts=3, base_delay_ms=0.0)

    with pytest.raises(RuntimeError, match="db connection lost"):
        await strategy.execute_with_retry(raises_runtime_error)
