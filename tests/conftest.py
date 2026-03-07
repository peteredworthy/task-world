"""Shared test fixtures and configuration."""

from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv

from orchestrator.workflow.events import WorkflowEvent

# Load .env before test collection so that skipif conditions
# (e.g. os.getenv("OPENAI_API_KEY")) see the values.
load_dotenv()


# ---------------------------------------------------------------------------
# --run-slow flag: skip @pytest.mark.slow tests unless explicitly opted in
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.slow (real LLM agents, costs money)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="needs --run-slow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


class FakeClock:
    """Deterministic clock for testing."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


class CollectingEmitter:
    """Event emitter that collects events for assertion."""

    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def emit(self, event: WorkflowEvent) -> None:
        self.events.append(event)


@pytest.fixture
def fake_clock() -> FakeClock:
    """Fake clock for deterministic tests."""
    return FakeClock()
