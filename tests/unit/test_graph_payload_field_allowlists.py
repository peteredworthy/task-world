"""Behavioral contracts for typed graph-event payload retention."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from orchestrator.graph import (
    EVENT_PAYLOAD_MODELS,
    EVENT_PAYLOAD_SPECS,
    EventPayloadSpec,
    GRAPH_PROJECTION_PAYLOAD_FIELDS,
    LIGHT_GRAPH_PAYLOAD_FIELDS,
    NODE_DETAIL_PAYLOAD_FIELDS,
    SUMMARY_REBUILD_PAYLOAD_FIELDS,
    generated_payload_fields,
    payload_model_fields,
    validate_event_payload_specs,
)


class _CoincidentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str


def test_all_payload_allowlists_are_generated_exactly() -> None:
    assert GRAPH_PROJECTION_PAYLOAD_FIELDS == generated_payload_fields("projection")
    assert LIGHT_GRAPH_PAYLOAD_FIELDS == generated_payload_fields("light")
    assert SUMMARY_REBUILD_PAYLOAD_FIELDS == generated_payload_fields("summary")
    assert NODE_DETAIL_PAYLOAD_FIELDS == generated_payload_fields("node_detail")


def test_generated_fields_are_sorted_unique_and_strict() -> None:
    for mode in ("projection", "light", "summary", "node_detail"):
        fields = generated_payload_fields(mode)
        assert fields == tuple(sorted(set(fields)))
        assert "extra" not in fields


def test_every_canonical_payload_model_has_an_immutable_spec() -> None:
    assert EVENT_PAYLOAD_SPECS.keys() == EVENT_PAYLOAD_MODELS.keys()
    for event_type, model in EVENT_PAYLOAD_MODELS.items():
        assert EVENT_PAYLOAD_SPECS[event_type].model is model

    mutable_view: Any = EVENT_PAYLOAD_SPECS
    with pytest.raises(TypeError):
        mutable_view["new_event"] = EVENT_PAYLOAD_SPECS["node_created"]


def test_new_payload_model_cannot_inherit_retention_by_field_name() -> None:
    with pytest.raises(ValueError, match="missing payload specs: coincident_event"):
        validate_event_payload_specs(
            {**EVENT_PAYLOAD_MODELS, "coincident_event": _CoincidentPayload},
            EVENT_PAYLOAD_SPECS,
        )


def test_stale_retention_field_and_exception_are_rejected() -> None:
    with pytest.raises(ValueError, match="not serialized: stale_field"):
        EventPayloadSpec(
            model=_CoincidentPayload,
            projection=frozenset({"stale_field"}),
        )
    with pytest.raises(ValueError, match="unknown envelope fields: stale_field"):
        EventPayloadSpec(
            model=_CoincidentPayload,
            envelope_fields=frozenset({"stale_field"}),
        )


def test_retained_fields_are_declared_by_payload_models_or_envelope() -> None:
    for spec in EVENT_PAYLOAD_SPECS.values():
        serialized_fields = payload_model_fields(spec.model)
        for mode in ("projection", "light", "summary", "node_detail"):
            undeclared = getattr(spec, mode) - serialized_fields - spec.envelope_fields
            assert not undeclared, (spec.model.__name__, mode, undeclared)


def test_node_created_retains_typed_retry_limit_for_all_projection_reads() -> None:
    spec = EVENT_PAYLOAD_SPECS["node_created"]

    assert "max_attempts" in spec.projection
    assert "max_attempts" in spec.light
    assert "max_attempts" in spec.summary
    assert "max_attempts" in spec.node_detail
