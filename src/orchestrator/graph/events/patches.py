"""Strict graph patch event specifications."""

from __future__ import annotations

from typing import Any

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


def reduce_graph_patch_accepted(
    state: Any,
    payload: GraphPatchAcceptedPayload,
    metadata: EventMetadata,
) -> Any:
    """Apply the current accepted-patch facts without entering history replay."""

    del metadata
    from orchestrator.graph.projections import copy_projection, refresh_derived_topology_state

    next_state = copy_projection(state)
    planner_node_id = payload.proposed_by_node_id
    patch_id = payload.patch_id
    next_state["open_proposal_blockers"].pop(patch_id, None)
    accepted = list(next_state["accepted_graph_patches_by_node"].get(planner_node_id, []))
    accepted.append(patch_id)
    next_state["accepted_graph_patches_by_node"][planner_node_id] = accepted
    successor_node_ids = payload.successor_planner_node_ids
    if successor_node_ids:
        next_state["accepted_no_successor_patches_by_node"][planner_node_id] = []
        next_state["accepted_no_successor_patch_ids_by_node"].pop(planner_node_id, None)
        next_state["planner_successors"][planner_node_id] = successor_node_ids[0]
    else:
        no_successor_patches = list(
            next_state["accepted_no_successor_patches_by_node"].get(planner_node_id, [])
        )
        no_successor_patches.append(patch_id)
        next_state["accepted_no_successor_patches_by_node"][planner_node_id] = no_successor_patches
        next_state["accepted_no_successor_patch_ids_by_node"][planner_node_id] = patch_id
    refresh_derived_topology_state(next_state)
    return next_state


def reduce_graph_patch_rejected(
    state: Any,
    payload: GraphPatchRejectedPayload,
    metadata: EventMetadata,
) -> Any:
    """Resolve a current rejected patch without entering history replay."""

    del metadata
    from orchestrator.graph.projections import copy_projection, refresh_derived_topology_state

    next_state = copy_projection(state)
    next_state["open_proposal_blockers"].pop(payload.patch_id, None)
    refresh_derived_topology_state(next_state)
    return next_state


GRAPH_PATCH_ACCEPTED = EventSpecification(
    "graph_patch_accepted",
    GraphPatchAcceptedPayload,
    reduce_graph_patch_accepted,
    ProjectionParticipation.MUTATES,
)
GRAPH_PATCH_REJECTED = EventSpecification(
    "graph_patch_rejected",
    GraphPatchRejectedPayload,
    reduce_graph_patch_rejected,
    ProjectionParticipation.MUTATES,
)
EVENT_SPECIFICATIONS = (GRAPH_PATCH_ACCEPTED, GRAPH_PATCH_REJECTED)
