"""Pure queries over graph projection storage."""

from orchestrator.graph.models import ResourceClaimProjection
from orchestrator.graph.projections import GraphProjection


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    return tuple(projection["node_resource_claims"].get(node_id, ()))


def run_state(projection: GraphProjection) -> str | None:
    """Return the current lifecycle state, or ``None`` before its first event."""
    return projection["run_state"]


def completion_decision_passed(projection: GraphProjection) -> bool:
    """Return whether the latest lifecycle completion decision passed."""
    return projection["completion_decision_passed"]
