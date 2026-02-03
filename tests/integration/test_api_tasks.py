"""Integration tests for task API endpoints."""

from pathlib import Path

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def _setup_active_run(client: AsyncClient) -> tuple[str, str]:
    """Create a run and start it, returning (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "project_id": "proj-1"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    return run_id, task_id


async def test_get_task(client: AsyncClient) -> None:
    run_id, task_id = await _setup_active_run(client)

    response = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task_id
    assert data["status"] == "pending"
    assert len(data["checklist"]) == 1
    assert data["checklist"][0]["req_id"] == "R1"
    assert data["max_attempts"] == 3


async def test_get_task_not_found(client: AsyncClient) -> None:
    run_id, _ = await _setup_active_run(client)
    response = await client.get(f"/api/runs/{run_id}/tasks/nonexistent")
    assert response.status_code == 404


async def test_full_task_lifecycle(client: AsyncClient) -> None:
    """Full lifecycle: start -> checklist update -> submit -> grade -> complete."""
    run_id, task_id = await _setup_active_run(client)

    # Start task
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["new_status"] == "building"

    # Verify task is now building
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "building"
    assert len(resp.json()["attempts"]) == 1

    # Update checklist item
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done", "note": "Completed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["note"] == "Completed"

    # Submit for verification
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["new_status"] == "verifying"

    # Set grade
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Well done"},
    )
    assert resp.status_code == 200
    assert resp.json()["grade"] == "A"

    # Complete verification
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["new_status"] == "completed"


async def test_gate_failure_response(client: AsyncClient) -> None:
    """Submit with open checklist item should fail."""
    run_id, task_id = await _setup_active_run(client)

    # Start task
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Submit without completing checklist
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["new_status"] == "building"


async def test_revision_cycle(client: AsyncClient) -> None:
    """Fail verification with bad grade, then retry and pass."""
    run_id, task_id = await _setup_active_run(client)

    # Attempt 1: start, submit, fail verification
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "D", "grade_reason": "Poor"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.json()["new_status"] == "building"  # Revision

    # Attempt 2: submit again with better grade
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.json()["new_status"] == "completed"


async def test_checklist_not_found(client: AsyncClient) -> None:
    run_id, task_id = await _setup_active_run(client)
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/NONEXISTENT",
        json={"status": "done"},
    )
    assert resp.status_code == 404


async def test_grade_not_found(client: AsyncClient) -> None:
    run_id, task_id = await _setup_active_run(client)
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/NONEXISTENT/grade",
        json={"grade": "A"},
    )
    assert resp.status_code == 404


async def test_run_not_found_for_task(client: AsyncClient) -> None:
    resp = await client.get("/api/runs/nonexistent/tasks/whatever")
    assert resp.status_code == 404
