"""SQLAlchemy ORM models for persistent storage."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

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
    execution_mode: Mapped[str] = mapped_column(String, nullable=False, default="legacy")

    # Routine reference
    routine_id: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_source: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_embedded: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Routine traceability (for project routines)
    routine_path: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_commit: Mapped[str | None] = mapped_column(String, nullable=True)

    # Oversight parent/child orchestration
    parent_run_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("runs.id"), nullable=True, index=True
    )
    parent_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_slice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    oversight_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Runner configuration
    runner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    runner_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verifier_model: Mapped[str | None] = mapped_column(String, nullable=True)

    # Worktree
    worktree_enabled: Mapped[bool] = mapped_column(Integer, default=1)  # SQLite has no bool
    worktree_path: Mapped[str | None] = mapped_column(String, nullable=True)
    delete_worktree_on_completion: Mapped[bool] = mapped_column(Integer, default=0)
    source_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    source_branch_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    merge_strategy: Mapped[str | None] = mapped_column(String, nullable=True)

    # Config passed to routine
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Environment files
    env_file_specs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    env_source_dir: Mapped[str | None] = mapped_column(String, nullable=True)

    # Runtime state
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    transition_tracker: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )

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

    # Per-model token usage breakdown (JSON array of ModelTokenUsage dicts)
    token_usage_by_model: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=None
    )

    # Relationships
    steps: Mapped[list["StepModel"]] = relationship(
        "StepModel",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="StepModel.order_index",
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
    has_verification: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

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

    # Optimistic locking — incremented by SQLAlchemy on every UPDATE
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": version}

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
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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

    # Per-model token usage breakdown (JSON array of ModelTokenUsage dicts)
    token_usage_by_model: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=None
    )

    # Structured action log (tool calls, text, metrics)
    action_log_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    task: Mapped["TaskModel"] = relationship("TaskModel", back_populates="attempts")


class CostRecordModel(Base):
    __tablename__ = "cost_records"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "task_id",
            "attempt_num",
            "agent_runner_type",
            "phase",
            name="uq_cost_records_execution",
        ),
        Index("idx_cost_records_run", "run_id"),
        Index("idx_cost_records_mode", "agent_runner_type", "mode_tag"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    attempt_num: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_runner_type: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    mode_tag: Mapped[str] = mapped_column(String, nullable=False, default="default")
    model_name: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    token_usage_by_model: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InteractionLogArtifactModel(Base):
    __tablename__ = "interaction_log_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "task_id",
            "attempt_num",
            "agent_runner_type",
            "phase",
            name="uq_interaction_log_artifacts_execution",
        ),
        Index("idx_interaction_log_artifacts_run", "run_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    cost_record_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("cost_records.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    attempt_num: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_runner_type: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    artifact_kind: Mapped[str] = mapped_column(
        String, nullable=False, default="agent_interaction_log"
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_log_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EventV2PayloadModel(Base):
    """Large JSON envelope for an events_v2 metadata row."""

    __tablename__ = "events_v2_payloads"

    position: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("events_v2.position", ondelete="CASCADE"),
        primary_key=True,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string


class EventV2Model(Base):
    """Authoritative append-only workflow event row.

    ``position`` is the durable global ordering key. ``version`` is the
    per-aggregate event sequence, not a SQLAlchemy optimistic-lock column. The
    proof path uses ``(aggregate_id, version)`` as its stable retry/import
    duplicate-detection identity.
    """

    __tablename__ = "events_v2"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "version", name="uq_events_v2_aggregate_version"),
        Index("idx_events_v2_aggregate", "aggregate_id", "position"),
        Index("idx_events_v2_type", "event_type", "position"),
    )

    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[str] = mapped_column(String, nullable=False)  # ISO 8601
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = column_property(
        select(EventV2PayloadModel.payload)
        .where(EventV2PayloadModel.position == position)
        .correlate_except(EventV2PayloadModel)
        .scalar_subquery()
    )


class GraphOutboxModel(Base):
    """Transactional side-effect intent emitted from accepted graph events."""

    __tablename__ = "graph_outbox"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_graph_outbox_event_id"),
        Index("idx_graph_outbox_status_id", "status", "outbox_id"),
        Index("idx_graph_outbox_run", "run_id", "outbox_id"),
    )

    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectionCheckpointModel(Base):
    __tablename__ = "projection_checkpoints"

    projector_name: Mapped[str] = mapped_column(String, primary_key=True)
    last_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)  # ISO 8601


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


class AgentRunnerModelProfileDefaultModel(Base):
    __tablename__ = "agent_runner_model_profile_defaults"
    __table_args__ = (
        UniqueConstraint("runner_type", "profile", name="uq_agent_runner_model_profile"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    runner_type: Mapped[str] = mapped_column(String, nullable=False)
    profile: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)


class RoutineMetaModel(Base):
    """Stores user-managed metadata for routines (e.g. archive status).

    Routines are discovered from YAML files and have no primary DB record.
    This table stores supplementary metadata keyed by (routine_id, source).
    """

    __tablename__ = "routine_meta"
    __table_args__ = (UniqueConstraint("routine_id", "source", name="uq_routine_meta_id_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routine_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Integer, default=0, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
