"""Integration tests for task API endpoints."""

from pathlib import Path

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db
from orchestrator.workflow.signals import InMemorySignalTransport
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


async def _setup_active_run(client: AsyncClient) -> tuple[str, str]:
    """Create a run and start it, returning (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
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


async def test_full_task_lifecycle(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Full lifecycle: start -> checklist update -> submit -> grade -> complete."""
    client, drain = client_and_drain
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

    # Submit for verification (202 async) then drain
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    # Verify task is now verifying
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "verifying"

    # Set grade
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Well done"},
    )
    assert resp.status_code == 200
    assert resp.json()["grade"] == "A"

    # Complete verification (202 async) then drain
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    # Verify task is now completed
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "completed"


async def test_gate_failure_response(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Submit with open checklist item: 202 accepted, drain → run paused with gate_blocked."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client)

    # Start task
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Submit without completing checklist — accepted (202)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202

    # Drain signals — GateBlockedError causes run to pause
    await drain(run_id)

    # Run should be paused with gate_blocked reason
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.json()["status"] == "paused"
    assert run_resp.json()["pause_reason"] == "gate_blocked"


async def test_revision_cycle(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Fail verification with bad grade, then retry and pass."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client)

    # Attempt 1: start, submit, fail verification
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "D", "grade_reason": "Poor"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    # Task should be back in building (revision)
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "building"

    # Attempt 2: submit again with better grade
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "completed"


async def test_checklist_not_found(client: AsyncClient) -> None:
    run_id, task_id = await _setup_active_run(client)
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/NONEXISTENT",
        json={"status": "done"},
    )
    assert resp.status_code == 404


async def test_grade_not_found(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client)
    # Advance task to VERIFYING so set_grade guard passes
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/NONEXISTENT/grade",
        json={"grade": "A"},
    )
    assert resp.status_code == 404


async def test_flexible_req_id_formats_in_api(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """API should accept numeric req_id variants for checklist/grade endpoints."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client)

    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Numeric-only format should resolve to R1.
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/1",
        json={"status": "done"},
    )
    assert resp.status_code == 200
    assert resp.json()["req_id"] == "R1"

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    # Dashed format should resolve to R1.
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R-01/grade",
        json={"grade": "A", "grade_reason": "Flexible ID accepted"},
    )
    assert resp.status_code == 200
    assert resp.json()["req_id"] == "R1"


async def test_run_not_found_for_task(client: AsyncClient) -> None:
    resp = await client.get("/api/runs/nonexistent/tasks/whatever")
    assert resp.status_code == 404


async def test_prompt_returns_builder_when_building(client: AsyncClient) -> None:
    """Prompt endpoint returns builder prompt when task is in BUILDING state."""
    run_id, task_id = await _setup_active_run(client)

    # Start task -> BUILDING
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "building"
    assert "software developer" in data["system"].lower()
    assert "## Task" in data["user"]
    assert "## Requirements" in data["user"]


async def test_prompt_returns_verifier_when_verifying(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Prompt endpoint returns verifier prompt when task is in VERIFYING state."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client)

    # Start task -> BUILDING
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Complete checklist and submit -> drain -> VERIFYING
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "verifying"
    assert "code reviewer" in data["system"].lower()
    assert "## Requirements to Verify" in data["user"]


async def test_prompt_rejects_pending_task(client: AsyncClient) -> None:
    """Prompt endpoint returns 409 when task is in PENDING state."""
    run_id, task_id = await _setup_active_run(client)

    # Task is still PENDING (not started)
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "invalid_transition"
    assert data["from_status"] == "pending"


async def test_prompt_rejects_completed_task(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Prompt endpoint returns 409 when task is in COMPLETED state."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client)

    # Full lifecycle to reach COMPLETED
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    # Task is now COMPLETED
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "invalid_transition"
    assert data["from_status"] == "completed"


async def test_submit_with_unfinished_checklist_returns_409(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Submit task when checklist gate fails: 202 accepted, drain → run paused with gate_blocked."""
    client, drain = client_and_drain
    # 1. Create and start a run
    run_id, task_id = await _setup_active_run(client)

    # 2. Start the first task (status becomes BUILDING)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "building"

    # 3. DO NOT mark checklist items as done (checklist gate will fail)

    # 4. Submit — accepted (202) since processing is async
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202

    # 5. Drain signals — GateBlockedError causes run to pause
    await drain(run_id)

    # 6. Verify run is paused with gate_blocked reason
    run_resp = await client.get(f"/api/runs/{run_id}")
    data = run_resp.json()
    assert data["status"] == "paused"
    assert data["pause_reason"] == "gate_blocked"
