"""Parity test: pause, resume, and cancel flows.

Captures current orchestrator behaviour as a regression baseline.
Covers:
  - Start run, pause with the default "manual_pause" reason
  - Assert run.status == paused and pause_reason persisted in the DB
  - Resume run and assert run.status == active
  - Cancel: start run, cancel, assert run.status == failed
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

SIMPLE_ROUTINE: dict[str, Any] = {
    "id": "parity-pause-resume",
    "name": "Parity Pause/Resume Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Only Step",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Only Task",
                    "task_context": "Do the thing",
                    "requirements": [{"id": "R1", "desc": "Task done"}],
                }
            ],
        }
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


async def _create_and_start_run(client: AsyncClient, repo: str = "parity-pause-repo") -> str:
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": SIMPLE_ROUTINE,
            "repo_name": repo,
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    return run_id


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Pause / resume tests
# ---------------------------------------------------------------------------


async def test_pause_sets_status_and_reason(client: AsyncClient) -> None:
    """Pausing an active run sets status=paused with pause_reason persisted."""
    run_id = await _create_and_start_run(client)

    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "paused"
    # The API pause endpoint uses "manual_pause" as the default reason
    assert data["pause_reason"] == "manual_pause"

    # Verify state persisted via GET
    run = await _get_run(client, run_id)
    assert run["status"] == "paused"
    assert run["pause_reason"] == "manual_pause"


async def test_resume_clears_paused_state(client: AsyncClient) -> None:
    """Resuming a paused run restores status=active and clears pause_reason."""
    run_id = await _create_and_start_run(client, repo="parity-resume-repo")

    await client.post(f"/api/runs/{run_id}/pause")

    resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"

    # Verify via GET
    run = await _get_run(client, run_id)
    assert run["status"] == "active"
    # pause_reason should be cleared on resume
    assert run["pause_reason"] is None


async def test_pause_resume_then_complete(client: AsyncClient) -> None:
    """Full workflow: start → pause → resume → complete task → run completed."""
    run_id = await _create_and_start_run(client, repo="parity-full-pause-repo")
    run_data = await _get_run(client, run_id)
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # Pause
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.json()["status"] == "paused"

    # Resume
    resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resp.json()["status"] == "active"

    # Complete the task
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")

    run = await _get_run(client, run_id)
    assert run["status"] == "completed"


async def test_pause_events_recorded(client: AsyncClient) -> None:
    """Pause and resume events appear in the activity log."""
    run_id = await _create_and_start_run(client, repo="parity-events-repo")

    await client.post(f"/api/runs/{run_id}/pause")
    await client.post(f"/api/runs/{run_id}/resume")

    resp = await client.get(f"/api/runs/{run_id}/activity")
    assert resp.status_code == 200
    event_types = [e["event_type"] for e in resp.json()["events"]]
    assert "run_status_changed" in event_types


# ---------------------------------------------------------------------------
# Cancel tests
# ---------------------------------------------------------------------------


async def test_cancel_active_run(client: AsyncClient) -> None:
    """Cancelling an active run sets status=failed."""
    run_id = await _create_and_start_run(client, repo="parity-cancel-repo")

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed", "Cancelled run should have status=failed"
    assert data["completed_at"] is not None

    run = await _get_run(client, run_id)
    assert run["status"] == "failed"


async def test_cancel_paused_run(client: AsyncClient) -> None:
    """Cancelling a paused run also sets status=failed."""
    run_id = await _create_and_start_run(client, repo="parity-cancel-paused-repo")

    await client.post(f"/api/runs/{run_id}/pause")
    run = await _get_run(client, run_id)
    assert run["status"] == "paused"

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
