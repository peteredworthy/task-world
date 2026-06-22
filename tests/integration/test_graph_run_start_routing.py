from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import SignalConsumer, WorkflowService


def _routine_payload() -> dict[str, Any]:
    return {
        "id": "graph-routing",
        "name": "Graph Routing",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [{"id": "task-1", "title": "Task"}],
            }
        ],
    }


async def test_create_run_records_execution_mode(
    _shared_app_fixture: tuple[AsyncClient, Any, Path, Path, Any],
    git_repo: Path,
) -> None:
    client, _drain, _, _, _ = _shared_app_fixture

    response = await client.post(
        "/api/runs",
        json={
            "repo_name": git_repo.name,
            "branch": "main",
            "routine_embedded": _routine_payload(),
            "execution_mode": "graph",
            "agent_runner_type": "cli_subprocess",
        },
    )

    assert response.status_code == 201
    created = response.json()
    fetched = await client.get(f"/api/runs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["execution_mode"] == "graph"


async def test_explicit_legacy_run_records_execution_mode_legacy(
    _shared_app_fixture: tuple[AsyncClient, Any, Path, Path, Any],
    git_repo: Path,
) -> None:
    client, _drain, _, _, _ = _shared_app_fixture

    response = await client.post(
        "/api/runs",
        json={
            "repo_name": git_repo.name,
            "branch": "main",
            "routine_embedded": _routine_payload(),
            "execution_mode": "legacy",
            "agent_runner_type": "cli_subprocess",
        },
    )

    assert response.status_code == 201
    assert response.json()["execution_mode"] == "legacy"


@pytest.mark.asyncio
async def test_run_start_routes_graph_mode_to_driver(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "routing.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    graph_called = asyncio.Event()
    workflow_called = False
    called_run_ids: list[str] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def graph_runner(run_id: str) -> None:
        called_run_ids.append(run_id)
        graph_called.set()

    async def workflow_runner(workflow: Any) -> None:
        nonlocal workflow_called
        workflow_called = True

    try:
        run_id = "graph-routing-run"
        await _create_run(session_factory, run_id, execution_mode="graph")
        consumer = SignalConsumer(
            session_factory,
            create_service,
            workflow_runner=workflow_runner,
            graph_runner=graph_runner,
            poll_interval=100.0,
        )
        async with session_factory() as session:
            service = await create_service(session)
            await consumer._handle_run_start(run_id, None, session, service)

        await asyncio.wait_for(graph_called.wait(), timeout=2)
        assert called_run_ids == [run_id]
        assert workflow_called is False
        assert run_id not in consumer._active_workflows
    finally:
        await engine.dispose()


async def test_graph_cancel_route_appends_graph_cancel_before_signal_drain(
    _shared_app_fixture: tuple[AsyncClient, Any, Path, Path, Any],
) -> None:
    client, drain, _, _, app = _shared_app_fixture
    run_id = "graph-cancel-api-run"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _create_run(
        session_factory,
        run_id,
        execution_mode="graph",
        status=RunStatus.ACTIVE,
        agent_runner_type=AgentRunnerType.CODEX_SERVER,
    )
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _graph_event("run_lifecycle_changed", {"to_state": "active"}),
                _graph_event(
                    "node_created",
                    {"node_id": "worker-1", "kind": "worker", "state": "running"},
                ),
                _graph_event(
                    "lease_granted",
                    {
                        "lease_id": "lease-worker-1",
                        "node_id": "worker-1",
                        "generation": 1,
                        "execution_id": "exec-worker-1",
                        "expires_at": "2026-06-22T12:05:00+00:00",
                    },
                ),
            ],
        )
        await session.commit()

    response = await client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 202
    assert response.json()["is_graph_backed"] is True
    async with session_factory() as session:
        events = await GraphEventStore(session).read_run(run_id)
    event_types = [event.event_type for event in events]
    assert event_types[-4:] == [
        "run_lifecycle_changed",
        "lease_revoked",
        "node_state_changed",
        "run_lifecycle_changed",
    ]
    assert events[-4].payload["to_state"] == "cancelling"
    assert events[-3].payload["lease_id"] == "lease-worker-1"
    assert events[-2].payload == {
        "node_id": "worker-1",
        "new_state": "cancelled",
        "trigger": "run_cancelled",
        "reason": "run_cancelled",
    }
    assert events[-1].payload["to_state"] == "cancelled"

    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "failed"
    async with session_factory() as session:
        after_drain_events = await GraphEventStore(session).read_run(run_id)
    assert [event.event_type for event in after_drain_events] == event_types


async def _create_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    execution_mode: str,
    status: RunStatus = RunStatus.DRAFT,
    agent_runner_type: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS,
) -> None:
    routine = RoutineConfig.model_validate(_routine_payload())
    run = create_run_from_routine(routine, repo_name="routing-repo", source_branch="main")
    run.id = run_id
    run.execution_mode = execution_mode
    run.status = status
    run.agent_runner_type = agent_runner_type
    async with session_factory() as session:
        if status == RunStatus.DRAFT:
            await WorkflowService(session).create_run(run)
        else:
            await save_run(session, run)
            await session.commit()


def _graph_event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{len(str(payload))}",
        run_id="placeholder",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
