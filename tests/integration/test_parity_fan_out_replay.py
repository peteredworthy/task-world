"""Parity replay test: partial fan-out completion survives executor restart.

Simulates a scenario where a fan-out step has 3 child tasks, 2 complete
successfully before a 'restart' (state corrupted to DRAFT), and verifies
that replaying the event journal correctly reconstructs:
  - The first 2 children as COMPLETED
  - The third child as PENDING (not yet done)
  - The fan-out step as NOT completed (still in progress)
  - The run as ACTIVE

Uses a file-based DB (required for journal writing) but drives state changes
through WorkflowService directly — no HTTP overhead or signal drain cycles.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from orchestrator.config import ChecklistStatus, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import resolve_default_journal_path
from orchestrator.db import replay_journal_to_repository
from orchestrator.db import RunRepository
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# Fan-out routine: Step 1 setup, Step 2 has 3 parallel child tasks, Step 3 combine.
FAN_OUT_ROUTINE: dict[str, Any] = {
    "id": "replay-fan-out",
    "name": "Replay Fan-Out Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Setup",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Setup Task",
                    "task_context": "Prepare the work",
                    "requirements": [{"id": "R1", "desc": "Setup done"}],
                }
            ],
        },
        {
            "id": "S-02",
            "title": "Fan-Out Processing",
            "tasks": [
                {
                    "id": "T-02",
                    "title": "Child Task A",
                    "task_context": "Process item A",
                    "requirements": [{"id": "R1", "desc": "Item A processed"}],
                },
                {
                    "id": "T-03",
                    "title": "Child Task B",
                    "task_context": "Process item B",
                    "requirements": [{"id": "R1", "desc": "Item B processed"}],
                },
                {
                    "id": "T-04",
                    "title": "Child Task C",
                    "task_context": "Process item C",
                    "requirements": [{"id": "R1", "desc": "Item C processed"}],
                },
            ],
        },
        {
            "id": "S-03",
            "title": "Combine",
            "tasks": [
                {
                    "id": "T-05",
                    "title": "Combine Results",
                    "task_context": "Combine all processed items",
                    "requirements": [{"id": "R1", "desc": "Combined"}],
                }
            ],
        },
    ],
}


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[async_sessionmaker[AsyncSession], Path], None]:
    """File-based DB so the event journal is written to disk for replay tests."""
    db_path = tmp_path / "orchestrator.db"
    engine = create_engine(str(db_path))
    await init_db(engine)
    factory = create_session_factory(engine)
    yield factory, db_path
    await engine.dispose()


def _now() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _checklist(req_id: str = "R1") -> list[ChecklistItem]:
    return [ChecklistItem(req_id=req_id, desc="Done", priority=Priority.CRITICAL)]


def _make_run(run_id: str = "run-replay") -> Run:
    now = _now()
    return Run(
        id=run_id,
        repo_name="replay-fan-out-repo",
        status=RunStatus.DRAFT,
        routine_id="replay-fan-out",
        routine_source=RoutineSource.EMBEDDED,
        routine_embedded=FAN_OUT_ROUTINE,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-setup",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=_checklist(),
                        max_attempts=3,
                    )
                ],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                tasks=[
                    TaskState(
                        id="task-child-a",
                        config_id="T-02",
                        status=TaskStatus.PENDING,
                        checklist=_checklist(),
                        max_attempts=3,
                    ),
                    TaskState(
                        id="task-child-b",
                        config_id="T-03",
                        status=TaskStatus.PENDING,
                        checklist=_checklist(),
                        max_attempts=3,
                    ),
                    TaskState(
                        id="task-child-c",
                        config_id="T-04",
                        status=TaskStatus.PENDING,
                        checklist=_checklist(),
                        max_attempts=3,
                    ),
                ],
            ),
            StepState(
                id="step-3",
                config_id="S-03",
                tasks=[
                    TaskState(
                        id="task-combine",
                        config_id="T-05",
                        status=TaskStatus.PENDING,
                        checklist=_checklist(),
                        max_attempts=3,
                    )
                ],
            ),
        ],
        created_at=now,
        updated_at=now,
    )


async def _complete_task(service: WorkflowService, run_id: str, task_id: str) -> None:
    """Drive a task through start → submit → grade → complete-verification via service."""
    await service.start_task(run_id, task_id)
    await service.update_checklist_item(run_id, task_id, "R1", ChecklistStatus.DONE)
    await service.apply_submission(run_id, task_id)
    await service.set_grade(run_id, task_id, "R1", "A", "done")
    await service.apply_verification(run_id, task_id)
    task = await service.get_task(run_id, task_id)
    assert task.status == TaskStatus.COMPLETED


def _corrupt_run_to_draft(run: Run) -> None:
    """Reset run and all tasks to initial state to simulate restoring from stale backup."""
    run.status = RunStatus.DRAFT
    run.started_at = None
    run.current_step_index = 0
    for step in run.steps:
        step.completed = False
        for task in step.tasks:
            task.status = TaskStatus.PENDING
            task.current_attempt = 0
            task.attempts = []


async def test_partial_fan_out_replay_reconstructs_correct_state(
    file_db: tuple[async_sessionmaker[AsyncSession], Path],
) -> None:
    """After restart, completed fan-out children stay COMPLETED; pending stay PENDING.

    Scenario:
    1. Create run with 3 fan-out children in step 2
    2. Complete setup (step 1) + child A and child B (2 of 3)
    3. Simulate executor restart: corrupt state to DRAFT/PENDING
    4. Replay events from journal
    5. Assert: run=ACTIVE, step 1=completed, child A=completed, child B=completed,
       child C=pending, fan-out step NOT completed
    """
    factory, db_path = file_db
    run_id = "run-replay-partial"

    async with factory() as session:
        service = WorkflowService(session)
        run = _make_run(run_id)
        await service.create_run(run)
        await service.apply_start_run(run_id)

        await _complete_task(service, run_id, "task-setup")

        loaded = await service.get_run(run_id)
        assert loaded.current_step_index == 1

        # Complete child A and child B (but NOT child C — partial completion)
        await _complete_task(service, run_id, "task-child-a")
        await _complete_task(service, run_id, "task-child-b")

        # Verify partial state
        loaded = await service.get_run(run_id)
        assert loaded.steps[1].completed is False, "Fan-out step should not be completed yet"
        assert loaded.current_step_index == 1
        child_c = await service.get_task(run_id, "task-child-c")
        assert child_c.status == TaskStatus.PENDING

    # Verify journal was written
    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None and journal_path.exists(), "Journal file must exist"

    # --- Simulate executor restart: corrupt all state to DRAFT/PENDING ---
    async with factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        _corrupt_run_to_draft(stale_run)
        await repo.save(stale_run)
        await session.commit()

    # Verify state is now corrupted
    async with factory() as session:
        repo = RunRepository(session)
        corrupted = await repo.get(run_id)
        assert corrupted.status == RunStatus.DRAFT

    # --- Replay journal to reconstruct state ---
    async with factory() as session:
        repo = RunRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
        )
        await session.commit()

    assert summary.replayed_events > 0, "Replay should have processed events"
    assert summary.updated_runs == 1, "Run should have been updated by replay"

    # --- Assert correct reconstruction ---
    async with factory() as session:
        repo = RunRepository(session)
        restored = await repo.get(run_id)

    assert restored.status == RunStatus.ACTIVE, f"Run should be active, got {restored.status}"
    assert restored.steps[0].completed is True, "Setup step should be completed"
    assert restored.steps[1].completed is False, (
        "Fan-out step should NOT be completed (child C still pending)"
    )
    assert restored.current_step_index == 1, (
        f"Should still be on fan-out step, got index {restored.current_step_index}"
    )

    child_a = next(t for t in restored.steps[1].tasks if t.id == "task-child-a")
    child_b = next(t for t in restored.steps[1].tasks if t.id == "task-child-b")
    child_c = next(t for t in restored.steps[1].tasks if t.id == "task-child-c")

    assert child_a.status == TaskStatus.COMPLETED, (
        f"Child A should be completed, got {child_a.status}"
    )
    assert child_b.status == TaskStatus.COMPLETED, (
        f"Child B should be completed, got {child_b.status}"
    )
    assert child_c.status == TaskStatus.PENDING, (
        f"Child C should remain pending, got {child_c.status}"
    )


async def test_all_fan_out_children_completed_replay(
    file_db: tuple[async_sessionmaker[AsyncSession], Path],
) -> None:
    """Replay after all children complete advances step index correctly."""
    factory, db_path = file_db
    run_id = "run-replay-all"

    async with factory() as session:
        service = WorkflowService(session)
        run = _make_run(run_id)
        await service.create_run(run)
        await service.apply_start_run(run_id)

        await _complete_task(service, run_id, "task-setup")
        await _complete_task(service, run_id, "task-child-a")
        await _complete_task(service, run_id, "task-child-b")
        await _complete_task(service, run_id, "task-child-c")

        loaded = await service.get_run(run_id)
        assert loaded.steps[1].completed is True
        assert loaded.current_step_index == 2

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    # Corrupt state
    async with factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        _corrupt_run_to_draft(stale_run)
        await repo.save(stale_run)
        await session.commit()

    # Replay
    async with factory() as session:
        repo = RunRepository(session)
        await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
        )
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        restored = await repo.get(run_id)

    assert restored.status == RunStatus.ACTIVE
    assert restored.steps[0].completed is True
    assert restored.steps[1].completed is True
    assert restored.current_step_index == 2

    for child_id in ("task-child-a", "task-child-b", "task-child-c"):
        child = next(t for step in restored.steps for t in step.tasks if t.id == child_id)
        assert child.status == TaskStatus.COMPLETED, (
            f"Child {child_id} should be completed, got {child.status}"
        )
