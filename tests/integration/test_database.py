"""Integration tests for database setup and ORM models."""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
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
    assert "events_v2" in tables
    await engine.dispose()


async def test_crud_run(session: AsyncSession) -> None:
    run = _make_run()
    session.add(run)
    await session.flush()

    result = await session.execute(select(RunModel).where(RunModel.id == "run-1"))
    loaded = result.scalar_one()
    assert loaded.repo_name == "proj-1"
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


def test_event_v2_metadata_exposes_durability_contract() -> None:
    table = EventV2Model.__table__

    assert table.primary_key.columns.keys() == ["position"]
    assert table.c.position.autoincrement is True

    required_columns = {
        "position",
        "aggregate_id",
        "event_type",
        "payload",
        "timestamp",
        "version",
    }
    assert required_columns <= set(table.columns.keys())
    for column_name in required_columns:
        assert not table.c[column_name].nullable
    assert "event_id" not in table.columns
    assert "import_id" not in table.columns

    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.name
    }
    assert unique_constraints["uq_events_v2_aggregate_version"] == ("aggregate_id", "version")

    indexes = {
        index.name: tuple(column.name for column in index.columns) for index in table.indexes
    }
    assert indexes["idx_events_v2_aggregate"] == ("aggregate_id", "position")
    assert indexes["idx_events_v2_type"] == ("event_type", "position")


async def test_events_v2_alembic_schema_and_retry_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "events-v2-migration.sqlite"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)

    async with engine.begin() as conn:
        schema = await conn.run_sync(
            lambda sync_conn: {
                "columns": {
                    column["name"]: column for column in inspect(sync_conn).get_columns("events_v2")
                },
                "pk": inspect(sync_conn).get_pk_constraint("events_v2"),
                "unique": inspect(sync_conn).get_unique_constraints("events_v2"),
                "indexes": inspect(sync_conn).get_indexes("events_v2"),
            }
        )

    assert set(schema["columns"]) >= {
        "position",
        "aggregate_id",
        "event_type",
        "payload",
        "timestamp",
        "version",
    }
    assert schema["pk"]["constrained_columns"] == ["position"]
    assert any(
        constraint["name"] == "uq_events_v2_aggregate_version"
        and constraint["column_names"] == ["aggregate_id", "version"]
        for constraint in schema["unique"]
    )
    indexes = {index["name"]: index["column_names"] for index in schema["indexes"]}
    assert indexes["idx_events_v2_aggregate"] == ["aggregate_id", "position"]
    assert indexes["idx_events_v2_type"] == ["event_type", "position"]

    async with factory() as migrated_session:
        await migrated_session.execute(
            text(
                "INSERT INTO events_v2"
                " (aggregate_id, event_type, payload, timestamp, version)"
                " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
            ),
            {
                "aggregate_id": "retry-run",
                "event_type": "run_status_changed",
                "payload": json.dumps({"run_id": "retry-run"}),
                "timestamp": "2025-01-15T10:30:00Z",
                "version": 1,
            },
        )
        await migrated_session.flush()
        await migrated_session.commit()

        with pytest.raises(IntegrityError):
            await migrated_session.execute(
                text(
                    "INSERT INTO events_v2"
                    " (aggregate_id, event_type, payload, timestamp, version)"
                    " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
                ),
                {
                    "aggregate_id": "retry-run",
                    "event_type": "task_status_changed",
                    "payload": json.dumps({"run_id": "retry-run", "task_id": "task-1"}),
                    "timestamp": "2025-01-15T10:30:01Z",
                    "version": 1,
                },
            )
            await migrated_session.flush()

        await migrated_session.rollback()

    async with factory() as verify_session:
        count = await verify_session.scalar(
            text(
                "SELECT COUNT(*) FROM events_v2"
                " WHERE aggregate_id = :aggregate_id AND version = :version"
            ),
            {"aggregate_id": "retry-run", "version": 1},
        )
        assert count == 1

    await engine.dispose()


async def test_events_v2_retry_identity_is_aggregate_version_not_payload_identity(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "events-v2-identity-limitation.sqlite"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)

    payload = json.dumps({"run_id": "retry-run", "status": "active"})
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO events_v2"
                " (aggregate_id, event_type, payload, timestamp, version)"
                " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
            ),
            {
                "aggregate_id": "retry-run",
                "event_type": "run_status_changed",
                "payload": payload,
                "timestamp": "2025-01-15T10:30:00Z",
                "version": 1,
            },
        )
        await session.execute(
            text(
                "INSERT INTO events_v2"
                " (aggregate_id, event_type, payload, timestamp, version)"
                " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
            ),
            {
                "aggregate_id": "retry-run",
                "event_type": "run_status_changed",
                "payload": payload,
                "timestamp": "2025-01-15T10:30:00Z",
                "version": 2,
            },
        )
        await session.commit()

    async with factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO events_v2"
                    " (aggregate_id, event_type, payload, timestamp, version)"
                    " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
                ),
                {
                    "aggregate_id": "retry-run",
                    "event_type": "task_status_changed",
                    "payload": json.dumps({"run_id": "retry-run", "task_id": "task-1"}),
                    "timestamp": "2025-01-15T10:30:01Z",
                    "version": 2,
                },
            )
            await session.flush()

        await session.rollback()

    async with factory() as verify_session:
        rows = (
            (
                await verify_session.execute(
                    text(
                        "SELECT position, payload, version FROM events_v2"
                        " WHERE aggregate_id = :aggregate_id ORDER BY position"
                    ),
                    {"aggregate_id": "retry-run"},
                )
            )
            .mappings()
            .all()
        )

    assert [(row["version"], row["payload"]) for row in rows] == [(1, payload), (2, payload)]
    await engine.dispose()


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
        repo_name="proj-1",
        source_branch="main",
        status="active",
        routine_id="routine-1",
        routine_sha="abc123",
        routine_source="local",
        runner_type="openhands_local",
        runner_config={"key": "val"},
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
    assert loaded.runner_type == "openhands_local"
    assert loaded.runner_config == {"key": "val"}
    assert loaded.worktree_enabled is True
    assert loaded.worktree_path == "/tmp/wt"
    assert loaded.config == {"feature": "auth"}
    assert loaded.current_step_index == 2
    assert loaded.total_tokens_read == 500
