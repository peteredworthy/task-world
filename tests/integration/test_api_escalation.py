"""Integration tests for requirement escalation API endpoint."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, signal_transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    c, _ = client_and_drain
    return c


async def _setup_building_task(client: AsyncClient) -> tuple[str, str]:
    """Create a run, start it, and start the task. Returns (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert resp.status_code == 201
    data = resp.json()
    run_id = data["id"]
    task_id = data["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    return run_id, task_id


async def test_escalate_pauses_run_and_marks_requirement(client: AsyncClient) -> None:
    """POST escalation marks requirement as escalated and pauses the run."""
    run_id, task_id = await _setup_building_task(client)

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/escalate",
        json={"requirement_id": "R1", "reason": "Cannot find the relevant API"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "escalated"
    assert data["pause_reason"] == "requirement_escalated"

    # Run should now be PAUSED
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["status"] == "paused"
    assert run_data["pause_reason"] == "requirement_escalated"

    # The requirement should be marked escalated
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.status_code == 200
    checklist = task_resp.json()["checklist"]
    r1 = next(item for item in checklist if item["req_id"] == "R1")
    assert r1["status"] == "escalated"
    assert r1["note"] == "Cannot find the relevant API"


async def test_escalation_resume_after_human_intervention(client: AsyncClient) -> None:
    """After escalation, human resumes run; then can modify requirement (run is active again)."""
    run_id, task_id = await _setup_building_task(client)

    # Agent escalates a requirement
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/escalate",
        json={"requirement_id": "R1", "reason": "Blocked by external dependency"},
    )
    assert resp.status_code == 200

    # Confirm run is paused with correct reason
    run_resp = await client.get(f"/api/runs/{run_id}")
    run_data = run_resp.json()
    assert run_data["status"] == "paused"
    assert run_data["pause_reason"] == "requirement_escalated"

    # Human resumes the run
    resume_resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "active"

    # Now that the run is active again, human can modify the escalated requirement
    patch_resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "not_applicable", "note": "Skipped by human reviewer"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "not_applicable"


async def test_escalation_on_completed_run_returns_409(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Escalation on a completed run returns 409 InvalidTransition."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_building_task(client)

    # Complete the full lifecycle: building -> verifying -> completed
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert submit_resp.status_code == 202
    await drain(run_id)
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    complete_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert complete_resp.status_code == 202
    await drain(run_id)

    # Run is now completed (or at minimum the task is completed and run may be too)
    # Cancel the run to put it in a terminal state we can test
    # Actually let's verify the run completed naturally after the task completed
    run_resp = await client.get(f"/api/runs/{run_id}")
    run_status = run_resp.json()["status"]
    # The run should be in a non-ACTIVE state (completed or similar)
    assert run_status != "active"

    # Now try to escalate — should fail since run is not ACTIVE
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/escalate",
        json={"requirement_id": "R1", "reason": "Too late"},
    )
    assert resp.status_code == 409


async def test_escalation_on_nonexistent_task_returns_404(client: AsyncClient) -> None:
    """Escalation with a nonexistent task_id returns 404."""
    run_id, _ = await _setup_building_task(client)

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/nonexistent-task/escalate",
        json={"requirement_id": "R1", "reason": "Test"},
    )
    assert resp.status_code == 404


async def test_escalation_on_nonexistent_requirement_returns_404(client: AsyncClient) -> None:
    """Escalation with a nonexistent requirement_id returns 404."""
    run_id, task_id = await _setup_building_task(client)

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/escalate",
        json={"requirement_id": "R999", "reason": "Test"},
    )
    assert resp.status_code == 404
