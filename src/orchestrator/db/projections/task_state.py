"""TaskStateProjector: maintains tasks, attempts read-model tables from events."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import TaskStatus
from orchestrator.db.orm.models import AttemptModel, StepModel, TaskModel
from orchestrator.workflow import (
    ApprovalDecision,
    ApprovalRequested,
    AttemptUpdated,
    AutoVerifyCompleted,
    ChildCompleted,
    ChildFailed,
    ChildSpawned,
    ChecklistItemGraded,
    ChecklistItemUpdated,
    ClarificationRequested,
    ClarificationResponded,
    FanOutChildrenCreated,
    FanOutChildrenReset,
    FanOutChildRetried,
    FanOutCompleted,
    FanOutSpawned,
    RunStepBackward,
    TaskAttemptCreated,
    TaskCreated,
    TaskReverted,
    TaskStatusChanged,
    WorkflowEvent,
)

logger = logging.getLogger(__name__)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _attempt_from_snapshot(task_id: str, snapshot: dict[str, Any]) -> AttemptModel:
    return AttemptModel(
        task_id=task_id,
        **_attempt_values_from_snapshot(snapshot),
    )


def _attempt_values_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw_metrics = snapshot.get("metrics")
    metrics = cast(dict[str, Any], raw_metrics) if isinstance(raw_metrics, dict) else {}
    return {
        "id": snapshot["id"],
        "attempt_num": snapshot.get("attempt_num", 0),
        "attempt_id": snapshot.get("id"),
        "started_at": _parse_datetime(snapshot.get("started_at")),
        "completed_at": _parse_datetime(snapshot.get("completed_at")),
        "paused_at": _parse_datetime(snapshot.get("paused_at")),
        "builder_prompt": snapshot.get("builder_prompt"),
        "verifier_prompt": snapshot.get("verifier_prompt"),
        "verifier_comment": snapshot.get("verifier_comment"),
        "outcome": snapshot.get("outcome"),
        "tokens_read": cast(int, metrics.get("tokens_read", 0)),
        "tokens_write": cast(int, metrics.get("tokens_write", 0)),
        "tokens_cache": cast(int, metrics.get("tokens_cache", 0)),
        "duration_ms": cast(int, metrics.get("duration_ms", 0)),
        "num_actions": cast(int, metrics.get("num_actions", 0)),
        "grade_snapshot": snapshot.get("grade_snapshot") or None,
        "auto_verify_results": snapshot.get("auto_verify_results") or None,
        "token_usage_by_model": snapshot.get("token_usage_by_model") or None,
        "runner_type": snapshot.get("agent_runner_type"),
        "agent_model": snapshot.get("agent_model"),
        "agent_settings": snapshot.get("agent_settings") or None,
        "agent_output": snapshot.get("agent_output"),
        "error": snapshot.get("error"),
        "action_log_json": snapshot.get("action_log"),
        "start_commit": snapshot.get("start_commit"),
        "end_commit": snapshot.get("end_commit"),
    }


async def _upsert_attempt_snapshots(
    session: AsyncSession,
    task_id: str,
    snapshots: list[dict[str, Any]],
) -> None:
    for snapshot in snapshots:
        if not snapshot.get("id"):
            continue
        values = _attempt_values_from_snapshot(snapshot)
        existing = await session.get(AttemptModel, values["id"])
        if existing is None:
            session.add(AttemptModel(task_id=task_id, **values))
            continue
        for field_name, value in values.items():
            setattr(existing, field_name, value)


class TaskStateProjector:
    """Maintains tasks and attempts tables from task-lifecycle events."""

    handled_events: frozenset[type] = frozenset(
        {
            TaskCreated,
            TaskStatusChanged,
            ChecklistItemGraded,
            ChecklistItemUpdated,
            AutoVerifyCompleted,
            ClarificationRequested,
            ClarificationResponded,
            ApprovalRequested,
            ApprovalDecision,
            TaskReverted,
            FanOutSpawned,
            ChildSpawned,
            ChildCompleted,
            ChildFailed,
            FanOutCompleted,
            TaskAttemptCreated,
            AttemptUpdated,
            FanOutChildrenCreated,
            FanOutChildrenReset,
            FanOutChildRetried,
            RunStepBackward,
        }
    )

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        match event:
            case TaskCreated():
                complexity = event.complexity or "standard"
                import json

                await session.execute(
                    text(
                        "INSERT OR IGNORE INTO tasks"
                        " (id, step_id, config_id, title, complexity, order_index,"
                        " status, checklist, current_attempt, max_attempts, version,"
                        " has_verification, pending_action_type, pending_clarification_id,"
                        " parent_task_id, fan_out_index, fan_out_input, fan_out_output,"
                        " child_id)"
                        " VALUES (:id, :step_id, :config_id, :title, :complexity,"
                        " :order_index, :status, :checklist, :current_attempt,"
                        " :max_attempts, 1, :has_verification, :pending_action_type,"
                        " :pending_clarification_id, :parent_task_id,"
                        " :fan_out_index, :fan_out_input, :fan_out_output,"
                        " :child_id)"
                    ),
                    {
                        "id": event.task_id,
                        "step_id": event.step_id,
                        "config_id": event.config_id,
                        "title": event.title,
                        "complexity": complexity,
                        "order_index": event.order_index,
                        "status": getattr(event.status, "value", event.status),
                        "checklist": json.dumps(event.checklist),
                        "current_attempt": event.current_attempt,
                        "max_attempts": event.max_attempts,
                        "has_verification": 1 if event.has_verification else 0,
                        "pending_action_type": event.pending_action_type,
                        "pending_clarification_id": event.pending_clarification_id,
                        "parent_task_id": event.parent_task_id,
                        "fan_out_index": event.fan_out_index,
                        "fan_out_input": event.fan_out_input,
                        "fan_out_output": event.fan_out_output,
                        "child_id": event.child_id,
                    },
                )
            case TaskStatusChanged():
                values: dict[str, Any] = {
                    "status": getattr(event.new_status, "value", event.new_status)
                }
                if event.current_attempt is not None:
                    values["current_attempt"] = event.current_attempt
                await session.execute(
                    update(TaskModel).where(TaskModel.id == event.task_id).values(**values)
                )
                await _upsert_attempt_snapshots(session, event.task_id, event.attempt_snapshots)
            case RunStepBackward():
                step_ids = (
                    select(StepModel.id)
                    .where(
                        StepModel.run_id == event.run_id,
                        StepModel.order_index >= event.to_step_index,
                        StepModel.order_index <= event.from_step_index,
                    )
                    .scalar_subquery()
                )
                await session.execute(
                    update(TaskModel)
                    .where(
                        TaskModel.step_id.in_(step_ids),
                        TaskModel.status != TaskStatus.COMPLETED.value,
                    )
                    .values(status=TaskStatus.PENDING.value)
                )
            case TaskReverted():
                snapshot = event.task_snapshot
                if snapshot:
                    task_values: dict[str, Any] = {
                        "status": snapshot.get("status"),
                        "checklist": snapshot.get("checklist", []),
                        "current_attempt": snapshot.get("current_attempt", 0),
                        "max_attempts": snapshot.get("max_attempts", 3),
                    }
                    if "has_verification" in snapshot:
                        task_values["has_verification"] = (
                            1 if snapshot.get("has_verification") else 0
                        )
                    for field_name in (
                        "config_id",
                        "title",
                        "complexity",
                        "pending_action_type",
                        "pending_clarification_id",
                        "parent_task_id",
                        "fan_out_index",
                        "fan_out_input",
                        "fan_out_output",
                        "child_id",
                    ):
                        if field_name in snapshot:
                            task_values[field_name] = snapshot.get(field_name)
                    await session.execute(
                        update(TaskModel).where(TaskModel.id == event.task_id).values(**task_values)
                    )
                    await session.execute(
                        delete(AttemptModel).where(AttemptModel.task_id == event.task_id)
                    )
                    raw_attempts = snapshot.get("attempts", [])
                    attempt_snapshots: list[dict[str, Any]] = []
                    if isinstance(raw_attempts, list):
                        for raw_attempt in cast(list[Any], raw_attempts):
                            if isinstance(raw_attempt, dict):
                                attempt_snapshot = cast(dict[str, Any], raw_attempt)
                                if attempt_snapshot.get("id"):
                                    attempt_snapshots.append(attempt_snapshot)
                    attempts = [
                        _attempt_from_snapshot(event.task_id, attempt)
                        for attempt in attempt_snapshots
                    ]
                    session.add_all(attempts)
            case ChecklistItemUpdated():
                row = await session.execute(
                    select(TaskModel.checklist).where(TaskModel.id == event.task_id)
                )
                raw_checklist = row.scalar_one_or_none() or []
                checklist = list(raw_checklist)
                for item in checklist:
                    if item.get("req_id") == event.req_id:
                        item["status"] = getattr(event.status, "value", event.status)
                        if event.note is not None:
                            item["note"] = event.note
                        break
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(checklist=checklist)
                )
            case ChecklistItemGraded():
                row = await session.execute(
                    select(TaskModel.checklist).where(TaskModel.id == event.task_id)
                )
                raw_checklist = row.scalar_one_or_none() or []
                checklist = list(raw_checklist)
                for item in checklist:
                    if item.get("req_id") == event.req_id:
                        item["grade"] = event.grade
                        if event.grade_reason is not None:
                            item["grade_reason"] = event.grade_reason
                        break
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(checklist=checklist)
                )
            case AutoVerifyCompleted():
                values: dict[str, Any] = {}
                if event.checklist:
                    values["checklist"] = event.checklist
                if event.current_attempt is not None:
                    values["current_attempt"] = event.current_attempt
                if values:
                    await session.execute(
                        update(TaskModel).where(TaskModel.id == event.task_id).values(**values)
                    )
                if event.latest_attempt_snapshot is not None:
                    await _upsert_attempt_snapshots(
                        session, event.task_id, [event.latest_attempt_snapshot]
                    )
                elif event.results:
                    row = await session.execute(
                        select(AttemptModel)
                        .where(AttemptModel.task_id == event.task_id)
                        .order_by(AttemptModel.attempt_num.desc())
                        .limit(1)
                    )
                    attempt = row.scalar_one_or_none()
                    if attempt is not None:
                        attempt.auto_verify_results = event.results
            case ClarificationRequested():
                import json as _json

                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(
                        status="pending_user_action",
                        pending_action_type="clarification",
                        pending_clarification_id=event.request_id,
                    )
                )
                await session.execute(
                    text(
                        "INSERT OR IGNORE INTO clarification_requests"
                        " (id, run_id, task_id, attempt_num, questions, created_at)"
                        " VALUES (:id, :run_id, :task_id, :attempt_num,"
                        " :questions, :created_at)"
                    ),
                    {
                        "id": event.request_id,
                        "run_id": event.run_id,
                        "task_id": event.task_id,
                        "attempt_num": event.attempt_num,
                        "questions": _json.dumps(event.questions),
                        "created_at": event.timestamp,
                    },
                )
            case ClarificationResponded():
                values: dict[str, Any] = {
                    "pending_action_type": None,
                    "pending_clarification_id": None,
                }
                if event.new_status is not None:
                    values["status"] = getattr(event.new_status, "value", event.new_status)
                await session.execute(
                    update(TaskModel).where(TaskModel.id == event.task_id).values(**values)
                )
                if event.responded_at is not None:
                    await session.execute(
                        text(
                            "UPDATE clarification_requests SET responded_at = :responded_at"
                            " WHERE id = :request_id"
                        ),
                        {
                            "request_id": event.request_id,
                            "responded_at": _parse_datetime(event.responded_at),
                        },
                    )
                should_insert_response = (
                    event.response_id is not None
                    or event.responded_at is not None
                    or event.responded_by is not None
                    or bool(event.answers)
                )
                if should_insert_response:
                    import json as _json

                    response_id = event.response_id or f"{event.request_id}:response"
                    first_answer = event.answers[0] if event.answers else {}
                    responded_by = (
                        event.responded_by or first_answer.get("answered_by") or "unknown"
                    )
                    responded_at = _parse_datetime(event.responded_at) or event.timestamp
                    await session.execute(
                        text(
                            "INSERT OR IGNORE INTO clarification_responses"
                            " (id, request_id, answers, responded_by, responded_at)"
                            " VALUES (:id, :request_id, :answers, :responded_by, :responded_at)"
                        ),
                        {
                            "id": response_id,
                            "request_id": event.request_id,
                            "answers": _json.dumps(event.answers),
                            "responded_by": responded_by,
                            "responded_at": responded_at,
                        },
                    )
            case ApprovalRequested():
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(pending_action_type="approval")
                )
            case ApprovalDecision():
                values: dict[str, Any] = {"pending_action_type": None}
                if event.new_status is not None:
                    values["status"] = getattr(event.new_status, "value", event.new_status)
                if event.current_attempt is not None:
                    values["current_attempt"] = event.current_attempt
                if event.checklist is not None:
                    values["checklist"] = event.checklist
                await session.execute(
                    update(TaskModel).where(TaskModel.id == event.task_id).values(**values)
                )
                await _upsert_attempt_snapshots(
                    session,
                    event.task_id,
                    event.attempt_snapshots,
                )
            case TaskAttemptCreated():
                import json as _json

                await session.execute(
                    text(
                        "INSERT OR IGNORE INTO attempts"
                        " (id, task_id, attempt_num, attempt_id, started_at,"
                        " runner_type, agent_model,"
                        " tokens_read, tokens_write, tokens_cache, duration_ms, num_actions)"
                        " VALUES (:id, :task_id, :attempt_num, :attempt_id,"
                        " :started_at, :runner_type, :agent_model, 0, 0, 0, 0, 0)"
                    ),
                    {
                        "id": event.attempt_id,
                        "task_id": event.task_id,
                        "attempt_num": event.attempt_num,
                        "attempt_id": event.attempt_id,
                        "started_at": _parse_datetime(event.started_at),
                        "runner_type": event.runner_type,
                        "agent_model": event.agent_model,
                    },
                )
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(
                        current_attempt=event.attempt_num,
                        status=getattr(
                            event.new_task_status or TaskStatus.BUILDING,
                            "value",
                            event.new_task_status or TaskStatus.BUILDING,
                        ),
                    )
                )
            case AttemptUpdated():
                row = await session.execute(
                    select(AttemptModel).where(AttemptModel.id == event.attempt_id)
                )
                attempt = row.scalar_one_or_none()
                if attempt is not None:
                    if event.output_lines:
                        new_text = "\n".join(event.output_lines)
                        if attempt.agent_output:
                            combined = f"{attempt.agent_output}\n{new_text}"
                            attempt.agent_output = "\n".join(combined.splitlines()[-10000:])
                        else:
                            attempt.agent_output = "\n".join(event.output_lines[-10000:])
                    if event.error is not None:
                        attempt.error = event.error
                    if event.outcome is not None:
                        attempt.outcome = event.outcome
                    if event.builder_prompt is not None:
                        attempt.builder_prompt = event.builder_prompt
                    if event.verifier_prompt is not None:
                        attempt.verifier_prompt = event.verifier_prompt
                    if event.verifier_comment is not None:
                        attempt.verifier_comment = event.verifier_comment
                    if event.grade_snapshot is not None:
                        attempt.grade_snapshot = event.grade_snapshot
                    if event.completed_at is not None:
                        attempt.completed_at = _parse_datetime(event.completed_at)
                    if event.paused_at is not None:
                        attempt.paused_at = _parse_datetime(event.paused_at)
                    if event.clear_paused_state:
                        attempt.paused_at = None
                        attempt.outcome = None
                    if event.auto_verify_results is not None:
                        attempt.auto_verify_results = event.auto_verify_results
                    if event.action_log is not None:
                        attempt.action_log_json = event.action_log
                    if event.token_usage_by_model is not None:
                        attempt.token_usage_by_model = event.token_usage_by_model
                    if event.tokens_read is not None:
                        attempt.tokens_read = (attempt.tokens_read or 0) + event.tokens_read
                    if event.tokens_write is not None:
                        attempt.tokens_write = (attempt.tokens_write or 0) + event.tokens_write
                    if event.tokens_cache is not None:
                        attempt.tokens_cache = (attempt.tokens_cache or 0) + event.tokens_cache
                    if event.duration_ms is not None:
                        attempt.duration_ms = (attempt.duration_ms or 0) + event.duration_ms
                    if event.num_actions is not None:
                        attempt.num_actions = (attempt.num_actions or 0) + event.num_actions
                    if event.agent_runner_type is not None:
                        attempt.runner_type = getattr(
                            event.agent_runner_type, "value", event.agent_runner_type
                        )
                    if event.agent_model is not None:
                        attempt.agent_model = event.agent_model
                    if event.agent_settings is not None:
                        attempt.agent_settings = event.agent_settings
                    if event.start_commit is not None:
                        attempt.start_commit = event.start_commit
                    if event.end_commit is not None:
                        attempt.end_commit = event.end_commit
                if event.new_task_status is not None:
                    await session.execute(
                        update(TaskModel)
                        .where(TaskModel.id == event.task_id)
                        .values(
                            status=getattr(event.new_task_status, "value", event.new_task_status)
                        )
                    )
            case FanOutChildrenCreated():
                import json as _json

                for i, child in enumerate(event.children):
                    checklist = child.get("checklist", [])
                    await session.execute(
                        text(
                            "INSERT OR IGNORE INTO tasks"
                            " (id, step_id, config_id, title, complexity, order_index,"
                            " status, checklist, current_attempt, max_attempts, version,"
                            " has_verification, parent_task_id, fan_out_index, fan_out_input,"
                            " fan_out_output, child_id)"
                            " VALUES (:id, :step_id, :config_id, :title, :complexity,"
                            " :order_index, 'pending', :checklist, 0, :max_attempts, 1,"
                            " :has_verification, :parent_task_id, :fan_out_index, :fan_out_input,"
                            " :fan_out_output, :child_id)"
                        ),
                        {
                            "id": child["id"],
                            "step_id": event.step_id,
                            "config_id": child.get("config_id", ""),
                            "title": child.get("title", ""),
                            "complexity": child.get("complexity") or "standard",
                            "order_index": child.get("order_index", i),
                            "checklist": _json.dumps(checklist),
                            "max_attempts": child.get("max_attempts", 3),
                            "has_verification": 1 if child.get("has_verification", True) else 0,
                            "parent_task_id": event.parent_task_id,
                            "fan_out_index": child.get("fan_out_index"),
                            "fan_out_input": child.get("fan_out_input"),
                            "fan_out_output": child.get("fan_out_output"),
                            "child_id": child.get("child_id"),
                        },
                    )
                if event.parent_new_status is not None:
                    await session.execute(
                        update(TaskModel)
                        .where(TaskModel.id == event.parent_task_id)
                        .values(
                            status=getattr(
                                event.parent_new_status, "value", event.parent_new_status
                            )
                        )
                    )
            case FanOutChildrenReset():
                from sqlalchemy import or_

                result = await session.execute(
                    select(TaskModel).where(
                        or_(
                            TaskModel.id == event.parent_task_id,
                            TaskModel.parent_task_id == event.parent_task_id,
                        )
                    )
                )
                tasks = result.scalars().all()
                for task in tasks:
                    if task.id == event.parent_task_id:
                        task.status = "fan_out_running"
                    elif task.status != "completed":
                        task.status = "pending"
            case FanOutChildRetried():
                result = await session.execute(
                    select(TaskModel).where(TaskModel.id == event.child_task_id)
                )
                child = result.scalar_one_or_none()
                if child is not None and child.parent_task_id is not None:
                    child.status = "pending"
                    parent_result = await session.execute(
                        select(TaskModel).where(TaskModel.id == child.parent_task_id)
                    )
                    parent = parent_result.scalar_one_or_none()
                    if parent is not None:
                        parent.status = "fan_out_running"
                        step_result = await session.execute(
                            select(StepModel).where(StepModel.id == parent.step_id)
                        )
                        step = step_result.scalar_one_or_none()
                        if step is not None:
                            step.completed = False
            case _:
                pass  # FanOut*, Child* handled by legacy paths

    async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:
        for event in events:
            if type(event) in self.handled_events:
                await self.handle(event, session)
