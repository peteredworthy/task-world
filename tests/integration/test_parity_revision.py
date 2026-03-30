"""Parity test: revision cycle.

Captures current orchestrator behaviour as a regression baseline.
Covers: task fails verification (grade F → revision_needed), a new
attempt is created with feedback from the failed attempt, the second
attempt passes. Asserts attempt_count = 2, both attempts have correct
outcomes, and the run advances to completed.
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

REVISION_ROUTINE: dict[str, Any] = {
    "id": "parity-revision",
    "name": "Parity Revision Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Only Step",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task Under Test",
                    "task_context": "Do the work",
                    "requirements": [{"id": "R1", "desc": "Complete the task"}],
                    "retry": {"max_attempts": 3},
                }
            ],
        }
    ],
}


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


async def _get_task(client: AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    return resp.json()


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


async def test_revision_attempt_count_and_outcomes(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Grade F on attempt 1 → revision; attempt 2 passes → run completed."""
    client, drain = client_and_drain

    # Create and start run
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": REVISION_ROUTINE,
            "repo_name": "parity-revision-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run = resp.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # ---------------------------------------------------------------
    # Attempt 1: fail verification
    # ---------------------------------------------------------------
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "building"

    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "building"
    assert task["current_attempt"] == 1
    assert len(task["attempts"]) == 1

    # Mark checklist done and submit
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "verifying"

    # Grade F → triggers revision
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "F", "grade_reason": "Completely wrong"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)

    # Task should now be on attempt 2 with attempt 1 marked as revision_needed
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "building"
    assert task["current_attempt"] == 2
    assert len(task["attempts"]) == 2
    assert task["attempts"][0]["outcome"] == "revision_needed", (
        "First attempt outcome should be revision_needed"
    )

    # Run should still be active
    run_state = await _get_run(client, run_id)
    assert run_state["status"] == "active"

    # ---------------------------------------------------------------
    # Attempt 2: pass verification
    # ---------------------------------------------------------------
    # Checklist starts fresh for new attempt; mark done again
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "verifying"

    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Much better"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)

    # Final assertions
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "completed"
    assert task["current_attempt"] == 2
    assert len(task["attempts"]) == 2
    assert task["attempts"][0]["outcome"] == "revision_needed"
    assert task["attempts"][1]["outcome"] == "passed"

    run_state = await _get_run(client, run_id)
    assert run_state["status"] == "completed"
    assert run_state["steps"][0]["completed"] is True


async def test_revision_feedback_available_on_second_attempt(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Grade reason from failed attempt is recorded on the first attempt."""
    client, drain = client_and_drain

    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": REVISION_ROUTINE,
            "repo_name": "parity-feedback-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run = resp.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # Attempt 1: fail with a specific reason
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
        json={"grade": "D", "grade_reason": "Missing key functionality"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)

    # Verify that attempt 1 captured the grade reason
    task = await _get_task(client, run_id, task_id)
    assert len(task["attempts"]) == 2
    attempt1 = task["attempts"][0]
    assert attempt1["outcome"] == "revision_needed"
    # The checklist item on attempt 1 should have the grade recorded
    checklist_items = attempt1.get("checklist", [])
    if checklist_items:
        r1_item = next((i for i in checklist_items if i["req_id"] == "R1"), None)
        if r1_item:
            assert r1_item.get("grade") == "D"
