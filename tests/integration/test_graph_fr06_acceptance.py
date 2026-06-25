from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphController, GraphEventStore


@pytest.fixture
async def fr06_app() -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=None, routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


async def test_fr06_edges_bind_fanout_join_optional_bind_all_and_supersede(
    fr06_app: tuple[AsyncClient, Any],
) -> None:
    client, app = fr06_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    run_id = f"fr06-bindings-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, run_id)
    await _seed_fr06_graph(session_factory, run_id)
    controller = GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )

    first_callback = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "submit_callback",
        _callback_payload(
            run_id,
            observed_graph_position=await controller.current_position(run_id),
            idempotency_key="fr06-first-callback",
            payload_hash="fr06-first",
            output_records=[
                _candidate("candidate-1", "first candidate"),
                _candidate("candidate-2", "second candidate"),
                _file_state("file-state-1", "snapshot-1"),
            ],
            complete_node=False,
        ),
    )
    assert [event.event_type for event in first_callback.events].count("input_bound") == 9

    second_callback = await controller.handle_command(
        run_id,
        first_callback.projection_position,
        "submit_callback",
        _callback_payload(
            run_id,
            observed_graph_position=first_callback.projection_position,
            idempotency_key="fr06-supersede-callback",
            payload_hash="fr06-supersede",
            output_records=[
                _file_state(
                    "file-state-2",
                    "snapshot-2",
                    supersedes_record_id="file-state-1",
                )
            ],
            complete_node=False,
        ),
    )
    assert any(
        event.event_type == "input_bound"
        and event.payload["to_node_id"] == "planner-1"
        and event.payload["record_ids"] == ["file-state-2"]
        and event.payload["supersedes_record_id"] == "file-state-1"
        for event in second_callback.events
    )

    joined = await controller.handle_command(
        run_id,
        second_callback.projection_position,
        "evaluate_join",
        {"node_id": "join-1", "record_id": "join-result-fr06"},
    )
    assert joined.events[0].event_type == "output_record_accepted"
    assert joined.events[0].payload["value"] == {
        "status": "ready",
        "source_record_ids": ["candidate-1"],
    }

    first_rejection = await _submit_bad_edge_patch(
        controller,
        run_id,
        joined.projection_position,
        "patch-fr06-bad-port",
        {
            "op": "create_edge",
            "edge_id": "edge-bad-port",
            "from_node_id": "worker-1",
            "from_port": "candidate",
            "to_node_id": "verifier-a",
            "to_port": "source_records",
            "required": True,
        },
    )
    second_rejection = await _submit_bad_edge_patch(
        controller,
        run_id,
        first_rejection.projection_position,
        "patch-fr06-bad-policy",
        {
            "op": "create_edge",
            "edge_id": "edge-bad-policy",
            "from_node_id": "worker-1",
            "from_port": "candidate",
            "to_node_id": "summarizer-1",
            "to_port": "source_records",
            "required": True,
            "binding_policy": "bind_first",
        },
    )
    third_rejection = await _submit_bad_edge_patch(
        controller,
        run_id,
        second_rejection.projection_position,
        "patch-fr06-bad-selector",
        {
            "op": "create_edge",
            "edge_id": "edge-bad-selector",
            "from_node_id": "worker-1",
            "from_port": "candidate",
            "to_node_id": "verifier-b",
            "to_port": "candidate_under_test",
            "required": True,
            "accepted_record_selector": {"record_kinds": ["verification"]},
        },
    )
    assert [event.event_type for event in third_rejection.events] == ["graph_patch_rejected"]

    scheduled = await controller.handle_command(
        run_id,
        third_rejection.projection_position,
        "schedule_tick",
        {"max_grants": 0, "base_snapshot_id": "S0"},
    )
    assert any(
        event.event_type == "node_ready" and event.payload["node_id"] == "optional-worker"
        for event in scheduled.events
    )

    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    topology = await _get_json(client, f"/api/runs/{run_id}/graph/topology")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    patches = await _get_json(client, f"/api/runs/{run_id}/graph/patches")
    join = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/join-1?payload_mode=full")
    optional_worker = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/optional-worker")
    planner = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/planner-1")
    final_blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")

    optional_edge_event = next(
        event
        for event in events
        if event["event_type"] == "edge_created"
        and event["payload"]["edge_id"] == "edge-optional-artifact"
    )
    assert optional_edge_event["payload"]["required"] is False

    edge_by_id = {edge["edge_id"]: edge for edge in topology["edges"]}
    assert edge_by_id["edge-candidate-verifier-a"]["binding"]["record_ids"] == ["candidate-1"]
    assert edge_by_id["edge-candidate-verifier-b"]["binding"]["record_ids"] == ["candidate-1"]
    assert (
        edge_by_id["edge-candidate-verifier-a"]["target_port_contract"]
        == (edge_by_id["edge-candidate-verifier-b"]["target_port_contract"])
    )
    assert edge_by_id["edge-candidate-summarizer"]["binding"]["binding_policy"] == "bind_all"
    assert edge_by_id["edge-candidate-summarizer"]["binding"]["record_ids"] == [
        "candidate-1",
        "candidate-2",
    ]
    assert edge_by_id["edge-candidate-summarizer"]["target_port_contract"]["cardinality"] == (
        "many"
    )
    assert edge_by_id["edge-candidate-join"]["target_port_contract"]["record_types"] == [
        "candidate",
        "check_result",
        "file_state",
        "verification_report",
    ]
    assert edge_by_id["edge-candidate-join"]["binding"]["binding_policy"] == "bind_first"
    assert edge_by_id["edge-file-state-planner"]["binding"]["binding_policy"] == (
        "rebind_on_superseding"
    )
    assert edge_by_id["edge-file-state-planner"]["binding"]["record_ids"] == ["file-state-2"]
    assert edge_by_id["edge-file-state-planner"]["binding"]["record_bound_positions"] == {
        "file-state-2": 33
    }
    assert edge_by_id["edge-optional-artifact"]["required"] is False, edge_by_id[
        "edge-optional-artifact"
    ]
    assert edge_by_id["edge-optional-artifact"]["binding"] is None

    assert join["output_records"][0]["record_id"] == "join-result-fr06"
    assert optional_worker["state"] == "ready"
    assert optional_worker["input_ports"] == {}
    assert planner["input_ports"]["accepted_file_state"] == ["file-state-2"]
    assert "optional-worker" in scheduler["scheduler"]["ready"]
    blocker_node_ids = {blocker.get("node_id") for blocker in final_blockers["blockers"]}
    assert {"verifier-a", "verifier-b", "optional-worker"} <= blocker_node_ids

    rejection_reasons = {
        attempt["patch_id"]: attempt["rejection_reason"]
        for attempt in patches["attempts"]
        if attempt["status"] == "rejected"
    }
    assert "unknown target port" in rejection_reasons["patch-fr06-bad-port"]
    assert "binding_policy bind_first is incompatible" in rejection_reasons["patch-fr06-bad-policy"]
    assert "selector is incompatible" in rejection_reasons["patch-fr06-bad-selector"]


async def _submit_bad_edge_patch(
    controller: GraphController,
    run_id: str,
    expected_position: int,
    patch_id: str,
    op: dict[str, Any],
) -> Any:
    result = await controller.handle_command(
        run_id,
        expected_position,
        "submit_patch",
        {
            "patch_id": patch_id,
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": expected_position,
            "ops": [op],
        },
    )
    assert [event.event_type for event in result.events] == ["graph_patch_rejected"]
    return result


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr06-acceptance-repo-{run_id}",
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
                        title="Prove FR-06 bindings",
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


async def _seed_fr06_graph(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, _fr06_events(run_id))
        await session.commit()


def _fr06_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event(run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "running",
            },
        ),
        _event(
            run_id,
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-worker-1",
                "generation": 1,
                "execution_id": "exec-worker-1",
                "base_snapshot_id": "S0",
            },
        ),
        _event(
            run_id,
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "planned"},
        ),
        _event(
            run_id,
            "node_created",
            {"node_id": "verifier-a", "kind": "verifier", "role": "verifier", "state": "planned"},
        ),
        _event(
            run_id,
            "node_created",
            {"node_id": "verifier-b", "kind": "verifier", "role": "verifier", "state": "planned"},
        ),
        _event(run_id, "node_created", {"node_id": "summarizer-1", "kind": "summarizer"}),
        _event(
            run_id,
            "node_created",
            {"node_id": "join-1", "kind": "join", "role": "fan_out_join", "state": "planned"},
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "optional-worker",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _edge(
            run_id,
            "edge-candidate-verifier-a",
            "worker-1",
            "candidate",
            "verifier-a",
            "candidate_under_test",
        ),
        _edge(
            run_id,
            "edge-candidate-verifier-b",
            "worker-1",
            "candidate",
            "verifier-b",
            "candidate_under_test",
        ),
        _edge(
            run_id,
            "edge-candidate-summarizer",
            "worker-1",
            "candidate",
            "summarizer-1",
            "source_records",
        ),
        _edge(
            run_id,
            "edge-candidate-join",
            "worker-1",
            "candidate",
            "join-1",
            "source_record_1",
        ),
        _edge(
            run_id,
            "edge-file-state-planner",
            "worker-1",
            "file_state",
            "planner-1",
            "accepted_file_state",
            binding_policy="rebind_on_superseding",
        ),
        _edge(
            run_id,
            "edge-optional-artifact",
            "worker-1",
            "artifact_reference",
            "optional-worker",
            "artifact_reference",
            required=False,
        ),
    ]


def _edge(
    run_id: str,
    edge_id: str,
    from_node_id: str,
    from_port: str,
    to_node_id: str,
    to_port: str,
    *,
    required: bool = True,
    binding_policy: str | None = None,
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "required": required,
    }
    if binding_policy is not None:
        payload["binding_policy"] = binding_policy
    return _event(run_id, "edge_created", payload)


def _callback_payload(
    run_id: str,
    *,
    observed_graph_position: int,
    idempotency_key: str,
    payload_hash: str,
    output_records: list[dict[str, Any]],
    complete_node: bool,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "node_id": "worker-1",
        "execution_id": "exec-worker-1",
        "lease_id": "lease-worker-1",
        "lease_generation": 1,
        "base_snapshot_id": "S0",
        "observed_graph_position": observed_graph_position,
        "idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "complete_node": complete_node,
        "payload": {
            "payload_hash": payload_hash,
            "output_records": output_records,
        },
    }


def _candidate(record_id: str, summary: str) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "record_kind": "output",
        "record_type": "candidate",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "value": {"summary": summary},
    }


def _file_state(
    record_id: str,
    snapshot_id: str,
    *,
    supersedes_record_id: str | None = None,
) -> dict[str, Any]:
    output = {
        "record_id": record_id,
        "record_kind": "file_state",
        "record_type": "file_state",
        "producer_node_id": "worker-1",
        "port": "file_state",
        "schema": "FileStateRecord",
        "snapshot_id": snapshot_id,
        "base_snapshot_id": "S0",
        "verdict": "captured",
    }
    if supersedes_record_id is not None:
        output["supersedes_record_id"] = supersedes_record_id
    return output


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _event(run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
