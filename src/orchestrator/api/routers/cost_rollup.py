"""Graph-node usage cost rollup endpoint."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.deps import get_session
from orchestrator.api.presenters import CostRollupCardinalityError, compute_cost_rollup
from orchestrator.api.schemas.cost_rollup import (
    CostRollupDimension,
    CostRollupFact,
    CostRollupFilters,
    CostRollupResponse,
    RunStatusFilter,
    SelectableRunnerTypeFilter,
)
from orchestrator.db import EventV2Model, RunModel
from orchestrator.graph_runtime import graph_aggregate_id

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _utc_isoformat(value: datetime) -> str:
    """Return the stable UTC representation used by graph event timestamps."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


async def load_cost_rollup_facts(
    session: AsyncSession,
    filters: CostRollupFilters,
) -> list[CostRollupFact]:
    """Load only canonical graph ``node_usage_recorded`` facts with SQL filters."""
    statement = (
        select(RunModel.id, EventV2Model.timestamp, EventV2Model.payload)
        .join(
            EventV2Model,
            EventV2Model.aggregate_id == (literal(graph_aggregate_id("")) + RunModel.id),
        )
        .where(EventV2Model.event_type == "node_usage_recorded")
        .order_by(EventV2Model.position)
    )
    if filters.statuses:
        statement = statement.where(RunModel.status.in_(filters.statuses))
    if filters.runner_types:
        statement = statement.where(RunModel.runner_type.in_(filters.runner_types))
    if filters.start is not None:
        statement = statement.where(EventV2Model.timestamp >= _utc_isoformat(filters.start))
    if filters.end is not None:
        statement = statement.where(EventV2Model.timestamp < _utc_isoformat(filters.end))

    result = await session.execute(statement)
    return [
        CostRollupFact(
            run_id=run_id,
            timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            **json.loads(payload),
        )
        for run_id, timestamp, payload in result.all()
    ]


@router.get("/cost-rollup", response_model=CostRollupResponse)
async def get_cost_rollup(
    session: Annotated[AsyncSession, Depends(get_session)],
    group_by: Annotated[list[CostRollupDimension], Query()] = ["run"],
    status: Annotated[list[RunStatusFilter], Query()] = [],
    runner_type: Annotated[list[SelectableRunnerTypeFilter], Query()] = [],
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> CostRollupResponse:
    """Return grouped usage and cost from graph events, never legacy cost records."""
    try:
        filters = CostRollupFilters(
            statuses=tuple(status),
            runner_types=tuple(runner_type),
            start=start,
            end=end,
        )
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=jsonable_encoder(error.errors())) from error
    try:
        return compute_cost_rollup(await load_cost_rollup_facts(session, filters), tuple(group_by))
    except CostRollupCardinalityError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
