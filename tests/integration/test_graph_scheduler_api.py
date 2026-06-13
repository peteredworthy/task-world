"""Integration tests for graph scheduler and lease API view."""

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-scheduler-api-test",
            "name": "Graph Scheduler API Test Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Do one thing",
                            "task_context": "Exercise scheduler projections.",
                            "verifier": {"rubric": [{"id": "req-1", "text": "Correct."}]},
                        }
                    ],
                }
            ],
        }
    )


def _event(event_type: str, payload: dict[str, Any], position: int = -1) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id="placeholder",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


async def _save_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    execution_mode: str = "legacy",
) -> None:
    run = create_run_from_routine(
        _routine(),
        repo_name=f"graph-scheduler-api-repo-{run_id}",
        source_branch="main",
    )
    run.id = run_id
    run.execution_mode = execution_mode
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _seed_scheduler_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "leased"}),
        _event("node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "planned"}),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-worker-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-worker-1",
                "expires_at": "2026-06-13T12:05:00+00:00",
            },
        ),
        _event(
            "node_deferred",
            {"node_id": "verifier-1", "reason": "missing_required_input:candidate"},
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def test_scheduler_endpoint_reflects_seeded_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-scheduler-{uuid4().hex[:8]}"
    await _seed_scheduler_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/scheduler")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["event_count"] == 5
    assert body["scheduler"]["ready"] == []
    assert body["scheduler"]["blocked"] == [
        {"node_id": "verifier-1", "reason": "missing_required_input:candidate"}
    ]
    assert body["scheduler"]["waiting_resources"] == []
    assert body["scheduler"]["waiting_gates"] == []
    assert body["leases"]["active"] == [
        {
            "lease_id": "lease-worker-1",
            "node_id": "worker-1",
            "generation": 1,
            "state": "active",
            "execution_id": "exec-worker-1",
            "expires_at": "2026-06-13T12:05:00+00:00",
        }
    ]
    assert body["leases"]["suspended"] == []


async def test_scheduler_endpoint_empty_for_non_graph_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-scheduler-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/scheduler")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["event_count"] == 0
    assert body["scheduler"] == {
        "ready": [],
        "blocked": [],
        "waiting_resources": [],
        "waiting_gates": [],
    }
    assert body["leases"] == {"active": [], "suspended": []}
