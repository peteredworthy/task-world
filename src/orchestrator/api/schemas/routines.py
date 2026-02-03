"""Routine API schemas."""

from pydantic import BaseModel


class StepSummarySchema(BaseModel):
    id: str
    title: str
    task_count: int


class RoutineSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    source: str
    step_count: int
    input_count: int


class RoutineDetail(BaseModel):
    id: str
    name: str
    description: str | None = None
    source: str
    inputs: list[dict[str, object]]
    steps: list[StepSummarySchema]


class RoutineListResponse(BaseModel):
    routines: list[RoutineSummary]
