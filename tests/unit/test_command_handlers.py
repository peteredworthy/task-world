"""Unit tests for event-sourced command handlers using real SQLite."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import ChecklistStatus, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import SqliteEventStore, StoredEvent
from orchestrator.db import AttemptModel, EventV2Model, RunModel, StepModel, TaskModel
from orchestrator.db import ProjectionRegistry, RunStateProjector, TaskStateProjector
from orchestrator.state import (
    Attempt,
    ModelTokenUsage,
    Run,
    StepState,
    TaskState,
    TransitionTracker,
)
from orchestrator.workflow import (
    CreateFanOutChildrenCommand,
    CreateRunCommand,
    CreateTaskAttemptCommand,
    CreateTaskCommand,
    DeleteRunCommand,
    CompleteRunWorktreeCommitCommand,
    CompleteRunWorktreeResetCommand,
    FailRunWorktreeCreationCommand,
    FailRunWorktreeCommitCommand,
    FailRunWorktreeResetCommand,
    InitialAttemptForRunCreate,
    InitialStepForRunCreate,
    InitialTaskForRunCreate,
    RecordClarificationRequestCommand,
    RecordTaskRevertedCommand,
    RequestRunWorktreeCreationCommand,
    RequestRunWorktreeCommitCommand,
    RequestRunWorktreeResetCommand,
    ResetFanOutChildrenCommand,
    RetryFanOutChildCommand,
    RewindStepIndexCommand,
    SetChecklistGradeCommand,
    UpdateChecklistItemCommand,
    UpdateLatestAttemptCommand,
    UpdateParentOversightFactsCommand,
    UpdateRunMetadataCommand,
    UpdateRunStatusCommand,
    UpdateRunWorktreeCommand,
    UpdateTaskStatusCommand,
    build_create_run_command,
    handle_create_fan_out_children,
    handle_create_run,
    handle_create_task,
    handle_create_task_attempt,
    handle_delete_run,
    handle_complete_run_worktree_commit,
    handle_complete_run_worktree_reset,
    handle_fail_run_worktree_creation,
    handle_fail_run_worktree_commit,
    handle_fail_run_worktree_reset,
    handle_record_clarification_request,
    handle_record_task_reverted,
    handle_request_run_worktree_creation,
    handle_request_run_worktree_commit,
    handle_request_run_worktree_reset,
    handle_reset_fan_out_children,
    handle_retry_fan_out_child,
    handle_rewind_step_index,
    handle_set_checklist_grade,
    handle_update_checklist_item,
    handle_update_latest_attempt,
    handle_update_parent_oversight_facts,
    handle_update_run_metadata,
    handle_update_run_status,
    handle_update_run_worktree,
    handle_update_task_status,
)

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class CommandHarness:
    session: AsyncSession
    store: SqliteEventStore


@pytest.fixture
async def harness() -> AsyncGenerator[CommandHarness, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as session:
        registry = ProjectionRegistry()
        registry.register(RunStateProjector())
        registry.register(TaskStateProjector())
        store = SqliteEventStore(session)
        store.add_projection_listener(registry)
        yield CommandHarness(session=session, store=store)
    await engine.dispose()


async def _stored_events(session: AsyncSession) -> list[EventV2Model]:
    result = await session.execute(select(EventV2Model).order_by(EventV2Model.position))
    return list(result.scalars())


async def _assert_latest_event(
    session: AsyncSession,
    expected_type: str,
    expected_payload: dict[str, object],
) -> EventV2Model:
    events = await _stored_events(session)
    assert events
    stored = events[-1]
    assert stored.event_type == expected_type
    payload = json.loads(stored.payload)
    assert payload["event_type"] == expected_type
    for key, value in expected_payload.items():
        assert payload[key] == value
    return stored


async def _assert_latest_events(
    session: AsyncSession,
    expected_types: list[str],
) -> list[EventV2Model]:
    events = await _stored_events(session)
    tail = events[-len(expected_types) :]
    assert [event.event_type for event in tail] == expected_types
    return tail


async def _get_run(session: AsyncSession, run_id: str = "run-1") -> RunModel:
    result = await session.execute(select(RunModel).where(RunModel.id == run_id))
    return result.scalar_one()


async def _get_step(session: AsyncSession, step_id: str = "step-1") -> StepModel:
    result = await session.execute(select(StepModel).where(StepModel.id == step_id))
    return result.scalar_one()


async def _get_task(session: AsyncSession, task_id: str) -> TaskModel:
    result = await session.execute(select(TaskModel).where(TaskModel.id == task_id))
    return result.scalar_one()


async def _get_attempt(session: AsyncSession, attempt_id: str = "attempt-1") -> AttemptModel:
    result = await session.execute(select(AttemptModel).where(AttemptModel.id == attempt_id))
    return result.scalar_one()


async def _run_handler(
    harness: CommandHarness,
    handler: Callable[..., Awaitable[list[object]]],
    command: object,
) -> list[StoredEvent]:
    before = len(await _stored_events(harness.session))
    emitted = await handler(command, harness.store, harness.session)
    await harness.session.flush()
    after = await _stored_events(harness.session)
    assert len(after) == before + len(emitted)
    return [
        StoredEvent(
            position=event.position,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            payload=event.payload,
            timestamp=event.timestamp,
            version=event.version,
        )
        for event in after[before:]
    ]


async def _create_run(harness: CommandHarness, run_id: str = "run-1") -> None:
    await _run_handler(
        harness,
        handle_create_run,
        CreateRunCommand(
            run_id=run_id,
            routine_id="routine-1",
            project_path="/tmp/project",
            repo_name="repo-1",
            status=RunStatus.DRAFT,
            config={"feature": "command-tests"},
        ),
    )


async def _create_step(
    session: AsyncSession,
    run_id: str = "run-1",
    step_id: str = "step-1",
    order_index: int = 0,
    completed: bool = False,
) -> None:
    session.add(
        StepModel(
            id=step_id,
            run_id=run_id,
            config_id=f"S-{order_index + 1:02d}",
            title=f"Step {order_index + 1}",
            order_index=order_index,
            completed=completed,
        )
    )
    await session.flush()


async def _create_task(
    harness: CommandHarness,
    task_id: str = "task-1",
    step_id: str = "step-1",
    status: TaskStatus | None = None,
    parent_task_id: str | None = None,
) -> None:
    await _run_handler(
        harness,
        handle_create_task,
        CreateTaskCommand(
            run_id="run-1",
            task_id=task_id,
            step_id=step_id,
            step_index=0,
            config_id=task_id.upper(),
            title=f"Task {task_id}",
            complexity="standard",
            order_index=0,
            max_attempts=3,
            checklist=[{"id": "R1", "text": "pass"}],
            parent_task_id=parent_task_id,
        ),
    )
    if status is not None and status != TaskStatus.PENDING:
        await harness.session.execute(
            text("UPDATE tasks SET status = :status WHERE id = :task_id"),
            {"status": status.value, "task_id": task_id},
        )
        await harness.session.flush()


async def _create_base_run_step_task(
    harness: CommandHarness,
    task_status: TaskStatus | None = None,
) -> None:
    await _create_run(harness)
    await _create_step(harness.session)
    await _create_task(harness, status=task_status)


async def test_create_run_emits_event_and_projects_run(harness: CommandHarness) -> None:
    await _run_handler(
        harness,
        handle_create_run,
        CreateRunCommand(
            run_id="run-1",
            routine_id="routine-1",
            project_path="/tmp/project",
            repo_name="repo-1",
            config={"slice": "S-03"},
            run_snapshot={
                "id": "run-1",
                "repo_name": "repo-1",
                "status": "draft",
                "config": {"slice": "S-03"},
                "agent_runner_type": "cli_subprocess",
                "agent_runner_config": {"model": "gpt-5.3-codex"},
                "source_branch": "main",
                "steps": [],
            },
        ),
    )

    await _assert_latest_event(
        harness.session,
        "run_created",
        {
            "run_id": "run-1",
            "routine_id": "routine-1",
            "repo_name": "repo-1",
            "run_snapshot": {
                "id": "run-1",
                "repo_name": "repo-1",
                "status": "draft",
                "config": {"slice": "S-03"},
                "agent_runner_type": "cli_subprocess",
                "agent_runner_config": {"model": "gpt-5.3-codex"},
                "source_branch": "main",
                "steps": [],
            },
        },
    )
    run = await _get_run(harness.session)
    assert run.status == "draft"
    assert run.config == {"slice": "S-03"}
    assert run.runner_type == "cli_subprocess"
    assert run.runner_config == {"model": "gpt-5.3-codex"}
    assert run.source_branch == "main"
    assert run.current_step_index == 0


async def test_create_run_snapshot_only_stores_one_event_but_projects_children(
    harness: CommandHarness,
) -> None:
    stored = await _run_handler(
        harness,
        handle_create_run,
        CreateRunCommand(
            run_id="snapshot-only-run",
            routine_id="routine-1",
            project_path="/tmp/project",
            repo_name="snapshot-repo",
            run_snapshot={
                "id": "snapshot-only-run",
                "repo_name": "snapshot-repo",
                "status": "paused",
                "config": {"slice": "S-01"},
                "current_step_index": 1,
                "steps": [
                    {
                        "id": "snapshot-only-step",
                        "config_id": "S-01",
                        "title": "Snapshot Step",
                        "order_index": 0,
                        "tasks": [
                            {
                                "id": "snapshot-only-task",
                                "config_id": "T-01",
                                "title": "Snapshot Task",
                                "order_index": 0,
                                "status": "pending_user_action",
                                "checklist": [{"req_id": "R1", "status": "done"}],
                                "current_attempt": 1,
                                "max_attempts": 4,
                                "has_verification": False,
                                "pending_action_type": "clarification",
                                "pending_clarification_id": "clarification-1",
                                "attempts": [
                                    {
                                        "id": "snapshot-only-attempt",
                                        "attempt_num": 1,
                                        "started_at": "2025-01-15T10:30:00Z",
                                        "paused_at": "2025-01-15T10:31:00Z",
                                        "outcome": "paused",
                                        "builder_prompt": "build prompt",
                                        "verifier_prompt": "verify prompt",
                                        "verifier_comment": "needs input",
                                        "grade_snapshot": [{"req_id": "R1", "grade": "pass"}],
                                        "auto_verify_results": [{"cmd": "pytest", "passed": True}],
                                        "agent_output": "output text",
                                        "action_log": {"actions": [{"kind": "edit"}]},
                                        "token_usage_by_model": [
                                            {
                                                "model": "gpt-5.3-codex",
                                                "input_tokens": 10,
                                                "output_tokens": 20,
                                            }
                                        ],
                                        "metrics": {
                                            "tokens_read": 2,
                                            "tokens_write": 3,
                                            "tokens_cache": 4,
                                            "duration_ms": 5,
                                            "num_actions": 6,
                                        },
                                        "agent_runner_type": "cli_subprocess",
                                        "agent_model": "gpt-5.3-codex",
                                        "agent_settings": {"temperature": 0},
                                        "start_commit": "start-sha",
                                        "end_commit": "end-sha",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in stored] == ["run_created"]
    run = await _get_run(harness.session, "snapshot-only-run")
    assert run.status == "paused"
    assert run.config == {"slice": "S-01"}
    assert run.current_step_index == 1

    step = await _get_step(harness.session, "snapshot-only-step")
    assert step.run_id == "snapshot-only-run"
    assert step.title == "Snapshot Step"

    task = await _get_task(harness.session, "snapshot-only-task")
    assert task.step_id == "snapshot-only-step"
    assert task.status == "pending_user_action"
    assert task.current_attempt == 1
    assert task.has_verification == 0
    assert task.pending_action_type == "clarification"
    assert task.pending_clarification_id == "clarification-1"
    assert task.checklist == [{"req_id": "R1", "status": "done"}]

    attempt = await _get_attempt(harness.session, "snapshot-only-attempt")
    assert attempt.task_id == "snapshot-only-task"
    assert attempt.outcome == "paused"
    assert attempt.tokens_read == 2
    assert attempt.tokens_write == 3
    assert attempt.tokens_cache == 4
    assert attempt.duration_ms == 5
    assert attempt.num_actions == 6
    assert attempt.builder_prompt == "build prompt"
    assert attempt.verifier_prompt == "verify prompt"
    assert attempt.verifier_comment == "needs input"
    assert attempt.grade_snapshot == [{"req_id": "R1", "grade": "pass"}]
    assert attempt.auto_verify_results == [{"cmd": "pytest", "passed": True}]
    assert attempt.agent_output == "output text"
    assert attempt.action_log_json == {"actions": [{"kind": "edit"}]}
    assert attempt.token_usage_by_model == [
        {"model": "gpt-5.3-codex", "input_tokens": 10, "output_tokens": 20}
    ]
    assert attempt.runner_type == "cli_subprocess"
    assert attempt.agent_model == "gpt-5.3-codex"
    assert attempt.agent_settings == {"temperature": 0}
    assert attempt.start_commit == "start-sha"
    assert attempt.end_commit == "end-sha"


def test_build_create_run_command_preserves_initial_attempt_replay_fields() -> None:
    usage = ModelTokenUsage(
        model="gpt-test",
        input_tokens=3,
        output_tokens=5,
        cost_per_m_input=1.25,
        cost_per_m_output=10.0,
    )
    run_usage = ModelTokenUsage(
        model="gpt-run",
        input_tokens=30,
        output_tokens=50,
        cost_per_m_input=1.5,
        cost_per_m_output=12.0,
    )
    created_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    updated_at = datetime(2025, 1, 15, 10, 1, 0, tzinfo=timezone.utc)
    started_at = datetime(2025, 1, 15, 10, 2, 0, tzinfo=timezone.utc)
    completed_at = datetime(2025, 1, 15, 10, 3, 0, tzinfo=timezone.utc)
    runner_started_at = datetime(2025, 1, 15, 10, 2, 30, tzinfo=timezone.utc)
    attempt = Attempt(
        id="attempt-1",
        attempt_num=1,
        builder_prompt="build this",
        auto_verify_results=[{"id": "output_exists", "passed": True}],
        agent_output="line one\nline two",
        action_log={"session_id": "session-1", "entries": []},
        token_usage_by_model=[usage],
    )
    run = Run(
        id="run-1",
        routine_id="routine-1",
        repo_name="repo-1",
        parent_run_id="parent-run",
        parent_task_id="parent-task",
        transition_tracker=TransitionTracker(counts={"S-02->S-01": 2}),
        created_at=created_at,
        updated_at=updated_at,
        started_at=started_at,
        completed_at=completed_at,
        agent_runner_started_at=runner_started_at,
        total_tokens_read=100,
        total_tokens_write=50,
        total_tokens_cache=10,
        total_duration_ms=1500,
        total_num_actions=5,
        token_usage_by_model=[run_usage],
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                title="Step 1",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        title="Task 1",
                        has_verification=False,
                        attempts=[attempt],
                    )
                ],
            )
        ],
    )

    command = build_create_run_command(run, project_path="/tmp/project")

    assert command.created_at == created_at.isoformat()
    assert command.updated_at == updated_at.isoformat()
    assert command.started_at == started_at.isoformat()
    assert command.completed_at == completed_at.isoformat()
    assert command.agent_runner_started_at == runner_started_at.isoformat()
    assert command.total_tokens_read == 100
    assert command.total_tokens_write == 50
    assert command.total_tokens_cache == 10
    assert command.total_duration_ms == 1500
    assert command.total_num_actions == 5
    assert command.token_usage_by_model == [run_usage.model_dump(mode="json")]
    assert command.aggregate_metrics_are_authoritative is True
    assert command.parent_run_id == "parent-run"
    assert command.parent_task_id == "parent-task"
    assert command.transition_tracker == {"counts": {"S-02->S-01": 2}}
    assert command.initial_tasks[0].has_verification is False
    initial_attempt = command.initial_tasks[0].attempts[0]
    assert initial_attempt.builder_prompt == "build this"
    assert initial_attempt.auto_verify_results == [{"id": "output_exists", "passed": True}]
    assert initial_attempt.agent_output == "line one\nline two"
    assert attempt.action_log is not None
    assert initial_attempt.action_log == attempt.action_log.model_dump(mode="json")
    assert initial_attempt.token_usage_by_model == [usage.model_dump(mode="json")]


async def test_create_run_replays_initial_attempt_gap_fields(
    harness: CommandHarness,
) -> None:
    await _run_handler(
        harness,
        handle_create_run,
        CreateRunCommand(
            run_id="run-1",
            routine_id="routine-1",
            project_path="/tmp/project",
            repo_name="repo-1",
            total_tokens_read=100,
            total_tokens_write=50,
            total_tokens_cache=10,
            total_duration_ms=1500,
            total_num_actions=5,
            token_usage_by_model=[{"model": "gpt-run", "input_tokens": 30, "output_tokens": 50}],
            transition_tracker={"counts": {"S-02->S-01": 2}},
            aggregate_metrics_are_authoritative=True,
            initial_steps=[
                InitialStepForRunCreate(
                    step_id="step-1",
                    config_id="S-01",
                    title="Step 1",
                    order_index=0,
                )
            ],
            initial_tasks=[
                InitialTaskForRunCreate(
                    task_id="task-1",
                    step_id="step-1",
                    config_id="T-01",
                    title="Task 1",
                    status=TaskStatus.COMPLETED,
                    has_verification=False,
                    attempts=[
                        InitialAttemptForRunCreate(
                            task_id="task-1",
                            attempt_id="attempt-1",
                            attempt_num=1,
                            agent_output="line one\nline two",
                            auto_verify_results=[
                                {"id": "output_exists", "passed": False, "output": "missing"}
                            ],
                            action_log={"session_id": "session-1", "entries": []},
                            token_usage_by_model=[
                                {
                                    "model": "gpt-test",
                                    "input_tokens": 3,
                                    "output_tokens": 5,
                                }
                            ],
                            tokens_read=10,
                            tokens_write=4,
                            tokens_cache=2,
                            duration_ms=150,
                            num_actions=3,
                        )
                    ],
                )
            ],
        ),
    )

    stored = await _assert_latest_event(
        harness.session,
        "attempt_updated",
        {
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "output_lines": ["line one\nline two"],
            "auto_verify_results": [{"id": "output_exists", "passed": False, "output": "missing"}],
            "action_log": {"session_id": "session-1", "entries": []},
            "token_usage_by_model": [{"model": "gpt-test", "input_tokens": 3, "output_tokens": 5}],
            "tokens_read": 10,
            "tokens_write": 4,
            "tokens_cache": 2,
            "duration_ms": 150,
            "num_actions": 3,
            "apply_to_run_totals": False,
        },
    )
    payload = json.loads(stored.payload)
    assert payload["output_lines"] == ["line one\nline two"]
    events = await _stored_events(harness.session)
    task_attempt_event = next(
        event for event in events if event.event_type == "task_attempt_created"
    )
    task_attempt_payload = json.loads(task_attempt_event.payload)
    assert task_attempt_payload["new_task_status"] == "completed"
    task_created_event = next(event for event in events if event.event_type == "task_created")
    task_created_payload = json.loads(task_created_event.payload)
    assert task_created_payload["has_verification"] is False
    run_created_event = next(event for event in events if event.event_type == "run_created")
    run_created_payload = json.loads(run_created_event.payload)
    assert run_created_payload["transition_tracker"] == {"counts": {"S-02->S-01": 2}}

    attempt = await _get_attempt(harness.session)
    assert attempt.agent_output == "line one\nline two"
    assert attempt.auto_verify_results == [
        {"id": "output_exists", "passed": False, "output": "missing"}
    ]
    assert attempt.action_log_json == {"session_id": "session-1", "entries": []}
    assert attempt.token_usage_by_model == [
        {"model": "gpt-test", "input_tokens": 3, "output_tokens": 5}
    ]
    assert attempt.tokens_read == 10
    assert attempt.tokens_write == 4
    assert attempt.tokens_cache == 2
    assert attempt.duration_ms == 150
    assert attempt.num_actions == 3
    task = await _get_task(harness.session, "task-1")
    assert task.status == "completed"
    assert task.has_verification == 0
    run = await _get_run(harness.session)
    assert run.transition_tracker == {"counts": {"S-02->S-01": 2}}
    assert run.total_tokens_read == 100
    assert run.total_tokens_write == 50
    assert run.total_tokens_cache == 10
    assert run.total_duration_ms == 1500
    assert run.total_num_actions == 5
    assert run.token_usage_by_model == [
        {"model": "gpt-run", "input_tokens": 30, "output_tokens": 50}
    ]


async def test_create_child_run_emits_event_and_projects_parent_links(
    harness: CommandHarness,
) -> None:
    await _run_handler(
        harness,
        handle_create_run,
        CreateRunCommand(
            run_id="child-run",
            routine_id="routine-child",
            project_path="/tmp/child",
            repo_name="repo-child",
            parent_run_id="parent-run",
            parent_task_id="parent-task",
        ),
    )

    await _assert_latest_event(
        harness.session,
        "run_created",
        {
            "run_id": "child-run",
            "parent_run_id": "parent-run",
            "parent_task_id": "parent-task",
        },
    )
    run = await _get_run(harness.session, "child-run")
    assert run.parent_run_id == "parent-run"
    assert run.parent_task_id == "parent-task"


async def test_delete_run_emits_tombstone_and_projects_delete(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_delete_run,
        DeleteRunCommand(
            run_id="run-1",
            deleted_by="user@example.com",
            reason="cleanup",
        ),
    )

    await _assert_latest_event(
        harness.session,
        "run_deleted",
        {
            "run_id": "run-1",
            "deleted_by": "user@example.com",
            "reason": "cleanup",
        },
    )
    result = await harness.session.execute(select(RunModel).where(RunModel.id == "run-1"))
    assert result.scalar_one_or_none() is None


async def test_create_task_emits_event_and_projects_task(harness: CommandHarness) -> None:
    await _create_run(harness)
    await _create_step(harness.session)

    await _run_handler(
        harness,
        handle_create_task,
        CreateTaskCommand(
            run_id="run-1",
            task_id="task-1",
            step_id="step-1",
            step_index=0,
            config_id="T-01",
            title="Implement R2",
            complexity="simple",
            order_index=4,
            max_attempts=5,
            checklist=[{"id": "R2", "text": "command tests"}],
            has_verification=False,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "task_created",
        {
            "task_id": "task-1",
            "step_id": "step-1",
            "config_id": "T-01",
            "has_verification": False,
        },
    )
    task = await _get_task(harness.session, "task-1")
    assert task.status == "pending"
    assert task.title == "Implement R2"
    assert task.complexity == "simple"
    assert task.order_index == 4
    assert task.max_attempts == 5
    assert task.has_verification == 0
    assert task.checklist == [{"id": "R2", "text": "command tests"}]


async def test_update_run_status_emits_event_and_projects_status(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_update_run_status,
        UpdateRunStatusCommand(
            run_id="run-1",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
            timestamp=NOW,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "run_status_changed",
        {"old_status": "draft", "new_status": "active"},
    )
    run = await _get_run(harness.session)
    assert run.status == "active"
    assert run.started_at == NOW.replace(tzinfo=None)


async def test_update_run_worktree_emits_event_and_projects_metadata(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_update_run_worktree,
        UpdateRunWorktreeCommand(
            run_id="run-1",
            worktree_path="/tmp/worktrees/run-1",
            source_branch_sha="abc123",
        ),
    )

    await _assert_latest_event(
        harness.session,
        "run_worktree_updated",
        {
            "run_id": "run-1",
            "worktree_path": "/tmp/worktrees/run-1",
            "source_branch_sha": "abc123",
        },
    )
    run = await _get_run(harness.session)
    assert run.worktree_path == "/tmp/worktrees/run-1"
    assert run.source_branch_sha == "abc123"

    await _run_handler(
        harness,
        handle_update_run_worktree,
        UpdateRunWorktreeCommand(
            run_id="run-1",
            worktree_path="/tmp/worktrees/run-1-recreated",
        ),
    )
    run = await _get_run(harness.session)
    assert run.worktree_path == "/tmp/worktrees/run-1-recreated"
    assert run.source_branch_sha == "abc123"


async def test_run_worktree_lifecycle_events_are_persisted(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_request_run_worktree_creation,
        RequestRunWorktreeCreationCommand(
            run_id="run-1",
            repo_name="repo",
            source_branch="main",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_creation_requested",
        {"repo_name": "repo", "source_branch": "main"},
    )

    await _run_handler(
        harness,
        handle_fail_run_worktree_creation,
        FailRunWorktreeCreationCommand(run_id="run-1", error="repo missing"),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_creation_failed",
        {"error": "repo missing"},
    )


async def test_run_worktree_reset_events_are_persisted(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_request_run_worktree_reset,
        RequestRunWorktreeResetCommand(
            run_id="run-1",
            worktree_path="/tmp/worktrees/run-1",
            reset_type="resume_uncommitted",
            head_before="abc123",
            reason="resume_strategy=reset_worktree",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_reset_requested",
        {
            "worktree_path": "/tmp/worktrees/run-1",
            "reset_type": "resume_uncommitted",
            "head_before": "abc123",
        },
    )

    await _run_handler(
        harness,
        handle_complete_run_worktree_reset,
        CompleteRunWorktreeResetCommand(
            run_id="run-1",
            worktree_path="/tmp/worktrees/run-1",
            reset_type="resume_uncommitted",
            head_before="abc123",
            head_after="abc123",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_reset_completed",
        {"reset_type": "resume_uncommitted", "head_after": "abc123"},
    )

    await _run_handler(
        harness,
        handle_fail_run_worktree_reset,
        FailRunWorktreeResetCommand(
            run_id="run-1",
            worktree_path="/tmp/worktrees/run-1",
            reset_type="checkout_ref",
            error="bad ref",
            target_ref="missing",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_reset_failed",
        {"reset_type": "checkout_ref", "error": "bad ref", "target_ref": "missing"},
    )


async def test_run_worktree_commit_events_are_persisted(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_request_run_worktree_commit,
        RequestRunWorktreeCommitCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            worktree_path="/tmp/worktrees/run-1",
            commit_type="builder_submit",
            message="Auto-commit builder changes for task task-1",
            head_before="abc123",
            reason="apply_submission",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_commit_requested",
        {
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "commit_type": "builder_submit",
            "message": "Auto-commit builder changes for task task-1",
            "head_before": "abc123",
        },
    )

    await _run_handler(
        harness,
        handle_complete_run_worktree_commit,
        CompleteRunWorktreeCommitCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            worktree_path="/tmp/worktrees/run-1",
            commit_type="builder_submit",
            message="Auto-commit builder changes for task task-1",
            created_commit=True,
            head_before="abc123",
            head_after="def456",
            commit_sha="def456",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_commit_completed",
        {"created_commit": True, "head_after": "def456", "commit_sha": "def456"},
    )

    await _run_handler(
        harness,
        handle_fail_run_worktree_commit,
        FailRunWorktreeCommitCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            worktree_path="/tmp/worktrees/run-1",
            commit_type="builder_submit",
            message="Auto-commit builder changes for task task-1",
            error="commit failed",
        ),
    )
    await _assert_latest_event(
        harness.session,
        "run_worktree_commit_failed",
        {"commit_type": "builder_submit", "error": "commit failed"},
    )


async def test_update_checklist_item_emits_event_and_preserves_note(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)
    await _create_step(harness.session)
    await _run_handler(
        harness,
        handle_create_task,
        CreateTaskCommand(
            run_id="run-1",
            task_id="task-1",
            step_id="step-1",
            step_index=0,
            config_id="T-01",
            title="Task with checklist",
            checklist=[
                {
                    "req_id": "R1",
                    "desc": "Existing note is preserved",
                    "priority": "critical",
                    "status": "open",
                    "note": "keep me",
                }
            ],
        ),
    )

    await _run_handler(
        harness,
        handle_update_checklist_item,
        UpdateChecklistItemCommand(
            run_id="run-1",
            task_id="task-1",
            req_id="R1",
            status=ChecklistStatus.DONE,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "checklist_item_updated",
        {"task_id": "task-1", "req_id": "R1", "status": "done", "note": None},
    )
    task = await _get_task(harness.session, "task-1")
    assert task.checklist[0]["status"] == "done"
    assert task.checklist[0]["note"] == "keep me"

    await _run_handler(
        harness,
        handle_update_checklist_item,
        UpdateChecklistItemCommand(
            run_id="run-1",
            task_id="task-1",
            req_id="R1",
            status=ChecklistStatus.BLOCKED,
            note="blocked by dependency",
        ),
    )

    task = await _get_task(harness.session, "task-1")
    assert task.checklist[0]["status"] == "blocked"
    assert task.checklist[0]["note"] == "blocked by dependency"


async def test_set_checklist_grade_emits_event_and_preserves_reason(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)
    await _create_step(harness.session)
    await _run_handler(
        harness,
        handle_create_task,
        CreateTaskCommand(
            run_id="run-1",
            task_id="task-1",
            step_id="step-1",
            step_index=0,
            config_id="T-01",
            title="Task with grade",
            checklist=[
                {
                    "req_id": "R1",
                    "desc": "Existing reason is preserved",
                    "priority": "critical",
                    "status": "done",
                    "grade_reason": "keep reason",
                }
            ],
        ),
    )

    await _run_handler(
        harness,
        handle_set_checklist_grade,
        SetChecklistGradeCommand(
            run_id="run-1",
            task_id="task-1",
            req_id="R1",
            grade="B",
        ),
    )

    await _assert_latest_event(
        harness.session,
        "checklist_item_graded",
        {"task_id": "task-1", "req_id": "R1", "grade": "B", "grade_reason": None},
    )
    task = await _get_task(harness.session, "task-1")
    assert task.checklist[0]["grade"] == "B"
    assert task.checklist[0]["grade_reason"] == "keep reason"

    await _run_handler(
        harness,
        handle_set_checklist_grade,
        SetChecklistGradeCommand(
            run_id="run-1",
            task_id="task-1",
            req_id="R1",
            grade="A",
            grade_reason="excellent",
        ),
    )

    task = await _get_task(harness.session, "task-1")
    assert task.checklist[0]["grade"] == "A"
    assert task.checklist[0]["grade_reason"] == "excellent"


async def test_update_task_status_emits_event_and_projects_status(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness)

    await _run_handler(
        harness,
        handle_update_task_status,
        UpdateTaskStatusCommand(
            run_id="run-1",
            task_id="task-1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.VERIFYING,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "task_status_changed",
        {"task_id": "task-1", "old_status": "pending", "new_status": "verifying"},
    )
    task = await _get_task(harness.session, "task-1")
    assert task.status == "verifying"


async def test_record_clarification_request_emits_event_and_projects_pending_state(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness)

    await _run_handler(
        harness,
        handle_record_clarification_request,
        RecordClarificationRequestCommand(
            run_id="run-1",
            task_id="task-1",
            request_id="req-1",
            attempt_num=1,
            questions=[{"id": "q1", "question": "Which option?"}],
            requested_at=NOW,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "clarification_requested",
        {
            "task_id": "task-1",
            "request_id": "req-1",
            "attempt_num": 1,
            "question_count": 1,
            "questions": [{"id": "q1", "question": "Which option?"}],
        },
    )
    task = await _get_task(harness.session, "task-1")
    assert task.status == "pending_user_action"
    assert task.pending_action_type == "clarification"
    assert task.pending_clarification_id == "req-1"

    result = await harness.session.execute(
        text(
            "SELECT run_id, task_id, attempt_num, questions"
            " FROM clarification_requests WHERE id = 'req-1'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "run-1"
    assert row[1] == "task-1"
    assert row[2] == 1
    assert json.loads(row[3]) == [{"id": "q1", "question": "Which option?"}]


async def test_rewind_step_index_emits_event_and_rewinds_advanced_run(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)
    await harness.session.execute(text("UPDATE runs SET current_step_index = 3 WHERE id = 'run-1'"))
    await harness.session.flush()

    await _run_handler(
        harness,
        handle_rewind_step_index,
        RewindStepIndexCommand(run_id="run-1", target_step_index=1),
    )

    await _assert_latest_event(
        harness.session,
        "step_index_rewound",
        {"run_id": "run-1", "target_step_index": 1},
    )
    run = await _get_run(harness.session)
    assert run.current_step_index == 1


async def test_rewind_step_index_emits_event_without_moving_lower_run(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_rewind_step_index,
        RewindStepIndexCommand(run_id="run-1", target_step_index=2),
    )

    await _assert_latest_event(
        harness.session,
        "step_index_rewound",
        {"run_id": "run-1", "target_step_index": 2},
    )
    run = await _get_run(harness.session)
    assert run.current_step_index == 0


async def test_create_task_attempt_emits_event_and_projects_attempt(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness)

    await _run_handler(
        harness,
        handle_create_task_attempt,
        CreateTaskAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            attempt_num=1,
            runner_type="cli_subprocess",
            agent_model="gpt-5.3-codex",
            new_task_status=TaskStatus.FAILED,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "task_attempt_created",
        {
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "attempt_num": 1,
            "new_task_status": "failed",
        },
    )
    task = await _get_task(harness.session, "task-1")
    attempt = await _get_attempt(harness.session)
    assert task.current_attempt == 1
    assert task.status == "failed"
    assert attempt.runner_type == "cli_subprocess"
    assert attempt.agent_model == "gpt-5.3-codex"


async def test_update_latest_attempt_projects_attempt_and_task_status(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness)
    await _run_handler(
        harness,
        handle_create_task_attempt,
        CreateTaskAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            attempt_num=1,
        ),
    )

    await _run_handler(
        harness,
        handle_update_latest_attempt,
        UpdateLatestAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            output_lines=["line one", "line two"],
            error="transient failure",
            outcome="failed",
            builder_prompt="build it",
            verifier_prompt="verify it",
            paused_at="2025-01-15T10:31:00+00:00",
            auto_verify_results=[{"id": "output_exists", "passed": False, "output": "missing"}],
            action_log={"session_id": "session-1", "entries": []},
            token_usage_by_model=[{"model": "gpt-test", "input_tokens": 3}],
            tokens_read=10,
            tokens_write=4,
            tokens_cache=2,
            duration_ms=150,
            num_actions=3,
            new_task_status=TaskStatus.FAILED,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "attempt_updated",
        {
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "paused_at": "2025-01-15T10:31:00+00:00",
            "auto_verify_results": [{"id": "output_exists", "passed": False, "output": "missing"}],
            "new_task_status": "failed",
        },
    )
    task = await _get_task(harness.session, "task-1")
    attempt = await _get_attempt(harness.session)
    assert task.status == "failed"
    assert attempt.agent_output == "line one\nline two"
    assert attempt.error == "transient failure"
    assert attempt.outcome == "failed"
    assert attempt.builder_prompt == "build it"
    assert attempt.verifier_prompt == "verify it"
    assert attempt.paused_at == datetime(2025, 1, 15, 10, 31, 0)
    assert attempt.auto_verify_results == [
        {"id": "output_exists", "passed": False, "output": "missing"}
    ]
    assert attempt.tokens_read == 10
    assert attempt.tokens_write == 4
    assert attempt.tokens_cache == 2
    assert attempt.duration_ms == 150
    assert attempt.num_actions == 3
    assert attempt.action_log_json == {"session_id": "session-1", "entries": []}
    assert attempt.token_usage_by_model == [{"model": "gpt-test", "input_tokens": 3}]
    run = await _get_run(harness.session)
    assert run.total_tokens_read == 10
    assert run.total_tokens_write == 4
    assert run.total_tokens_cache == 2
    assert run.total_duration_ms == 150
    assert run.total_num_actions == 3
    assert run.token_usage_by_model == [{"model": "gpt-test", "input_tokens": 3}]

    await _run_handler(
        harness,
        handle_update_latest_attempt,
        UpdateLatestAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            clear_paused_state=True,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "attempt_updated",
        {
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "clear_paused_state": True,
        },
    )
    attempt = await _get_attempt(harness.session)
    assert attempt.outcome is None
    assert attempt.paused_at is None


async def test_update_latest_attempt_appends_output_and_accumulates_metrics(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness)
    await _run_handler(
        harness,
        handle_create_task_attempt,
        CreateTaskAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            attempt_num=1,
        ),
    )

    await _run_handler(
        harness,
        handle_update_latest_attempt,
        UpdateLatestAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            output_lines=["first"],
            tokens_read=1,
            tokens_write=2,
        ),
    )
    await _run_handler(
        harness,
        handle_update_latest_attempt,
        UpdateLatestAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id="attempt-1",
            output_lines=["second"],
            tokens_read=3,
            tokens_write=4,
            new_task_status=TaskStatus.VERIFYING,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "attempt_updated",
        {"task_id": "task-1", "attempt_id": "attempt-1", "new_task_status": "verifying"},
    )
    task = await _get_task(harness.session, "task-1")
    attempt = await _get_attempt(harness.session)
    assert task.status == "verifying"
    assert attempt.agent_output == "first\nsecond"
    assert attempt.tokens_read == 4
    assert attempt.tokens_write == 6
    run = await _get_run(harness.session)
    assert run.total_tokens_read == 4
    assert run.total_tokens_write == 6


async def test_update_run_metadata_merges_runner_config(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_update_run_metadata,
        UpdateRunMetadataCommand(
            run_id="run-1",
            runner_config_delta={"pid": 1234, "container_id": "abc"},
        ),
    )

    await _assert_latest_event(
        harness.session,
        "run_metadata_updated",
        {
            "runner_config_delta": {"pid": 1234, "container_id": "abc"},
        },
    )
    run = await _get_run(harness.session)
    assert run.runner_config == {"pid": 1234, "container_id": "abc"}


async def test_record_task_reverted_emits_event_and_projects_snapshot(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness, task_status=TaskStatus.VERIFYING)

    snapshot = {
        "id": "task-1",
        "config_id": "TASK-1",
        "title": "Task task-1",
        "status": "building",
        "complexity": "standard",
        "checklist": [{"id": "R1", "text": "pass", "status": "open"}],
        "attempts": [
            {
                "id": "attempt-1",
                "attempt_num": 1,
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:30:00Z",
                "outcome": "reverted",
                "metrics": {
                    "tokens_read": 1,
                    "tokens_write": 2,
                    "tokens_cache": 0,
                    "duration_ms": 3,
                    "num_actions": 4,
                },
            },
            {
                "id": "attempt-2",
                "attempt_num": 2,
                "started_at": "2025-01-15T10:30:00Z",
                "completed_at": None,
                "outcome": None,
                "metrics": {},
            },
        ],
        "current_attempt": 2,
        "max_attempts": 3,
        "pending_action_type": None,
        "pending_clarification_id": None,
    }

    await _run_handler(
        harness,
        handle_record_task_reverted,
        RecordTaskRevertedCommand(
            run_id="run-1",
            task_id="task-1",
            reverted_from_status=TaskStatus.VERIFYING,
            task_snapshot=snapshot,
        ),
    )

    await _assert_latest_event(
        harness.session,
        "task_reverted",
        {
            "task_id": "task-1",
            "reverted_from_status": "verifying",
            "task_snapshot": snapshot,
        },
    )
    task = await _get_task(harness.session, "task-1")
    attempts = await harness.session.execute(
        select(AttemptModel)
        .where(AttemptModel.task_id == "task-1")
        .order_by(AttemptModel.attempt_num)
    )
    attempt_rows = list(attempts.scalars())
    assert task.status == "building"
    assert task.current_attempt == 2
    assert [attempt.id for attempt in attempt_rows] == ["attempt-1", "attempt-2"]
    assert attempt_rows[0].outcome == "reverted"
    assert attempt_rows[0].tokens_read == 1


async def test_update_parent_oversight_facts_emits_event_and_projects_merged_state(
    harness: CommandHarness,
) -> None:
    await _create_run(harness)

    await _run_handler(
        harness,
        handle_update_parent_oversight_facts,
        UpdateParentOversightFactsCommand(
            run_id="run-1",
            patch={
                "coordination_warnings": ["missing child evidence"],
                "delegated_work": {"task-1": {"status": "active"}},
            },
        ),
    )
    await _run_handler(
        harness,
        handle_update_parent_oversight_facts,
        UpdateParentOversightFactsCommand(
            run_id="run-1",
            patch={
                "coordination_warnings": ["missing child evidence"],
                "delegated_work": {"task-2": {"status": "pending"}},
            },
        ),
    )

    await _assert_latest_event(
        harness.session,
        "parent_oversight_facts_updated",
        {"run_id": "run-1"},
    )
    run = await _get_run(harness.session)
    assert run.oversight_state["coordination_warnings"] == ["missing child evidence"]
    assert run.oversight_state["delegated_work"] == {
        "task-1": {"status": "active"},
        "task-2": {"status": "pending"},
    }


async def test_create_fan_out_children_emits_event_and_projects_children_and_parent_status(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness)

    await _run_handler(
        harness,
        handle_create_fan_out_children,
        CreateFanOutChildrenCommand(
            run_id="run-1",
            step_id="step-1",
            parent_task_id="task-1",
            parent_new_status=TaskStatus.FAN_OUT_RUNNING,
            children=[
                {
                    "id": "child-1",
                    "config_id": "T-child-1",
                    "title": "Child 1",
                    "fan_out_index": 0,
                    "fan_out_input": "input-1",
                    "fan_out_output": "output-1",
                    "child_id": "stable-child-1",
                    "checklist": [{"id": "R2", "text": "child"}],
                    "has_verification": False,
                },
                {
                    "id": "child-2",
                    "config_id": "T-child-2",
                    "title": "Child 2",
                    "fan_out_index": 1,
                    "fan_out_input": "input-2",
                    "fan_out_output": "output-2",
                    "child_id": "stable-child-2",
                },
            ],
        ),
    )

    await _assert_latest_event(
        harness.session,
        "fan_out_children_created",
        {"parent_task_id": "task-1", "parent_new_status": "fan_out_running"},
    )
    events = await _stored_events(harness.session)
    payload = json.loads(events[-1].payload)
    assert payload["children"][0]["has_verification"] is False
    assert "has_verification" not in payload["children"][1]
    parent = await _get_task(harness.session, "task-1")
    child = await _get_task(harness.session, "child-1")
    child_default = await _get_task(harness.session, "child-2")
    assert parent.status == "fan_out_running"
    assert child.parent_task_id == "task-1"
    assert child.status == "pending"
    assert child.has_verification == 0
    assert child_default.has_verification == 1
    assert child.fan_out_index == 0
    assert child.fan_out_input == "input-1"
    assert child.fan_out_output == "output-1"
    assert child.child_id == "stable-child-1"
    assert child.checklist == [{"id": "R2", "text": "child"}]


async def test_reset_fan_out_children_emits_event_and_resets_only_non_completed_children(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness, task_status=TaskStatus.FAN_OUT_RUNNING)
    await _create_task(
        harness, task_id="child-1", status=TaskStatus.FAILED, parent_task_id="task-1"
    )
    await _create_task(
        harness,
        task_id="child-2",
        status=TaskStatus.COMPLETED,
        parent_task_id="task-1",
    )

    await _run_handler(
        harness,
        handle_reset_fan_out_children,
        ResetFanOutChildrenCommand(run_id="run-1", parent_task_id="task-1"),
    )

    await _assert_latest_event(
        harness.session,
        "fan_out_children_reset",
        {"parent_task_id": "task-1"},
    )
    parent = await _get_task(harness.session, "task-1")
    failed_child = await _get_task(harness.session, "child-1")
    completed_child = await _get_task(harness.session, "child-2")
    assert parent.status == "fan_out_running"
    assert failed_child.status == "pending"
    assert completed_child.status == "completed"


async def test_retry_fan_out_child_emits_retry_and_rewind_events_and_projects_state(
    harness: CommandHarness,
) -> None:
    await _create_base_run_step_task(harness, task_status=TaskStatus.FAN_OUT_RUNNING)
    await _create_task(
        harness, task_id="child-1", status=TaskStatus.FAILED, parent_task_id="task-1"
    )
    await harness.session.execute(text("UPDATE runs SET current_step_index = 3 WHERE id = 'run-1'"))
    await harness.session.execute(text("UPDATE steps SET completed = 1 WHERE id = 'step-1'"))
    await harness.session.flush()

    await _run_handler(
        harness,
        handle_retry_fan_out_child,
        RetryFanOutChildCommand(run_id="run-1", child_task_id="child-1", step_order_index=1),
    )

    await _assert_latest_events(
        harness.session,
        ["fan_out_child_retried", "step_index_rewound"],
    )
    parent = await _get_task(harness.session, "task-1")
    child = await _get_task(harness.session, "child-1")
    run = await _get_run(harness.session)
    step = await _get_step(harness.session)
    assert parent.status == "fan_out_running"
    assert child.status == "pending"
    assert run.current_step_index == 1
    assert not step.completed
