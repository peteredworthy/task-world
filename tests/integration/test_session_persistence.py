"""Integration tests for session state persistence."""

import json

from pathlib import Path

import pytest

from orchestrator.config.enums import AgentRunnerType
from orchestrator.state.models import Run, StepState
from orchestrator.state.session import SessionStateManager


@pytest.fixture
def persist_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "session.json"


async def test_save_and_load(persist_path: Path) -> None:
    # Create and save
    manager1 = SessionStateManager(persist_path)
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        steps=[StepState(id="s1", config_id="S-01", tasks=[])],
    )
    manager1.add_run(run)
    await manager1.save()

    # Load in new manager
    manager2 = SessionStateManager(persist_path)
    await manager2.load()

    retrieved = manager2.get_run("run-1")
    assert retrieved.id == "run-1"
    assert retrieved.repo_name == "proj-1"
    assert len(retrieved.steps) == 1


async def test_save_creates_directory(tmp_path: Path) -> None:
    deep_path = tmp_path / "a" / "b" / "c" / "session.json"
    manager = SessionStateManager(deep_path)
    manager.add_run(Run(id="r1", repo_name="p1"))
    await manager.save()

    assert deep_path.exists()


async def test_load_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("{}")

    manager = SessionStateManager(path)
    await manager.load()

    assert len(manager.list_runs()) == 0


async def test_load_nonexistent_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.json"
    manager = SessionStateManager(path)
    await manager.load()  # Should not raise
    assert len(manager.list_runs()) == 0


async def test_save_without_persist_path() -> None:
    manager = SessionStateManager()  # No persist path
    manager.add_run(Run(id="r1", repo_name="p1"))
    await manager.save()  # Should be a no-op, not raise


async def test_load_normalizes_historical_claude_sdk_without_rewriting_snapshot(
    persist_path: Path,
) -> None:
    raw_snapshot = {
        "runs": {
            "run-legacy": {
                "id": "run-legacy",
                "repo_name": "project",
                "agent_runner_type": "claude_sdk",
                "steps": [
                    {
                        "id": "step-1",
                        "config_id": "S-01",
                        "tasks": [
                            {
                                "id": "task-1",
                                "config_id": "T-01",
                                "attempts": [
                                    {
                                        "id": "attempt-1",
                                        "attempt_num": 1,
                                        "agent_runner_type": "claude_sdk",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    }
    persist_path.parent.mkdir(parents=True)
    persist_path.write_text(json.dumps(raw_snapshot, indent=2))
    original_bytes = persist_path.read_bytes()

    manager = SessionStateManager(persist_path)
    await manager.load()

    run = manager.get_run("run-legacy")
    assert run.agent_runner_type is AgentRunnerType.RETIRED
    assert run.steps[0].tasks[0].attempts[0].agent_runner_type is AgentRunnerType.RETIRED
    assert persist_path.read_bytes() == original_bytes
