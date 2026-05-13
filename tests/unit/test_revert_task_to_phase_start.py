"""Tests for WorkflowService._revert_task_to_phase_start.

Covers the two independent code paths (BUILDING vs VERIFYING) and the
git-checkout decision tree (needs 2 attempts + worktree + start_commit).
"""

from datetime import datetime
from typing import Any, cast

from orchestrator.config.enums import ChecklistStatus, Priority, TaskStatus
from orchestrator.state.models import Attempt, ChecklistItem, Run, TaskState
from orchestrator.workflow.service import WorkflowService

NOW = datetime(2026, 1, 1, 12, 0, 0)


class DummySession:
    def get_bind(self) -> None:
        return None


class RecordingWorkflowService(WorkflowService):
    def __init__(self) -> None:
        super().__init__(session=cast(Any, DummySession()))
        self.checkouts: list[tuple[str, str, str]] = []

    def _checkout_on_branch(self, worktree_path: str, run_id: str, commit_sha: str) -> bool:
        self.checkouts.append((worktree_path, run_id, commit_sha))
        return True


def _service() -> RecordingWorkflowService:
    return RecordingWorkflowService()


def _run(worktree_path: str | None = None) -> Run:
    return Run(repo_name="test-repo", worktree_path=worktree_path)


def _task(status: TaskStatus, n_attempts: int = 0, start_commit: str | None = None) -> TaskState:
    task = TaskState(id="t-1", config_id="T-01", status=status)
    for i in range(n_attempts):
        task.attempts.append(Attempt(attempt_num=i + 1, started_at=NOW, start_commit=start_commit))
        task.current_attempt = i + 1
    return task


def _checklist(n: int = 2) -> list[ChecklistItem]:
    return [
        ChecklistItem(
            req_id=f"R-{i}",
            desc="desc",
            priority=Priority.EXPECTED,
            status=ChecklistStatus.DONE,
            note="builder note",
            grade="pass",
            grade_reason="looks good",
        )
        for i in range(n)
    ]


class TestRevertBuilding:
    def test_closes_current_attempt_with_reverted_outcome(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1)
        svc._revert_task_to_phase_start(task, _run(), NOW)
        assert task.attempts[0].outcome == "reverted"
        assert task.attempts[0].completed_at == NOW

    def test_no_crash_when_no_existing_attempt(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=0)
        svc._revert_task_to_phase_start(task, _run(), NOW)
        assert len(task.attempts) == 1  # new attempt created by transition_to_building

    def test_resets_checklist_items_to_open(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1)
        task.checklist = _checklist()
        svc._revert_task_to_phase_start(task, _run(), NOW)
        for item in task.checklist:
            assert item.status == ChecklistStatus.OPEN
            assert item.note is None

    def test_creates_new_building_attempt(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1)
        svc._revert_task_to_phase_start(task, _run(), NOW)
        assert len(task.attempts) == 2
        assert task.status == TaskStatus.BUILDING

    def test_new_attempt_inherits_previous_start_commit(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1, start_commit="abc123")
        svc._revert_task_to_phase_start(task, _run(), NOW)
        assert task.attempts[1].start_commit == "abc123"

    def test_checkout_called_when_worktree_and_start_commit_present(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1, start_commit="abc123")
        run = _run(worktree_path="/some/worktree")
        svc._revert_task_to_phase_start(task, run, NOW)
        assert svc.checkouts == [("/some/worktree", run.id, "abc123")]

    def test_checkout_not_called_without_worktree(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1, start_commit="abc123")
        svc._revert_task_to_phase_start(task, _run(worktree_path=None), NOW)
        assert svc.checkouts == []

    def test_checkout_not_called_without_previous_start_commit(self) -> None:
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=1, start_commit=None)
        svc._revert_task_to_phase_start(task, _run(worktree_path="/some/worktree"), NOW)
        assert svc.checkouts == []

    def test_checkout_not_called_on_first_attempt(self) -> None:
        # With 0 existing attempts: transition_to_building creates attempt 1.
        # len(attempts) == 1 < 2, so no "previous" attempt to restore from.
        svc = _service()
        task = _task(TaskStatus.BUILDING, n_attempts=0)
        svc._revert_task_to_phase_start(task, _run(worktree_path="/worktree"), NOW)
        assert svc.checkouts == []


class TestRevertVerifying:
    def test_closes_current_attempt_with_reverted_outcome(self) -> None:
        svc = _service()
        task = _task(TaskStatus.VERIFYING, n_attempts=1)
        svc._revert_task_to_phase_start(task, _run(), NOW)
        assert task.attempts[0].outcome == "reverted"
        assert task.attempts[0].completed_at == NOW

    def test_clears_grades_but_preserves_checklist_status_and_note(self) -> None:
        # Verifier re-run should not undo the builder's checklist work.
        svc = _service()
        task = _task(TaskStatus.VERIFYING, n_attempts=1)
        task.checklist = _checklist()
        svc._revert_task_to_phase_start(task, _run(), NOW)
        for item in task.checklist:
            assert item.grade is None
            assert item.grade_reason is None
            assert item.status == ChecklistStatus.DONE  # preserved
            assert item.note == "builder note"  # preserved

    def test_creates_new_attempt_with_incremented_number(self) -> None:
        svc = _service()
        task = _task(TaskStatus.VERIFYING, n_attempts=1)
        svc._revert_task_to_phase_start(task, _run(), NOW)
        assert len(task.attempts) == 2
        assert task.attempts[-1].attempt_num == 2

    def test_checkout_never_called_for_verifying(self) -> None:
        # Worktree is already at end_commit from the builder's submit; no revert needed.
        svc = _service()
        task = _task(TaskStatus.VERIFYING, n_attempts=2, start_commit="abc123")
        svc._revert_task_to_phase_start(task, _run(worktree_path="/worktree"), NOW)
        assert svc.checkouts == []
