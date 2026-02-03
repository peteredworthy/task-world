"""Factory functions to create runtime state from configuration."""

from typing import Any, Callable
from uuid import uuid4

from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig, StepConfig, TaskConfig
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)


def default_id_generator() -> str:
    """Generate a unique ID using UUID4."""
    return str(uuid4())


def create_checklist_from_requirements(
    task_config: TaskConfig,
) -> list[ChecklistItem]:
    """Create checklist items from task requirements."""
    return [
        ChecklistItem(
            req_id=req.id,
            desc=req.desc,
            priority=req.priority,
        )
        for req in task_config.requirements
    ]


def create_task_state(
    task_config: TaskConfig,
    id_generator: Callable[[], str] = default_id_generator,
) -> TaskState:
    """Create task state from task config."""
    return TaskState(
        id=id_generator(),
        config_id=task_config.id,
        checklist=create_checklist_from_requirements(task_config),
        max_attempts=task_config.retry.max_attempts,
    )


def create_step_state(
    step_config: StepConfig,
    id_generator: Callable[[], str] = default_id_generator,
) -> StepState:
    """Create step state from step config."""
    tasks = [create_task_state(task_config, id_generator) for task_config in step_config.tasks]

    return StepState(
        id=id_generator(),
        config_id=step_config.id,
        tasks=tasks,
    )


def create_run_from_routine(
    routine: RoutineConfig,
    project_id: str,
    config: dict[str, Any] | None = None,
    routine_source: RoutineSource | None = None,
    routine_sha: str | None = None,
    id_generator: Callable[[], str] = default_id_generator,
) -> Run:
    """Create a Run instance from a RoutineConfig.

    ID generation order: run_id first, then step_id, then task_id(s) per step.

    Args:
        routine: The routine configuration
        project_id: ID of the project
        config: Runtime configuration values
        routine_source: Where the routine came from
        routine_sha: Git SHA of the routine
        id_generator: Function to generate IDs (inject for testing)

    Returns:
        A new Run in DRAFT status
    """
    run_id = id_generator()

    steps = [create_step_state(step_config, id_generator) for step_config in routine.steps]

    return Run(
        id=run_id,
        project_id=project_id,
        routine_id=routine.id,
        routine_source=routine_source,
        routine_sha=routine_sha,
        config=config or {},
        steps=steps,
    )
