"""Deterministic clock and ID generator for graph scenario tests."""

from datetime import UTC, datetime, timedelta


class FakeClock:
    """Clock with a fixed epoch that only moves when advanced."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIdGenerator:
    """Simple deterministic ID source."""

    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value
