"""Tests for RunStatus.STOPPING state machine transitions and API guards."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db import (
    RunRepository,
    SqliteEventStore,
    create_engine,
    create_session_factory,
    init_db,
    save_run,
)
from orchestrator.state import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import InMemorySignalTransport, InvalidTransitionError, WorkflowService


FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# API integration tests: 409 for STOPPING runs
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_and_app() -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, "local")],
    )
    await init_db(app.state.engine)
    app.state.signal_transport = InMemorySignalTransport()
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await app.state.engine.dispose()


async def _force_stopping(app: Any, run_id: str) -> None:
    """Directly set a run's status to STOPPING in the database."""
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.status = RunStatus.STOPPING
        await save_run(repo.session, run)
        await session.commit()


async def _create_and_start_run(client: AsyncClient) -> str:
    """Create and start a run, return run_id."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    return run_id


async def test_api_stopping_exposed_in_rest(client_and_app: tuple[AsyncClient, Any]) -> None:
    """STOPPING status is exposed in the REST API (not hidden/remapped)."""
    client, app = client_and_app
    run_id = await _create_and_start_run(client)
    await _force_stopping(app, run_id)

    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopping"


async def test_api_resume_stopping_returns_409(client_and_app: tuple[AsyncClient, Any]) -> None:
    """API returns 409 when resuming a STOPPING run."""
    client, app = client_and_app
    run_id = await _create_and_start_run(client)
    await _force_stopping(app, run_id)

    resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resp.status_code == 409


async def test_api_pause_stopping_returns_409(client_and_app: tuple[AsyncClient, Any]) -> None:
    """API returns 409 when pausing a STOPPING run."""
    client, app = client_and_app
    run_id = await _create_and_start_run(client)
    await _force_stopping(app, run_id)

    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 409


async def test_api_cancel_stopping_returns_409(client_and_app: tuple[AsyncClient, Any]) -> None:
    """API returns 409 when cancelling a STOPPING run."""
    client, app = client_and_app
    run_id = await _create_and_start_run(client)
    await _force_stopping(app, run_id)

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 409


async def test_api_recover_stopping_returns_409(client_and_app: tuple[AsyncClient, Any]) -> None:
    """API returns 409 when recovering a STOPPING run (restart)."""
    client, app = client_and_app
    run_id = await _create_and_start_run(client)
    await _force_stopping(app, run_id)

    resp = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": "task-1"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Service-level tests: in-flight task signals during shutdown
#
# Truth table for submit_for_verification and complete_verification:
#
#   submit_for_verification (BUILDING → VERIFYING):
#     ACTIVE   → allowed  — normal path
#     STOPPING → allowed  — agent's final cycle; gate outcome determines next state
#     PAUSED   → rejected — run is already paused; no agent should be submitting
#     FAILED   → rejected — terminal
#     COMPLETED→ rejected — terminal
#     DRAFT    → rejected — run never started
#
#   complete_verification (VERIFYING → outcome):
#     ACTIVE   → allowed  — normal path
#     STOPPING → allowed  — verifier's final cycle; outcome recorded
#     PAUSED   → allowed  — verifier completed after run was paused; outcome recorded,
#                           no new work spawned because run remains paused
#     FAILED   → rejected — terminal
#     COMPLETED→ rejected — terminal
#     DRAFT    → rejected — run never started
#
# Rationale for STOPPING/PAUSED exceptions:
#   When a pause is requested the run immediately moves to STOPPING and a PAUSE
#   signal is enqueued. An agent already mid-cycle may enqueue ACTIVITY_COMPLETED
#   or ACTIVITY_VERIFIED before (or just after) the PAUSE is processed. Discarding
#   those signals would leave the task permanently stuck in BUILDING or VERIFYING
#   with no way to recover without a manual restart. Processing them is safe:
#   - submit_for_verification on STOPPING: task moves to VERIFYING; run then becomes
#     PAUSED via the PAUSE signal; no verifier agent is spawned.
#   - complete_verification on STOPPING or PAUSED: outcome is recorded; the executor
#     loop that would normally spawn the next step is not running (or will exit on
#     status check), so no new work starts.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def svc_session() -> AsyncGenerator[tuple[WorkflowService, AsyncSession], None]:
    """In-memory DB with migrations; yields (service, session) for direct service calls."""
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield WorkflowService(session), session
    await engine.dispose()


def _make_run_with_checklist() -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
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
                                desc="Work complete",
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


async def _setup_building_task(
    svc: WorkflowService,
) -> None:
    """Create run, start it, mark checklist done, and start the task (→ BUILDING)."""
    await svc.create_run(_make_run_with_checklist())
    await svc.apply_start_run("run-1")
    await svc.start_task("run-1", "task-1")
    await svc.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)


async def _setup_verifying_task(svc: WorkflowService) -> None:
    """Build on _setup_building_task: also submit, leaving task in VERIFYING."""
    await _setup_building_task(svc)
    result = await svc.submit_for_verification("run-1", "task-1")
    assert result.success and result.new_status == TaskStatus.VERIFYING


@pytest.mark.asyncio
async def test_submit_for_verification_accepted_while_stopping(
    svc_session: tuple[WorkflowService, AsyncSession],
) -> None:
    """submit_for_verification succeeds when run is STOPPING (BUILDING → VERIFYING).

    Scenario: agent enqueues ACTIVITY_COMPLETED while the run is in STOPPING state
    (pause requested, PAUSE signal not yet consumed). The task should still gate-check
    and transition to VERIFYING. No verifier spawns because the run is not ACTIVE.
    """
    svc, _ = svc_session
    await _setup_building_task(svc)
    await svc.apply_stop_run("run-1")  # ACTIVE → STOPPING

    result = await svc.submit_for_verification("run-1", "task-1")

    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING


@pytest.mark.asyncio
async def test_apply_stop_run_writes_events_v2_and_projects_stopping(
    svc_session: tuple[WorkflowService, AsyncSession],
) -> None:
    svc, session = svc_session
    await _setup_building_task(svc)

    stopped = await svc.apply_stop_run("run-1")

    assert stopped.status == RunStatus.STOPPING
    reloaded = await svc.get_run("run-1")
    assert reloaded.status == RunStatus.STOPPING
    events = await SqliteEventStore(session).get_stream("run-1")
    status_events = [event for event in events if event.event_type == "run_status_changed"]
    assert status_events[-1].event_type == "run_status_changed"
    assert '"old_status":"active"' in status_events[-1].payload
    assert '"new_status":"stopping"' in status_events[-1].payload


@pytest.mark.asyncio
async def test_submit_for_verification_rejected_while_paused(
    svc_session: tuple[WorkflowService, AsyncSession],
) -> None:
    """submit_for_verification raises when run is PAUSED.

    PAUSED means the run has fully stopped; no agent should be submitting work.
    If an ACTIVITY_COMPLETED signal arrives for an already-PAUSED run, it is
    discarded (stays unhandled in queue until cleaned up).
    """
    svc, _ = svc_session
    await _setup_building_task(svc)
    await svc.apply_stop_run("run-1")  # ACTIVE → STOPPING
    await svc.apply_pause_run("run-1", reason="manual_pause")  # STOPPING → PAUSED

    with pytest.raises(InvalidTransitionError):
        await svc.submit_for_verification("run-1", "task-1")


@pytest.mark.asyncio
async def test_complete_verification_accepted_while_stopping(
    svc_session: tuple[WorkflowService, AsyncSession],
) -> None:
    """complete_verification succeeds when run is STOPPING (VERIFYING → outcome).

    Scenario: verifier enqueues ACTIVITY_VERIFIED while the run is STOPPING.
    The verification outcome is recorded. No next step is spawned because the
    executor loop exits once it sees the run is not ACTIVE.
    """
    svc, _ = svc_session
    await _setup_verifying_task(svc)
    await svc.apply_stop_run("run-1")  # ACTIVE → STOPPING

    result = await svc.complete_verification("run-1", "task-1")

    # Outcome depends on grades; with no grades submitted, the task remains
    # in VERIFYING (incomplete verification). The key assertion is no exception.
    assert result is not None


@pytest.mark.asyncio
async def test_complete_verification_accepted_while_paused(
    svc_session: tuple[WorkflowService, AsyncSession],
) -> None:
    """complete_verification succeeds when run is PAUSED (VERIFYING → outcome).

    Scenario: run was paused after verification started (e.g., another task's gate
    failed or a manual pause). The verifier completes its work and reports back.
    The outcome is recorded; no new work starts because the run is paused.
    """
    svc, _ = svc_session
    await _setup_verifying_task(svc)
    await svc.apply_stop_run("run-1")  # ACTIVE → STOPPING
    await svc.apply_pause_run("run-1", reason="manual_pause")  # STOPPING → PAUSED

    result = await svc.complete_verification("run-1", "task-1")

    assert result is not None


@pytest.mark.asyncio
async def test_complete_verification_rejected_while_failed(
    svc_session: tuple[WorkflowService, AsyncSession],
) -> None:
    """complete_verification raises when run is FAILED (terminal state).

    FAILED is a terminal state; verification outcomes are irrelevant and
    must not be silently accepted.
    """
    svc, _ = svc_session
    await _setup_verifying_task(svc)
    await svc.apply_cancel_run("run-1")  # → FAILED (cancel from ACTIVE)

    with pytest.raises(InvalidTransitionError):
        await svc.complete_verification("run-1", "task-1")
