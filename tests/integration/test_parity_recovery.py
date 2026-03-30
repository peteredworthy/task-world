"""Parity test: executor/service restart recovery.

Captures current orchestrator behaviour as a regression baseline.
Covers:
  - Start run, advance to first task (complete it)
  - Simulate service restart by creating a new WorkflowService from the
    same persisted database session factory (same DB, new in-memory state)
  - Assert run state is loaded correctly from DB
  - Assert completed task is still completed (no re-execution)
  - Assert no duplicate attempt created for the completed task
  - Assert run can continue from the correct step/task after restart
"""

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from orchestrator.config import ChecklistStatus, RunStatus, TaskStatus
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import Base
from orchestrator.db import create_session_factory
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"
_TMP_DIR = Path(__file__).parent.parent.parent / "tmp"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """File-based SQLite so a second session can read the same persisted state."""
    _TMP_DIR.mkdir(exist_ok=True)
    db_path = _TMP_DIR / f"test_recovery_{uuid.uuid4().hex}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()
    db_path.unlink(missing_ok=True)
    Path(str(db_path) + "-wal").unlink(missing_ok=True)
    Path(str(db_path) + "-shm").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_two_step_routine() -> RoutineConfig:
    req = RequirementConfig(id="R1", desc="Complete the work")
    return RoutineConfig(
        id="parity-recovery",
        name="Parity Recovery Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step One",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task One",
                        task_context="First task",
                        requirements=[req],
                    ),
                ],
            ),
            StepConfig(
                id="S-02",
                title="Step Two",
                tasks=[
                    TaskConfig(
                        id="T-02",
                        title="Task Two",
                        task_context="Second task",
                        requirements=[req],
                    ),
                ],
            ),
        ],
    )


def _make_run(routine: RoutineConfig, run_id: str = "run-recovery") -> Any:
    return create_run_from_routine(
        routine,
        repo_name="parity-recovery-repo",
        source_branch="main",
        id_generator=iter([run_id, "step-1", "task-1", "step-2", "task-2"]).__next__,
    )


async def _complete_task_via_service(service: WorkflowService, run_id: str, task_id: str) -> None:
    """Drive a task through start → mark done → submit → grade A → complete."""
    await service.start_task(run_id, task_id)
    await service.update_checklist_item(run_id, task_id, "R1", ChecklistStatus.DONE)
    await service.submit_for_verification(run_id, task_id)
    await service.set_grade(run_id, task_id, "R1", "A", "Good work")
    await service.complete_verification(run_id, task_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_recovery_state_persists_across_service_restart(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Completed task remains completed after service is re-instantiated from DB."""
    routine = _make_two_step_routine()
    run = _make_run(routine)
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id

    # --- Phase 1: service instance 1 ---
    async with session_factory() as session1:
        svc1 = WorkflowService(session1)
        await svc1.create_run(run)
        await svc1.apply_start_run(run_id)
        await _complete_task_via_service(svc1, run_id, task1_id)

    # --- Phase 2: simulate restart — new service from same DB ---
    async with session_factory() as session2:
        svc2 = WorkflowService(session2)

        # Load the run fresh from DB
        loaded = await svc2._repo.get(run_id)

        # Completed task must still be completed
        task1 = loaded.steps[0].tasks[0]
        assert task1.status == TaskStatus.COMPLETED, (
            "Task 1 should remain completed after service restart"
        )
        # Only one attempt — no re-execution
        assert len(task1.attempts) == 1, "No duplicate attempt should be created after restart"
        assert task1.attempts[0].outcome == "passed"

        # Step 1 should be marked completed
        assert loaded.steps[0].completed is True

        # Run should be on step index 1 (task 2 not started yet)
        assert loaded.current_step_index == 1
        assert loaded.status == RunStatus.ACTIVE


async def test_recovery_can_continue_from_correct_step(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """After restart, the second task can be started and completed normally."""
    routine = _make_two_step_routine()
    run = _make_run(routine, run_id="run-recovery-continue")
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id
    task2_id = run.steps[1].tasks[0].id

    # Phase 1: complete task 1 on service instance 1
    async with session_factory() as session1:
        svc1 = WorkflowService(session1)
        await svc1.create_run(run)
        await svc1.apply_start_run(run_id)
        await _complete_task_via_service(svc1, run_id, task1_id)

    # Phase 2: restart — continue with task 2 on service instance 2
    async with session_factory() as session2:
        svc2 = WorkflowService(session2)
        loaded = await svc2._repo.get(run_id)

        # Task 1 still completed, task 2 pending
        assert loaded.steps[0].tasks[0].status == TaskStatus.COMPLETED
        assert loaded.steps[1].tasks[0].status == TaskStatus.PENDING

        # Continue: start and complete task 2
        await _complete_task_via_service(svc2, run_id, task2_id)

        # Run should now be completed
        finished = await svc2._repo.get(run_id)
        assert finished.status == RunStatus.COMPLETED
        assert finished.steps[1].tasks[0].status == TaskStatus.COMPLETED
        assert len(finished.steps[1].tasks[0].attempts) == 1, (
            "Task 2 should have exactly one attempt"
        )


async def test_recovery_task1_not_restarted_after_restart(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reloading from DB does not create duplicate attempts for completed tasks."""
    routine = _make_two_step_routine()
    run = _make_run(routine, run_id="run-recovery-no-dup")
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id

    # Complete task 1
    async with session_factory() as session1:
        svc1 = WorkflowService(session1)
        await svc1.create_run(run)
        await svc1.apply_start_run(run_id)
        await _complete_task_via_service(svc1, run_id, task1_id)

    # After restart, verify task 1 has exactly one attempt
    async with session_factory() as session2:
        svc2 = WorkflowService(session2)
        loaded = await svc2._repo.get(run_id)
        task1 = loaded.steps[0].tasks[0]
        assert task1.status == TaskStatus.COMPLETED
        # Attempt count must not change on reload
        assert len(task1.attempts) == 1, "Reloading from DB must not create duplicate attempts"
