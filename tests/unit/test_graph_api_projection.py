"""Unit tests for graph API projection helpers."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api import (
    _graph_backed_run_ids_from_rows,
    build_final_invariant_blockers_response,
    build_graph_patch_attempts_response,
    build_graph_projection_response,
    build_graph_regions_response,
    build_graph_topology_response,
    build_node_detail_response,
    build_node_detail_response_from_summary,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime.store import GraphEventStore, GraphNodeDetailSummary
from orchestrator.db import create_engine, create_session_factory, init_db


def _event(
    event_type: str,
    payload: dict[str, object],
    *,
    run_id: str = "run-1",
    position: int = -1,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-event",
        run_id=run_id,
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def test_build_graph_projection_response_empty() -> None:
    projection = build_graph_projection_response("run-empty", [])

    assert projection.run_id == "run-empty"
    assert projection.event_count == 0
    assert projection.run_state is None
    assert projection.node_states == {}
    assert projection.task_states == {}
    assert projection.leases == {}
    assert projection.ready_nodes == []


def test_build_node_detail_filters_by_node_id() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "node-a",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "node-b",
                "kind": "worker",
                "state": "planned",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "node-a",
                "new_state": "ready",
                "old_state": "planned",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "node-b",
                "new_state": "running",
                "old_state": "planned",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "out-a",
                "record_kind": "output",
                "producer_node_id": "node-a",
                "task_region_id": "task-a",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "out-b",
                "record_kind": "graph_record",
                "producer_node_id": "node-b",
                "task_region_id": "task-b",
            },
        ),
        _event(
            "file_state_accepted",
            {
                "path": "README.md",
                "producer_node_id": "node-a",
                "state": "unchanged",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "node-a",
                "new_state": "completed",
            },
        ),
    ]

    detail = build_node_detail_response("run-node", "node-a", events)

    assert detail is not None
    assert detail.node_id == "node-a"
    assert detail.state == "completed"
    assert detail.contract is not None
    assert detail.contract["node_type"] == "worker"
    assert detail.contract["handler_type"] == "agent"
    assert detail.contract["output_ports"]["candidate"]["record_types"] == ["candidate"]
    assert len(detail.output_records) == 1
    assert detail.output_records[0]["record_id"] == "out-a"
    assert len(detail.file_state_records) == 1
    assert detail.file_state_records[0]["path"] == "README.md"
    assert [e.event_id for e in detail.events] == [
        "node_created-event",
        "node_state_changed-event",
        "output_record_accepted-event",
        "file_state_accepted-event",
        "node_state_changed-event",
    ]


def test_build_node_detail_exposes_contract_and_runtime_controls_separately() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "planned",
                "resource_claims": [{"mode": "read", "scope": "repo"}],
                "allowed_actions": ["run_command"],
                "preconditions": ["has_command_definition"],
                "command_definition": {
                    "id": "unit-check",
                    "cmd": "uv run pytest tests/unit/test_example.py -q",
                    "timeout_seconds": 30,
                },
            },
        )
    ]

    detail = build_node_detail_response("run-node", "check-1", events)

    assert detail is not None
    assert detail.contract is not None
    assert detail.contract["node_type"] == "check"
    assert detail.contract["handler_type"] == "deterministic_command"
    assert detail.resource_claims == [{"mode": "read", "scope": "repo"}]
    assert detail.allowed_actions == ["run_command"]
    assert detail.preconditions == ["has_command_definition"]
    assert detail.command_definition == {
        "id": "unit-check",
        "cmd": "uv run pytest tests/unit/test_example.py -q",
        "timeout_seconds": 30,
    }


def test_full_node_detail_from_summary_hydrates_compact_positions_only() -> None:
    long_body = "x" * 1_100_000
    summary = GraphNodeDetailSummary(
        run_id="run-node",
        node_id="node-a",
        position=3,
        kind="worker",
        role="builder",
        state="completed",
        task_region_id="task-a",
        input_ports={},
        output_records=[
            {
                "record_id": "out-a",
                "record_kind": "output",
                "producer_node_id": "node-a",
                "port": "candidate",
            }
        ],
        file_state_records=[],
        leases=[],
        active_lease=None,
        callback_history=[],
        events=[
            {
                "event_id": "compact-node-a",
                "event_type": "output_record_accepted",
                "run_id": "run-node",
                "position": 2,
                "timestamp": FakeClock().now().isoformat(),
                "payload": {
                    "record_id": "out-a",
                    "producer_node_id": "node-a",
                },
            }
        ],
    )
    full_events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "out-a",
                "record_kind": "output",
                "producer_node_id": "node-a",
                "port": "candidate",
                "value": {"body": long_body, "paths": [f"file-{index}" for index in range(201)]},
            },
            run_id="run-node",
            position=2,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "out-b",
                "record_kind": "output",
                "producer_node_id": "node-b",
                "port": "candidate",
                "value": {"body": "unrelated"},
            },
            run_id="run-node",
            position=3,
        ),
    ]

    detail = build_node_detail_response_from_summary(summary, full_events=full_events)

    assert [event.position for event in detail.events] == [2]
    assert detail.events[0].payload["record_id"] == "out-a"
    assert "value" not in detail.events[0].payload
    assert detail.output_records[0]["record_id"] == "out-a"
    assert detail.output_records[0]["producer_node_id"] == "node-a"
    bounded_body = detail.output_records[0]["value"]["body"]
    assert len(bounded_body) < len(long_body)
    assert bounded_body.endswith("...[truncated 100000 chars]")
    assert detail.output_records[0]["value"]["__truncated_fields"][0]["field"] == "body"
    assert detail.output_records[0]["value"]["__truncated_fields"][0]["original_length"] == len(
        long_body
    )
    assert len(detail.output_records[0]["value"]["paths"]) == 200
    assert detail.output_records[0]["value"]["__truncated_fields"][1] == {
        "field": "paths",
        "original_length": 201,
        "retained_items": 200,
    }


def test_build_graph_topology_response_exposes_edge_contracts_and_bindings() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
            },
            position=1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "ready",
            },
            position=2,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-candidate",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "required": True,
                "dependency_type": "input_binding",
                "accepted_record_selector": {"record_kinds": ["candidate"]},
                "metadata": {"purpose": "candidate validation"},
                "binding_policy": "bind_first",
            },
            position=3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
            },
            position=4,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
            position=5,
        ),
    ]

    topology = build_graph_topology_response("run-topology", events)

    assert topology.event_count == 5
    assert {node.node_id for node in topology.nodes} == {"worker-1", "verifier-1"}
    worker = next(node for node in topology.nodes if node.node_id == "worker-1")
    assert worker.contract is not None
    assert worker.contract["output_ports"]["candidate"]["record_types"] == ["candidate"]
    edge = topology.edges[0]
    assert edge.edge_id == "edge-candidate"
    assert edge.metadata["metadata"] == {"purpose": "candidate validation"}
    assert edge.metadata["binding_policy"] == "bind_first"
    assert edge.record_types == ["candidate"]
    assert edge.source_port_contract is not None
    assert edge.source_port_contract["record_types"] == ["candidate"]
    assert edge.target_port_contract is not None
    assert edge.target_port_contract["cardinality"] == "one"
    assert edge.binding is not None
    assert edge.binding.record_ids == ["candidate-1"]
    assert edge.binding.bound_at_position == 4
    assert edge.binding.binding_policy == "bind_first"
    assert len(edge.bound_records) == 1
    assert edge.bound_records[0].record_id == "candidate-1"
    assert edge.bound_records[0].record_type == "candidate"
    assert edge.bound_records[0].schema_ == "ImplementationCandidate"


def test_build_graph_topology_response_exposes_accumulated_many_bindings() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
            },
            position=1,
        ),
        _event(
            "node_created",
            {
                "node_id": "summarizer-1",
                "kind": "summarizer",
                "state": "ready",
            },
            position=2,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "required": True,
                "prompt_hydration_policy": "structured_json",
            },
            position=3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
            },
            position=4,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
            position=5,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-2",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
            },
            position=6,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-2"],
                "bound_at_position": 6,
            },
            position=7,
        ),
    ]

    topology = build_graph_topology_response("run-topology", events)

    edge = topology.edges[0]
    assert edge.metadata["prompt_hydration_policy"] == "structured_json"
    assert edge.target_port_contract is not None
    assert edge.target_port_contract["cardinality"] == "many"
    assert edge.binding is not None
    assert edge.binding.binding_policy == "bind_all"
    assert edge.binding.record_ids == ["candidate-1", "candidate-2"]
    assert edge.binding.record_bound_positions == {"candidate-1": 4, "candidate-2": 6}
    assert [record.record_id for record in edge.bound_records] == ["candidate-1", "candidate-2"]


def test_build_final_invariant_blockers_response_returns_typed_blockers() -> None:
    events = [
        _event(
            "run_lifecycle_changed",
            {"from_state": "queued", "to_state": "active"},
            position=1,
        ),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
            position=2,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {
                    "status": "blocked",
                    "blockers": [
                        {
                            "kind": "open_planner_proposal",
                            "reason": "planner proposal has not been accepted or rejected",
                            "proposal_id": "proposal-1",
                        }
                    ],
                },
            },
            position=3,
        ),
    ]

    response = build_final_invariant_blockers_response("run-blocked", events)

    assert response.run_id == "run-blocked"
    assert response.event_count == 3
    assert len(response.blockers) == 1
    blocker = response.blockers[0]
    assert blocker.kind == "open_planner_proposal"
    assert blocker.reason == "planner proposal has not been accepted or rejected"
    assert blocker.proposal_id == "proposal-1"


def test_build_final_invariant_blockers_response_returns_pending_node_blocker() -> None:
    events = [
        _event(
            "run_lifecycle_changed",
            {"from_state": "queued", "to_state": "active"},
            position=1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "state": "suspended",
                "task_region_id": "task-1",
            },
            position=2,
        ),
    ]

    response = build_final_invariant_blockers_response("run-pending-node", events)

    assert response.run_id == "run-pending-node"
    assert response.event_count == 2
    assert len(response.blockers) == 2
    blocker = response.blockers[0]
    assert blocker.kind == "pending_node"
    assert blocker.reason == "node has not reached a terminal state"
    assert blocker.node_id == "verifier-1"
    assert blocker.task_region_id == "task-1"
    assert blocker.state == "suspended"
    assert response.blockers[1].kind == "task_not_accepted"


def test_build_final_invariant_blockers_response_exposes_impossible_input_details() -> None:
    events = [
        _event(
            "run_lifecycle_changed",
            {"from_state": "queued", "to_state": "active"},
            position=1,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
            },
            position=2,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-missing-candidate",
                "from_node_id": "missing-worker",
                "from_port": "candidate",
                "to_node_id": "worker-1",
                "to_port": "candidate",
                "required": True,
                "dependency_type": "input_binding",
            },
            position=3,
        ),
    ]

    response = build_final_invariant_blockers_response("run-impossible-input", events)

    blocker = next(blocker for blocker in response.blockers if blocker.kind == "impossible_input")
    assert blocker.node_id == "worker-1"
    assert blocker.edge_id == "edge-missing-candidate"
    assert blocker.to_port == "candidate"
    assert blocker.task_region_id == "task-1"
    assert blocker.state == "planned"


def test_build_graph_regions_response_groups_states_and_blockers() -> None:
    events = [
        _event(
            "run_lifecycle_changed",
            {"from_state": "queued", "to_state": "active"},
            position=1,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
            },
            position=2,
        ),
    ]

    response = build_graph_regions_response("run-regions", events)

    assert response.run_id == "run-regions"
    assert response.event_count == 2
    assert len(response.regions) == 1
    region = response.regions[0]
    assert region.task_region_id == "task-1"
    assert region.state == "pending"
    assert len(region.blockers) == 2
    assert region.blockers[0].kind == "pending_node"
    assert region.blockers[0].node_id == "worker-1"
    assert region.blockers[0].task_region_id == "task-1"
    assert region.blockers[1].kind == "task_not_accepted"
    assert region.blockers[1].task_region_id == "task-1"


def test_batch_graph_backed_detection() -> None:
    rows: list[tuple[str, int]] = [
        ("graph:run-draft", 0),
        ("graph:run-queued", 2),
        ("graph:run-complete", 1),
    ]
    assert _graph_backed_run_ids_from_rows(rows) == {"run-queued", "run-complete"}


def test_batch_graph_backed_detection_ignores_legacy_aggregates() -> None:
    # Legacy workflow events share events_v2 with aggregate_id == run_id;
    # they must never make a run count as graph-backed.
    rows: list[tuple[str, int]] = [("run-legacy", 7), ("graph:run-graph", 3)]
    assert _graph_backed_run_ids_from_rows(rows) == {"run-graph"}


@pytest.mark.asyncio
async def test_build_graph_patch_attempts_response_reads_accepted_and_rejected_patches(
    session: AsyncSession,
) -> None:
    store = GraphEventStore(session)
    events = [
        _event(
            "graph_patch_proposed",
            {
                "patch_id": "patch-accepted",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
            },
            position=1,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-accepted",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
                "actor_role": "planner",
                "successor_planner_node_ids": ["planner-2"],
            },
            position=2,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
            position=3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "planner-1",
                "from_port": "graph_patch",
                "to_node_id": "worker-1",
                "to_port": "input",
                "required": True,
                "dependency_type": "input_binding",
            },
            position=4,
        ),
        _event(
            "node_state_changed",
            {"node_id": "worker-1", "new_state": "ready"},
            position=5,
        ),
        _event(
            "node_created",
            {
                "node_id": "unrelated-later-node",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
            position=6,
        ),
        _event(
            "graph_patch_rejected",
            {
                "patch_id": "patch-rejected",
                "proposed_by_node_id": "planner-2",
                "base_graph_position": 4,
                "reason": "stale patch conflicts with invalidating events",
                "read_set_diff": {
                    "patch_read_set": ["worker-1"],
                    "conflicting_event_ids": ["event-9"],
                },
            },
            position=7,
        ),
    ]

    await store.append_events("run-patches", 0, events)

    response = build_graph_patch_attempts_response(
        "run-patches",
        await store.read_run("run-patches"),
        current_graph_position=await store.current_position("run-patches"),
    )

    assert response.run_id == "run-patches"
    assert response.current_graph_position == 7
    assert [attempt.patch_id for attempt in response.attempts] == [
        "patch-accepted",
        "patch-rejected",
    ]

    accepted = response.attempts[0]
    assert accepted.status == "accepted"
    assert accepted.proposed_by_node_id == "planner-1"
    assert accepted.base_graph_position == 2
    assert accepted.accepted_position == 2
    assert accepted.created_node_ids == ["worker-1"]
    assert accepted.created_edge_ids == ["edge-1"]
    assert accepted.diagnostics["actor_role"] == "planner"
    assert accepted.diagnostics["successor_planner_node_ids"] == ["planner-2"]

    rejected = response.attempts[1]
    assert rejected.status == "rejected"
    assert rejected.proposed_by_node_id == "planner-2"
    assert rejected.base_graph_position == 4
    assert rejected.rejection_reason == "stale patch conflicts with invalidating events"
    assert rejected.read_set_diff == {
        "patch_read_set": ["worker-1"],
        "conflicting_event_ids": ["event-9"],
    }
