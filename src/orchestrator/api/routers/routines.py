"""Routine API endpoints."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from orchestrator.api.deps import get_routine_dirs
from orchestrator.api.schemas.routines import (
    RoutineDetail,
    RoutineListResponse,
    RoutineSummary,
    StepSummarySchema,
)
from orchestrator.config.enums import RoutineSource
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
