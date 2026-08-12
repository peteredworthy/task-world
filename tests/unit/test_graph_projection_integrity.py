"""Focused cache-safety invariants for the immutable projection."""

from copy import deepcopy

import pytest

from orchestrator.graph import (
    ProjectionCheckpointIntegrityError,
    initial_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
    validate_projection_critical_invariants,
    map_set,
)
from tests.unit.test_graph_projection_codec import final_projection_fixture


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
