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
    is_archived: bool = False


class RoutineDetail(ApiModel):
    id: str
    name: str
    description: str | None = None
    source: str
    inputs: list[dict[str, object]]
    steps: list[StepSummarySchema]
    is_archived: bool = False


class ArchiveRoutineResponse(ApiModel):
    id: str
    source: str
    is_archived: bool


class RoutineListResponse(ApiModel):
    routines: list[RoutineSummary]


class ValidateRoutineRequest(ApiModel):
    yaml_content: str


class ValidateRoutineResponse(ApiModel):
    valid: bool
    errors: list[str] = []
    builder_feedback: list[str] = []
