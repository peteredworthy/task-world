"""Pure graph patch validation helpers."""

from collections.abc import Sequence
from dataclasses import dataclass, field
import posixpath
from typing import Any, cast

from orchestrator.graph.command_bindings import is_known_check_command_binding
from orchestrator.graph.contracts import validate_edge_payload, validate_node_payload
from orchestrator.graph.models import (
    EdgeProjection,
    EventEnvelope,
    PatchEnvelope,
    normalize_record_selector,
)
from orchestrator.graph.projection_queries import resource_claims_for_node
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
    "requirement_revision_recorded",
    "node_authority_changed",
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
    "gap_planner": PLANNER_OPS,
    "oversight": KNOWN_OPS,
    "human": KNOWN_OPS,
    "controller": KNOWN_OPS,
}
MODE_RANK = {"read": 0, "write": 1, "graph_write": 2, "review_write": 3}
RESOURCE_CLAIM_MODES = {"read", "write", "external", "graph_write", "review_write"}
RUNNING_STATES = {"running", "leased"}
EXECUTABLE_NODE_KINDS = {"worker", "verifier", "check", "planner"}
PLANNER_SUCCESSOR_PORTS = {
    "region_summary",
    "accepted_file_state",
    "outstanding_failures",
    "session_carryover",
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
        for claim in _op_resource_claim_dicts(op):
            shape_error = _resource_claim_shape_error(claim)
            if shape_error is not None:
                return PatchValidationResult(accepted=False, rejection_reason=shape_error)
        if op_name == "set_resource_claims":
            escalation_reason = _resource_claim_escalation_reason(op, projection)
            if escalation_reason is not None:
                return PatchValidationResult(accepted=False, rejection_reason=escalation_reason)
        elif op_name == "retire_node":
            node_id = op.get("node_id")
            if (
                actor_role == "gap_planner"
                and isinstance(node_id, str)
                and projection["node_kinds"].get(node_id) in {"worker", "verifier", "check"}
            ):
                return PatchValidationResult(
                    accepted=False,
                    rejection_reason=f"gap planner cannot retire executable node: {node_id}",
                )
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
                contract_error = validate_node_payload(typed_node)
                if contract_error is not None:
                    return PatchValidationResult(
                        accepted=False,
                        rejection_reason=contract_error,
                    )
                kind = typed_node.get("kind")
                role = typed_node.get("role")
                if actor_role == "gap_planner":
                    gap_planner_error = _validate_gap_planner_node(typed_node)
                    if gap_planner_error is not None:
                        return PatchValidationResult(
                            accepted=False,
                            rejection_reason=gap_planner_error,
                        )
                if kind in EXECUTABLE_NODE_KINDS and not isinstance(role, str):
                    return PatchValidationResult(
                        accepted=False,
                        rejection_reason=f"executable node requires role: {kind}",
                    )
                if kind == "check":
                    check_command_error = _validate_check_command(typed_node, actor_role)
                    if check_command_error is not None:
                        return PatchValidationResult(
                            accepted=False,
                            rejection_reason=check_command_error,
                        )

    topology_error = _validate_typed_topology(ops, projection)
    if topology_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=topology_error)

    cycle_error = _validate_no_forbidden_cycles(ops, projection)
    if cycle_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=cycle_error)

    poison_error = _validate_no_poisoned_final_invariant_edges(ops, projection)
    if poison_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=poison_error)

    planner_successor_error = _validate_planner_successor_bindings(ops)
    if planner_successor_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=planner_successor_error)

    dynamic_region_error = _validate_dynamic_region_dependencies(ops, actor_role)
    if dynamic_region_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=dynamic_region_error)

    return PatchValidationResult(accepted=True)


def _validate_typed_topology(
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> str | None:
    created_nodes: dict[str, tuple[str, str | None]] = {}
    seen_node_ids: set[str] = set()
    seen_edge_ids: set[str] = set()

    for op in ops:
        op_name = op.get("op")
        if op_name == "create_node":
            node = op.get("node")
            if not isinstance(node, dict):
                return "create_node requires node payload"
            duplicate_error = _register_created_node(
                cast(dict[str, Any], node),
                created_nodes,
                seen_node_ids,
                projection,
                missing_message="create_node requires node_id",
            )
            if duplicate_error is not None:
                return duplicate_error
        elif op_name == "create_revision_attempt":
            for node_key, default_kind in (
                ("worker_node", "worker"),
                ("verifier_node", "verifier"),
            ):
                node = op.get(node_key)
                if not isinstance(node, dict):
                    continue
                duplicate_error = _register_created_node(
                    cast(dict[str, Any], node),
                    created_nodes,
                    seen_node_ids,
                    projection,
                    missing_message=f"create_revision_attempt {node_key} requires node_id",
                    default_kind=default_kind,
                )
                if duplicate_error is not None:
                    return duplicate_error
        elif op_name == "create_edge":
            edge_id = op.get("edge_id")
            if not isinstance(edge_id, str) or not edge_id:
                return "create_edge requires edge_id"
            if edge_id in seen_edge_ids or edge_id in projection["edges"]:
                return f"duplicate edge id: {edge_id}"
            seen_edge_ids.add(edge_id)

    for op in ops:
        if op.get("op") != "create_edge":
            continue
        edge = op
        edge_id = edge.get("edge_id")
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        if not isinstance(edge_id, str) or not edge_id:
            return "create_edge requires edge_id"
        if not isinstance(from_node_id, str) or not from_node_id:
            return f"edge {edge_id} requires from_node_id"
        if not isinstance(to_node_id, str) or not to_node_id:
            return f"edge {edge_id} requires to_node_id"

        if from_node_id == "*":
            source = _producer_class_contract_identity(edge)
            if source is None:
                return f"edge {edge_id} producer-class source requires from_node_kind"
        else:
            source = _node_contract_identity(from_node_id, created_nodes, projection)
            if source is None:
                return f"edge {edge_id} references unknown source node: {from_node_id}"
        target = _node_contract_identity(to_node_id, created_nodes, projection)
        if target is None:
            return f"edge {edge_id} references unknown target node: {to_node_id}"

        contract_error = validate_edge_payload(
            edge,
            source_kind=source[0],
            source_role=source[1],
            target_kind=target[0],
            target_role=target[1],
        )
        if contract_error is not None:
            return contract_error

    return None


def _register_created_node(
    node: dict[str, Any],
    created_nodes: dict[str, tuple[str, str | None]],
    seen_node_ids: set[str],
    projection: GraphProjection,
    *,
    missing_message: str,
    default_kind: str | None = None,
) -> str | None:
    node_id = node.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        return missing_message
    if node_id in seen_node_ids or node_id in projection["node_kinds"]:
        return f"duplicate node id: {node_id}"
    seen_node_ids.add(node_id)
    kind = node.get("kind")
    if not isinstance(kind, str):
        kind = default_kind
    if isinstance(kind, str):
        role = node.get("role")
        created_nodes[node_id] = (kind, role if isinstance(role, str) else None)
    return None


def _producer_class_contract_identity(edge: dict[str, Any]) -> tuple[str, str | None] | None:
    kind = edge.get("from_node_kind")
    if not isinstance(kind, str) or not kind:
        return None
    role = edge.get("from_node_role")
    return kind, role if isinstance(role, str) else None


def _node_contract_identity(
    node_id: str,
    created_nodes: dict[str, tuple[str, str | None]],
    projection: GraphProjection,
) -> tuple[str, str | None] | None:
    created = created_nodes.get(node_id)
    if created is not None:
        return created
    kind = projection["node_kinds"].get(node_id)
    if not isinstance(kind, str):
        return None
    role = projection.get("node_roles", {}).get(node_id)
    return (kind, role if isinstance(role, str) else None)


def _validate_gap_planner_node(node: dict[str, Any]) -> str | None:
    kind = node.get("kind")
    if kind == "planner":
        return "gap planner cannot create planner successor"
    if (
        kind in {"worker", "verifier", "check"}
        and node.get("task_region_id") != "corrective_work_region"
    ):
        return "gap planner executable nodes must target corrective_work_region"
    return None


def _validate_check_command(node: dict[str, Any], actor_role: str) -> str | None:
    command_definition = node.get("command_definition")
    if isinstance(command_definition, dict):
        return None

    hidden_oracle_command = node.get("hidden_oracle_command")
    if isinstance(hidden_oracle_command, str) and hidden_oracle_command.strip():
        if actor_role in {"planner", "gap_planner"}:
            node_id = node.get("node_id")
            if isinstance(node_id, str):
                return f"check node cannot expose hidden_oracle_command; use command_binding: {node_id}"
            return "check node cannot expose hidden_oracle_command; use command_binding"
        return None

    command_binding = node.get("command_binding")
    if is_known_check_command_binding(command_binding):
        return None

    node_id = node.get("node_id")
    if isinstance(node_id, str):
        return (
            "check node requires command_definition, hidden_oracle_command, "
            f"or command_binding: {node_id}"
        )
    return "check node requires command_definition, hidden_oracle_command, or command_binding"


def _validate_no_forbidden_cycles(
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> str | None:
    adjacency: dict[str, set[str]] = {}
    patch_nodes: set[str] = set()

    for edge in projection["edges"].values():
        source = edge.from_node_id
        target = edge.to_node_id
        adjacency.setdefault(source, set()).add(target)

    for op in ops:
        if op.get("op") != "create_edge":
            continue
        source = op.get("from_node_id")
        target = op.get("to_node_id")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        adjacency.setdefault(source, set()).add(target)
        patch_nodes.update((source, target))

    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(node_id: str, path: list[str]) -> list[str] | None:
        if node_id in visiting:
            cycle_start = path.index(node_id) if node_id in path else 0
            return path[cycle_start:]
        if node_id in visited:
            return None
        visiting.add(node_id)
        for next_node_id in sorted(adjacency.get(node_id, set())):
            cycle = visit(next_node_id, [*path, next_node_id])
            if cycle is not None:
                return cycle
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in sorted(adjacency):
        cycle = visit(node_id, [node_id])
        if cycle is None:
            continue
        if patch_nodes.isdisjoint(cycle):
            continue
        return f"graph patch would create forbidden cycle: {' -> '.join(cycle)}"
    return None


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


def _validate_dynamic_region_dependencies(
    ops: list[dict[str, Any]],
    actor_role: str,
) -> str | None:
    created_nodes = _created_nodes_by_id(ops)

    if not created_nodes:
        return None

    incoming_ports = _required_incoming_ports_by_node(ops, set(created_nodes))
    for node_id, node in created_nodes.items():
        kind = node.get("kind")
        role = node.get("role")
        ports = incoming_ports.get(node_id, set())
        if (
            kind == "planner"
            and role == "gap_planner"
            and ports.isdisjoint({"verification_evidence", "verification_report"})
        ):
            return "gap planner requires verification input edge"
        if (
            actor_role != "gap_planner"
            and _is_corrective_worker(node_id, node)
            and "classified_gap" not in ports
        ):
            return "corrective worker requires classified_gap input edge"
        if (
            kind == "check"
            and role == "invariant_gate"
            and ports.isdisjoint({"verification_evidence", "verification_report"})
        ):
            return "invariant check requires verification input edge"
    return None


def _validate_no_poisoned_final_invariant_edges(
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> str | None:
    created_nodes = _created_nodes_by_id(ops)
    edge_ops = [op for op in ops if op.get("op") == "create_edge"]
    existing_edges = projection["edges"].values()

    for edge in edge_ops:
        if not _is_required_passed_verification_edge(edge):
            continue
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        if not isinstance(from_node_id, str) or not isinstance(to_node_id, str):
            continue
        from_kind, _from_role = _node_kind_role(from_node_id, created_nodes, projection)
        to_kind, to_role = _node_kind_role(to_node_id, created_nodes, projection)
        if from_kind != "verifier" or to_kind != "check" or to_role != "invariant_gate":
            continue
        if any(
            _is_failed_verification_projection(candidate, from_node_id)
            for candidate in existing_edges
        ) or any(
            _is_failed_verification_continuation(candidate, from_node_id) for candidate in edge_ops
        ):
            return (
                f"required pass-gated final invariant edge from verifier {from_node_id} "
                "is poisoned by a failure continuation"
            )
    return None


def _created_nodes_by_id(ops: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    created_nodes: dict[str, dict[str, Any]] = {}
    for op in ops:
        if op.get("op") != "create_node":
            continue
        node = op.get("node")
        if not isinstance(node, dict):
            continue
        typed_node = cast(dict[str, Any], node)
        node_id = typed_node.get("node_id")
        if isinstance(node_id, str):
            created_nodes[node_id] = typed_node
    return created_nodes


def _node_kind_role(
    node_id: str,
    created_nodes: dict[str, dict[str, Any]],
    projection: GraphProjection,
) -> tuple[str | None, str | None]:
    created = created_nodes.get(node_id)
    if created is not None:
        kind = created.get("kind")
        role = created.get("role")
        return (
            kind if isinstance(kind, str) else None,
            role if isinstance(role, str) else None,
        )
    return projection["node_kinds"].get(node_id), projection["node_roles"].get(node_id)


def _is_required_passed_verification_edge(edge: dict[str, Any]) -> bool:
    if edge.get("from_port") != "verification_report":
        return False
    if edge.get("to_port") not in {"verification_evidence", "verification_report"}:
        return False
    if edge.get("required") is False:
        return False
    return _selector_outcome(edge) == "passed"


def _is_failed_verification_continuation(edge: dict[str, Any], verifier_node_id: str) -> bool:
    if edge.get("from_node_id") != verifier_node_id:
        return False
    if edge.get("from_port") != "verification_report":
        return False
    return _selector_outcome(edge) == "failed"


def _is_failed_verification_projection(edge: EdgeProjection, verifier_node_id: str) -> bool:
    if edge.from_node_id != verifier_node_id or edge.from_port != "verification_report":
        return False
    selector = edge.accepted_record_selector
    if not isinstance(selector, dict):
        return False
    return _selector_outcome({"accepted_record_selector": selector}) == "failed"


def _selector_outcome(edge: dict[str, Any]) -> str | None:
    selector = edge.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return None
    try:
        typed_selector = normalize_record_selector(selector)
    except ValueError:
        return None
    if typed_selector.get("record_type") != "verification_report":
        return None
    outcome = typed_selector.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _required_incoming_ports_by_node(
    ops: list[dict[str, Any]],
    created_node_ids: set[str],
) -> dict[str, set[str]]:
    ports: dict[str, set[str]] = {node_id: set() for node_id in created_node_ids}
    for op in ops:
        if op.get("op") != "create_edge":
            continue
        to_node_id = op.get("to_node_id")
        to_port = op.get("to_port")
        if not isinstance(to_node_id, str) or to_node_id not in created_node_ids:
            continue
        if not isinstance(to_port, str) or op.get("required") is False:
            continue
        if not isinstance(op.get("accepted_record_selector"), dict):
            continue
        ports[to_node_id].add(to_port)
    return ports


def _is_corrective_worker(node_id: str, node: dict[str, Any]) -> bool:
    if node.get("kind") != "worker":
        return False
    role = node.get("role")
    task_region_id = node.get("task_region_id")
    return (
        role == "fixer"
        or "corrective" in node_id
        or (isinstance(task_region_id, str) and "corrective" in task_region_id)
    )


def _has_selector_for_port(op: dict[str, Any], port: str) -> bool:
    selector = op.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return False
    try:
        typed_selector = normalize_record_selector(selector)
    except ValueError:
        return False
    return _selector_accepts_port(typed_selector, port)


def _selector_accepts_port(selector: dict[str, Any], port: str) -> bool:
    record_type = selector.get("record_type")
    if record_type == "any_of":
        raw_selectors = selector.get("selectors")
        if not isinstance(raw_selectors, list):
            return False
        for raw_selector in cast(list[Any], raw_selectors):
            if isinstance(raw_selector, dict) and _selector_accepts_port(
                cast(dict[str, Any], raw_selector),
                port,
            ):
                return True
        return False
    if port == "accepted_file_state":
        return record_type == "file_state"
    if port in {"verification_evidence", "verification_report"}:
        return record_type in {"verification_report", "check_result"}
    if port == "outstanding_failures":
        return record_type == "failure_record"
    if port == "region_summary":
        return record_type == "analysis_summary"
    return record_type == port


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


def _op_resource_claim_dicts(op: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect every resource-claim dict a patch op could introduce.

    Claims arrive either directly on ``set_resource_claims`` ops, or nested inside a
    node payload's ``authority.resource_claims`` on node-creation ops (``create_node``,
    ``create_gate``, ``create_appeal`` via ``node``; ``create_revision_attempt`` via
    ``worker_node``/``verifier_node``).
    """
    claims = list(_resource_claim_dicts(op.get("resource_claims")))
    for node_key in ("node", "worker_node", "verifier_node"):
        node = op.get(node_key)
        if not isinstance(node, dict):
            continue
        authority = cast(dict[str, Any], node).get("authority")
        if isinstance(authority, dict):
            claims.extend(
                _resource_claim_dicts(cast(dict[str, Any], authority).get("resource_claims"))
            )
    return claims


def _is_repo_relative_claim_path(path: str) -> bool:
    if path == "":
        return False
    if path.startswith("/"):
        return False
    normalized = posixpath.normpath(path)
    return normalized != ".." and not normalized.startswith("../")


def _resource_claim_shape_error(claim: dict[str, Any]) -> str | None:
    """Reject claim shapes normalization cannot make sense of.

    Path-in-scope claims (``scope`` set to a repo-relative path instead of the
    canonical ``"repo"``) are intentionally NOT rejected here: they are accepted and
    normalized to ``scope="repo"`` with the path folded into ``paths`` when the event is
    applied (see ``_claim_from_dict`` in commands.py). Only shapes that normalization
    cannot safely interpret — unknown modes, wrong-typed fields, or scope/paths values
    that escape the repo (absolute paths, ``..`` segments) — are rejected here, with a
    message that spells out the canonical shape for the planner.
    """
    mode = claim.get("mode")
    if not isinstance(mode, str) or mode not in RESOURCE_CLAIM_MODES:
        return (
            f"resource_claims mode must be one of {sorted(RESOURCE_CLAIM_MODES)}; got mode={mode!r}"
        )
    scope = claim.get("scope")
    if scope is not None and not isinstance(scope, str):
        return f"resource_claims scope must be a string; got scope={scope!r}"
    raw_paths = claim.get("paths")
    if raw_paths is not None:
        if not isinstance(raw_paths, list) or not all(
            isinstance(path, str) for path in cast(list[Any], raw_paths)
        ):
            return f"resource_claims paths must be a list of strings; got paths={raw_paths!r}"
    if (
        mode in {"read", "write"}
        and isinstance(scope, str)
        and scope not in ("repo", "")
        and not _is_repo_relative_claim_path(scope)
    ):
        return (
            'resource_claims must use scope="repo" with paths=[...]; '
            f"got scope={scope!r} — path prefixes belong in paths, not scope, and must "
            'be repo-relative (no leading "/" and no ".." segments)'
        )
    if isinstance(raw_paths, list):
        for path in cast(list[str], raw_paths):
            # Empty-string path entries are deliberately rejected here in favor of the
            # canonical whole-repo spellings (paths=["."], empty paths, or scope="").
            if not _is_repo_relative_claim_path(path):
                return (
                    "resource_claims paths entries must be repo-relative paths "
                    f'(no leading "/" and no ".." segments): {path!r}'
                )
    return None


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
    ranks = [
        rank
        for claim in _resource_claim_dicts(resource_claims_for_node(projection, node_id))
        if isinstance(claim.get("mode"), str)
        for rank in [MODE_RANK.get(claim["mode"])]
        if rank is not None
    ]
    return max(ranks) if ranks else None


def _resource_claim_dicts(raw_claims: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_claims, Sequence):
        return []

    claims: list[dict[str, Any]] = []
    for claim in cast(Sequence[Any], raw_claims):
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
