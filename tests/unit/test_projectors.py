"""Unit tests for RunStateProjector and TaskStateProjector."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import AgentRunnerType, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import AttemptModel, RunModel, StepModel, TaskModel
from orchestrator.db import ProjectionRegistry, RunStateProjector, TaskStateProjector
from orchestrator.workflow import (
    AgentChangedEvent,
    AttemptUpdated,
    ApprovalDecision,
    AutoVerifyCompleted,
    ChecklistGateEvaluated,
    ClarificationRequested,
    ClarificationResponded,
    GradesEvaluated,
    HealthCheckEvent,
    RunCreated,
    RunDeleted,
    RunStatusChanged,
    RunStepBackward,
    StepCompleted,
    StepCreated,
    StepHumanApprovalRecorded,
    StepSkipped,
    TaskCreated,
    TaskAttemptCreated,
    TaskReverted,
    TaskStatusChanged,
)

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def populated_session(session: AsyncSession) -> AsyncSession:
    """Session with a run, step, and task pre-populated."""
    run = RunModel(
        id="r1",
        repo_name="proj-1",
        status="draft",
        runner_config={},
        config={},
        created_at=NOW,
        updated_at=NOW,
    )
    step = StepModel(id="s1", run_id="r1", config_id="S-01", order_index=0)
    # Use text() to insert TaskModel bypassing ORM version_id_col issues in tests
    session.add(run)
    session.add(step)
    await session.flush()
    # Insert task via raw SQL to avoid version_id_col conflicts
    await session.execute(
        text(
            "INSERT INTO tasks (id, step_id, config_id, title, complexity, order_index,"
            " status, checklist, current_attempt, max_attempts, version)"
            " VALUES ('t1', 's1', 'T-01', '', 'standard', 0,"
            " 'pending', '[]', 0, 3, 1)"
        )
    )
    await session.flush()
    return session


async def _get_run(session: AsyncSession, run_id: str) -> RunModel:
    result = await session.execute(select(RunModel).where(RunModel.id == run_id))
    return result.scalar_one()


async def _get_step(session: AsyncSession, step_id: str) -> StepModel:
    result = await session.execute(select(StepModel).where(StepModel.id == step_id))
    return result.scalar_one()


async def _get_task(session: AsyncSession, task_id: str) -> TaskModel:
    result = await session.execute(text(f"SELECT * FROM tasks WHERE id = '{task_id}'"))
    row = result.fetchone()
    assert row is not None
    return row  # type: ignore[return-value]


async def _get_task_model(session: AsyncSession, task_id: str) -> TaskModel:
    result = await session.execute(select(TaskModel).where(TaskModel.id == task_id))
    return result.scalar_one()


async def _get_attempts(session: AsyncSession, task_id: str) -> list[AttemptModel]:
    result = await session.execute(
        select(AttemptModel)
        .where(AttemptModel.task_id == task_id)
        .order_by(AttemptModel.attempt_num)
    )
    return list(result.scalars())


async def test_run_status_changed_updates_run_model(populated_session: AsyncSession) -> None:
    projector = RunStateProjector()
    event = RunStatusChanged(
        run_id="r1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.status == "active"
    assert run.started_at == NOW.replace(tzinfo=None)


@pytest.mark.parametrize(
    "terminal_status",
    [RunStatus.FAILED, RunStatus.COMPLETED],
)
async def test_run_status_changed_sets_completed_at_for_terminal_status(
    populated_session: AsyncSession,
    terminal_status: RunStatus,
) -> None:
    projector = RunStateProjector()
    event = RunStatusChanged(
        run_id="r1",
        event_type="run_status_changed",
        old_status=RunStatus.ACTIVE,
        new_status=terminal_status,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.status == terminal_status.value
    assert run.completed_at == NOW.replace(tzinfo=None)


async def test_run_status_changed_clears_completed_at_for_recovery_pause(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text("UPDATE runs SET status = 'failed', completed_at = :completed_at WHERE id = 'r1'"),
        {"completed_at": NOW.replace(tzinfo=None)},
    )
    await populated_session.flush()

    projector = RunStateProjector()
    event = RunStatusChanged(
        run_id="r1",
        event_type="run_status_changed",
        old_status=RunStatus.FAILED,
        new_status=RunStatus.PAUSED,
        pause_reason="recovered",
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.status == "paused"
    assert run.pause_reason == "recovered"
    assert run.completed_at is None


async def test_agent_changed_updates_run_agent_fields(populated_session: AsyncSession) -> None:
    projector = RunStateProjector()
    event = AgentChangedEvent(
        run_id="r1",
        timestamp=NOW,
        old_agent=AgentRunnerType.CLI_SUBPROCESS,
        new_agent=AgentRunnerType.CLAUDE_SDK,
        old_agent_runner_config={"model": "gpt-5.3-codex"},
        new_agent_runner_config={"model": "claude-sonnet-4-6"},
    )

    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.runner_type == AgentRunnerType.CLAUDE_SDK.value
    assert run.runner_config == {"model": "claude-sonnet-4-6"}


async def test_clarification_responded_applies_run_config_delta(
    populated_session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = ClarificationResponded(
        run_id="r1",
        event_type="clarification_responded",
        task_id="t1",
        request_id="req-42",
        run_config_delta={
            "_compressed_decisions": [
                {
                    "question": "Which color?",
                    "decision": "Blue",
                    "rationale": "Selected option",
                }
            ],
            "_compressed_decisions_request_id": "req-42",
        },
        timestamp=NOW,
    )

    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.config == {
        "_compressed_decisions": [
            {
                "question": "Which color?",
                "decision": "Blue",
                "rationale": "Selected option",
            }
        ],
        "_compressed_decisions_request_id": "req-42",
    }


async def test_step_completed_marks_step_and_advances_run(populated_session: AsyncSession) -> None:
    projector = RunStateProjector()
    event = StepCompleted(
        run_id="r1",
        event_type="step_completed",
        step_id="s1",
        step_index=0,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    step_result = await populated_session.execute(
        text("SELECT completed FROM steps WHERE id = 's1'")
    )
    step_row = step_result.fetchone()
    assert step_row is not None
    assert step_row[0] == 1  # completed=True (stored as integer in SQLite)

    run_result = await populated_session.execute(
        text("SELECT current_step_index FROM runs WHERE id = 'r1'")
    )
    run_row = run_result.fetchone()
    assert run_row is not None
    assert run_row[0] == 1  # step_index + 1 = 0 + 1


async def test_step_skipped_sets_skip_fields_and_advances_run(
    populated_session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = StepSkipped(
        run_id="r1",
        event_type="step_skipped",
        step_id="s1",
        step_index=0,
        skip_reason="condition not met",
        completed=True,
        current_step_index_after=3,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(
        text("SELECT skipped, skip_reason, completed FROM steps WHERE id = 's1'")
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == 1  # skipped=True
    assert row[1] == "condition not met"
    assert row[2] == 1  # completed=True

    run_result = await populated_session.execute(
        text("SELECT current_step_index FROM runs WHERE id = 'r1'")
    )
    run_row = run_result.fetchone()
    assert run_row is not None
    assert run_row[0] == 3


async def test_step_skipped_defaults_current_step_index_after_to_next_step(
    populated_session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = StepSkipped(
        run_id="r1",
        event_type="step_skipped",
        step_id="s1",
        step_index=0,
        skip_reason="condition not met",
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(
        text("SELECT current_step_index FROM runs WHERE id = 'r1'")
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_step_human_approval_recorded_updates_step(
    populated_session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = StepHumanApprovalRecorded(
        run_id="r1",
        step_id="s1",
        approved_by="reviewer@example.com",
        approved_at=NOW,
        comment="Approved",
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    step = await _get_step(populated_session, "s1")
    assert step.human_approval == {
        "approved_by": "reviewer@example.com",
        "approved_at": "2025-01-15T10:30:00Z",
        "comment": "Approved",
    }


async def test_task_status_changed_updates_task_model(populated_session: AsyncSession) -> None:
    projector = TaskStateProjector()
    event = TaskStatusChanged(
        run_id="r1",
        event_type="task_status_changed",
        task_id="t1",
        old_status=TaskStatus.PENDING,
        new_status=TaskStatus.BUILDING,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(text("SELECT status FROM tasks WHERE id = 't1'"))
    row = result.fetchone()
    assert row is not None
    assert row[0] == "building"


async def test_task_reverted_restores_task_and_attempts_from_snapshot(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'verifying', current_attempt = 1,"
            " max_attempts = 2, pending_action_type = 'approval',"
            " pending_clarification_id = 'old-request' WHERE id = 't1'"
        )
    )
    populated_session.add(
        AttemptModel(
            id="old-attempt",
            task_id="t1",
            attempt_num=1,
            attempt_id="old-attempt",
            outcome="paused",
        )
    )
    await populated_session.flush()

    snapshot = {
        "id": "t1",
        "config_id": "T-01",
        "title": "Reverted task",
        "status": "building",
        "complexity": "standard",
        "checklist": [
            {
                "req_id": "R1",
                "desc": "Do it",
                "priority": "critical",
                "status": "open",
                "note": None,
                "grade": None,
                "grade_reason": None,
            }
        ],
        "attempts": [
            {
                "id": "attempt-1",
                "attempt_num": 1,
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:30:00Z",
                "paused_at": None,
                "outcome": "reverted",
                "metrics": {
                    "tokens_read": 7,
                    "tokens_write": 3,
                    "tokens_cache": 1,
                    "duration_ms": 250,
                    "num_actions": 2,
                },
                "grade_snapshot": [],
                "auto_verify_results": [],
                "token_usage_by_model": [],
                "agent_runner_type": "cli_subprocess",
                "agent_model": "gpt-5.3-codex",
                "agent_settings": {"model": "gpt-5.3-codex"},
                "agent_output": "partial output",
                "error": None,
                "action_log": None,
                "start_commit": "abc",
                "end_commit": "def",
            },
            {
                "id": "attempt-2",
                "attempt_num": 2,
                "started_at": "2025-01-15T10:30:00Z",
                "completed_at": None,
                "paused_at": None,
                "outcome": None,
                "metrics": {
                    "tokens_read": 0,
                    "tokens_write": 0,
                    "tokens_cache": 0,
                    "duration_ms": 0,
                    "num_actions": 0,
                },
                "grade_snapshot": [],
                "auto_verify_results": [],
                "token_usage_by_model": [],
                "agent_runner_type": "cli_subprocess",
                "agent_model": "gpt-5.3-codex",
                "agent_settings": {"model": "gpt-5.3-codex"},
                "agent_output": None,
                "error": None,
                "action_log": None,
                "start_commit": "abc",
                "end_commit": None,
            },
        ],
        "current_attempt": 2,
        "max_attempts": 3,
        "has_verification": False,
        "pending_action_type": None,
        "pending_clarification_id": None,
        "parent_task_id": None,
        "fan_out_index": None,
        "fan_out_input": None,
        "fan_out_output": None,
        "child_id": None,
    }

    projector = TaskStateProjector()
    event = TaskReverted(
        run_id="r1",
        event_type="task_reverted",
        task_id="t1",
        reverted_from_status=TaskStatus.VERIFYING,
        task_snapshot=snapshot,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.status == "building"
    assert task.current_attempt == 2
    assert task.max_attempts == 3
    assert task.has_verification == 0
    assert task.pending_action_type is None
    assert task.pending_clarification_id is None
    assert task.checklist == snapshot["checklist"]

    attempts = await _get_attempts(populated_session, "t1")
    assert [attempt.id for attempt in attempts] == ["attempt-1", "attempt-2"]
    assert attempts[0].outcome == "reverted"
    assert attempts[0].completed_at == NOW.replace(tzinfo=None)
    assert attempts[0].tokens_read == 7
    assert attempts[0].runner_type == "cli_subprocess"
    assert attempts[0].start_commit == "abc"
    assert attempts[1].outcome is None
    assert attempts[1].start_commit == "abc"


async def test_task_reverted_without_has_verification_keeps_existing_value(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(text("UPDATE tasks SET has_verification = 0 WHERE id = 't1'"))
    await populated_session.flush()

    snapshot = {
        "id": "t1",
        "config_id": "T-01",
        "title": "Reverted task",
        "status": "building",
        "complexity": "standard",
        "checklist": [],
        "attempts": [],
        "current_attempt": 0,
        "max_attempts": 3,
    }

    projector = TaskStateProjector()
    event = TaskReverted(
        run_id="r1",
        event_type="task_reverted",
        task_id="t1",
        reverted_from_status=TaskStatus.VERIFYING,
        task_snapshot=snapshot,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.has_verification == 0


async def test_clarification_requested_sets_pending(populated_session: AsyncSession) -> None:
    projector = TaskStateProjector()
    event = ClarificationRequested(
        run_id="r1",
        event_type="clarification_requested",
        task_id="t1",
        request_id="req-42",
        attempt_num=2,
        question_count=1,
        questions=[{"id": "q1", "question": "What should change?"}],
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(
        text(
            "SELECT status, pending_action_type, pending_clarification_id"
            " FROM tasks WHERE id = 't1'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "pending_user_action"
    assert row[1] == "clarification"
    assert row[2] == "req-42"

    result = await populated_session.execute(
        text(
            "SELECT run_id, task_id, attempt_num, questions, created_at"
            " FROM clarification_requests WHERE id = 'req-42'"
        )
    )
    request_row = result.fetchone()
    assert request_row is not None
    assert request_row[0] == "r1"
    assert request_row[1] == "t1"
    assert request_row[2] == 2
    assert json.loads(request_row[3]) == [{"id": "q1", "question": "What should change?"}]
    assert request_row[4] is not None


async def test_clarification_responded_clears_pending(populated_session: AsyncSession) -> None:
    # First set pending
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'pending_user_action',"
            " pending_action_type = 'clarification',"
            " pending_clarification_id = 'req-42' WHERE id = 't1'"
        )
    )
    await populated_session.execute(
        text(
            "INSERT INTO clarification_requests"
            " (id, run_id, task_id, attempt_num, questions, created_at)"
            " VALUES ('req-42', 'r1', 't1', 1, '[]', :created_at)"
        ),
        {"created_at": NOW},
    )
    await populated_session.flush()

    projector = TaskStateProjector()
    event = ClarificationResponded(
        run_id="r1",
        event_type="clarification_responded",
        task_id="t1",
        request_id="req-42",
        response_id="resp-42",
        answers=[{"question_id": "q1", "free_text": "Use blue", "answered_by": "user"}],
        responded_by="user",
        responded_at=NOW,
        new_status=TaskStatus.BUILDING,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(
        text(
            "SELECT status, pending_action_type, pending_clarification_id"
            " FROM tasks WHERE id = 't1'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "building"
    assert row[1] is None
    assert row[2] is None

    request_result = await populated_session.execute(
        text("SELECT responded_at FROM clarification_requests WHERE id = 'req-42'")
    )
    request_row = request_result.fetchone()
    assert request_row is not None
    assert request_row[0] is not None

    response_result = await populated_session.execute(
        text(
            "SELECT request_id, answers, responded_by"
            " FROM clarification_responses WHERE id = 'resp-42'"
        )
    )
    response_row = response_result.fetchone()
    assert response_row is not None
    assert response_row[0] == "req-42"
    assert json.loads(response_row[1]) == [
        {"question_id": "q1", "free_text": "Use blue", "answered_by": "user"}
    ]
    assert response_row[2] == "user"


async def test_clarification_responded_legacy_payload_only_clears_pending(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'pending_user_action',"
            " pending_action_type = 'clarification',"
            " pending_clarification_id = 'req-42' WHERE id = 't1'"
        )
    )
    await populated_session.flush()

    projector = TaskStateProjector()
    event = ClarificationResponded(
        run_id="r1",
        event_type="clarification_responded",
        task_id="t1",
        request_id="req-42",
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(
        text(
            "SELECT status, pending_action_type, pending_clarification_id"
            " FROM tasks WHERE id = 't1'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "pending_user_action"
    assert row[1] is None
    assert row[2] is None


async def test_clarification_responded_empty_answers_inserts_response_row(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'pending_user_action',"
            " pending_action_type = 'clarification',"
            " pending_clarification_id = 'req-empty' WHERE id = 't1'"
        )
    )
    await populated_session.execute(
        text(
            "INSERT INTO clarification_requests"
            " (id, run_id, task_id, attempt_num, questions, created_at)"
            " VALUES ('req-empty', 'r1', 't1', 1, '[]', :created_at)"
        ),
        {"created_at": NOW},
    )
    await populated_session.flush()

    projector = TaskStateProjector()
    event = ClarificationResponded(
        run_id="r1",
        event_type="clarification_responded",
        task_id="t1",
        request_id="req-empty",
        response_id="resp-empty",
        answers=[],
        responded_by=None,
        responded_at=NOW,
        new_status=TaskStatus.BUILDING,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    response_result = await populated_session.execute(
        text(
            "SELECT request_id, answers, responded_by"
            " FROM clarification_responses WHERE id = 'resp-empty'"
        )
    )
    response_row = response_result.fetchone()
    assert response_row is not None
    assert response_row[0] == "req-empty"
    assert json.loads(response_row[1]) == []
    assert response_row[2] == "unknown"


async def test_approval_decision_approve_projects_completion(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'pending_user_action',"
            " pending_action_type = 'approval', current_attempt = 1 WHERE id = 't1'"
        )
    )
    await populated_session.flush()

    projector = TaskStateProjector()
    event = ApprovalDecision(
        run_id="r1",
        event_type="approval_decision",
        task_id="t1",
        step_id="s1",
        approved=True,
        decided_by="reviewer",
        new_status=TaskStatus.COMPLETED,
        current_attempt=1,
        attempt_snapshots=[
            {
                "id": "attempt-1",
                "attempt_num": 1,
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:30:00Z",
                "outcome": "passed",
            }
        ],
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.status == "completed"
    assert task.pending_action_type is None
    attempts = await _get_attempts(populated_session, "t1")
    assert len(attempts) == 1
    assert attempts[0].outcome == "passed"
    assert attempts[0].completed_at is not None


async def test_approval_decision_reject_projects_retry_attempt_and_checklist_reset(
    populated_session: AsyncSession,
) -> None:
    checklist = [
        {
            "req_id": "R1",
            "desc": "Do it",
            "priority": "critical",
            "status": "open",
            "note": "stale builder note",
        }
    ]
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'pending_user_action',"
            " pending_action_type = 'approval', current_attempt = 1,"
            " checklist = :checklist WHERE id = 't1'"
        ),
        {"checklist": json.dumps(checklist)},
    )
    await populated_session.flush()

    projected_checklist = [dict(checklist[0], note=None)]
    projector = TaskStateProjector()
    event = ApprovalDecision(
        run_id="r1",
        event_type="approval_decision",
        task_id="t1",
        step_id="s1",
        approved=False,
        comment="needs work",
        decided_by="reviewer",
        new_status=TaskStatus.BUILDING,
        current_attempt=2,
        checklist=projected_checklist,
        attempt_snapshots=[
            {
                "id": "attempt-1",
                "attempt_num": 1,
                "started_at": "2025-01-15T10:00:00Z",
            },
            {
                "id": "attempt-2",
                "attempt_num": 2,
                "started_at": "2025-01-15T10:30:00Z",
            },
        ],
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.status == "building"
    assert task.pending_action_type is None
    assert task.current_attempt == 2
    assert task.checklist == projected_checklist
    attempts = await _get_attempts(populated_session, "t1")
    assert [attempt.attempt_num for attempt in attempts] == [1, 2]


async def test_approval_decision_reject_projects_terminal_failure(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE tasks SET status = 'pending_user_action',"
            " pending_action_type = 'approval', current_attempt = 1,"
            " max_attempts = 1 WHERE id = 't1'"
        )
    )
    await populated_session.flush()

    projector = TaskStateProjector()
    event = ApprovalDecision(
        run_id="r1",
        event_type="approval_decision",
        task_id="t1",
        step_id="s1",
        approved=False,
        comment="still failing",
        decided_by="reviewer",
        new_status=TaskStatus.FAILED,
        current_attempt=1,
        attempt_snapshots=[
            {
                "id": "attempt-1",
                "attempt_num": 1,
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:30:00Z",
                "outcome": "failed",
            }
        ],
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.status == "failed"
    assert task.pending_action_type is None
    attempts = await _get_attempts(populated_session, "t1")
    assert len(attempts) == 1
    assert attempts[0].outcome == "failed"
    assert attempts[0].completed_at is not None


async def test_unknown_event_type_is_silently_skipped(populated_session: AsyncSession) -> None:
    """Events not in handled_events set must not raise from either projector."""
    run_projector = RunStateProjector()

    # HealthCheckEvent is in RunStateProjector.handled_events but has no run-table mutation
    # Use an event type that neither projector handles
    unknown_event = HealthCheckEvent(
        run_id="r1",
        phase="started",
        message="health check",
        timestamp=NOW,
    )
    # HealthCheckEvent is in RunStateProjector.handled_events (case _: pass) — no exception
    await run_projector.handle(unknown_event, populated_session)

    # ChecklistGateEvaluated is in RunStateProjector.handled_events but has no mutation
    gate_event = ChecklistGateEvaluated(
        run_id="r1",
        task_id="t1",
        passed=True,
        timestamp=NOW,
    )
    await run_projector.handle(gate_event, populated_session)

    # AutoVerifyCompleted is in RunStateProjector.handled_events (case _: pass)
    av_event = AutoVerifyCompleted(
        run_id="r1",
        task_id="t1",
        passed=True,
        timestamp=NOW,
    )
    await run_projector.handle(av_event, populated_session)

    # GradesEvaluated is in RunStateProjector.handled_events (case _: pass)
    grades_event = GradesEvaluated(
        run_id="r1",
        task_id="t1",
        passed=True,
        timestamp=NOW,
    )
    await run_projector.handle(grades_event, populated_session)

    # No assertion needed — test passes if no exception is raised


async def test_run_step_backward_updates_current_step_index(
    populated_session: AsyncSession,
) -> None:
    # First advance step index to 2
    await populated_session.execute(text("UPDATE runs SET current_step_index = 2 WHERE id = 'r1'"))
    await populated_session.flush()

    projector = RunStateProjector()
    event = RunStepBackward(
        run_id="r1",
        from_step_index=2,
        to_step_index=1,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    result = await populated_session.execute(
        text("SELECT current_step_index FROM runs WHERE id = 'r1'")
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_run_step_backward_applies_transition_tracker_delta(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE runs SET current_step_index = 2, transition_tracker = :tracker WHERE id = 'r1'"
        ),
        {"tracker": json.dumps({"counts": {"S-02->S-01": 1}})},
    )
    await populated_session.flush()

    projector = RunStateProjector()
    event = RunStepBackward(
        run_id="r1",
        from_step_index=2,
        to_step_index=1,
        timestamp=NOW,
        transition_tracker_delta={"S-02->S-01": 1},
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.current_step_index == 1
    assert run.transition_tracker == {"counts": {"S-02->S-01": 2}}


async def test_run_step_backward_without_delta_leaves_transition_tracker_unchanged(
    populated_session: AsyncSession,
) -> None:
    await populated_session.execute(
        text(
            "UPDATE runs SET current_step_index = 2, transition_tracker = :tracker WHERE id = 'r1'"
        ),
        {"tracker": json.dumps({"counts": {"S-02->S-01": 1}})},
    )
    await populated_session.flush()

    projector = RunStateProjector()
    event = RunStepBackward(
        run_id="r1",
        from_step_index=2,
        to_step_index=1,
        timestamp=NOW,
    )
    await projector.handle(event, populated_session)
    await populated_session.flush()

    run = await _get_run(populated_session, "r1")
    assert run.current_step_index == 1
    assert run.transition_tracker == {"counts": {"S-02->S-01": 1}}


async def test_run_created_inserts_run_model(session: AsyncSession) -> None:
    projector = RunStateProjector()
    event = RunCreated(
        run_id="new-run",
        event_type="run_created",
        timestamp=NOW,
        routine_id="routine-1",
        project_path="/path/to/project",
        repo_name="my-repo",
        status=RunStatus.DRAFT,
        config={"var": "val"},
    )
    await projector.handle(event, session)
    await session.flush()

    result = await session.execute(
        text(
            "SELECT id, repo_name, status, routine_id, transition_tracker"
            " FROM runs WHERE id = 'new-run'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "new-run"
    assert row[1] == "my-repo"
    assert row[2] == "draft"
    assert row[3] == "routine-1"
    assert row[4] is None


async def test_run_created_inserts_explicit_metadata_without_snapshot(
    session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = RunCreated(
        run_id="metadata-run",
        event_type="run_created",
        timestamp=NOW,
        routine_id="routine-1",
        project_path="/path/to/project",
        repo_name="metadata-repo",
        status=RunStatus.ACTIVE,
        created_at="2025-01-15T10:00:00+00:00",
        updated_at="2025-01-15T10:01:00+00:00",
        started_at="2025-01-15T10:02:00+00:00",
        completed_at="2025-01-15T10:03:00+00:00",
        agent_runner_started_at="2025-01-15T10:02:30+00:00",
        total_tokens_read=100,
        total_tokens_write=50,
        total_tokens_cache=10,
        total_duration_ms=1500,
        total_num_actions=5,
        token_usage_by_model=[{"model": "gpt-test", "input_tokens": 3}],
        transition_tracker={"counts": {"S-02->S-01": 2}},
    )
    await projector.handle(event, session)
    await session.flush()

    run = await _get_run(session, "metadata-run")
    assert run.created_at == datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    assert run.updated_at == datetime(2025, 1, 15, 10, 1, 0, tzinfo=timezone.utc)
    assert run.started_at == datetime(2025, 1, 15, 10, 2, 0, tzinfo=timezone.utc)
    assert run.completed_at == datetime(2025, 1, 15, 10, 3, 0, tzinfo=timezone.utc)
    assert run.runner_started_at == datetime(2025, 1, 15, 10, 2, 30, tzinfo=timezone.utc)
    assert run.total_tokens_read == 100
    assert run.total_tokens_write == 50
    assert run.total_tokens_cache == 10
    assert run.total_duration_ms == 1500
    assert run.total_num_actions == 5
    assert run.token_usage_by_model == [{"model": "gpt-test", "input_tokens": 3}]
    assert run.transition_tracker == {"counts": {"S-02->S-01": 2}}


async def test_run_created_inserts_parent_task_link_without_snapshot(
    session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = RunCreated(
        run_id="child-run",
        event_type="run_created",
        timestamp=NOW,
        routine_id="routine-child",
        project_path="/path/to/project",
        repo_name="child-repo",
        status=RunStatus.DRAFT,
        parent_run_id="parent-run",
        parent_task_id="parent-task",
    )
    await projector.handle(event, session)
    await session.flush()

    run = await _get_run(session, "child-run")
    assert run.parent_run_id == "parent-run"
    assert run.parent_task_id == "parent-task"


async def test_run_deleted_removes_run_model(session: AsyncSession) -> None:
    projector = RunStateProjector()
    await projector.handle(
        RunCreated(
            run_id="deleted-run",
            event_type="run_created",
            timestamp=NOW,
            routine_id="routine-1",
            repo_name="deleted-repo",
            status=RunStatus.DRAFT,
        ),
        session,
    )
    await projector.handle(
        StepCreated(
            run_id="deleted-run",
            timestamp=NOW,
            step_id="deleted-step",
            config_id="S-01",
            title="Deleted Step",
            order_index=0,
        ),
        session,
    )
    await session.flush()

    await projector.handle(
        RunDeleted(
            run_id="deleted-run",
            event_type="run_deleted",
            timestamp=NOW,
            deleted_by="user@example.com",
        ),
        session,
    )
    await session.flush()

    run_result = await session.execute(select(RunModel).where(RunModel.id == "deleted-run"))
    assert run_result.scalar_one_or_none() is None
    step_result = await session.execute(select(StepModel).where(StepModel.id == "deleted-step"))
    assert step_result.scalar_one_or_none() is None


async def test_step_created_inserts_step_model(session: AsyncSession) -> None:
    projector = RunStateProjector()
    await projector.handle(
        RunCreated(
            run_id="step-run",
            event_type="run_created",
            timestamp=NOW,
            routine_id="routine-1",
            repo_name="step-repo",
            status=RunStatus.DRAFT,
        ),
        session,
    )
    await projector.handle(
        StepCreated(
            run_id="step-run",
            timestamp=NOW,
            step_id="step-explicit",
            config_id="S-01",
            title="Explicit Step",
            order_index=2,
            condition={"if": "needed"},
            step_index=2,
        ),
        session,
    )
    await session.flush()

    step = await _get_step(session, "step-explicit")
    assert step.run_id == "step-run"
    assert step.config_id == "S-01"
    assert step.title == "Explicit Step"
    assert step.order_index == 2
    assert step.condition == {"if": "needed"}


def _snapshot_run_created_event() -> RunCreated:
    return RunCreated(
        run_id="snapshot-run",
        timestamp=NOW,
        routine_id="routine-1",
        repo_name="snapshot-repo",
        status=RunStatus.DRAFT,
        config={"slice": "S-01"},
        run_snapshot={
            "id": "snapshot-run",
            "repo_name": "snapshot-repo",
            "status": "draft",
            "pause_reason": None,
            "last_error": None,
            "routine_id": "routine-1",
            "routine_sha": "sha-1",
            "routine_source": "embedded",
            "routine_embedded": {"id": "routine-1", "steps": []},
            "routine_path": "routine.yaml",
            "routine_commit": "commit-1",
            "parent_run_id": "parent-run",
            "parent_task_id": "parent-task",
            "parent_slice_id": "slice-01",
            "oversight_state": {"child_count": 1},
            "agent_runner_type": "cli_subprocess",
            "agent_runner_config": {"model": "gpt-5.3-codex"},
            "verifier_model": "gpt-5.3-codex",
            "worktree_enabled": True,
            "worktree_path": "/tmp/worktree",
            "delete_worktree_on_completion": True,
            "source_branch": "main",
            "source_branch_sha": "abc123",
            "merge_strategy": "merge",
            "config": {"slice": "S-01"},
            "env_file_specs": [{"name": "OPENAI_API_KEY", "source": "host"}],
            "env_source_dir": "/tmp/env",
            "current_step_index": 1,
            "transition_tracker": {"counts": {"S-02->S-01": 2}},
            "created_at": "2025-01-15T10:30:00Z",
            "updated_at": "2025-01-15T10:30:00Z",
            "started_at": None,
            "completed_at": None,
            "agent_runner_started_at": None,
            "scheduled_resume_at": None,
            "steps": [
                {
                    "id": "step-snapshot",
                    "config_id": "S-01",
                    "title": "Snapshot Step",
                    "order_index": 7,
                    "completed": False,
                    "human_approval": None,
                    "condition": {"when": "true"},
                    "skipped": False,
                    "skip_reason": None,
                    "tasks": [
                        {
                            "id": "task-snapshot",
                            "config_id": "T-01",
                            "title": "Snapshot Task",
                            "order_index": 4,
                            "status": "building",
                            "complexity": "standard",
                            "checklist": [
                                {
                                    "req_id": "R1",
                                    "desc": "Requirement",
                                    "priority": "critical",
                                    "status": "done",
                                    "note": "complete",
                                }
                            ],
                            "current_attempt": 1,
                            "max_attempts": 4,
                            "has_verification": False,
                            "attempts": [
                                {
                                    "id": "attempt-snapshot",
                                    "attempt_num": 1,
                                    "started_at": "2025-01-15T10:30:00Z",
                                    "outcome": "paused",
                                    "paused_at": "2025-01-15T10:31:00Z",
                                    "metrics": {
                                        "tokens_read": 2,
                                        "tokens_write": 3,
                                        "tokens_cache": 4,
                                        "duration_ms": 5,
                                        "num_actions": 6,
                                    },
                                    "agent_runner_type": "cli_subprocess",
                                    "agent_model": "gpt-5.3-codex",
                                    "agent_settings": {"model": "gpt-5.3-codex"},
                                    "builder_prompt": "build it",
                                    "verifier_prompt": "verify it",
                                    "verifier_comment": "paused for clarification",
                                    "grade_snapshot": [{"req_id": "R1", "grade": "pass"}],
                                    "auto_verify_results": [{"cmd": "pytest", "passed": True}],
                                    "agent_output": "agent output",
                                    "action_log": {"actions": [{"kind": "edit"}]},
                                    "token_usage_by_model": [
                                        {
                                            "model": "gpt-5.3-codex",
                                            "input_tokens": 2,
                                            "output_tokens": 3,
                                        }
                                    ],
                                    "start_commit": "start-sha",
                                    "end_commit": "end-sha",
                                }
                            ],
                            "pending_action_type": "clarification",
                            "pending_clarification_id": "clarification-1",
                            "parent_task_id": None,
                            "fan_out_index": None,
                            "fan_out_input": None,
                            "fan_out_output": None,
                            "child_id": None,
                        },
                        {
                            "id": "task-snapshot-default",
                            "config_id": "T-02",
                            "title": "Snapshot Default Task",
                            "order_index": 5,
                            "status": "pending",
                            "complexity": "standard",
                            "checklist": [],
                            "current_attempt": 0,
                            "max_attempts": 3,
                            "attempts": [],
                            "pending_action_type": None,
                            "pending_clarification_id": None,
                            "parent_task_id": None,
                            "fan_out_index": None,
                            "fan_out_input": None,
                            "fan_out_output": None,
                            "child_id": None,
                        },
                    ],
                }
            ],
        },
    )


async def test_run_created_snapshot_projected_by_registry_into_initial_steps_and_tasks(
    session: AsyncSession,
) -> None:
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    event = _snapshot_run_created_event()
    await registry([], session, [event])
    await session.flush()

    run = await _get_run(session, "snapshot-run")
    assert run.repo_name == "snapshot-repo"
    assert run.runner_type == "cli_subprocess"
    assert run.runner_config == {"model": "gpt-5.3-codex"}
    assert run.verifier_model == "gpt-5.3-codex"
    assert run.source_branch == "main"
    assert run.source_branch_sha == "abc123"
    assert run.merge_strategy == "merge"
    assert run.worktree_path == "/tmp/worktree"
    assert run.delete_worktree_on_completion == 1
    assert run.routine_embedded == {"id": "routine-1", "steps": []}
    assert run.parent_run_id == "parent-run"
    assert run.parent_task_id == "parent-task"
    assert run.transition_tracker == {"counts": {"S-02->S-01": 2}}
    assert run.env_file_specs == [{"name": "OPENAI_API_KEY", "source": "host"}]
    assert run.current_step_index == 1

    step = await _get_step(session, "step-snapshot")
    assert step.run_id == "snapshot-run"
    assert step.config_id == "S-01"
    assert step.title == "Snapshot Step"
    assert step.order_index == 7
    assert step.condition == {"when": "true"}

    task = await _get_task_model(session, "task-snapshot")
    assert task.step_id == "step-snapshot"
    assert task.status == "building"
    assert task.order_index == 4
    assert task.current_attempt == 1
    assert task.max_attempts == 4
    assert task.has_verification == 0
    assert task.pending_action_type == "clarification"
    assert task.pending_clarification_id == "clarification-1"
    assert task.checklist[0]["status"] == "done"
    attempts = await _get_attempts(session, "task-snapshot")
    assert [attempt.id for attempt in attempts] == ["attempt-snapshot"]
    assert attempts[0].outcome == "paused"
    assert attempts[0].tokens_read == 2
    assert attempts[0].runner_type == "cli_subprocess"
    assert attempts[0].builder_prompt == "build it"
    assert attempts[0].verifier_prompt == "verify it"
    assert attempts[0].verifier_comment == "paused for clarification"
    assert attempts[0].grade_snapshot == [{"req_id": "R1", "grade": "pass"}]
    assert attempts[0].auto_verify_results == [{"cmd": "pytest", "passed": True}]
    assert attempts[0].agent_output == "agent output"
    assert attempts[0].action_log_json == {"actions": [{"kind": "edit"}]}
    assert attempts[0].token_usage_by_model == [
        {"model": "gpt-5.3-codex", "input_tokens": 2, "output_tokens": 3}
    ]
    assert attempts[0].start_commit == "start-sha"
    assert attempts[0].end_commit == "end-sha"

    default_task = await _get_task_model(session, "task-snapshot-default")
    assert default_task.has_verification == 1


async def test_registry_rebuild_expands_snapshot_even_with_later_task_for_same_run(
    session: AsyncSession,
) -> None:
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(
        [
            _snapshot_run_created_event(),
            TaskCreated(
                run_id="snapshot-run",
                timestamp=NOW,
                task_id="later-task",
                step_id="step-snapshot",
                step_index=7,
                config_id="T-03",
                title="Later Task",
                complexity="standard",
                order_index=8,
                checklist=[],
            ),
        ],
        session,
    )
    await session.flush()

    snapshot_task = await _get_task_model(session, "task-snapshot")
    assert snapshot_task.step_id == "step-snapshot"
    assert snapshot_task.current_attempt == 1
    attempts = await _get_attempts(session, "task-snapshot")
    assert [attempt.id for attempt in attempts] == ["attempt-snapshot"]
    assert attempts[0].builder_prompt == "build it"

    later_task = await _get_task_model(session, "later-task")
    assert later_task.step_id == "step-snapshot"
    assert later_task.title == "Later Task"


async def test_run_state_projector_does_not_project_snapshot_tasks_or_attempts(
    session: AsyncSession,
) -> None:
    projector = RunStateProjector()
    event = _snapshot_run_created_event()
    await projector.handle(event, session)
    await session.flush()

    run = await _get_run(session, "snapshot-run")
    assert run.repo_name == "snapshot-repo"
    assert run.runner_type == "cli_subprocess"
    assert run.runner_config == {"model": "gpt-5.3-codex"}
    assert run.verifier_model == "gpt-5.3-codex"
    assert run.source_branch == "main"
    assert run.source_branch_sha == "abc123"
    assert run.merge_strategy == "merge"
    assert run.worktree_path == "/tmp/worktree"
    assert run.delete_worktree_on_completion == 1
    assert run.routine_embedded == {"id": "routine-1", "steps": []}
    assert run.parent_run_id == "parent-run"
    assert run.parent_task_id == "parent-task"
    assert run.transition_tracker == {"counts": {"S-02->S-01": 2}}
    assert run.env_file_specs == [{"name": "OPENAI_API_KEY", "source": "host"}]
    assert run.current_step_index == 1

    step_count = await session.scalar(
        select(func.count()).select_from(StepModel).where(StepModel.run_id == "snapshot-run")
    )
    task_count = await session.scalar(
        select(func.count())
        .select_from(TaskModel)
        .where(TaskModel.id.in_(["task-snapshot", "task-snapshot-default"]))
    )
    attempt_count = await session.scalar(
        select(func.count()).select_from(AttemptModel).where(AttemptModel.id == "attempt-snapshot")
    )
    assert step_count == 0
    assert task_count == 0
    assert attempt_count == 0


async def test_task_created_inserts_task_model(session: AsyncSession) -> None:
    # Insert a run and step first so the task row can reference them (use ORM for Python defaults)
    run = RunModel(
        id="r-task",
        repo_name="repo",
        status="draft",
        runner_config={},
        config={},
        created_at=NOW,
        updated_at=NOW,
    )
    step = StepModel(id="s-task", run_id="r-task", config_id="S-01", order_index=0)
    session.add(run)
    session.add(step)
    await session.flush()

    projector = TaskStateProjector()
    event = TaskCreated(
        run_id="r-task",
        event_type="task_created",
        timestamp=NOW,
        task_id="t-new",
        step_id="s-task",
        step_index=0,
        config_id="T-01",
        title="My Task",
        complexity="standard",
        order_index=1,
        max_attempts=5,
        checklist=[{"id": "R1", "description": "req"}],
        parent_task_id=None,
        has_verification=False,
    )
    await projector.handle(event, session)
    await session.flush()

    result = await session.execute(
        text(
            "SELECT id, step_id, config_id, title, complexity, order_index, max_attempts, has_verification FROM tasks WHERE id = 't-new'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "t-new"
    assert row[1] == "s-task"
    assert row[2] == "T-01"
    assert row[3] == "My Task"
    assert row[4] == "standard"
    assert row[5] == 1
    assert row[6] == 5
    assert row[7] == 0


async def test_attempt_updated_can_skip_run_totals_projection(
    populated_session: AsyncSession,
) -> None:
    run = await _get_run(populated_session, "r1")
    run.total_tokens_read = 100
    run.total_tokens_write = 50
    run.total_tokens_cache = 10
    run.total_duration_ms = 1500
    run.total_num_actions = 5
    run.token_usage_by_model = [{"model": "gpt-run", "input_tokens": 30}]
    await populated_session.flush()

    task_projector = TaskStateProjector()
    run_projector = RunStateProjector()
    await task_projector.handle(
        TaskAttemptCreated(
            run_id="r1",
            task_id="t1",
            attempt_id="a1",
            attempt_num=1,
            timestamp=NOW,
        ),
        populated_session,
    )
    event = AttemptUpdated(
        run_id="r1",
        task_id="t1",
        attempt_id="a1",
        timestamp=NOW,
        output_lines=["line one"],
        tokens_read=10,
        tokens_write=4,
        tokens_cache=2,
        duration_ms=150,
        num_actions=3,
        token_usage_by_model=[{"model": "gpt-attempt", "input_tokens": 3}],
        apply_to_run_totals=False,
    )
    await task_projector.handle(event, populated_session)
    await run_projector.handle(event, populated_session)
    await populated_session.flush()

    attempts = await _get_attempts(populated_session, "t1")
    assert attempts[0].agent_output == "line one"
    assert attempts[0].tokens_read == 10
    assert attempts[0].tokens_write == 4
    assert attempts[0].tokens_cache == 2
    assert attempts[0].duration_ms == 150
    assert attempts[0].num_actions == 3
    assert attempts[0].token_usage_by_model == [{"model": "gpt-attempt", "input_tokens": 3}]
    unchanged_run = await _get_run(populated_session, "r1")
    assert unchanged_run.total_tokens_read == 100
    assert unchanged_run.total_tokens_write == 50
    assert unchanged_run.total_tokens_cache == 10
    assert unchanged_run.total_duration_ms == 1500
    assert unchanged_run.total_num_actions == 5
    assert unchanged_run.token_usage_by_model == [{"model": "gpt-run", "input_tokens": 30}]


async def test_task_attempt_created_projects_requested_task_status(
    populated_session: AsyncSession,
) -> None:
    projector = TaskStateProjector()
    await projector.handle(
        TaskAttemptCreated(
            run_id="r1",
            task_id="t1",
            attempt_id="a-default",
            attempt_num=1,
            timestamp=NOW,
        ),
        populated_session,
    )
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.current_attempt == 1
    assert task.status == "building"

    await projector.handle(
        TaskAttemptCreated(
            run_id="r1",
            task_id="t1",
            attempt_id="a-failed",
            attempt_num=2,
            timestamp=NOW,
            new_task_status=TaskStatus.FAILED,
        ),
        populated_session,
    )
    await populated_session.flush()

    task = await _get_task_model(populated_session, "t1")
    assert task.current_attempt == 2
    assert task.status == "failed"
