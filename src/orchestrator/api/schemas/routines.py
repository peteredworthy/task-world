"""Routine API schemas."""

from orchestrator.api.schemas.base import ApiModel


class StepSummarySchema(ApiModel):
    id: str
    title: str
    task_count: int


class RoutineSummary(ApiModel):
    id: str
    name: str
    description: str | None = None
    source: str
    step_count: int
    input_count: int


class RoutineDetail(ApiModel):
    id: str
    name: str
    description: str | None = None
    source: str
    inputs: list[dict[str, object]]
    steps: list[StepSummarySchema]


class RoutineListResponse(ApiModel):
    routines: list[RoutineSummary]


class ValidateRoutineRequest(ApiModel):
    yaml_content: str


class ValidateRoutineResponse(ApiModel):
    valid: bool
    errors: list[str] = []
    builder_feedback: list[str] = []
