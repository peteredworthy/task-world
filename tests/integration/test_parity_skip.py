"""Parity test: conditional step skipping.

Captures current orchestrator behaviour as a regression baseline.
Covers:
  - Step with a condition that evaluates to false ('false' literal)
  - Step is skipped (not executed) and skip_reason is recorded
  - Run advances to the next non-skipped step
  - Skip state persists in the DB across service operations
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig, StepCondition, StepConfig, TaskConfig
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow.signals import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# ---------------------------------------------------------------------------
# Embedded routine: 3 steps, step 2 has condition=false, step 3 is normal
# ---------------------------------------------------------------------------

SKIP_ROUTINE: dict[str, Any] = {
    "id": "parity-skip",
    "name": "Parity Skip Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Always runs",
                    "requirements": [{"id": "R1", "desc": "Done"}],
                }
            ],
        },
        {
            "id": "S-02",
            "title": "Step Two (Skipped)",
            "condition": {"when": "false"},
            "tasks": [
                {
                    "id": "T-02",
                    "title": "Task Two",
                    "task_context": "Should never run",
                    "requirements": [{"id": "R1", "desc": "Done"}],
                }
            ],
        },
        {
            "id": "S-03",
            "title": "Step Three",
            "tasks": [
                {
                    "id": "T-03",
                    "title": "Task Three",
                    "task_context": "Runs after skip",
                    "requirements": [{"id": "R1", "desc": "Done"}],
                }
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _complete_task(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn, req_id: str = "R1"
) -> None:
    """Drive a task through the full build → verify → complete cycle."""
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)

    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 202
    await drain(run_id)

    task = (await client.get(f"/api/runs/{run_id}/tasks/{task_id}")).json()
    assert task["status"] == "completed"


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# API-based tests
# ---------------------------------------------------------------------------


async def test_skip_step_not_executed(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Step with condition=false is skipped; its task remains pending."""
    client, drain = client_and_drain
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": SKIP_ROUTINE,
            "repo_name": "parity-skip-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    task2_id = run["steps"][1]["tasks"][0]["id"]  # task in skipped step

    await client.post(f"/api/runs/{run_id}/start")

    # Complete step 1 → triggers condition evaluation on step 2
    await _complete_task(client, run_id, task1_id, drain)

    # Step 2 should be skipped; its task should remain pending (not executed)
    run_state = await _get_run(client, run_id)
    assert run_state["steps"][1]["skipped"] is True, "Step 2 should be marked as skipped"

    # Task in skipped step should not have been started
    task2_resp = await client.get(f"/api/runs/{run_id}/tasks/{task2_id}")
    assert task2_resp.status_code == 200
    task2 = task2_resp.json()
    assert task2["status"] == "pending", "Task in skipped step should remain pending (not executed)"


async def test_skip_step_run_advances_to_next(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """After skipping step 2, run.current_step_index advances to step 3."""
    client, drain = client_and_drain
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": SKIP_ROUTINE,
            "repo_name": "parity-skip-advance-repo",
            "branch": "main",
        },
    )
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await _complete_task(client, run_id, task1_id, drain)

    # Run should have jumped to step index 2 (step 3), skipping step index 1
    run_state = await _get_run(client, run_id)
    assert run_state["current_step_index"] == 2, (
        "Run should advance past the skipped step to step index 2"
    )
    assert run_state["status"] == "active"


async def test_skip_reason_recorded(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Skipped step has a non-empty skip_reason."""
    client, drain = client_and_drain
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": SKIP_ROUTINE,
            "repo_name": "parity-skip-reason-repo",
            "branch": "main",
        },
    )
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await _complete_task(client, run_id, task1_id, drain)

    run_state = await _get_run(client, run_id)
    skip_reason = run_state["steps"][1].get("skip_reason")
    assert skip_reason is not None, "Skip reason should be recorded"
    assert len(skip_reason) > 0, "Skip reason should not be empty"
    # The engine records: "Condition 'false' evaluated to false"
    assert "false" in skip_reason.lower(), "Skip reason should mention the condition"


async def test_skip_step_full_workflow_completes(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Full run with skipped step 2: step 1 → skip step 2 → step 3 → completed."""
    client, drain = client_and_drain
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": SKIP_ROUTINE,
            "repo_name": "parity-skip-full-repo",
            "branch": "main",
        },
    )
    run = resp.json()
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    task3_id = run["steps"][2]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")

    # Complete step 1 (step 2 auto-skipped)
    await _complete_task(client, run_id, task1_id, drain)

    # Complete step 3
    await _complete_task(client, run_id, task3_id, drain)

    run_state = await _get_run(client, run_id)
    assert run_state["status"] == "completed"
    assert run_state["steps"][0]["completed"] is True
    assert run_state["steps"][1]["skipped"] is True
    assert run_state["steps"][2]["completed"] is True


# ---------------------------------------------------------------------------
# Service-level tests (persistence)
# ---------------------------------------------------------------------------


def _make_skip_routine() -> RoutineConfig:
    """Create a 3-step routine where step 2 has condition=false."""
    return RoutineConfig(
        id="parity-skip-service",
        name="Parity Skip Service Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step One",
                tasks=[TaskConfig(id="T-01", title="Task One", task_context="Run this")],
            ),
            StepConfig(
                id="S-02",
                title="Step Two (Skipped)",
                tasks=[TaskConfig(id="T-02", title="Task Two", task_context="Skip this")],
                condition=StepCondition(when="false"),
            ),
            StepConfig(
                id="S-03",
                title="Step Three",
                tasks=[TaskConfig(id="T-03", title="Task Three", task_context="Run this")],
            ),
        ],
    )


async def test_skip_state_persists_to_db(service: WorkflowService) -> None:
    """Skipped and skip_reason fields persist through save/load cycle."""
    routine = _make_skip_routine()
    run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

    # Manually mark step 2 as skipped (simulates what the engine does)
    run.steps[1].skipped = True
    run.steps[1].skip_reason = "Condition 'false' evaluated to false"

    await service.create_run(run)

    loaded = await service._repo.get(run.id)
    assert loaded.steps[1].skipped is True
    assert loaded.steps[1].skip_reason == "Condition 'false' evaluated to false"
    # Non-skipped steps should not be skipped
    assert loaded.steps[0].skipped is False
    assert loaded.steps[2].skipped is False


async def test_non_skipped_step_has_no_skip_reason(service: WorkflowService) -> None:
    """Steps without conditions have skipped=False and skip_reason=None."""
    routine = _make_skip_routine()
    run = create_run_from_routine(routine, repo_name="test-repo-2", source_branch="main")

    await service.create_run(run)

    loaded = await service._repo.get(run.id)
    assert loaded.steps[0].skipped is False
    assert loaded.steps[0].skip_reason is None
    assert loaded.steps[2].skipped is False
    assert loaded.steps[2].skip_reason is None
