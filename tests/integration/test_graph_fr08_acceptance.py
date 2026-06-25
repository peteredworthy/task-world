"""FR-08 acceptance coverage for mutation validation and authority decisions."""

from datetime import timezone
import json
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphController, GraphEventStore


SECRET_COMMAND = "uv run pytest tests/oracle -q"


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


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr08-acceptance-repo-{run_id}",
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
                        title="Prove mutation validation",
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


async def _seed_invalid_patch_graph_run(app: Any, run_id: str) -> GraphController:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_graph_run(session_factory, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "running"},
        ),
        _event("node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "planned"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["docs/"]}],
            },
        ),
        _event(
            "node_state_changed",
            {"node_id": "worker-1", "new_state": "running", "trigger": "test_seed"},
        ),
        _event(
            "node_created",
            {"node_id": "worker-stale", "kind": "worker", "role": "builder", "state": "planned"},
        ),
        _event(
            "node_state_changed",
            {"node_id": "worker-stale", "new_state": "cancelled", "trigger": "test_seed"},
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


async def _submit_patch(
    controller: GraphController,
    run_id: str,
    *,
    expected_position: int,
    patch_id: str,
    ops: list[dict[str, Any]],
    actor_role: str = "planner",
    base_graph_position: int | None = None,
) -> None:
    await controller.handle_command(
        run_id,
        expected_position,
        "submit_patch",
        {
            "patch_id": patch_id,
            "proposed_by_node_id": "planner-1",
            "base_graph_position": expected_position
            if base_graph_position is None
            else base_graph_position,
            "actor_role": actor_role,
            "ops": ops,
        },
    )


async def _events(client: AsyncClient, run_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert response.status_code == 200
    return response.json()


async def _patches(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/runs/{run_id}/graph/patches")
    assert response.status_code == 200
    return response.json()


async def _seed_authority_denial_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_graph_run(session_factory, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "authority-1", "kind": "authority_request", "state": "running"},
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
                "execution_id": "exec-authority-1",
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


async def test_fr08_invalid_patch_matrix_rejected_and_readable(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fr08-patch-{uuid4().hex[:8]}"
    controller = await _seed_invalid_patch_graph_run(app, run_id)

    await _submit_patch(
        controller,
        run_id,
        expected_position=7,
        patch_id="patch-stale",
        base_graph_position=6,
        ops=[{"op": "retire_node", "node_id": "worker-stale"}],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=8,
        patch_id="patch-unauthorized",
        actor_role="worker",
        ops=[{"op": "create_node", "node": {"node_id": "artifact-unauth", "kind": "artifact"}}],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=9,
        patch_id="patch-duplicate-node",
        ops=[
            {
                "op": "create_node",
                "node": {"node_id": "worker-1", "kind": "worker", "role": "builder"},
            }
        ],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=10,
        patch_id="patch-hidden-command",
        ops=[
            {
                "op": "create_node",
                "node": {
                    "node_id": "check-hidden",
                    "kind": "check",
                    "role": "invariant_gate",
                    "state": "planned",
                    "hidden_oracle_command": SECRET_COMMAND,
                },
            },
            {
                "op": "create_edge",
                "edge_id": "edge-verifier-check-hidden",
                "from_node_id": "verifier-1",
                "from_port": "verification_report",
                "to_node_id": "check-hidden",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
            },
        ],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=11,
        patch_id="patch-resource-escalation",
        ops=[
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/"]}],
            }
        ],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=12,
        patch_id="patch-active-retire",
        ops=[{"op": "retire_node", "node_id": "worker-1"}],
    )

    events = await _events(client, run_id)
    patch_view = await _patches(client, run_id)
    topology_resp = await client.get(f"/api/runs/{run_id}/graph/topology")
    assert topology_resp.status_code == 200

    rejected = [event for event in events if event["event_type"] == "graph_patch_rejected"]
    assert [event["payload"]["patch_id"] for event in rejected] == [
        "patch-stale",
        "patch-unauthorized",
        "patch-duplicate-node",
        "patch-hidden-command",
        "patch-resource-escalation",
        "patch-active-retire",
    ]
    expected_reasons = {
        "patch-stale": "stale patch conflicts with invalidating events",
        "patch-unauthorized": "actor role worker cannot perform create_node",
        "patch-duplicate-node": "duplicate node id: worker-1",
        "patch-hidden-command": (
            "check node cannot expose hidden_oracle_command; use command_binding: check-hidden"
        ),
        "patch-resource-escalation": "resource claim escalation for worker-1: write",
        "patch-active-retire": "cannot retire active node: worker-1",
    }
    assert {event["payload"]["patch_id"]: event["payload"]["reason"] for event in rejected} == (
        expected_reasons
    )
    stale_payload = rejected[0]["payload"]
    assert stale_payload["read_set_diff"]["patch_read_set"] == ["worker-stale"]
    assert stale_payload["read_set_diff"]["conflicting_event_ids"]

    attempts = patch_view["attempts"]
    assert [attempt["patch_id"] for attempt in attempts] == list(expected_reasons)
    assert {attempt["patch_id"]: attempt["status"] for attempt in attempts} == {
        patch_id: "rejected" for patch_id in expected_reasons
    }
    assert {attempt["patch_id"]: attempt["rejection_reason"] for attempt in attempts} == (
        expected_reasons
    )
    assert all(attempt["created_node_ids"] == [] for attempt in attempts)
    assert all(attempt["created_edge_ids"] == [] for attempt in attempts)
    topology = topology_resp.json()
    assert {node["node_id"] for node in topology["nodes"]} == {
        "planner-1",
        "verifier-1",
        "worker-1",
        "worker-stale",
    }
    assert topology["edges"] == []
    assert SECRET_COMMAND not in json.dumps(events)
    assert SECRET_COMMAND not in json.dumps(patch_view)


async def test_fr08_authority_denial_and_rejection_readbacks(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fr08-authority-{uuid4().hex[:8]}"
    await _seed_authority_denial_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "deny",
            "decider": {"kind": "human", "id": "alice"},
            "reason": "Rejected for FR-08 denial proof.",
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
    assert "node_deferred" in event_types
    decision_record = body["events"][1]["payload"]
    assert decision_record["record_type"] == "authority_decision"
    assert decision_record["value"]["decision"] == "denied"
    assert body["events"][4]["payload"]["lease_id"] == "lease-authority-1"
    assert any(
        event["event_type"] == "node_deferred"
        and event["payload"]
        == {
            "node_id": "worker-docs",
            "reason": "authority_not_granted:authority-1",
        }
        for event in body["events"]
    )

    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    authority_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/authority-1?payload_mode=full"
    )
    worker_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/worker-docs")
    topology_resp = await client.get(f"/api/runs/{run_id}/graph/topology")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert scheduler_resp.status_code == 200
    assert authority_resp.status_code == 200
    assert worker_resp.status_code == 200
    assert topology_resp.status_code == 200
    assert events_resp.status_code == 200

    scheduler = scheduler_resp.json()
    authority = authority_resp.json()
    worker = worker_resp.json()
    assert scheduler["scheduler"]["ready"] == []
    assert scheduler["scheduler"]["blocked"] == []
    assert scheduler["leases"]["active"] == []
    assert authority["state"] == "completed"
    authority_decisions = [
        record
        for record in authority["output_records"]
        if record["record_type"] == "authority_decision"
    ]
    assert len(authority_decisions) == 1
    assert authority_decisions[0]["value"]["decision"] == "denied"
    assert worker["state"] == "planned"
    assert worker["input_ports"]["authority"] == ["authority_decision-authority-1"]
    authority_edge = next(
        edge for edge in topology_resp.json()["edges"] if edge["edge_id"] == "edge-authority-worker"
    )
    assert authority_edge["binding"]["record_ids"] == ["authority_decision-authority-1"]

    invalid_target = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "worker-docs",
            "decision": "grant",
            "decider": {"kind": "human", "id": "alice"},
        },
    )
    assert invalid_target.status_code == 409
    assert "authority decisions require authority_request target" in invalid_target.text

    invalid_shape = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )
    assert invalid_shape.status_code == 422
    assert "decision for authority must be one of" in invalid_shape.text

    events = events_resp.json()
    assert any(
        event["event_type"] == "authority_decision_recorded"
        and event["payload"]["decision"] == "denied"
        for event in events
    )
    assert not any(
        event["event_type"] == "output_record_accepted"
        and event["payload"].get("producer_node_id") == "worker-docs"
        for event in events
    )
