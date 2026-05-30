"""Command handlers for step gate state."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from orchestrator.workflow.events import StepHumanApprovalRecorded

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.workflow.events.types import WorkflowEvent


class RecordStepHumanApprovalCommand(BaseModel):
    run_id: str
    step_id: str
    approved_by: str
    approved_at: datetime
    comment: str | None = None


async def handle_record_step_human_approval(
    cmd: RecordStepHumanApprovalCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = StepHumanApprovalRecorded(
        run_id=cmd.run_id,
        step_id=cmd.step_id,
        approved_by=cmd.approved_by,
        approved_at=cmd.approved_at,
        comment=cmd.comment,
    )
    await event_store.append([event])
    return [event]
