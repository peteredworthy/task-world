"""Unit tests for pure graph patch validation."""

from datetime import UTC, datetime
from typing import Any

import pytest

from orchestrator.graph import ResourceClaimProjection
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    PatchEnvelope,
    PatchOp,
)
from orchestrator.graph import (
    PatchValidationResult,
    resource_claim_dicts,
    validate_patch,
)
from orchestrator.graph import GraphProjection, build_projection, initial_projection
from tests.unit.graph_test_utils import event


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
    node_ids = set(node_states or {}) | set(node_kinds or {}) | set(node_roles or {})
    node_ids.update(resource_claims or {})
    events = [
        event(
            "node_created",
            {
                "node_id": node_id,
                "kind": (node_kinds or {}).get(node_id, "worker"),
                "role": (node_roles or {}).get(node_id),
                "state": (node_states or {}).get(node_id, "planned"),
                "resource_claims": (resource_claims or {}).get(node_id, []),
            },
            position=index,
        )
        for index, node_id in enumerate(sorted(node_ids))
    ]
    events.extend(
        event("edge_created", edge, position=len(events) + index)
        for index, edge in enumerate((edges or {}).values())
    )
    return build_projection(events)


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


def test_required_pass_gated_final_check_from_recoverable_verifier_rejected() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-final",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "task_region_id": "final-region",
                        "command_definition": {"id": "hidden-oracle", "cmd": "true"},
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "planner-gap",
                        "kind": "planner",
                        "role": "gap_planner",
                        "state": "planned",
                        "task_region_id": "gap-region",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-pass-final",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-final",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-failed-gap",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "planner-gap",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "failed",
                    },
                },
            ]
        ),
        projection=_projection(
            node_states={"verifier-1": "planned"},
            node_kinds={"verifier-1": "verifier"},
            node_roles={"verifier-1": "verifier"},
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == (
        "required pass-gated final invariant edge from verifier verifier-1 "
        "is poisoned by a failure continuation"
    )


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
                    "accepted_record_selector": {
                        "record_type": "any_of",
                        "selectors": [
                            {"record_type": "verification_report", "schema": "VerificationReport"},
                            {"record_type": "check_result", "schema": "CheckResult"},
                        ],
                    },
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
                    "accepted_record_selector": {
                        "record_type": "any_of",
                        "selectors": [
                            {"record_type": "verification_report", "schema": "VerificationReport"},
                            {"record_type": "check_result", "schema": "CheckResult"},
                        ],
                    },
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
                    "accepted_record_selector": {
                        "record_type": "any_of",
                        "selectors": [
                            {"record_type": "verification_report", "schema": "VerificationReport"},
                            {"record_type": "check_result", "schema": "CheckResult"},
                        ],
                    },
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
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
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
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
                },
            ]
        ),
    )

    assert not result.accepted
    assert result.rejection_reason == "edge edge-1 references unknown target node: missing-target"


def test_create_edge_accepts_revision_attempt_embedded_worker_in_same_patch() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "candidate-1",
                    "worker_node": {
                        "node_id": "worker-revision-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-revision-candidate",
                    "from_node_id": "worker-revision-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "required": True,
                },
            ]
        ),
        projection=_projection(
            node_kinds={"verifier-1": "verifier"},
            node_roles={"verifier-1": "verifier"},
        ),
        actor_role="oversight",
    )

    assert result.accepted is True


def test_create_edge_accepts_revision_attempt_embedded_worker_with_default_kind() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "candidate-1",
                    "worker_node": {
                        "node_id": "worker-revision-1",
                        "role": "builder",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-revision-candidate",
                    "from_node_id": "worker-revision-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "required": True,
                },
            ]
        ),
        projection=_projection(
            node_kinds={"verifier-1": "verifier"},
            node_roles={"verifier-1": "verifier"},
        ),
        actor_role="oversight",
    )

    assert result.accepted is True


def test_create_edge_accepts_producer_class_source() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-class-final",
                    "from_node_id": "*",
                    "from_node_kind": "verifier",
                    "from_node_role": "verifier",
                    "from_port": "verification_report",
                    "to_node_id": "check-final",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                },
            ]
        ),
        projection=_projection(
            node_kinds={"check-final": "check"},
        ),
        actor_role="oversight",
    )

    assert result.accepted is True


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
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
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
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
                },
            ]
        ),
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "edge edge-1 references unknown target port check.not_a_real_input"
    )


def test_create_edge_rejects_binding_policy_incompatible_with_target_cardinality() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
                    },
                },
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
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "required": True,
                    "binding_policy": "bind_all",
                },
            ]
        ),
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "edge edge-1 binding_policy bind_all is incompatible with target cardinality one"
    )


def test_create_edge_accepts_known_prompt_hydration_policy() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
                    },
                },
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
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "required": True,
                    "prompt_hydration_policy": "structured_json",
                },
            ]
        ),
    )

    assert result.accepted


def test_create_edge_rejects_unknown_prompt_hydration_policy() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
                    },
                },
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
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "verifier-1",
                    "to_port": "candidate_under_test",
                    "required": True,
                    "prompt_hydration_policy": "dump_everything",
                },
            ]
        ),
    )

    assert not result.accepted
    assert (
        result.rejection_reason
        == "edge edge-1 has unknown prompt_hydration_policy: dump_everything"
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
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
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
                    "accepted_record_selector": {
                        "record_type": "candidate",
                        "schema": "ImplementationCandidate",
                    },
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


def test_gap_planner_no_op_allowed_when_classified_gap_successor_waits() -> None:
    projection = _projection(
        node_kinds={"planner-1": "planner", "worker-corrective": "worker"},
        edges={
            "edge-gap-to-corrective": {
                "edge_id": "edge-gap-to-corrective",
                "from_node_id": "planner-1",
                "from_port": "gap_classification",
                "to_node_id": "worker-corrective",
                "to_port": "classified_gap",
                "required": True,
                "dependency_type": "input_binding",
            }
        },
    )

    result = _validate(_patch([]), projection=projection, actor_role="gap_planner")

    assert result.accepted


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
                        "objective": "Produce a corrective candidate that resolves the classified gap.",
                        "access_mode": "write",
                        "acceptance": ["corrective candidate resolves the classified gap"],
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


def test_resource_claim_dicts_accepts_read_only_sequence() -> None:
    claim = ResourceClaimProjection(mode="read", scope="repo")

    assert resource_claim_dicts((claim,)) == [claim.model_dump()]


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


def test_set_resource_claims_unknown_mode_rejected() -> None:
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "delete", "scope": "repo"}],
            }
        ]
    )

    result = _validate(patch)

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "resource_claims mode must be one of" in result.rejection_reason


def test_set_resource_claims_absolute_path_in_scope_rejected() -> None:
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "/etc/passwd"}],
            }
        ]
    )

    result = _validate(patch)

    assert not result.accepted
    assert result.rejection_reason is not None
    assert 'scope="repo" with paths=[...]' in result.rejection_reason


def test_set_resource_claims_dotdot_escaping_path_in_scope_rejected() -> None:
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "../outside"}],
            }
        ]
    )

    result = _validate(patch)

    assert not result.accepted
    assert result.rejection_reason is not None
    assert 'scope="repo" with paths=[...]' in result.rejection_reason


def test_create_node_authority_non_string_paths_entry_rejected() -> None:
    # `node` is untyped (dict[str, Any]) on PatchOp, unlike the top-level
    # `set_resource_claims.resource_claims` field, which pydantic already type-checks
    # to list[str] before validate_patch ever runs. Malformed paths embedded in a
    # node's authority therefore need their own shape check here.
    patch = _patch(
        [
            {
                "op": "create_node",
                "node": {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "role": "builder",
                    "state": "planned",
                    "authority": {
                        "resource_claims": [{"mode": "write", "scope": "repo", "paths": [1, 2]}],
                    },
                },
            }
        ]
    )

    result = _validate(patch)

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "resource_claims paths must be a list of strings" in result.rejection_reason


def test_set_resource_claims_empty_string_path_entry_rejected() -> None:
    """`paths: [""]` is rejected; canonical whole-repo spellings pass."""
    rejected = _validate(
        _patch(
            [
                {
                    "op": "set_resource_claims",
                    "node_id": "worker-1",
                    "resource_claims": [{"mode": "write", "scope": "repo", "paths": [""]}],
                }
            ]
        )
    )

    assert not rejected.accepted
    assert rejected.rejection_reason is not None
    assert "must be repo-relative paths" in rejected.rejection_reason

    accepted = _validate(
        _patch(
            [
                {
                    "op": "set_resource_claims",
                    "node_id": "worker-1",
                    "resource_claims": [
                        {"mode": "write", "scope": "repo", "paths": ["."]},
                        {"mode": "write", "scope": "repo", "paths": []},
                        {"mode": "read", "scope": ""},
                    ],
                }
            ]
        )
    )

    assert accepted.accepted


def test_set_resource_claims_path_in_scope_is_accepted_not_rejected() -> None:
    """The incident shape is accepted here; normalization (Part A) fixes it up later.

    Validation only rejects shapes normalization cannot make sense of. A repo-relative
    path stuffed into `scope` is exactly the shape `_claim_from_dict` normalizes at
    event-application time, so it must be accepted at patch-validation time.
    """
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "src/orchestrator/graph"}],
            }
        ]
    )

    result = _validate(patch)

    assert result.accepted


def test_set_resource_claims_external_and_graph_write_scope_untouched() -> None:
    """external/graph_write claims don't use scope as a path and must not be rejected."""
    patch = _patch(
        [
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [
                    {"mode": "external", "scope": "external", "external_resource_key": "k"},
                    {"mode": "graph_write", "scope": "graph"},
                ],
            }
        ]
    )

    result = _validate(patch)

    assert result.accepted


def test_create_node_authority_resource_claims_shape_validated() -> None:
    patch = _patch(
        [
            {
                "op": "create_node",
                "node": {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "role": "builder",
                    "state": "planned",
                    "authority": {
                        "resource_claims": [{"mode": "bogus", "scope": "repo"}],
                    },
                },
            }
        ]
    )

    result = _validate(patch)

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "resource_claims mode must be one of" in result.rejection_reason


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
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
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


def test_create_edge_accepts_revision_attempt_embedded_nodes_in_same_patch() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "candidate-1",
                    "worker_node": {
                        "node_id": "worker-revision-2",
                        "kind": "worker",
                        "role": "builder",
                    },
                    "verifier_node": {
                        "node_id": "verifier-revision-2",
                        "kind": "verifier",
                        "role": "verifier",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-revision-candidate",
                    "from_node_id": "worker-revision-2",
                    "from_port": "candidate",
                    "to_node_id": "verifier-revision-2",
                    "to_port": "candidate_under_test",
                    "accepted_record_selector": {
                        "record_type": "candidate",
                        "schema": "ImplementationCandidate",
                    },
                },
            ]
        )
    )

    assert result.accepted


def test_create_node_rejects_worker_without_objective() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                    },
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == "worker node requires objective: worker-1"


def test_create_node_rejects_worker_without_access_mode() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                    },
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == "worker node requires access_mode: worker-1"


def test_create_node_rejects_worker_with_invalid_access_mode() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "implementation",
                    },
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == "worker node access_mode must be read_only or write: worker-1"


def test_create_node_rejects_worker_without_acceptance() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                    },
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == "worker node requires acceptance: worker-1"


def test_create_node_rejects_worker_with_malformed_acceptance() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": "run the tests",
                    },
                }
            ]
        )
    )

    assert result.accepted is False
    assert (
        result.rejection_reason
        == "worker node acceptance must be a list of non-empty strings: worker-1"
    )


def test_create_node_accepts_worker_with_full_contract() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
                    },
                }
            ]
        )
    )

    assert result.accepted is True


@pytest.mark.parametrize(
    ("kind", "role", "extra"),
    [
        ("verifier", "verifier", {}),
        ("check", "check", {"command_binding": "dynamic_feature_hidden_oracle"}),
        ("planner", "planner", {}),
    ],
)
def test_worker_contract_is_not_required_of_non_worker_kinds(
    kind: str, role: str, extra: dict[str, Any]
) -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "node-1",
                        "kind": kind,
                        "role": role,
                        "state": "planned",
                        **extra,
                    },
                }
            ]
        )
    )

    assert result.accepted is True


def test_gap_planner_corrective_worker_requires_worker_contract() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-corrective",
                        "kind": "worker",
                        "role": "fixer",
                        "state": "planned",
                        "task_region_id": "corrective_work_region",
                    },
                }
            ]
        ),
        actor_role="gap_planner",
    )

    assert result.accepted is False
    assert result.rejection_reason == "worker node requires objective: worker-corrective"


def test_create_revision_attempt_worker_node_is_not_contract_checked() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "candidate-1",
                    "worker_node": {
                        "node_id": "worker-revision-3",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                    },
                },
            ]
        )
    )

    assert result.accepted is True


def _discovery_worker_node(**overrides: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "node_id": "worker-1",
        "kind": "worker",
        "role": "discovery",
        "state": "planned",
        "objective": "Implement a candidate that satisfies the bound requirements.",
        "access_mode": "write",
        "acceptance": ["candidate satisfies the bound requirements"],
    }
    node.update(overrides)
    return node


def test_create_node_rejects_discovery_worker_declaring_write_access_mode() -> None:
    result = _validate(_patch([{"op": "create_node", "node": _discovery_worker_node()}]))

    assert result.accepted is False
    assert result.rejection_reason == (
        "discovery worker cannot declare access_mode write; supply "
        "access_mode_override_justification: worker-1"
    )


def test_create_node_accepts_discovery_worker_write_access_mode_with_override() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": _discovery_worker_node(
                        access_mode_override_justification=(
                            "Requires write access to reproduce the failure in place."
                        )
                    ),
                }
            ]
        )
    )

    assert result.accepted is True


def test_create_node_rejects_blank_access_mode_override_justification() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": _discovery_worker_node(access_mode_override_justification="   "),
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == (
        "access_mode_override_justification must be a non-empty string: worker-1"
    )


@pytest.mark.parametrize(
    ("role", "access_mode"),
    [("discovery", "read_only"), ("builder", "write")],
)
def test_create_node_rejects_unnecessary_access_mode_override_justification(
    role: str, access_mode: str
) -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": _discovery_worker_node(
                        role=role,
                        access_mode=access_mode,
                        access_mode_override_justification="Not needed here.",
                    ),
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == (
        "access_mode_override_justification is only valid for a discovery worker "
        "declaring access_mode write: worker-1"
    )


@pytest.mark.parametrize("mode", ["write", "graph_write", "review_write"])
def test_create_node_rejects_read_only_worker_with_escalated_resource_claim(mode: str) -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": _discovery_worker_node(
                        role="builder",
                        access_mode="read_only",
                        authority={
                            "resource_claims": [{"mode": mode, "scope": "repo", "paths": ["."]}]
                        },
                    ),
                }
            ]
        )
    )

    assert result.accepted is False
    assert result.rejection_reason == f"read_only worker cannot claim {mode} authority: worker-1"


def test_create_node_accepts_read_only_worker_with_read_resource_claim() -> None:
    for claim in (
        {"mode": "read", "scope": "repo", "paths": ["."]},
        {"mode": "external", "scope": "repo", "paths": ["."]},
    ):
        result = _validate(
            _patch(
                [
                    {
                        "op": "create_node",
                        "node": _discovery_worker_node(
                            role="builder",
                            access_mode="read_only",
                            authority={"resource_claims": [claim]},
                        ),
                    }
                ]
            )
        )

        assert result.accepted is True


@pytest.mark.parametrize("role", ["builder", "implementer", "fixer", "reviewer", "summarizer"])
def test_non_discovery_worker_roles_may_declare_write_access_mode(role: str) -> None:
    # The "fixer" role separately requires a classified_gap input edge
    # (`_is_corrective_worker`), unrelated to access_mode; satisfy it with a
    # pre-existing gap-source node (so creating that node doesn't itself
    # trigger the unrelated "gap planner requires verification input edge"
    # check) so this test isolates the access_mode/role predicate under test.
    if role == "fixer":
        projection = _projection(
            node_kinds={"gap-source": "planner"}, node_roles={"gap-source": "gap_planner"}
        )
        extra_ops = [
            {
                "op": "create_edge",
                "edge_id": "edge-classified-gap",
                "from_node_id": "gap-source",
                "from_port": "classified_gap",
                "to_node_id": "worker-1",
                "to_port": "classified_gap",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "gap_classification",
                    "schema": "GapClassification",
                    "classification": "corrective_work_required",
                },
            },
        ]
    else:
        projection = initial_projection()
        extra_ops = []
    result = _validate(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": _discovery_worker_node(role=role, access_mode="write"),
                },
                *extra_ops,
            ]
        ),
        projection=projection,
    )

    assert result.accepted is True


def test_create_revision_attempt_discovery_worker_is_not_access_mode_gated() -> None:
    result = _validate(
        _patch(
            [
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "candidate-1",
                    "worker_node": _discovery_worker_node(node_id="worker-revision-3"),
                },
            ]
        )
    )

    assert result.accepted is True
