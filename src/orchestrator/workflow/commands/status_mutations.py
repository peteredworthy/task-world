"""Command handlers for run/task status transitions and step-index rewind."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.workflow.events import RunStatusChanged, StepIndexRewound, TaskStatusChanged

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.workflow.events.types import WorkflowEvent


class UpdateRunStatusCommand(BaseModel):
    run_id: str
    old_status: RunStatus
    new_status: RunStatus
    pause_reason: str | None = None
    last_error: str | None = None
    timestamp: datetime | None = None


async def handle_update_run_status(
    cmd: UpdateRunStatusCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunStatusChanged(
        **({"timestamp": cmd.timestamp} if cmd.timestamp is not None else {}),
        run_id=cmd.run_id,
        event_type="run_status_changed",
        old_status=cmd.old_status,
        new_status=cmd.new_status,
        pause_reason=cmd.pause_reason,
        last_error=cmd.last_error,
    )
    await event_store.append([event])
    return [event]


class UpdateTaskStatusCommand(BaseModel):
    run_id: str
    task_id: str
    old_status: TaskStatus
    new_status: TaskStatus


async def handle_update_task_status(
    cmd: UpdateTaskStatusCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = TaskStatusChanged(
        run_id=cmd.run_id,
        event_type="task_status_changed",
        task_id=cmd.task_id,
        old_status=cmd.old_status,
        new_status=cmd.new_status,
    )
    await event_store.append([event])
    return [event]


class RewindStepIndexCommand(BaseModel):
    run_id: str
    target_step_index: int


async def handle_rewind_step_index(
    cmd: RewindStepIndexCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = StepIndexRewound(
        run_id=cmd.run_id,
        target_step_index=cmd.target_step_index,
    )
    await event_store.append([event])
    return [event]
