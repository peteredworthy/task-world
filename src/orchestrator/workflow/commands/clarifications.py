"""Command handlers for clarification request state."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from orchestrator.config.enums import TaskStatus
from orchestrator.workflow.events import (
    ApprovalDecision,
    ClarificationRequested,
    ClarificationResponded,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.workflow.events.types import WorkflowEvent


class RecordClarificationRequestCommand(BaseModel):
    run_id: str
    task_id: str
    request_id: str
    attempt_num: int
    questions: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    requested_at: datetime


async def handle_record_clarification_request(
    cmd: RecordClarificationRequestCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = ClarificationRequested(
        timestamp=cmd.requested_at,
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        request_id=cmd.request_id,
        attempt_num=cmd.attempt_num,
        question_count=len(cmd.questions),
        questions=cmd.questions,
    )
    await event_store.append([event])
    return [event]


class RecordClarificationResponseCommand(BaseModel):
    run_id: str
    task_id: str
    request_id: str
    response_id: str
    answers: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    responded_by: str
    responded_at: datetime
    new_status: TaskStatus | str
    run_config_delta: dict[str, Any] = Field(default_factory=dict)


async def handle_record_clarification_response(
    cmd: RecordClarificationResponseCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = ClarificationResponded(
        timestamp=cmd.responded_at,
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        request_id=cmd.request_id,
        response_id=cmd.response_id,
        answers=cmd.answers,
        responded_by=cmd.responded_by,
        responded_at=cmd.responded_at,
        new_status=cmd.new_status,
        run_config_delta=cmd.run_config_delta,
    )
    await event_store.append([event])
    return [event]


class RecordApprovalDecisionCommand(BaseModel):
    run_id: str
    task_id: str
    step_id: str
    approved: bool
    comment: str | None = None
    decided_by: str
    decided_at: datetime
    new_status: TaskStatus | str
    current_attempt: int | None = None
    checklist: list[dict[str, Any]] | None = None
    attempt_snapshots: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


async def handle_record_approval_decision(
    cmd: RecordApprovalDecisionCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = ApprovalDecision(
        timestamp=cmd.decided_at,
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        step_id=cmd.step_id,
        approved=cmd.approved,
        comment=cmd.comment,
        decided_by=cmd.decided_by,
        new_status=cmd.new_status,
        current_attempt=cmd.current_attempt,
        checklist=cmd.checklist,
        attempt_snapshots=cmd.attempt_snapshots,
    )
    await event_store.append([event])
    return [event]
