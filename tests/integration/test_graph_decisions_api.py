"""Integration tests for graph human-decision API view."""

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
            "id": "graph-decisions-api-test",
            "name": "Graph Decisions API Test Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Do one thing",
                            "task_context": "Exercise decision projections.",
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
        repo_name=f"graph-decisions-api-repo-{run_id}",
        source_branch="main",
    )
    run.id = run_id
    run.execution_mode = execution_mode
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _seed_decision_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "gate",
                "state": "ready",
                "gate_type": "human_approval",
                "prompt": "Approve verified candidate?",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "ready",
                "prompt": "Grant docs write authority?",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "authority-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["repo:docs/**:write"],
                    "target_node_id": "worker-docs",
                    "target_region_id": "task-1",
                    "reason": "Worker needs docs write access.",
                    "expires_at": "2026-06-13T12:05:00+00:00",
                },
            },
        ),
        _event(
            "node_created",
            {"node_id": "appeal-1", "kind": "appeal", "state": "completed"},
        ),
        _event(
            "oversight_decision_recorded",
            {"appeal_node_id": "appeal-1", "node_id": "oversight-1", "outcome": "rejected"},
        ),
        _event(
            "node_created",
            {
                "node_id": "review-1",
                "kind": "review",
                "state": "blocked",
                "blocker": "merge_conflicts",
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def _seed_active_authority_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "running",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "authority-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["repo:docs/**:write"],
                    "target_node_id": "worker-docs",
                    "reason": "Worker needs docs write access.",
                },
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-authority-request",
                "to_node_id": "authority-1",
                "to_port": "authority_request_record",
                "record_ids": ["authority-request-1"],
            },
        ),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-authority-1",
                "node_id": "authority-1",
                "generation": 1,
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-docs",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-authority-worker",
                "from_node_id": "authority-1",
                "from_port": "authority_decision",
                "to_node_id": "worker-docs",
                "to_port": "authority",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["authority_decision"]},
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def test_decisions_endpoint_reflects_seeded_gates_and_appeals(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-{uuid4().hex[:8]}"
    await _seed_decision_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["event_count"] == 6
    assert body["pending_gates"] == [
        {
            "node_id": "authority-1",
            "gate_type": "authority_request",
            "prompt": "Grant docs write authority?",
            "expires_at": "2026-06-13T12:05:00+00:00",
            "requested_authority": ["repo:docs/**:write"],
            "target_node_id": "worker-docs",
            "target_region_id": "task-1",
        },
        {
            "node_id": "gate-1",
            "gate_type": "human_approval",
            "prompt": "Approve verified candidate?",
        },
    ]
    assert body["appeals"] == [{"node_id": "appeal-1", "state": "completed", "outcome": "rejected"}]
    assert body["review"] == {"ready": False, "blockers": ["review-1: merge_conflicts"]}


async def test_record_authority_decision_updates_decision_readback(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-{uuid4().hex[:8]}"
    await _seed_decision_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "grant",
            "decider": {"kind": "human", "id": "alice"},
            "scope": {"tools": ["graph_write"]},
            "expires_at": "2026-06-13T12:30:00+00:00",
            "reason": "Approved for bounded docs update.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["graph_position"] == 9
    assert [event["event_type"] for event in body["events"]] == [
        "authority_decision_recorded",
        "output_record_accepted",
        "node_state_changed",
    ]
    decision_record = body["events"][1]["payload"]
    assert decision_record["record_id"] == "authority_decision-authority-1"
    assert decision_record["record_kind"] == "output"
    assert decision_record["record_type"] == "authority_decision"
    assert decision_record["producer_node_id"] == "authority-1"
    assert decision_record["port"] == "authority_decision"
    assert decision_record["schema"] == "AuthorityDecision"
    assert decision_record["run_id"] == run_id
    assert decision_record["graph_position"] == 8
    assert decision_record["value"] == {
        "decision": "granted",
        "decision_type": "authority",
        "decider": {"kind": "human", "id": "alice"},
        "scope": {"tools": ["graph_write"]},
        "expires_at": "2026-06-13T12:30:00+00:00",
        "reason": "Approved for bounded docs update.",
    }
    assert body["decision_view"]["pending_gates"] == [
        {
            "node_id": "gate-1",
            "gate_type": "human_approval",
            "prompt": "Approve verified candidate?",
        },
    ]

    readback = await client.get(f"/api/runs/{run_id}/graph/decisions")
    assert readback.status_code == 200
    assert readback.json()["pending_gates"] == body["decision_view"]["pending_gates"]


async def test_record_authority_decision_binds_and_recomputes_active_scheduler(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-{uuid4().hex[:8]}"
    await _seed_active_authority_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "granted",
            "decider": {"kind": "human", "id": "alice"},
            "scope": {"tools": ["graph_write"]},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    event_types = [event["event_type"] for event in body["events"]]
    assert event_types[:5] == [
        "authority_decision_recorded",
        "output_record_accepted",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    assert "node_ready" in event_types
    assert body["events"][2]["payload"]["edge_id"] == "edge-authority-worker"
    assert body["events"][2]["payload"]["record_ids"] == ["authority_decision-authority-1"]
    assert body["events"][4]["payload"]["lease_id"] == "lease-authority-1"
    assert any(
        event["event_type"] == "node_ready" and event["payload"] == {"node_id": "worker-docs"}
        for event in body["events"]
    )

    scheduler = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    assert scheduler.status_code == 200
    scheduler_body = scheduler.json()
    assert scheduler_body["scheduler"]["ready"] == ["worker-docs"]
    assert scheduler_body["scheduler"]["blocked"] == []
    assert scheduler_body["leases"]["active"] == []


async def test_record_decision_rejects_invalid_decision_at_api_boundary(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-{uuid4().hex[:8]}"
    await _seed_decision_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert response.status_code == 422
    assert "decision for authority must be one of" in response.text


async def test_decisions_endpoint_empty_for_non_graph_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-decisions-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["event_count"] == 0
    assert body["pending_gates"] == []
    assert body["appeals"] == []
    assert body["review"] == {"ready": False, "blockers": []}
