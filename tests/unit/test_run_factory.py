"""Tests for run factory functions."""

from typing import Callable

import pytest

from orchestrator.config.enums import Priority, RoutineSource
from orchestrator.config.models import (
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.state.factory import (
    create_checklist_from_requirements,
    create_run_from_routine,
    create_task_state,
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
        project_id="proj-1",
        id_generator=sequential_id_generator,
    )

    # run_id first, then task_id (inside step), then step_id
    assert run.id == "id-1"
    assert run.steps[0].tasks[0].id == "id-2"
    assert run.steps[0].id == "id-3"


def test_create_run_with_config(simple_routine: RoutineConfig) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        project_id="proj-1",
        config={"feature": "auth", "branch": "main"},
    )

    assert run.config["feature"] == "auth"
    assert run.config["branch"] == "main"


def test_create_run_with_source(simple_routine: RoutineConfig) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        project_id="proj-1",
        routine_source=RoutineSource.LOCAL,
        routine_sha="abc123",
    )

    assert run.routine_source == RoutineSource.LOCAL
    assert run.routine_sha == "abc123"


def test_checklist_populated(simple_routine: RoutineConfig) -> None:
    run = create_run_from_routine(
        routine=simple_routine,
        project_id="proj-1",
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
