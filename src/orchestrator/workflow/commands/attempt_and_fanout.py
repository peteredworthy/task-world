"""Command handlers for task attempts, oversight facts, and fan-out operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from orchestrator.config.enums import TaskStatus
from orchestrator.workflow.events import (
    AttemptUpdated,
    FanOutChildrenCreated,
    FanOutChildrenReset,
    FanOutChildRetried,
    ParentOversightFactsUpdated,
    RunMetadataUpdated,
    StepIndexRewound,
    TaskAttemptCreated,
    TaskReverted,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.workflow.events.types import WorkflowEvent


class CreateTaskAttemptCommand(BaseModel):
    run_id: str
    task_id: str
    attempt_id: str
    attempt_num: int
    runner_type: str | None = None
    agent_model: str | None = None
    new_task_status: TaskStatus = TaskStatus.BUILDING


async def handle_create_task_attempt(
    cmd: CreateTaskAttemptCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = TaskAttemptCreated(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        attempt_id=cmd.attempt_id,
        attempt_num=cmd.attempt_num,
        runner_type=cmd.runner_type,
        agent_model=cmd.agent_model,
        new_task_status=cmd.new_task_status,
    )
    await event_store.append([event])
    return [event]


class UpdateLatestAttemptCommand(BaseModel):
    run_id: str
    task_id: str
    attempt_id: str
    output_lines: list[str] | None = None
    error: str | None = None
    outcome: str | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    grade_snapshot: list[dict[str, Any]] | None = None
    completed_at: str | None = None
    paused_at: str | None = None
    clear_paused_state: bool = False
    auto_verify_results: list[dict[str, Any]] | None = None
    action_log: Any | None = None
    token_usage_by_model: list[dict[str, Any]] | None = None
    tokens_read: int | None = None
    tokens_write: int | None = None
    tokens_cache: int | None = None
    duration_ms: int | None = None
    num_actions: int | None = None
    agent_runner_type: str | None = None
    agent_model: str | None = None
    agent_settings: dict[str, Any] | None = None
    start_commit: str | None = None
    end_commit: str | None = None
    new_task_status: TaskStatus | None = None


async def handle_update_latest_attempt(
    cmd: UpdateLatestAttemptCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = AttemptUpdated(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        attempt_id=cmd.attempt_id,
        output_lines=cmd.output_lines,
        error=cmd.error,
        outcome=cmd.outcome,
        builder_prompt=cmd.builder_prompt,
        verifier_prompt=cmd.verifier_prompt,
        verifier_comment=cmd.verifier_comment,
        grade_snapshot=cmd.grade_snapshot,
        completed_at=cmd.completed_at,
        paused_at=cmd.paused_at,
        clear_paused_state=cmd.clear_paused_state,
        auto_verify_results=cmd.auto_verify_results,
        action_log=cmd.action_log,
        token_usage_by_model=cmd.token_usage_by_model,
        tokens_read=cmd.tokens_read,
        tokens_write=cmd.tokens_write,
        tokens_cache=cmd.tokens_cache,
        duration_ms=cmd.duration_ms,
        num_actions=cmd.num_actions,
        agent_runner_type=cmd.agent_runner_type,
        agent_model=cmd.agent_model,
        agent_settings=cmd.agent_settings,
        start_commit=cmd.start_commit,
        end_commit=cmd.end_commit,
        new_task_status=cmd.new_task_status,
    )
    await event_store.append([event])
    return [event]


class UpdateRunMetadataCommand(BaseModel):
    run_id: str
    runner_config_delta: dict[str, Any] = Field(default_factory=dict)


async def handle_update_run_metadata(
    cmd: UpdateRunMetadataCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunMetadataUpdated(
        run_id=cmd.run_id,
        runner_config_delta=cmd.runner_config_delta,
    )
    await event_store.append([event])
    return [event]


class UpdateParentOversightFactsCommand(BaseModel):
    run_id: str
    patch: dict[str, Any] = Field(default_factory=dict)


async def handle_update_parent_oversight_facts(
    cmd: UpdateParentOversightFactsCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = ParentOversightFactsUpdated(
        run_id=cmd.run_id,
        patch=cmd.patch,
    )
    await event_store.append([event])
    return [event]


class RecordTaskRevertedCommand(BaseModel):
    run_id: str
    task_id: str
    reverted_from_status: TaskStatus | str
    task_snapshot: dict[str, Any] = Field(default_factory=dict)


async def handle_record_task_reverted(
    cmd: RecordTaskRevertedCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = TaskReverted(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        reverted_from_status=cmd.reverted_from_status,
        task_snapshot=cmd.task_snapshot,
    )
    await event_store.append([event])
    return [event]


class CreateFanOutChildrenCommand(BaseModel):
    run_id: str
    step_id: str
    parent_task_id: str
    children: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    parent_new_status: TaskStatus | None = None


async def handle_create_fan_out_children(
    cmd: CreateFanOutChildrenCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = FanOutChildrenCreated(
        run_id=cmd.run_id,
        step_id=cmd.step_id,
        parent_task_id=cmd.parent_task_id,
        children=cmd.children,
        parent_new_status=cmd.parent_new_status,
    )
    await event_store.append([event])
    return [event]


class ResetFanOutChildrenCommand(BaseModel):
    run_id: str
    parent_task_id: str


async def handle_reset_fan_out_children(
    cmd: ResetFanOutChildrenCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = FanOutChildrenReset(
        run_id=cmd.run_id,
        parent_task_id=cmd.parent_task_id,
    )
    await event_store.append([event])
    return [event]


class RetryFanOutChildCommand(BaseModel):
    run_id: str
    child_task_id: str
    step_order_index: int


async def handle_retry_fan_out_child(
    cmd: RetryFanOutChildCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    events: list[WorkflowEvent] = [
        FanOutChildRetried(
            run_id=cmd.run_id,
            child_task_id=cmd.child_task_id,
            step_order_index=cmd.step_order_index,
        ),
        StepIndexRewound(
            run_id=cmd.run_id,
            target_step_index=cmd.step_order_index,
        ),
    ]
    await event_store.append(events)
    return events
