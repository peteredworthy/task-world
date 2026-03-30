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
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

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


async def _create_and_start_run(
    client: AsyncClient, drain: DrainFn, repo: str = "parity-pause-repo"
) -> str:
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
    assert resp.status_code == 202
    await drain(run_id)
    run = await client.get(f"/api/runs/{run_id}")
    assert run.json()["status"] == "active"
    return run_id


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Pause / resume tests
# ---------------------------------------------------------------------------


async def test_pause_sets_status_and_reason(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Pausing an active run sets status=paused with pause_reason persisted."""
    client, drain = client_and_drain
    run_id = await _create_and_start_run(client, drain)

    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    # Verify state persisted via GET
    run = await _get_run(client, run_id)
    assert run["status"] == "paused"
    # The API pause endpoint uses "manual_pause" as the default reason
    assert run["pause_reason"] == "manual_pause"


async def test_resume_clears_paused_state(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Resuming a paused run restores status=active and clears pause_reason."""
    client, drain = client_and_drain
    run_id = await _create_and_start_run(client, drain, repo="parity-resume-repo")

    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resp.status_code == 202
    await drain(run_id)

    # Verify via GET
    run = await _get_run(client, run_id)
    assert run["status"] == "active"
    # pause_reason should be cleared on resume
    assert run["pause_reason"] is None


async def test_pause_resume_then_complete(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Full workflow: start → pause → resume → complete task → run completed."""
    client, drain = client_and_drain
    run_id = await _create_and_start_run(client, drain, repo="parity-full-pause-repo")
    run_data = await _get_run(client, run_id)
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # Pause
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "paused"

    # Resume
    resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resp.status_code == 202
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "active"

    # Complete the task
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
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)

    run = await _get_run(client, run_id)
    assert run["status"] == "completed"


async def test_pause_events_recorded(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Pause and resume events appear in the activity log."""
    client, drain = client_and_drain
    run_id = await _create_and_start_run(client, drain, repo="parity-events-repo")

    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resp.status_code == 202
    await drain(run_id)

    resp = await client.get(f"/api/runs/{run_id}/activity")
    assert resp.status_code == 200
    event_types = [e["event_type"] for e in resp.json()["events"]]
    assert "run_status_changed" in event_types


# ---------------------------------------------------------------------------
# Cancel tests
# ---------------------------------------------------------------------------


async def test_cancel_active_run(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Cancelling an active run sets status=failed."""
    client, drain = client_and_drain
    run_id = await _create_and_start_run(client, drain, repo="parity-cancel-repo")

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 202
    await drain(run_id)

    run = await _get_run(client, run_id)
    assert run["status"] == "failed", "Cancelled run should have status=failed"
    assert run["completed_at"] is not None


async def test_cancel_paused_run(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Cancelling a paused run also sets status=failed."""
    client, drain = client_and_drain
    run_id = await _create_and_start_run(client, drain, repo="parity-cancel-paused-repo")

    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)
    run = await _get_run(client, run_id)
    assert run["status"] == "paused"

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 202
    await drain(run_id)
    run = await _get_run(client, run_id)
    assert run["status"] == "failed"
