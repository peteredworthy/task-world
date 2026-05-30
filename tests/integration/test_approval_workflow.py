"""Integration tests for approval workflow."""

import json
from datetime import datetime, timezone

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import (
    RunStateProjector,
    SqliteEventStore,
    StoredEvent,
    TaskStateProjector,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import deserialize_event
from orchestrator.workflow.service import WorkflowService


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


@pytest.fixture
def event_store(session: AsyncSession) -> SqliteEventStore:
    return SqliteEventStore(session)


def _make_run_with_pending_approval() -> Run:
    """Create a run with a task in PENDING_USER_ACTION state with approval action."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING_USER_ACTION,
                        pending_action_type="approval",
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Complete the task",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        attempts=[
                            Attempt(
                                attempt_num=1,
                                started_at=now,
                            )
                        ],
                        max_attempts=3,
                        current_attempt=1,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _json_value(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


async def _replay_task_projection(
    events: list[StoredEvent],
    task_id: str,
) -> dict[str, object]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    try:
        async with factory() as replay_session:
            run_projector = RunStateProjector()
            task_projector = TaskStateProjector()
            for stored in events:
                event = deserialize_event(stored.event_type, stored.payload)
                await run_projector.handle(event, replay_session)
                await task_projector.handle(event, replay_session)
            await replay_session.flush()

            task_result = await replay_session.execute(
                text(
                    "SELECT status, pending_action_type, current_attempt, checklist"
                    " FROM tasks WHERE id = :task_id"
                ),
                {"task_id": task_id},
            )
            task_row = task_result.fetchone()
            assert task_row is not None

            attempts_result = await replay_session.execute(
                text(
                    "SELECT attempt_num, completed_at, outcome"
                    " FROM attempts WHERE task_id = :task_id ORDER BY attempt_num"
                ),
                {"task_id": task_id},
            )
            attempts = [
                {
                    "attempt_num": row[0],
                    "completed_at": row[1],
                    "outcome": row[2],
                }
                for row in attempts_result.fetchall()
            ]
            return {
                "status": task_row[0],
                "pending_action_type": task_row[1],
                "current_attempt": task_row[2],
                "checklist": _json_value(task_row[3]),
                "attempts": attempts,
            }
    finally:
        await engine.dispose()


async def test_approve_task_transitions_to_completed(
    service: WorkflowService,
    event_store: SqliteEventStore,
) -> None:
    """Test approval: task in PENDING_USER_ACTION -> approve -> COMPLETED."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Approve the task
    result = await service.approve_task(
        run_id="run-1",
        task_id="task-1",
        approved_by="reviewer@example.com",
        comment="Looks good!",
    )

    # Verify transition to COMPLETED
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED

    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.COMPLETED
    assert task.pending_action_type is None
    # Verify the attempt was marked completed
    assert len(task.attempts) > 0
    assert task.attempts[-1].completed_at is not None
    assert task.attempts[-1].outcome == "passed"

    replayed = await _replay_task_projection(await event_store.get_stream("run-1"), "task-1")
    assert replayed["status"] == "completed"
    assert replayed["pending_action_type"] is None
    assert replayed["current_attempt"] == 1
    attempts = replayed["attempts"]
    assert isinstance(attempts, list)
    assert attempts[-1]["outcome"] == "passed"
    assert attempts[-1]["completed_at"] is not None


async def test_reject_task_transitions_to_building(
    service: WorkflowService,
    event_store: SqliteEventStore,
) -> None:
    """Test rejection: task in PENDING_USER_ACTION -> reject -> BUILDING (new attempt)."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Get initial attempt number
    task_before = await service.get_task("run-1", "task-1")
    initial_attempt = task_before.current_attempt

    # Reject the task
    result = await service.reject_task(
        run_id="run-1",
        task_id="task-1",
        rejected_by="reviewer@example.com",
        reason="Needs revision - add error handling",
    )

    # Verify transition to BUILDING with new attempt
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING

    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.BUILDING
    assert task.pending_action_type is None
    assert task.current_attempt == initial_attempt + 1
    assert len(task.attempts) == initial_attempt + 1

    replayed = await _replay_task_projection(await event_store.get_stream("run-1"), "task-1")
    assert replayed["status"] == "building"
    assert replayed["pending_action_type"] is None
    assert replayed["current_attempt"] == initial_attempt + 1
    attempts = replayed["attempts"]
    assert isinstance(attempts, list)
    assert [attempt["attempt_num"] for attempt in attempts] == [1, 2]


async def test_approval_decision_event_emitted_on_approve(
    service: WorkflowService,
    event_store: SqliteEventStore,
) -> None:
    """Test ApprovalDecision event is emitted with correct fields on approval."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Approve the task
    await service.approve_task(
        run_id="run-1",
        task_id="task-1",
        approved_by="reviewer@example.com",
        comment="Excellent work!",
    )

    # Query events
    events = await event_store.get_stream("run-1")

    # Find the approval_decision event
    approval_events = [e for e in events if e.event_type == "approval_decision"]
    assert len(approval_events) == 1

    event = json.loads(approval_events[0].payload)
    assert event["run_id"] == "run-1"
    assert event["task_id"] == "task-1"
    assert event["step_id"] == "step-1"
    assert event["approved"] is True
    assert event["comment"] == "Excellent work!"
    assert event["decided_by"] == "reviewer@example.com"
    assert event["new_status"] == "completed"
    assert event["current_attempt"] == 1
    assert event["attempt_snapshots"][-1]["outcome"] == "passed"
    assert event["attempt_snapshots"][-1]["completed_at"] is not None
    assert "timestamp" in event


async def test_approval_decision_event_emitted_on_reject(
    service: WorkflowService,
    event_store: SqliteEventStore,
) -> None:
    """Test ApprovalDecision event is emitted with correct fields on rejection."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Reject the task
    await service.reject_task(
        run_id="run-1",
        task_id="task-1",
        rejected_by="reviewer@example.com",
        reason="Missing test coverage",
    )

    # Query events
    events = await event_store.get_stream("run-1")

    # Find the approval_decision event
    approval_events = [e for e in events if e.event_type == "approval_decision"]
    assert len(approval_events) == 1

    event = json.loads(approval_events[0].payload)
    assert event["run_id"] == "run-1"
    assert event["task_id"] == "task-1"
    assert event["step_id"] == "step-1"
    assert event["approved"] is False
    assert event["comment"] == "Missing test coverage"
    assert event["decided_by"] == "reviewer@example.com"
    assert event["new_status"] == "building"
    assert event["current_attempt"] == 2
    assert len(event["attempt_snapshots"]) == 2
    assert "timestamp" in event


async def test_get_pending_actions_includes_approval(
    service: WorkflowService,
) -> None:
    """Test that get_pending_actions includes approval tasks."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Get pending actions
    actions = await service.get_pending_actions("run-1")

    # Should have one pending approval action
    assert len(actions) == 1
    action = actions[0]
    assert action["task_id"] == "task-1"
    assert action["step_id"] == "step-1"
    assert action["action_type"] == "approval"


async def test_approve_without_comment(
    service: WorkflowService,
) -> None:
    """Test approval without optional comment."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Approve without comment
    result = await service.approve_task(
        run_id="run-1",
        task_id="task-1",
        approved_by="reviewer@example.com",
    )

    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED


async def test_reject_without_reason(
    service: WorkflowService,
) -> None:
    """Test rejection without optional reason."""
    run = _make_run_with_pending_approval()
    await service.create_run(run)

    # Reject without reason
    result = await service.reject_task(
        run_id="run-1",
        task_id="task-1",
        rejected_by="reviewer@example.com",
    )

    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING


async def test_reject_at_max_attempts_transitions_to_failed_and_replays(
    service: WorkflowService,
    event_store: SqliteEventStore,
) -> None:
    """Rejection at max attempts reaches terminal failure and replays from events_v2."""
    run = _make_run_with_pending_approval()
    task = run.steps[0].tasks[0]
    task.current_attempt = 1
    task.max_attempts = 1
    await service.create_run(run)

    result = await service.reject_task(
        run_id="run-1",
        task_id="task-1",
        rejected_by="reviewer@example.com",
        reason="Still missing required behavior",
    )

    assert result.success is True
    assert result.new_status == TaskStatus.FAILED

    task_after = await service.get_task("run-1", "task-1")
    assert task_after.status == TaskStatus.FAILED
    assert task_after.pending_action_type is None
    assert task_after.current_attempt == 1
    assert task_after.attempts[-1].outcome == "failed"
    assert task_after.attempts[-1].completed_at is not None

    replayed = await _replay_task_projection(await event_store.get_stream("run-1"), "task-1")
    assert replayed["status"] == "failed"
    assert replayed["pending_action_type"] is None
    assert replayed["current_attempt"] == 1
    attempts = replayed["attempts"]
    assert isinstance(attempts, list)
    assert attempts[-1]["outcome"] == "failed"
    assert attempts[-1]["completed_at"] is not None


async def test_get_pending_actions_excludes_future_steps(
    service: WorkflowService,
) -> None:
    """Pending actions should only be returned for the current actionable step."""
    run = _make_run_with_pending_approval()
    run.steps.append(
        StepState(
            id="step-2",
            config_id="S-02",
            tasks=[
                TaskState(
                    id="task-2",
                    config_id="T-01",
                    status=TaskStatus.PENDING_USER_ACTION,
                    pending_action_type="approval",
                    checklist=[
                        ChecklistItem(
                            req_id="R1",
                            desc="Future step approval",
                            priority=Priority.CRITICAL,
                        )
                    ],
                    max_attempts=3,
                    current_attempt=0,
                )
            ],
        )
    )
    run.current_step_index = 0
    await service.create_run(run)

    actions = await service.get_pending_actions("run-1")

    assert len(actions) == 1
    assert actions[0]["step_id"] == "step-1"
    assert actions[0]["task_id"] == "task-1"
