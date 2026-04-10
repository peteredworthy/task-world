"""Integration tests for full workflow lifecycle through HTTP API endpoints.

These tests exercise the COMPLETE workflow from run creation through task
completion, including revision cycles, queue/pause/resume flows, cancellation,
cost estimation, embedded routines, and activity event recording -- all via
the public REST API.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow.locks import InMemoryLockManager
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture(scope="module")
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport_obj = InMemorySignalTransport()
    app.state.signal_transport = transport_obj
    drain = make_drain_fn(app, transport_obj)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture(scope="module")
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_run(
    client: AsyncClient,
    routine_id: str = "simple-routine",
    repo_name: str = "proj-1",
    branch: str = "main",
    **extra: Any,
) -> dict[str, Any]:
    """Create a run via POST and return the response body."""
    body: dict[str, Any] = {
        "routine_id": routine_id,
        "repo_name": repo_name,
        "branch": branch,
        **extra,
    }
    resp = await client.post("/api/runs", json=body)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


async def _start_run(
    client: AsyncClient, run_id: str, drain: DrainFn | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202, f"Failed to start run: {resp.text}"
    if drain is not None:
        await drain(run_id)
    resp2 = await client.get(f"/api/runs/{run_id}")
    assert resp2.status_code == 200
    return resp2.json()


async def _start_task(client: AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200, f"Failed to start task: {resp.text}"
    data = resp.json()
    assert data["success"] is True, f"start_task returned success=False: {data}"
    return data


async def _mark_checklist_done(
    client: AsyncClient, run_id: str, task_id: str, req_id: str
) -> dict[str, Any]:
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}",
        json={"status": "done"},
    )
    assert resp.status_code == 200, f"Failed to update checklist: {resp.text}"
    return resp.json()


async def _submit_task(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200, f"Failed to submit task: {resp.text}"
    if drain is not None:
        await drain(run_id)
    return {"success": True}


async def _grade_item(
    client: AsyncClient,
    run_id: str,
    task_id: str,
    req_id: str,
    grade: str,
    reason: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"grade": grade}
    if reason is not None:
        body["grade_reason"] = reason
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
        json=body,
    )
    assert resp.status_code == 200, f"Failed to set grade: {resp.text}"
    return resp.json()


async def _complete_verification(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200, f"Failed to complete verification: {resp.text}"
    if drain is not None:
        await drain(run_id)
    return {"success": True}


async def _complete_task_successfully(
    client: AsyncClient, run_id: str, task_id: str, req_id: str = "R1", drain: DrainFn | None = None
) -> None:
    """Drive a single task through the full builder/verifier cycle to completion."""
    await _start_task(client, run_id, task_id)
    await _mark_checklist_done(client, run_id, task_id, req_id)
    await _submit_task(client, run_id, task_id, drain=drain)
    # Verify task is in verifying state after drain
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "verifying", "Task should be verifying after submit+drain"
    await _grade_item(client, run_id, task_id, req_id, "A", "Excellent")
    await _complete_verification(client, run_id, task_id, drain=drain)
    # Verify task is completed after drain
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "completed", "Task should be completed after verify+drain"


# ---------------------------------------------------------------------------
# Test 1: Full lifecycle -- builder/verifier pass
# ---------------------------------------------------------------------------


async def test_full_lifecycle_builder_verifier_pass(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Complete workflow: create -> start -> build -> verify -> complete."""
    client, drain = client_and_drain
    # 1. Create run
    run_data = await _create_run(client)
    run_id = run_data["id"]
    assert run_data["status"] == "draft", "Newly created run should be in draft status"
    assert len(run_data["steps"]) == 1, "simple-routine has one step"
    assert len(run_data["steps"][0]["tasks"]) == 1, "simple-routine has one task"

    # 2. Start run
    started = await _start_run(client, run_id, drain=drain)
    assert started["status"] == "active", "Run should be active after start"

    # 3. Verify run status via GET
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    # 4. Get task ID
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # 5. Start task
    start_resp = await _start_task(client, run_id, task_id)
    assert start_resp["new_status"] == "building", "Task should be building after start"

    # 6. Verify task status via GET
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.status_code == 200
    task_data = task_resp.json()
    assert task_data["status"] == "building", "Task status should be building"
    assert len(task_data["attempts"]) == 1, "Should have one attempt"
    assert task_data["current_attempt"] == 1, "Should be on attempt 1"

    # 7. Get builder prompt
    prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert prompt_resp.status_code == 200
    prompt_data = prompt_resp.json()
    assert prompt_data["phase"] == "building", "Prompt phase should be building"
    assert "software developer" in prompt_data["system"].lower(), "Builder system prompt expected"
    assert "## Task" in prompt_data["user"], "Builder user prompt should contain task section"

    # 8. Mark checklist item done
    checklist_resp = await _mark_checklist_done(client, run_id, task_id, "R1")
    assert checklist_resp["status"] == "done", "Checklist item should be done"

    # 9. Submit task (202 async) then drain
    await _submit_task(client, run_id, task_id, drain=drain)

    # 10. Verify task is in verifying state
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "verifying"

    # 11. Get verifier prompt
    prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert prompt_resp.status_code == 200
    prompt_data = prompt_resp.json()
    assert prompt_data["phase"] == "verifying", "Prompt phase should be verifying"
    assert "code reviewer" in prompt_data["system"].lower(), "Verifier system prompt expected"
    assert "## Requirements to Verify" in prompt_data["user"], (
        "Verifier prompt should list requirements"
    )

    # 12. Grade checklist item
    grade_resp = await _grade_item(client, run_id, task_id, "R1", "A", "Well done")
    assert grade_resp["grade"] == "A"
    assert grade_resp["grade_reason"] == "Well done"

    # 13. Complete verification (202 async) then drain
    await _complete_verification(client, run_id, task_id, drain=drain)

    # 14. Verify task is completed via GET
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "completed"

    # 15. Verify run auto-completed
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run_final = run_resp.json()
    assert run_final["status"] == "completed", "Run should auto-complete when all tasks done"
    assert run_final["completed_at"] is not None, "completed_at should be set"

    # 16. Verify step is marked completed
    assert run_final["steps"][0]["completed"] is True, "Step should be marked completed"

    # 17. Verify activity events are recorded
    activity_resp = await client.get(f"/api/runs/{run_id}/activity")
    assert activity_resp.status_code == 200
    activity_data = activity_resp.json()
    assert activity_data["run_id"] == run_id
    assert len(activity_data["events"]) > 0, "Should have recorded workflow events"
    event_types = [e["event_type"] for e in activity_data["events"]]
    assert "run_status_changed" in event_types, "Should have run status change events"
    assert "task_status_changed" in event_types, "Should have task status change events"


# ---------------------------------------------------------------------------
# Test 2: Full lifecycle with revision
# ---------------------------------------------------------------------------


async def test_full_lifecycle_with_revision(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Revision cycle: fail verification, then pass on retry."""
    client, drain = client_and_drain
    # Setup: create and start run
    run_data = await _create_run(client)
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]
    await _start_run(client, run_id, drain=drain)

    # Attempt 1: start task, submit, fail verification
    await _start_task(client, run_id, task_id)
    await _mark_checklist_done(client, run_id, task_id, "R1")
    await _submit_task(client, run_id, task_id, drain=drain)

    # Verify task is in verifying state
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "verifying"

    # Grade with F -> should trigger revision
    await _grade_item(client, run_id, task_id, "R1", "F", "Needs complete rework")
    await _complete_verification(client, run_id, task_id, drain=drain)

    # Verify task went back to building
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    task_data = task_resp.json()
    assert task_data["status"] == "building", "Failed grade should trigger revision"
    assert task_data["current_attempt"] == 2, "Should be on attempt 2 after revision"
    assert len(task_data["attempts"]) == 2, "Should have 2 attempts"
    # First attempt should have outcome recorded
    assert task_data["attempts"][0]["outcome"] == "revision_needed", (
        "First attempt should be marked as revision_needed"
    )

    # Attempt 2: complete successfully
    await _mark_checklist_done(client, run_id, task_id, "R1")
    await _submit_task(client, run_id, task_id, drain=drain)

    # Verify in verifying state
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "verifying"

    await _grade_item(client, run_id, task_id, "R1", "A", "Much better")
    await _complete_verification(client, run_id, task_id, drain=drain)

    # Verify task completed
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "completed", "Should complete on second attempt"

    # Verify final state
    run_resp = await client.get(f"/api/runs/{run_id}")
    run_final = run_resp.json()
    assert run_final["status"] == "completed", "Run should auto-complete"
    assert run_final["steps"][0]["completed"] is True

    # Verify final task state has 2 attempts
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    task_final = task_resp.json()
    assert task_final["status"] == "completed"
    assert len(task_final["attempts"]) == 2
    assert task_final["attempts"][1]["outcome"] == "passed", "Second attempt should pass"


# ---------------------------------------------------------------------------
# Test 3: Cancel active run
# ---------------------------------------------------------------------------


async def test_full_lifecycle_cancel_active_run(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Create, start, begin a task, then cancel the run."""
    client, drain = client_and_drain
    # 1. Create and start run
    run_data = await _create_run(client)
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]
    await _start_run(client, run_id, drain=drain)

    # 2. Start a task (put it in building state)
    await _start_task(client, run_id, task_id)

    # Verify task is building
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "building"

    # 3. Cancel the run
    cancel_resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 202
    await drain(run_id)

    # 4. Verify via GET
    run_resp = await client.get(f"/api/runs/{run_id}")
    cancel_data = run_resp.json()
    assert cancel_data["status"] == "failed", "Cancelled run should be in failed status"
    assert cancel_data["completed_at"] is not None, "completed_at should be set on cancel"

    # 5. Verify activity includes the cancellation event
    activity_resp = await client.get(f"/api/runs/{run_id}/activity")
    assert activity_resp.status_code == 200
    event_types = [e["event_type"] for e in activity_resp.json()["events"]]
    assert "run_status_changed" in event_types


# ---------------------------------------------------------------------------
# Test 5: Pause and resume
# ---------------------------------------------------------------------------


async def test_full_lifecycle_pause_resume(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Create, start, pause, resume, then complete the workflow."""
    client, drain = client_and_drain
    # 1. Create and start
    run_data = await _create_run(client)
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]
    await _start_run(client, run_id, drain=drain)

    # 2. Pause
    pause_resp = await client.post(f"/api/runs/{run_id}/pause")
    assert pause_resp.status_code == 202
    await drain(run_id)

    # 3. Verify paused via GET
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.json()["status"] == "paused", "Run should be paused"

    # 4. Resume
    resume_resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resume_resp.status_code == 202
    await drain(run_id)

    # 5. Verify active via GET
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.json()["status"] == "active", "Run should be active after resume"

    # 6. Complete the workflow
    await _complete_task_successfully(client, run_id, task_id, drain=drain)

    run_final = await client.get(f"/api/runs/{run_id}")
    assert run_final.json()["status"] == "completed"

    # Verify pause/resume events appear in activity
    activity_resp = await client.get(f"/api/runs/{run_id}/activity")
    event_types = [e["event_type"] for e in activity_resp.json()["events"]]
    assert "run_status_changed" in event_types


# ---------------------------------------------------------------------------
# Test 6: Cost estimation in response
# ---------------------------------------------------------------------------


async def test_cost_estimation_in_response(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Verify cost estimation appears when token data is present."""
    client, drain = client_and_drain
    # 1. Create and complete a run (abbreviated)
    run_data = await _create_run(client)
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]
    await _start_run(client, run_id, drain=drain)
    await _complete_task_successfully(client, run_id, task_id, drain=drain)

    # Verify initially no cost estimate (no tokens used through API)
    run_resp = await client.get(f"/api/runs/{run_id}")
    run_final = run_resp.json()
    assert run_final["status"] == "completed"
    assert run_final["total_tokens_read"] == 0, "No tokens tracked through API"

    # 2. Manually update token counts via the repo layer
    from orchestrator.db import RunRepository

    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    session_factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.total_tokens_read = 100_000
        run.total_tokens_write = 50_000
        run.total_tokens_cache = 10_000
        await repo.save(run)
        await session.commit()

    # 3. GET the run again - should now have cost estimation
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    data = run_resp.json()

    assert data["total_tokens_read"] == 100_000, "Token read count should be persisted"
    assert data["total_tokens_write"] == 50_000, "Token write count should be persisted"
    assert data["total_tokens_cache"] == 10_000, "Token cache count should be persisted"

    # 4. Verify cost fields are populated
    assert data["estimated_cost_usd"] is not None, "Cost estimate should be populated"
    assert data["estimated_cost_usd"] > 0, "Cost estimate should be positive"
    assert data["cost_disclaimer"] is not None, "Cost disclaimer should be present"
    assert "gpt-4o" in data["cost_disclaimer"], "Disclaimer should mention gpt-4o"
    assert "Estimate only" in data["cost_disclaimer"], "Disclaimer should note it's an estimate"


# ---------------------------------------------------------------------------
# Test 7: Embedded routine full lifecycle
# ---------------------------------------------------------------------------

EMBEDDED_ROUTINE: dict[str, Any] = {
    "id": "inline-test",
    "name": "Inline Test Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Inline Step",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Inline Task",
                    "task_context": "Do the inline thing",
                    "requirements": [{"id": "R1", "desc": "It works correctly"}],
                }
            ],
        }
    ],
}


async def test_embedded_routine_full_lifecycle(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Full lifecycle using an inline embedded routine instead of routine_id."""
    client, drain = client_and_drain
    # 1. Create run with embedded routine
    resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-embedded",
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    run_data = resp.json()
    run_id = run_data["id"]

    assert run_data["routine_id"] == "inline-test", "routine_id should come from embedded config"
    assert run_data["routine_source"] == "embedded", "Source should be embedded"
    assert run_data["routine_embedded"] == EMBEDDED_ROUTINE, "Embedded routine should be returned"
    assert run_data["status"] == "draft"
    assert len(run_data["steps"]) == 1
    assert len(run_data["steps"][0]["tasks"]) == 1

    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # 2. Start the run
    started = await _start_run(client, run_id, drain=drain)
    assert started["status"] == "active"

    # 3. Start task
    await _start_task(client, run_id, task_id)

    # Verify prompt works with embedded routine
    prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert prompt_resp.status_code == 200
    assert prompt_resp.json()["phase"] == "building"

    # 4. Complete the full workflow
    await _mark_checklist_done(client, run_id, task_id, "R1")
    await _submit_task(client, run_id, task_id, drain=drain)

    # Verify verifier prompt works with embedded routine
    prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert prompt_resp.status_code == 200
    assert prompt_resp.json()["phase"] == "verifying"

    await _grade_item(client, run_id, task_id, "R1", "A", "Perfect")
    await _complete_verification(client, run_id, task_id, drain=drain)

    # Verify task completed
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "completed"

    # 5. Verify run completed successfully
    run_resp = await client.get(f"/api/runs/{run_id}")
    run_final = run_resp.json()
    assert run_final["status"] == "completed", "Run should auto-complete"
    assert run_final["routine_embedded"] == EMBEDDED_ROUTINE, (
        "Embedded routine should persist through lifecycle"
    )
    assert run_final["steps"][0]["completed"] is True


# ---------------------------------------------------------------------------
# Test 8: Lock manager prevents concurrent task start (gap-fix wiring)
# ---------------------------------------------------------------------------


async def test_lock_manager_prevents_concurrent_task_start(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Verify that the lock manager is wired into the app and prevents
    a different agent from starting the same task.

    The API's start_task endpoint always uses agent_id="default", so calling
    it twice from the API will NOT trigger TaskLockedError -- instead, the
    second call fails at the transition level because the task is already
    in BUILDING status.

    To truly test that the lock manager is wired in and prevents concurrent
    access from different agents, we acquire a lock directly on the shared
    lock_manager (from app.state) with a different agent_id, then verify
    that the API's start_task call (which uses agent_id="default") returns
    409 with TaskLockedError.
    """
    client, drain = client_and_drain
    # 1. Create and start a run
    run_data = await _create_run(client)
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]
    await _start_run(client, run_id, drain=drain)

    # 2. Acquire the lock as a different agent (simulating another agent holding the lock)
    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    lock_manager = cast(InMemoryLockManager, app.state.lock_manager)
    from datetime import datetime, timezone

    acquired = lock_manager.acquire(task_id, "other-agent", datetime.now(timezone.utc))
    assert acquired is True, "Should be able to acquire lock as other-agent"

    # 3. Try to start the task via the API (uses agent_id="default")
    # This should fail with 409 because "other-agent" holds the lock
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 409, (
        f"Expected 409 (TaskLockedError) when task is locked by another agent, "
        f"got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data["error"] == "task_locked", (
        f"Expected error type 'task_locked', got {data.get('error')}"
    )
    assert data["task_id"] == task_id

    # 4. Release the lock and verify the API start_task now succeeds
    lock_manager.release(task_id, "other-agent")

    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200, (
        f"Should succeed after lock is released, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data["success"] is True
    assert data["new_status"] == "building"


# ---------------------------------------------------------------------------
# Test 9: Auto-verify results appear in task detail response (gap-fix wiring)
# ---------------------------------------------------------------------------

EMBEDDED_ROUTINE_WITH_AUTO_VERIFY: dict[str, Any] = {
    "id": "auto-verify-routine",
    "name": "Auto Verify Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step With Auto Verify",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task With Auto Verify",
                    "task_context": "Do something and verify it",
                    "requirements": [{"id": "R1", "desc": "It works correctly"}],
                    "auto_verify": {
                        "items": [
                            {"id": "AV1", "cmd": "echo passed", "must": True},
                        ],
                        "tail_lines": 10,
                    },
                }
            ],
        }
    ],
}


async def test_auto_verify_results_in_response(
    client_and_drain: tuple[AsyncClient, DrainFn], tmp_path: Path
) -> None:
    """Verify that auto-verify commands are executed during submit and
    results appear in the task detail response.

    Auto-verify runs when:
    1. routine_embedded has auto_verify items for the task
    2. An AutoVerifyRunner is injected (LocalAutoVerifyRunner in deps.py)
    3. The run has a worktree_path that resolves to a real directory

    We set worktree_path to tmp_path so auto-verify commands can run.
    """
    from orchestrator.db import RunRepository

    client, drain = client_and_drain
    # 1. Create run with embedded routine that has auto_verify
    resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "test-repo",
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE_WITH_AUTO_VERIFY,
        },
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    run_data = resp.json()
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # Update the run's worktree_path so auto-verify can run
    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    session_factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)
    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.worktree_path = str(tmp_path)
        await repo.save(run)
        await session.commit()

    # 2. Start the run and task
    await _start_run(client, run_id, drain=drain)
    await _start_task(client, run_id, task_id)

    # 3. Mark checklist done and submit (triggers auto-verify), then drain
    await _mark_checklist_done(client, run_id, task_id, "R1")
    await _submit_task(client, run_id, task_id, drain=drain)
    # Auto-verify with "echo passed" should succeed, so task is now in verifying
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "verifying", (
        f"Expected verifying after auto-verify pass, got {task_resp.json()['status']}"
    )

    # 4. Check task detail for auto_verify_results
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.status_code == 200
    task_data = task_resp.json()

    assert len(task_data["attempts"]) == 1, "Should have one attempt"
    attempt = task_data["attempts"][0]
    assert len(attempt["auto_verify_results"]) > 0, (
        "auto_verify_results should be populated after submit"
    )

    av_result = attempt["auto_verify_results"][0]
    assert av_result["item_id"] == "AV1", "Should reference the auto-verify item"
    assert av_result["passed"] is True, "'echo passed' should succeed"
    assert av_result["exit_code"] == 0, "Exit code should be 0"

    # 5. Verify the auto_verify_completed event is in the activity feed
    activity_resp = await client.get(f"/api/runs/{run_id}/activity")
    assert activity_resp.status_code == 200
    event_types = [e["event_type"] for e in activity_resp.json()["events"]]
    assert "auto_verify_completed" in event_types, (
        "auto_verify_completed event should be recorded in activity"
    )


# ---------------------------------------------------------------------------
# Test 10: Activity events recorded for all transitions (gap-fix wiring)
# ---------------------------------------------------------------------------


async def test_activity_events_recorded_for_all_transitions(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Verify that ALL expected event types are recorded during a full
    lifecycle through the API.

    Expected events for a complete lifecycle:
    - run_status_changed: draft->active (start_run)
    - task_status_changed: pending->building (start_task)
    - checklist_gate_evaluated: gate pass on submit
    - task_status_changed: building->verifying (submit)
    - grades_evaluated: grade evaluation on complete-verification
    - task_status_changed: verifying->completed (complete-verification)
    - step_completed: step finishes when all tasks complete
    - run_status_changed: active->completed (auto-complete)
    """
    client, drain = client_and_drain
    # 1. Create and start a run
    run_data = await _create_run(client)
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # 2. Start run
    await _start_run(client, run_id, drain=drain)

    # 3. Start task
    await _start_task(client, run_id, task_id)

    # 4. Mark checklist done and submit
    await _mark_checklist_done(client, run_id, task_id, "R1")
    await _submit_task(client, run_id, task_id, drain=drain)

    # 5. Grade and complete verification
    await _grade_item(client, run_id, task_id, "R1", "A", "Excellent")
    await _complete_verification(client, run_id, task_id, drain=drain)

    # 6. Verify run completed
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.json()["status"] == "completed"

    # 7. Get activity events
    activity_resp = await client.get(f"/api/runs/{run_id}/activity")
    assert activity_resp.status_code == 200
    activity_data = activity_resp.json()
    assert activity_data["run_id"] == run_id

    events = activity_data["events"]
    event_types = [e["event_type"] for e in events]

    # Verify ALL expected event types are present
    expected_types = [
        "run_status_changed",
        "task_status_changed",
        "checklist_gate_evaluated",
        "grades_evaluated",
        "step_completed",
    ]
    for expected in expected_types:
        assert expected in event_types, (
            f"Expected event type '{expected}' not found in activity. Got: {event_types}"
        )

    # Verify specific event counts
    run_status_events = [e for e in events if e["event_type"] == "run_status_changed"]
    assert len(run_status_events) == 2, (
        f"Expected 2 run_status_changed events (draft->active, active->completed), "
        f"got {len(run_status_events)}"
    )

    task_status_events = [e for e in events if e["event_type"] == "task_status_changed"]
    assert len(task_status_events) == 3, (
        f"Expected 3 task_status_changed events "
        f"(pending->building, building->verifying, verifying->completed), "
        f"got {len(task_status_events)}"
    )

    gate_events = [e for e in events if e["event_type"] == "checklist_gate_evaluated"]
    assert len(gate_events) == 1, (
        f"Expected 1 checklist_gate_evaluated event, got {len(gate_events)}"
    )

    grade_events = [e for e in events if e["event_type"] == "grades_evaluated"]
    assert len(grade_events) == 1, f"Expected 1 grades_evaluated event, got {len(grade_events)}"

    step_events = [e for e in events if e["event_type"] == "step_completed"]
    assert len(step_events) == 1, f"Expected 1 step_completed event, got {len(step_events)}"

    # Verify event ordering (timestamps should be monotonically increasing)
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps), "Events should be in chronological order"

    # Verify enrichment: task_title and step_title resolved for task events
    for task_event in task_status_events:
        assert task_event["task_title"] is not None, (
            "task_title should be resolved for task_status_changed events"
        )
        assert task_event["step_title"] is not None, (
            "step_title should be resolved for task_status_changed events"
        )

    # Verify that run_status_changed events show correct transitions
    assert run_status_events[0]["payload"]["old_status"] == "draft"
    assert run_status_events[0]["payload"]["new_status"] == "active"
    assert run_status_events[1]["payload"]["old_status"] == "active"
    assert run_status_events[1]["payload"]["new_status"] == "completed"


# ---------------------------------------------------------------------------
# Test 11: Embedded routine persists across requests (gap-fix wiring)
# ---------------------------------------------------------------------------

EMBEDDED_ROUTINE_PERSIST: dict[str, Any] = {
    "id": "persist-test",
    "name": "Persist Test Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Persist Step",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Persist Task",
                    "task_context": "Verify persistence of embedded routine",
                    "requirements": [{"id": "R1", "desc": "Persisted correctly"}],
                }
            ],
        }
    ],
}


async def test_embedded_routine_persists_across_requests(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Verify that routine_embedded is stored in the database and survives
    across multiple GET requests and through the entire lifecycle.

    This confirms the routine_embedded JSON column on RunModel works end-to-end.
    """
    client, drain = client_and_drain
    # 1. Create run with embedded routine
    resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "proj-persist",
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE_PERSIST,
        },
    )
    assert resp.status_code == 201
    run_data = resp.json()
    run_id = run_data["id"]
    task_id = run_data["steps"][0]["tasks"][0]["id"]

    # Verify embedded routine is in the create response
    assert run_data["routine_embedded"] == EMBEDDED_ROUTINE_PERSIST
    assert run_data["routine_source"] == "embedded"
    assert run_data["routine_id"] == "persist-test"

    # 2. GET the run - verify routine_embedded is returned
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["routine_embedded"] == EMBEDDED_ROUTINE_PERSIST, (
        "routine_embedded should persist in GET response"
    )

    # 3. Start the run
    await _start_run(client, run_id, drain=drain)

    # GET again - still there after status change
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.json()["routine_embedded"] == EMBEDDED_ROUTINE_PERSIST, (
        "routine_embedded should persist after starting the run"
    )

    # 4. Complete a task through the full lifecycle
    await _start_task(client, run_id, task_id)
    await _mark_checklist_done(client, run_id, task_id, "R1")
    await _submit_task(client, run_id, task_id, drain=drain)
    await _grade_item(client, run_id, task_id, "R1", "A", "Perfect")
    await _complete_verification(client, run_id, task_id, drain=drain)

    # 5. GET the run after completion - routine_embedded still there
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200
    final_data = get_resp.json()
    assert final_data["status"] == "completed", "Run should be completed"
    assert final_data["routine_embedded"] == EMBEDDED_ROUTINE_PERSIST, (
        "routine_embedded should persist through entire lifecycle to completion"
    )

    # 6. Verify via list endpoint — routine_embedded is deferred for
    # performance, so the list response returns null for this field.
    list_resp = await client.get("/api/runs")
    assert list_resp.status_code == 200
    runs = list_resp.json()["runs"]
    matching = [r for r in runs if r["id"] == run_id]
    assert len(matching) == 1
    assert matching[0]["routine_embedded"] is None, (
        "routine_embedded should be null in list endpoint (deferred for performance)"
    )
    # But the detail endpoint should still return the full embedded routine.
    detail_resp = await client.get(f"/api/runs/{run_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["routine_embedded"] == EMBEDDED_ROUTINE_PERSIST, (
        "routine_embedded should appear in detail endpoint"
    )
