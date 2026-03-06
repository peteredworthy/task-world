"""Task API schemas."""

from datetime import datetime
from typing import Any

from pydantic import field_validator

from orchestrator.api.schemas.base import ApiModel
from orchestrator.config.enums import ChecklistStatus
from orchestrator.config.models import MCPServerConfig


class ChecklistItemSchema(ApiModel):
    req_id: str
    desc: str
    priority: str
    status: str
    note: str | None = None
    grade: str | None = None
    grade_reason: str | None = None


class GradeSnapshotItemSchema(ApiModel):
    req_id: str
    grade: str | None = None
    grade_reason: str | None = None
    note: str | None = None


# --- Structured Action Log schemas ---


class ToolUseDetailSchema(ApiModel):
    tool_use_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = {}
    summary: str | None = None


class ToolResultDetailSchema(ApiModel):
    tool_use_id: str = ""
    output: str = ""
    exit_code: int | None = None
    success: bool = True
    output_length: int = 0


class TurnMetricsSchema(ApiModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0


class ActionLogEntrySchema(ApiModel):
    sequence_num: int = 0
    kind: str
    timestamp: datetime | None = None
    text: str | None = None
    tool_use: ToolUseDetailSchema | None = None
    tool_result: ToolResultDetailSchema | None = None
    metrics: TurnMetricsSchema | None = None
    raw_type: str | None = None


class ActionLogSchema(ApiModel):
    entries: list[ActionLogEntrySchema] = []
    session_id: str | None = None
    agent_model: str | None = None
    tools_available: list[str] = []
    total_turns: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


# --- Attempt and Task schemas ---


class AttemptSchema(ApiModel):
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
    has_action_log: bool = False

    # Git commit range for this attempt
    start_commit: str | None = None
    end_commit: str | None = None


class TaskDetailResponse(ApiModel):
    id: str
    config_id: str
    title: str = ""
    status: str
    complexity: str = "standard"
    checklist: list[ChecklistItemSchema]
    attempts: list[AttemptSchema]
    current_attempt: int
    max_attempts: int


class TransitionResponse(ApiModel):
    success: bool
    new_status: str
    error: str | None = None


_VALID_CHECKLIST_STATUSES = [e.value for e in ChecklistStatus]
_VALID_GRADES = ["A", "B", "C", "D", "F"]


class UpdateChecklistRequest(ApiModel):
    status: str
    note: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: str) -> str:
        lowered = v.lower()
        if lowered not in _VALID_CHECKLIST_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Valid options: {', '.join(_VALID_CHECKLIST_STATUSES)}"
            )
        return lowered


class SetGradeRequest(ApiModel):
    grade: str
    grade_reason: str | None = None

    @field_validator("grade", mode="before")
    @classmethod
    def validate_grade(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_GRADES:
            raise ValueError(f"Invalid grade '{v}'. Valid options: {', '.join(_VALID_GRADES)}")
        return upper


class CallbackInstructions(ApiModel):
    """Instructions for external agents to call back to the orchestrator."""

    run_id: str
    task_id: str
    api_base_url: str
    rest_instructions: str
    mcp_instructions: str
    mcp_servers: list[MCPServerConfig] | None = None


class PromptResponse(ApiModel):
    system: str
    user: str
    phase: str  # "building" or "verifying"
    callback: CallbackInstructions | None = None


class AgentLogsResponse(ApiModel):
    """Response for agent log retrieval."""

    run_id: str
    task_id: str
    attempt_num: int
    output: str | None = None
    error: str | None = None
    line_count: int = 0
    action_log: ActionLogSchema | None = None


class ApproveTaskRequest(ApiModel):
    comment: str | None = None


class RejectTaskRequest(ApiModel):
    reason: str | None = None
