"""Integration tests for event-log durability proof helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.deps import get_event_store_v2
from orchestrator.config.enums import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db import (
    AttemptModel,
    EventV2Model,
    JsonlOutboxObserver,
    ProjectionRegistry,
    RunModel,
    RunStateProjector,
    SqliteEventStore,
    StepModel,
    TaskModel,
    TaskStateProjector,
    commit_with_event_outbox,
    create_engine,
    create_session_factory,
    create_wired_event_store_v2,
    init_db,
)
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import (
    AttemptUpdated,
    RunCreated,
    RunStatusChanged,
    StepCompleted,
    StepCreated,
    TaskAttemptCreated,
    TaskCreated,
    TaskStatusChanged,
    deserialize_event,
)
from orchestrator.workflow.service import WorkflowService

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

PROJECTION_TABLES = {
    "runs": RunModel,
    "steps": StepModel,
    "tasks": TaskModel,
    "attempts": AttemptModel,
}

# Helper contract: no deterministic run/step/task/attempt read-model columns are
# omitted. If a future projector-owned column is intentionally skipped, name it
# here with the domain reason it is non-deterministic.
CANONICAL_PROJECTION_OMITTED_FIELDS: dict[str, dict[str, str]] = {
    "runs": {},
    "steps": {},
    "tasks": {},
    "attempts": {},
}


def _make_service_run(run_id: str = "durable-service-run") -> Run:
    return Run(
        id=run_id,
        repo_name="durable-repo",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="durable-routine",
        routine_source=RoutineSource.LOCAL,
        config={"durability": True},
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_runner_config={"model": "gpt-5.3-codex"},
        steps=[
            StepState(
                id="durable-service-step",
                config_id="S-01",
                title="Durability Step",
                step_index=0,
                tasks=[
                    TaskState(
                        id="durable-service-task",
                        config_id="T-01",
                        title="Durability Task",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R8",
                                desc="Prove event log durability",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=2,
                    )
                ],
            )
        ],
        created_at=NOW,
        updated_at=NOW,
    )


def _run_created_event(run_id: str) -> RunCreated:
    return RunCreated(
        run_id=run_id,
        timestamp=NOW,
        routine_id="durable-routine",
        repo_name="durable-repo",
        status=RunStatus.DRAFT,
        config={"durability": True},
        runner_type=AgentRunnerType.CLI_SUBPROCESS.value,
        runner_config={"model": "gpt-5.3-codex"},
        current_step_index=0,
        created_at="2025-01-15T10:30:00Z",
        updated_at="2025-01-15T10:30:00Z",
    )


def _crash_retry_lifecycle_events(run_id: str) -> list[Any]:
    return [
        _run_created_event(run_id),
        StepCreated(
            run_id=run_id,
            timestamp=NOW,
            step_id="crash-retry-step",
            config_id="S-01",
            title="Crash Retry Step",
            order_index=0,
        ),
        TaskCreated(
            run_id=run_id,
            timestamp=NOW,
            task_id="crash-retry-task",
            step_id="crash-retry-step",
            step_index=0,
            config_id="T-01",
            title="Crash Retry Task",
            order_index=0,
            checklist=[
                {
                    "req_id": "R12",
                    "title": "Crash retry durability",
                    "status": ChecklistStatus.OPEN.value,
                }
            ],
            status=TaskStatus.PENDING,
            max_attempts=2,
        ),
    ]


def test_events_v2_schema_metadata_exposes_durability_contract() -> None:
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
    assert unique_constraints["uq_events_v2_aggregate_version"] == (
        "aggregate_id",
        "version",
    )

    indexes = {
        index.name: tuple(column.name for column in index.columns) for index in table.indexes
    }
    assert indexes["idx_events_v2_aggregate"] == ("aggregate_id", "position")
    assert indexes["idx_events_v2_type"] == ("event_type", "position")


async def test_events_v2_migration_schema_and_retry_identity(tmp_path: Path) -> None:
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


async def test_events_v2_ordering_uses_position_and_aggregate_version(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "events-v2-ordering.sqlite"
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

    assert [row["position"] for row in rows] == sorted(row["position"] for row in rows)
    assert [(row["version"], row["payload"]) for row in rows] == [(1, payload), (2, payload)]
    await engine.dispose()


async def test_duplicate_stable_event_identity_is_constraint_backed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "events-v2-duplicate-identity.sqlite"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)

    aggregate_id = "duplicate-identity-run"
    payload = json.dumps({"run_id": aggregate_id, "status": "active"})

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO events_v2"
                " (aggregate_id, event_type, payload, timestamp, version)"
                " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
            ),
            {
                "aggregate_id": aggregate_id,
                "event_type": "run_status_changed",
                "payload": payload,
                "timestamp": "2025-01-15T10:30:00Z",
                "version": 1,
            },
        )
        await session.commit()

    async with factory() as duplicate_session:
        with pytest.raises(IntegrityError):
            await duplicate_session.execute(
                text(
                    "INSERT INTO events_v2"
                    " (aggregate_id, event_type, payload, timestamp, version)"
                    " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
                ),
                {
                    "aggregate_id": aggregate_id,
                    "event_type": "run_status_changed",
                    "payload": payload,
                    "timestamp": "2025-01-15T10:30:00Z",
                    "version": 1,
                },
            )
            await duplicate_session.flush()
        await duplicate_session.rollback()

    async with factory() as verify_session:
        row_count = await verify_session.scalar(
            text("SELECT COUNT(*) FROM events_v2 WHERE aggregate_id = :aggregate_id"),
            {"aggregate_id": aggregate_id},
        )
        stream = await SqliteEventStore(verify_session).get_stream(aggregate_id)

    assert row_count == 1
    assert [(event.event_type, event.version, event.payload) for event in stream] == [
        ("run_status_changed", 1, payload)
    ]

    await engine.dispose()


async def test_duplicate_aggregate_sequence_preserves_original_ordered_stream(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "events-v2-duplicate-sequence.sqlite"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)

    aggregate_id = "duplicate-sequence-run"
    first_payload = json.dumps({"run_id": aggregate_id, "status": "active"})
    second_payload = json.dumps({"run_id": aggregate_id, "task_id": "task-1"})

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO events_v2"
                " (aggregate_id, event_type, payload, timestamp, version)"
                " VALUES"
                " (:aggregate_id, 'run_status_changed', :first_payload,"
                "  '2025-01-15T10:30:00Z', 1),"
                " (:aggregate_id, 'task_status_changed', :second_payload,"
                "  '2025-01-15T10:30:01Z', 2)"
            ),
            {
                "aggregate_id": aggregate_id,
                "first_payload": first_payload,
                "second_payload": second_payload,
            },
        )
        await session.commit()

    async with factory() as duplicate_session:
        with pytest.raises(IntegrityError):
            await duplicate_session.execute(
                text(
                    "INSERT INTO events_v2"
                    " (aggregate_id, event_type, payload, timestamp, version)"
                    " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
                ),
                {
                    "aggregate_id": aggregate_id,
                    "event_type": "checklist_gate_evaluated",
                    "payload": json.dumps(
                        {"run_id": aggregate_id, "task_id": "task-1", "passed": True}
                    ),
                    "timestamp": "2025-01-15T10:30:02Z",
                    "version": 2,
                },
            )
            await duplicate_session.flush()
        await duplicate_session.rollback()

    async with factory() as verify_session:
        row_count = await verify_session.scalar(
            text("SELECT COUNT(*) FROM events_v2 WHERE aggregate_id = :aggregate_id"),
            {"aggregate_id": aggregate_id},
        )
        stream = await SqliteEventStore(verify_session).get_stream(aggregate_id)

    assert row_count == 2
    assert [(event.event_type, event.version, event.payload) for event in stream] == [
        ("run_status_changed", 1, first_payload),
        ("task_status_changed", 2, second_payload),
    ]
    assert [event.position for event in stream] == sorted(event.position for event in stream)

    await engine.dispose()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return _normalize_json_value(decoded)
    if isinstance(value, dict):
        return {key: _normalize_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    return value


def _projection_snapshot_json(snapshot: dict[str, list[dict[str, Any]]]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True)


async def _aggregate_sequence_evidence(
    session: AsyncSession,
    run_id: str,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS event_count,"
                    " MIN(position) AS min_position,"
                    " MAX(position) AS max_position,"
                    " MIN(version) AS min_version,"
                    " MAX(version) AS max_version"
                    " FROM events_v2 WHERE aggregate_id = :run_id"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .one()
    )
    event_types = (
        (
            await session.execute(
                text(
                    "SELECT event_type FROM events_v2"
                    " WHERE aggregate_id = :run_id ORDER BY position"
                ),
                {"run_id": run_id},
            )
        )
        .scalars()
        .all()
    )
    return {
        "event_count": row["event_count"],
        "position_range": [row["min_position"], row["max_position"]],
        "aggregate_version_range": [row["min_version"], row["max_version"]],
        "event_types": event_types,
    }


async def canonical_projection_snapshot(
    session: AsyncSession,
) -> dict[str, list[dict[str, Any]]]:
    """Capture deterministic run, step, task, and attempt projection state.

    The snapshot reads the same application read-model tables used by API and
    workflow services. JSON columns are decoded and re-serialized with sorted
    keys so storage encoding and dict ordering cannot hide semantic mismatches.
    """
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for table_name, model in PROJECTION_TABLES.items():
        omitted_fields = CANONICAL_PROJECTION_OMITTED_FIELDS[table_name]
        columns = [
            column.name for column in model.__table__.columns if column.name not in omitted_fields
        ]
        column_sql = ", ".join(columns)
        order_sql = ", ".join(columns[:1])
        result = await session.execute(
            text(f"SELECT {column_sql} FROM {table_name} ORDER BY {order_sql}")
        )
        snapshot[table_name] = [
            {key: _normalize_json_value(row[key]) for key in columns}
            for row in result.mappings().all()
        ]
    return snapshot


async def test_canonical_projection_snapshot_matches_after_events_v2_rebuild(
    session: AsyncSession,
) -> None:
    store = create_wired_event_store_v2(session, include_outbox=False)
    await store.append(
        [
            RunCreated(
                run_id="durable-run",
                timestamp=NOW,
                routine_id="routine-1",
                repo_name="durable-repo",
                status=RunStatus.DRAFT,
                config={"z": 1, "a": {"nested": True}},
                runner_type=AgentRunnerType.CLI_SUBPROCESS.value,
                runner_config={"model": "gpt-5.3-codex", "settings": {"b": 2, "a": 1}},
                current_step_index=0,
            ),
            StepCreated(
                run_id="durable-run",
                timestamp=NOW,
                step_id="durable-step",
                config_id="S-01",
                title="Durability Step",
                order_index=0,
                condition={"right": "value", "left": "config.enabled"},
            ),
            TaskCreated(
                run_id="durable-run",
                timestamp=NOW,
                task_id="durable-task",
                step_id="durable-step",
                step_index=0,
                config_id="T-01",
                title="Durability Task",
                order_index=0,
                checklist=[
                    {"status": "pending", "req_id": "R4", "title": "Snapshot diagnostics"},
                    {"title": "Projection helper", "req_id": "R3", "status": "pending"},
                ],
                status=TaskStatus.PENDING,
                max_attempts=2,
            ),
            RunStatusChanged(
                run_id="durable-run",
                timestamp=NOW,
                event_type="run_status_changed",
                old_status=RunStatus.DRAFT,
                new_status=RunStatus.ACTIVE,
            ),
            TaskAttemptCreated(
                run_id="durable-run",
                timestamp=NOW,
                task_id="durable-task",
                attempt_id="attempt-1",
                attempt_num=1,
                runner_type=AgentRunnerType.CLI_SUBPROCESS.value,
                agent_model="gpt-5.3-codex",
                started_at="2025-01-15T10:30:00Z",
            ),
            AttemptUpdated(
                run_id="durable-run",
                timestamp=NOW,
                task_id="durable-task",
                attempt_id="attempt-1",
                output_lines=["builder output"],
                outcome="passed",
                completed_at="2025-01-15T10:31:00Z",
                grade_snapshot=[{"req_id": "R3", "grade": "A"}],
                auto_verify_results=[{"name": "durability", "passed": True}],
                action_log={"events": [{"name": "submit", "args": {"b": 2, "a": 1}}]},
                token_usage_by_model=[
                    {
                        "model": "gpt-5.3-codex",
                        "output_tokens": 5,
                        "input_tokens": 10,
                        "cache_read_tokens": 3,
                        "cache_creation_tokens": 1,
                    }
                ],
                tokens_read=10,
                tokens_write=5,
                tokens_cache=3,
                duration_ms=123,
                num_actions=1,
                agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
                agent_model="gpt-5.3-codex",
                agent_settings={"temperature": 0, "tools": ["submit", "update_checklist"]},
                start_commit="abc123",
                end_commit="def456",
            ),
            TaskStatusChanged(
                run_id="durable-run",
                timestamp=NOW,
                event_type="task_status_changed",
                task_id="durable-task",
                old_status=TaskStatus.BUILDING,
                new_status=TaskStatus.COMPLETED,
                current_attempt=1,
            ),
            StepCompleted(
                run_id="durable-run",
                timestamp=NOW,
                event_type="step_completed",
                step_id="durable-step",
                step_index=0,
            ),
            RunStatusChanged(
                run_id="durable-run",
                timestamp=NOW,
                event_type="run_status_changed",
                old_status=RunStatus.ACTIVE,
                new_status=RunStatus.COMPLETED,
            ),
        ]
    )
    await session.flush()

    before_rebuild = await canonical_projection_snapshot(session)

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.execute(text("DELETE FROM projection_checkpoints"))
    await session.flush()

    stored_events = await store.get_all()
    workflow_events = [
        deserialize_event(stored_event.event_type, stored_event.payload)
        for stored_event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()

    after_rebuild = await canonical_projection_snapshot(session)

    assert before_rebuild == after_rebuild, (
        "Canonical projection snapshot mismatch after events_v2 rebuild.\n"
        f"Omitted fields: {CANONICAL_PROJECTION_OMITTED_FIELDS}\n"
        f"Before rebuild:\n{_projection_snapshot_json(before_rebuild)}\n"
        f"After rebuild:\n{_projection_snapshot_json(after_rebuild)}"
    )


async def test_workflow_service_api_dependency_path_commits_events_v2_then_rebuilds_without_journal(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "service-api-proof" / "orchestrator.db"
    db_path.parent.mkdir()
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    journal_path = db_path.parent / ".orchestrator" / "state" / "history.jsonl"
    run_id = "durable-service-run"
    pre_commit_evidence: dict[str, Any] = {}

    async with factory() as session:
        api_store = await get_event_store_v2(session)

        async def capture_pre_commit_boundary(
            stored_events: list[Any],
            listener_session: AsyncSession,
            _workflow_events: list[Any],
        ) -> None:
            # workflow authority proof: events_v2 rows have been flushed before
            # the corresponding projection listener boundary is considered done.
            event_count = await listener_session.scalar(
                text("SELECT COUNT(*) FROM events_v2 WHERE aggregate_id = :run_id"),
                {"run_id": run_id},
            )
            task_projection_count = await listener_session.scalar(
                text(
                    "SELECT COUNT(*) FROM tasks"
                    " JOIN steps ON steps.id = tasks.step_id"
                    " WHERE steps.run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            if not pre_commit_evidence:
                pre_commit_evidence.update(
                    {
                        "stored_event_types": [event.event_type for event in stored_events],
                        "event_count": event_count,
                        "task_projection_count": task_projection_count,
                    }
                )

        api_store.add_projection_listener(capture_pre_commit_boundary)
        service = WorkflowService(session, event_store_v2=api_store)

        created = await service.create_run(_make_service_run(run_id))
        assert created.id == run_id
        await service.apply_start_run(run_id)
        await service.start_task(run_id, "durable-service-task")
        await service.update_checklist_item(
            run_id,
            "durable-service-task",
            "R8",
            ChecklistStatus.DONE,
        )
        await service.submit_for_verification(run_id, "durable-service-task")
        before_crash_evidence = await _aggregate_sequence_evidence(session, run_id)
        await service.trigger_recovery(
            run_id,
            "durable-service-task",
            "validator crashed before retry",
        )
        await service.complete_recovery_retry(
            run_id,
            "durable-service-task",
            "Retry from durable events_v2 state.",
        )
        after_retry_evidence = await _aggregate_sequence_evidence(session, run_id)

    assert pre_commit_evidence["stored_event_types"] == [
        "run_created",
        "step_created",
        "task_created",
    ]
    assert pre_commit_evidence["event_count"] == 3
    assert pre_commit_evidence["task_projection_count"] == 1
    assert before_crash_evidence["event_count"] > pre_commit_evidence["event_count"]
    assert before_crash_evidence["aggregate_version_range"] == [
        1,
        before_crash_evidence["event_count"],
    ]
    assert after_retry_evidence["event_count"] > before_crash_evidence["event_count"]
    assert after_retry_evidence["aggregate_version_range"] == [
        1,
        after_retry_evidence["event_count"],
    ]
    assert journal_path.exists()
    journal_records = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert [record["event_type"] for record in journal_records[:3]] == pre_commit_evidence[
        "stored_event_types"
    ]
    assert len(journal_records) == after_retry_evidence["event_count"]

    async with factory() as session:
        store = SqliteEventStore(session)
        stream = await store.get_stream(run_id)
        assert [event.event_type for event in stream[:3]] == [
            "run_created",
            "step_created",
            "task_created",
        ]
        assert [event.version for event in stream] == list(
            range(1, after_retry_evidence["event_count"] + 1)
        )
        assert [event.position for event in stream] == [
            record["position"] for record in journal_records
        ]
        before_rebuild = await canonical_projection_snapshot(session)

        # JSONL journal is a secondary import surface, not rebuild authority.
        journal_path.unlink()
        await session.execute(text("DELETE FROM attempts"))
        await session.execute(text("DELETE FROM tasks"))
        await session.execute(text("DELETE FROM steps"))
        await session.execute(text("DELETE FROM runs"))
        await session.execute(text("DELETE FROM projection_checkpoints"))
        await session.flush()
        checkpoint_count = await session.scalar(text("SELECT COUNT(*) FROM projection_checkpoints"))
        assert checkpoint_count == 0

        # Read ordered events from events_v2 after clearing disposable projections.
        stored_events = await SqliteEventStore(session).get_all()
        workflow_events = [
            deserialize_event(stored_event.event_type, stored_event.payload)
            for stored_event in stored_events
        ]
        registry = ProjectionRegistry()
        registry.register(RunStateProjector())
        registry.register(TaskStateProjector())
        await registry.rebuild_all(workflow_events, session)
        await session.flush()

        after_rebuild = await canonical_projection_snapshot(session)
        after_rebuild_evidence = await _aggregate_sequence_evidence(session, run_id)

    assert not journal_path.exists()
    assert after_rebuild_evidence == after_retry_evidence
    assert before_rebuild == after_rebuild, (
        "Canonical projection snapshot mismatch after service-path events_v2 rebuild.\n"
        f"Event evidence before crash: {before_crash_evidence}\n"
        f"Event evidence after retry: {after_retry_evidence}\n"
        f"Event evidence after rebuild: {after_rebuild_evidence}\n"
        f"Before rebuild:\n{_projection_snapshot_json(before_rebuild)}\n"
        f"After rebuild:\n{_projection_snapshot_json(after_rebuild)}"
    )
    await engine.dispose()


async def test_crash_retry_drill_keeps_accepted_events_unique_across_transaction_boundaries(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "crash-retry-drill" / "orchestrator.db"
    db_path.parent.mkdir()
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    run_id = "crash-retry-run"
    workflow_events = _crash_retry_lifecycle_events(run_id)
    evidence: dict[str, Any] = {"db_path_pattern": str(db_path)}

    async with factory() as interrupted_session:
        store = create_wired_event_store_v2(interrupted_session, include_outbox=False)
        await store.append(workflow_events)
        evidence["before_pre_commit_crash"] = await _aggregate_sequence_evidence(
            interrupted_session,
            run_id,
        )
        await interrupted_session.rollback()

    async with factory() as verify_rollback_session:
        evidence["after_pre_commit_rollback"] = await _aggregate_sequence_evidence(
            verify_rollback_session,
            run_id,
        )

    assert evidence["before_pre_commit_crash"] == {
        "event_count": 3,
        "position_range": [1, 3],
        "aggregate_version_range": [1, 3],
        "event_types": ["run_created", "step_created", "task_created"],
    }
    assert evidence["after_pre_commit_rollback"] == {
        "event_count": 0,
        "position_range": [None, None],
        "aggregate_version_range": [None, None],
        "event_types": [],
    }, evidence

    async with factory() as retry_session:
        store = create_wired_event_store_v2(retry_session, include_outbox=False)
        accepted = await store.append(workflow_events)
        await retry_session.commit()
        evidence["after_retry_commit"] = await _aggregate_sequence_evidence(
            retry_session,
            run_id,
        )

    assert [(event.event_type, event.version) for event in accepted] == [
        ("run_created", 1),
        ("step_created", 2),
        ("task_created", 3),
    ]
    assert evidence["after_retry_commit"] == {
        "event_count": 3,
        "position_range": [1, 3],
        "aggregate_version_range": [1, 3],
        "event_types": ["run_created", "step_created", "task_created"],
    }, evidence

    async with factory() as duplicate_retry_session:
        with pytest.raises(IntegrityError):
            await duplicate_retry_session.execute(
                text(
                    "INSERT INTO events_v2"
                    " (aggregate_id, event_type, payload, timestamp, version)"
                    " VALUES (:aggregate_id, :event_type, :payload, :timestamp, :version)"
                ),
                {
                    "aggregate_id": accepted[-1].aggregate_id,
                    "event_type": accepted[-1].event_type,
                    "payload": accepted[-1].payload,
                    "timestamp": accepted[-1].timestamp,
                    "version": accepted[-1].version,
                },
            )
            await duplicate_retry_session.flush()
        await duplicate_retry_session.rollback()

    async with factory() as verify_duplicate_retry_session:
        evidence["after_committed_duplicate_retry"] = await _aggregate_sequence_evidence(
            verify_duplicate_retry_session,
            run_id,
        )
        before_rebuild = await canonical_projection_snapshot(verify_duplicate_retry_session)
        await verify_duplicate_retry_session.execute(text("DELETE FROM attempts"))
        await verify_duplicate_retry_session.execute(text("DELETE FROM tasks"))
        await verify_duplicate_retry_session.execute(text("DELETE FROM steps"))
        await verify_duplicate_retry_session.execute(text("DELETE FROM runs"))
        await verify_duplicate_retry_session.execute(text("DELETE FROM projection_checkpoints"))
        await verify_duplicate_retry_session.flush()

        stored_events = await SqliteEventStore(verify_duplicate_retry_session).get_all()
        replay_events = [
            deserialize_event(stored_event.event_type, stored_event.payload)
            for stored_event in stored_events
        ]
        registry = ProjectionRegistry()
        registry.register(RunStateProjector())
        registry.register(TaskStateProjector())
        await registry.rebuild_all(replay_events, verify_duplicate_retry_session)
        await verify_duplicate_retry_session.flush()

        after_rebuild = await canonical_projection_snapshot(verify_duplicate_retry_session)
        evidence["after_rebuild"] = await _aggregate_sequence_evidence(
            verify_duplicate_retry_session,
            run_id,
        )

    assert evidence["after_committed_duplicate_retry"] == evidence["after_retry_commit"], evidence
    assert evidence["after_rebuild"] == evidence["after_retry_commit"], evidence
    assert before_rebuild == after_rebuild, (
        "Canonical projection snapshot mismatch after crash/retry drill rebuild.\n"
        f"Event evidence: {evidence}\n"
        f"Before rebuild:\n{_projection_snapshot_json(before_rebuild)}\n"
        f"After rebuild:\n{_projection_snapshot_json(after_rebuild)}"
    )
    await engine.dispose()


async def test_projection_rollback_when_listener_failure_prevents_commit(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "projection-failure-proof" / "orchestrator.db"
    db_path.parent.mkdir()
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    run_id = "projection-failure-run"
    failure_evidence: dict[str, Any] = {}

    async with factory() as session:
        store = create_wired_event_store_v2(session, include_outbox=False)

        async def failing_projection_listener(
            _stored_events: list[Any],
            listener_session: AsyncSession,
            _workflow_events: list[Any],
        ) -> None:
            # projection rollback evidence: events and projection rows are visible
            # inside the failed transaction and must disappear after rollback.
            failure_evidence["event_rows_before_failure"] = await listener_session.scalar(
                text("SELECT COUNT(*) FROM events_v2 WHERE aggregate_id = :run_id"),
                {"run_id": run_id},
            )
            failure_evidence["run_rows_before_failure"] = await listener_session.scalar(
                text("SELECT COUNT(*) FROM runs WHERE id = :run_id"),
                {"run_id": run_id},
            )
            raise RuntimeError("projection listener failed before commit")

        store.add_projection_listener(failing_projection_listener)
        with pytest.raises(RuntimeError, match="projection listener failed"):
            await store.append([_run_created_event(run_id)])
        await session.rollback()

    assert failure_evidence == {
        "event_rows_before_failure": 1,
        "run_rows_before_failure": 1,
    }
    async with factory() as session:
        event_count = await session.scalar(
            text("SELECT COUNT(*) FROM events_v2 WHERE aggregate_id = :run_id"),
            {"run_id": run_id},
        )
        run_count = await session.scalar(
            text("SELECT COUNT(*) FROM runs WHERE id = :run_id"),
            {"run_id": run_id},
        )
    assert event_count == 0
    assert run_count == 0
    await engine.dispose()


async def test_journal_failure_is_secondary_sink_post_commit(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "jsonl-failure-proof" / "orchestrator.db"
    db_path.parent.mkdir()
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    run_id = "jsonl-secondary-failure-run"
    journal_parent_as_file = tmp_path / "journal-parent-is-file"
    journal_parent_as_file.write_text("not a directory")
    bad_journal_path = journal_parent_as_file / "history.jsonl"

    async with factory() as session:
        store = create_wired_event_store_v2(session, include_outbox=False)
        store.add_listener(JsonlOutboxObserver(bad_journal_path))
        stored = await store.append([_run_created_event(run_id)])

        # secondary sink / post_commit boundary: journal failure happens after
        # database commit, so the accepted events_v2 row remains authoritative.
        with pytest.raises((FileExistsError, NotADirectoryError)):
            await commit_with_event_outbox(session)

    async with factory() as session:
        event_rows = await SqliteEventStore(session).get_stream(run_id)
        run_count = await session.scalar(
            text("SELECT COUNT(*) FROM runs WHERE id = :run_id"),
            {"run_id": run_id},
        )

    assert len(stored) == 1
    assert len(event_rows) == 1
    assert event_rows[0].event_type == "run_created"
    assert event_rows[0].version == 1
    assert run_count == 1
    assert not bad_journal_path.exists()
    await engine.dispose()
