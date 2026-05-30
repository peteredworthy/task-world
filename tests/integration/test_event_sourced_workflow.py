"""Integration tests: event-sourced workflow round-trip, empty-DB rebuild, status parity."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.config.enums import RunStatus
from orchestrator.db import init_db
from orchestrator.db import SqliteEventStore
from orchestrator.db import ProjectionRegistry, RunStateProjector, TaskStateProjector
from orchestrator.workflow import (
    CreateRunCommand,
    InitialStepForRunCreate,
    CreateTaskCommand,
    UpdateRunStatusCommand,
    handle_create_run,
    handle_create_task,
    handle_update_run_status,
)
from orchestrator.workflow import deserialize_event

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def api_fixture() -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    """Per-test fresh app + in-memory DB + HTTP client."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await app.state.engine.dispose()


async def test_full_workflow_round_trip(
    api_fixture: tuple[AsyncClient, Any],
) -> None:
    """API run-creation produces RunCreated event; GET /api/runs matches the POST response."""
    client, app = api_fixture
    session_factory = app.state.session_factory

    # Step 1: Create a run via the API
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "round-trip-repo", "branch": "main"},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    created = resp.json()
    run_id: str = created["id"]

    # Step 2: API response has correct fields
    assert created["status"] == "draft"
    assert created["routine_id"] == "simple-routine"
    assert created["repo_name"] == "round-trip-repo"

    # Step 3: events_v2 contains a RunCreated event for this run
    async with session_factory() as session:
        store = SqliteEventStore(session)
        stream = await store.get_stream(run_id)

    assert stream, "Expected at least one event in the stream"
    run_created_events = [e for e in stream if e.event_type == "run_created"]
    assert len(run_created_events) == 1, (
        f"Expected exactly one run_created event, got {[e.event_type for e in stream]}"
    )
    first = run_created_events[0]
    assert first.aggregate_id == run_id

    payload = json.loads(first.payload)
    assert payload["run_id"] == run_id
    assert payload["routine_id"] == "simple-routine"
    assert payload["repo_name"] == "round-trip-repo"

    # Step 4: GET /api/runs/{run_id} matches the POST response
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["id"] == run_id
    assert fetched["status"] == created["status"]
    assert fetched["routine_id"] == created["routine_id"]
    assert fetched["repo_name"] == created["repo_name"]


async def test_empty_db_rebuild(
    api_fixture: tuple[AsyncClient, Any],
) -> None:
    """Truncate runs+tasks, replay events via ProjectionRegistry, API response matches original."""
    client, app = api_fixture
    session_factory = app.state.session_factory

    run_id = "rebuild-run-001"
    step_id = "rebuild-step-001"
    task_id = "rebuild-task-001"

    # Step 1: Build state entirely via command handlers (no save_run / no API)
    async with session_factory() as session:
        registry = ProjectionRegistry()
        registry.register(RunStateProjector())
        registry.register(TaskStateProjector())
        store = SqliteEventStore(session)
        store.add_projection_listener(registry)

        # Emit RunCreated → projector inserts into runs table
        await handle_create_run(
            CreateRunCommand(
                run_id=run_id,
                routine_id="rebuild-routine",
                project_path="",
                repo_name="rebuild-repo",
                status=RunStatus.DRAFT,
                config={"rebuild_key": "rebuild_value"},
                initial_steps=[
                    InitialStepForRunCreate(
                        step_id=step_id,
                        config_id="S-01",
                        title="Rebuild Step",
                        order_index=0,
                        step_index=0,
                    )
                ],
            ),
            store,
            session,
        )

        # Emit TaskCreated → projector inserts into tasks table
        await handle_create_task(
            CreateTaskCommand(
                run_id=run_id,
                task_id=task_id,
                step_id=step_id,
                step_index=0,
                config_id="T-01",
                title="Rebuild Task",
                complexity="standard",
                order_index=0,
                max_attempts=3,
                checklist=[{"req_id": "R1", "desc": "rebuild passes", "priority": "critical"}],
            ),
            store,
            session,
        )

        # Emit RunStatusChanged → projector updates run status
        await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=RunStatus.DRAFT,
                new_status=RunStatus.PAUSED,
                pause_reason="test_empty_db_rebuild",
            ),
            store,
            session,
        )

        await session.commit()

    # Step 2: Capture current API response
    before_resp = await client.get(f"/api/runs/{run_id}")
    assert before_resp.status_code == 200, f"Run not found before truncation: {before_resp.text}"
    before = before_resp.json()
    assert before["status"] == "paused"
    assert before["routine_id"] == "rebuild-routine"
    assert before["repo_name"] == "rebuild-repo"
    assert len(before["steps"]) == 1
    assert len(before["steps"][0]["tasks"]) == 1

    # Step 3: Truncate runs and tasks read-model tables
    async with session_factory() as session:
        await session.execute(text("DELETE FROM tasks"))
        await session.execute(text("DELETE FROM runs"))
        await session.commit()

    # Step 4: Confirm the run is gone
    gone_resp = await client.get(f"/api/runs/{run_id}")
    assert gone_resp.status_code == 404, (
        f"Expected 404 after truncation, got {gone_resp.status_code}"
    )

    # Step 5: Rebuild projections from events_v2
    async with session_factory() as session:
        store = SqliteEventStore(session)
        all_stored = await store.get_all()

        workflow_events = []
        for se in all_stored:
            try:
                workflow_events.append(deserialize_event(se.event_type, se.payload))
            except (ValueError, KeyError):
                pass  # skip unknown/legacy event types

        rebuild_registry = ProjectionRegistry()
        rebuild_registry.register(RunStateProjector())
        rebuild_registry.register(TaskStateProjector())
        await rebuild_registry.rebuild_all(workflow_events, session)
        await session.commit()

    # Step 6: Re-fetch API response and compare field-by-field
    after_resp = await client.get(f"/api/runs/{run_id}")
    assert after_resp.status_code == 200, f"Run not found after rebuild: {after_resp.text}"
    after = after_resp.json()

    assert after["id"] == before["id"]
    assert after["status"] == before["status"]
    assert after["routine_id"] == before["routine_id"]
    assert after["repo_name"] == before["repo_name"]
    assert after["pause_reason"] == before["pause_reason"]
    assert len(after["steps"]) == len(before["steps"])
    assert len(after["steps"][0]["tasks"]) == len(before["steps"][0]["tasks"])
    assert after["steps"][0]["tasks"][0]["id"] == before["steps"][0]["tasks"][0]["id"]
    assert after["steps"][0]["tasks"][0]["title"] == before["steps"][0]["tasks"][0]["title"]
    assert after["steps"][0]["tasks"][0]["status"] == before["steps"][0]["tasks"][0]["status"]


async def test_parity_run_status_update(
    api_fixture: tuple[AsyncClient, Any],
) -> None:
    """UpdateRunStatusCommand produces RunStatusChanged event; API response agrees with projection."""
    client, app = api_fixture
    session_factory = app.state.session_factory

    run_id = "parity-run-001"

    # Build a run via command handler
    async with session_factory() as session:
        registry = ProjectionRegistry()
        registry.register(RunStateProjector())
        registry.register(TaskStateProjector())
        store = SqliteEventStore(session)
        store.add_projection_listener(registry)

        await handle_create_run(
            CreateRunCommand(
                run_id=run_id,
                routine_id="parity-routine",
                project_path="",
                repo_name="parity-repo",
                status=RunStatus.DRAFT,
            ),
            store,
            session,
        )

        # Emit status change via command handler
        await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=RunStatus.DRAFT,
                new_status=RunStatus.ACTIVE,
            ),
            store,
            session,
        )

        await session.commit()

    # Verify events_v2 has both events in order
    async with session_factory() as session:
        store = SqliteEventStore(session)
        stream = await store.get_stream(run_id)

    event_types = [e.event_type for e in stream]
    assert "run_created" in event_types, f"Missing run_created in {event_types}"
    assert "run_status_changed" in event_types, f"Missing run_status_changed in {event_types}"

    # run_created must precede run_status_changed
    created_pos = next(e.position for e in stream if e.event_type == "run_created")
    changed_pos = next(e.position for e in stream if e.event_type == "run_status_changed")
    assert created_pos < changed_pos

    # Verify the run_status_changed event payload
    status_event = next(e for e in stream if e.event_type == "run_status_changed")
    payload = json.loads(status_event.payload)
    assert payload["new_status"] == "active"
    assert payload["old_status"] == "draft"

    # Verify GET /api/runs/{run_id} agrees with the projected state
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["id"] == run_id
    assert fetched["status"] == "active", (
        f"API status {fetched['status']!r} does not match projected 'active'"
    )
