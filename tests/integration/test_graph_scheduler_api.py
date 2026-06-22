"""Integration tests for graph scheduler and lease API view."""

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphController, GraphEventStore
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


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


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


async def _seed_resource_conflict_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "writer-a",
                "kind": "worker",
                "state": "leased",
                "resource_claims": [{"mode": "write", "scope": "repo"}],
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "writer-b",
                "kind": "worker",
                "state": "planned",
                "resource_claims": [{"mode": "write", "scope": "repo"}],
            },
        ),
        _event("node_state_changed", {"node_id": "writer-b", "new_state": "ready"}),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-writer-a",
                "node_id": "writer-a",
                "generation": 1,
                "execution_id": "exec-writer-a",
                "expires_at": "2026-06-13T12:05:00+00:00",
                "resource_claims": [{"mode": "write", "scope": "repo"}],
            },
        ),
        _event(
            "node_deferred",
            {"node_id": "writer-b", "reason": "resource_conflict:write:write"},
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def _seed_path_scoped_write_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "writer-docs",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/"]}],
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "writer-tests",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["tests/"]}],
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "writer-docs-overlap",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/api.md"]}],
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    controller = GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )
    await controller.handle_command(
        run_id,
        len(events),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 10, "base_snapshot_id": "snapshot-path-scoped"},
    )


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


async def test_resource_conflict_readback_matches_run_graph_scheduler_and_events(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-resource-conflict-{uuid4().hex[:8]}"
    await _seed_resource_conflict_graph_run(app, run_id)

    run_resp = await client.get(f"/api/runs/{run_id}")
    graph_resp = await client.get(f"/api/runs/{run_id}/graph")
    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")

    assert run_resp.status_code == 200
    assert graph_resp.status_code == 200
    assert scheduler_resp.status_code == 200
    assert events_resp.status_code == 200

    run = run_resp.json()
    graph = graph_resp.json()
    scheduler = scheduler_resp.json()
    events = events_resp.json()

    assert run["is_graph_backed"] is True
    assert graph["run_state"] == "active"
    assert graph["ready_nodes"] == ["writer-b"]
    assert graph["leases"]["lease-writer-a"]["node_id"] == "writer-a"
    assert graph["leases"]["lease-writer-a"]["state"] == "active"

    assert scheduler["event_count"] == graph["event_count"] == len(events)
    assert scheduler["scheduler"]["ready"] == ["writer-b"]
    assert scheduler["scheduler"]["blocked"] == []
    assert scheduler["scheduler"]["waiting_resources"] == [
        {"node_id": "writer-b", "reason": "resource_conflict:write:write"}
    ]
    assert scheduler["scheduler"]["waiting_gates"] == []
    assert scheduler["leases"]["active"] == [
        {
            "lease_id": "lease-writer-a",
            "node_id": "writer-a",
            "generation": 1,
            "state": "active",
            "execution_id": "exec-writer-a",
            "expires_at": "2026-06-13T12:05:00+00:00",
        }
    ]

    deferred_events = [event for event in events if event["event_type"] == "node_deferred"]
    assert deferred_events == [
        {
            "event_id": deferred_events[0]["event_id"],
            "event_type": "node_deferred",
            "run_id": run_id,
            "position": 6,
            "timestamp": deferred_events[0]["timestamp"],
            "payload": {"node_id": "writer-b", "reason": "resource_conflict:write:write"},
        }
    ]


async def test_path_scoped_write_claims_can_progress_without_resource_conflict(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-path-writes-{uuid4().hex[:8]}"
    await _seed_path_scoped_write_graph_run(app, run_id)

    graph_resp = await client.get(f"/api/runs/{run_id}/graph")
    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")

    assert graph_resp.status_code == 200
    assert scheduler_resp.status_code == 200
    assert events_resp.status_code == 200

    graph = graph_resp.json()
    scheduler = scheduler_resp.json()
    events = events_resp.json()
    lease_events = [event for event in events if event["event_type"] == "lease_granted"]
    deferred_events = [event for event in events if event["event_type"] == "node_deferred"]

    assert [event["payload"]["node_id"] for event in lease_events] == [
        "writer-docs",
        "writer-tests",
    ]
    assert [event["payload"]["resource_claims"][0]["paths"] for event in lease_events] == [
        ["docs/"],
        ["tests/"],
    ]
    assert len(deferred_events) == 1
    assert deferred_events[0]["event_type"] == "node_deferred"
    assert deferred_events[0]["run_id"] == run_id
    assert deferred_events[0]["position"] > lease_events[-1]["position"]
    assert deferred_events[0]["payload"] == {
        "node_id": "writer-docs-overlap",
        "reason": "resource_conflict:write:write",
    }
    assert scheduler["event_count"] == graph["event_count"] == len(events)
    assert scheduler["scheduler"]["ready"] == ["writer-docs-overlap"]
    assert scheduler["scheduler"]["waiting_resources"] == [
        {"node_id": "writer-docs-overlap", "reason": "resource_conflict:write:write"}
    ]
    assert scheduler["leases"]["active"] == [
        {
            "lease_id": lease_events[0]["payload"]["lease_id"],
            "node_id": "writer-docs",
            "generation": 1,
            "state": "active",
            "execution_id": lease_events[0]["payload"]["execution_id"],
            "expires_at": "2026-01-01T00:01:00+00:00",
        },
        {
            "lease_id": lease_events[1]["payload"]["lease_id"],
            "node_id": "writer-tests",
            "generation": 1,
            "state": "active",
            "execution_id": lease_events[1]["payload"]["execution_id"],
            "expires_at": "2026-01-01T00:01:00+00:00",
        },
    ]


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
