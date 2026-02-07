"""Integration tests for RunRepository."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.repositories import RunRepository
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.errors import RunNotFoundError
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import (
    Attempt,
    AttemptMetrics,
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> RunRepository:
    return RunRepository(session)


def _make_simple_run(run_id: str = "run-1") -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id=run_id,
        project_id="proj-1",
        status=RunStatus.DRAFT,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        config={"feature": "auth"},
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


async def test_save_and_get_simple_run(repo: RunRepository) -> None:
    run = _make_simple_run()
    await repo.save(run)
    loaded = await repo.get("run-1")

    assert loaded.id == "run-1"
    assert loaded.project_id == "proj-1"
    assert loaded.status == RunStatus.DRAFT
    assert loaded.routine_id == "simple-routine"
    assert loaded.routine_source == RoutineSource.LOCAL
    assert loaded.config == {"feature": "auth"}
    assert len(loaded.steps) == 1
    assert loaded.steps[0].config_id == "S-01"
    assert len(loaded.steps[0].tasks) == 1
    assert loaded.steps[0].tasks[0].config_id == "T-01"
    assert len(loaded.steps[0].tasks[0].checklist) == 1
    assert loaded.steps[0].tasks[0].checklist[0].req_id == "R1"
    assert loaded.steps[0].tasks[0].checklist[0].priority == Priority.CRITICAL
    assert loaded.steps[0].tasks[0].checklist[0].status == ChecklistStatus.OPEN


async def test_save_and_get_complex_run(repo: RunRepository) -> None:
    """Test a run with attempts, metrics, and grades."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = Run(
        id="run-complex",
        project_id="proj-1",
        status=RunStatus.ACTIVE,
        routine_id="complete-routine",
        routine_source=RoutineSource.LOCAL,
        routine_sha="abc123",
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.COMPLETED,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Do it",
                                priority=Priority.CRITICAL,
                                status=ChecklistStatus.DONE,
                                grade="A",
                                grade_reason="Well done",
                            ),
                            ChecklistItem(
                                req_id="R2",
                                desc="Check it",
                                priority=Priority.EXPECTED,
                                status=ChecklistStatus.DONE,
                                note="Verified",
                            ),
                        ],
                        attempts=[
                            Attempt(
                                id="att-1",
                                attempt_num=1,
                                started_at=now,
                                completed_at=now,
                                outcome="revision_needed",
                                metrics=AttemptMetrics(
                                    tokens_read=500,
                                    tokens_write=200,
                                    duration_ms=10000,
                                ),
                            ),
                            Attempt(
                                id="att-2",
                                attempt_num=2,
                                started_at=now,
                                completed_at=now,
                                outcome="passed",
                                metrics=AttemptMetrics(
                                    tokens_read=300,
                                    tokens_write=100,
                                    duration_ms=5000,
                                ),
                            ),
                        ],
                        current_attempt=2,
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
        started_at=now,
        total_tokens_read=800,
        total_tokens_write=300,
        total_duration_ms=15000,
    )

    await repo.save(run)
    loaded = await repo.get("run-complex")

    assert loaded.status == RunStatus.ACTIVE
    assert loaded.routine_sha == "abc123"
    assert loaded.total_tokens_read == 800

    task = loaded.steps[0].tasks[0]
    assert task.status == TaskStatus.COMPLETED
    assert task.current_attempt == 2
    assert len(task.checklist) == 2
    assert task.checklist[0].grade == "A"
    assert task.checklist[0].grade_reason == "Well done"
    assert task.checklist[1].note == "Verified"

    assert len(task.attempts) == 2
    assert task.attempts[0].outcome == "revision_needed"
    assert task.attempts[0].metrics.tokens_read == 500
    assert task.attempts[1].outcome == "passed"
    assert task.attempts[1].metrics.duration_ms == 5000


async def test_update_and_resave(repo: RunRepository) -> None:
    run = _make_simple_run()
    await repo.save(run)

    loaded = await repo.get("run-1")
    loaded.status = RunStatus.ACTIVE
    loaded.started_at = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
    loaded.steps[0].tasks[0].status = TaskStatus.BUILDING
    loaded.steps[0].tasks[0].checklist[0].status = ChecklistStatus.DONE

    await repo.save(loaded)
    reloaded = await repo.get("run-1")

    assert reloaded.status == RunStatus.ACTIVE
    assert reloaded.started_at is not None
    assert reloaded.steps[0].tasks[0].status == TaskStatus.BUILDING
    assert reloaded.steps[0].tasks[0].checklist[0].status == ChecklistStatus.DONE


async def test_list_all(repo: RunRepository) -> None:
    await repo.save(_make_simple_run("run-1"))
    await repo.save(_make_simple_run("run-2"))

    runs = await repo.list_all()
    assert len(runs) == 2
    ids = {r.id for r in runs}
    assert ids == {"run-1", "run-2"}


async def test_list_by_project(repo: RunRepository) -> None:
    run1 = _make_simple_run("run-1")
    run2 = _make_simple_run("run-2")
    run2.project_id = "proj-2"
    await repo.save(run1)
    await repo.save(run2)

    proj1_runs = await repo.list_by_project("proj-1")
    assert len(proj1_runs) == 1
    assert proj1_runs[0].id == "run-1"


async def test_list_by_status(repo: RunRepository) -> None:
    run1 = _make_simple_run("run-1")
    run2 = _make_simple_run("run-2")
    run2.status = RunStatus.ACTIVE
    await repo.save(run1)
    await repo.save(run2)

    draft_runs = await repo.list_by_status(RunStatus.DRAFT)
    assert len(draft_runs) == 1
    assert draft_runs[0].id == "run-1"


async def test_delete(repo: RunRepository) -> None:
    await repo.save(_make_simple_run())
    await repo.delete("run-1")

    with pytest.raises(RunNotFoundError):
        await repo.get("run-1")


async def test_get_nonexistent_raises(repo: RunRepository) -> None:
    with pytest.raises(RunNotFoundError):
        await repo.get("nonexistent")


async def test_delete_nonexistent_raises(repo: RunRepository) -> None:
    with pytest.raises(RunNotFoundError):
        await repo.delete("nonexistent")


async def test_factory_created_run_roundtrips(repo: RunRepository) -> None:
    """Runs created via create_run_from_routine should survive save/load."""
    routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
    run = create_run_from_routine(
        routine=routine,
        project_id="proj-1",
        config={"feature_name": "auth"},
        routine_source=RoutineSource.LOCAL,
        routine_sha="deadbeef",
    )

    await repo.save(run)
    loaded = await repo.get(run.id)

    assert loaded.project_id == "proj-1"
    assert loaded.routine_id == "complete-routine"
    assert loaded.routine_sha == "deadbeef"
    assert loaded.config == {"feature_name": "auth", "branch": "main"}
    assert len(loaded.steps) == 2
    assert loaded.steps[0].config_id == "S-01"
    assert loaded.steps[1].config_id == "S-02"
    assert len(loaded.steps[0].tasks) == 1  # T-01
    assert len(loaded.steps[1].tasks) == 2  # T-02, T-03
    assert loaded.steps[0].tasks[0].max_attempts == 3
    assert loaded.steps[1].tasks[0].max_attempts == 2  # T-02 custom retry


async def test_list_empty(repo: RunRepository) -> None:
    runs = await repo.list_all()
    assert runs == []
