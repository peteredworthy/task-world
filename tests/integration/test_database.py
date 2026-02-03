"""Integration tests for database setup and ORM models."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.models import AttemptModel, EventModel, RunModel, StepModel, TaskModel


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run(run_id: str = "run-1", project_id: str = "proj-1") -> RunModel:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return RunModel(
        id=run_id,
        project_id=project_id,
        status="draft",
        agent_config={},
        config={},
        created_at=now,
        updated_at=now,
    )


async def test_engine_creation() -> None:
    engine = create_engine(":memory:")
    assert engine is not None
    await engine.dispose()


async def test_init_db_creates_tables() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn))
    assert "runs" in tables
    assert "steps" in tables
    assert "tasks" in tables
    assert "attempts" in tables
    assert "events" in tables
    await engine.dispose()


async def test_crud_run(session: AsyncSession) -> None:
    run = _make_run()
    session.add(run)
    await session.flush()

    result = await session.execute(select(RunModel).where(RunModel.id == "run-1"))
    loaded = result.scalar_one()
    assert loaded.project_id == "proj-1"
    assert loaded.status == "draft"


async def test_crud_with_steps_and_tasks(session: AsyncSession) -> None:
    run = _make_run()
    step = StepModel(id="step-1", run_id="run-1", config_id="S-01", order_index=0)
    task = TaskModel(
        id="task-1",
        step_id="step-1",
        config_id="T-01",
        order_index=0,
        status="pending",
        checklist=[{"req_id": "R1", "desc": "Do it", "priority": "critical", "status": "open"}],
    )
    attempt = AttemptModel(
        id="att-1",
        task_id="task-1",
        attempt_num=1,
        started_at=datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc),
        tokens_read=100,
    )

    run.steps.append(step)
    step.tasks.append(task)
    task.attempts.append(attempt)
    session.add(run)
    await session.flush()

    result = await session.execute(select(RunModel).where(RunModel.id == "run-1"))
    loaded = result.scalar_one()
    assert len(loaded.steps) == 1
    assert loaded.steps[0].config_id == "S-01"
    assert len(loaded.steps[0].tasks) == 1
    assert loaded.steps[0].tasks[0].checklist[0]["req_id"] == "R1"
    assert len(loaded.steps[0].tasks[0].attempts) == 1
    assert loaded.steps[0].tasks[0].attempts[0].tokens_read == 100


async def test_cascade_delete(session: AsyncSession) -> None:
    run = _make_run()
    step = StepModel(id="step-1", run_id="run-1", config_id="S-01", order_index=0)
    task = TaskModel(id="task-1", step_id="step-1", config_id="T-01", order_index=0, checklist=[])
    attempt = AttemptModel(id="att-1", task_id="task-1", attempt_num=1)
    event = EventModel(
        run_id="run-1",
        event_type="run_status_changed",
        timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        payload={"old_status": "draft", "new_status": "active"},
    )

    run.steps.append(step)
    step.tasks.append(task)
    task.attempts.append(attempt)
    run.events.append(event)
    session.add(run)
    await session.flush()

    await session.delete(run)
    await session.flush()

    assert (await session.execute(select(StepModel))).scalars().all() == []
    assert (await session.execute(select(TaskModel))).scalars().all() == []
    assert (await session.execute(select(AttemptModel))).scalars().all() == []
    assert (await session.execute(select(EventModel))).scalars().all() == []


async def test_event_insert_and_query(session: AsyncSession) -> None:
    run = _make_run()
    session.add(run)
    await session.flush()

    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    events = [
        EventModel(
            run_id="run-1",
            event_type="run_status_changed",
            timestamp=now,
            payload={"old_status": "draft", "new_status": "active"},
        ),
        EventModel(
            run_id="run-1",
            event_type="task_status_changed",
            timestamp=now,
            payload={"task_id": "t1", "old_status": "pending", "new_status": "building"},
        ),
    ]
    session.add_all(events)
    await session.flush()

    result = await session.execute(
        select(EventModel).where(EventModel.run_id == "run-1").order_by(EventModel.id)
    )
    loaded = result.scalars().all()
    assert len(loaded) == 2
    assert loaded[0].event_type == "run_status_changed"
    assert loaded[1].event_type == "task_status_changed"


async def test_step_ordering(session: AsyncSession) -> None:
    run = _make_run()
    run.steps = [
        StepModel(id="step-2", run_id="run-1", config_id="S-02", order_index=1),
        StepModel(id="step-1", run_id="run-1", config_id="S-01", order_index=0),
    ]
    session.add(run)
    await session.flush()

    # Expire and reload with eager loading to verify DB ordering
    session.expire_all()
    result = await session.execute(
        select(RunModel).where(RunModel.id == "run-1").options(selectinload(RunModel.steps))
    )
    loaded = result.scalar_one()
    assert loaded.steps[0].config_id == "S-01"
    assert loaded.steps[1].config_id == "S-02"


async def test_run_fields_roundtrip(session: AsyncSession) -> None:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = RunModel(
        id="run-full",
        project_id="proj-1",
        status="active",
        routine_id="routine-1",
        routine_sha="abc123",
        routine_source="local",
        agent_type="openhands_local",
        agent_config={"key": "val"},
        worktree_enabled=True,
        worktree_path="/tmp/wt",
        delete_worktree_on_completion=False,
        config={"feature": "auth"},
        current_step_index=2,
        created_at=now,
        updated_at=now,
        started_at=now,
        total_tokens_read=500,
        total_tokens_write=200,
        total_duration_ms=30000,
    )
    session.add(run)
    await session.flush()

    result = await session.execute(select(RunModel).where(RunModel.id == "run-full"))
    loaded = result.scalar_one()
    assert loaded.routine_id == "routine-1"
    assert loaded.routine_sha == "abc123"
    assert loaded.agent_type == "openhands_local"
    assert loaded.agent_config == {"key": "val"}
    assert loaded.worktree_enabled is True
    assert loaded.worktree_path == "/tmp/wt"
    assert loaded.config == {"feature": "auth"}
    assert loaded.current_step_index == 2
    assert loaded.total_tokens_read == 500
