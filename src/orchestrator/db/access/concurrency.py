"""Swappable concurrency strategy for event-store append operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class ConcurrencyConflictError(Exception):
    """Raised when optimistic concurrency retries are exhausted."""


class ConcurrencyStrategy:
    """Protocol: wraps an async operation with conflict-retry logic."""

    async def execute_with_retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        raise NotImplementedError


class RetryWithBackoff(ConcurrencyStrategy):
    """SQLite strategy: retry up to max_attempts with exponential backoff.

    base_delay_ms is the initial delay in milliseconds; each retry doubles it.
    Swap this for PostgreSQL advisory-lock or serializable-transaction strategy
    without changing SqliteEventStore.

    The optional _sleep_fn parameter allows injecting a test-time sleep
    function without patching asyncio.sleep.
    """

    def __init__(
        self,
        max_attempts: int = 10,
        base_delay_ms: float = 10.0,
        _sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay_ms = base_delay_ms
        self._sleep_fn = _sleep_fn or asyncio.sleep

    async def execute_with_retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        delay = self.base_delay_ms / 1000.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                if not _is_version_conflict(exc):
                    raise  # re-raise original — not a concurrency conflict; do NOT wrap in ConcurrencyConflictError
                if attempt == self.max_attempts:
                    raise ConcurrencyConflictError(
                        f"Version conflict unresolved after {attempt} attempt(s)"
                    ) from exc
                await self._sleep_fn(delay)
                delay *= 2
        raise ConcurrencyConflictError("unreachable")  # pragma: no cover


def _is_version_conflict(exc: Exception) -> bool:
    """Return True if the exception is a retriable SQLite write conflict.

    Handles both UNIQUE constraint violations (two sessions assigned the same
    optimistic version) and SQLITE_BUSY "database is locked" errors (a session
    couldn't acquire the write lock within SQLite's built-in timeout).
    """
    msg = str(exc).lower()
    if "unique" in msg and ("aggregate_id" in msg or "uq_events_v2" in msg):
        return True
    if "database is locked" in msg:
        return True
    return False
