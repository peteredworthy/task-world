"""Integration tests for graph compatibility projection endpoints."""

from uuid import uuid4
from typing import Any

from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from orchestrator.config.models import RoutineConfig
from orchestrator.db import EventV2Model, GraphEventSummaryModel, GraphProjectionSnapshotModel
from orchestrator.graph import FakeClock
from orchestrator.graph.commands import IdGenerator
from orchestrator.state.factory import create_run_from_routine
from orchestrator.db.access.mutations import save_run
from orchestrator.graph_runtime import GraphController, GraphEventStore, seed_run


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
                            "verifier": {
                                "rubric": [
                                    {
                                        "id": "req-1",
                                        "text": "The implementation is correct.",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{self._run_id}-{prefix}-{self._next}"
        self._next += 1
        return value


async def _seed_graph_run(
    app: Any,
    run_id: str,
) -> None:
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


async def _seed_worker_verifier_cycle(app: Any, run_id: str) -> None:
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    clock = FakeClock()
    id_gen: IdGenerator = _RunSeedIdGenerator(run_id)
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    async with session_factory() as session:
        events = await GraphEventStore(session).read_run(run_id)
    position = max(event.position for event in events)
    worker_lease = next(event for event in events if event.event_type == "lease_granted")
    worker_node = str(worker_lease.payload["node_id"])
    worker_created = next(
        event
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == worker_node
    )
    candidate_id = str(worker_created.payload["candidate_id"])
    task_region_id = str(worker_created.payload["task_region_id"])
    attempt_number = int(worker_created.payload["attempt_number"])

    acknowledged = await controller.handle_command(
        run_id,
        position,
        "acknowledge_start",
        {
            "node_id": worker_node,
            "lease_id": worker_lease.payload["lease_id"],
            "lease_generation": worker_lease.payload["generation"],
            "execution_id": worker_lease.payload["execution_id"],
        },
    )
    completed_worker = await controller.handle_command(
        run_id,
        acknowledged.projection_position,
        "submit_callback",
        {
            "run_id": run_id,
            "node_id": worker_node,
            "execution_id": worker_lease.payload["execution_id"],
            "lease_id": worker_lease.payload["lease_id"],
            "lease_generation": worker_lease.payload["generation"],
            "base_snapshot_id": worker_lease.payload["base_snapshot_id"],
            "observed_graph_position": acknowledged.projection_position,
            "idempotency_key": f"callback-{worker_node}",
            "payload": {
                "payload_hash": f"hash-{worker_node}",
                "output_records": [
                    {
                        "record_id": candidate_id,
                        "record_kind": "output",
                        "producer_node_id": worker_node,
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "candidate_id": candidate_id,
                        "task_region_id": task_region_id,
                        "attempt_number": attempt_number,
                        "value": {"summary": "worker output"},
                    },
                    {
                        "record_id": f"fs-{worker_node}",
                        "record_kind": "file_state",
                        "snapshot_id": f"snapshot-{worker_node}",
                        "producer_node_id": worker_node,
                        "verdict": "captured",
                        "tracked": [
                            {
                                "path": "src/app.py",
                                "status": "modified",
                                "classification": "source",
                            }
                        ],
                        "residue": [
                            {
                                "path": "tmp/output.log",
                                "classification": "test_artifact",
                                "needs_gatekeeper": False,
                            }
                        ],
                    },
                ],
            },
        },
    )
    scheduled_verifier = await controller.handle_command(
        run_id,
        completed_worker.projection_position,
        "schedule_tick",
        {"max_grants": 1, "lease_seconds": 60},
    )
    verifier_lease = next(
        event for event in scheduled_verifier.events if event.event_type == "lease_granted"
    )
    verifier_node = str(verifier_lease.payload["node_id"])
    acknowledged_verifier = await controller.handle_command(
        run_id,
        scheduled_verifier.projection_position,
        "acknowledge_start",
        {
            "node_id": verifier_node,
            "lease_id": verifier_lease.payload["lease_id"],
            "lease_generation": verifier_lease.payload["generation"],
            "execution_id": verifier_lease.payload["execution_id"],
        },
    )
    await controller.handle_command(
        run_id,
        acknowledged_verifier.projection_position,
        "submit_callback",
        {
            "run_id": run_id,
            "node_id": verifier_node,
            "execution_id": verifier_lease.payload["execution_id"],
            "lease_id": verifier_lease.payload["lease_id"],
            "lease_generation": verifier_lease.payload["generation"],
            "base_snapshot_id": verifier_lease.payload["base_snapshot_id"],
            "observed_graph_position": acknowledged_verifier.projection_position,
            "idempotency_key": f"callback-{verifier_node}",
            "payload": {
                "payload_hash": f"hash-{verifier_node}",
                "output_records": [
                    {
                        "record_id": f"verification-{candidate_id}",
                        "record_kind": "verification",
                        "producer_node_id": verifier_node,
                        "candidate_id": candidate_id,
                        "verdict": "passed",
                        "evidence": {"summary": "looks good"},
                        "value": {
                            "grades": [
                                {
                                    "requirement_id": "R-1",
                                    "grade": "A",
                                    "reason": "candidate satisfies requirement",
                                }
                            ]
                        },
                    }
                ],
            },
        },
    )


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

    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert events_resp.status_code == 200
    all_events = events_resp.json()
    assert len(all_events) == projection["event_count"]

    filter_resp = await client.get(f"/api/runs/{run_id}/graph/events?from_position=2")
    assert filter_resp.status_code == 200
    filtered_events = filter_resp.json()
    assert len(filtered_events) <= len(all_events)
    assert all(event["position"] >= 2 for event in filtered_events)

    summary_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")
    assert summary_resp.status_code == 200
    summary_events = summary_resp.json()
    assert len(summary_events) == len(all_events)
    root_summary = next(
        event for event in summary_events if event["payload"].get("node_id") == "root"
    )
    assert "routine" not in root_summary["payload"]

    invalid_summary_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=compact")
    assert invalid_summary_resp.status_code == 422

    detail_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{worker_node}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["state"] == projection["node_states"][worker_node]
    assert detail["node_id"] == worker_node

    not_found = await client.get(f"/api/runs/{run_id}/graph/nodes/nonexistent")
    assert not_found.status_code == 404


async def test_active_graph_execution_readback_uses_bounded_summary_paths(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-active-readback"

    await _seed_graph_run(app, run_id)

    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    assert projection_resp.status_code == 200
    projection = projection_resp.json()
    active_leases = [
        lease for lease in projection["leases"].values() if lease.get("state") == "active"
    ]
    assert active_leases
    active_node_id = active_leases[0]["node_id"]

    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")
    node_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{active_node_id}")

    assert scheduler_resp.status_code == 200
    assert events_resp.status_code == 200
    assert node_resp.status_code == 200

    scheduler = scheduler_resp.json()
    assert any(lease["node_id"] == active_node_id for lease in scheduler["leases"]["active"])

    summary_events = events_resp.json()
    assert len(summary_events) == projection["event_count"]
    assert all("routine" not in event["payload"] for event in summary_events)

    node = node_resp.json()
    assert node["node_id"] == active_node_id
    assert node["active_lease"]["state"] == "active"
    assert "routine" not in str(node["events"])


async def test_graph_projection_routes_recreate_deleted_read_models(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-read-model-api-rebuild"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await session.execute(
            delete(GraphProjectionSnapshotModel).where(
                GraphProjectionSnapshotModel.run_id == run_id
            )
        )
        await session.commit()

    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    decisions_resp = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert projection_resp.status_code == 200
    assert scheduler_resp.status_code == 200
    assert decisions_resp.status_code == 200
    assert projection_resp.json()["event_count"] > 0
    assert scheduler_resp.json()["event_count"] == projection_resp.json()["event_count"]
    assert decisions_resp.json()["event_count"] == projection_resp.json()["event_count"]

    async with session_factory() as session:
        summary_count = await session.scalar(
            select(func.count())
            .select_from(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
        )
        snapshot_count = await session.scalar(
            select(func.count())
            .select_from(GraphProjectionSnapshotModel)
            .where(GraphProjectionSnapshotModel.run_id == run_id)
        )

    assert summary_count == projection_resp.json()["event_count"]
    assert snapshot_count == 1


async def test_node_detail_returns_inputs_outputs_filestate_callbacks(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-node-detail-cycle"
    await _seed_worker_verifier_cycle(app, run_id)

    events_resp = await client.get(f"/api/runs/{run_id}/graph/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    worker_node = next(
        event["payload"]["node_id"]
        for event in events
        if event["event_type"] == "node_created" and event["payload"].get("kind") == "worker"
    )
    verifier_node = next(
        event["payload"]["node_id"]
        for event in events
        if event["event_type"] == "node_created" and event["payload"].get("kind") == "verifier"
    )

    summary_worker_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{worker_node}")
    assert summary_worker_resp.status_code == 200
    summary_worker = summary_worker_resp.json()
    assert summary_worker["kind"] == "worker"
    assert summary_worker["output_records"]
    assert summary_worker["output_records"][0]["record_id"]
    assert summary_worker["output_records"][0]["port"]
    assert "value" not in summary_worker["output_records"][0]
    assert summary_worker["file_state_records"]
    assert summary_worker["file_state_records"][0]["classification_summary"]["total_paths"] == 0

    summary_verifier_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{verifier_node}")
    assert summary_verifier_resp.status_code == 200
    summary_verifier = summary_verifier_resp.json()
    assert summary_verifier["input_ports"]["candidate_under_test"] == [
        summary_worker["output_records"][0]["record_id"]
    ]

    worker_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/{worker_node}?payload_mode=full"
    )
    assert worker_resp.status_code == 200
    worker = worker_resp.json()
    assert worker["kind"] == "worker"
    assert worker["role"] == "builder"
    assert worker["output_records"]
    assert any(record["record_kind"] == "output" for record in worker["output_records"])
    assert worker["file_state_records"]
    file_state = worker["file_state_records"][0]
    assert file_state["verdict"] == "captured"
    assert file_state["classification_summary"]["total_paths"] == 2
    assert file_state["classification_summary"]["classifications"]["test_artifact"] == 1
    assert worker["active_lease"]["state"] == "released"
    worker_callback_types = [event["event_type"] for event in worker["callback_history"]]
    assert worker_callback_types == ["node_state_changed", "callback_accepted"]
    assert [event["position"] for event in worker["callback_history"]] == sorted(
        event["position"] for event in worker["callback_history"]
    )

    verifier_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/{verifier_node}?payload_mode=full"
    )
    assert verifier_resp.status_code == 200
    verifier = verifier_resp.json()
    assert verifier["kind"] == "verifier"
    assert verifier["input_ports"]["candidate_under_test"] == [
        worker["output_records"][0]["record_id"]
    ]
    assert verifier["output_records"]
    assert verifier["output_records"][0]["record_kind"] == "verification"
    verifier_callback_types = [event["event_type"] for event in verifier["callback_history"]]
    assert verifier_callback_types == ["node_state_changed", "callback_accepted"]


async def test_node_detail_404_for_unknown_node(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-node-detail-404"
    await _seed_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/nodes/nonexistent")
    assert response.status_code == 404


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
