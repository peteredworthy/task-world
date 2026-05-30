"""Tests for run factory functions."""

from typing import Callable

import pytest

from orchestrator.config import Priority, RoutineSource
from orchestrator.config.models import (
    RequirementConfig,
    RoutineConfig,
    RoutineInputConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.state.errors import MissingRequiredInputError
from orchestrator.state.factory import (
    create_checklist_from_requirements,
    create_run_from_routine,
    create_task_state,
    validate_routine_inputs,
)


@pytest.fixture
def simple_routine() -> RoutineConfig:
    return RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Context",
                        requirements=[
                            RequirementConfig(id="R1", desc="Req 1"),
                            RequirementConfig(id="R2", desc="Req 2", priority=Priority.NICE),
                        ],
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def sequential_id_generator() -> Callable[[], str]:
    """Deterministic ID generator for testing."""
    counter = [0]

    def generate() -> str:
        counter[0] += 1
        return f"id-{counter[0]}"

    return generate


def test_create_checklist_from_requirements() -> None:
    task = TaskConfig(
        id="T1",
        title="Task",
        task_context="Context",
        requirements=[
            RequirementConfig(id="R1", desc="Req 1", priority=Priority.CRITICAL),
            RequirementConfig(id="R2", desc="Req 2", priority=Priority.EXPECTED),
        ],
    )
    checklist = create_checklist_from_requirements(task)

    assert len(checklist) == 2
    assert checklist[0].req_id == "R1"
    assert checklist[0].priority == Priority.CRITICAL
    assert checklist[1].priority == Priority.EXPECTED


def test_create_run_deterministic_ids(
    simple_routine: RoutineConfig, sequential_id_generator: Callable[[], str]
) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        repo_name="proj-1",
        source_branch="main",
        id_generator=sequential_id_generator,
    )

    # run_id first, then task_id (inside step), then step_id
    assert run.id == "id-1"
    assert run.steps[0].tasks[0].id == "id-2"
    assert run.steps[0].id == "id-3"


def test_create_run_with_config(simple_routine: RoutineConfig) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        repo_name="proj-1",
        source_branch="main",
        config={"feature": "auth", "branch": "main"},
    )

    assert run.config["feature"] == "auth"
    assert run.config["branch"] == "main"


def test_create_run_with_source(simple_routine: RoutineConfig) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
        routine_sha="abc123",
    )

    assert run.routine_source == RoutineSource.LOCAL
    assert run.routine_sha == "abc123"


def test_checklist_populated(simple_routine: RoutineConfig) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        repo_name="proj-1",
        source_branch="main",
    )

    task = run.steps[0].tasks[0]
    assert len(task.checklist) == 2
    assert task.checklist[0].req_id == "R1"
    assert task.checklist[1].req_id == "R2"


def test_create_task_state_max_attempts() -> None:
    from orchestrator.config.models import RetryConfig

    task_config = TaskConfig(
        id="T1",
        title="Task",
        task_context="Context",
        retry=RetryConfig(max_attempts=5),
    )
    task_state = create_task_state(task_config)
    assert task_state.max_attempts == 5


def test_create_task_state_without_verifier_config_keeps_verification_enabled() -> None:
    task_config = TaskConfig(
        id="T1",
        title="Task",
        task_context="Context",
    )

    task_state = create_task_state(task_config)

    assert task_state.has_verification is True


# --- validate_routine_inputs tests ---


def _make_routine_with_inputs(inputs: list[RoutineInputConfig]) -> RoutineConfig:
    """Helper to create a minimal routine with the given inputs."""
    return RoutineConfig(
        id="r1",
        name="Test Routine",
        inputs=inputs,
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(id="T-01", title="Task 1", task_context="ctx"),
                ],
            ),
        ],
    )


def test_validate_missing_required_input_raises() -> None:
    """Missing required input raises MissingRequiredInputError."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="project_name", required=True),
        ]
    )

    with pytest.raises(MissingRequiredInputError) as exc_info:
        validate_routine_inputs(routine, {})

    assert exc_info.value.input_name == "project_name"
    assert "project_name" in str(exc_info.value)


def test_validate_optional_input_with_default_applied() -> None:
    """Optional input with default gets applied when not provided."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="branch", required=False, default="main"),
        ]
    )

    result = validate_routine_inputs(routine, {})

    assert result["branch"] == "main"


def test_validate_optional_input_without_default_not_added() -> None:
    """Optional input without default is not added to config."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="notes", required=False, default=None),
        ]
    )

    result = validate_routine_inputs(routine, {})

    assert "notes" not in result


def test_validate_all_inputs_provided_passes_through() -> None:
    """All inputs provided passes through unchanged."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="project_name", required=True),
            RoutineInputConfig(name="branch", required=False, default="main"),
        ]
    )
    config = {"project_name": "my-proj", "branch": "dev"}

    result = validate_routine_inputs(routine, config)

    assert result == {"project_name": "my-proj", "branch": "dev"}


def test_validate_no_inputs_defined_passes_through() -> None:
    """Routine with no inputs defined passes through unchanged."""
    routine = _make_routine_with_inputs([])
    config = {"extra_key": "value"}

    result = validate_routine_inputs(routine, config)

    assert result == {"extra_key": "value"}


def test_validate_does_not_mutate_original_config() -> None:
    """validate_routine_inputs returns a new dict, not mutating the original."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="branch", required=False, default="main"),
        ]
    )
    original = {"existing": "value"}

    result = validate_routine_inputs(routine, original)

    assert "branch" in result
    assert "branch" not in original


def test_create_run_from_routine_validates_inputs() -> None:
    """create_run_from_routine raises on missing required inputs."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="project_name", required=True),
        ]
    )

    with pytest.raises(MissingRequiredInputError):
        create_run_from_routine(routine=routine, repo_name="proj-1", source_branch="main")


def test_create_run_from_routine_applies_defaults() -> None:
    """create_run_from_routine applies default values from routine inputs."""
    routine = _make_routine_with_inputs(
        [
            RoutineInputConfig(name="branch", required=False, default="main"),
        ]
    )

    run = create_run_from_routine(routine=routine, repo_name="proj-1", source_branch="main")

    assert run.config["branch"] == "main"


# --- Gap coverage: TaskState pending fields ---


def test_task_state_pending_fields_default_none() -> None:
    """Test TaskState with pending_action_type and pending_clarification_id defaulting to None."""
    from orchestrator.state.models import TaskState

    task = TaskState(
        config_id="T-01",
        title="Task 1",
    )
    assert task.pending_action_type is None
    assert task.pending_clarification_id is None


def test_task_state_with_pending_clarification_action() -> None:
    """Test TaskState with pending_action_type set to clarification."""
    from orchestrator.state.models import TaskState

    task = TaskState(
        config_id="T-01",
        title="Task 1",
        pending_action_type="clarification",
        pending_clarification_id="clarif-123",
    )
    assert task.pending_action_type == "clarification"
    assert task.pending_clarification_id == "clarif-123"


def test_task_state_with_pending_approval_action() -> None:
    """Test TaskState with pending_action_type set to approval."""
    from orchestrator.state.models import TaskState

    task = TaskState(
        config_id="T-01",
        title="Task 1",
        pending_action_type="approval",
    )
    assert task.pending_action_type == "approval"
    assert task.pending_clarification_id is None


def test_create_task_state_preserves_pending_fields() -> None:
    """Test that create_task_state creates TaskState with pending fields initialized to None."""
    task_config = TaskConfig(
        id="T1",
        title="Task",
        task_context="Context",
    )
    task_state = create_task_state(task_config)

    assert task_state.pending_action_type is None
    assert task_state.pending_clarification_id is None
