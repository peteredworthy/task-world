"""Strict graph patch event specifications."""

from __future__ import annotations
from typing import Any
from orchestrator.graph.models import EventEnvelope
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


class GraphPatchAcceptedPayload(StrictPayload):
    patch_id: str
    base_graph_position: int
    actor_role: str
    proposed_by_node_id: str
    successor_planner_node_ids: list[str]
    session_id: str | None = None
    carryover_record_id: str | None = None
    diagnostics: dict[str, JsonValue] | None = None
    ops: list[JsonValue] | None = None


class GraphPatchRejectedPayload(StrictPayload):
    patch_id: str
    base_graph_position: int
    actor_role: str
    proposed_by_node_id: str
    reason: str
    read_set_diff: dict[str, JsonValue] | None = None
    diagnostics: dict[str, JsonValue] | None = None
    budget: int | None = None
    count: int | None = None


def _legacy_reduce(state: Any, payload: StrictPayload, metadata: EventMetadata) -> Any:
    from orchestrator.graph.projections import reduce_legacy_event

    return reduce_legacy_event(
        state,
        EventEnvelope(
            event_id=metadata.event_id,
            run_id=metadata.run_id,
            position=metadata.position,
            event_type=metadata.event_type,
            schema_version=metadata.payload_schema_generation,
            actor=metadata.actor,
            timestamp=metadata.timestamp,
            payload=payload.to_json(),
        ),
    )


GRAPH_PATCH_ACCEPTED = EventSpecification(
    "graph_patch_accepted",
    GraphPatchAcceptedPayload,
    _legacy_reduce,
    ProjectionParticipation.MUTATES,
)
GRAPH_PATCH_REJECTED = EventSpecification(
    "graph_patch_rejected",
    GraphPatchRejectedPayload,
    _legacy_reduce,
    ProjectionParticipation.MUTATES,
)
EVENT_SPECIFICATIONS = (GRAPH_PATCH_ACCEPTED, GRAPH_PATCH_REJECTED)
