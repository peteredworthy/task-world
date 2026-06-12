"""Shared test fixtures and configuration."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from dotenv import load_dotenv

if TYPE_CHECKING:
    from orchestrator.workflow import WorkflowEvent

# Load .env before test collection so that skipif conditions
# (e.g. os.getenv("OPENAI_API_KEY")) see the values.
load_dotenv()


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Return optimal worker count for this machine.

    pytest-xdist's -n auto uses cpu_count() workers, which on a 10-CPU
    machine spawns 10 workers + 1 controller = 11 processes — causing CPU
    over-subscription and ~1.5s overhead from context switching.
    Using cpu_count - 2 keeps one CPU free for the controller and OS,
    improving throughput by ~1.5s on a 10-CPU M1 Mac.
    """
    return max(1, multiprocessing.cpu_count() - 2)


@pytest.fixture(autouse=True, scope="session")
def _isolate_git_session_path() -> Generator[None, None, None]:
    """Ensure tests resolve to a real git binary instead of the wrapper.

    A project-installed git wrapper is present in PATH and blocks `git init` in
    test repos during local execution. Remove it for the full test run and keep
    standard system locations available.
    """
    previous_path = os.environ.get("PATH")
    path_entries = [
        path
        for path in os.environ.get("PATH", "").split(os.pathsep)
        if path and "orchestrator-git-wrapper-bin" not in path
    ]
    for required in ("/usr/bin", "/usr/local/bin", "/bin"):
        if required not in path_entries:
            path_entries.append(required)
    os.environ["PATH"] = os.pathsep.join(path_entries)
    try:
        yield
    finally:
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path


@pytest.fixture(autouse=True)
def _isolate_git(tmp_path: Path) -> Generator[None, None, None]:
    """Isolate git operations from the project repo and pre-commit state.

    Under pytest-xdist (especially inside pre-commit hooks), git env vars
    like ``GIT_INDEX_FILE``, ``GIT_DIR``, ``GIT_AUTHOR_NAME`` etc. leak
    into subprocess calls, causing index errors or wrong author names.
    Clearing them ensures each test's temp repo is fully self-contained.
    """
    vars_to_restore = (
        "GIT_CEILING_DIRECTORIES",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    )
    previous = {name: os.environ.get(name) for name in vars_to_restore}
    previous["PATH"] = os.environ.get("PATH")
    previous["ORCHESTRATOR_RUN_WORKTREE"] = os.environ.get("ORCHESTRATOR_RUN_WORKTREE")
    previous["ORCHESTRATOR_RUN_BRANCH"] = os.environ.get("ORCHESTRATOR_RUN_BRANCH")

    path_entries = [
        path
        for path in os.environ.get("PATH", "").split(os.pathsep)
        if path and "orchestrator-git-wrapper-bin" not in path
    ]
    if "/usr/bin" not in path_entries:
        path_entries.append("/usr/bin")
    if "/usr/local/bin" not in path_entries:
        path_entries.append("/usr/local/bin")
    if "/bin" not in path_entries:
        path_entries.append("/bin")
    os.environ["PATH"] = os.pathsep.join(path_entries)

    os.environ.pop("ORCHESTRATOR_RUN_WORKTREE", None)
    os.environ.pop("ORCHESTRATOR_RUN_BRANCH", None)
    os.environ["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    for var in vars_to_restore:
        os.environ.pop(var, None)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                if name == "PATH":
                    os.environ.pop(name, None)
                else:
                    os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ---------------------------------------------------------------------------
# --run-slow / --run-e2e flags: skip expensive tests unless explicitly opted in
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.slow (real LLM agents, costs money)",
    )
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.e2e (full process/network workflows)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Let --run-slow/--run-e2e relax the default marker expression."""
    default_markexpr = "not slow and not e2e"
    if config.option.markexpr != default_markexpr:
        return

    run_slow = config.getoption("--run-slow")
    run_e2e = config.getoption("--run-e2e")
    if run_slow and run_e2e:
        config.option.markexpr = ""
    elif run_slow:
        config.option.markexpr = "not e2e"
    elif run_e2e:
        config.option.markexpr = "not slow"


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """Avoid importing split-out expensive suites unless explicitly requested."""
    tests_root = Path(str(config.rootpath)).resolve() / "tests"
    try:
        relative = collection_path.resolve().relative_to(tests_root)
    except ValueError:
        return False

    if not relative.parts:
        return False
    suite = relative.parts[0]
    if suite == "slow" and not config.getoption("--run-slow"):
        return True
    if suite == "e2e" and not config.getoption("--run-e2e"):
        return True
    return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_slow = pytest.mark.skip(reason="needs --run-slow to run")
    skip_e2e = pytest.mark.skip(reason="needs --run-e2e to run")
    for item in items:
        if "slow" in item.keywords and not config.getoption("--run-slow"):
            item.add_marker(skip_slow)
        if "e2e" in item.keywords and not config.getoption("--run-e2e"):
            item.add_marker(skip_e2e)


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
