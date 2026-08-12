"""Focused cache-safety invariants for the immutable projection."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    ProjectionCheckpointIntegrityError,
    ProjectionReplayConflictError,
    edges_view,
    initial_projection,
    map_set,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    validate_projection_critical_invariants,
)
from tests.unit.test_graph_projection_codec import final_projection_fixture


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def test_critical_invariants_accept_a_valid_projection() -> None:
    validate_projection_critical_invariants(final_projection_fixture())


def test_critical_invariants_reject_a_map_identity_mismatch() -> None:
    projection = final_projection_fixture()
    node_id, node = next(iter(projection.nodes.items()))
    malformed = projection.model_copy(
        update={
            "nodes": map_set(
                projection.nodes,
                node_id,
                node.model_copy(update={"spec": node.spec.model_copy(update={"node_id": "wrong"})}),
            )
        }
    )

    with pytest.raises(ProjectionCheckpointIntegrityError, match="map key"):
        validate_projection_critical_invariants(malformed)


def test_disposable_checkpoint_rebuild_input_is_not_salvaged_after_corruption() -> None:
    checkpoint = projection_to_checkpoint(final_projection_fixture(), position=7)
    corrupted = deepcopy(checkpoint)
    corrupted["state"] = []

    with pytest.raises(ValueError):
        projection_from_checkpoint(corrupted)


def test_empty_projection_has_the_critical_index_shape() -> None:
    validate_projection_critical_invariants(initial_projection())


def test_strict_authoritative_replay_accepts_wildcard_producer_class_edge() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "node_created",
            {"node_id": "check-final", "kind": "check", "state": "planned"},
            position=0,
        ),
        enforce_relationships=True,
    )

    projection = reduce_event(
        projection,
        _event(
            "edge_created",
            {
                "edge_id": "edge-verifier-class-final",
                "from_node_id": "*",
                "from_node_kind": "verifier",
                "from_node_role": "verifier",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
            },
            position=1,
        ),
        enforce_relationships=True,
    )

    edge = edges_view(projection)["edge-verifier-class-final"]
    assert edge.from_node_id == "*"
    assert edge.from_node_kind == "verifier"
    assert edge.from_node_role == "verifier"


@pytest.mark.parametrize(
    ("from_node_id", "to_node_id", "missing_relation"),
    [
        ("missing-source", "known-node", "edge source node"),
        ("known-node", "missing-target", "edge target node"),
    ],
)
def test_strict_authoritative_replay_still_rejects_dangling_literal_edge_nodes(
    from_node_id: str,
    to_node_id: str,
    missing_relation: str,
) -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "node_created",
            {"node_id": "known-node", "kind": "worker", "state": "planned"},
            position=0,
        ),
        enforce_relationships=True,
    )

    with pytest.raises(ProjectionReplayConflictError, match=missing_relation):
        reduce_event(
            projection,
            _event(
                "edge_created",
                {
                    "edge_id": "edge-dangling",
                    "from_node_id": from_node_id,
                    "from_port": "candidate",
                    "to_node_id": to_node_id,
                    "to_port": "input",
                },
                position=1,
            ),
            enforce_relationships=True,
        )
