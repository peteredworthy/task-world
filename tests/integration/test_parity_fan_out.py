"""Parity test: fan-out step (multiple parallel child tasks).

Captures current orchestrator behaviour as a regression baseline.
Covers: a step containing multiple tasks (fan-out style); each child task
is completed in order; the parent step is marked completed only after all
children finish; the run then advances past the fan-out step.

Note: This test uses an embedded routine with multiple tasks in a single
step (the simplest form of "fan-out" that the orchestrator supports natively
via the API, without requiring filesystem glob expansion).
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# Routine: Step 1 has a single setup task; Step 2 has 3 child tasks (fan-out).
# Step 3 is the combine/finalise step after the fan-out.
FAN_OUT_ROUTINE: dict[str, Any] = {
    "id": "parity-fan-out",
    "name": "Parity Fan-Out Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Setup",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Setup Task",
                    "task_context": "Prepare the work",
                    "requirements": [{"id": "R1", "desc": "Setup done"}],
                }
            ],
        },
        {
            "id": "S-02",
            "title": "Fan-Out Processing",
            "tasks": [
                {
                    "id": "T-02",
                    "title": "Child Task A",
                    "task_context": "Process item A",
                    "requirements": [{"id": "R1", "desc": "Item A processed"}],
                },
                {
                    "id": "T-03",
                    "title": "Child Task B",
                    "task_context": "Process item B",
                    "requirements": [{"id": "R1", "desc": "Item B processed"}],
                },
                {
                    "id": "T-04",
                    "title": "Child Task C",
                    "task_context": "Process item C",
                    "requirements": [{"id": "R1", "desc": "Item C processed"}],
                },
            ],
        },
        {
            "id": "S-03",
            "title": "Combine",
            "tasks": [
                {
                    "id": "T-05",
                    "title": "Combine Results",
                    "task_context": "Combine all processed items",
                    "requirements": [{"id": "R1", "desc": "Combined"}],
                }
            ],
        },
    ],
}


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


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


async def _get_task(client: AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    return resp.json()


async def _complete_task(
    client: AsyncClient, run_id: str, task_id: str, req_id: str = "R1"
) -> None:
    """Drive a task through the full build → verify → complete cycle."""
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200, f"start failed: {resp.text}"
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "completed"


async def test_fan_out_step_structure(client: AsyncClient) -> None:
    """Fan-out step contains exactly 3 child tasks at creation."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": FAN_OUT_ROUTINE,
            "repo_name": "parity-fan-out-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run = resp.json()

    assert len(run["steps"]) == 3
    assert len(run["steps"][1]["tasks"]) == 3, "Fan-out step should have 3 child tasks"
    assert run["steps"][1]["completed"] is False


async def test_fan_out_step_incomplete_while_children_pending(client: AsyncClient) -> None:
    """Fan-out step not completed while child tasks are still pending."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": FAN_OUT_ROUTINE,
            "repo_name": "parity-fan-out-partial-repo",
            "branch": "main",
        },
    )
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    child_a_id = run["steps"][1]["tasks"][0]["id"]
    child_b_id = run["steps"][1]["tasks"][1]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await _complete_task(client, run_id, task1_id)

    # Complete only first child
    await _complete_task(client, run_id, child_a_id)

    run_state = await _get_run(client, run_id)
    # current_step_index should still be on step index 1 (fan-out step)
    assert run_state["current_step_index"] == 1, (
        "Should still be on fan-out step while child tasks are incomplete"
    )
    assert run_state["steps"][1]["completed"] is False

    # Second child still pending
    task_b = await _get_task(client, run_id, child_b_id)
    assert task_b["status"] == "pending"


async def test_fan_out_step_completes_when_all_children_done(client: AsyncClient) -> None:
    """Fan-out step marked completed only after all child tasks finish."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": FAN_OUT_ROUTINE,
            "repo_name": "parity-fan-out-complete-repo",
            "branch": "main",
        },
    )
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    child_a_id = run["steps"][1]["tasks"][0]["id"]
    child_b_id = run["steps"][1]["tasks"][1]["id"]
    child_c_id = run["steps"][1]["tasks"][2]["id"]

    await client.post(f"/api/runs/{run_id}/start")

    # Complete setup step
    await _complete_task(client, run_id, task1_id)
    run_state = await _get_run(client, run_id)
    assert run_state["current_step_index"] == 1

    # Complete all fan-out children in order
    await _complete_task(client, run_id, child_a_id)
    await _complete_task(client, run_id, child_b_id)
    await _complete_task(client, run_id, child_c_id)

    # Fan-out step should now be completed and run should advance
    run_state = await _get_run(client, run_id)
    assert run_state["steps"][1]["completed"] is True, (
        "Fan-out step should be completed when all children finish"
    )
    assert run_state["current_step_index"] == 2, "Run should advance past the fan-out step"
    assert run_state["status"] == "active", "Run still active (combine step not done)"


async def test_fan_out_run_completes_after_all_steps(client: AsyncClient) -> None:
    """Full workflow: setup → fan-out (3 children) → combine → run completed."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": FAN_OUT_ROUTINE,
            "repo_name": "parity-fan-out-full-repo",
            "branch": "main",
        },
    )
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    child_a_id = run["steps"][1]["tasks"][0]["id"]
    child_b_id = run["steps"][1]["tasks"][1]["id"]
    child_c_id = run["steps"][1]["tasks"][2]["id"]
    combine_id = run["steps"][2]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")

    await _complete_task(client, run_id, task1_id)
    await _complete_task(client, run_id, child_a_id)
    await _complete_task(client, run_id, child_b_id)
    await _complete_task(client, run_id, child_c_id)
    await _complete_task(client, run_id, combine_id)

    run_state = await _get_run(client, run_id)
    assert run_state["status"] == "completed"
    assert run_state["completed_at"] is not None
    for step in run_state["steps"]:
        assert step["completed"] is True

    # All fan-out children completed with 1 attempt each
    for child_id in (child_a_id, child_b_id, child_c_id):
        task = await _get_task(client, run_id, child_id)
        assert task["status"] == "completed"
        assert task["current_attempt"] == 1
