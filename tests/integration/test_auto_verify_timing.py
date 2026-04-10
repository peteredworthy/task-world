"""API-level test for auto_verify 409 gate response.

The service-level timing tests (blocking transition, no bounce, passing transition)
live in test_auto_verify_workflow.py. This file covers the HTTP API surface.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """HTTP client backed by a real in-memory app with LocalAutoVerifyRunner and signal drain."""
    signal_transport = InMemorySignalTransport()
    app = create_app(db_path=":memory:")
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, signal_transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


def _embedded_routine_with_auto_verify(cmd: str, must: bool = True) -> dict[str, Any]:
    """Build a routine_embedded dict suitable for the API create-run endpoint."""
    return {
        "id": "api-timing-routine",
        "name": "API Timing Test Routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task with auto-verify",
                        "task_context": "Do the thing",
                        "requirements": [{"id": "R1", "desc": "It works"}],
                        "auto_verify": {
                            "items": [{"id": "av-check", "cmd": cmd, "must": must}],
                            "tail_lines": 10,
                        },
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# API-level integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_auto_verify_configured_failure_returns_409(
    api_client_and_drain: tuple[AsyncClient, DrainFn], tmp_path: Path
) -> None:
    """Submit returns 409 synchronously when checklist gate is blocked.

    When auto_verify is configured but has no working directory (no worktree),
    auto-verify is skipped and any OPEN critical checklist items cause a
    GateBlockedError to be returned synchronously as a 409 response.
    The run stays active; no drain is needed.
    """
    api_client, drain = api_client_and_drain
    # Create a run with an embedded routine containing a failing auto_verify command
    resp = await api_client.post(
        "/api/runs",
        json={
            "routine_embedded": _embedded_routine_with_auto_verify(cmd="false", must=True),
            "repo_name": "timing-test-repo",
            "branch": "main",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    # Start the run and the task
    start_resp = await api_client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    await api_client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Submit WITHOUT marking the checklist done — returns 409 synchronously.
    # No worktree → auto-verify skipped → OPEN critical item → GateBlockedError → 409.
    resp = await api_client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 409, f"Expected 409 from submit, got {resp.status_code}: {resp.text}"

    # Run stays active — no state change on gate failure
    run_resp = await api_client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["status"] == "active", f"Expected active, got {run_data['status']}"
