"""Run API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from orchestrator.api.schemas.base import ApiModel
from orchestrator.api.schemas.tasks import ActionLogSchema, AttemptSchema, ModelTokenUsageSchema

from orchestrator.config.enums import AgentRunnerType, MergeStrategy


_VALID_AGENT_TYPES = [e.value for e in AgentRunnerType]
_VALID_MERGE_STRATEGIES = [e.value for e in MergeStrategy]
_VALID_EXECUTION_MODES = ["legacy", "graph"]


def _validate_agent_runner_type(v: str | None) -> str | None:
    """Validate and normalize agent_runner_type (case-insensitive)."""
    if v is None:
        return v
    lowered = v.lower()
    if lowered not in _VALID_AGENT_TYPES:
        raise ValueError(
            f"Invalid agent_runner_type '{v}'. Valid options: {', '.join(_VALID_AGENT_TYPES)}"
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
    agent_runner_type: str | None = None
    agent_runner_config: dict[str, Any] = {}
    env_files: EnvFileRequestConfig | None = None
    merge_strategy: str | None = None
    execution_mode: str | None = None

    @field_validator("agent_runner_type", mode="before")
    @classmethod
    def validate_agent_runner_type(cls, v: str | None) -> str | None:
        return _validate_agent_runner_type(v)

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

    @field_validator("execution_mode", mode="before")
    @classmethod
    def validate_execution_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        lowered = v.lower()
        if lowered not in _VALID_EXECUTION_MODES:
            raise ValueError(
                f"Invalid execution_mode '{v}'. Valid options: {', '.join(_VALID_EXECUTION_MODES)}"
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


class CreateChildRunRequest(ApiModel):
    """Create a child run linked to an oversight parent run."""

    routine_id: str | None = None
    routine_embedded: dict[str, Any] | None = None
    repo_name: str | None = None
    branch: str | None = None
    config: dict[str, Any] = {}
    agent_runner_type: str | None = None
    agent_runner_config: dict[str, Any] = {}
    env_files: EnvFileRequestConfig | None = None
    merge_strategy: str | None = None
    execution_mode: str | None = None
    parent_slice_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    next_action_decision: Literal[
        "continue",
        "replan",
        "stop",
        "environment_blocked",
    ] = "continue"

    @field_validator("agent_runner_type", mode="before")
    @classmethod
    def validate_agent_runner_type(cls, v: str | None) -> str | None:
        return _validate_agent_runner_type(v)

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

    @field_validator("execution_mode", mode="before")
    @classmethod
    def validate_execution_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        lowered = v.lower()
        if lowered not in _VALID_EXECUTION_MODES:
            raise ValueError(
                f"Invalid execution_mode '{v}'. Valid options: {', '.join(_VALID_EXECUTION_MODES)}"
            )
        return lowered

    @model_validator(mode="after")
    def validate_routine_source(self) -> "CreateChildRunRequest":
        has_id = self.routine_id is not None
        has_embedded = self.routine_embedded is not None
        if has_id == has_embedded:
            raise ValueError("Exactly one of 'routine_id' or 'routine_embedded' must be provided")
        return self


class EvidenceCommandSchema(ApiModel):
    command: str
    exit_code: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""


class EvidenceTestResultSchema(ApiModel):
    name: str
    status: Literal["passed", "failed", "skipped", "not_run"]
    details: str = ""


class EvidenceBundleSchema(ApiModel):
    """Planner-facing run.evidence.v1 bundle."""

    schema_version: Literal["run.evidence.v1"]
    slice_id: str
    routine_id: str
    assumption_tested: str
    summary: str
    commands_run: list[EvidenceCommandSchema]
    test_results: list[EvidenceTestResultSchema]
    target_bug_reproduced: Literal["reproduced", "not_reproduced", "not_targeted", "unknown"]
    real_frontend_path_exercised: bool
    real_execution_surface: str
    files_changed: list[str]
    evidence_files: list[str]
    open_uncertainties: list[str]
    next_recommendation: Literal["proceed", "replan", "stop", "environment_blocked"]
    outcome: Literal[
        "verified_fix",
        "bug_not_reproduced",
        "behavior_already_correct",
        "environment_blocked",
        "needs_revision",
        "partial_progress",
        "unrelated_failure",
    ]


class RunEvidenceItem(ApiModel):
    path: str
    bundle: EvidenceBundleSchema


class EvidenceValidationIssueSchema(ApiModel):
    field: str
    message: str


class InvalidEvidenceItem(ApiModel):
    path: str
    errors: list[EvidenceValidationIssueSchema]


class RunEvidenceResponse(ApiModel):
    run_id: str
    evidence: list[RunEvidenceItem]
    invalid_evidence: list[InvalidEvidenceItem] = Field(default_factory=list[InvalidEvidenceItem])


class ParentOversightResponse(ApiModel):
    run_id: str
    oversight_state: dict[str, Any]


class TargetInventoryItemSchema(ApiModel):
    """Parent-authored target inventory item for super-parent oversight."""

    schema_version: Literal["super_parent.target_inventory.v1"] = "super_parent.target_inventory.v1"
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    in_scope: bool = True
    resolved: bool = False


class FinalValidationMarkerSchema(ApiModel):
    """Parent-authored integrated validation marker."""

    schema_version: Literal["super_parent.final_validation.v1"] = "super_parent.final_validation.v1"
    passed: bool
    integration_scope: Literal["integrated", "final"] = "integrated"
    integrated_commit_sha: str = Field(min_length=7)
    report_path: str = Field(min_length=1)
    commands_run: list[EvidenceCommandSchema] = Field(min_length=1)
    evidence_files: list[str] = Field(min_length=1)


class ParentOversightUpdateRequest(ApiModel):
    """Durable parent-authored facts to merge into the oversight payload."""

    current_understanding: dict[str, Any] | None = None
    target_inventory: list[TargetInventoryItemSchema] | None = None
    final_validation: FinalValidationMarkerSchema | None = None
    decisions: list[dict[str, Any]] | None = None
    decision: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize_single_decision(self) -> "ParentOversightUpdateRequest":
        if self.decision is not None:
            if self.decisions is None:
                self.decisions = [self.decision]
            else:
                self.decisions.append(self.decision)
        return self


class AcceptChildRunResponse(ApiModel):
    parent_run_id: str
    child_run_id: str
    status: Literal["clean", "conflicts"]
    merge_commit_sha: str | None = None
    conflict_files: list[str] = []
    conflict_count: int = 0
    oversight_state: dict[str, Any]


class ResolveChildRunRequest(ApiModel):
    resolution: Literal["reject", "abandon"]
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class ResolveChildRunResponse(ApiModel):
    parent_run_id: str
    child_run_id: str
    resolution: Literal["reject", "abandon"]
    reason: str
    resolved_at: datetime
    oversight_state: dict[str, Any]


class ChildRunListResponse(ApiModel):
    parent_run_id: str
    children: list["RunResponse"]


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
    is_graph_backed: bool = False
    execution_mode: str = "legacy"
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: str | None = None
    routine_embedded: dict[str, Any] | None = None
    routine_path: str | None = None
    routine_commit: str | None = None
    parent_run_id: str | None = None
    parent_slice_id: str | None = None
    oversight_state: dict[str, Any] = {}
    agent_runner_type: str | None = None
    agent_runner_type_display: str
    agent_icon: str
    agent_runner_config: dict[str, Any] = {}
    verifier_model: str | None = None
    worktree_enabled: bool = True
    worktree_path: str | None = None
    worktree_relative_path: str | None = None
    source_branch: str | None = None
    source_branch_sha: str | None = None
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
    agent_runner_started_at: datetime | None = None
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
    token_usage_by_model: list[ModelTokenUsageSchema] = []
    estimated_cost_usd: float | None = None
    cost_disclaimer: str | None = None


class RunListResponse(ApiModel):
    runs: list[RunResponse]


class RunTracePhase(ApiModel):
    phase: Literal["builder", "verifier"]
    prompt: str | None = None
    note: str | None = None
    message_count: int = 0
    action_sequence_start: int | None = None
    action_sequence_end: int | None = None


class RunTraceAttempt(ApiModel):
    step_index: int
    step_id: str
    step_config_id: str
    step_title: str = ""
    task_id: str
    task_config_id: str
    task_title: str = ""
    task_status: str
    task_current_attempt: int
    task_max_attempts: int
    attempt: AttemptSchema
    phases: list[RunTracePhase] = []
    action_log: ActionLogSchema | None = None


class RunTraceResponse(ApiModel):
    run_id: str
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
    token_usage_by_model: list[ModelTokenUsageSchema] = []
    attempts: list[RunTraceAttempt]


class BackwardTransitionRequest(ApiModel):
    """Request to transition backward to an earlier step."""

    target_step_index: int = Field(ge=0)
    reason: str | None = None


class ResumeRunRequest(ApiModel):
    """Request to resume a paused run, optionally changing the agent."""

    agent_runner_type: str | None = None
    agent_runner_config: dict[str, Any] | None = None
    resume_strategy: str | None = None  # "continue" | "reset_worktree"

    @field_validator("agent_runner_type", mode="before")
    @classmethod
    def validate_agent_runner_type(cls, v: str | None) -> str | None:
        return _validate_agent_runner_type(v)

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
    agent_runner_type: str | None = None
    agent_runner_config: dict[str, Any] | None = None
    preserve_checklist: bool = False
    guidance: str | None = None
    reset_branch: bool = True

    @field_validator("agent_runner_type", mode="before")
    @classmethod
    def validate_agent_runner_type(cls, v: str | None) -> str | None:
        return _validate_agent_runner_type(v)


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


def get_agent_runner_display_name(
    agent_runner_type: AgentRunnerType | None, agent_runner_config: dict[str, Any] | None = None
) -> str:
    """Get human-readable display name for an agent runner type.

    Args:
        agent_runner_type: The agent runner type enum value, or None

    Returns:
        Display name string for the UI
    """
    if agent_runner_type is None:
        return "No Agent Runner"

    display_map = {
        AgentRunnerType.OPENHANDS_LOCAL: "OpenHands",
        AgentRunnerType.OPENHANDS_DOCKER: "OpenHands Docker",
        AgentRunnerType.CLI_SUBPROCESS: "Claude CLI",
        AgentRunnerType.CODEX_SERVER: "Codex Server",
        AgentRunnerType.CLAUDE_SDK: "Claude SDK",
    }
    display_name = display_map.get(agent_runner_type, "Unknown Agent Runner")
    if agent_runner_type == AgentRunnerType.CLI_SUBPROCESS:
        command = (agent_runner_config or {}).get("command")
        if isinstance(command, str) and command.strip():
            return f"{command} CLI"
    return display_name


def get_agent_runner_icon(agent_runner_type: AgentRunnerType | None) -> str:
    """Get icon key for an agent runner type.

    Args:
        agent_runner_type: The agent runner type enum value, or None

    Returns:
        Icon key string for the UI
    """
    if agent_runner_type is None:
        return "none"

    icon_map = {
        AgentRunnerType.OPENHANDS_LOCAL: "openhands",
        AgentRunnerType.OPENHANDS_DOCKER: "docker",
        AgentRunnerType.CLI_SUBPROCESS: "cli",
        AgentRunnerType.CODEX_SERVER: "codex",
        AgentRunnerType.CLAUDE_SDK: "claude",
    }

    return icon_map.get(agent_runner_type, "unknown")
