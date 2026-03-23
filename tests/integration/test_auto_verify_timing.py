"""Tests confirming the auto_verify timing fix.

auto_verify commands execute BEFORE the checklist gate evaluates self-reported
status. This ensures that a builder cannot bypass auto_verify by marking all
checklist items as 'done' when the actual work fails verification.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.event_store import EventStore
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow.signals import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


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


@pytest.fixture
async def api_client(api_client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    """Backward-compatible fixture returning just the client."""
    c, _ = api_client_and_drain
    return c


def _make_run_with_auto_verify(
    project_path: str,
    auto_verify_cmd: str,
    must: bool = True,
) -> Run:
    """Create an in-memory Run with a single must:true auto_verify item."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-timing",
        repo_name="test-repo",
        worktree_path=project_path,
        status=RunStatus.DRAFT,
        routine_id="timing-routine",
        routine_source=RoutineSource.EMBEDDED,
        routine_embedded={
            "id": "timing-routine",
            "name": "Timing Test Routine",
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
                                "items": [
                                    {
                                        "id": "av-check",
                                        "cmd": auto_verify_cmd,
                                        "must": must,
                                    }
                                ],
                                "tail_lines": 10,
                            },
                        }
                    ],
                }
            ],
        },
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="It works",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


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
# Service-level integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_auto_verify_blocks_transition_even_with_done_checklist(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Failing must:true auto_verify blocks BUILDING->VERIFYING even when the
    builder has self-reported all checklist items as done.

    This is the core timing-fix assertion: auto_verify runs *before* the
    checklist gate, so a builder cannot bypass it by pre-marking all items.
    """
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    # 'false' always exits non-zero → must:true item will fail
    run = _make_run_with_auto_verify(str(tmp_path), auto_verify_cmd="false")
    await service.create_run(run)
    await service.start_run("run-timing")
    await service.start_task("run-timing", "task-1")

    # Builder self-reports all checklist items as done; without the timing fix
    # the gate would evaluate these and pass, letting the task reach VERIFYING.
    await service.update_checklist_item("run-timing", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-timing", "task-1")

    # The transition to VERIFYING must be blocked despite a fully-done checklist.
    assert result.new_status != TaskStatus.VERIFYING, (
        "Timing fix broken: task reached VERIFYING despite failing must:true auto_verify"
    )

    # Task must stay in BUILDING so the builder can revise.
    task = await service.get_task("run-timing", "task-1")
    assert task.status == TaskStatus.BUILDING


@pytest.mark.asyncio
async def test_failing_auto_verify_never_bounces_through_verifying(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Failing must:true auto_verify should never emit BUILDING->VERIFYING->BUILDING."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(str(tmp_path), auto_verify_cmd="false")
    await service.create_run(run)
    await service.start_run("run-timing")
    await service.start_task("run-timing", "task-1")
    await service.update_checklist_item("run-timing", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-timing", "task-1")
    assert result.new_status == TaskStatus.BUILDING

    store = EventStore(session)
    events = await store.get_events_for_run("run-timing")
    status_events = [
        e
        for e in events
        if e["type"] == "task_status_changed" and e["payload"].get("task_id") == "task-1"
    ]

    transitions = [
        (e["payload"].get("old_status"), e["payload"].get("new_status")) for e in status_events
    ]
    assert ("building", "verifying") not in transitions
    assert ("verifying", "building") not in transitions


@pytest.mark.asyncio
async def test_passing_auto_verify_allows_transition(session: AsyncSession, tmp_path: Path) -> None:
    """When all must:true auto_verify items pass the transition proceeds to VERIFYING."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    # 'echo ok' always exits zero → must:true item will pass
    run = _make_run_with_auto_verify(str(tmp_path), auto_verify_cmd="echo ok")
    await service.create_run(run)
    await service.start_run("run-timing")
    await service.start_task("run-timing", "task-1")
    await service.update_checklist_item("run-timing", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-timing", "task-1")

    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING

    task = await service.get_task("run-timing", "task-1")
    assert task.status == TaskStatus.VERIFYING


# ---------------------------------------------------------------------------
# API-level integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_auto_verify_configured_failure_returns_409(
    api_client_and_drain: tuple[AsyncClient, DrainFn], tmp_path: Path
) -> None:
    """API pauses run with gate_blocked when auto_verify fails and checklist is not done.

    When auto_verify is configured with a failing command the checklist gate has
    no opportunity to auto-mark items, so any OPEN critical items cause a
    GateBlockedError which pauses the run with pause_reason="gate_blocked".
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
    await api_client.post(f"/api/runs/{run_id}/start")
    await api_client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Submit WITHOUT marking the checklist done — returns 202 (async).
    # auto_verify fails (cmd="false") → no auto-marking → OPEN critical item → GateBlockedError
    resp = await api_client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202, f"Expected 202 from submit, got {resp.status_code}: {resp.text}"

    # Drain signals — the GateBlockedError will pause the run with reason="gate_blocked"
    await drain(run_id)

    # Verify the run is now paused due to gate blocked
    run_resp = await api_client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["status"] == "paused", f"Expected paused, got {run_data['status']}"
    assert run_data["pause_reason"] == "gate_blocked", (
        f"Expected gate_blocked pause_reason, got {run_data['pause_reason']}"
    )
