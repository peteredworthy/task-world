"""Tests for configuration models."""

import pytest

from orchestrator.config.enums import Priority
from orchestrator.config.models import (
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)


def test_requirement_defaults() -> None:
    req = RequirementConfig(id="R1", desc="Test requirement")
    assert req.must is True
    assert req.priority == Priority.CRITICAL


def test_task_with_requirements() -> None:
    task = TaskConfig(
        id="T1",
        title="Test Task",
        task_context="Do something",
        requirements=[
            RequirementConfig(id="R1", desc="Req 1"),
            RequirementConfig(id="R2", desc="Req 2", priority=Priority.NICE),
        ],
    )
    assert len(task.requirements) == 2
    assert task.requirements[1].priority == Priority.NICE


def test_routine_complete() -> None:
    routine = RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Context",
                    ),
                ],
            )
        ],
    )
    assert routine.id == "test-routine"
    assert len(routine.steps) == 1


def test_model_overrides() -> None:
    task = TaskConfig(
        id="T1",
        title="Task",
        task_context="Default context",
        model_overrides={
            "claude-sonnet": {"task_context": "Claude-specific context"},
        },
    )
    assert task.model_overrides is not None
    assert task.model_overrides["claude-sonnet"]["task_context"] == "Claude-specific context"


def test_reject_ref_in_steps() -> None:
    """CRITICAL: ref/use inheritance must be rejected."""
    with pytest.raises(ValueError, match="ref.*not supported|not supported.*ref"):
        RoutineConfig(
            id="test",
            name="Test",
            steps=[{"ref": "some-step"}],  # type: ignore[list-item]
        )


def test_reject_use_in_task() -> None:
    """CRITICAL: ref/use inheritance must be rejected."""
    with pytest.raises(ValueError, match="use.*not supported|not supported.*use"):
        StepConfig(
            id="S1",
            title="Step",
            tasks=[{"use": "some-task"}],  # type: ignore[list-item]
        )


def test_step_with_multiple_tasks() -> None:
    step = StepConfig(
        id="S1",
        title="Step 1",
        tasks=[
            TaskConfig(id="T1", title="Task 1", task_context="Context 1"),
            TaskConfig(id="T2", title="Task 2", task_context="Context 2"),
        ],
    )
    assert len(step.tasks) == 2


def test_step_requires_at_least_one_task() -> None:
    with pytest.raises(ValueError):
        StepConfig(
            id="S1",
            title="Step",
            tasks=[],
        )
