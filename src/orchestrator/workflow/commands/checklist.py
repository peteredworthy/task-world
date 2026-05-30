"""Command handlers for checklist item updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from orchestrator.config.enums import ChecklistStatus
from orchestrator.workflow.events import ChecklistItemGraded, ChecklistItemUpdated

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.workflow.events.types import WorkflowEvent


class UpdateChecklistItemCommand(BaseModel):
    run_id: str
    task_id: str
    req_id: str
    status: ChecklistStatus | str
    note: str | None = None


async def handle_update_checklist_item(
    cmd: UpdateChecklistItemCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = ChecklistItemUpdated(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        req_id=cmd.req_id,
        status=cmd.status,
        note=cmd.note,
    )
    await event_store.append([event])
    return [event]


class SetChecklistGradeCommand(BaseModel):
    run_id: str
    task_id: str
    req_id: str
    grade: str
    grade_reason: str | None = None


async def handle_set_checklist_grade(
    cmd: SetChecklistGradeCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = ChecklistItemGraded(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        req_id=cmd.req_id,
        grade=cmd.grade,
        grade_reason=cmd.grade_reason,
    )
    await event_store.append([event])
    return [event]
