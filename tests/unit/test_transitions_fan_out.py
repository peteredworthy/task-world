"""Unit tests for FAN_OUT_RUNNING transitions and step completion with children."""

from orchestrator.config import TaskStatus
from orchestrator.state.models import StepState, TaskState
from orchestrator.workflow import (
    VALID_TRANSITIONS,
    is_step_complete,
    step_has_failure,
)


class TestFanOutRunningTransitions:
    def test_fan_out_running_to_verifying(self) -> None:
        """FAN_OUT_RUNNING -> VERIFYING is a valid transition."""
        assert TaskStatus.VERIFYING in VALID_TRANSITIONS[TaskStatus.FAN_OUT_RUNNING]

    def test_fan_out_running_to_completed(self) -> None:
        """FAN_OUT_RUNNING -> COMPLETED is a valid transition."""
        assert TaskStatus.COMPLETED in VALID_TRANSITIONS[TaskStatus.FAN_OUT_RUNNING]

    def test_fan_out_running_to_failed(self) -> None:
        """FAN_OUT_RUNNING -> FAILED is a valid transition."""
        assert TaskStatus.FAILED in VALID_TRANSITIONS[TaskStatus.FAN_OUT_RUNNING]

    def test_pending_to_fan_out_running(self) -> None:
        """PENDING -> FAN_OUT_RUNNING is a valid transition."""
        assert TaskStatus.FAN_OUT_RUNNING in VALID_TRANSITIONS[TaskStatus.PENDING]


class TestStepCompleteSkipsChildren:
    def test_is_step_complete_skips_children(self) -> None:
        """Step completion should only consider top-level (non-child) tasks.

        A step with a parent task in COMPLETED and child tasks in PENDING
        should be considered complete because children are managed by the
        fan-out executor.
        """
        parent = TaskState(
            id="parent-1",
            config_id="T-02",
            status=TaskStatus.COMPLETED,
            parent_task_id=None,
        )
        child1 = TaskState(
            id="child-1",
            config_id="T-02_fan_0",
            status=TaskStatus.PENDING,
            parent_task_id="parent-1",
            fan_out_index=0,
        )
        child2 = TaskState(
            id="child-2",
            config_id="T-02_fan_1",
            status=TaskStatus.PENDING,
            parent_task_id="parent-1",
            fan_out_index=1,
        )
        step = StepState(
            id="step-1",
            config_id="S-02",
            tasks=[parent, child1, child2],
        )
        assert is_step_complete(step) is True

    def test_step_has_failure_skips_children(self) -> None:
        """step_has_failure should only consider top-level (non-child) tasks.

        A step where a child has FAILED but the parent is still FAN_OUT_RUNNING
        should NOT be reported as a step-level failure because the parent
        is still managing execution.
        """
        parent = TaskState(
            id="parent-1",
            config_id="T-02",
            status=TaskStatus.FAN_OUT_RUNNING,
            parent_task_id=None,
        )
        child_failed = TaskState(
            id="child-1",
            config_id="T-02_fan_0",
            status=TaskStatus.FAILED,
            parent_task_id="parent-1",
            fan_out_index=0,
        )
        child_ok = TaskState(
            id="child-2",
            config_id="T-02_fan_1",
            status=TaskStatus.COMPLETED,
            parent_task_id="parent-1",
            fan_out_index=1,
        )
        step = StepState(
            id="step-1",
            config_id="S-02",
            tasks=[parent, child_failed, child_ok],
        )
        # Parent is FAN_OUT_RUNNING (non-terminal), so step is not complete
        assert is_step_complete(step) is False
        # Even though a child failed, only top-level tasks count for step failure
        assert step_has_failure(step) is False

    def test_is_step_complete_fan_out_running_not_terminal(self) -> None:
        """FAN_OUT_RUNNING is non-terminal -- a step with only a FAN_OUT_RUNNING
        parent should NOT be considered complete."""
        parent = TaskState(
            id="parent-1",
            config_id="T-02",
            status=TaskStatus.FAN_OUT_RUNNING,
            parent_task_id=None,
        )
        step = StepState(
            id="step-1",
            config_id="S-02",
            tasks=[parent],
        )
        assert is_step_complete(step) is False
