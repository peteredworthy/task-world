"""Runtime state Pydantic models for runs, steps, tasks, and attempts."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from orchestrator.runners.action_log import ActionLog
from orchestrator.config.enums import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.envfiles.models import EnvFileSpec


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChecklistItem(BaseModel):
    """Runtime state of a single requirement."""

    req_id: str
    desc: str
    priority: Priority
    status: ChecklistStatus = ChecklistStatus.OPEN
    note: str | None = None
    grade: str | None = None
    grade_reason: str | None = None


class AttemptMetrics(BaseModel):
    """Metrics for a single attempt."""

    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0
    num_actions: int = 0


class GradeSnapshotItem(BaseModel):
    """Snapshot of a single checklist item's grade and builder note at attempt completion."""

    req_id: str
    grade: str | None = None
    grade_reason: str | None = None
    note: str | None = None


class Attempt(BaseModel):
    """A single builder-verifier cycle."""

    id: str = Field(default_factory=generate_id)
    attempt_num: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    outcome: str | None = None  # "passed", "revision_needed", "failed"
    metrics: AttemptMetrics = Field(default_factory=AttemptMetrics)
    grade_snapshot: list[GradeSnapshotItem] = Field(default_factory=lambda: [])
    auto_verify_results: list[dict[str, Any]] = Field(default_factory=lambda: [])

    # Agent snapshot - record what agent was used for this attempt
    agent_type: AgentRunnerType | None = None
    agent_model: str | None = None  # e.g. "claude-sonnet-4-5-20250514"
    agent_settings: dict[str, Any] = Field(default_factory=dict)

    # Agent output capture
    agent_output: str | None = None  # Final captured output (joined lines)
    error: str | None = None  # Error message if agent failed

    # Structured action log (tool calls, text, metrics)
    action_log: ActionLog | None = None

    # Git tracking - commit SHAs for builder/verifier handoff
    start_commit: str | None = None  # Commit at attempt start
    end_commit: str | None = None  # Commit at attempt end (after builder)


class TaskState(BaseModel):
    """Runtime state of a task."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    title: str = ""
    status: TaskStatus = TaskStatus.PENDING
    complexity: str = "standard"
    checklist: list[ChecklistItem] = Field(default_factory=lambda: [])
    attempts: list[Attempt] = Field(default_factory=lambda: [])
    current_attempt: int = 0
    max_attempts: int = 3
    pending_action_type: str | None = None  # "clarification" | "approval"
    pending_clarification_id: str | None = None
    has_verification: bool = True  # False if task has no auto_verify items and no verifier rubric


class HumanApproval(BaseModel):
    """Record of human gate approval."""

    approved_by: str
    approved_at: datetime
    comment: str | None = None


class StepState(BaseModel):
    """Runtime state of a step."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    title: str = ""
    tasks: list[TaskState] = Field(default_factory=lambda: [])
    completed: bool = False
    human_approval: HumanApproval | None = None


class TransitionTracker(BaseModel):
    """Track backward transitions to prevent infinite loops."""

    counts: dict[str, int] = Field(default_factory=dict)

    def record_transition(self, from_step: str, to_step: str) -> None:
        """Record a transition from one step to another."""
        key = f"{from_step}->{to_step}"
        self.counts[key] = self.counts.get(key, 0) + 1

    def can_transition(self, from_step: str, to_step: str, max_iterations: int) -> bool:
        """Check if a transition can occur without exceeding max iterations."""
        key = f"{from_step}->{to_step}"
        return self.counts.get(key, 0) < max_iterations

    def get_count(self, from_step: str, to_step: str) -> int:
        """Get the number of times a transition has occurred."""
        key = f"{from_step}->{to_step}"
        return self.counts.get(key, 0)

    model_config = {"arbitrary_types_allowed": True}


class Run(BaseModel):
    """Runtime state of an entire run."""

    id: str = Field(default_factory=generate_id)
    repo_name: str
    status: RunStatus = RunStatus.DRAFT
    pause_reason: str | None = None  # e.g., "agent_died", "manual_pause"
    last_error: str | None = None  # Human-readable error detail when paused due to error

    # Routine reference
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: RoutineSource | None = None
    routine_embedded: dict[str, Any] | None = None

    # Routine traceability (for project routines)
    routine_path: str | None = None  # Path within repo (e.g., "routines/feature.yaml")
    routine_commit: str | None = None  # Commit SHA when routine was read

    # Agent configuration
    agent_type: AgentRunnerType | None = None
    agent_config: dict[str, Any] = Field(default_factory=lambda: {})
    verifier_model: str | None = None  # Pinned at run creation; verifier always uses this model

    # Worktree
    worktree_enabled: bool = True
    worktree_path: str | None = None
    delete_worktree_on_completion: bool = False
    source_branch: str | None = None
    merge_strategy: str = "squash"

    # Config passed to routine
    config: dict[str, Any] = Field(default_factory=lambda: {})

    # Environment files
    env_file_specs: list[EnvFileSpec] = Field(default_factory=lambda: [])
    env_source_dir: str | None = None

    # Runtime state
    steps: list[StepState] = Field(default_factory=lambda: [])
    current_step_index: int = 0
    transition_tracker: TransitionTracker | None = Field(default_factory=TransitionTracker)

    # Timestamps
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    agent_started_at: datetime | None = None

    # Aggregate metrics
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
