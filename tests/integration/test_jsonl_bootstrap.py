"""Integration tests for JSONL bootstrap (Task 5.5/5.6).

Three scenarios:
1. Known JSONL fixture seeds events_v2 and populates projection tables.
2. Already-populated DB: bootstrap is a no-op.
3. Missing JSONL: WARNING logged, no exception raised.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import (
    ProjectionRegistry,
    RunStateProjector,
    TaskStateProjector,
    bootstrap_from_jsonl,
    create_engine,
    create_session_factory,
    init_db,
)

_RUN_ID = "run-bootstrap-test-1"
_TASK_ID = "task-bootstrap-test-1"
_STEP_ID = "step-bootstrap-test-1"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _write_fixture_jsonl(path: Path) -> None:
    """Write a JSONL fixture in outbox format."""
    records = [
        {
            "position": 1,
            "aggregate_id": _RUN_ID,
            "event_type": "run_created",
            "timestamp": "2025-01-15T10:30:00+00:00",
            "payload": {
                "run_id": _RUN_ID,
                "event_type": "run_created",
                "timestamp": "2025-01-15T10:30:00+00:00",
                "routine_id": "test-routine",
                "project_path": "",
                "repo_name": "test-repo",
                "status": "draft",
                "config": {},
                "parent_run_id": None,
                "parent_task_id": None,
            },
        },
        {
            "position": 2,
            "aggregate_id": _RUN_ID,
            "event_type": "run_status_changed",
            "timestamp": "2025-01-15T10:30:01+00:00",
            "payload": {
                "run_id": _RUN_ID,
                "event_type": "run_status_changed",
                "timestamp": "2025-01-15T10:30:01+00:00",
                "old_status": "draft",
                "new_status": "active",
                "pause_reason": None,
                "last_error": None,
            },
        },
        {
            "position": 3,
            "aggregate_id": _RUN_ID,
            "event_type": "task_created",
            "timestamp": "2025-01-15T10:30:02+00:00",
            "payload": {
                "run_id": _RUN_ID,
                "event_type": "task_created",
                "timestamp": "2025-01-15T10:30:02+00:00",
                "task_id": _TASK_ID,
                "step_id": _STEP_ID,
                "step_index": 0,
                "config_id": "task-1",
                "title": "Task 1",
                "complexity": None,
                "order_index": 0,
                "max_attempts": 3,
                "checklist": [],
                "parent_task_id": None,
            },
        },
        {
            "position": 4,
            "aggregate_id": _RUN_ID,
            "event_type": "agent_output",
            "timestamp": "2025-01-15T10:30:03+00:00",
            "payload": {
                "run_id": _RUN_ID,
                "event_type": "agent_output",
                "timestamp": "2025-01-15T10:30:03+00:00",
                "task_id": _TASK_ID,
                "attempt_num": 1,
                "lines": ["runtime output"],
                "line_offset": 0,
            },
        },
        {
            "position": 5,
            "aggregate_id": _RUN_ID,
            "event_type": "agent_error",
            "timestamp": "2025-01-15T10:30:04+00:00",
            "payload": {
                "run_id": _RUN_ID,
                "event_type": "agent_error",
                "timestamp": "2025-01-15T10:30:04+00:00",
                "task_id": _TASK_ID,
                "attempt_num": 1,
                "error_type": "AgentExecutionError",
                "error_message": "failed",
            },
        },
        {
            "position": 6,
            "aggregate_id": _RUN_ID,
            "event_type": "health_check",
            "timestamp": "2025-01-15T10:30:05+00:00",
            "payload": {
                "run_id": _RUN_ID,
                "event_type": "health_check",
                "timestamp": "2025-01-15T10:30:05+00:00",
                "phase": "completed",
                "message": "ok",
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _write_legacy_fixture_jsonl(path: Path) -> None:
    """Write a JSONL fixture in legacy history format."""
    records = [
        {
            "sequence_number": 10,
            "run_id": _RUN_ID,
            "event_type": "run_created",
            "timestamp": "2025-01-15T10:30:00+00:00",
            "payload": {
                "routine_id": "test-routine",
                "project_path": "",
                "repo_name": "test-repo",
                "status": "draft",
                "config": {},
                "parent_run_id": None,
                "parent_task_id": None,
            },
        },
        {
            "sequence_number": 11,
            "run_id": _RUN_ID,
            "event_type": "step_created",
            "timestamp": "2025-01-15T10:30:01+00:00",
            "payload": {
                "step_id": _STEP_ID,
                "config_id": "step-1",
                "title": "Step 1",
                "order_index": 0,
            },
        },
        {
            "sequence_number": 12,
            "run_id": _RUN_ID,
            "event_type": "task_created",
            "timestamp": "2025-01-15T10:30:02+00:00",
            "payload": {
                "task_id": _TASK_ID,
                "step_id": _STEP_ID,
                "step_index": 0,
                "config_id": "task-1",
                "title": "Task 1",
                "order_index": 0,
                "max_attempts": 3,
                "checklist": [],
                "parent_task_id": None,
            },
        },
        {
            "sequence_number": 13,
            "run_id": _RUN_ID,
            "event_type": "run_status_changed",
            "timestamp": "2025-01-15T10:30:03+00:00",
            "payload": {
                "old_status": "draft",
                "new_status": "active",
                "pause_reason": None,
                "last_error": None,
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def test_operational_scripts_import_cleanly() -> None:
    """Maintained and fenced operational scripts must not fail at import time."""
    for module_name in [
        "scripts.restore_from_journal",
        "scripts.seed_db",
        "scripts.clone_run_from_s2",
        "scripts.experiments.kickoff_e8_arm_b",
        "scripts.experiments.kickoff_e8_arm_c",
    ]:
        import_module(module_name)


async def test_bootstrap_seeds_events_and_rebuilds_projections(
    session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scenario 1: Known JSONL fixture seeds events_v2, populates runs table, sets checkpoints."""
    journal_path = tmp_path / "history.jsonl"
    _write_fixture_jsonl(journal_path)

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())

    with caplog.at_level(logging.DEBUG, logger="orchestrator.db.bootstrap"):
        await bootstrap_from_jsonl(session, journal_path, registry)
    await session.flush()

    # events_v2 row count matches fixture (6 events)
    count = (await session.execute(text("SELECT COUNT(*) FROM events_v2"))).scalar_one()
    assert count == 6
    event_types = [
        row[0]
        for row in (
            await session.execute(text("SELECT event_type FROM events_v2 ORDER BY position"))
        ).fetchall()
    ]
    assert event_types == [
        "run_created",
        "run_status_changed",
        "task_created",
        "agent_output",
        "agent_error",
        "health_check",
    ]
    assert not any("skipping unknown event type" in record.message for record in caplog.records)

    # runs projection table has the expected row with correct status
    run_row = (
        await session.execute(
            text("SELECT status FROM runs WHERE id = :id"),
            {"id": _RUN_ID},
        )
    ).fetchone()
    assert run_row is not None, "runs table should contain the bootstrapped run"
    assert run_row[0] == "active"  # RunStatusChanged(new_status=active) was applied

    # tasks projection table has the expected row
    task_row = (
        await session.execute(
            text("SELECT id FROM tasks WHERE id = :id"),
            {"id": _TASK_ID},
        )
    ).fetchone()
    assert task_row is not None, "tasks table should contain the bootstrapped task"

    # projection_checkpoints records the last processed position
    checkpoints = (
        await session.execute(
            text("SELECT projector_name, last_position FROM projection_checkpoints")
        )
    ).fetchall()
    assert len(checkpoints) > 0, "projection_checkpoints should have at least one entry"
    for projector_name, last_pos in checkpoints:
        assert last_pos == 6, (
            f"Checkpoint for {projector_name} should be at last position 6, got {last_pos}"
        )


async def test_bootstrap_noop_when_events_v2_populated(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Scenario 2: Already-populated DB means bootstrap is a no-op."""
    journal_path = tmp_path / "history.jsonl"
    _write_fixture_jsonl(journal_path)

    # Pre-populate events_v2 with one existing row
    await session.execute(
        text(
            "INSERT INTO events_v2"
            " (position, aggregate_id, event_type, payload, timestamp, version)"
            " VALUES (99, 'existing-run', 'run_status_changed', '{}', '2025-01-01T00:00:00', 1)"
        )
    )
    await session.flush()

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())

    # Bootstrap should detect non-empty events_v2 and return without inserting
    await bootstrap_from_jsonl(session, journal_path, registry)
    await session.flush()

    # Count must still be 1 — the fixture events were NOT inserted
    count = (await session.execute(text("SELECT COUNT(*) FROM events_v2"))).scalar_one()
    assert count == 1, "Bootstrap should be a no-op when events_v2 is non-empty"

    # runs table should remain empty (projections not rebuilt from fixture)
    run_count = (await session.execute(text("SELECT COUNT(*) FROM runs"))).scalar_one()
    assert run_count == 0, "Runs table should not be populated by no-op bootstrap"


async def test_bootstrap_supports_legacy_history_jsonl(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Legacy history records seed events_v2 and rebuild current projections."""
    journal_path = tmp_path / "history.jsonl"
    _write_legacy_fixture_jsonl(journal_path)

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())

    await bootstrap_from_jsonl(session, journal_path, registry)
    await session.flush()

    events = (
        await session.execute(
            text(
                "SELECT position, aggregate_id, event_type, version "
                "FROM events_v2 ORDER BY position"
            )
        )
    ).fetchall()
    assert events == [
        (10, _RUN_ID, "run_created", 1),
        (11, _RUN_ID, "step_created", 2),
        (12, _RUN_ID, "task_created", 3),
        (13, _RUN_ID, "run_status_changed", 4),
    ]

    run_status = (
        await session.execute(text("SELECT status FROM runs WHERE id = :id"), {"id": _RUN_ID})
    ).scalar_one()
    assert run_status == "active"

    step_id = (
        await session.execute(text("SELECT id FROM steps WHERE id = :id"), {"id": _STEP_ID})
    ).scalar_one()
    assert step_id == _STEP_ID

    task_id = (
        await session.execute(text("SELECT id FROM tasks WHERE id = :id"), {"id": _TASK_ID})
    ).scalar_one()
    assert task_id == _TASK_ID


async def test_restore_script_restores_legacy_jsonl_to_file_db(tmp_path: Path) -> None:
    """The restore script entrypoint uses events_v2 bootstrap against a real DB file."""
    restore_module = import_module("scripts.restore_from_journal")
    db_path = tmp_path / "orchestrator.db"
    journal_path = tmp_path / "history.jsonl"
    _write_legacy_fixture_jsonl(journal_path)

    await restore_module.restore_from_journal(db_path=db_path, journal_path=journal_path)

    engine = create_engine(db_path)
    try:
        factory = create_session_factory(engine)
        async with factory() as verify_session:
            event_count = (
                await verify_session.execute(text("SELECT COUNT(*) FROM events_v2"))
            ).scalar_one()
            assert event_count == 4
            run_status = (
                await verify_session.execute(
                    text("SELECT status FROM runs WHERE id = :id"), {"id": _RUN_ID}
                )
            ).scalar_one()
            assert run_status == "active"
    finally:
        await engine.dispose()


async def test_bootstrap_graceful_missing_jsonl(
    session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scenario 3: Missing JSONL path → WARNING logged, no exception raised."""
    non_existent_path = tmp_path / "does_not_exist.jsonl"

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())

    with caplog.at_level(logging.WARNING, logger="orchestrator.db.bootstrap"):
        # None path should log a warning and return cleanly
        await bootstrap_from_jsonl(session, None, registry)
        # Non-existent file should also log a warning and return cleanly
        await bootstrap_from_jsonl(session, non_existent_path, registry)

    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warning_messages) >= 2, (
        "Expected at least 2 warnings (one for None path, one for missing file), "
        f"got {warning_messages}"
    )

    # events_v2 must remain empty — no exception means no partial inserts
    count = (await session.execute(text("SELECT COUNT(*) FROM events_v2"))).scalar_one()
    assert count == 0, "events_v2 should be empty after graceful missing-JSONL bootstrap"
