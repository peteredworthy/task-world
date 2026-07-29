"""Observable contracts for the isolated immutable projection scaffold."""

import pytest
from pydantic import ValidationError

from orchestrator.graph import FrozenMap, ImmutableGraphProjection


def test_graph_projection_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ImmutableGraphProjection.model_validate({"unknown": True})


def test_empty_projection_uses_persistent_defaults() -> None:
    projection = ImmutableGraphProjection()

    assert isinstance(projection.nodes.by_id, FrozenMap)
    assert projection.scheduling.ready_node_ids == ()


def test_projection_groups_are_frozen() -> None:
    projection = ImmutableGraphProjection()

    with pytest.raises(ValidationError, match="frozen_instance"):
        projection.scheduling.ready_node_ids = ("node-1",)
