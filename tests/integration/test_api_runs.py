"""Integration tests for run API endpoints.

WARNING — shared fixture:
    The ``client_and_drain`` / ``client`` fixtures in this module reuse a
    single FastAPI app + in-memory DB across every test in the file (module
    scope). Isolation is the test author's responsibility:

    - Use the ``repo_name`` fixture for *every* ``repo_name`` field you send.
      It returns a unique per-test value (UUID-suffixed); hardcoded names
      collide across tests.
    - For tests that list runs, filter by your own ``repo_name`` — never
      assert on global counts. Other tests' runs are visible in the same DB.
    - Run IDs returned from ``POST /api/runs`` are server-generated UUIDs and
      cannot collide; reference your run only by the ``id`` you received.
    - On teardown, non-terminal runs for this test's ``repo_name`` are
      cancelled (see ``cleanup_runs_for_repo``), so a mid-test failure
      cannot leak executor work into siblings.
"""

import json
from pathlib import Path

from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import RunStatus
from orchestrator.db import RunRepository
from orchestrator.db import SqliteEventStore
from orchestrator.db.access.mutations import save_run
from collections.abc import AsyncGenerator

from tests.integration.conftest import cleanup_runs_for_repo
from tests.integration.signal_helpers import DrainFn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


class NoopRunnerExecutor:
    async def setup_and_spawn(self, run_id: str) -> None:
        pass

    async def cancel_run(self, run_id: str) -> None:
        pass


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


async def _create_run(client: AsyncClient, repo_name: str) -> dict[str, Any]:
    """Helper: create a run and return the response data.

    Pass the per-test ``repo_name`` fixture so the created run is isolated
    from other tests sharing this module's app/DB.
    """
    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": repo_name, "branch": "main"},
    )
    assert response.status_code == 201
    return response.json()


async def _create_run_paused_at_manual_gate(
    client: AsyncClient,
    app: Any,
    repo_name: str,
) -> tuple[str, str]:
    routine_config = {
        "id": "test-manual-gate",
        "name": "test-manual-gate",
        "steps": [
            {
                "id": "step1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task1",
                        "title": "Task 1",
                        "instructions": "Build something",
                    }
                ],
            },
            {
                "id": "step2",
                "title": "Step 2",
                "condition": {"when": "manual"},
                "tasks": [
                    {
                        "id": "task2",
                        "title": "Task 2",
                        "instructions": "Build something else",
                    }
                ],
            },
        ],
    }
    create_resp = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": routine_config,
        },
    )
    assert create_resp.status_code == 201
    run = create_resp.json()
    run_id = run["id"]
    step2_id = run["steps"][1]["id"]

    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        domain_run = await repo.get(run_id)
        domain_run.steps[0].completed = True
        domain_run.current_step_index = 1
        domain_run.status = RunStatus.PAUSED
        domain_run.pause_reason = "manual_gate"
        await save_run(session, domain_run)
        await session.commit()

    return run_id, step2_id


async def test_create_run(client: AsyncClient, repo_name: str) -> None:
    data = await _create_run(client, repo_name)
    assert data["repo_name"] == repo_name
    assert data["routine_id"] == "simple-routine"
    assert data["status"] == "draft"
    assert len(data["steps"]) == 1
    assert len(data["steps"][0]["tasks"]) == 1


async def test_skip_step_writes_step_skipped_to_events_v2_and_activity(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    repo_name: str,
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    try:
        run_id, step_id = await _create_run_paused_at_manual_gate(client, app, repo_name)

        skip_resp = await client.post(f"/api/runs/{run_id}/steps/{step_id}/skip")
        assert skip_resp.status_code == 200
        run_data = skip_resp.json()
        skipped_step = next(step for step in run_data["steps"] if step["id"] == step_id)
        assert skipped_step["skipped"] is True
        assert skipped_step["skip_reason"] == "manual_skip"
        assert skipped_step["completed"] is True
        assert run_data["current_step_index"] == 2
        assert run_data["status"] == "active"
        assert run_data["pause_reason"] is None

        async with app.state.session_factory() as session:
            repo = RunRepository(session)
            persisted_run = await repo.get(run_id)
            assert persisted_run.status == RunStatus.ACTIVE
            assert persisted_run.pause_reason is None
            assert persisted_run.current_step_index == 2
            persisted_step = next(step for step in persisted_run.steps if step.id == step_id)
            assert persisted_step.skipped is True
            assert persisted_step.completed is True
            assert persisted_step.skip_reason == "manual_skip"

            store = SqliteEventStore(session)
            stored_events = await store.get_stream(run_id)

        step_skipped_events = [
            event for event in stored_events if event.event_type == "step_skipped"
        ]
        assert len(step_skipped_events) == 1
        status_events = [
            event for event in stored_events if event.event_type == "run_status_changed"
        ]
        assert status_events
        latest_status_payload = json.loads(status_events[-1].payload)
        assert latest_status_payload["new_status"] == "active"
        assert latest_status_payload["pause_reason"] is None

        activity_resp = await client.get(f"/api/runs/{run_id}/activity?event_type=step_skipped")
        assert activity_resp.status_code == 200
        activity_events = activity_resp.json()["events"]
        assert len(activity_events) == 1
        assert activity_events[0]["event_type"] == "step_skipped"
        assert activity_events[0]["payload"]["step_id"] == step_id
        assert activity_events[0]["payload"]["skip_reason"] == "manual_skip"
        assert activity_events[0]["payload"]["completed"] is True
        assert activity_events[0]["payload"]["current_step_index_after"] == 2
    finally:
        await cleanup_runs_for_repo(client, repo_name)


async def test_create_run_routine_not_found(client: AsyncClient, repo_name: str) -> None:
    response = await client.post(
        "/api/runs",
        json={"routine_id": "nonexistent", "repo_name": repo_name, "branch": "main"},
    )
    assert response.status_code == 404


async def test_list_runs_empty(client: AsyncClient, repo_name: str) -> None:
    # Filter by our unique repo_name — global state may contain other tests' runs.
    response = await client.get("/api/runs", params={"repo_name": repo_name})
    assert response.status_code == 200
    assert response.json() == {"runs": []}


async def test_list_runs(client: AsyncClient, repo_name: str) -> None:
    await _create_run(client, repo_name)
    # Filter by our unique repo_name — other tests share this app's DB.
    response = await client.get("/api/runs", params={"repo_name": repo_name})
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == 1


async def test_list_runs_filter_by_project(client: AsyncClient, repo_name: str) -> None:
    await _create_run(client, repo_name)

    response = await client.get("/api/runs", params={"repo_name": repo_name})
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    # A repo_name we never used returns []; uuid suffix makes a guaranteed-miss key.
    response = await client.get("/api/runs", params={"repo_name": f"other-project-{repo_name}"})
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 0


async def test_list_runs_filter_by_status(client: AsyncClient, repo_name: str) -> None:
    await _create_run(client, repo_name)

    # Combined repo_name + status filter scopes counts to this test's run.
    response = await client.get("/api/runs", params={"repo_name": repo_name, "status": "draft"})
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1

    response = await client.get("/api/runs", params={"repo_name": repo_name, "status": "active"})
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 0


async def test_get_run(client: AsyncClient, repo_name: str) -> None:
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id
    assert data["repo_name"] == repo_name


async def test_get_run_trace_lists_attempts(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]

    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert response.status_code == 200

    response = await client.get(f"/api/runs/{run_id}/trace")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert len(data["attempts"]) == 1
    trace_attempt = data["attempts"][0]
    assert trace_attempt["step_config_id"] == "S-01"
    assert trace_attempt["task_id"] == task_id
    assert trace_attempt["task_config_id"] == "T-01"
    assert trace_attempt["attempt"]["attempt_num"] == 1
    assert trace_attempt["attempt"]["metrics"]["num_actions"] == 0
    assert trace_attempt["action_log"] is None


async def test_get_run_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/runs/nonexistent")
    assert response.status_code == 404


async def test_start_run(client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"
    assert data["started_at"] is not None
    activity = (
        await client.get(f"/api/runs/{run_id}/activity?event_type=run_status_changed")
    ).json()
    assert len(activity["events"]) == 1
    assert activity["events"][0]["event_type"] == "run_status_changed"


async def test_start_run_invalid_state(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    # Start it first
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # Try to start again -> 409
    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 409


async def test_delete_run(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    repo_name: str,
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    response = await client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 204

    async with app.state.session_factory() as session:
        store = SqliteEventStore(session)
        events = await store.get_stream(run_id)

    assert [event.event_type for event in events].count("run_deleted") == 1

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 404


async def test_delete_run_not_found(client: AsyncClient) -> None:
    response = await client.delete("/api/runs/nonexistent")
    assert response.status_code == 404


async def test_pause_run(client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    # Start the run first
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # Pause it
    response = await client.post(f"/api/runs/{run_id}/pause")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "paused"


async def test_resume_run(client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    # Start, then pause, then resume
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"


async def test_pause_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/runs/nonexistent/pause")
    assert response.status_code == 404


async def test_resume_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/runs/nonexistent/resume")
    assert response.status_code == 404


async def test_pause_invalid_state(client: AsyncClient, repo_name: str) -> None:
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    # Try to pause a DRAFT run -> 409
    response = await client.post(f"/api/runs/{run_id}/pause")
    assert response.status_code == 409


async def test_resume_invalid_state(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    # Start the run (ACTIVE), then try to resume without pausing -> 409
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 409


async def _drive_run_to_failed(
    client: AsyncClient, drain: DrainFn, repo_name: str
) -> tuple[str, str]:
    """Create a run and fail it by exhausting 3 verification attempts."""
    created = await _create_run(client, repo_name)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    for _ in range(3):
        await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert resp.status_code == 200
        await drain(run_id)
        await client.put(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
            json={"grade": "D", "grade_reason": "force failure"},
        )
        resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
        assert resp.status_code == 200
        await drain(run_id)

    return run_id, task_id


async def _drive_run_to_completed(
    client: AsyncClient, drain: DrainFn, repo_name: str
) -> tuple[str, str]:
    """Create a run and complete it successfully."""
    created = await _create_run(client, repo_name)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
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
    return run_id, task_id


async def test_recover_run_success_from_failed(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _drive_run_to_failed(client, drain, repo_name)
    run_before = await client.get(f"/api/runs/{run_id}")
    assert run_before.status_code == 200
    assert run_before.json()["status"] == "failed"

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": task_id, "additional_attempts": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] == "paused"
    assert data["pause_reason"] == "recovered"


async def test_recover_run_conflict_when_active(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/recover", json={"target_task_id": task_id})
    assert response.status_code == 409


async def test_recover_run_succeeds_when_paused(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Recovery is allowed on PAUSED runs (e.g., a task failed while the run was paused)."""
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]
    task_id = created["steps"][0]["tasks"][0]["id"]
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/recover", json={"target_task_id": task_id})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "paused"
    assert data["pause_reason"] == "recovered"


async def test_recover_run_conflict_when_completed(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    run_id, task_id = await _drive_run_to_completed(client, drain, repo_name)
    run_before = await client.get(f"/api/runs/{run_id}")
    assert run_before.status_code == 200
    assert run_before.json()["status"] == "completed"

    response = await client.post(f"/api/runs/{run_id}/recover", json={"target_task_id": task_id})
    assert response.status_code == 409


async def test_recover_run_not_found_when_run_missing(client: AsyncClient) -> None:
    response = await client.post(
        "/api/runs/nonexistent/recover",
        json={"target_task_id": "any-task-id"},
    )
    assert response.status_code == 404


async def test_recover_run_not_found_when_target_task_missing(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    client, drain = client_and_drain
    run_id, _task_id = await _drive_run_to_failed(client, drain, repo_name)

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": "missing-task-id"},
    )
    assert response.status_code == 404


async def test_resume_with_agent_change(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any], repo_name: str
) -> None:
    """Resume a paused run while changing the agent runner type and config."""
    client, drain, _, _, app = _shared_app_fixture
    original_executor = getattr(app.state, "runner_executor", None)
    app.state.runner_executor = NoopRunnerExecutor()
    run_id: str | None = None

    try:
        response = await client.post(
            "/api/runs",
            json={
                "routine_id": "simple-routine",
                "repo_name": repo_name,
                "branch": "main",
                "agent_runner_type": "cli_subprocess",
                "agent_runner_config": {"callback_channel": "mcp"},
            },
        )
        assert response.status_code == 201
        run_id = response.json()["id"]

        # Drain lifecycle signals without spawning the managed executor so the
        # run remains active and resumable for this API-level test.
        resp = await client.post(f"/api/runs/{run_id}/start")
        assert resp.status_code == 202
        await drain(run_id)
        resp = await client.post(f"/api/runs/{run_id}/pause")
        assert resp.status_code == 202
        await drain(run_id)

        response = await client.post(
            f"/api/runs/{run_id}/resume",
            json={
                "agent_runner_type": "cli_subprocess",
                "agent_runner_config": {"stdin_mode": "closed"},
            },
        )
        assert response.status_code == 202
        await drain(run_id)
        data = (await client.get(f"/api/runs/{run_id}")).json()

        assert data["status"] == "active"
        assert data["agent_runner_type"] == "cli_subprocess"
        assert data["agent_runner_config"] == {"stdin_mode": "closed"}

        events_response = await client.get(f"/api/runs/{run_id}/activity")
        assert events_response.status_code == 200
        events = events_response.json()["events"]

        agent_changed_events = [e for e in events if e["event_type"] == "agent_changed"]
        assert len(agent_changed_events) == 1
        event = agent_changed_events[0]
        assert event["payload"]["old_agent"] == "cli_subprocess"
        assert event["payload"]["new_agent"] == "cli_subprocess"
        assert event["payload"]["old_agent_runner_config"] == {"callback_channel": "mcp"}
        assert event["payload"]["new_agent_runner_config"] == {"stdin_mode": "closed"}
    finally:
        await cleanup_runs_for_repo(client, repo_name)
        app.state.runner_executor = original_executor


async def test_resume_without_agent_change(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Resume a paused run without changing the agent (no body or empty body)."""
    client, drain = client_and_drain

    # Set initial agent (this is the run we actually exercise; the earlier
    # _create_run call from the original test was unused).
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": repo_name,
            "branch": "main",
            "agent_runner_type": "cli_subprocess",
            "agent_runner_config": {"stdin_mode": "open"},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Start and pause the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    # Resume without changing agent (no request body)
    response = await client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()

    # Verify the run is active with the same agent
    assert data["status"] == "active"
    assert data["agent_runner_type"] == "cli_subprocess"
    assert data["agent_runner_config"] == {"stdin_mode": "open"}

    # Verify no agent_changed event was emitted
    events_response = await client.get(f"/api/runs/{run_id}/activity")
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    agent_changed_events = [e for e in events if e["event_type"] == "agent_changed"]
    assert len(agent_changed_events) == 0


async def test_resume_with_config_only_change(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Resume a paused run while changing only the agent runner config (not the type)."""
    client, drain = client_and_drain
    # Create a run with initial agent runner config
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": repo_name,
            "branch": "main",
            "agent_runner_type": "cli_subprocess",
            "agent_runner_config": {"stdin_mode": "close", "model": "gpt-4"},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    # Start and pause the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    # Resume with updated config only (no agent_runner_type change)
    response = await client.post(
        f"/api/runs/{run_id}/resume",
        json={
            "agent_runner_config": {"stdin_mode": "open", "model": "claude-3"},
        },
    )
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()

    # Verify the run is active with same agent runner type but updated config
    assert data["status"] == "active"
    assert data["agent_runner_type"] == "cli_subprocess"
    assert data["agent_runner_config"] == {"stdin_mode": "open", "model": "claude-3"}

    # Verify the agent change event was emitted (config changed even though type didn't)
    events_response = await client.get(f"/api/runs/{run_id}/activity")
    assert events_response.status_code == 200
    events = events_response.json()["events"]

    # Find the agent_changed event
    agent_changed_events = [e for e in events if e["event_type"] == "agent_changed"]
    assert len(agent_changed_events) == 1
    event = agent_changed_events[0]
    assert event["payload"]["old_agent"] == "cli_subprocess"
    assert event["payload"]["new_agent"] == "cli_subprocess"
    assert event["payload"]["old_agent_runner_config"] == {"stdin_mode": "close", "model": "gpt-4"}
    assert event["payload"]["new_agent_runner_config"] == {
        "stdin_mode": "open",
        "model": "claude-3",
    }


async def test_create_run_with_agent_runner_config(client: AsyncClient, repo_name: str) -> None:
    """agent_runner_config is stored and returned in the response."""
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": repo_name,
            "branch": "main",
            "agent_runner_type": "cli_subprocess",
            "agent_runner_config": {"model": "claude-4", "callback_channel": "mcp"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_runner_type"] == "cli_subprocess"
    assert data["agent_runner_config"]["model"] == "claude-4"
    assert data["agent_runner_config"]["callback_channel"] == "mcp"


async def test_create_run_agent_runner_config_defaults_to_empty(
    client: AsyncClient, repo_name: str
) -> None:
    """agent_runner_config defaults to empty dict when not provided."""
    data = await _create_run(client, repo_name)
    assert data["agent_runner_config"] == {}


# --- B2: cancel_run and recent_hours tests ---


async def test_cancel_run_from_active(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Cancel an active run -> FAILED."""
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "failed"
    assert data["completed_at"] is not None


async def test_cancel_run_from_paused(
    client_and_drain: tuple[AsyncClient, DrainFn], repo_name: str
) -> None:
    """Cancel a paused run -> FAILED."""
    client, drain = client_and_drain
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "failed"
    assert data["completed_at"] is not None


async def test_cancel_run_from_draft_invalid(client: AsyncClient, repo_name: str) -> None:
    """Cancel from DRAFT returns 409."""
    created = await _create_run(client, repo_name)
    run_id = created["id"]

    response = await client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 409


async def test_cancel_run_not_found(client: AsyncClient) -> None:
    """Cancel a nonexistent run returns 404."""
    response = await client.post("/api/runs/nonexistent/cancel")
    assert response.status_code == 404


async def test_list_runs_recent_hours(client: AsyncClient, repo_name: str) -> None:
    """recent_hours filter returns recently created runs.

    Other tests share this app's DB, so the global list can contain many
    runs. We assert that *our* run appears, not on the global count.
    """
    await _create_run(client, repo_name)

    response = await client.get("/api/runs?recent_hours=1")
    assert response.status_code == 200
    runs_for_me = [r for r in response.json()["runs"] if r["repo_name"] == repo_name]
    assert len(runs_for_me) == 1

    response = await client.get("/api/runs?recent_hours=24")
    assert response.status_code == 200
    runs_for_me = [r for r in response.json()["runs"] if r["repo_name"] == repo_name]
    assert len(runs_for_me) == 1


# --- E1: Embedded routine tests ---

EMBEDDED_ROUTINE: dict[str, Any] = {
    "id": "embedded-test",
    "name": "Embedded Test Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Do the embedded thing",
                    "requirements": [{"id": "R1", "desc": "It works"}],
                }
            ],
        }
    ],
}


async def test_create_run_with_embedded_routine(client: AsyncClient, repo_name: str) -> None:
    """Create a run using an inline embedded routine dict."""
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_name"] == repo_name
    assert data["routine_id"] == "embedded-test"
    assert data["routine_source"] == "embedded"
    assert data["routine_embedded"] == EMBEDDED_ROUTINE
    assert data["status"] == "draft"
    assert len(data["steps"]) == 1
    assert len(data["steps"][0]["tasks"]) == 1
    assert data["steps"][0]["config_id"] == "S-01"
    assert data["steps"][0]["tasks"][0]["config_id"] == "T-01"


async def test_create_run_embedded_routine_persisted(client: AsyncClient, repo_name: str) -> None:
    """Embedded routine is persisted and returned on GET."""
    create_resp = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["routine_embedded"] == EMBEDDED_ROUTINE
    assert data["routine_source"] == "embedded"


async def test_create_run_both_routine_id_and_embedded_fails(
    client: AsyncClient, repo_name: str
) -> None:
    """Providing both routine_id and routine_embedded returns 422."""
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": EMBEDDED_ROUTINE,
        },
    )
    assert response.status_code == 422


async def test_create_run_neither_routine_id_nor_embedded_fails(
    client: AsyncClient, repo_name: str
) -> None:
    """Providing neither routine_id nor routine_embedded returns 422."""
    response = await client.post(
        "/api/runs",
        json={"repo_name": repo_name, "branch": "main"},
    )
    assert response.status_code == 422


async def test_create_run_embedded_routine_invalid_schema(
    client: AsyncClient, repo_name: str
) -> None:
    """Embedded routine with invalid schema returns 422."""
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": {"id": "bad", "name": "Bad"},
            # Missing required 'steps' field
        },
    )
    assert response.status_code == 422


async def test_create_run_embedded_routine_with_ref_rejected(
    client: AsyncClient, repo_name: str
) -> None:
    """Embedded routine containing 'ref' key is rejected by RoutineConfig validator."""
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": {
                "id": "bad-ref",
                "name": "Bad Ref Routine",
                "ref": "some-template",
                "steps": [
                    {
                        "id": "S-01",
                        "title": "Step",
                        "tasks": [
                            {
                                "id": "T-01",
                                "title": "Task",
                                "task_context": "Context",
                            }
                        ],
                    }
                ],
            },
        },
    )
    assert response.status_code == 422


async def test_create_run_embedded_with_config(client: AsyncClient, repo_name: str) -> None:
    """Embedded routine run can include runtime config."""
    routine_with_inputs: dict[str, Any] = {
        "id": "with-inputs",
        "name": "Routine With Inputs",
        "inputs": [
            {"name": "target_branch", "required": True},
        ],
        "steps": [
            {
                "id": "S-01",
                "title": "Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task",
                        "task_context": "Deploy to branch",
                        "requirements": [{"id": "R1", "desc": "Deployed"}],
                    }
                ],
            }
        ],
    }
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": routine_with_inputs,
            "config": {"target_branch": "main"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["config"]["target_branch"] == "main"


async def test_create_run_embedded_missing_required_input(
    client: AsyncClient, repo_name: str
) -> None:
    """Embedded routine with missing required input returns 422."""
    routine_with_inputs: dict[str, Any] = {
        "id": "with-inputs",
        "name": "Routine With Inputs",
        "inputs": [
            {"name": "target_branch", "required": True},
        ],
        "steps": [
            {
                "id": "S-01",
                "title": "Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task",
                        "task_context": "Deploy to branch",
                    }
                ],
            }
        ],
    }
    response = await client.post(
        "/api/runs",
        json={
            "repo_name": repo_name,
            "branch": "main",
            "routine_embedded": routine_with_inputs,
            # No config with target_branch
        },
    )
    assert response.status_code == 422


async def test_run_response_includes_cost_estimation(client: AsyncClient, repo_name: str) -> None:
    """Test that cost estimation is populated when token data exists."""
    data = await _create_run(client, repo_name)
    run_id = data["id"]

    # Initially, no tokens, so no cost estimate
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["total_tokens_read"] == 0
    assert data["total_tokens_write"] == 0
    assert data["estimated_cost_usd"] is None
    assert data["cost_disclaimer"] is None

    # Simulate task execution by updating the run state with token data
    from orchestrator.db import RunRepository

    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    session_factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.total_tokens_read = 100000
        run.total_tokens_write = 50000
        run.total_tokens_cache = 10000
        await save_run(repo.session, run)
        await session.commit()

    # Now fetch the run again
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()

    # Should now have cost estimation
    assert data["total_tokens_read"] == 100000
    assert data["total_tokens_write"] == 50000
    assert data["total_tokens_cache"] == 10000
    assert data["estimated_cost_usd"] is not None
    assert data["estimated_cost_usd"] > 0
    assert data["cost_disclaimer"] is not None
    assert "gpt-4o" in data["cost_disclaimer"]
    assert "Estimate only" in data["cost_disclaimer"]


# --- token_usage_by_model API exposure tests (R6, R7, R8) ---


async def _inject_run_token_usage(
    client: AsyncClient,
    run_id: str,
    token_usage: list[dict[str, Any]],
) -> None:
    """Helper: write token_usage_by_model directly to the RunModel row."""
    from sqlalchemy import select

    from orchestrator.db import RunModel

    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    session_factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)

    async with session_factory() as session:
        result = await session.execute(select(RunModel).where(RunModel.id == run_id))
        run_model = result.scalar_one()
        run_model.token_usage_by_model = token_usage or None
        await session.commit()


async def test_get_run_returns_token_usage_by_model_with_all_fields(
    client: AsyncClient, repo_name: str
) -> None:
    """R6: GET /api/runs/{id} returns token_usage_by_model with all expected fields."""
    data = await _create_run(client, repo_name)
    run_id = data["id"]

    # Inject per-model token data
    usage_record = {
        "model": "claude-sonnet-4-6",
        "cache_read_tokens": 500_000,
        "cache_creation_tokens": 200_000,
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cost_per_m_cache_read": 0.30,
        "cost_per_m_cache_creation": 3.75,
        "cost_per_m_input": 3.00,
        "cost_per_m_output": 15.00,
    }
    await _inject_run_token_usage(client, run_id, [usage_record])

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()

    usage_list = body["token_usage_by_model"]
    assert isinstance(usage_list, list)
    assert len(usage_list) == 1

    entry = usage_list[0]
    assert entry["model"] == "claude-sonnet-4-6"
    assert entry["cache_read_tokens"] == 500_000
    assert entry["cache_creation_tokens"] == 200_000
    assert entry["input_tokens"] == 1_000_000
    assert entry["output_tokens"] == 100_000
    assert entry["cost_per_m_cache_read"] == pytest.approx(0.30)
    assert entry["cost_per_m_cache_creation"] == pytest.approx(3.75)
    assert entry["cost_per_m_input"] == pytest.approx(3.00)
    assert entry["cost_per_m_output"] == pytest.approx(15.00)
    assert "total_cost_usd" in entry
    assert entry["total_cost_usd"] > 0


async def test_get_run_empty_token_usage_returns_empty_list_and_no_crash(
    client: AsyncClient, repo_name: str
) -> None:
    """R7: Old runs with no token_usage_by_model return [] without error.

    estimated_cost_usd falls back to legacy token-based estimation (>= 0.0)
    or None — the important thing is no crash and token_usage_by_model == [].
    """
    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]
    session_factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)

    data = await _create_run(client, repo_name)
    run_id = data["id"]

    # Simulate old run: no per-model data, but has legacy token counts
    from sqlalchemy import select

    from orchestrator.db import RunModel

    async with session_factory() as session:
        result = await session.execute(select(RunModel).where(RunModel.id == run_id))
        run_model = result.scalar_one()
        run_model.token_usage_by_model = None  # no per-model data
        run_model.total_tokens_read = 200_000
        run_model.total_tokens_write = 80_000
        run_model.total_tokens_cache = 10_000
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200  # no crash
    body = response.json()

    assert body["token_usage_by_model"] == []

    # Legacy fallback: estimated_cost_usd should be a non-negative number (not None)
    cost = body["estimated_cost_usd"]
    assert cost is not None
    assert cost >= 0.0


async def test_get_run_estimated_cost_equals_sum_of_per_model_costs(
    client: AsyncClient, repo_name: str
) -> None:
    """R8: estimated_cost_usd equals the sum of per-model total_cost_usd values."""
    data = await _create_run(client, repo_name)
    run_id = data["id"]

    usage_records = [
        {
            "model": "claude-sonnet-4-6",
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "input_tokens": 1_000_000,
            "output_tokens": 100_000,
            "cost_per_m_cache_read": 0.30,
            "cost_per_m_cache_creation": 3.75,
            "cost_per_m_input": 3.00,
            "cost_per_m_output": 15.00,
        },
        {
            "model": "claude-haiku-4-5",
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "input_tokens": 500_000,
            "output_tokens": 50_000,
            "cost_per_m_cache_read": 0.08,
            "cost_per_m_cache_creation": 1.00,
            "cost_per_m_input": 0.80,
            "cost_per_m_output": 4.00,
        },
    ]
    await _inject_run_token_usage(client, run_id, usage_records)

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()

    usage_list = body["token_usage_by_model"]
    assert len(usage_list) == 2

    expected_total = sum(entry["total_cost_usd"] for entry in usage_list)
    assert body["estimated_cost_usd"] == pytest.approx(expected_total, rel=1e-5)
    assert body["cost_disclaimer"] == "Per-model cost from embedded rates."


# --- Agent error handler tests ---


async def test_agent_error_handlers_registered(client: AsyncClient) -> None:
    """Verify that agent error handlers are registered in the FastAPI app.

    Note: These handlers return specific HTTP status codes:
    - AgentNotAvailableError -> 503 Service Unavailable
    - AgentExecutionError -> 500 Internal Server Error
    - AgentCancelledError -> 499 Client Closed Request

    However, these errors are raised during agent.execute() calls, which happen
    outside the API request/response cycle. The current architecture does not
    have API endpoints that directly execute agents (agents are executed
    externally or via background tasks).

    This test verifies the handlers exist but cannot trigger them through the API.
    Full end-to-end testing would require:
    1. An endpoint that triggers agent execution synchronously, OR
    2. A background task system that can propagate exceptions to API responses

    For now, we verify handler registration and document the gap.
    """
    from orchestrator.runners.errors import (
        AgentCancelledError,
        AgentExecutionError,
        AgentNotAvailableError,
    )

    app = cast(FastAPI, client._transport.app)  # type: ignore[attr-defined]

    # Verify error handlers are registered
    error_handlers = app.exception_handlers

    # Check that our agent error types have handlers
    assert AgentNotAvailableError in error_handlers
    assert AgentExecutionError in error_handlers
    assert AgentCancelledError in error_handlers


async def test_create_run_produces_run_created_event_in_events_v2(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    repo_name: str,
) -> None:
    """POST /api/runs must produce a RunCreated event in events_v2 for the new run_id."""
    client, _drain, _, _, app = _shared_app_fixture

    response = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": repo_name, "branch": "main"},
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    from orchestrator.db import SqliteEventStore

    session_factory = app.state.session_factory
    async with session_factory() as session:
        store = SqliteEventStore(session)
        events = await store.get_stream(run_id)

    event_types = [e.event_type for e in events]
    assert event_types.count("run_created") == 1
    assert event_types.count("step_created") == 1
    assert event_types.count("task_created") == 1

    run_created = next(e for e in events if e.event_type == "run_created")
    assert run_created.aggregate_id == run_id
    payload = json.loads(run_created.payload)
    assert payload["run_id"] == run_id
    assert payload["repo_name"] == repo_name
    assert payload["run_snapshot"] == {}

    await cleanup_runs_for_repo(client, repo_name)
