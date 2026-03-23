"""Integration tests for UserManagedAgent with real WorkflowService.

Tests that the submit notification bridge works end-to-end:
register event on service A, call submit_for_verification on service B
(different instance, same shared registry), verify event fires.

Also tests the full production path where the REST API submit endpoint
goes through FastAPI DI, creating a fresh WorkflowService that shares
the SubmitEventRegistry with the waiting agent.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from orchestrator.runners.errors import AgentTimeoutError
from orchestrator.runners.agents.user_managed.agent import UserManagedAgent
from orchestrator.runners.types import ExecutionContext
from orchestrator.api.app import create_app
from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import SubmitEventRegistry, WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    factory = create_session_factory(db_engine)
    async with factory() as s:
        yield s


@pytest.fixture
def registry() -> SubmitEventRegistry:
    """Shared submit event registry — the same instance for all services."""
    return SubmitEventRegistry()


@pytest.fixture
def service(session: AsyncSession, registry: SubmitEventRegistry) -> WorkflowService:
    return WorkflowService(session, submit_event_registry=registry)


def _make_run() -> Run:
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
                                desc="Complete the task",
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


async def test_submit_notification_fires_event(service: WorkflowService) -> None:
    """When submit_for_verification is called, the registered event fires."""
    run = await service.create_run(_make_run())
    await service.start_run(run.id)
    await service.start_task(run.id, "task-1")
    await service.update_checklist_item(run.id, "task-1", "R1", ChecklistStatus.DONE)

    event = service.register_submit_event("task-1")
    assert not event.is_set()

    await service.submit_for_verification(run.id, "task-1")
    assert event.is_set()


async def test_submit_notification_no_event_registered(service: WorkflowService) -> None:
    """submit_for_verification works normally when no event is registered."""
    run = await service.create_run(_make_run())
    await service.start_run(run.id)
    await service.start_task(run.id, "task-1")
    await service.update_checklist_item(run.id, "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification(run.id, "task-1")
    assert result is not None


async def test_cross_instance_submit_notification(
    session: AsyncSession,
    registry: SubmitEventRegistry,
) -> None:
    """Event registered on service A fires when service B calls submit_for_verification.

    This is the critical test: in production, the UserManagedAgent registers
    an event via one WorkflowService instance, while the REST/MCP submit
    endpoint creates a *different* WorkflowService instance.  Both must share
    the same SubmitEventRegistry for the notification to reach the agent.
    """
    service_a = WorkflowService(session, submit_event_registry=registry)
    service_b = WorkflowService(session, submit_event_registry=registry)

    run = await service_a.create_run(_make_run())
    await service_a.start_run(run.id)
    await service_a.start_task(run.id, "task-1")
    await service_a.update_checklist_item(run.id, "task-1", "R1", ChecklistStatus.DONE)

    # Agent registers on service A
    event = service_a.register_submit_event("task-1")
    assert not event.is_set()

    # Submit happens on service B (simulates a different request)
    await service_b.submit_for_verification(run.id, "task-1")

    # Event should still fire because both share the registry
    assert event.is_set()


async def test_user_managed_agent_cross_instance(
    session: AsyncSession,
    registry: SubmitEventRegistry,
) -> None:
    """UserManagedAgent.execute returns when submit comes from a different service instance."""
    service_agent = WorkflowService(session, submit_event_registry=registry)
    service_api = WorkflowService(session, submit_event_registry=registry)

    run = await service_agent.create_run(_make_run())
    await service_agent.start_run(run.id)
    await service_agent.start_task(run.id, "task-1")
    await service_agent.update_checklist_item(run.id, "task-1", "R1", ChecklistStatus.DONE)

    agent = UserManagedAgent(service=service_agent, timeout_minutes=1)

    ctx = ExecutionContext(
        run_id=run.id,
        task_id="task-1",
        working_dir="/tmp",
        prompt="Complete the work",
        requirements=["R1"],
    )

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    async def submit_via_different_service() -> None:
        await asyncio.sleep(0.05)
        # This simulates the REST/MCP handler calling submit on a fresh service
        await service_api.submit_for_verification(run.id, "task-1")

    task = asyncio.create_task(submit_via_different_service())
    result = await agent.execute(ctx, on_update, on_submit)
    await task

    assert result.success is True


async def test_user_managed_agent_timeout_with_real_service(
    service: WorkflowService,
) -> None:
    """UserManagedAgent times out when no submit is called."""
    run = await service.create_run(_make_run())
    await service.start_run(run.id)
    await service.start_task(run.id, "task-1")

    agent = UserManagedAgent(service=service, timeout_minutes=0)

    ctx = ExecutionContext(
        run_id=run.id,
        task_id="task-1",
        working_dir="/tmp",
        prompt="Complete the work",
        requirements=["R1"],
    )

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    with pytest.raises(AgentTimeoutError):
        await agent.execute(ctx, on_update, on_submit)


# --- Full-stack tests using the FastAPI app ---


async def test_user_managed_agent_wakes_from_rest_api_submit() -> None:
    """Full production path: agent waits while REST POST /submit fires the shared registry.

    This is the most important integration test for UserManagedAgent.
    It exercises the actual DI path: FastAPI deps.py creates a fresh
    WorkflowService that gets the SubmitEventRegistry from app.state.
    When that service calls submit_for_verification (via signal drain),
    the registry notifies the agent's event, waking it up.
    """
    from orchestrator.workflow.signals import InMemorySignalTransport
    from tests.integration.signal_helpers import make_drain_fn

    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    drain = make_drain_fn(app, signal_transport)

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Set up run via REST API (creates data in the shared in-memory DB)
        resp = await client.post(
            "/api/runs",
            json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
        )
        assert resp.status_code == 201
        run_id = resp.json()["id"]
        task_id = resp.json()["steps"][0]["tasks"][0]["id"]

        await client.post(f"/api/runs/{run_id}/start")
        await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
        await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )

        # Create agent service that shares the app's SubmitEventRegistry
        registry = app.state.submit_event_registry
        session_factory = app.state.session_factory
        async with session_factory() as agent_session:
            agent_service = WorkflowService(agent_session, submit_event_registry=registry)
            agent = UserManagedAgent(service=agent_service, timeout_minutes=1)

            ctx = ExecutionContext(
                run_id=run_id,
                task_id=task_id,
                working_dir="/tmp",
                prompt="Complete the work",
                requirements=["R1"],
            )

            async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
                pass

            async def on_submit() -> None:
                pass

            async def submit_via_rest_api_and_drain() -> None:
                await asyncio.sleep(0.05)
                resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
                assert resp.status_code == 202
                # Drain signals so submit_for_verification is called and the agent wakes up
                await drain(run_id)

            bg = asyncio.create_task(submit_via_rest_api_and_drain())
            result = await agent.execute(ctx, on_update, on_submit)
            await bg

            assert result.success is True

    await app.state.engine.dispose()
