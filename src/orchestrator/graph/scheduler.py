"""Pure readiness and scheduling helpers for execution graph nodes."""

from collections.abc import Sequence
from dataclasses import dataclass, field


def _empty_paths() -> list[str]:
    return []


@dataclass(frozen=True)
class ResourceClaim:
    mode: str
    scope: str
    paths: list[str] = field(default_factory=_empty_paths)
    snapshot_id: str | None = None
    external_resource_key: str | None = None
    exclusive: bool = False


def _empty_resource_claims() -> list[ResourceClaim]:
    return []


@dataclass(frozen=True)
class NodeScheduleInfo:
    node_id: str
    kind: str
    state: str
    priority: int = 0
    region_order: int = 0
    creation_position: int = 0
    resource_claims: list[ResourceClaim] = field(default_factory=_empty_resource_claims)


@dataclass(frozen=True)
class SchedulingDecision:
    projection_position: int
    candidates: list[str]
    selected: list[str]
    deferred: list[str]
    deferred_reasons: dict[str, str]


def claims_conflict(existing: ResourceClaim, requested: ResourceClaim) -> bool:
    if existing.mode == "external" and requested.mode == "external":
        return _external_claims_conflict(existing, requested)
    if existing.mode == "external" or requested.mode == "external":
        return False

    if existing.mode == "graph_write" and requested.mode == "graph_write":
        return True
    if existing.mode == "graph_write" or requested.mode == "graph_write":
        return False

    if existing.mode == "review_write" or requested.mode == "review_write":
        return existing.mode in {"read", "write", "review_write"} or requested.mode in {
            "read",
            "write",
            "review_write",
        }

    if existing.mode == "write" and requested.mode == "write":
        return True
    if existing.scope == "repo" and requested.scope == "repo":
        if existing.mode == "read" and requested.mode == "write":
            return _paths_overlap(existing.paths, requested.paths)
        if existing.mode == "write" and requested.mode == "read":
            return _paths_overlap(existing.paths, requested.paths)
    if existing.mode == "read" and requested.mode == "read":
        return False

    return False


def evaluate_readiness(
    node: NodeScheduleInfo,
    run_lifecycle_state: str,
    active_lease_node_ids: Sequence[str],
    claimed_resources: Sequence[ResourceClaim],
) -> tuple[bool, str]:
    if run_lifecycle_state != "active":
        return False, "run_not_active"
    if node.state not in {"planned", "blocked"}:
        return False, f"node_state_not_eligible:{node.state}"
    if node.node_id in active_lease_node_ids:
        return False, "node_already_leased"
    for existing in claimed_resources:
        for requested in node.resource_claims:
            if claims_conflict(existing, requested):
                return False, "resource_conflict"
    return True, ""


def schedule(
    nodes: Sequence[NodeScheduleInfo],
    run_lifecycle_state: str,
    active_leases: Sequence[ResourceClaim],
    projection_position: int,
    max_grants: int = 10,
) -> SchedulingDecision:
    if run_lifecycle_state != "active":
        return SchedulingDecision(
            projection_position=projection_position,
            candidates=[],
            selected=[],
            deferred=[],
            deferred_reasons={},
        )

    candidates = sorted(
        (node for node in nodes if node.state == "ready"),
        key=lambda node: (
            -node.priority,
            node.region_order,
            node.creation_position,
            node.node_id,
        ),
    )
    selected: list[str] = []
    selected_claims = list(active_leases)
    deferred: list[str] = []
    deferred_reasons: dict[str, str] = {}

    for node in candidates:
        if len(selected) >= max_grants:
            deferred.append(node.node_id)
            deferred_reasons[node.node_id] = "max_grants_reached"
            continue

        reason = _first_conflict_reason(selected_claims, node.resource_claims)
        if reason:
            deferred.append(node.node_id)
            deferred_reasons[node.node_id] = reason
            continue

        selected.append(node.node_id)
        selected_claims.extend(node.resource_claims)

    return SchedulingDecision(
        projection_position=projection_position,
        candidates=[node.node_id for node in candidates],
        selected=selected,
        deferred=deferred,
        deferred_reasons=deferred_reasons,
    )


def _paths_overlap(existing_paths: list[str], requested_paths: list[str]) -> bool:
    return (
        not existing_paths
        or not requested_paths
        or bool(set(existing_paths).intersection(requested_paths))
    )


def _external_claims_conflict(existing: ResourceClaim, requested: ResourceClaim) -> bool:
    if existing.external_resource_key != requested.external_resource_key:
        return False
    if existing.external_resource_key is None:
        return False
    return (
        existing.exclusive
        or requested.exclusive
        or _claim_writes(existing)
        or _claim_writes(requested)
    )


def _claim_writes(claim: ResourceClaim) -> bool:
    return claim.mode in {"write", "graph_write", "review_write"}


def _first_conflict_reason(
    existing_claims: Sequence[ResourceClaim],
    requested_claims: Sequence[ResourceClaim],
) -> str:
    for existing in existing_claims:
        for requested in requested_claims:
            if claims_conflict(existing, requested):
                return f"resource_conflict:{existing.mode}:{requested.mode}"
    return ""
