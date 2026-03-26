"""Unit tests for human interaction transition functions."""

from datetime import datetime, timezone

import pytest

from orchestrator.config import ChecklistStatus, Priority, TaskStatus
from orchestrator.state.models import Attempt, ChecklistItem, TaskState
from orchestrator.workflow import (
    transition_from_approval,
    transition_from_clarification,
    transition_to_pending_approval,
    transition_to_pending_clarification,
)


@pytest.fixture
def now() -> datetime:
    """Fixed timestamp for deterministic testing."""
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def building_task() -> TaskState:
    """A task in BUILDING state."""
    return TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.BUILDING,
        max_attempts=3,
        current_attempt=1,
        attempts=[
            Attempt(attempt_num=1, started_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc))
        ],
        checklist=[
            ChecklistItem(
                req_id="req1",
                desc="Requirement 1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.DONE,
            )
        ],
    )


@pytest.fixture
def verifying_task() -> TaskState:
    """A task in VERIFYING state."""
    return TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.VERIFYING,
        max_attempts=3,
        current_attempt=1,
        attempts=[
            Attempt(attempt_num=1, started_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc))
        ],
        checklist=[
            ChecklistItem(
                req_id="req1",
                desc="Requirement 1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.DONE,
            )
        ],
    )


# --- Clarification Transitions ---


def test_transition_to_pending_clarification_from_building(building_task: TaskState):
    """Can transition to PENDING_USER_ACTION for clarification from BUILDING."""
    result = transition_to_pending_clarification(building_task, "clarification-123")

    assert result.success is True
    assert result.new_status == TaskStatus.PENDING_USER_ACTION
    assert building_task.status == TaskStatus.PENDING_USER_ACTION
    assert building_task.pending_action_type == "clarification"
    assert building_task.pending_clarification_id == "clarification-123"


def test_transition_to_pending_clarification_from_invalid_status(verifying_task: TaskState):
    """Cannot request clarification from states other than BUILDING."""
    result = transition_to_pending_clarification(verifying_task, "clarification-123")

    assert result.success is False
    assert result.error == "Cannot request clarification from verifying"
    assert verifying_task.status == TaskStatus.VERIFYING  # Unchanged
    assert verifying_task.pending_action_type is None
    assert verifying_task.pending_clarification_id is None


def test_transition_from_clarification_back_to_building():
    """Can resume from clarification back to BUILDING."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="clarification",
        pending_clarification_id="clarification-123",
        max_attempts=3,
        current_attempt=1,
    )

    result = transition_from_clarification(task)

    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING
    assert task.status == TaskStatus.BUILDING
    assert task.pending_action_type is None
    assert task.pending_clarification_id is None


def test_transition_from_clarification_invalid_status(building_task: TaskState):
    """Cannot resume from clarification if not in PENDING_USER_ACTION."""
    result = transition_from_clarification(building_task)

    assert result.success is False
    assert result.error == "Cannot resume from building"
    assert building_task.status == TaskStatus.BUILDING  # Unchanged


def test_transition_from_clarification_wrong_action_type():
    """Cannot resume from clarification if pending_action_type is not 'clarification'."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="approval",
        max_attempts=3,
        current_attempt=1,
    )

    result = transition_from_clarification(task)

    assert result.success is False
    assert result.error == "Not a clarification action: approval"
    assert task.status == TaskStatus.PENDING_USER_ACTION  # Unchanged


# --- Approval Transitions ---


def test_transition_to_pending_approval_from_verifying(verifying_task: TaskState):
    """Can transition to PENDING_USER_ACTION for approval from VERIFYING."""
    result = transition_to_pending_approval(verifying_task)

    assert result.success is True
    assert result.new_status == TaskStatus.PENDING_USER_ACTION
    assert verifying_task.status == TaskStatus.PENDING_USER_ACTION
    assert verifying_task.pending_action_type == "approval"


def test_transition_to_pending_approval_from_invalid_status(building_task: TaskState):
    """Cannot request approval from states other than VERIFYING."""
    result = transition_to_pending_approval(building_task)

    assert result.success is False
    assert result.error == "Cannot await approval from building"
    assert building_task.status == TaskStatus.BUILDING  # Unchanged
    assert building_task.pending_action_type is None


def test_transition_from_approval_approved(now: datetime):
    """Approving completes the task."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="approval",
        max_attempts=3,
        current_attempt=1,
        attempts=[
            Attempt(attempt_num=1, started_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc))
        ],
    )

    result = transition_from_approval(task, approved=True, now=now)

    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert task.pending_action_type is None
    assert task.attempts[-1].completed_at == now
    assert task.attempts[-1].outcome == "passed"


def test_transition_from_approval_rejected_starts_new_attempt(now: datetime):
    """Rejecting starts a new attempt back in BUILDING."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="approval",
        max_attempts=3,
        current_attempt=1,
        attempts=[
            Attempt(attempt_num=1, started_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc))
        ],
    )

    result = transition_from_approval(task, approved=False, now=now)

    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING
    assert task.status == TaskStatus.BUILDING
    assert task.pending_action_type is None
    assert task.current_attempt == 2
    assert len(task.attempts) == 2
    assert task.attempts[1].attempt_num == 2
    assert task.attempts[1].started_at == now


def test_transition_from_approval_rejected_at_max_attempts_fails(now: datetime):
    """Rejecting at max attempts causes FAILED status."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="approval",
        max_attempts=3,
        current_attempt=3,  # Already at max
        attempts=[
            Attempt(attempt_num=1, started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)),
            Attempt(attempt_num=2, started_at=datetime(2026, 1, 1, 10, 30, 0, tzinfo=timezone.utc)),
            Attempt(attempt_num=3, started_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)),
        ],
    )

    result = transition_from_approval(task, approved=False, now=now)

    assert result.success is True
    assert result.new_status == TaskStatus.FAILED
    assert result.error == "Max attempts (3) reached"
    assert task.status == TaskStatus.FAILED
    assert task.pending_action_type is None
    assert task.attempts[-1].completed_at == now
    assert task.attempts[-1].outcome == "failed"


def test_transition_from_approval_invalid_status(building_task: TaskState, now: datetime):
    """Cannot complete approval if not in PENDING_USER_ACTION."""
    result = transition_from_approval(building_task, approved=True, now=now)

    assert result.success is False
    assert result.error == "Cannot complete approval from building"
    assert building_task.status == TaskStatus.BUILDING  # Unchanged


def test_transition_from_approval_wrong_action_type(now: datetime):
    """Cannot complete approval if pending_action_type is not 'approval'."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="clarification",
        pending_clarification_id="clarification-123",
        max_attempts=3,
        current_attempt=1,
    )

    result = transition_from_approval(task, approved=True, now=now)

    assert result.success is False
    assert result.error == "Not an approval action: clarification"
    assert task.status == TaskStatus.PENDING_USER_ACTION  # Unchanged


# --- Edge Cases ---


def test_transition_from_approval_rejected_with_no_attempts(now: datetime):
    """Rejecting with no attempts creates the first attempt."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="approval",
        max_attempts=3,
        current_attempt=0,
        attempts=[],
    )

    result = transition_from_approval(task, approved=False, now=now)

    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING
    assert task.status == TaskStatus.BUILDING
    assert task.current_attempt == 1
    assert len(task.attempts) == 1
    assert task.attempts[0].attempt_num == 1
    assert task.attempts[0].started_at == now


def test_transition_from_approval_approved_with_no_attempts(now: datetime):
    """Approving with no attempts still completes successfully."""
    task = TaskState(
        config_id="task-1",
        title="Test Task",
        status=TaskStatus.PENDING_USER_ACTION,
        pending_action_type="approval",
        max_attempts=3,
        current_attempt=0,
        attempts=[],
    )

    result = transition_from_approval(task, approved=True, now=now)

    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert len(task.attempts) == 0  # No attempt to mark as passed
