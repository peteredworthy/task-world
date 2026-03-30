"""Parity test: linear two-step workflow with three tasks.

Captures current orchestrator behaviour as a regression baseline.
Covers: run creation → start → build → submit → verify → complete for
each task across two steps, asserting run.status, run.current_step_index,
task.status, and attempt counts at every meaningful stage.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# ---------------------------------------------------------------------------
# Embedded routine: 2 steps, 3 tasks
# ---------------------------------------------------------------------------

LINEAR_ROUTINE: dict[str, Any] = {
    "id": "parity-linear",
    "name": "Parity Linear Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Do task one",
                    "requirements": [{"id": "R1", "desc": "Requirement 1"}],
                }
            ],
        },
        {
            "id": "S-02",
            "title": "Step Two",
            "tasks": [
                {
                    "id": "T-02",
                    "title": "Task Two",
                    "task_context": "Do task two",
                    "requirements": [{"id": "R1", "desc": "Requirement 1"}],
                },
                {
                    "id": "T-03",
                    "title": "Task Three",
                    "task_context": "Do task three",
                    "requirements": [{"id": "R1", "desc": "Requirement 1"}],
                },
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_run(client: AsyncClient) -> dict[str, Any]:
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": LINEAR_ROUTINE,
            "repo_name": "parity-linear-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


async def _start_run(
    client: AsyncClient, run_id: str, drain: DrainFn | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202, f"Failed to start run: {resp.text}"
    if drain is not None:
        await drain(run_id)
    resp2 = await client.get(f"/api/runs/{run_id}")
    assert resp2.status_code == 200
    return resp2.json()


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


async def _get_task(client: AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    return resp.json()


async def _complete_task(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn, req_id: str = "R1"
) -> None:
    """Drive a task through the full build → verify → complete cycle."""
    # Start
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["new_status"] == "building"

    # Mark checklist done
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}",
        json={"status": "done"},
    )
    assert resp.status_code == 200

    # Submit (now returns 200)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    # Grade
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
        json={"grade": "A", "grade_reason": "Looks good"},
    )
    assert resp.status_code == 200

    # Complete verification (now returns 200)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_linear_run_structure(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Run created with 2 steps and 3 tasks in the expected layout."""
    client, _drain = client_and_drain
    run = await _create_run(client)

    assert run["status"] == "draft"
    assert len(run["steps"]) == 2, "Expected 2 steps"
    assert len(run["steps"][0]["tasks"]) == 1, "Step 1 should have 1 task"
    assert len(run["steps"][1]["tasks"]) == 2, "Step 2 should have 2 tasks"
    assert run["current_step_index"] == 0


async def test_linear_run_starts_active(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Run transitions to active and lands on step 0 after start."""
    client, _drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]

    started = await _start_run(client, run_id, drain=_drain)
    assert started["status"] == "active"
    assert started["current_step_index"] == 0


async def test_linear_task_status_transitions(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Task status progresses: pending → building → verifying → completed."""
    client, drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    await _start_run(client, run_id, drain=drain)

    # Initially pending
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "pending"

    # After start: building, first attempt created
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "building"
    assert task["current_attempt"] == 1
    assert len(task["attempts"]) == 1

    # After submit: verifying
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "verifying"

    # After complete-verification with grade A: completed
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "completed"
    assert task["attempts"][0]["outcome"] == "passed"


async def test_linear_step_advances_after_step1_complete(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """current_step_index advances from 0 to 1 after step 1 completes."""
    client, drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]

    await _start_run(client, run_id, drain=drain)

    # Step 0 is current
    r = await _get_run(client, run_id)
    assert r["current_step_index"] == 0

    await _complete_task(client, run_id, task1_id, drain)

    # Step should have advanced
    r = await _get_run(client, run_id)
    assert r["current_step_index"] == 1, "Should advance to step index 1 after step 1 completes"
    assert r["steps"][0]["completed"] is True


async def test_linear_full_workflow_completes_run(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Full 3-task linear run: all tasks done, run status == completed."""
    client, drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    task2_id = run["steps"][1]["tasks"][0]["id"]
    task3_id = run["steps"][1]["tasks"][1]["id"]

    await _start_run(client, run_id, drain=drain)

    # Complete step 1
    await _complete_task(client, run_id, task1_id, drain)

    r = await _get_run(client, run_id)
    assert r["status"] == "active", "Run should remain active after step 1"
    assert r["current_step_index"] == 1

    # Complete step 2 task 1
    await _complete_task(client, run_id, task2_id, drain)

    r = await _get_run(client, run_id)
    assert r["status"] == "active", "Run still active with one step-2 task remaining"

    # Complete step 2 task 2 → run should complete
    await _complete_task(client, run_id, task3_id, drain)

    r = await _get_run(client, run_id)
    assert r["status"] == "completed"
    assert r["completed_at"] is not None
    assert r["steps"][0]["completed"] is True
    assert r["steps"][1]["completed"] is True

    # All tasks completed with one attempt each
    for task_id in (task1_id, task2_id, task3_id):
        t = await _get_task(client, run_id, task_id)
        assert t["status"] == "completed"
        assert t["current_attempt"] == 1
        assert len(t["attempts"]) == 1
