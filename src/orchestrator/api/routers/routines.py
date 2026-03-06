"""Routine API endpoints."""

from pathlib import Path
from collections.abc import Sequence
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


def _format_loc(loc: tuple[object, ...]) -> str:
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            if parts:
                parts.append(f".{part}")
            else:
                parts.append(str(part))
    return "".join(parts)


def _validation_feedback_from_pydantic(errors: list[dict[str, object]]) -> list[str]:
    feedback: list[str] = []
    for err in errors:
        loc = err.get("loc")
        msg = err.get("msg")
        if isinstance(loc, Sequence) and not isinstance(loc, str):
            loc_parts = [part for part in cast(Sequence[object], loc)]
            loc_text = _format_loc(tuple(loc_parts))
        else:
            loc_text = str(loc)
        msg_text = str(msg)
        line = f"Fix `{loc_text}`: {msg_text}."
        if "Field required" in msg_text:
            line += " Add the missing field with a valid value."
        elif "Input should be a valid list" in msg_text:
            line += " Ensure this value is a YAML list (`- item`)."
        elif "Input should be a valid string" in msg_text:
            line += " Provide a YAML string value."
        elif "contains 'ref' or 'use'" in msg_text:
            line += " Expand inherited references; this schema requires explicit definitions."
        feedback.append(line)
    return feedback


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
        return ValidateRoutineResponse(
            valid=False,
            errors=[f"YAML parse error: {e}"],
            builder_feedback=[
                "YAML parsing failed. Check indentation, list markers (`-`), and quotes around strings containing `:`."
            ],
        )

    if data is None:
        return ValidateRoutineResponse(
            valid=False,
            errors=["Empty YAML content"],
            builder_feedback=["Provide a routine object with at least `id`, `name`, and `steps`."],
        )

    # Handle the `routine:` wrapper (same as loader.py)
    if isinstance(data, dict) and "routine" in data:
        data = cast(Any, data["routine"])

    # Validate with RoutineConfig
    try:
        RoutineConfig.model_validate(data)
    except ValidationError as e:
        pydantic_errors = e.errors()
        errors = [f"{err['loc']}: {err['msg']}" for err in pydantic_errors]
        return ValidateRoutineResponse(
            valid=False,
            errors=errors,
            builder_feedback=_validation_feedback_from_pydantic(
                cast(list[dict[str, object]], pydantic_errors)
            ),
        )

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
                    title=step.title or step.id,
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
