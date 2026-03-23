"""Tests for the skip step API endpoint for manual gates."""

from collections.abc import AsyncGenerator
from pathlib import Path

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
    """Create an async test client with in-memory database and signal drain."""
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
    """Backward-compatible fixture that returns just the client."""
    c, _ = client_and_drain
    return c


async def _create_run_with_manual_gate(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run with a manual gate condition on step 2."""
    routine_config = {
        "id": "test-manual-gate",
        "name": "test-manual-gate",
        "steps": [
            {
                "id": "step1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task1",
                        "title": "Task 1",
                        "instructions": "Build something",
                    }
                ],
            },
            {
                "id": "step2",
                "title": "Step 2",
                "condition": {"when": "manual"},
                "tasks": [
                    {
                        "id": "task2",
                        "title": "Task 2",
                        "instructions": "Build something else",
                    }
                ],
            },
        ],
    }

    # Create run
    create_resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "test-repo",
            "branch": "main",
            "routine_embedded": routine_config,
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # Start run
    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 200

    # Complete step 1
    task1_id = create_resp.json()["steps"][0]["tasks"][0]["id"]

    # Start task 1
    task_start_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/start")
    assert task_start_resp.status_code == 200

    # Submit task 1
    submit_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task1_id}/submit",
        json={
            "artifacts": [],
            "completion_reason": "Completed task",
        },
    )
    assert submit_resp.status_code == 202
    await drain(run_id)

    # Complete verification (auto-verify should pass)
    complete_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task1_id}/complete-verification",
        json={"passing_grades": []},
    )
    assert complete_resp.status_code == 202
    await drain(run_id)

    # Now check that run is paused at manual gate
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["status"] == "paused"
    assert run_data["pause_reason"] == "manual_gate"

    # Get step2 ID
    step2_id = run_data["steps"][1]["id"]

    return run_id, step2_id


@pytest.mark.asyncio
class TestSkipStepAPI:
    """Tests for POST /runs/{id}/steps/{step_id}/skip endpoint."""

    async def test_skip_manual_gate_step(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skip a step with manual gate condition."""
        client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate(client, drain)

        # Skip the manual gate step
        skip_resp = await client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        # Verify run is resumed or paused at next manual gate
        run_data = skip_resp.json()
        assert run_data["id"] == run_id

        # Step 2 should be marked as skipped
        assert run_data["steps"][1]["skipped"] is True
        assert run_data["steps"][1]["skip_reason"] == "manual_skip"
        assert run_data["steps"][1]["completed"] is True

    async def test_skip_returns_409_when_not_paused_at_manual_gate(
        self, client: AsyncClient
    ) -> None:
        """Return 409 when run is not paused at a manual gate."""
        # Create and start a normal run
        routine_config = {
            "id": "test-no-condition",
            "name": "test-no-condition",
            "steps": [
                {
                    "id": "step1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task1",
                            "title": "Task 1",
                            "instructions": "Build something",
                        }
                    ],
                }
            ],
        }

        create_resp = await client.post(
            "/api/runs",
            json={
                "repo_name": "test-repo",
                "branch": "main",
                "routine_embedded": routine_config,
            },
        )
        run_id = create_resp.json()["id"]
        step1_id = create_resp.json()["steps"][0]["id"]

        # Try to skip without pausing at manual gate
        skip_resp = await client.post(f"/api/runs/{run_id}/steps/{step1_id}/skip")
        assert skip_resp.status_code == 409
        assert "manual gate" in skip_resp.json()["detail"].lower()

    async def test_skip_returns_409_for_wrong_step_id(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Return 409 when step_id doesn't match current step."""
        client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate(client, drain)

        # Try to skip with wrong step ID
        skip_resp = await client.post(f"/api/runs/{run_id}/steps/wrong-step-id/skip")
        assert skip_resp.status_code == 409
        assert "not the current step" in skip_resp.json()["detail"].lower()

    async def test_skip_advances_to_next_step(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skipping a step advances current_step_index."""
        client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate(client, drain)

        # Check current_step_index before skip
        run_resp = await client.get(f"/api/runs/{run_id}")
        initial_index = run_resp.json()["current_step_index"]

        # Skip the manual gate step
        skip_resp = await client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        # Current step index should advance
        new_index = skip_resp.json()["current_step_index"]
        assert new_index > initial_index

    async def test_skip_handles_cascading_conditions(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skip can handle cascading conditions (skip multiple steps if needed)."""
        client, drain = client_and_drain
        routine_config = {
            "id": "test-cascade-conditions",
            "name": "test-cascade-conditions",
            "steps": [
                {
                    "id": "step1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task1",
                            "title": "Task 1",
                            "instructions": "Build something",
                        }
                    ],
                },
                {
                    "id": "step2",
                    "title": "Step 2",
                    "condition": {"when": "manual"},
                    "tasks": [
                        {
                            "id": "task2",
                            "title": "Task 2",
                            "instructions": "Build something else",
                        }
                    ],
                },
                {
                    "id": "step3",
                    "title": "Step 3",
                    "condition": {"when": "false"},
                    "tasks": [
                        {
                            "id": "task3",
                            "title": "Task 3",
                            "instructions": "Build third thing",
                        }
                    ],
                },
                {
                    "id": "step4",
                    "title": "Step 4",
                    "tasks": [
                        {
                            "id": "task4",
                            "title": "Task 4",
                            "instructions": "Build fourth thing",
                        }
                    ],
                },
            ],
        }

        # Create run
        create_resp = await client.post(
            "/api/runs",
            json={
                "repo_name": "test-repo",
                "branch": "main",
                "routine_embedded": routine_config,
            },
        )
        run_id = create_resp.json()["id"]

        # Start run
        start_resp = await client.post(f"/api/runs/{run_id}/start")
        assert start_resp.status_code == 200

        # Complete step 1
        task1_id = create_resp.json()["steps"][0]["tasks"][0]["id"]

        task_start_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/start")
        assert task_start_resp.status_code == 200

        submit_resp = await client.post(
            f"/api/runs/{run_id}/tasks/{task1_id}/submit",
            json={"artifacts": [], "completion_reason": "Completed task"},
        )
        assert submit_resp.status_code == 202
        await drain(run_id)

        complete_resp = await client.post(
            f"/api/runs/{run_id}/tasks/{task1_id}/complete-verification",
            json={"passing_grades": []},
        )
        assert complete_resp.status_code == 202
        await drain(run_id)

        # Now run is paused at step 2 (manual gate)
        run_resp = await client.get(f"/api/runs/{run_id}")
        run_data = run_resp.json()
        step2_id = run_data["steps"][1]["id"]

        # Skip step 2 - this should cascade and also skip step 3 (false condition)
        skip_resp = await client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        # Verify step 2 is skipped
        run_data = skip_resp.json()
        assert run_data["steps"][1]["skipped"] is True

        # Verify step 3 is also skipped (cascading condition evaluation)
        assert run_data["steps"][2]["skipped"] is True

        # Step 4 should be the current step (not skipped)
        assert run_data["steps"][3]["skipped"] is False
