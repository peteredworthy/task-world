"""Parity test: fan-out step (multiple parallel child tasks).

Captures current orchestrator behaviour as a regression baseline.
Covers: a step containing multiple tasks (fan-out style); each child task
is completed in order; the parent step is marked completed only after all
children finish; the run then advances past the fan-out step.

Note: This test uses an embedded routine with multiple tasks in a single
step (the simplest form of "fan-out" that the orchestrator supports natively
via the API, without requiring filesystem glob expansion).

Tests operate at the WorkflowService level — no HTTP overhead or signal drain
cycles, since the assertions are purely about state machine properties.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import ChecklistStatus, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService

# Routine: Step 1 has a single setup task; Step 2 has 3 child tasks (fan-out).
# Step 3 is the combine/finalise step after the fan-out.
FAN_OUT_ROUTINE: dict[str, Any] = {
    "id": "parity-fan-out",
    "name": "Parity Fan-Out Routine",
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
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _now() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _checklist(req_id: str = "R1") -> list[ChecklistItem]:
    return [ChecklistItem(req_id=req_id, desc="Done", priority=Priority.CRITICAL)]


def _make_run(run_id: str = "run-fanout") -> Run:
    now = _now()
    return Run(
        id=run_id,
        repo_name="parity-fan-out-repo",
        status=RunStatus.DRAFT,
        routine_id="parity-fan-out",
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


async def test_fan_out_step_structure(session: AsyncSession) -> None:
    """Fan-out step contains exactly 3 child tasks at creation."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)

    loaded = await service.get_run(run.id)
    assert len(loaded.steps) == 3
    assert len(loaded.steps[1].tasks) == 3, "Fan-out step should have 3 child tasks"
    assert loaded.steps[1].completed is False


async def test_fan_out_step_incomplete_while_children_pending(
    session: AsyncSession,
) -> None:
    """Fan-out step not completed while child tasks are still pending."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run(run.id)

    await _complete_task(service, run.id, "task-setup")

    loaded = await service.get_run(run.id)
    assert loaded.current_step_index == 1, "Should have advanced to the fan-out step"

    # Complete only the first child
    await _complete_task(service, run.id, "task-child-a")

    loaded = await service.get_run(run.id)
    assert loaded.current_step_index == 1, (
        "Should still be on fan-out step while child tasks are incomplete"
    )
    assert loaded.steps[1].completed is False

    child_b = await service.get_task(run.id, "task-child-b")
    assert child_b.status == TaskStatus.PENDING


async def test_fan_out_step_completes_when_all_children_done(
    session: AsyncSession,
) -> None:
    """Fan-out step marked completed only after all child tasks finish."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run(run.id)

    await _complete_task(service, run.id, "task-setup")

    loaded = await service.get_run(run.id)
    assert loaded.current_step_index == 1

    await _complete_task(service, run.id, "task-child-a")
    await _complete_task(service, run.id, "task-child-b")
    await _complete_task(service, run.id, "task-child-c")

    loaded = await service.get_run(run.id)
    assert loaded.steps[1].completed is True, (
        "Fan-out step should be completed when all children finish"
    )
    assert loaded.current_step_index == 2, "Run should advance past the fan-out step"
    assert loaded.status == RunStatus.ACTIVE, "Run still active (combine step not done)"


async def test_fan_out_run_completes_after_all_steps(
    session: AsyncSession,
) -> None:
    """Full workflow: setup → fan-out (3 children) → combine → run completed."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run(run.id)

    await _complete_task(service, run.id, "task-setup")
    await _complete_task(service, run.id, "task-child-a")
    await _complete_task(service, run.id, "task-child-b")
    await _complete_task(service, run.id, "task-child-c")
    await _complete_task(service, run.id, "task-combine")

    loaded = await service.get_run(run.id)
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.completed_at is not None
    for step in loaded.steps:
        assert step.completed is True

    for child_id in ("task-child-a", "task-child-b", "task-child-c"):
        task = await service.get_task(run.id, child_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.current_attempt == 1
