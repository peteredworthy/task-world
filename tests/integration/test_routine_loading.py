"""Integration tests for routine loading from YAML fixtures."""

from pathlib import Path

import pytest

from orchestrator.config import Priority, RoutineValidationError, load_routine_from_path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


def test_load_simple_routine() -> None:
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
    assert routine.id == "simple-routine"
    assert len(routine.steps) == 1
    task = routine.steps[0].tasks[0]
    assert task.id == "T-01"


def test_load_complete_routine() -> None:
    routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
    assert routine.id == "complete-routine"
    assert len(routine.inputs) == 2
    assert routine.inputs[0].required is True
    assert routine.inputs[1].default == "main"

    # Step 1: Planning (single task)
    assert len(routine.steps) == 2
    task = routine.steps[0].tasks[0]
    assert task.model_overrides is not None
    assert "claude-sonnet" in task.model_overrides
    assert task.requirements[0].priority == Priority.CRITICAL
    assert len(task.auto_verify.items) == 1
    assert task.retry.max_attempts == 3

    # Step 2: Implementation (multiple tasks)
    step2 = routine.steps[1]
    assert step2.id == "S-02"
    assert step2.step_context == "Implement the feature"
    assert len(step2.tasks) == 2
    assert step2.tasks[0].id == "T-02"
    assert step2.tasks[0].retry.max_attempts == 2
    assert len(step2.tasks[0].requirements) == 3
    assert step2.tasks[0].requirements[2].priority == Priority.NICE
    assert step2.tasks[1].id == "T-03"
    assert len(step2.tasks[1].auto_verify.items) == 1


def test_reject_ref_inheritance() -> None:
    """CRITICAL: Files with ref/use must be rejected."""
    with pytest.raises((RoutineValidationError, ValueError)):
        load_routine_from_path(FIXTURES / "invalid_with_ref.yaml")
