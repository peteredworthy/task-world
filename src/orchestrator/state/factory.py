"""Factory functions to create runtime state from configuration."""

from typing import Any, Callable
from uuid import uuid4

from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig, StepConfig, TaskConfig
from orchestrator.state.errors import MissingRequiredInputError
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
    has_verification = bool(task_config.auto_verify.items) or bool(task_config.verifier.rubric)
    return TaskState(
        id=id_generator(),
        config_id=task_config.id,
        title=task_config.title,
        checklist=create_checklist_from_requirements(task_config),
        max_attempts=task_config.retry.max_attempts,
        has_verification=has_verification,
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
        title=step_config.title,
        tasks=tasks,
    )


def validate_routine_inputs(routine: RoutineConfig, config: dict[str, Any]) -> dict[str, Any]:
    """Validate and enrich config with defaults from routine inputs.

    Args:
        routine: The routine configuration with input definitions
        config: User-provided configuration values

    Returns:
        Enriched config dict with defaults applied for missing optional inputs

    Raises:
        MissingRequiredInputError: If a required input is not provided
    """
    enriched = dict(config)
    for inp in routine.inputs:
        if inp.name not in enriched:
            if inp.required:
                raise MissingRequiredInputError(inp.name)
            if inp.default is not None:
                enriched[inp.name] = inp.default
    return enriched


def create_run_from_routine(
    routine: RoutineConfig,
    repo_name: str,
    source_branch: str,
    config: dict[str, Any] | None = None,
    routine_source: RoutineSource | None = None,
    routine_sha: str | None = None,
    routine_path: str | None = None,
    routine_commit: str | None = None,
    id_generator: Callable[[], str] = default_id_generator,
) -> Run:
    """Create a Run instance from a RoutineConfig.

    ID generation order: run_id first, then step_id, then task_id(s) per step.

    Args:
        routine: The routine configuration
        repo_name: Name of the repository in repos directory
        source_branch: Branch to base worktree on
        config: Runtime configuration values
        routine_source: Where the routine came from
        routine_sha: Git SHA of the routine
        routine_path: Path within repo for project routines
        routine_commit: Commit SHA when routine was read
        id_generator: Function to generate IDs (inject for testing)

    Returns:
        A new Run in DRAFT status
    """
    validated_config = validate_routine_inputs(routine, config or {})
    run_id = id_generator()

    steps = [create_step_state(step_config, id_generator) for step_config in routine.steps]

    return Run(
        id=run_id,
        repo_name=repo_name,
        source_branch=source_branch,
        routine_id=routine.id,
        routine_source=routine_source,
        routine_sha=routine_sha,
        routine_path=routine_path,
        routine_commit=routine_commit,
        config=validated_config,
        steps=steps,
    )
