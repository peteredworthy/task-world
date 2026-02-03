"""Runtime state Pydantic models for runs, steps, tasks, and attempts."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from orchestrator.config.enums import (
    AgentType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)


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


class TaskState(BaseModel):
    """Runtime state of a task."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    status: TaskStatus = TaskStatus.PENDING
    checklist: list[ChecklistItem] = Field(default_factory=lambda: [])
    attempts: list[Attempt] = Field(default_factory=lambda: [])
    current_attempt: int = 0
    max_attempts: int = 3


class StepState(BaseModel):
    """Runtime state of a step."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    tasks: list[TaskState] = Field(default_factory=lambda: [])
    completed: bool = False


class Run(BaseModel):
    """Runtime state of an entire run."""

    id: str = Field(default_factory=generate_id)
    project_id: str
    status: RunStatus = RunStatus.DRAFT

    # Routine reference
    routine_id: str | None = None
    routine_sha: str | None = None
    routine_source: RoutineSource | None = None

    # Agent configuration
    agent_type: AgentType | None = None
    agent_config: dict[str, Any] = Field(default_factory=lambda: {})

    # Worktree
    worktree_enabled: bool = True
    worktree_path: str | None = None
    delete_worktree_on_completion: bool = False

    # Config passed to routine
    config: dict[str, Any] = Field(default_factory=lambda: {})

    # Runtime state
    steps: list[StepState] = Field(default_factory=lambda: [])
    current_step_index: int = 0

    # Timestamps
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Aggregate metrics
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
