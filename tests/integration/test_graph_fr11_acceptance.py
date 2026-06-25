"""FR-11 acceptance coverage for scheduler ordering and bounded fairness."""

from datetime import timezone
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphController, GraphEventStore


BASE_SNAPSHOT_ID = "snapshot-fr11"


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
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr11-acceptance-repo-{run_id}",
        status=RunStatus.ACTIVE.value,
        execution_mode="graph",
        source_branch="main",
        created_at=now,
        updated_at=now,
        current_step_index=0,
        steps=[
            StepModel(
                id=f"{run_id}-step-1",
                run_id=run_id,
                config_id="step-1",
                title="Step 1",
                order_index=0,
                tasks=[
                    TaskModel(
                        id=f"{run_id}-task-1",
                        step_id=f"{run_id}-step-1",
                        config_id="task-1",
                        title="Prove scheduler fairness",
                        order_index=0,
                        status="pending",
                        checklist=[],
                    )
                ],
            )
        ],
    )
    async with session_factory() as session:
        session.add(run)
        await session.commit()


async def _seed_fr11_ready_frontier(app: Any, run_id: str) -> GraphController:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event("node_created", {"node_id": "check-control", "kind": "check", "state": "ready"}),
        _event("node_created", {"node_id": "join-control", "kind": "join", "state": "ready"}),
        _event(
            "node_created",
            {"node_id": "final-gate-control", "kind": "final_gate", "state": "ready"},
        ),
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
                "node_id": "reader-src",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["src/"]}],
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "reader-tests",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["tests/"]}],
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

    return GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )


async def _schedule(
    controller: GraphController,
    run_id: str,
    *,
    expected_position: int,
    max_grants: int,
) -> None:
    priorities = {
        "check-control": 20,
        "join-control": 20,
        "final-gate-control": 20,
        "reader-tests": 9,
        "writer-docs": 7,
        "reader-src": 5,
        "writer-docs-overlap": 3,
    }
    await controller.handle_command(
        run_id,
        expected_position,
        "schedule_tick",
        {
            "lease_seconds": 60,
            "max_grants": max_grants,
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "priorities": priorities,
        },
    )


async def _acknowledge_start(
    controller: GraphController,
    run_id: str,
    *,
    expected_position: int,
    lease: dict[str, Any],
) -> None:
    await controller.handle_command(
        run_id,
        expected_position,
        "acknowledge_start",
        {
            "node_id": lease["node_id"],
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "execution_id": lease["execution_id"],
        },
    )


async def _complete_worker(
    controller: GraphController,
    run_id: str,
    *,
    expected_position: int,
    lease: dict[str, Any],
) -> None:
    node_id = lease["node_id"]
    await controller.handle_command(
        run_id,
        expected_position,
        "submit_callback",
        {
            "run_id": run_id,
            "node_id": node_id,
            "execution_id": lease["execution_id"],
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "observed_graph_position": expected_position,
            "idempotency_key": f"{node_id}-complete",
            "payload_hash": f"{node_id}-hash",
            "payload": {
                "payload_hash": f"{node_id}-hash",
                "output_records": [
                    {
                        "record_id": f"candidate-{node_id}",
                        "record_kind": "output",
                        "producer_node_id": node_id,
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": f"{node_id} completed"},
                    },
                    {
                        "record_id": f"file-state-{node_id}",
                        "record_kind": "file_state",
                        "producer_node_id": node_id,
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": f"{BASE_SNAPSHOT_ID}-{node_id}",
                        "base_snapshot_id": BASE_SNAPSHOT_ID,
                        "verdict": "captured",
                        "tracked": [
                            {
                                "path": "docs/fr11.md",
                                "status": "modified",
                                "hash": "sha256-fr11",
                            }
                        ],
                    },
                ],
            },
        },
    )


async def _full_events(client: AsyncClient, run_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert response.status_code == 200
    return response.json()


def _leases_by_node(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        event["payload"]["node_id"]: event["payload"]
        for event in events
        if event["event_type"] == "lease_granted"
    }


async def test_fr11_scheduler_orders_frontier_and_progresses_deferred_work(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fr11-{uuid4().hex[:8]}"
    controller = await _seed_fr11_ready_frontier(app, run_id)

    await _schedule(controller, run_id, expected_position=8, max_grants=2)
    tick_one_events = await _full_events(client, run_id)
    tick_one_leases = [
        event["payload"]["node_id"]
        for event in tick_one_events
        if event["event_type"] == "lease_granted"
    ]
    assert tick_one_leases == ["check-control", "final-gate-control"]
    assert {
        event["payload"]["node_id"]: event["payload"]["reason"]
        for event in tick_one_events
        if event["event_type"] == "node_deferred"
    } == {
        "join-control": "max_grants_reached",
        "reader-tests": "max_grants_reached",
        "writer-docs": "max_grants_reached",
        "reader-src": "max_grants_reached",
        "writer-docs-overlap": "max_grants_reached",
    }

    await _schedule(controller, run_id, expected_position=len(tick_one_events), max_grants=10)
    tick_two_events = await _full_events(client, run_id)
    lease_order = [
        event["payload"]["node_id"]
        for event in tick_two_events
        if event["event_type"] == "lease_granted"
    ]
    assert lease_order == [
        "check-control",
        "final-gate-control",
        "join-control",
        "reader-tests",
        "writer-docs",
        "reader-src",
    ]
    tick_two_deferrals = [
        event
        for event in tick_two_events
        if event["event_type"] == "node_deferred"
        and event["payload"]["node_id"] == "writer-docs-overlap"
    ]
    assert tick_two_deferrals[-1]["payload"]["reason"] == "resource_conflict:write:write"

    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    assert scheduler_resp.status_code == 200
    scheduler = scheduler_resp.json()
    assert scheduler["scheduler"]["ready"] == ["writer-docs-overlap"]
    assert scheduler["scheduler"]["waiting_resources"] == [
        {"node_id": "writer-docs-overlap", "reason": "resource_conflict:write:write"}
    ]

    writer_docs_lease = _leases_by_node(tick_two_events)["writer-docs"]
    await _acknowledge_start(
        controller,
        run_id,
        expected_position=len(tick_two_events),
        lease=writer_docs_lease,
    )
    after_ack_events = await _full_events(client, run_id)
    await _complete_worker(
        controller,
        run_id,
        expected_position=len(after_ack_events),
        lease=writer_docs_lease,
    )
    after_release_events = await _full_events(client, run_id)
    assert any(
        event["event_type"] == "lease_released" and event["payload"]["node_id"] == "writer-docs"
        for event in after_release_events
    )

    await _schedule(controller, run_id, expected_position=len(after_release_events), max_grants=10)
    final_events = await _full_events(client, run_id)
    final_lease_order = [
        event["payload"]["node_id"]
        for event in final_events
        if event["event_type"] == "lease_granted"
    ]
    assert final_lease_order == [
        "check-control",
        "final-gate-control",
        "join-control",
        "reader-tests",
        "writer-docs",
        "reader-src",
        "writer-docs-overlap",
    ]

    graph_resp = await client.get(f"/api/runs/{run_id}/graph")
    node_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/writer-docs?payload_mode=full")
    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    assert graph_resp.status_code == 200
    assert node_resp.status_code == 200
    assert scheduler_resp.status_code == 200

    graph = graph_resp.json()
    node = node_resp.json()
    scheduler = scheduler_resp.json()
    assert graph["run_state"] == "active"
    assert graph["ready_nodes"] == []
    assert scheduler["scheduler"]["waiting_resources"] == []
    assert node["state"] == "completed"
    assert [event["event_type"] for event in node["callback_history"]] == [
        "node_state_changed",
        "callback_accepted",
    ]
    assert node["callback_history"][0]["payload"]["trigger"] == "runtime_start_acknowledged"
    assert node["callback_history"][1]["payload"]["reason"] == "accepted"
    assert {record["record_id"] for record in node["output_records"]} == {"candidate-writer-docs"}
    assert {record["record_id"] for record in node["file_state_records"]} == {
        "file-state-writer-docs"
    }
    assert any(
        event["event_type"] == "file_state_accepted"
        and event["payload"]["record_id"] == "file-state-writer-docs"
        for event in final_events
    )
