"""Integration tests for database setup and ORM models."""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import AttemptModel, EventV2Model, RunModel, StepModel, TaskModel


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run(run_id: str = "run-1", repo_name: str = "proj-1") -> RunModel:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return RunModel(
        id=run_id,
        repo_name=repo_name,
        status="draft",
        runner_config={},
        config={},
        created_at=now,
        updated_at=now,
    )


async def test_init_db_creates_tables() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn))
    assert "runs" in tables
    assert "steps" in tables
    assert "tasks" in tables
    assert "attempts" in tables
    assert "events_v2" in tables
    await engine.dispose()


async def test_cascade_delete(session: AsyncSession) -> None:
    run = _make_run()
    step = StepModel(id="step-1", run_id="run-1", config_id="S-01", order_index=0)
    task = TaskModel(id="task-1", step_id="step-1", config_id="T-01", order_index=0, checklist=[])
    attempt = AttemptModel(id="att-1", task_id="task-1", attempt_num=1)

    run.steps.append(step)
    step.tasks.append(task)
    task.attempts.append(attempt)
    session.add(run)
    await session.flush()

    await session.delete(run)
    await session.flush()

    assert (await session.execute(select(StepModel))).scalars().all() == []
    assert (await session.execute(select(TaskModel))).scalars().all() == []
    assert (await session.execute(select(AttemptModel))).scalars().all() == []


async def test_event_v2_insert_and_query(session: AsyncSession) -> None:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc).isoformat()
    events = [
        EventV2Model(
            aggregate_id="run-1",
            event_type="run_status_changed",
            timestamp=now,
            payload=json.dumps({"old_status": "draft", "new_status": "active"}),
            version=1,
        ),
        EventV2Model(
            aggregate_id="run-1",
            event_type="task_status_changed",
            timestamp=now,
            payload=json.dumps(
                {"task_id": "t1", "old_status": "pending", "new_status": "building"}
            ),
            version=2,
        ),
    ]
    session.add_all(events)
    await session.flush()

    result = await session.execute(
        select(EventV2Model)
        .where(EventV2Model.aggregate_id == "run-1")
        .order_by(EventV2Model.position)
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
