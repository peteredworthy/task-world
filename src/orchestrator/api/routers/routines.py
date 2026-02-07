"""Routine API endpoints."""

from pathlib import Path
from typing import Annotated, Any, cast

import yaml
from fastapi import APIRouter, Depends
from pydantic import ValidationError

from orchestrator.api.deps import get_routine_dirs
from orchestrator.api.schemas.routines import (
    RoutineDetail,
    RoutineListResponse,
    RoutineSummary,
    StepSummarySchema,
    ValidateRoutineRequest,
    ValidateRoutineResponse,
)
from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig
from orchestrator.routines.discovery import discover_routines
from orchestrator.routines.errors import RoutineNotFoundError

router = APIRouter(prefix="/api/routines", tags=["routines"])


@router.get("", response_model=RoutineListResponse)
async def list_routines(
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
) -> RoutineListResponse:
    """List all discovered routines."""
    found = discover_routines(routine_dirs)
    summaries: list[RoutineSummary] = []
    for routine in found:
        summaries.append(
            RoutineSummary(
                id=routine.config.id,
                name=routine.config.name,
                description=routine.config.description,
                source=routine.source.value,
                step_count=len(routine.config.steps),
                input_count=len(routine.config.inputs),
            )
        )
    return RoutineListResponse(routines=summaries)


@router.post("/validate", response_model=ValidateRoutineResponse)
async def validate_routine(request: ValidateRoutineRequest) -> ValidateRoutineResponse:
    """Validate a routine YAML definition without saving it."""
    # Parse YAML
    try:
        data: Any = yaml.safe_load(request.yaml_content)
    except yaml.YAMLError as e:
        return ValidateRoutineResponse(valid=False, errors=[f"YAML parse error: {e}"])

    if data is None:
        return ValidateRoutineResponse(valid=False, errors=["Empty YAML content"])

    # Handle the `routine:` wrapper (same as loader.py)
    if isinstance(data, dict) and "routine" in data:
        data = cast(Any, data["routine"])

    # Validate with RoutineConfig
    try:
        RoutineConfig.model_validate(data)
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        return ValidateRoutineResponse(valid=False, errors=errors)

    return ValidateRoutineResponse(valid=True)


@router.get("/{routine_id}", response_model=RoutineDetail)
async def get_routine(
    routine_id: str,
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
) -> RoutineDetail:
    """Get a routine by ID."""
    found = discover_routines(routine_dirs)
    for routine in found:
        if routine.config.id == routine_id:
            steps = [
                StepSummarySchema(
                    id=step.id,
                    title=step.title,
                    task_count=len(step.tasks),
                )
                for step in routine.config.steps
            ]
            inputs = [inp.model_dump(mode="json") for inp in routine.config.inputs]
            return RoutineDetail(
                id=routine.config.id,
                name=routine.config.name,
                description=routine.config.description,
                source=routine.source.value,
                inputs=inputs,
                steps=steps,
            )
    raise RoutineNotFoundError(routine_id)
