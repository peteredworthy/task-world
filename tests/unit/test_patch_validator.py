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
    resource_claims: dict[str, list[dict[str, Any]]] | None = None,
) -> GraphProjection:
    projection = initial_projection()
    if node_states is not None:
        projection["node_states"] = node_states
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


def test_create_worker_without_role_rejected() -> None:
    result = _validate(
        _patch([{"op": "create_node", "node": {"node_id": "worker-1", "kind": "worker"}}])
    )

    assert not result.accepted
    assert result.rejection_reason is not None
    assert "requires role" in result.rejection_reason


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
