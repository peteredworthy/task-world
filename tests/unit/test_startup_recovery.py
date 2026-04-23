"""Tests for startup recovery helpers and continue semantics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orchestrator.api.app import _is_startup_recoverable_pause_reason
from orchestrator.config import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import (
    EventStore,
    RunRepository,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state import Attempt
from orchestrator.workflow import LocalAutoVerifyRunner, PersistentEventEmitter
from orchestrator.workflow.service import WorkflowService


def test_startup_recovery_includes_executor_not_started() -> None:
    assert _is_startup_recoverable_pause_reason("server_shutdown") is True
    assert _is_startup_recoverable_pause_reason("agent_not_running_on_startup") is True
    assert _is_startup_recoverable_pause_reason("executor_not_started") is True
    assert _is_startup_recoverable_pause_reason("manual") is False
    assert _is_startup_recoverable_pause_reason(None) is False


@pytest.mark.asyncio
async def test_apply_resume_run_continue_preserves_current_phase_state() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    routine = RoutineConfig(
        id="resume-continue-routine",
        name="Resume Continue Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do the work",
                        requirements=[RequirementConfig(id="R1", desc="Complete the work")],
                    )
                ],
            )
        ],
    )

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=routine,
            repo_name="resume-continue-repo",
            source_branch="main",
        )
        run.routine_embedded = routine.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CODEX_SERVER
        run.agent_config = {"model": "gpt-5.4-mini"}
        run.status = RunStatus.PAUSED
        run.pause_reason = "executor_not_started"

        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.checklist[0].status = ChecklistStatus.DONE
        task.checklist[0].note = "partial progress retained"
        task.checklist[0].priority = Priority.CRITICAL
        task.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
        attempt = task.attempts[0]
        attempt.outcome = "paused"
        attempt.paused_at = datetime.now(timezone.utc)

        await repo.save(run)
        await session.commit()

        resumed = await service.apply_resume_run(run.id, resume_strategy="continue")
        await session.commit()

        resumed_task = resumed.steps[0].tasks[0]
        resumed_attempt = resumed_task.attempts[-1]

        assert resumed.status == RunStatus.ACTIVE
        assert resumed.pause_reason is None
        assert resumed_task.status == TaskStatus.BUILDING
        assert resumed_task.checklist[0].status == ChecklistStatus.DONE
        assert resumed_task.checklist[0].note == "partial progress retained"
        assert resumed_attempt.outcome is None
        assert resumed_attempt.paused_at is None

    await engine.dispose()
