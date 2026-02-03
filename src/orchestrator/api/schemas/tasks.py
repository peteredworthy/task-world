"""Task API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ChecklistItemSchema(BaseModel):
    req_id: str
    desc: str
    priority: str
    status: str
    note: str | None = None
    grade: str | None = None
    grade_reason: str | None = None


class AttemptSchema(BaseModel):
    id: str
    attempt_num: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    outcome: str | None = None
    metrics: dict[str, Any] = {}


class TaskDetailResponse(BaseModel):
    id: str
    config_id: str
    status: str
    checklist: list[ChecklistItemSchema]
    attempts: list[AttemptSchema]
    current_attempt: int
    max_attempts: int


class TransitionResponse(BaseModel):
    success: bool
    new_status: str
    error: str | None = None


class UpdateChecklistRequest(BaseModel):
    status: str
    note: str | None = None


class SetGradeRequest(BaseModel):
    grade: str
    grade_reason: str | None = None
