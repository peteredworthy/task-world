"""Integration tests for backward transition API."""

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


async def test_transition_backward_basic(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Test basic backward transition to earlier step."""
    client, drain = client_and_drain
    # Create a run with 3 steps
    routine = {
        "id": "test-routine",
        "name": "Test Routine",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                        "task_context": "Context 1",
                        "requirements": [{"id": "req-1", "desc": "Requirement 1"}],
                    }
                ],
            },
            {
                "id": "step-2",
                "title": "Step 2",
                "tasks": [
                    {
                        "id": "task-2",
                        "title": "Task 2",
                        "task_context": "Context 2",
                        "requirements": [{"id": "req-2", "desc": "Requirement 2"}],
                    }
                ],
            },
            {
                "id": "step-3",
                "title": "Step 3",
                "tasks": [
                    {
                        "id": "task-3",
                        "title": "Task 3",
                        "task_context": "Context 3",
                        "requirements": [{"id": "req-3", "desc": "Requirement 3"}],
                    }
                ],
            },
        ],
    }

    # Create run
    create_resp = await client.post(
        "/api/runs",
        json={"routine_embedded": routine, "repo_name": "/tmp/test-project", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run_data = create_resp.json()
    run_id = run_data["id"]

    # Start the run
    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)

    # Start task 1 and complete it to progress step 0
    task1_id = run_data["steps"][0]["tasks"][0]["id"]
    await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/start")
    # Mark requirement done
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task1_id}/checklist/req-1",
        json={"status": "done"},
    )
    # Submit for verification
    submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/submit")
    assert submit_resp.status_code == 200
    await drain(run_id)
    # Set grade and complete
    await client.put(
        f"/api/runs/{run_id}/tasks/{task1_id}/checklist/req-1/grade",
        json={"grade": "A"},
    )
    complete_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/complete-verification")
    assert complete_resp.status_code == 200
    await drain(run_id)

    # Check we're now at step 1
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.json()["current_step_index"] == 1

    # Transition backward to step 0
    backward_resp = await client.post(
        f"/api/runs/{run_id}/transition-back",
        json={"target_step_index": 0, "reason": "Need to revise earlier work"},
    )
    assert backward_resp.status_code == 200
    backward_data = backward_resp.json()

    assert backward_data["current_step_index"] == 0
    # Steps should be marked not completed
    assert backward_data["steps"][0]["completed"] is False
    assert backward_data["steps"][1]["completed"] is False
    # First task should remain completed since it finished
    assert backward_data["steps"][0]["tasks"][0]["status"] == "completed"


async def test_transition_backward_invalid_target_out_of_bounds(client: AsyncClient) -> None:
    """Test backward transition with out of bounds target."""
    # Create a run with 2 steps
    routine = {
        "id": "test-routine",
        "name": "Test Routine",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                        "task_context": "Context 1",
                        "requirements": [{"id": "req-1", "desc": "Requirement 1"}],
                    }
                ],
            },
            {
                "id": "step-2",
                "title": "Step 2",
                "tasks": [
                    {
                        "id": "task-2",
                        "title": "Task 2",
                        "task_context": "Context 2",
                        "requirements": [{"id": "req-2", "desc": "Requirement 2"}],
                    }
                ],
            },
        ],
    }

    create_resp = await client.post(
        "/api/runs",
        json={"routine_embedded": routine, "repo_name": "/tmp/test-project", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # Try to transition to invalid index (5 is out of bounds)
    backward_resp = await client.post(
        f"/api/runs/{run_id}/transition-back", json={"target_step_index": 5}
    )
    assert backward_resp.status_code == 409


async def test_transition_backward_invalid_target_forward(client: AsyncClient) -> None:
    """Test that transitioning forward is rejected."""
    # Create a run with 2 steps
    routine = {
        "id": "test-routine",
        "name": "Test Routine",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                        "task_context": "Context 1",
                        "requirements": [{"id": "req-1", "desc": "Requirement 1"}],
                    }
                ],
            },
            {
                "id": "step-2",
                "title": "Step 2",
                "tasks": [
                    {
                        "id": "task-2",
                        "title": "Task 2",
                        "task_context": "Context 2",
                        "requirements": [{"id": "req-2", "desc": "Requirement 2"}],
                    }
                ],
            },
        ],
    }

    create_resp = await client.post(
        "/api/runs",
        json={"routine_embedded": routine, "repo_name": "/tmp/test-project", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # Current step is 0, try to transition to 1 (forward, should fail)
    backward_resp = await client.post(
        f"/api/runs/{run_id}/transition-back", json={"target_step_index": 1}
    )
    assert backward_resp.status_code == 409


async def test_transition_backward_event_emitted(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Test that backward transition emits proper event."""
    client, drain = client_and_drain
    # Create a run with 2 steps
    routine = {
        "id": "test-routine",
        "name": "Test Routine",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                        "task_context": "Context 1",
                        "requirements": [{"id": "req-1", "desc": "Requirement 1"}],
                    }
                ],
            },
            {
                "id": "step-2",
                "title": "Step 2",
                "tasks": [
                    {
                        "id": "task-2",
                        "title": "Task 2",
                        "task_context": "Context 2",
                        "requirements": [{"id": "req-2", "desc": "Requirement 2"}],
                    }
                ],
            },
        ],
    }

    create_resp = await client.post(
        "/api/runs",
        json={"routine_embedded": routine, "repo_name": "/tmp/test-project", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run_data = create_resp.json()
    run_id = run_data["id"]

    # Start and complete step 0
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    task1_id = run_data["steps"][0]["tasks"][0]["id"]
    await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task1_id}/checklist/req-1",
        json={"status": "done"},
    )
    submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/submit")
    assert submit_resp.status_code == 200
    await drain(run_id)
    await client.put(
        f"/api/runs/{run_id}/tasks/{task1_id}/checklist/req-1/grade",
        json={"grade": "A"},
    )
    complete_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/complete-verification")
    assert complete_resp.status_code == 200
    await drain(run_id)

    # Transition backward
    backward_resp = await client.post(
        f"/api/runs/{run_id}/transition-back",
        json={"target_step_index": 0, "reason": "Revision needed"},
    )
    assert backward_resp.status_code == 200

    # Check activity log for backward transition event
    activity_resp = await client.get(f"/api/runs/{run_id}/activity")
    assert activity_resp.status_code == 200
    activity_data = activity_resp.json()

    # Find the backward transition event
    backward_events = [e for e in activity_data["events"] if e["event_type"] == "run_step_backward"]
    assert len(backward_events) == 1
    event = backward_events[0]
    assert event["payload"]["from_step_index"] == 1
    assert event["payload"]["to_step_index"] == 0
    assert event["payload"]["reason"] == "Revision needed"
