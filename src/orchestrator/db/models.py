"""SQLAlchemy ORM models for persistent storage."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.db.base import Base


class RunModel(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Routine reference
    routine_id: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    routine_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # Agent configuration
    agent_type: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Worktree
    worktree_enabled: Mapped[bool] = mapped_column(Integer, default=1)  # SQLite has no bool
    worktree_path: Mapped[str | None] = mapped_column(String, nullable=True)
    delete_worktree_on_completion: Mapped[bool] = mapped_column(Integer, default=0)

    # Config passed to routine
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Runtime state
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Aggregate metrics
    total_tokens_read: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_write: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_cache: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)

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
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Integer, default=0)

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
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    current_attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

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

    # Relationships
    task: Mapped["TaskModel"] = relationship("TaskModel", back_populates="attempts")


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Relationships
    run: Mapped["RunModel"] = relationship("RunModel", back_populates="events")
