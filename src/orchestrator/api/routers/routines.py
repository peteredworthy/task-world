"""Routine API endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from typing import Annotated, Any, cast

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.deps import get_routine_dirs, get_session
from orchestrator.api.schemas.routines import (
    ArchiveRoutineResponse,
    RoutineDetail,
    RoutineListResponse,
    RoutineSummary,
    StepSummarySchema,
    ValidateRoutineRequest,
    ValidateRoutineResponse,
)
from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig
from orchestrator.config import discover_routines, RoutineNotFoundError
from orchestrator.db import RoutineMetaModel

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


async def _get_archived_ids(session: AsyncSession) -> set[tuple[str, str]]:
    """Return set of (routine_id, source) pairs that are archived."""
    result = await session.execute(
        select(RoutineMetaModel).where(RoutineMetaModel.is_archived == True)  # noqa: E712
    )
    return {(row.routine_id, row.source) for row in result.scalars()}


async def _get_or_create_meta(
    session: AsyncSession, routine_id: str, source: str
) -> RoutineMetaModel:
    result = await session.execute(
        select(RoutineMetaModel).where(
            RoutineMetaModel.routine_id == routine_id,
            RoutineMetaModel.source == source,
        )
    )
    meta = result.scalar_one_or_none()
    if meta is None:
        meta = RoutineMetaModel(routine_id=routine_id, source=source)
        session.add(meta)
    return meta


@router.get("", response_model=RoutineListResponse)
async def list_routines(
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
    session: Annotated[AsyncSession, Depends(get_session)],
    include_archived: bool = Query(False, description="Include archived routines in response"),
) -> RoutineListResponse:
    """List all discovered routines."""
    found = discover_routines(routine_dirs)
    archived_ids = await _get_archived_ids(session)

    summaries: list[RoutineSummary] = []
    for routine in found:
        key = (routine.config.id, routine.source.value)
        is_archived = key in archived_ids
        if is_archived and not include_archived:
            continue
        summaries.append(
            RoutineSummary(
                id=routine.config.id,
                name=routine.config.name,
                description=routine.config.description,
                source=routine.source.value,
                step_count=len(routine.config.steps),
                input_count=len(routine.config.inputs),
                is_archived=is_archived,
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
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoutineDetail:
    """Get a routine by ID."""
    found = discover_routines(routine_dirs)
    archived_ids = await _get_archived_ids(session)
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
            key = (routine.config.id, routine.source.value)
            return RoutineDetail(
                id=routine.config.id,
                name=routine.config.name,
                description=routine.config.description,
                source=routine.source.value,
                inputs=inputs,
                steps=steps,
                is_archived=key in archived_ids,
            )
    raise RoutineNotFoundError(routine_id)


@router.post("/{routine_id}/archive", response_model=ArchiveRoutineResponse)
async def archive_routine(
    routine_id: str,
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ArchiveRoutineResponse:
    """Archive a routine so it is hidden from the default listing and selector."""
    found = discover_routines(routine_dirs)
    source: str | None = None
    for routine in found:
        if routine.config.id == routine_id:
            source = routine.source.value
            break
    if source is None:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")

    meta = await _get_or_create_meta(session, routine_id, source)
    meta.is_archived = True
    meta.archived_at = datetime.now(timezone.utc)
    await session.commit()
    return ArchiveRoutineResponse(id=routine_id, source=source, is_archived=True)


@router.post("/{routine_id}/unarchive", response_model=ArchiveRoutineResponse)
async def unarchive_routine(
    routine_id: str,
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ArchiveRoutineResponse:
    """Unarchive a routine so it appears again in listings and the selector."""
    found = discover_routines(routine_dirs)
    source: str | None = None
    for routine in found:
        if routine.config.id == routine_id:
            source = routine.source.value
            break
    if source is None:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")

    result = await session.execute(
        select(RoutineMetaModel).where(
            RoutineMetaModel.routine_id == routine_id,
            RoutineMetaModel.source == source,
        )
    )
    meta = result.scalar_one_or_none()
    if meta is None or not meta.is_archived:
        return ArchiveRoutineResponse(id=routine_id, source=source, is_archived=False)
    meta.is_archived = False
    meta.archived_at = None
    await session.commit()
    return ArchiveRoutineResponse(id=routine_id, source=source, is_archived=False)
