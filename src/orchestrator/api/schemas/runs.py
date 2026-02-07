"""Run API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator

from orchestrator.config.enums import AgentType


class EnvFileSpecSchema(BaseModel):
    path: str
    promote_on_success: bool = False


class EnvFileRequestConfig(BaseModel):
    """Env file configuration for run creation."""

    source_dir: str | None = None
    files: list[EnvFileSpecSchema] | None = None


class CreateRunRequest(BaseModel):
    routine_id: str | None = None
    project_id: str
    routine_embedded: dict[str, Any] | None = None
    config: dict[str, Any] = {}
    agent_type: str | None = None
    agent_config: dict[str, Any] = {}
    env_files: EnvFileRequestConfig | None = None
    source_branch: str | None = None
    merge_strategy: str | None = None
    init_project: bool = False

    @model_validator(mode="after")
    def validate_routine_source(self) -> "CreateRunRequest":
        """Ensure exactly one of routine_id or routine_embedded is provided."""
        has_id = self.routine_id is not None
        has_embedded = self.routine_embedded is not None
        if has_id == has_embedded:  # both set or neither set
            raise ValueError("Exactly one of 'routine_id' or 'routine_embedded' must be provided")
        return self


class GradeSummaryItem(BaseModel):
    grade: str | None = None
    priority: str


class AttemptOutcome(BaseModel):
    attempt_num: int
    outcome: str | None = None


class TaskSummary(BaseModel):
    id: str
    config_id: str
    title: str = ""
    status: str
    current_attempt: int
    max_attempts: int
    grade_summary: list[GradeSummaryItem] = []
    attempts_summary: list[AttemptOutcome] = []
    pending_action_type: str | None = None  # "clarification" | "approval" | None
    pending_clarification_count: int | None = None


class StepSummary(BaseModel):
    id: str
    config_id: str
    title: str = ""
    completed: bool
    tasks: list[TaskSummary]
    has_approval_gate: bool = False
    approval_status: str | None = None  # "pending" | "approved" | "rejected" | None


class RunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: str | None = None
    routine_embedded: dict[str, Any] | None = None
    agent_type: str | None = None
    agent_type_display: str
    agent_icon: str
    agent_config: dict[str, Any] = {}
    worktree_enabled: bool = True
    worktree_path: str | None = None
    source_branch: str | None = None
    merge_strategy: str | None = None
    config: dict[str, Any] = {}
    env_file_specs: list[EnvFileSpecSchema] = []
    env_source_dir: str | None = None
    steps: list[StepSummary] = []
    current_step_index: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    agent_started_at: datetime | None = None
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    estimated_cost_usd: float | None = None
    cost_disclaimer: str | None = None


class RunListResponse(BaseModel):
    runs: list[RunResponse]


class GuidanceResponse(BaseModel):
    """Aggregate guidance for external agents."""

    run_id: str
    task_id: str | None = None
    prompt: str | None = None
    phase: str | None = None  # "building" or "verifying"
    mcp_url: str
    expected_actions: list[str]


class AgentCancelledRequest(BaseModel):
    """Request to cancel waiting for external agent."""

    reason: str | None = None


class BackwardTransitionRequest(BaseModel):
    """Request to transition backward to an earlier step."""

    target_step_index: int
    reason: str | None = None


class ResumeRunRequest(BaseModel):
    """Request to resume a paused run, optionally changing the agent."""

    agent_type: str | None = None
    agent_config: dict[str, Any] | None = None


class BranchStatusResponse(BaseModel):
    """Response for branch status check."""

    behind_count: int
    ahead_count: int
    can_merge_cleanly: bool
    has_conflicts: bool
    source_branch: str
    run_branch: str


class BackMergeResponse(BaseModel):
    """Response for back-merge operation."""

    merge_commit: str
    message: str


class MergeBackRequest(BaseModel):
    """Request for merge-back operation."""

    strategy: str | None = None


class MergeBackResponse(BaseModel):
    """Response for merge-back operation."""

    merge_commit: str
    strategy: str
    message: str


def get_agent_display_name(agent_type: AgentType | None) -> str:
    """Get human-readable display name for an agent type.

    Args:
        agent_type: The agent type enum value, or None

    Returns:
        Display name string for the UI
    """
    if agent_type is None:
        return "No Agent"

    display_map = {
        AgentType.OPENHANDS_LOCAL: "OpenHands",
        AgentType.OPENHANDS_DOCKER: "OpenHands Docker",
        AgentType.CLI_SUBPROCESS: "Claude CLI",
        AgentType.USER_MANAGED: "External Agent",
    }

    return display_map.get(agent_type, "Unknown Agent")


def get_agent_icon(agent_type: AgentType | None) -> str:
    """Get icon key for an agent type.

    Args:
        agent_type: The agent type enum value, or None

    Returns:
        Icon key string for the UI
    """
    if agent_type is None:
        return "none"

    icon_map = {
        AgentType.OPENHANDS_LOCAL: "openhands",
        AgentType.OPENHANDS_DOCKER: "docker",
        AgentType.CLI_SUBPROCESS: "cli",
        AgentType.USER_MANAGED: "external",
    }

    return icon_map.get(agent_type, "unknown")
