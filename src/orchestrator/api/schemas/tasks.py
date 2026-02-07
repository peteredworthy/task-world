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


class GradeSnapshotItemSchema(BaseModel):
    req_id: str
    grade: str | None = None
    grade_reason: str | None = None


class AttemptSchema(BaseModel):
    id: str
    attempt_num: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    outcome: str | None = None
    metrics: dict[str, Any] = {}
    grade_snapshot: list[GradeSnapshotItemSchema] = []
    auto_verify_results: list[dict[str, Any]] = []

    # Agent snapshot
    agent_type: str | None = None
    agent_model: str | None = None
    agent_settings: dict[str, Any] = {}
    error: str | None = None
    has_output: bool = False


class TaskDetailResponse(BaseModel):
    id: str
    config_id: str
    title: str = ""
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


class CallbackInstructions(BaseModel):
    """Instructions for external agents to call back to the orchestrator."""

    run_id: str
    task_id: str
    api_base_url: str
    rest_instructions: str
    mcp_instructions: str


class PromptResponse(BaseModel):
    system: str
    user: str
    phase: str  # "building" or "verifying"
    callback: CallbackInstructions | None = None


class AgentLogsResponse(BaseModel):
    """Response for agent log retrieval."""

    run_id: str
    task_id: str
    attempt_num: int
    output: str | None = None
    error: str | None = None
    line_count: int = 0


class ApproveTaskRequest(BaseModel):
    comment: str | None = None


class RejectTaskRequest(BaseModel):
    reason: str | None = None
