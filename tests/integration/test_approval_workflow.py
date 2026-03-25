"""Integration tests for approval workflow."""

from datetime import datetime, timezone

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import (
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
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
def event_store(session: AsyncSession) -> EventStore:
    return EventStore(session)


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


async def test_approve_task_transitions_to_completed(
    service: WorkflowService,
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


async def test_reject_task_transitions_to_building(
    service: WorkflowService,
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


async def test_approval_decision_event_emitted_on_approve(
    service: WorkflowService,
    event_store: EventStore,
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
    events = await event_store.get_events_for_run(run_id="run-1")

    # Find the approval_decision event
    approval_events = [e for e in events if e.get("type") == "approval_decision"]
    assert len(approval_events) == 1

    event = approval_events[0]["payload"]
    assert event["run_id"] == "run-1"
    assert event["task_id"] == "task-1"
    assert event["step_id"] == "step-1"
    assert event["approved"] is True
    assert event["comment"] == "Excellent work!"
    assert event["decided_by"] == "reviewer@example.com"
    assert "timestamp" in event


async def test_approval_decision_event_emitted_on_reject(
    service: WorkflowService,
    event_store: EventStore,
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
    events = await event_store.get_events_for_run(run_id="run-1")

    # Find the approval_decision event
    approval_events = [e for e in events if e.get("type") == "approval_decision"]
    assert len(approval_events) == 1

    event = approval_events[0]["payload"]
    assert event["run_id"] == "run-1"
    assert event["task_id"] == "task-1"
    assert event["step_id"] == "step-1"
    assert event["approved"] is False
    assert event["comment"] == "Missing test coverage"
    assert event["decided_by"] == "reviewer@example.com"
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
