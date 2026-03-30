"""Integration tests for run API endpoints."""

from pathlib import Path

from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport_obj = InMemorySignalTransport()
    app.state.signal_transport = transport_obj
    drain = make_drain_fn(app, transport_obj)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


async def _create_run(client: AsyncClient) -> dict[str, Any]:
    """Helper: create a run and return the response data."""
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert response.status_code == 201
    return response.json()


async def test_create_run(client: AsyncClient) -> None:
    data = await _create_run(client)
    assert data["repo_name"] == "proj-1"
    assert data["routine_id"] == "simple-routine"
    assert data["status"] == "draft"
    assert len(data["steps"]) == 1
    assert len(data["steps"][0]["tasks"]) == 1


async def test_create_run_routine_not_found(client: AsyncClient) -> None:
    response = await client.post(
        "/api/runs",
        json={"routine_id": "nonexistent", "repo_name": "proj-1", "branch": "main"},
    )
    assert response.status_code == 404


async def test_list_runs_empty(client: AsyncClient) -> None:
    response = await client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}


async def test_list_runs(client: AsyncClient) -> None:
    await _create_run(client)
    response = await client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == 1


async def test_list_runs_filter_by_project(client: AsyncClient) -> None:
    await _create_run(client)

    response = await client.get("/api/runs?repo_name=proj-1")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    response = await client.get("/api/runs?repo_name=other-project")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 0


async def test_list_runs_filter_by_status(client: AsyncClient) -> None:
    await _create_run(client)

    response = await client.get("/api/runs?status=draft")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    response = await client.get("/api/runs?status=active")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 0


async def test_get_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id
    assert data["repo_name"] == "proj-1"


async def test_get_run_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/runs/nonexistent")
    assert response.status_code == 404


async def test_start_run(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"
    assert data["started_at"] is not None


async def test_start_run_invalid_state(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    # Start it first
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # Try to start again -> 409
    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 409


async def test_delete_run(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 204

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 404


async def test_delete_run_not_found(client: AsyncClient) -> None:
    response = await client.delete("/api/runs/nonexistent")
    assert response.status_code == 404


async def test_pause_run(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    # Start the run first
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # Pause it
    response = await client.post(f"/api/runs/{run_id}/pause")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "paused"


async def test_resume_run(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    # Start, then pause, then resume
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"


async def test_pause_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/runs/nonexistent/pause")
    assert response.status_code == 404


async def test_resume_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/runs/nonexistent/resume")
    assert response.status_code == 404


async def test_pause_invalid_state(client: AsyncClient) -> None:
    created = await _create_run(client)
    run_id = created["id"]

    # Try to pause a DRAFT run -> 409
    response = await client.post(f"/api/runs/{run_id}/pause")
    assert response.status_code == 409


async def test_resume_invalid_state(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    # Start the run (ACTIVE), then try to resume without pausing -> 409
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409


async def _drive_run_to_failed(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run and fail it by exhausting 3 verification attempts."""
    created = await _create_run(client)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    for _ in range(3):
        await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert resp.status_code == 200
        await drain(run_id)
        await client.put(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
            json={"grade": "D", "grade_reason": "force failure"},
        )
        resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
        assert resp.status_code == 200
        await drain(run_id)

    return run_id, task_id


async def _drive_run_to_completed(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run and complete it successfully."""
    created = await _create_run(client)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)
    return run_id, task_id


async def test_recover_run_success_from_failed(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _drive_run_to_failed(client, drain)
    run_before = await client.get(f"/api/runs/{run_id}")
    assert run_before.status_code == 200
    assert run_before.json()["status"] == "failed"

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": task_id, "additional_attempts": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] == "paused"
    assert data["pause_reason"] == "recovered"


async def test_recover_run_conflict_when_active(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/recover", json={"target_task_id": task_id})
    assert response.status_code == 409


async def test_recover_run_succeeds_when_paused(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Recovery is allowed on PAUSED runs (e.g., a task failed while the run was paused)."""
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/recover", json={"target_task_id": task_id})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "paused"
    assert data["pause_reason"] == "recovered"


async def test_recover_run_conflict_when_completed(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _drive_run_to_completed(client, drain)
    run_before = await client.get(f"/api/runs/{run_id}")
    assert run_before.status_code == 200
    assert run_before.json()["status"] == "completed"

    response = await client.post(f"/api/runs/{run_id}/recover", json={"target_task_id": task_id})
    assert response.status_code == 409


async def test_recover_run_not_found_when_run_missing(client: AsyncClient) -> None:
    response = await client.post(
        "/api/runs/nonexistent/recover",
        json={"target_task_id": "any-task-id"},
    )
    assert response.status_code == 404


async def test_recover_run_not_found_when_target_task_missing(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    run_id, _task_id = await _drive_run_to_failed(client, drain)

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": "missing-task-id"},
    )
    assert response.status_code == 404


async def test_resume_with_agent_change(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Resume a paused run while changing the agent type and config."""
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    # Set initial agent
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-2",
            "branch": "main",
            "agent_type": "cli_subprocess",
            "agent_config": {"callback_channel": "mcp"},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Start and pause the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    # Resume with a different agent
    response = await client.post(
        f"/api/runs/{run_id}/resume",
        json={
            "agent_type": "user_managed",
            "agent_config": {"timeout_minutes": 30},
        },
    )
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()

    # Verify the run is active with new agent
    assert data["status"] == "active"
    assert data["agent_type"] == "user_managed"
    assert data["agent_config"] == {"timeout_minutes": 30}

    # Verify the agent change event was emitted
    events_response = await client.get(f"/api/runs/{run_id}/activity")
    assert events_response.status_code == 200
    events = events_response.json()["events"]

    # Find the agent_changed event
    agent_changed_events = [e for e in events if e["event_type"] == "agent_changed"]
    assert len(agent_changed_events) == 1
    event = agent_changed_events[0]
    assert event["payload"]["old_agent"] == "cli_subprocess"
    assert event["payload"]["new_agent"] == "user_managed"
    assert event["payload"]["old_agent_config"] == {"callback_channel": "mcp"}
    assert event["payload"]["new_agent_config"] == {"timeout_minutes": 30}


async def test_resume_without_agent_change(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Resume a paused run without changing the agent (no body or empty body)."""
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    # Set initial agent
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-3",
            "branch": "main",
            "agent_type": "cli_subprocess",
            "agent_config": {"stdin_mode": "open"},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Start and pause the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    # Resume without changing agent (no request body)
    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()

    # Verify the run is active with the same agent
    assert data["status"] == "active"
    assert data["agent_type"] == "cli_subprocess"
    assert data["agent_config"] == {"stdin_mode": "open"}

    # Verify no agent_changed event was emitted
    events_response = await client.get(f"/api/runs/{run_id}/activity")
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    agent_changed_events = [e for e in events if e["event_type"] == "agent_changed"]
    assert len(agent_changed_events) == 0


async def test_resume_with_config_only_change(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Resume a paused run while changing only the agent config (not the type)."""
    client, drain = client_and_drain
    # Create a run with initial agent config
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-4",
            "branch": "main",
            "agent_type": "cli_subprocess",
            "agent_config": {"stdin_mode": "close", "model": "gpt-4"},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Start and pause the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    # Resume with updated config only (no agent_type change)
    response = await client.post(
        f"/api/runs/{run_id}/resume",
        json={
            "agent_config": {"stdin_mode": "open", "model": "claude-3"},
        },
    )
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()

    # Verify the run is active with same agent type but updated config
    assert data["status"] == "active"
    assert data["agent_type"] == "cli_subprocess"
    assert data["agent_config"] == {"stdin_mode": "open", "model": "claude-3"}

    # Verify the agent change event was emitted (config changed even though type didn't)
    events_response = await client.get(f"/api/runs/{run_id}/activity")
    assert events_response.status_code == 200
    events = events_response.json()["events"]

    # Find the agent_changed event
    agent_changed_events = [e for e in events if e["event_type"] == "agent_changed"]
    assert len(agent_changed_events) == 1
    event = agent_changed_events[0]
    assert event["payload"]["old_agent"] == "cli_subprocess"
    assert event["payload"]["new_agent"] == "cli_subprocess"
    assert event["payload"]["old_agent_config"] == {"stdin_mode": "close", "model": "gpt-4"}
    assert event["payload"]["new_agent_config"] == {"stdin_mode": "open", "model": "claude-3"}


async def test_create_run_with_agent_config(client: AsyncClient) -> None:
    """agent_config is stored and returned in the response."""
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
            "agent_type": "cli_subprocess",
            "agent_config": {"model": "claude-4", "callback_channel": "mcp"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_type"] == "cli_subprocess"
    assert data["agent_config"]["model"] == "claude-4"
    assert data["agent_config"]["callback_channel"] == "mcp"


async def test_create_run_agent_config_defaults_to_empty(client: AsyncClient) -> None:
    """agent_config defaults to empty dict when not provided."""
    data = await _create_run(client)
    assert data["agent_config"] == {}


# --- B2: cancel_run and recent_hours tests ---


async def test_cancel_run_from_active(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Cancel an active run -> FAILED."""
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "failed"
    assert data["completed_at"] is not None


async def test_cancel_run_from_paused(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Cancel a paused run -> FAILED."""
    client, drain = client_and_drain
    created = await _create_run(client)
    run_id = created["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "failed"
    assert data["completed_at"] is not None


async def test_cancel_run_from_draft_invalid(client: AsyncClient) -> None:
    """Cancel from DRAFT returns 409."""
    created = await _create_run(client)
    run_id = created["id"]

    response = await client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 409


async def test_cancel_run_not_found(client: AsyncClient) -> None:
    """Cancel a nonexistent run returns 404."""
    response = await client.post("/api/runs/nonexistent/cancel")
    assert response.status_code == 404


async def test_list_runs_recent_hours(client: AsyncClient) -> None:
    """recent_hours filter returns recently created runs."""
    await _create_run(client)

    # All runs were just created, so recent_hours=1 should return them
    response = await client.get("/api/runs?recent_hours=1")
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    # recent_hours=0 might return nothing (cutoff is exactly now)
    # but we can't control time precisely, so just verify the param is accepted
    response = await client.get("/api/runs?recent_hours=24")
    assert response.status_code == 200
    assert len(response.json()["runs"]) >= 1


# --- E1: Embedded routine tests ---

EMBEDDED_ROUTINE: dict[str, Any] = {
    "id": "embedded-test",
    "name": "Embedded Test Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Do the embedded thing",
                    "requirements": [{"id": "R1", "desc": "It works"}],
                }
            ],
        }
    ],
}


async def test_create_run_with_embedded_routine(client: AsyncClient) -> None:
    """Create a run using an inline embedded routine dict."""
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-embedded",
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_name"] == "proj-embedded"
    assert data["routine_id"] == "embedded-test"
    assert data["routine_source"] == "embedded"
    assert data["routine_embedded"] == EMBEDDED_ROUTINE
    assert data["status"] == "draft"
    assert len(data["steps"]) == 1
    assert len(data["steps"][0]["tasks"]) == 1
    assert data["steps"][0]["config_id"] == "S-01"
    assert data["steps"][0]["tasks"][0]["config_id"] == "T-01"


async def test_create_run_embedded_routine_persisted(client: AsyncClient) -> None:
    """Embedded routine is persisted and returned on GET."""
    create_resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-embedded",
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["routine_embedded"] == EMBEDDED_ROUTINE
    assert data["routine_source"] == "embedded"


async def test_create_run_both_routine_id_and_embedded_fails(client: AsyncClient) -> None:
    """Providing both routine_id and routine_embedded returns 422."""
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert response.status_code == 422


async def test_create_run_neither_routine_id_nor_embedded_fails(client: AsyncClient) -> None:
    """Providing neither routine_id nor routine_embedded returns 422."""
    response = await client.post(
        "/api/runs",
        json={"repo_name": "proj-1", "branch": "main"},
    )
    assert response.status_code == 422


async def test_create_run_embedded_routine_invalid_schema(client: AsyncClient) -> None:
    """Embedded routine with invalid schema returns 422."""
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-1",
            "branch": "main",
            "routine_embedded": {"id": "bad", "name": "Bad"},
            # Missing required 'steps' field
        },
    )
    assert response.status_code == 422


async def test_create_run_embedded_routine_with_ref_rejected(client: AsyncClient) -> None:
    """Embedded routine containing 'ref' key is rejected by RoutineConfig validator."""
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-1",
            "branch": "main",
            "routine_embedded": {
                "id": "bad-ref",
                "name": "Bad Ref Routine",
                "ref": "some-template",
                "steps": [
                    {
                        "id": "S-01",
                        "title": "Step",
                        "tasks": [
                            {
                                "id": "T-01",
                                "title": "Task",
                                "task_context": "Context",
                            }
                        ],
                    }
                ],
            },
        },
    )
    assert response.status_code == 422


async def test_create_run_embedded_with_config(client: AsyncClient) -> None:
    """Embedded routine run can include runtime config."""
    routine_with_inputs: dict[str, Any] = {
        "id": "with-inputs",
        "name": "Routine With Inputs",
        "inputs": [
            {"name": "target_branch", "required": True},
        ],
        "steps": [
            {
                "id": "S-01",
                "title": "Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task",
                        "task_context": "Deploy to branch",
                        "requirements": [{"id": "R1", "desc": "Deployed"}],
                    }
                ],
            }
        ],
    }
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-1",
            "branch": "main",
            "routine_embedded": routine_with_inputs,
            "config": {"target_branch": "main"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["config"]["target_branch"] == "main"


async def test_create_run_embedded_missing_required_input(client: AsyncClient) -> None:
    """Embedded routine with missing required input returns 422."""
    routine_with_inputs: dict[str, Any] = {
        "id": "with-inputs",
        "name": "Routine With Inputs",
        "inputs": [
            {"name": "target_branch", "required": True},
        ],
        "steps": [
            {
                "id": "S-01",
                "title": "Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task",
                        "task_context": "Deploy to branch",
                    }
                ],
            }
        ],
    }
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-1",
            "branch": "main",
            "routine_embedded": routine_with_inputs,
            # No config with target_branch
        },
    )
    assert response.status_code == 422


async def test_run_response_includes_cost_estimation(client: AsyncClient) -> None:
    """Test that cost estimation is populated when token data exists."""
    data = await _create_run(client)
    run_id = data["id"]

    # Initially, no tokens, so no cost estimate
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["total_tokens_read"] == 0
    assert data["total_tokens_write"] == 0
    assert data["estimated_cost_usd"] is None
    assert data["cost_disclaimer"] is None

    # Simulate task execution by updating the run state with token data
    from orchestrator.db import RunRepository

    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    session_factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.total_tokens_read = 100000
        run.total_tokens_write = 50000
        run.total_tokens_cache = 10000
        await repo.save(run)
        await session.commit()

    # Now fetch the run again
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()

    # Should now have cost estimation
    assert data["total_tokens_read"] == 100000
    assert data["total_tokens_write"] == 50000
    assert data["total_tokens_cache"] == 10000
    assert data["estimated_cost_usd"] is not None
    assert data["estimated_cost_usd"] > 0
    assert data["cost_disclaimer"] is not None
    assert "gpt-4o" in data["cost_disclaimer"]
    assert "Estimate only" in data["cost_disclaimer"]


# --- Agent error handler tests ---


async def test_agent_error_handlers_registered(client: AsyncClient) -> None:
    """Verify that agent error handlers are registered in the FastAPI app.

    Note: These handlers return specific HTTP status codes:
    - AgentNotAvailableError -> 503 Service Unavailable
    - AgentExecutionError -> 500 Internal Server Error
    - AgentCancelledError -> 499 Client Closed Request

    However, these errors are raised during agent.execute() calls, which happen
    outside the API request/response cycle. The current architecture does not
    have API endpoints that directly execute agents (agents are executed
    externally or via background tasks).

    This test verifies the handlers exist but cannot trigger them through the API.
    Full end-to-end testing would require:
    1. An endpoint that triggers agent execution synchronously, OR
    2. A background task system that can propagate exceptions to API responses

    For now, we verify handler registration and document the gap.
    """
    from orchestrator.runners.errors import (
        AgentCancelledError,
        AgentExecutionError,
        AgentNotAvailableError,
    )

    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]

    # Verify error handlers are registered
    error_handlers = app.exception_handlers

    # Check that our agent error types have handlers
    assert AgentNotAvailableError in error_handlers
    assert AgentExecutionError in error_handlers
    assert AgentCancelledError in error_handlers
