"""Pure queries over graph projection storage."""

from orchestrator.graph.models import ResourceClaimProjection
from orchestrator.graph.projections import GraphProjection


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    return tuple(projection["node_resource_claims"].get(node_id, ()))
