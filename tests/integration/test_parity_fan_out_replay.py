"""Parity replay test: partial fan-out completion survives executor restart.

Simulates a scenario where a fan-out step has 3 child tasks, 2 complete
successfully before a 'restart' (state corrupted to DRAFT), and verifies
that replaying the event journal correctly reconstructs:
  - The first 2 children as COMPLETED
  - The third child as PENDING (not yet done)
  - The fan-out step as NOT completed (still in progress)
  - The run as ACTIVE
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource, RunStatus, TaskStatus
from orchestrator.db import init_db
from orchestrator.db import resolve_default_journal_path
from orchestrator.db import replay_journal_to_repository
from orchestrator.db import RunRepository
from orchestrator.state.models import Run
from orchestrator.workflow.signals import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# Fan-out routine: Step 1 setup, Step 2 has 3 parallel child tasks, Step 3 combine.
FAN_OUT_ROUTINE: dict[str, Any] = {
    "id": "replay-fan-out",
    "name": "Replay Fan-Out Routine",
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
async def file_db_client(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, FastAPI, DrainFn], None]:
    db_path = tmp_path / "orchestrator.db"
    transport = InMemorySignalTransport()
    app = create_app(
        db_path=str(db_path),
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        spawn_agents=False,
    )
    app.state.signal_transport = transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, db_path, app, drain
    await app.state.engine.dispose()


async def _complete_task(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn, req_id: str = "R1"
) -> None:
    """Drive a task through start → submit → grade → complete-verification."""
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200, f"start failed: {resp.text}"
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


def _corrupt_run_to_draft(run: Run) -> None:
    """Reset run and all tasks to initial state to simulate restoring from stale backup."""
    run.status = RunStatus.DRAFT
    run.started_at = None
    run.current_step_index = 0
    for step in run.steps:
        step.completed = False
        for task in step.tasks:
            task.status = TaskStatus.PENDING
            task.current_attempt = 0
            task.attempts = []


async def test_partial_fan_out_replay_reconstructs_correct_state(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """After restart, completed fan-out children stay COMPLETED; pending stay PENDING.

    Scenario:
    1. Create run with 3 fan-out children in step 2
    2. Complete setup (step 1) + child A and child B (2 of 3)
    3. Simulate executor restart: corrupt state to DRAFT/PENDING
    4. Replay events from journal
    5. Assert: run=ACTIVE, step 1=completed, child A=completed, child B=completed,
       child C=pending, fan-out step NOT completed
    """
    client, db_path, app, drain = file_db_client

    # Create and start run
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": FAN_OUT_ROUTINE,
            "repo_name": "replay-fan-out-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run = resp.json()
    run_id = run["id"]
    setup_task_id = run["steps"][0]["tasks"][0]["id"]
    child_a_id = run["steps"][1]["tasks"][0]["id"]
    child_b_id = run["steps"][1]["tasks"][1]["id"]
    child_c_id = run["steps"][1]["tasks"][2]["id"]

    # Start run
    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 200

    # Complete setup step
    await _complete_task(client, run_id, setup_task_id, drain)

    # Verify we're on step 2
    run_state = (await client.get(f"/api/runs/{run_id}")).json()
    assert run_state["current_step_index"] == 1

    # Complete child A and child B (but NOT child C — partial completion)
    await _complete_task(client, run_id, child_a_id, drain)
    await _complete_task(client, run_id, child_b_id, drain)

    # Verify partial state: step 2 not completed yet, child C still pending
    run_state = (await client.get(f"/api/runs/{run_id}")).json()
    assert run_state["steps"][1]["completed"] is False, "Fan-out step should not be completed yet"
    assert run_state["current_step_index"] == 1, "Should still be on fan-out step"

    task_c = (await client.get(f"/api/runs/{run_id}/tasks/{child_c_id}")).json()
    assert task_c["status"] == "pending", f"Child C should be pending, got {task_c['status']}"

    # Verify journal was written
    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None and journal_path.exists(), "Journal file must exist"

    # --- Simulate executor restart: corrupt all state to DRAFT/PENDING ---
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        _corrupt_run_to_draft(stale_run)
        await repo.save(stale_run)
        await session.commit()

    # Verify state is now corrupted
    corrupted = (await client.get(f"/api/runs/{run_id}")).json()
    assert corrupted["status"] == "draft"

    # --- Replay journal to reconstruct state ---
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
        )
        await session.commit()

    assert summary.replayed_events > 0, "Replay should have processed events"
    assert summary.updated_runs == 1, "Run should have been updated by replay"

    # --- Assert correct reconstruction ---
    restored = (await client.get(f"/api/runs/{run_id}")).json()

    # Run should be active (not draft, not completed)
    assert restored["status"] == "active", f"Run should be active, got {restored['status']}"

    # Step 1 (setup) should be completed
    assert restored["steps"][0]["completed"] is True, "Setup step should be completed"

    # Step 2 (fan-out) should NOT be completed (child C still pending)
    assert restored["steps"][1]["completed"] is False, (
        "Fan-out step should NOT be completed (child C still pending)"
    )

    # Should still be on fan-out step
    assert restored["current_step_index"] == 1, (
        f"Should still be on fan-out step, got index {restored['current_step_index']}"
    )

    # Child A and B should be COMPLETED
    child_a_state = (await client.get(f"/api/runs/{run_id}/tasks/{child_a_id}")).json()
    assert child_a_state["status"] == "completed", (
        f"Child A should be completed after replay, got {child_a_state['status']}"
    )

    child_b_state = (await client.get(f"/api/runs/{run_id}/tasks/{child_b_id}")).json()
    assert child_b_state["status"] == "completed", (
        f"Child B should be completed after replay, got {child_b_state['status']}"
    )

    # Child C should still be PENDING (not yet completed before restart)
    child_c_state = (await client.get(f"/api/runs/{run_id}/tasks/{child_c_id}")).json()
    assert child_c_state["status"] == "pending", (
        f"Child C should remain pending after replay, got {child_c_state['status']}"
    )


async def test_all_fan_out_children_completed_replay(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """Replay after all children complete advances step index correctly."""
    client, db_path, app, drain = file_db_client

    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": FAN_OUT_ROUTINE,
            "repo_name": "replay-fan-out-all-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run = resp.json()
    run_id = run["id"]
    setup_task_id = run["steps"][0]["tasks"][0]["id"]
    child_a_id = run["steps"][1]["tasks"][0]["id"]
    child_b_id = run["steps"][1]["tasks"][1]["id"]
    child_c_id = run["steps"][1]["tasks"][2]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await _complete_task(client, run_id, setup_task_id, drain)
    await _complete_task(client, run_id, child_a_id, drain)
    await _complete_task(client, run_id, child_b_id, drain)
    await _complete_task(client, run_id, child_c_id, drain)

    # Verify all done before restart
    run_state = (await client.get(f"/api/runs/{run_id}")).json()
    assert run_state["steps"][1]["completed"] is True
    assert run_state["current_step_index"] == 2  # Advanced to combine step

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    # Corrupt state
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        _corrupt_run_to_draft(stale_run)
        await repo.save(stale_run)
        await session.commit()

    # Replay
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
        )
        await session.commit()

    restored = (await client.get(f"/api/runs/{run_id}")).json()
    assert restored["status"] == "active"
    assert restored["steps"][0]["completed"] is True
    assert restored["steps"][1]["completed"] is True
    assert restored["current_step_index"] == 2

    for child_id in (child_a_id, child_b_id, child_c_id):
        child_state = (await client.get(f"/api/runs/{run_id}/tasks/{child_id}")).json()
        assert child_state["status"] == "completed", (
            f"Child {child_id} should be completed, got {child_state['status']}"
        )
