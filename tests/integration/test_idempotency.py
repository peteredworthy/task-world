"""Integration tests for idempotency of key activity boundary endpoints.

Duplicate API calls to submit, complete-verification, and cancel must be
safe no-ops — not errors or state corruption.
"""

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


# ---------------------------------------------------------------------------
# Helpers (minimal, shared with lifecycle tests)
# ---------------------------------------------------------------------------


async def _create_and_start_run(client: AsyncClient) -> tuple[str, str]:
    """Create a run, start it, return (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert resp.status_code == 201
    run_data = resp.json()
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    start = await client.post(f"/api/runs/{run_id}/start")
    assert start.status_code == 200
    return run_id, task_id


async def _drive_to_verifying(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn
) -> None:
    """Drive task from PENDING to VERIFYING (builder phase complete)."""
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200

    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    # Verify task is now verifying
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "verifying"


async def _drive_to_completed(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn
) -> None:
    """Drive task from VERIFYING to COMPLETED (verifier phase complete)."""
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Looks good"},
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    # Verify task is now completed
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# R1: Idempotent submit
# ---------------------------------------------------------------------------


async def test_submit_twice(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Calling submit twice must advance task exactly once; second call is a no-op."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client)

    # First submit: task moves BUILDING -> VERIFYING
    await _drive_to_verifying(client, run_id, task_id, drain)

    # Verify task is in VERIFYING
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "verifying"
    attempts_after_first = len(resp.json()["attempts"])

    # Second submit: enqueues signal, drain applies it (idempotent)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    # Attempt count must not have increased
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    task_data = resp.json()
    assert task_data["status"] == "verifying", (
        "Task must still be in verifying after duplicate submit"
    )
    assert len(task_data["attempts"]) == attempts_after_first, (
        "Duplicate submit must not create a second attempt"
    )


# ---------------------------------------------------------------------------
# R2: Idempotent complete-verification
# ---------------------------------------------------------------------------


async def test_verify_twice(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Calling complete-verification twice must not create a second attempt or error."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client)

    # Drive to VERIFYING
    await _drive_to_verifying(client, run_id, task_id, drain)

    # First complete-verification: task moves VERIFYING -> COMPLETED
    await _drive_to_completed(client, run_id, task_id, drain)

    # Check attempt count after first completion
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    task_data = resp.json()
    assert task_data["status"] == "completed"
    attempts_after_first = len(task_data["attempts"])

    # Second complete-verification: enqueues signal, drain applies it (idempotent)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    # Attempt count and status must be unchanged
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    task_data = resp.json()
    assert task_data["status"] == "completed", "Task must still be completed"
    assert len(task_data["attempts"]) == attempts_after_first, (
        "Duplicate complete-verification must not create a new attempt"
    )


# ---------------------------------------------------------------------------
# R3: Idempotent cancel
# ---------------------------------------------------------------------------


async def test_cancel_twice(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Cancelling an already-cancelled run must return success without error."""
    client, _drain = client_and_drain
    run_id, _ = await _create_and_start_run(client)

    # First cancel: run moves ACTIVE -> FAILED
    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200, f"First cancel should succeed: {resp.text}"
    first = resp.json()
    assert first["status"] == "failed", "Run should be failed after cancel"

    # Second cancel: must also succeed (HTTP 200), no error, run stays failed
    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200, (
        f"Second cancel should return 200, got {resp.status_code}: {resp.text}"
    )
    second = resp.json()
    assert second["status"] == "failed", "Run must remain failed after duplicate cancel"
    assert second["id"] == run_id, "Response must refer to the same run"
