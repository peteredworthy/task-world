"""Shared test fixtures and configuration."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

from orchestrator.workflow import WorkflowEvent

# Load .env before test collection so that skipif conditions
# (e.g. os.getenv("OPENAI_API_KEY")) see the values.
load_dotenv()


@pytest.fixture(autouse=True)
def _isolate_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate git operations from the project repo and pre-commit state.

    Under pytest-xdist (especially inside pre-commit hooks), git env vars
    like ``GIT_INDEX_FILE``, ``GIT_DIR``, ``GIT_AUTHOR_NAME`` etc. leak
    into subprocess calls, causing index errors or wrong author names.
    Clearing them ensures each test's temp repo is fully self-contained.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for var in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)


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
