"""Run API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CreateRunRequest(BaseModel):
    routine_id: str
    project_id: str
    config: dict[str, Any] = {}
    agent_type: str | None = None
    agent_config: dict[str, Any] = {}


class TaskSummary(BaseModel):
    id: str
    config_id: str
    status: str
    current_attempt: int
    max_attempts: int


class StepSummary(BaseModel):
    id: str
    config_id: str
    completed: bool
    tasks: list[TaskSummary]


class RunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: str | None = None
    agent_type: str | None = None
    agent_config: dict[str, Any] = {}
    worktree_enabled: bool = True
    worktree_path: str | None = None
    config: dict[str, Any] = {}
    steps: list[StepSummary] = []
    current_step_index: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0


class RunListResponse(BaseModel):
    runs: list[RunResponse]
