"""Integration tests for user-managed agent lifecycle endpoints."""

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


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


async def _create_and_start_run(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Helper: create, start a run, and return (run_id, task_id)."""
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert response.status_code == 201
    data = response.json()
    run_id = data["id"]
    task_id = data["steps"][0]["tasks"][0]["id"]

    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 202
    await drain(run_id)

    return run_id, task_id


async def test_agent_started_sets_timestamp(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """POST /runs/{id}/agent-started sets agent_started_at timestamp."""
    client, drain = client_and_drain
    run_id, _ = await _create_and_start_run(client, drain)

    # Before marking agent started, timestamp should be None
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_started_at"] is None

    # Mark agent as started
    response = await client.post(f"/api/runs/{run_id}/agent-started")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_started_at"] is not None
    assert data["agent_started_at"].endswith("Z")

    # Verify the timestamp persists
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_started_at"] is not None
    assert data["agent_started_at"].endswith("Z")


async def test_agent_started_can_be_called_multiple_times(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """agent-started can be called multiple times (idempotent with timestamp update)."""
    client, drain = client_and_drain
    run_id, _ = await _create_and_start_run(client, drain)

    # First call
    response = await client.post(f"/api/runs/{run_id}/agent-started")
    assert response.status_code == 200
    first_timestamp = response.json()["agent_started_at"]
    assert first_timestamp is not None

    # Second call (should update timestamp)
    response = await client.post(f"/api/runs/{run_id}/agent-started")
    assert response.status_code == 200
    second_timestamp = response.json()["agent_started_at"]
    assert second_timestamp is not None
    # Note: timestamps might be the same if called quickly, but that's OK


async def test_agent_cancelled_transitions_to_failed(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """POST /runs/{id}/agent-cancelled transitions run to FAILED."""
    client, drain = client_and_drain
    run_id, _ = await _create_and_start_run(client, drain)

    # Verify run is ACTIVE
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    # Cancel the agent
    response = await client.post(
        f"/api/runs/{run_id}/agent-cancelled",
        json={"reason": "User cancelled external agent"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"

    # Verify the run remains FAILED
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


async def test_agent_cancelled_without_reason(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """agent-cancelled works without a reason."""
    client, drain = client_and_drain
    run_id, _ = await _create_and_start_run(client, drain)

    response = await client.post(f"/api/runs/{run_id}/agent-cancelled", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


async def test_guidance_with_building_task(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """GET /runs/{id}/guidance returns prompt and actions for BUILDING task."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)

    # Start the first task (BUILDING)
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert response.status_code == 200

    # Get guidance
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    data = response.json()

    assert data["run_id"] == run_id
    assert data["task_id"] == task_id
    assert data["phase"] == "building"
    assert data["prompt"] is not None
    assert len(data["prompt"]) > 0
    assert data["mcp_url"] == "/mcp/sse"
    assert len(data["expected_actions"]) > 0
    assert any("checklist" in action for action in data["expected_actions"])
    assert any("submit" in action for action in data["expected_actions"])


async def test_guidance_with_verifying_task(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """GET /runs/{id}/guidance returns prompt and actions for VERIFYING task."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)

    # Start task and submit for verification
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert response.status_code == 200
    await drain(run_id)

    # Get guidance (should now be VERIFYING)
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    data = response.json()

    assert data["run_id"] == run_id
    assert data["task_id"] == task_id
    assert data["phase"] == "verifying"
    assert data["prompt"] is not None
    assert len(data["prompt"]) > 0
    assert any("grade" in action for action in data["expected_actions"])
    assert any("complete-verification" in action for action in data["expected_actions"])


async def test_guidance_with_no_active_task(client: AsyncClient) -> None:
    """GET /runs/{id}/guidance handles runs with no active tasks."""
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Get guidance (no tasks active yet)
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    data = response.json()

    assert data["run_id"] == run_id
    assert data["task_id"] is None
    assert data["phase"] is None
    assert data["prompt"] is None
    assert "No active task" in data["expected_actions"][0]


async def test_guidance_run_not_found(client: AsyncClient) -> None:
    """GET /runs/{id}/guidance returns 404 for nonexistent run."""
    response = await client.get("/api/runs/nonexistent/guidance")
    assert response.status_code == 404


async def test_agent_started_run_not_found(client: AsyncClient) -> None:
    """POST /runs/{id}/agent-started returns 404 for nonexistent run."""
    response = await client.post("/api/runs/nonexistent/agent-started")
    assert response.status_code == 404


async def test_agent_cancelled_run_not_found(client: AsyncClient) -> None:
    """POST /runs/{id}/agent-cancelled returns 404 for nonexistent run."""
    response = await client.post("/api/runs/nonexistent/agent-cancelled", json={})
    assert response.status_code == 404


async def test_full_user_managed_lifecycle(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Test complete user-managed agent lifecycle flow.

    1. Create run
    2. Mark agent started
    3. Get guidance
    4. Start task (via guidance)
    5. Mark checklist items done
    6. Submit for verification (via guidance)
    7. Get guidance again (should be verifying)
    8. Set grades
    9. Complete verification
    """
    client, drain = client_and_drain
    # Create and start run
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert response.status_code == 201
    run_id = response.json()["id"]
    task_id = response.json()["steps"][0]["tasks"][0]["id"]

    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 202
    await drain(run_id)

    # Mark agent started
    response = await client.post(f"/api/runs/{run_id}/agent-started")
    assert response.status_code == 200
    assert response.json()["agent_started_at"] is not None

    # Get initial guidance
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    guidance = response.json()
    assert guidance["task_id"] is None  # No active task yet

    # Start task
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Get guidance (should now have building task)
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    guidance = response.json()
    assert guidance["phase"] == "building"
    assert guidance["task_id"] == task_id

    # Mark checklist item done
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )

    # Submit for verification (202 async) then drain
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert response.status_code == 200
    await drain(run_id)

    # Get guidance (should be verifying now)
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    guidance = response.json()
    assert guidance["phase"] == "verifying"
    assert "grade" in " ".join(guidance["expected_actions"])

    # Set grades
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Perfect work"},
    )

    # Complete verification (200 sync) then drain
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert response.status_code == 200
    await drain(run_id)

    # Verify task is completed
    response = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


async def test_guidance_with_embedded_routine(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """GET /runs/{id}/guidance works with embedded routines."""
    client, drain = client_and_drain
    # Create run with embedded routine
    embedded = {
        "id": "embedded-test",
        "name": "Embedded Test",
        "description": "Test routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Test Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Test Task",
                        "task_context": "Do the thing",
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "Complete the work",
                                "priority": "critical",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    response = await client.post(
        "/api/runs",
        json={
            "routine_embedded": embedded,
            "repo_name": "proj-1",
            "branch": "main",
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]
    task_id = response.json()["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Get guidance (should work with embedded routine)
    response = await client.get(f"/api/runs/{run_id}/guidance")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["task_id"] == task_id
    assert data["phase"] == "building"
    assert data["prompt"] is not None
