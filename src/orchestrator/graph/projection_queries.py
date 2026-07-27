"""Pure queries over graph projection storage.

Each query owns the physical projection access and returns values that cannot
mutate projection containers.
"""

from copy import deepcopy
from collections.abc import Mapping

from orchestrator.graph.models import (
    CandidateProjection,
    EdgeProjection,
    InputBindingProjection,
    LeaseProjection,
    ResourceClaimProjection,
)
from orchestrator.graph.projections import GraphProjection


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    return tuple(
        claim.model_copy(deep=True) for claim in projection["node_resource_claims"].get(node_id, ())
    )


def node_exists(projection: GraphProjection, node_id: str) -> bool:
    """Return whether a node has been created."""
    return node_id in projection["node_kinds"]


def node_kind(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's declared kind, if it exists."""
    return projection["node_kinds"].get(node_id)


def node_role(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's declared role, if supplied."""
    return projection["node_roles"].get(node_id)


def node_creation_position(projection: GraphProjection, node_id: str) -> int | None:
    """Return a node's creation position, if it exists."""
    return projection["node_creation_positions"].get(node_id)


def node_task_region(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's task-region identifier, if supplied."""
    return projection["node_task_regions"].get(node_id)


def node_state(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's current runtime state, if it exists."""
    return projection["node_states"].get(node_id)


def node_attempt(projection: GraphProjection, node_id: str) -> int | None:
    """Return a node's current attempt number, if supplied."""
    return projection["node_attempts"].get(node_id)


def node_candidate_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's current candidate identifier, if supplied."""
    return projection["node_candidates"].get(node_id)


def node_failed_candidate_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's failed candidate identifier, if supplied."""
    return projection["node_failed_candidates"].get(node_id)


def node_allowed_actions(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return a node's allowed actions in declaration order."""
    return tuple(projection["node_allowed_actions"].get(node_id, ()))


def node_preconditions(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return a node's preconditions in declaration order."""
    return tuple(projection["node_preconditions"].get(node_id, ()))


def node_command_definition(
    projection: GraphProjection, node_id: str
) -> Mapping[str, object] | None:
    """Return an independent command-definition copy, if supplied."""
    definition = projection["node_command_definitions"].get(node_id)
    return deepcopy(definition) if definition is not None else None


def node_last_deferred_reason(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's last scheduling deferral reason, if any."""
    return projection["last_deferred_reasons"].get(node_id)


def node_retry_not_before(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's retry deadline, if one has been scheduled."""
    return projection["retry_not_before_by_node"].get(node_id)


def task_state(projection: GraphProjection, task_region_id: str) -> str | None:
    """Return a task region's current state, if it exists."""
    return projection["task_states"].get(task_region_id)


def task_candidates(
    projection: GraphProjection, task_region_id: str
) -> tuple[CandidateProjection, ...]:
    """Return independent candidate copies in projection order."""
    return tuple(
        candidate.model_copy(deep=True)
        for candidate in projection["task_candidates"].get(task_region_id, ())
    )


def edge_by_id(projection: GraphProjection, edge_id: str) -> EdgeProjection | None:
    """Return an independent edge copy, if it exists."""
    edge = projection["edges"].get(edge_id)
    return edge.model_copy(deep=True) if edge is not None else None


def iter_edges(projection: GraphProjection) -> tuple[EdgeProjection, ...]:
    """Return independent edge copies in projection insertion order."""
    return tuple(edge.model_copy(deep=True) for edge in projection["edges"].values())


def edges_from_node(projection: GraphProjection, node_id: str) -> tuple[EdgeProjection, ...]:
    """Return outgoing edges in projection insertion order."""
    return tuple(
        edge.model_copy(deep=True)
        for edge in projection["edges"].values()
        if edge.from_node_id == node_id
    )


def edges_to_node(projection: GraphProjection, node_id: str) -> tuple[EdgeProjection, ...]:
    """Return incoming edges in projection insertion order."""
    return tuple(
        edge.model_copy(deep=True)
        for edge in projection["edges"].values()
        if edge.to_node_id == node_id
    )


def input_binding_for_port(
    projection: GraphProjection, node_id: str, port: str
) -> InputBindingProjection | None:
    """Return an independent input-binding copy for a node port, if present."""
    binding = projection["input_bindings"].get(node_id, {}).get(port)
    return binding.model_copy(deep=True) if binding is not None else None


def input_bindings_for_node(
    projection: GraphProjection, node_id: str
) -> tuple[InputBindingProjection, ...]:
    """Return independent node input-binding copies in port insertion order."""
    return tuple(
        binding.model_copy(deep=True)
        for binding in projection["input_bindings"].get(node_id, {}).values()
    )


def bound_record_ids(projection: GraphProjection, node_id: str, port: str) -> tuple[str, ...]:
    """Return record identifiers bound to a node input port in binding order."""
    binding = projection["input_bindings"].get(node_id, {}).get(port)
    return tuple(binding.record_ids) if binding is not None else ()


def lease_by_id(projection: GraphProjection, lease_id: str) -> LeaseProjection | None:
    """Return an independent lease copy, if it exists."""
    lease = projection["leases"].get(lease_id)
    return lease.model_copy(deep=True) if lease is not None else None


def iter_leases(projection: GraphProjection) -> tuple[LeaseProjection, ...]:
    """Return independent lease copies in projection insertion order."""
    return tuple(lease.model_copy(deep=True) for lease in projection["leases"].values())


def active_leases(projection: GraphProjection) -> tuple[LeaseProjection, ...]:
    """Return active leases in projection insertion order."""
    return tuple(
        lease.model_copy(deep=True)
        for lease in projection["leases"].values()
        if lease.state == "active"
    )


def lease_generation(projection: GraphProjection, lease_id: str) -> int | None:
    """Return a lease generation, if the lease exists and has one."""
    lease = projection["leases"].get(lease_id)
    return lease.generation if lease is not None else None


def run_state(projection: GraphProjection) -> str | None:
    """Return the current lifecycle state, or ``None`` before its first event."""
    return projection["run_state"]


def completion_decision_passed(projection: GraphProjection) -> bool:
    """Return whether the latest lifecycle completion decision passed."""
    return projection["completion_decision_passed"]
