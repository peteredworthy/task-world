"""Tests for SessionStateManager in-memory operations."""

import pytest

from orchestrator.config import ChecklistStatus, Priority
from orchestrator.state.errors import (
    ChecklistItemNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.state.session import SessionStateManager


@pytest.fixture
def manager() -> SessionStateManager:
    return SessionStateManager()  # Memory-only


@pytest.fixture
def sample_run() -> Run:
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Requirement 1",
                                priority=Priority.CRITICAL,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def test_add_and_get_run(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    retrieved = manager.get_run("run-1")
    assert retrieved.id == "run-1"


def test_get_nonexistent_run(manager: SessionStateManager) -> None:
    with pytest.raises(RunNotFoundError):
        manager.get_run("nonexistent")


def test_list_runs(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    runs = manager.list_runs()
    assert len(runs) == 1


def test_get_task(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    task = manager.get_task("run-1", "task-1")
    assert task.config_id == "T-01"


def test_get_nonexistent_task(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    with pytest.raises(TaskNotFoundError):
        manager.get_task("run-1", "nonexistent")


def test_update_checklist_item(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    item = manager.update_checklist_item(
        run_id="run-1",
        task_id="task-1",
        req_id="R1",
        status=ChecklistStatus.DONE,
        note="Completed successfully",
    )
    assert item.status == ChecklistStatus.DONE
    assert item.note == "Completed successfully"


def test_delete_run(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    manager.delete_run("run-1")
    with pytest.raises(RunNotFoundError):
        manager.get_run("run-1")


def test_delete_nonexistent_run(manager: SessionStateManager) -> None:
    with pytest.raises(RunNotFoundError):
        manager.delete_run("nonexistent")


def test_update_nonexistent_run(manager: SessionStateManager, sample_run: Run) -> None:
    with pytest.raises(RunNotFoundError):
        manager.update_run(sample_run)


def test_update_checklist_nonexistent_req(manager: SessionStateManager, sample_run: Run) -> None:
    manager.add_run(sample_run)
    with pytest.raises(ChecklistItemNotFoundError):
        manager.update_checklist_item(
            run_id="run-1",
            task_id="task-1",
            req_id="NONEXISTENT",
            status=ChecklistStatus.DONE,
        )
