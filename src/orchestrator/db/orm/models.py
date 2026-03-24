"""SQLAlchemy ORM models for persistent storage."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.db.orm.base import Base


@dataclass
class AttemptRecord:
    """Canonical attempt record shape, usable across all task types.

    Works for: normal tasks, fan-out children, script tasks, recovery retries.
    attempt_num provides ordering within a task; attempt_id is globally unique
    and maps to a Temporal Activity ID.
    """

    attempt_num: int
    attempt_id: str
    task_id: str = ""
    outcome: str | None = None  # "passed", "revision_needed", "failed"
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=lambda: {})


class RunModel(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repo_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    pause_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

    # Routine reference
    routine_id: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_source: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_embedded: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Routine traceability (for project routines)
    routine_path: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_commit: Mapped[str | None] = mapped_column(String, nullable=True)

    # Runner configuration
    runner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    runner_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verifier_model: Mapped[str | None] = mapped_column(String, nullable=True)

    # Worktree
    worktree_enabled: Mapped[bool] = mapped_column(Integer, default=1)  # SQLite has no bool
    worktree_path: Mapped[str | None] = mapped_column(String, nullable=True)
    delete_worktree_on_completion: Mapped[bool] = mapped_column(Integer, default=0)
    source_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    merge_strategy: Mapped[str | None] = mapped_column(String, nullable=True)

    # Config passed to routine
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Environment files
    env_file_specs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    env_source_dir: Mapped[str | None] = mapped_column(String, nullable=True)

    # Runtime state
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runner_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_resume_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Aggregate metrics
    total_tokens_read: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_write: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_cache: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_num_actions: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    steps: Mapped[list["StepModel"]] = relationship(
        "StepModel",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="StepModel.order_index",
    )

    events: Mapped[list["EventModel"]] = relationship(
        "EventModel",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EventModel.id",
    )


class StepModel(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    config_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Integer, default=0)

    # Human approval (stored as JSON)
    human_approval: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Conditional step fields
    skipped: Mapped[bool] = mapped_column(Integer, default=0)
    skip_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    run: Mapped["RunModel"] = relationship("RunModel", back_populates="steps")
    tasks: Mapped[list["TaskModel"]] = relationship(
        "TaskModel",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="TaskModel.order_index",
    )


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    step_id: Mapped[str] = mapped_column(
        String, ForeignKey("steps.id", ondelete="CASCADE"), nullable=False
    )
    config_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    complexity: Mapped[str] = mapped_column(String, nullable=False, default="standard")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    current_attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    # Pending action tracking
    pending_action_type: Mapped[str | None] = mapped_column(String, nullable=True)
    pending_clarification_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Fan-out fields
    parent_task_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("tasks.id"), nullable=True, default=None
    )
    fan_out_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    fan_out_input: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    fan_out_output: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    child_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    # Relationships
    step: Mapped["StepModel"] = relationship("StepModel", back_populates="tasks")
    attempts: Mapped[list["AttemptModel"]] = relationship(
        "AttemptModel",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="AttemptModel.attempt_num",
    )


class AttemptModel(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_num: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    builder_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    verifier_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    verifier_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    tokens_read: Mapped[int] = mapped_column(Integer, default=0)
    tokens_write: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    num_actions: Mapped[int] = mapped_column(Integer, default=0)
    grade_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    auto_verify_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # Runner snapshot
    runner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_model: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Agent output capture
    agent_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Git tracking - commit SHAs for builder/verifier handoff
    start_commit: Mapped[str | None] = mapped_column(String, nullable=True)
    end_commit: Mapped[str | None] = mapped_column(String, nullable=True)

    # Structured action log (tool calls, text, metrics)
    action_log_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    task: Mapped["TaskModel"] = relationship("TaskModel", back_populates="attempts")


class EventModel(Base):
    __tablename__ = "events"
    __table_args__ = (
        # Composite index for the common paginated-activity query: WHERE run_id = ? AND event_type = ?
        Index("ix_events_run_id_event_type", "run_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Relationships
    run: Mapped["RunModel"] = relationship("RunModel", back_populates="events")


class ClarificationRequestModel(Base):
    __tablename__ = "clarification_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    attempt_num: Mapped[int] = mapped_column(Integer, nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    run: Mapped["RunModel"] = relationship("RunModel")
    response: Mapped["ClarificationResponseModel | None"] = relationship(
        "ClarificationResponseModel",
        back_populates="request",
        uselist=False,
    )


class RunnerProfileDefaultModel(Base):
    __tablename__ = "runner_profile_defaults"
    __table_args__ = (UniqueConstraint("runner_type", "profile", name="uq_runner_profile"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    runner_type: Mapped[str] = mapped_column(String, nullable=False)
    profile: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)


class ReplayCheckpointModel(Base):
    __tablename__ = "replay_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    journal_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    last_applied_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_applied_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    backup_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PendingSignalModel(Base):
    __tablename__ = "pending_signals"
    __table_args__ = (
        # Index for fast drain queries: unprocessed signals for a given run
        Index("ix_pending_signals_run_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ClarificationResponseModel(Base):
    __tablename__ = "clarification_responses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("clarification_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    responded_by: Mapped[str] = mapped_column(String, nullable=False)
    responded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    request: Mapped["ClarificationRequestModel"] = relationship(
        "ClarificationRequestModel", back_populates="response"
    )
