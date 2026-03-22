"""Run API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from orchestrator.api.schemas.base import ApiModel

from orchestrator.config.enums import AgentRunnerType, MergeStrategy


_VALID_AGENT_TYPES = [e.value for e in AgentRunnerType]
_VALID_MERGE_STRATEGIES = [e.value for e in MergeStrategy]


def _validate_agent_type(v: str | None) -> str | None:
    """Validate and normalize agent_type (case-insensitive)."""
    if v is None:
        return v
    lowered = v.lower()
    if lowered not in _VALID_AGENT_TYPES:
        raise ValueError(
            f"Invalid agent_type '{v}'. Valid options: {', '.join(_VALID_AGENT_TYPES)}"
        )
    return lowered


class EnvFileSpecSchema(ApiModel):
    path: str
    promote_on_success: bool = False


class EnvFileRequestConfig(ApiModel):
    """Env file configuration for run creation."""

    source_dir: str | None = None
    files: list[EnvFileSpecSchema] | None = None


class CreateRunRequest(ApiModel):
    routine_id: str | None = None
    repo_name: str
    branch: str  # Source branch to base worktree on
    routine_embedded: dict[str, Any] | None = None
    config: dict[str, Any] = {}
    agent_type: str | None = None
    agent_config: dict[str, Any] = {}
    env_files: EnvFileRequestConfig | None = None
    merge_strategy: str | None = None

    @field_validator("agent_type", mode="before")
    @classmethod
    def validate_agent_type(cls, v: str | None) -> str | None:
        return _validate_agent_type(v)

    @field_validator("merge_strategy", mode="before")
    @classmethod
    def validate_merge_strategy(cls, v: str | None) -> str | None:
        if v is None:
            return v
        lowered = v.lower()
        if lowered not in _VALID_MERGE_STRATEGIES:
            raise ValueError(
                f"Invalid merge_strategy '{v}'. Valid options: {', '.join(_VALID_MERGE_STRATEGIES)}"
            )
        return lowered

    @model_validator(mode="after")
    def validate_routine_source(self) -> "CreateRunRequest":
        """Ensure exactly one of routine_id or routine_embedded is provided."""
        has_id = self.routine_id is not None
        has_embedded = self.routine_embedded is not None
        if has_id == has_embedded:  # both set or neither set
            raise ValueError("Exactly one of 'routine_id' or 'routine_embedded' must be provided")
        return self


class GradeSummaryItem(ApiModel):
    grade: str | None = None
    priority: str


class AttemptOutcome(ApiModel):
    attempt_num: int
    outcome: str | None = None


class TaskSummary(ApiModel):
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
    parent_task_id: str | None = None


class StepConditionSchema(ApiModel):
    when: str | None = None
    repeat_for: str | None = None


class StepSummary(ApiModel):
    id: str
    config_id: str
    title: str = ""
    completed: bool
    tasks: list[TaskSummary]
    has_approval_gate: bool = False
    approval_status: str | None = None  # "pending" | "approved" | "rejected" | None
    skipped: bool = False
    skip_reason: str | None = None
    condition: StepConditionSchema | None = None


class RunResponse(ApiModel):
    id: str
    repo_name: str
    status: str
    pause_reason: str | None = None
    last_error: str | None = None
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: str | None = None
    routine_embedded: dict[str, Any] | None = None
    routine_path: str | None = None
    routine_commit: str | None = None
    agent_type: str | None = None
    agent_type_display: str
    agent_icon: str
    agent_config: dict[str, Any] = {}
    verifier_model: str | None = None
    worktree_enabled: bool = True
    worktree_path: str | None = None
    worktree_relative_path: str | None = None
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
    total_num_actions: int = 0
    estimated_cost_usd: float | None = None
    cost_disclaimer: str | None = None


class RunListResponse(ApiModel):
    runs: list[RunResponse]


class GuidanceResponse(ApiModel):
    """Aggregate guidance for external agents."""

    run_id: str
    task_id: str | None = None
    prompt: str | None = None
    phase: str | None = None  # "building" or "verifying"
    mcp_url: str
    expected_actions: list[str]


class AgentCancelledRequest(ApiModel):
    """Request to cancel waiting for external agent."""

    reason: str | None = None


class BackwardTransitionRequest(ApiModel):
    """Request to transition backward to an earlier step."""

    target_step_index: int = Field(ge=0)
    reason: str | None = None


class ResumeRunRequest(ApiModel):
    """Request to resume a paused run, optionally changing the agent."""

    agent_type: str | None = None
    agent_config: dict[str, Any] | None = None
    resume_strategy: str | None = None  # "continue" | "reset_worktree"

    @field_validator("agent_type", mode="before")
    @classmethod
    def validate_agent_type(cls, v: str | None) -> str | None:
        return _validate_agent_type(v)

    @model_validator(mode="after")
    def validate_resume_strategy(self) -> "ResumeRunRequest":
        valid = ("continue", "reset_worktree")
        if self.resume_strategy is not None and self.resume_strategy not in valid:
            raise ValueError(f"resume_strategy must be one of {valid}")
        return self


class RecoverRequest(ApiModel):
    """Request to recover a failed run to a target task."""

    target_task_id: str
    additional_attempts: int = Field(default=1, ge=0)
    agent_type: str | None = None
    agent_config: dict[str, Any] | None = None
    preserve_checklist: bool = False
    guidance: str | None = None
    reset_branch: bool = True

    @field_validator("agent_type", mode="before")
    @classmethod
    def validate_agent_type(cls, v: str | None) -> str | None:
        return _validate_agent_type(v)


class RecoverResponse(ApiModel):
    """Response for run recovery."""

    run_id: str
    status: str
    pause_reason: str | None = None
    current_step_index: int | None = None


class MergeReadinessSnapshot(ApiModel):
    """Snapshot of merge readiness derived from branch status."""

    status: str  # "ready" | "conflicts" | "behind"
    blocking_reasons: list[str]


class BranchStatusResponse(ApiModel):
    """Response for branch status check."""

    behind_count: int
    ahead_count: int
    can_merge_cleanly: bool
    has_conflicts: bool
    source_branch: str
    run_branch: str
    predicted_conflict_count: int = 0
    merge_readiness: MergeReadinessSnapshot


class BackMergeResponse(ApiModel):
    """Response for back-merge operation."""

    status: str  # "clean" | "conflicts"
    merge_commit_sha: str | None = None
    conflict_files: list[str] = []
    conflict_count: int = 0
    # Backward-compatible aliases
    merge_commit: str | None = None
    message: str | None = None


class MergeBackRequest(ApiModel):
    """Request for merge-back operation."""

    strategy: Literal["squash", "merge"] | None = None
    dirty_action: Literal["stash", "commit"] | None = None


class MergeBackResponse(ApiModel):
    """Response for merge-back operation."""

    merge_commit: str
    strategy: str
    message: str


def get_agent_display_name(
    agent_type: AgentRunnerType | None, agent_config: dict[str, Any] | None = None
) -> str:
    """Get human-readable display name for an agent type.

    Args:
        agent_type: The agent type enum value, or None

    Returns:
        Display name string for the UI
    """
    if agent_type is None:
        return "No Agent"

    display_map = {
        AgentRunnerType.OPENHANDS_LOCAL: "OpenHands",
        AgentRunnerType.OPENHANDS_DOCKER: "OpenHands Docker",
        AgentRunnerType.CLI_SUBPROCESS: "Claude CLI",
        AgentRunnerType.USER_MANAGED: "External Agent",
        AgentRunnerType.CODEX_SERVER: "Codex Server",
    }
    display_name = display_map.get(agent_type, "Unknown Agent")
    if agent_type == AgentRunnerType.CLI_SUBPROCESS:
        command = (agent_config or {}).get("command")
        if isinstance(command, str) and command.strip():
            return f"{command} CLI"
    return display_name


def get_agent_icon(agent_type: AgentRunnerType | None) -> str:
    """Get icon key for an agent type.

    Args:
        agent_type: The agent type enum value, or None

    Returns:
        Icon key string for the UI
    """
    if agent_type is None:
        return "none"

    icon_map = {
        AgentRunnerType.OPENHANDS_LOCAL: "openhands",
        AgentRunnerType.OPENHANDS_DOCKER: "docker",
        AgentRunnerType.CLI_SUBPROCESS: "cli",
        AgentRunnerType.USER_MANAGED: "external",
        AgentRunnerType.CODEX_SERVER: "codex",
    }

    return icon_map.get(agent_type, "unknown")
