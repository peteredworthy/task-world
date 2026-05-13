"""Integration tests for task API endpoints.

WARNING — shared fixture:
    The ``client_and_drain`` / ``client`` fixtures in this module reuse a
    single FastAPI app + in-memory DB across every test in the file (module
    scope). Isolation is the test author's responsibility:

    - Pass the ``repo_name`` fixture to ``_setup_active_run`` (and any direct
      ``POST /api/runs``). It returns a unique per-test value (UUID-suffixed).
    - Don't assert on global ``/api/runs`` counts — filter by ``repo_name``.
    - Run/task IDs returned from the API are server-generated UUIDs and
      cannot collide across tests.
    - Teardown cancels non-terminal runs for this test's ``repo_name`` so a
      mid-test failure cannot leak executor work into siblings.

    ``db_backed_client_and_consumer`` is a separate per-test fixture (only
    one test uses it); it builds its own ``SignalConsumer`` and is isolated
    from the shared app on purpose.
"""

from pathlib import Path

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import SignalConsumer, WorkflowService
from tests.integration.conftest import cleanup_runs_for_repo
from tests.integration.signal_helpers import DrainFn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client_and_drain(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    repo_name: str,
) -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """Shared module-scoped client + drain. Cancels this test's runs on teardown."""
    client, drain, _, _, _ = _shared_app_fixture
    yield client, drain
    await cleanup_runs_for_repo(client, repo_name)


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


@pytest.fixture
async def db_backed_client_and_consumer() -> AsyncGenerator[
    tuple[AsyncClient, SignalConsumer], None
]:
    """Per-test fixture (NOT shared) for the SignalConsumer-backed test only."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    consumer = SignalConsumer(app.state.session_factory, create_service)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, consumer
    await app.state.engine.dispose()


async def _setup_active_run(
    client: AsyncClient,
    repo_name: str,
    drain: DrainFn | None = None,
) -> tuple[str, str]:
    """Create a run and start it, returning (run_id, task_id).

    Pass the per-test ``repo_name`` fixture so the created run is isolated
    from other tests sharing this module's app/DB.
    """
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": repo_name, "branch": "main"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    if drain is not None:
        await drain(run_id)
    return run_id, task_id


async def test_get_task(client: AsyncClient, repo_name: str) -> None:
    run_id, task_id = await _setup_active_run(client, repo_name)

    response = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task_id
    assert data["status"] == "pending"
    assert len(data["checklist"]) == 1
    assert data["checklist"][0]["req_id"] == "R1"
    assert data["max_attempts"] == 3


async def test_get_task_not_found(client: AsyncClient, repo_name: str) -> None:
    run_id, _ = await _setup_active_run(client, repo_name)
    response = await client.get(f"/api/runs/{run_id}/tasks/nonexistent")
    assert response.status_code == 404


async def test_full_task_lifecycle(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Full lifecycle: start -> checklist update -> submit -> grade -> complete."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # Start task
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["new_status"] == "building"

    # Verify task is now building
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "building"
    assert len(resp.json()["attempts"]) == 1

    # Update checklist item
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done", "note": "Completed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["note"] == "Completed"

    # Submit for verification (200 sync)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    # Verify task is now verifying
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "verifying"

    # Set grade
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Well done"},
    )
    assert resp.status_code == 200
    assert resp.json()["grade"] == "A"

    # Complete verification (200 sync)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)

    # Verify task is now completed
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.json()["status"] == "completed"


async def test_db_backed_activity_signals_are_persisted(
    db_backed_client_and_consumer: tuple[AsyncClient, SignalConsumer],
    repo_name: str,
) -> None:
    """Task activity signals must survive the request session for the DB consumer."""
    client, consumer = db_backed_client_and_consumer

    run_id, task_id = await _setup_active_run(client, repo_name)
    await consumer._process_run(run_id)

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200

    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done", "note": "Completed"},
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "building"

    await consumer._process_run(run_id)
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "verifying"

    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A", "grade_reason": "Well done"},
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "verifying"

    await consumer._process_run(run_id)
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


async def test_gate_failure_response(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Submit with open checklist item: returns 409 directly (synchronous gate check)."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # Start task
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Submit without completing checklist — gate check fails immediately (409)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 409

    # Run should remain active (no drain needed, no pause)
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.json()["status"] == "active"


async def test_revision_cycle(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Fail verification with bad grade, then retry and pass."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # Attempt 1: start, submit, fail verification
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
        json={"grade": "D", "grade_reason": "Poor"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)

    # Task should be back in building (revision)
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "building"

    # Attempt 2: submit again with better grade
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

    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "completed"


async def test_checklist_not_found(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/NONEXISTENT",
        json={"status": "done"},
    )
    assert resp.status_code == 404


async def test_grade_not_found(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)
    # Advance task to VERIFYING so set_grade guard passes
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/NONEXISTENT/grade",
        json={"grade": "A"},
    )
    assert resp.status_code == 404


async def test_flexible_req_id_formats_in_api(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """API should accept numeric req_id variants for checklist/grade endpoints."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Numeric-only format should resolve to R1.
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/1",
        json={"status": "done"},
    )
    assert resp.status_code == 200
    assert resp.json()["req_id"] == "R1"

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    # Dashed format should resolve to R1.
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R-01/grade",
        json={"grade": "A", "grade_reason": "Flexible ID accepted"},
    )
    assert resp.status_code == 200
    assert resp.json()["req_id"] == "R1"


async def test_run_not_found_for_task(client: AsyncClient) -> None:
    resp = await client.get("/api/runs/nonexistent/tasks/whatever")
    assert resp.status_code == 404


async def test_prompt_returns_builder_when_building(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Prompt endpoint returns builder prompt when task is in BUILDING state."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # Start task -> BUILDING
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "building"
    assert "software developer" in data["system"].lower()
    assert "## Task" in data["user"]
    assert "## Requirements" in data["user"]


async def test_prompt_returns_verifier_when_verifying(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Prompt endpoint returns verifier prompt when task is in VERIFYING state."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # Start task -> BUILDING
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Complete checklist and submit -> drain -> VERIFYING
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "verifying"
    assert "code reviewer" in data["system"].lower()
    assert "## Requirements to Verify" in data["user"]


async def test_prompt_rejects_pending_task(client: AsyncClient, repo_name: str) -> None:
    """Prompt endpoint returns 409 when task is in PENDING state."""
    run_id, task_id = await _setup_active_run(client, repo_name)

    # Task is still PENDING (not started)
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "invalid_transition"
    assert data["from_status"] == "pending"


async def test_prompt_rejects_completed_task(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Prompt endpoint returns 409 when task is in COMPLETED state."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # Full lifecycle to reach COMPLETED
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

    # Task is now COMPLETED
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "invalid_transition"
    assert data["from_status"] == "completed"


async def test_submit_with_unfinished_checklist_returns_409(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Submit task when checklist gate fails: returns 409 directly (synchronous gate check)."""
    client, drain = client_and_drain
    # 1. Create and start a run
    run_id, task_id = await _setup_active_run(client, repo_name, drain)

    # 2. Start the first task (status becomes BUILDING)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "building"

    # 3. DO NOT mark checklist items as done (checklist gate will fail)

    # 4. Submit — gate check fails immediately, returns 409
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 409

    # 5. Verify run remains active (no drain needed, no pause)
    run_resp = await client.get(f"/api/runs/{run_id}")
    data = run_resp.json()
    assert data["status"] == "active"
