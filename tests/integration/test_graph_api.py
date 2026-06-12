"""Integration tests for graph compatibility projection endpoints."""

from uuid import uuid4
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from orchestrator.config.models import RoutineConfig
from orchestrator.db import EventV2Model
from orchestrator.graph import FakeClock
from orchestrator.graph.commands import IdGenerator
from orchestrator.state.factory import create_run_from_routine
from orchestrator.db.access.mutations import save_run
from orchestrator.graph_runtime import GraphController, seed_run


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-api-test",
            "name": "Graph API Test Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Do one thing",
                            "task_context": "Exercise graph projections.",
                        }
                    ],
                }
            ],
        }
    )


async def _seed_graph_run(
    app: Any,
    run_id: str,
) -> None:
    class _RunSeedIdGenerator:
        def __init__(self, run_id: str) -> None:
            self._run_id = run_id.replace("-", "")
            self._next = 1

        def next_id(self, prefix: str = "") -> str:
            value = f"{self._run_id}-{prefix}-{self._next}"
            self._next += 1
            return value

    clock = FakeClock()
    id_gen: IdGenerator = _RunSeedIdGenerator(run_id)
    routine = _routine()
    repo_name = "graph-api-test-repo"

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    # Seed the projection from compiled routine topology.
    seed = await seed_run(
        session_factory,
        routine,
        run_id=run_id,
        clock=clock,
        id_gen=id_gen,
    )
    assert seed.projection_position > 0

    # Append lifecycle ticks directly through the controller so projection mirrors
    # existing graph-runner execution flow.
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {"max_grants": 1, "lease_seconds": 60},
    )

    run = create_run_from_routine(routine, repo_name=repo_name, source_branch="main")
    run.id = run_id
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def test_graph_projection_empty_for_non_graph_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-run-{uuid4().hex[:8]}"
    run = create_run_from_routine(
        _routine(),
        repo_name="graph-api-legacy-repo",
        source_branch="main",
    )
    run.id = run_id
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["run_id"] == run_id
    assert projection["event_count"] == 0
    assert projection["run_state"] is None
    assert projection["node_states"] == {}
    assert projection["task_states"] == {}
    assert projection["leases"] == {}
    assert projection["ready_nodes"] == []


async def test_graph_projection_reflects_seeded_events(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-seeded-run"

    await _seed_graph_run(app, run_id)

    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    assert projection_resp.status_code == 200
    projection = projection_resp.json()
    assert projection["event_count"] > 0
    assert projection["run_state"] == "active"
    assert len(projection["node_states"]) > 0
    worker_node = next(
        node_id for node_id in projection["node_states"] if node_id.startswith("worker-")
    )

    events_resp = await client.get(f"/api/runs/{run_id}/graph/events")
    assert events_resp.status_code == 200
    all_events = events_resp.json()
    assert len(all_events) == projection["event_count"]

    filter_resp = await client.get(f"/api/runs/{run_id}/graph/events?from_position=2")
    assert filter_resp.status_code == 200
    filtered_events = filter_resp.json()
    assert len(filtered_events) <= len(all_events)
    assert all(event["position"] >= 2 for event in filtered_events)

    detail_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{worker_node}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["state"] == projection["node_states"][worker_node]
    assert detail["node_id"] == worker_node

    not_found = await client.get(f"/api/runs/{run_id}/graph/nodes/nonexistent")
    assert not_found.status_code == 404


async def test_is_graph_backed_flag_in_run_response(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture

    run_id = "graph-backed-flag"
    await _seed_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["is_graph_backed"] is True

    list_response = await client.get("/api/runs")
    assert list_response.status_code == 200
    runs = list_response.json()["runs"]
    run_entry = next(run for run in runs if run["id"] == run_id)
    assert run_entry["is_graph_backed"] is True


async def test_is_graph_backed_false_for_legacy_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-run-{uuid4().hex[:8]}"
    run = create_run_from_routine(
        _routine(),
        repo_name="graph-api-legacy-repo",
        source_branch="main",
    )
    run.id = run_id
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["is_graph_backed"] is False

    list_response = await client.get("/api/runs")
    assert list_response.status_code == 200
    runs = list_response.json()["runs"]
    run_entry = next(run for run in runs if run["id"] == run_id)
    assert run_entry["is_graph_backed"] is False


async def test_legacy_run_with_workflow_events_is_not_graph_backed(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """Production legacy runs have workflow events in events_v2 under
    aggregate_id == run_id. Those rows must not 500 the graph projection
    endpoint nor mark the run graph-backed (regression: dogfood run r220)."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-evented-{uuid4().hex[:8]}"
    run = create_run_from_routine(
        _routine(),
        repo_name="graph-api-legacy-repo",
        source_branch="main",
    )
    run.id = run_id
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        # Simulate the legacy workflow event stream for this run.
        session.add(
            EventV2Model(
                aggregate_id=run_id,
                version=1,
                event_type="run_created",
                payload='{"timestamp": "2026-06-12T00:00:00Z", "run_id": "%s"}' % run_id,
                timestamp="2026-06-12T00:00:00Z",
            )
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["event_count"] == 0
    assert projection["run_state"] is None
    assert projection["node_states"] == {}

    detail = await client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["is_graph_backed"] is False

    list_response = await client.get("/api/runs")
    runs = list_response.json()["runs"]
    run_entry = next(run for run in runs if run["id"] == run_id)
    assert run_entry["is_graph_backed"] is False


async def test_graph_events_from_position(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture

    run_id = "graph-events-position"
    await _seed_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/events?from_position=2")
    assert response.status_code == 200
    events = response.json()

    # Ensure the endpoint enforces floor-position filtering and ordering.
    assert all(event["position"] >= 2 for event in events)
    assert events == sorted(events, key=lambda item: item["position"])
