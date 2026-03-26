"""Integration tests for full persistence with real restart simulation.

Tests use a temporary on-disk SQLite database with separate engine/session
instances to prove state survives across completely independent connections.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.config import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
    load_routine_from_path,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.db import RunRepository
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_persistence.db"


def _make_run() -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
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
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Complete the task",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def test_state_survives_restart(db_path: Path) -> None:
    """Create run and start it in one session, verify in a completely new session."""
    # --- Session 1: Create and start run ---
    engine1 = create_engine(str(db_path))
    await init_db(engine1)
    factory1 = create_session_factory(engine1)

    async with factory1() as session1:
        service1 = WorkflowService(session1)
        run = _make_run()
        await service1.create_run(run)
        await service1.start_run("run-1")
        await service1.start_task("run-1", "task-1")

    await engine1.dispose()

    # --- Session 2: Completely new engine, verify state ---
    engine2 = create_engine(str(db_path))
    factory2 = create_session_factory(engine2)

    async with factory2() as session2:
        service2 = WorkflowService(session2)
        loaded = await service2.get_run("run-1")

        assert loaded.status == RunStatus.ACTIVE
        assert loaded.started_at is not None
        assert loaded.steps[0].tasks[0].status == TaskStatus.BUILDING
        assert loaded.steps[0].tasks[0].current_attempt == 1

    await engine2.dispose()


async def test_full_lifecycle_survives_restart(db_path: Path) -> None:
    """Full lifecycle in session 1, verify final state in session 2."""
    # --- Session 1: Full lifecycle ---
    engine1 = create_engine(str(db_path))
    await init_db(engine1)
    factory1 = create_session_factory(engine1)

    async with factory1() as session1:
        service1 = WorkflowService(session1)
        run = _make_run()
        await service1.create_run(run)
        await service1.start_run("run-1")
        await service1.start_task("run-1", "task-1")
        await service1.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        await service1.submit_for_verification("run-1", "task-1")
        await service1.set_grade("run-1", "task-1", "R1", "A", "Well done")
        result = await service1.complete_verification("run-1", "task-1")
        assert result.new_status == TaskStatus.COMPLETED

    await engine1.dispose()

    # --- Session 2: Verify from scratch ---
    engine2 = create_engine(str(db_path))
    factory2 = create_session_factory(engine2)

    async with factory2() as session2:
        service2 = WorkflowService(session2)
        loaded = await service2.get_run("run-1")

        assert loaded.status == RunStatus.COMPLETED
        assert loaded.completed_at is not None
        assert loaded.steps[0].completed is True
        task = loaded.steps[0].tasks[0]
        assert task.status == TaskStatus.COMPLETED
        assert task.current_attempt == 1
        assert len(task.attempts) == 1
        assert task.attempts[0].outcome == "passed"
        assert task.checklist[0].grade == "A"
        assert task.checklist[0].grade_reason == "Well done"

    await engine2.dispose()


async def test_events_survive_restart(db_path: Path) -> None:
    """Events persist and can be queried from a new session."""
    # --- Session 1: Generate events ---
    engine1 = create_engine(str(db_path))
    await init_db(engine1)
    factory1 = create_session_factory(engine1)

    async with factory1() as session1:
        service1 = WorkflowService(session1)
        run = _make_run()
        await service1.create_run(run)
        await service1.start_run("run-1")
        await service1.start_task("run-1", "task-1")

    await engine1.dispose()

    # --- Session 2: Verify events ---
    engine2 = create_engine(str(db_path))
    factory2 = create_session_factory(engine2)

    async with factory2() as session2:
        store = EventStore(session2)
        events = await store.get_events_for_run("run-1")
        assert len(events) >= 2
        event_types = [e["type"] for e in events]
        assert "run_status_changed" in event_types
        assert "task_status_changed" in event_types

    await engine2.dispose()


async def test_routine_fixture_roundtrip(db_path: Path) -> None:
    """Runs created from YAML fixtures survive restart."""
    routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
    run = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        config={"feature_name": "auth"},
        routine_source=RoutineSource.LOCAL,
        routine_sha="deadbeef",
    )

    # --- Session 1: Save ---
    engine1 = create_engine(str(db_path))
    await init_db(engine1)
    factory1 = create_session_factory(engine1)

    async with factory1() as session1:
        repo1 = RunRepository(session1)
        await repo1.save(run)
        await session1.commit()

    await engine1.dispose()

    # --- Session 2: Load ---
    engine2 = create_engine(str(db_path))
    factory2 = create_session_factory(engine2)

    async with factory2() as session2:
        repo2 = RunRepository(session2)
        loaded = await repo2.get(run.id)

        assert loaded.repo_name == "proj-1"
        assert loaded.routine_id == "complete-routine"
        assert loaded.routine_sha == "deadbeef"
        assert loaded.config == {"feature_name": "auth", "branch": "main"}
        assert len(loaded.steps) == 2
        assert loaded.steps[0].config_id == "S-01"
        assert loaded.steps[1].config_id == "S-02"

    await engine2.dispose()
