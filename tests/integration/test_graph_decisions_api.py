"""Integration tests for graph human-decision API view."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import advance_graph_archival_maintenance_once
from orchestrator.config.models import RoutineConfig
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine
from tests.unit.graph_test_utils import canonical_event_payload


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
        payload=canonical_event_payload(event_type, payload),
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
            "node_created",
            {
                "node_id": "worker-docs",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
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
            "node_created",
            {"node_id": "oversight-1", "kind": "oversight", "state": "completed"},
        ),
        _event(
            "oversight_decision_recorded",
            {"appeal_node_id": "appeal-1", "node_id": "oversight-1", "decision": "rejected"},
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
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "authority-1",
                "from_port": "authority_request_record",
                "to_node_id": "authority-1",
                "to_port": "authority_request_record",
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-1",
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
                "accepted_record_selector": {
                    "record_type": "authority_decision",
                    "schema": "AuthorityDecision",
                },
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def _seed_active_human_gate_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "running",
                "gate_type": "human_approval",
                "prompt": "Approve reviewed output?",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-request-1",
                "record_kind": "graph_record",
                "record_type": "decision_request",
                "producer_node_id": "human-gate-1",
                "port": "decision_request",
                "schema": "DecisionRequest",
                "value": {
                    "decision_type": "approval",
                    "options": ["approved", "rejected"],
                    "default_option": "rejected",
                    "consequence_summary": "Release the successor when approved.",
                },
            },
        ),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-human-gate-1",
                "node_id": "human-gate-1",
                "generation": 1,
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-successor",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gate-successor",
                "from_node_id": "human-gate-1",
                "from_port": "decision_record",
                "to_node_id": "worker-successor",
                "to_port": "approval",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "decision_record",
                    "schema": "DecisionRecord",
                },
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
    assert body["event_count"] == 8
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
            "decision": "granted",
            "decider": {"kind": "human", "id": "alice"},
            "scope": {"tools": ["graph_write"]},
            "expires_at": "2026-06-13T12:30:00+00:00",
            "reason": "Approved for bounded docs update.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["graph_position"] == 11
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
    assert decision_record["graph_position"] == 10
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


async def test_record_approval_decision_is_durable_and_releases_waiting_successor(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-{uuid4().hex[:8]}"
    await _seed_active_human_gate_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "approval",
            "node_id": "human-gate-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice", "role": "operator"},
            "reason": "Reviewed output.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    event_types = [event["event_type"] for event in body["events"]]
    assert event_types[:5] == [
        "approval_decision_recorded",
        "output_record_accepted",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    assert "node_ready" in event_types
    assert body["decision_view"]["pending_gates"] == []

    events = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert events.status_code == 200
    recorded = next(
        event for event in events.json() if event["event_type"] == "approval_decision_recorded"
    )
    assert recorded["payload"]["decision"] == "approved"
    assert recorded["payload"]["decider"] == {"kind": "human", "id": "alice"}
    assert recorded["payload"]["reason"] == "Reviewed output."

    readback = await client.get(f"/api/runs/{run_id}/graph/decisions")
    assert readback.status_code == 200
    assert readback.json()["pending_gates"] == []

    scheduler = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    assert scheduler.status_code == 200
    assert scheduler.json()["scheduler"]["ready"] == ["worker-successor"]
    assert scheduler.json()["leases"]["active"] == []

    before_rejection = (await client.get(f"/api/runs/{run_id}/graph")).json()
    rejected = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "approval",
            "node_id": "worker-successor",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice", "role": "operator"},
        },
    )
    assert rejected.status_code == 409
    assert "approval decisions require gate or human_gate target" in rejected.text

    graph = await client.get(f"/api/runs/{run_id}/graph")
    assert graph.status_code == 200
    assert graph.json()["node_states"] == before_rejection["node_states"]
    assert graph.json()["leases"] == before_rejection["leases"]


async def test_record_rejected_approval_is_durable_and_dead_inputs_successor(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-{uuid4().hex[:8]}"
    await _seed_active_human_gate_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "approval",
            "node_id": "human-gate-1",
            "decision": "rejected",
            "decider": {"kind": "human", "id": "alice", "role": "operator"},
            "reason": "Reviewed output is unsafe.",
        },
    )

    assert response.status_code == 200, response.text
    event_types = [event["event_type"] for event in response.json()["events"]]
    assert event_types[:3] == [
        "approval_decision_recorded",
        "node_state_changed",
        "lease_released",
    ]
    assert "output_record_accepted" not in event_types
    assert "input_bound" not in event_types
    assert "node_ready" not in event_types

    events = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert events.status_code == 200
    recorded = next(
        event for event in events.json() if event["event_type"] == "approval_decision_recorded"
    )
    assert recorded["payload"]["decision"] == "rejected"
    assert recorded["payload"]["reason"] == "Reviewed output is unsafe."

    graph = await client.get(f"/api/runs/{run_id}/graph")
    assert graph.status_code == 200
    assert graph.json()["node_states"]["human-gate-1"] == "failed"

    scheduler = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    assert scheduler.status_code == 200
    assert scheduler.json()["scheduler"]["ready"] == []
    assert scheduler.json()["leases"]["active"] == []

    blockers = await client.get(f"/api/runs/{run_id}/graph/final-blockers")
    assert blockers.status_code == 503
    assert blockers.json()["detail"] == {
        "code": "read_model_unavailable",
        "run_id": run_id,
        "read_model": "graph_final_blockers_view",
        "current_position": response.json()["graph_position"],
        "reason": "missing_or_stale",
        "retryable": True,
    }

    assert await advance_graph_archival_maintenance_once(app) is True
    assert await advance_graph_archival_maintenance_once(app) is False

    blockers = await client.get(f"/api/runs/{run_id}/graph/final-blockers")
    assert blockers.status_code == 200
    final_blockers = blockers.json()["blockers"]
    assert any(
        blocker["kind"] == "dead_required_input" and blocker["node_id"] == "worker-successor"
        for blocker in final_blockers
    ), final_blockers


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


@pytest.mark.parametrize(
    ("decision_type", "decision"),
    [
        ("approval", "defer"),
        ("authority", "grant"),
        ("authority", "deny"),
    ],
)
async def test_record_decision_rejects_removed_decision_aliases_at_api_boundary(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
    decision_type: str,
    decision: str,
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-invalid-{uuid4().hex[:8]}"
    await _seed_decision_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": decision_type,
            "node_id": "authority-1",
            "decision": decision,
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert response.status_code == 422
    assert f"decision for {decision_type} must be one of" in response.text


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"node_id": ""},
        {"node_id": "n" * 201},
        {"decision": ""},
        {"decision": "a" * 65},
        {"record_id": ""},
        {"record_id": "r" * 201},
        {"decider": ""},
        {"decider": {"kind": ""}},
    ],
)
async def test_record_decision_restores_http_field_constraints(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
    invalid_fields: dict[str, object],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-decisions-malformed-{uuid4().hex[:8]}"
    await _seed_decision_graph_run(app, run_id)
    payload: dict[str, object] = {
        "decision_type": "authority",
        "node_id": "authority-1",
        "decision": "granted",
        "decider": {"kind": "human", "id": "alice"},
    }
    payload.update(invalid_fields)

    response = await client.post(f"/api/runs/{run_id}/graph/decisions", json=payload)

    assert response.status_code == 422


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
