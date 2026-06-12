"""Pure graph patch validation helpers."""

from dataclasses import dataclass, field
from typing import Any, cast

from orchestrator.graph.models import EventEnvelope, PatchEnvelope
from orchestrator.graph.projections import GraphProjection


@dataclass(frozen=True)
class PatchValidationResult:
    accepted: bool
    rejection_reason: str | None = None
    conflicting_events: list[EventEnvelope] = field(default_factory=lambda: [])
    read_set_diff: dict[str, Any] | None = None


INVALIDATING_NODE_STATES = {"retired", "cancelled"}
INVALIDATING_RUN_STATES = {"cancelling", "cancelled", "failed"}
INVALIDATING_EVENT_TYPES = {
    "requirement_amended",
    "authority_narrowed",
    "node_authority_changed",
    "candidate_superseded",
    "region_marked_suspect",
    "plan_region_marked_suspect",
    "graph_patch_accepted",
}
KNOWN_OPS = {
    "create_node",
    "create_edge",
    "retire_node",
    "create_revision_attempt",
    "create_appeal",
    "create_gate",
    "set_resource_claims",
    "set_allowed_actions",
    "mark_plan_region_suspect",
}
PLANNER_OPS = KNOWN_OPS - {"create_gate"}
ALLOWED_BY_ROLE = {
    "planner": PLANNER_OPS,
    "oversight": KNOWN_OPS,
    "human": KNOWN_OPS,
    "controller": KNOWN_OPS,
}
MODE_RANK = {"read": 0, "write": 1, "graph_write": 2, "review_write": 3}
RUNNING_STATES = {"running", "leased"}
EXECUTABLE_NODE_KINDS = {"worker", "verifier", "check", "planner"}
PLANNER_SUCCESSOR_PORTS = {
    "region_summary",
    "accepted_file_state",
    "outstanding_failures",
}


def classify_event(event: EventEnvelope) -> str:
    """Classify whether an event can invalidate a stale patch read-set."""
    if event.event_type == "node_state_changed":
        new_state = event.payload.get("new_state")
        if isinstance(new_state, str) and new_state in INVALIDATING_NODE_STATES:
            return "invalidating"
    if event.event_type == "run_lifecycle_changed":
        to_state = event.payload.get("to_state")
        if isinstance(to_state, str) and to_state in INVALIDATING_RUN_STATES:
            return "invalidating"
    if event.event_type in INVALIDATING_EVENT_TYPES:
        return "invalidating"
    return "neutral"


def op_read_set(op: dict[str, Any]) -> set[str]:
    """Return graph object ids that a patch operation semantically depends on."""
    op_name = op.get("op")
    if op_name == "create_node":
        return set()
    if op_name == "create_edge":
        return _string_values(op.get("from_node_id"), op.get("to_node_id"))
    if op_name == "retire_node":
        return _string_values(op.get("node_id"))
    if op_name == "create_revision_attempt":
        return _string_values(op.get("task_region_id"), op.get("failed_candidate_id"))
    if op_name == "create_appeal":
        return _string_values(op.get("appealed_node_id"))
    if op_name == "create_gate":
        return _string_values_from_iterable(op.get("predecessor_node_ids"))
    if op_name in {"set_resource_claims", "set_allowed_actions"}:
        return _string_values(op.get("node_id"))
    if op_name == "mark_plan_region_suspect":
        return _string_values_from_iterable(op.get("region_node_ids"))
    return set()


def validate_patch(
    patch: PatchEnvelope,
    current_position: int,
    events_since_base: list[EventEnvelope],
    projection: GraphProjection,
    actor_role: str,
) -> PatchValidationResult:
    ops = [_op_to_dict(op) for op in patch.ops]

    stale_result = _validate_staleness(patch, current_position, events_since_base, ops)
    if stale_result is not None:
        return stale_result

    allowed_ops = ALLOWED_BY_ROLE.get(actor_role, set())
    for op in ops:
        op_name = op.get("op")
        if not isinstance(op_name, str) or op_name not in KNOWN_OPS:
            return PatchValidationResult(
                accepted=False,
                rejection_reason=f"unknown op: {op_name}",
            )
        if op_name not in allowed_ops:
            return PatchValidationResult(
                accepted=False,
                rejection_reason=f"actor role {actor_role} cannot perform {op_name}",
            )

    for op in ops:
        op_name = op["op"]
        if op_name == "set_resource_claims":
            escalation_reason = _resource_claim_escalation_reason(op, projection)
            if escalation_reason is not None:
                return PatchValidationResult(accepted=False, rejection_reason=escalation_reason)
        elif op_name == "retire_node":
            node_id = op.get("node_id")
            if (
                isinstance(node_id, str)
                and projection["node_states"].get(node_id) in RUNNING_STATES
            ):
                return PatchValidationResult(
                    accepted=False,
                    rejection_reason=f"cannot retire active node: {node_id}",
                )
        elif op_name == "create_node":
            node = op.get("node")
            if isinstance(node, dict):
                typed_node = cast(dict[str, Any], node)
                kind = typed_node.get("kind")
                role = typed_node.get("role")
                if kind in EXECUTABLE_NODE_KINDS and not isinstance(role, str):
                    return PatchValidationResult(
                        accepted=False,
                        rejection_reason=f"executable node requires role: {kind}",
                    )

    planner_successor_error = _validate_planner_successor_bindings(ops)
    if planner_successor_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=planner_successor_error)

    return PatchValidationResult(accepted=True)


def _validate_planner_successor_bindings(ops: list[dict[str, Any]]) -> str | None:
    successor_ids: set[str] = set()
    required_ports_by_successor: dict[str, set[str]] = {}
    for op in ops:
        if op.get("op") != "create_node":
            continue
        node = op.get("node")
        if not isinstance(node, dict):
            continue
        typed_node = cast(dict[str, Any], node)
        if typed_node.get("kind") != "planner" or typed_node.get("role") != "planner":
            continue
        node_id = typed_node.get("node_id")
        if not isinstance(node_id, str):
            continue
        successor_ids.add(node_id)
        required_ports_by_successor[node_id] = {
            str(port.get("port"))
            for port in _port_dicts(typed_node.get("inputs"))
            if port.get("required") is not False and isinstance(port.get("port"), str)
        }

    if not successor_ids:
        return None

    selector_ports_by_successor: dict[str, set[str]] = {node_id: set() for node_id in successor_ids}
    for op in ops:
        if op.get("op") != "create_edge":
            continue
        to_node_id = op.get("to_node_id")
        to_port = op.get("to_port")
        if not isinstance(to_node_id, str) or to_node_id not in successor_ids:
            continue
        if not isinstance(to_port, str) or to_port not in PLANNER_SUCCESSOR_PORTS:
            return f"invalid planner successor input port: {to_port}"
        if not _has_selector_for_port(op, to_port):
            return f"planner successor input requires selector: {to_port}"
        selector_ports_by_successor[to_node_id].add(to_port)

    for node_id, required_ports in required_ports_by_successor.items():
        missing = sorted(required_ports - selector_ports_by_successor[node_id])
        if missing:
            return f"planner successor missing selector-bound inputs: {', '.join(missing)}"
    return None


def _has_selector_for_port(op: dict[str, Any], port: str) -> bool:
    selector = op.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return False
    typed_selector = cast(dict[str, Any], selector)
    record_kinds = typed_selector.get("record_kinds")
    if not isinstance(record_kinds, list):
        return False
    return port in {kind for kind in cast(list[Any], record_kinds) if isinstance(kind, str)}


def _port_dicts(raw_ports: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_ports, list):
        return []
    return [
        cast(dict[str, Any], port) for port in cast(list[Any], raw_ports) if isinstance(port, dict)
    ]


def _validate_staleness(
    patch: PatchEnvelope,
    current_position: int,
    events_since_base: list[EventEnvelope],
    ops: list[dict[str, Any]],
) -> PatchValidationResult | None:
    if patch.base_graph_position >= current_position:
        return None

    patch_read_set = set[str]().union(*(op_read_set(op) for op in ops))
    invalidating = [
        event
        for event in events_since_base
        if classify_event(event) == "invalidating"
        and _event_touches_read_set(event, patch_read_set)
    ]
    if not invalidating:
        return None

    return PatchValidationResult(
        accepted=False,
        rejection_reason="stale patch conflicts with invalidating events",
        conflicting_events=invalidating,
        read_set_diff={
            "patch_read_set": sorted(patch_read_set),
            "conflicting_event_ids": [event.event_id for event in invalidating],
        },
    )


def _event_touches_read_set(event: EventEnvelope, read_set: set[str]) -> bool:
    node_id = event.payload.get("node_id")
    if isinstance(node_id, str) and node_id in read_set:
        return True

    record_id = event.payload.get("record_id")
    if isinstance(record_id, str) and record_id in read_set:
        return True

    region_node_ids = event.payload.get("region_node_ids")
    return bool(_string_values_from_iterable(region_node_ids) & read_set)


def _resource_claim_escalation_reason(
    op: dict[str, Any],
    projection: GraphProjection,
) -> str | None:
    node_id = op.get("node_id")
    if not isinstance(node_id, str):
        return None

    existing_rank = _existing_resource_claim_rank(projection, node_id)
    if existing_rank is None:
        return None

    for claim in _resource_claim_dicts(op.get("resource_claims")):
        mode = claim.get("mode")
        requested_rank = MODE_RANK.get(mode) if isinstance(mode, str) else None
        if requested_rank is not None and requested_rank > existing_rank:
            return f"resource claim escalation for {node_id}: {mode}"
    return None


def _existing_resource_claim_rank(projection: GraphProjection, node_id: str) -> int | None:
    projection_data = cast(dict[str, Any], projection)
    candidate_sources = (
        projection_data.get("resource_claims"),
        projection_data.get("node_resource_claims"),
    )
    for source in candidate_sources:
        if not isinstance(source, dict):
            continue
        typed_source = cast(dict[str, Any], source)
        raw_claims = typed_source.get(node_id)
        ranks = [
            rank
            for claim in _resource_claim_dicts(raw_claims)
            if isinstance(claim.get("mode"), str)
            for rank in [MODE_RANK.get(claim["mode"])]
            if rank is not None
        ]
        if ranks:
            return max(ranks)
    return None


def _resource_claim_dicts(raw_claims: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_claims, list):
        return []

    claims: list[dict[str, Any]] = []
    for claim in cast(list[Any], raw_claims):
        if isinstance(claim, dict):
            claims.append(cast(dict[str, Any], claim))
        else:
            model_dump = getattr(claim, "model_dump", None)
            if not callable(model_dump):
                continue
            dumped = model_dump()
            if isinstance(dumped, dict):
                claims.append(cast(dict[str, Any], dumped))
    return claims


def _op_to_dict(op: Any) -> dict[str, Any]:
    if isinstance(op, dict):
        return cast(dict[str, Any], op)
    dumped = op.model_dump()
    return cast(dict[str, Any], dumped)


def _string_values(*values: Any) -> set[str]:
    return {value for value in values if isinstance(value, str)}


def _string_values_from_iterable(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in cast(list[Any], value) if isinstance(item, str)}
