"""Integration tests for task API input validation (checklist status, grades)."""

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

BASE_BODY = {"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"}


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    signal_transport = InMemorySignalTransport()
    app.state.signal_transport = signal_transport
    drain = make_drain_fn(app, signal_transport)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


async def _create_and_start_run(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run, start it, and return (run_id, task_id)."""
    create_resp = await client.post(
        "/api/runs", json={**BASE_BODY, "agent_runner_type": "user_managed"}
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)

    # Get the task ID from the run
    run_resp = await client.get(f"/api/runs/{run_id}")
    steps = run_resp.json()["steps"]
    task_id = steps[0]["tasks"][0]["id"]
    return run_id, task_id


# --- Checklist status validation ---


async def test_invalid_checklist_status_returns_422(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Invalid checklist status should return 422 with valid options."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "invalid_status"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert any("Invalid status" in str(e) for e in body["detail"])


async def test_valid_checklist_status_accepted(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Valid checklist statuses should be accepted."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)
    for status in ["done", "open", "blocked", "not_applicable"]:
        resp = await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": status},
        )
        assert resp.status_code == 200, f"status={status} failed: {resp.text}"


async def test_checklist_status_case_insensitive(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Checklist status should accept mixed case."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "DONE"},
    )
    assert resp.status_code == 200


# --- Grade validation ---


async def test_invalid_grade_returns_422(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Invalid grade should return 422 with valid options."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "Z"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert any("Invalid grade" in str(e) for e in body["detail"])


async def test_valid_grades_not_rejected_by_schema(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Valid grades should pass schema validation (task may be in wrong state, but not 422)."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)
    for grade in ["A", "B", "C", "D", "F"]:
        resp = await client.put(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
            json={"grade": grade},
        )
        # Should not be 422 (schema validation); may be 409 (wrong task state)
        assert resp.status_code != 422, f"grade={grade} wrongly rejected as invalid"


async def test_grade_case_insensitive(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Lowercase grades should pass schema validation (not 422)."""
    client, drain = client_and_drain
    run_id, task_id = await _create_and_start_run(client, drain)
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "a"},
    )
    assert resp.status_code != 422
