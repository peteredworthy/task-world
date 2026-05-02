"""Unit tests for transition_to_recovering and transition_force_accept."""

from datetime import datetime

from orchestrator.config import TaskStatus
from orchestrator.state.models import Attempt, TaskState
from orchestrator.workflow import (
    transition_force_accept,
    transition_to_recovering,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)
EARLIER = datetime(2026, 1, 1, 11, 0, 0)


def make_task(status: TaskStatus) -> TaskState:
    return TaskState(id="t-1", config_id="T-01", status=status)


def make_attempt(completed_at: datetime | None = None) -> Attempt:
    return Attempt(attempt_num=1, started_at=NOW, completed_at=completed_at)


class TestTransitionToRecovering:
    def test_valid_from_verifying(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        result = transition_to_recovering(task, "scripts crashed")
        assert result.success is True
        assert result.new_status == TaskStatus.RECOVERING
        assert task.status == TaskStatus.RECOVERING

    def test_stores_failure_reason_in_last_attempt(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        task.attempts.append(make_attempt())
        transition_to_recovering(task, "max attempts exceeded")
        assert task.attempts[-1].verifier_comment == "max attempts exceeded"

    def test_invalid_from_building(self) -> None:
        task = make_task(TaskStatus.BUILDING)
        result = transition_to_recovering(task, "irrelevant")
        assert result.success is False
        assert result.new_status == TaskStatus.BUILDING
        assert result.error is not None
        assert "building" in result.error.lower()

    def test_invalid_from_pending(self) -> None:
        task = make_task(TaskStatus.PENDING)
        result = transition_to_recovering(task, "irrelevant")
        assert result.success is False

    def test_invalid_from_completed(self) -> None:
        task = make_task(TaskStatus.COMPLETED)
        result = transition_to_recovering(task, "irrelevant")
        assert result.success is False

    def test_no_attempts_transitions_successfully(self) -> None:
        """failure_reason is silently not stored when there are no attempts."""
        task = make_task(TaskStatus.VERIFYING)
        assert len(task.attempts) == 0
        result = transition_to_recovering(task, "some reason")
        assert result.success is True
        assert task.status == TaskStatus.RECOVERING


class TestTransitionForceAccept:
    def test_valid_from_failed(self) -> None:
        task = make_task(TaskStatus.FAILED)
        result = transition_force_accept(task, NOW)
        assert result.success is True
        assert result.new_status == TaskStatus.COMPLETED
        assert task.status == TaskStatus.COMPLETED

    def test_valid_from_building(self) -> None:
        task = make_task(TaskStatus.BUILDING)
        result = transition_force_accept(task, NOW)
        assert result.success is True
        assert task.status == TaskStatus.COMPLETED

    def test_valid_from_verifying(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        result = transition_force_accept(task, NOW)
        assert result.success is True
        assert task.status == TaskStatus.COMPLETED

    def test_sets_outcome_passed(self) -> None:
        task = make_task(TaskStatus.FAILED)
        task.attempts.append(make_attempt())
        transition_force_accept(task, NOW)
        assert task.attempts[-1].outcome == "passed"

    def test_sets_completed_at(self) -> None:
        task = make_task(TaskStatus.FAILED)
        task.attempts.append(make_attempt(completed_at=None))
        transition_force_accept(task, NOW)
        assert task.attempts[-1].completed_at == NOW

    def test_does_not_overwrite_existing_completed_at(self) -> None:
        task = make_task(TaskStatus.FAILED)
        task.attempts.append(make_attempt(completed_at=EARLIER))
        transition_force_accept(task, NOW)
        assert task.attempts[-1].completed_at == EARLIER

    def test_invalid_from_pending(self) -> None:
        task = make_task(TaskStatus.PENDING)
        result = transition_force_accept(task, NOW)
        assert result.success is False
        assert result.new_status == TaskStatus.PENDING
        assert result.error is not None

    def test_invalid_from_completed(self) -> None:
        task = make_task(TaskStatus.COMPLETED)
        result = transition_force_accept(task, NOW)
        assert result.success is False

    def test_invalid_from_recovering(self) -> None:
        task = make_task(TaskStatus.RECOVERING)
        result = transition_force_accept(task, NOW)
        assert result.success is False
