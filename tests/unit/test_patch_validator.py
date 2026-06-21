"""Unit tests for pure graph patch validation."""

from datetime import UTC, datetime
from typing import Any, cast

from orchestrator.graph.models import (
    Actor,
    ActorKind,
    EventEnvelope,
    PatchEnvelope,
    PatchOp,
)
from orchestrator.graph.patch_validator import PatchValidationResult, validate_patch
from orchestrator.graph.projections import GraphProjection, initial_projection


def _patch(
    ops: list[dict[str, Any]],
    *,
    base_graph_position: int = 10,
) -> PatchEnvelope:
    return PatchEnvelope(
        patch_id="patch-1",
        proposed_by_node_id="planner-1",
        base_graph_position=base_graph_position,
        ops=[PatchOp(**op) for op in ops],
        rationale_record_id=None,
    )


def _event(
    event_type: str,
    payload: dict[str, Any],
    *,
    event_id: str = "event-1",
    position: int = 11,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def _projection(
    *,
    node_states: dict[str, str] | None = None,
    node_kinds: dict[str, str] | None = None,
    node_roles: dict[str, str] | None = None,
    edges: dict[str, dict[str, Any]] | None = None,
    resource_claims: dict[str, list[dict[str, Any]]] | None = None,
) -> GraphProjection:
    projection = initial_projection()
    if node_states is not None:
        projection["node_states"] = node_states
    if node_kinds is not None:
        projection["node_kinds"] = node_kinds
    if node_roles is not None:
        projection["node_roles"] = node_roles
    if edges is not None:
        projection["edges"] = edges
    if resource_claims is not None:
        cast(dict[str, Any], projection)["resource_claims"] = resource_claims
    return projection


def _validate(
    patch: PatchEnvelope,
    *,
    current_position: int = 10,
    events_since_base: list[EventEnvelope] | None = None,
    projection: GraphProjection | None = None,
    actor_role: str = "planner",
) -> PatchValidationResult:
    return validate_patch(
        patch,
        current_position,
        events_since_base or [],
        projection or initial_projection(),
        actor_role,
    )


def test_patch_at_current_position_accepted() -> None:
    result = _validate(
        _patch([{"op": "create_node", "node": {"node_id": "note-1", "kind": "artifact"}}])
    )

    assert result.accepted


def test_patch_stale_neutral_events_only_accepted() -> None:
    patch = _patch([{"op": "retire_node", "node_id": "worker-1"}], base_graph_position=10)
    events = [
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}),
        _event("cost_recorded", {"node_id": "worker-1", "tokens": 100}, event_id="event-2"),
        _event("heartbeat_recorded", {"node_id": "worker-1"}, event_id="event-3"),
    ]

    result = _validate(
        patch,
        current_position=13,
        events_since_base=events,
        projection=_projection(node_states={"worker-1": "planned"}),
    )

    assert result.accepted


def test_patch_stale_invalidating_event_in_read_set_rejected() -> None:
    patch = _patch([{"op": "retire_node", "node_id": "worker-1"}], base_graph_position=10)
    conflict = _event(
        "node_state_changed",
        {"node_id": "worker-1", "new_state": "retired"},
    )

    result = _validate(
        patch,
        current_position=11,
        events_since_base=[conflict],
        projection=_projection(node_states={"worker-1": "planned"}),
    )

    assert not result.accepted
    assert result.conflicting_events == [conflict]
    assert result.read_set_diff == {
        "patch_read_set": ["worker-1"],
        "conflicting_event_ids": ["event-1"],
    }


def test_patch_stale_invalidating_event_not_in_read_set_accepted() -> None:
    patch = _patch([{"op": "retire_node", "node_id": "worker-1"}], base_graph_position=10)
    conflict_elsewhere = _event(
        "node_state_changed",
        {"node_id": "worker-2", "new_state": "retired"},
    )

    result = _validate(
        patch,
        current_position=11,
        events_since_base=[conflict_elsewhere],
        projection=_projection(node_states={"worker-1": "planned"}),
    )

    assert result.accepted


def test_planner_can_create_node() -> None:
    result = _validate(
        _patch([{"op": "create_node", "node": {"node_id": "artifact-1", "kind": "artifact"}}])
    )

    assert result.accepted


def test_create_node_rejects_unknown_node_type() -> None:
    result = _validate(
        _patch([{"op": "create_node", "node": {"node_id": "mystery-1", "kind": "mystery"}}])
    )

    assert not result.accepted
    assert result.rejection_reason == "unknown node type: mystery"


def test_create_node_rejects_unknown_declared_input_port() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "inputs": [{"port": "not_a_real_input", "direction": "input"}],
                    },
                }
            ]
        )
    )

    assert not result.accepted
    assert result.rejection_reason == "node worker-1 declares unknown input port: not_a_real_input"


def test_planner_cannot_create_check_without_command_definition() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                    },
                }
            ]
        )
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "check node requires command_definition, hidden_oracle_command, or command_binding: check-1"
    )


def test_planner_cannot_create_check_with_hidden_oracle_command() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "hidden_oracle_command": "uv run pytest tests/oracle -q",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-check",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-1",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
                },
            ]
        ),
        projection=_projection(node_kinds={"verifier-1": "verifier"}),
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "check node cannot expose hidden_oracle_command; use command_binding: check-1"
    )


def test_planner_can_create_check_with_command_definition() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "command_definition": {"cmd": "uv run pytest tests/oracle -q"},
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-check",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-1",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
                },
            ]
        ),
        projection=_projection(node_kinds={"verifier-1": "verifier"}),
    )

    assert result.accepted


def test_planner_can_create_check_with_dynamic_feature_oracle_binding() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "command_binding": "dynamic_feature_hidden_oracle",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-check",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-1",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
                },
            ]
        ),
        projection=_projection(node_kinds={"verifier-1": "verifier"}),
    )

    assert result.accepted


def test_planner_cannot_create_check_with_unknown_command_binding() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "command_binding": "unknown_binding",
                    },
                }
            ]
        )
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "check node requires command_definition, hidden_oracle_command, or command_binding: check-1"
    )


def test_create_edge_rejects_unknown_endpoint_node_in_projection() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_edge",
                    "edge_id": "edge-1",
                    "from_node_id": "missing-source",
                    "from_port": "verification_report",
                    "to_node_id": "missing-target",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification"]},
                }
            ]
        )
    )

    assert not result.accepted
    assert result.rejection_reason == "edge edge-1 references unknown source node: missing-source"


def test_create_edge_rejects_unknown_endpoint_node_in_same_patch() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-1",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "missing-target",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification"]},
                },
            ]
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == "edge edge-1 references unknown target node: missing-target"


def test_create_edge_rejects_unknown_source_port() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "command_binding": "dynamic_feature_hidden_oracle",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-1",
                    "from_node_id": "verifier-1",
                    "from_port": "not_a_real_output",
                    "to_node_id": "check-1",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification"]},
                },
            ]
        ),
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "edge edge-1 references unknown source port verifier.not_a_real_output"
    )


def test_create_edge_rejects_unknown_target_port() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "command_binding": "dynamic_feature_hidden_oracle",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-1",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-1",
                    "to_port": "not_a_real_input",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification"]},
                },
            ]
        ),
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "edge edge-1 references unknown target port check.not_a_real_input"
    )


def test_create_edge_rejects_new_cycle() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_edge",
                    "edge_id": "edge-cycle",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "worker-1",
                    "to_port": "verification_report",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification"]},
                },
            ]
        ),
        projection=_projection(
            node_kinds={"worker-1": "worker", "verifier-1": "verifier"},
            edges={
                "edge-existing": {
                    "edge_id": "edge-existing",
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "required": True,
                }
            },
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == (
        "graph patch would create forbidden cycle: verifier-1 -> worker-1 -> verifier-1"
    )


def test_create_edge_rejects_selector_incompatible_with_source_port() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "command_binding": "dynamic_feature_hidden_oracle",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-1",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-1",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["candidate"]},
                },
            ]
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == "edge edge-1 selector is incompatible with source output port"


def test_planner_cannot_create_gate() -> None:
    result = _validate(_patch([{"op": "create_gate", "predecessor_node_ids": ["worker-1"]}]))

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "cannot perform create_gate" in result.rejection_reason


def test_oversight_can_create_gate() -> None:
    result = _validate(
        _patch([{"op": "create_gate", "predecessor_node_ids": ["worker-1"]}]),
        actor_role="oversight",
    )

    assert result.accepted


def test_gap_planner_can_submit_no_op_patch() -> None:
    result = _validate(_patch([]), actor_role="gap_planner")

    assert result.accepted


def test_gap_planner_no_op_rejected_when_classified_gap_successor_waits() -> None:
    projection = initial_projection()
    projection["edges"]["edge-gap-to-corrective"] = {
        "edge_id": "edge-gap-to-corrective",
        "from_node_id": "planner-1",
        "from_port": "gap_classification",
        "to_node_id": "worker-corrective",
        "to_port": "classified_gap",
        "required": True,
        "dependency_type": "input_binding",
    }

    result = _validate(_patch([]), projection=projection, actor_role="gap_planner")

    assert not result.accepted
    assert (
        result.rejection_reason
        == "gap planner no-op leaves required classified_gap successor unsatisfied"
    )


def test_gap_planner_can_append_corrective_work_region() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "corrective-worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": "corrective_work_region",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "corrective-verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                        "task_region_id": "corrective_work_region",
                    },
                },
            ]
        ),
        actor_role="gap_planner",
    )

    assert result.accepted


def test_gap_planner_cannot_create_generic_planner_successor() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "planner-successor-1",
                        "kind": "planner",
                        "role": "planner",
                        "state": "planned",
                    },
                }
            ]
        ),
        actor_role="gap_planner",
    )

    assert not result.accepted
    assert result.rejection_reason == "gap planner cannot create planner successor"


def test_gap_planner_cannot_create_gap_planner_successor() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "gap-planner-successor-1",
                        "kind": "planner",
                        "role": "gap_planner",
                        "state": "planned",
                    },
                }
            ]
        ),
        actor_role="gap_planner",
    )

    assert not result.accepted
    assert result.rejection_reason == "gap planner cannot create planner successor"


def test_gap_planner_executable_work_must_be_corrective() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "extra-worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": "optional_expansion_region",
                    },
                }
            ]
        ),
        actor_role="gap_planner",
    )

    assert not result.accepted
    assert result.rejection_reason == (
        "gap planner executable nodes must target corrective_work_region"
    )


def test_unknown_op_rejected() -> None:
    result = _validate(_patch([{"op": "teleport_node", "node_id": "worker-1"}]))

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "unknown op" in result.rejection_reason


def test_set_resource_claims_escalation_rejected() -> None:
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "repo"}],
            }
        ]
    )

    result = _validate(
        patch,
        projection=_projection(
            resource_claims={"worker-1": [{"mode": "read", "scope": "repo"}]},
        ),
    )

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "resource claim escalation" in result.rejection_reason


def test_set_resource_claims_narrowing_accepted() -> None:
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "read", "scope": "repo"}],
            }
        ]
    )

    result = _validate(
        patch,
        projection=_projection(
            resource_claims={"worker-1": [{"mode": "graph_write", "scope": "repo"}]},
        ),
    )

    assert result.accepted


def test_retire_running_node_rejected() -> None:
    result = _validate(
        _patch([{"op": "retire_node", "node_id": "worker-1"}]),
        projection=_projection(node_states={"worker-1": "running"}),
    )

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "cannot retire active node" in result.rejection_reason


def test_retire_planned_node_accepted() -> None:
    result = _validate(
        _patch([{"op": "retire_node", "node_id": "worker-1"}]),
        projection=_projection(node_states={"worker-1": "planned"}),
    )

    assert result.accepted


def test_gap_planner_cannot_retire_executable_node() -> None:
    result = _validate(
        _patch([{"op": "retire_node", "node_id": "worker-1"}]),
        projection=_projection(
            node_states={"worker-1": "planned"},
            node_kinds={"worker-1": "worker"},
        ),
        actor_role="gap_planner",
    )

    assert not result.accepted
    assert result.rejection_reason == "gap planner cannot retire executable node: worker-1"


def test_create_worker_without_role_rejected() -> None:
    result = _validate(
        _patch([{"op": "create_node", "node": {"node_id": "worker-1", "kind": "worker"}}])
    )

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "requires role" in result.rejection_reason


def test_unknown_node_type_rejected() -> None:
    result = _validate(
        _patch([{"op": "create_node", "node": {"node_id": "mystery-1", "kind": "mystery"}}])
    )

    assert not result.accepted
    assert result.rejection_reason == "unknown node type: mystery"


def test_declared_unknown_node_port_rejected() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "inputs": [{"port": "untyped_blob", "direction": "input"}],
                    },
                }
            ]
        )
    )

    assert not result.accepted
    assert result.rejection_reason == "node worker-1 declares unknown input port: untyped_blob"


def test_edge_unknown_source_node_rejected() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-worker-verifier",
                    "from_node_id": "worker-missing",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                },
            ]
        )
    )

    assert not result.accepted
    assert result.rejection_reason == (
        "edge edge-worker-verifier references unknown source node: worker-missing"
    )


def test_edge_unknown_port_rejected() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_edge",
                    "edge_id": "edge-worker-verifier",
                    "from_node_id": "worker-1",
                    "from_port": "diagnostic",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                }
            ]
        ),
        projection=_projection(
            node_kinds={"worker-1": "worker", "verifier-1": "verifier"},
            node_states={"worker-1": "completed", "verifier-1": "planned"},
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == (
        "edge edge-worker-verifier references unknown source port worker.diagnostic"
    )


def test_edge_selector_incompatible_with_source_port_rejected() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_edge",
                    "edge_id": "edge-worker-verifier",
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "accepted_record_selector": {"record_kinds": ["verification"]},
                }
            ]
        ),
        projection=_projection(
            node_kinds={"worker-1": "worker", "verifier-1": "verifier"},
            node_states={"worker-1": "completed", "verifier-1": "planned"},
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == (
        "edge edge-worker-verifier selector is incompatible with source output port"
    )


def test_multi_op_patch_one_fails_rejected() -> None:
    patch = _patch(
        [
            {"op": "create_node", "node": {"node_id": "artifact-1", "kind": "artifact"}},
            {"op": "retire_node", "node_id": "worker-1"},
        ]
    )

    result = _validate(
        patch,
        projection=_projection(node_states={"worker-1": "leased"}),
    )

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "cannot retire active node" in result.rejection_reason
