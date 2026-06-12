"""Pure readiness and scheduling helpers for execution graph nodes."""

from collections.abc import Sequence
from dataclasses import dataclass, field
import fnmatch
import posixpath


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


def _empty_edges() -> list["InputEdgeInfo"]:
    return []


def _empty_ports() -> set[str]:
    return set()


def _empty_state_map() -> dict[str, str]:
    return {}


def _empty_bool_map() -> dict[str, bool]:
    return {}


def _empty_preconditions() -> list[str]:
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
    required_edges: list["InputEdgeInfo"] = field(default_factory=_empty_edges)
    satisfied_input_ports: set[str] = field(default_factory=_empty_ports)
    upstream_states: dict[str, str] = field(default_factory=_empty_state_map)
    upstream_kinds: dict[str, str] = field(default_factory=_empty_state_map)
    upstream_pending_appeals: set[str] = field(default_factory=_empty_ports)
    gate_decisions: dict[str, bool] = field(default_factory=_empty_bool_map)
    failed_candidate_id: str | None = None
    preconditions: list[str] = field(default_factory=_empty_preconditions)
    command_definition_present: bool = False


@dataclass(frozen=True)
class InputEdgeInfo:
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool = True


@dataclass(frozen=True)
class SchedulingDecision:
    projection_position: int
    candidates: list[str]
    selected: list[str]
    deferred: list[str]
    deferred_reasons: dict[str, str]


def claims_conflict(existing: ResourceClaim, requested: ResourceClaim) -> bool:
    if _external_claim_missing_key(existing) or _external_claim_missing_key(requested):
        return True
    if existing.mode == "external" and requested.mode == "external":
        return _external_claims_conflict(existing, requested)
    if existing.mode == "external" or requested.mode == "external":
        return existing.exclusive or requested.exclusive

    if existing.mode == "graph_write" and requested.mode == "graph_write":
        return True
    if existing.mode == "graph_write" or requested.mode == "graph_write":
        # Graph patch application is controller-serialized in v1; it is not a runner lease.
        return False

    if existing.mode == "review_write" or requested.mode == "review_write":
        return _review_claims_conflict(existing, requested)

    if existing.mode == "write" and requested.mode == "write":
        return True
    if existing.scope == "repo" and requested.scope == "repo":
        if existing.mode == "read" and requested.mode == "write":
            return existing.snapshot_id is None and _paths_overlap(existing.paths, requested.paths)
        if existing.mode == "write" and requested.mode == "read":
            return requested.snapshot_id is None and _paths_overlap(existing.paths, requested.paths)
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
    for edge in node.required_edges:
        if not edge.required:
            continue
        if edge.to_port not in node.satisfied_input_ports:
            return False, f"missing_required_input:{edge.to_port}"
    for edge in node.required_edges:
        if not edge.required:
            continue
        upstream_node_id = edge.from_node_id
        upstream_state = node.upstream_states.get(upstream_node_id)
        pending_appeal = upstream_node_id in node.upstream_pending_appeals
        if _upstream_failure_allowed(node, edge):
            continue
        if upstream_state in {"failed", "cancelled"} or pending_appeal:
            return False, f"upstream_failed:{upstream_node_id}"
    for edge in node.required_edges:
        if not edge.required:
            continue
        upstream_node_id = edge.from_node_id
        if node.upstream_states.get(upstream_node_id) is None:
            continue
        if node.upstream_kinds.get(upstream_node_id) == "gate":
            if node.gate_decisions.get(upstream_node_id) is not True:
                return False, f"gate_not_approved:{upstream_node_id}"
    invalid_claim = _invalid_claim_reason(node.resource_claims)
    if invalid_claim:
        return False, invalid_claim
    for precondition in node.preconditions:
        if not _precondition_satisfied(node, precondition):
            return False, f"precondition_failed:{precondition}"
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
        (node for node in nodes if node.state == "ready" and node.kind != "gate"),
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
    existing = [_normalize_claim_path(path) for path in existing_paths]
    requested = [_normalize_claim_path(path) for path in requested_paths]
    if not existing or not requested:
        return True
    if any(path.invalid for path in existing) or any(path.invalid for path in requested):
        return True
    return any(
        _normalized_paths_overlap(existing_path, requested_path)
        for existing_path in existing
        for requested_path in requested
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


def _external_claim_missing_key(claim: ResourceClaim) -> bool:
    return claim.mode == "external" and claim.external_resource_key is None


def _invalid_claim_reason(claims: Sequence[ResourceClaim]) -> str:
    for claim in claims:
        if _external_claim_missing_key(claim):
            return "invalid_claim:external_missing_key"
    return ""


def _precondition_satisfied(node: NodeScheduleInfo, precondition: str) -> bool:
    if precondition == "has_command_definition":
        return node.command_definition_present
    return False


def _claim_writes(claim: ResourceClaim) -> bool:
    return claim.mode in {"write", "graph_write", "review_write"}


@dataclass(frozen=True)
class _NormalizedPath:
    raw: str
    pattern: str
    invalid: bool
    whole_repo: bool
    has_glob: bool


def _normalize_claim_path(path: str) -> _NormalizedPath:
    if path in {"", "."}:
        return _NormalizedPath(raw=path, pattern="", invalid=False, whole_repo=True, has_glob=False)
    if path.startswith("/"):
        return _NormalizedPath(
            raw=path, pattern=path, invalid=True, whole_repo=False, has_glob=False
        )

    normalized = posixpath.normpath(path)
    if normalized == ".":
        return _NormalizedPath(raw=path, pattern="", invalid=False, whole_repo=True, has_glob=False)
    invalid = normalized == ".." or normalized.startswith("../")
    has_glob = any(char in normalized for char in "*?[")
    return _NormalizedPath(
        raw=path,
        pattern=normalized,
        invalid=invalid,
        whole_repo=False,
        has_glob=has_glob,
    )


def _normalized_paths_overlap(existing: _NormalizedPath, requested: _NormalizedPath) -> bool:
    if existing.whole_repo or requested.whole_repo:
        return True
    if existing.has_glob and requested.has_glob:
        return _glob_prefixes_may_overlap(existing.pattern, requested.pattern)
    if existing.has_glob:
        return _glob_overlaps_literal(existing.pattern, requested.pattern)
    if requested.has_glob:
        return _glob_overlaps_literal(requested.pattern, existing.pattern)
    return _literal_paths_overlap(existing.pattern, requested.pattern)


def _glob_overlaps_literal(pattern: str, literal: str) -> bool:
    return fnmatch.fnmatchcase(literal, pattern) or _literal_prefix_may_match_glob(literal, pattern)


def _literal_prefix_may_match_glob(literal: str, pattern: str) -> bool:
    return any(
        fnmatch.fnmatchcase(f"{literal}/{probe}", pattern) for probe in ("x", "x.py", "nested/x.py")
    )


def _glob_prefixes_may_overlap(existing_pattern: str, requested_pattern: str) -> bool:
    existing_prefix = _static_prefix(existing_pattern)
    requested_prefix = _static_prefix(requested_pattern)
    if existing_prefix == "" or requested_prefix == "":
        return True
    return _literal_paths_overlap(existing_prefix, requested_prefix)


def _static_prefix(pattern: str) -> str:
    parts: list[str] = []
    for part in pattern.split("/"):
        if any(char in part for char in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def _literal_paths_overlap(existing: str, requested: str) -> bool:
    return (
        existing == requested
        or requested.startswith(f"{existing}/")
        or existing.startswith(f"{requested}/")
    )


def _review_claims_conflict(existing: ResourceClaim, requested: ResourceClaim) -> bool:
    if existing.mode == "graph_write" or requested.mode == "graph_write":
        return False
    if existing.mode == "review_write" and requested.mode == "review_write":
        return True
    if existing.mode == "write" or requested.mode == "write":
        return True
    if existing.mode == "read" and requested.mode == "review_write":
        return existing.snapshot_id is None and _paths_overlap(existing.paths, requested.paths)
    if existing.mode == "review_write" and requested.mode == "read":
        return requested.snapshot_id is None and _paths_overlap(existing.paths, requested.paths)
    return False


def _upstream_failure_allowed(node: NodeScheduleInfo, edge: InputEdgeInfo) -> bool:
    if node.kind in {"recovery", "oversight"}:
        return True
    return node.failed_candidate_id is not None or edge.to_port in {
        "failed_verification",
        "verification_failure",
        "failed_candidate",
    }


def _first_conflict_reason(
    existing_claims: Sequence[ResourceClaim],
    requested_claims: Sequence[ResourceClaim],
) -> str:
    for existing in existing_claims:
        for requested in requested_claims:
            if claims_conflict(existing, requested):
                return f"resource_conflict:{existing.mode}:{requested.mode}"
    return ""
