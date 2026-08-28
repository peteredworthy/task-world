"""Pure graph patch validation helpers."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import posixpath
from typing import Any, cast

from orchestrator.graph.command_bindings import is_known_check_command_binding
from orchestrator.graph.contracts import validate_edge_payload, validate_node_payload
from orchestrator.graph.models import (
    EdgeProjection,
    EventEnvelope,
    PatchEnvelope,
    SemanticArtifactRecord,
    VerificationReportRecord,
    normalize_record_selector,
)
from orchestrator.graph.projection_queries import (
    edges_view,
    node_kinds_view,
    node_payload_view,
    node_roles_view,
    node_states_view,
    record_payloads_view,
    resource_claims_for_node,
    semantic_schema_declarations_view,
    output_record_payloads_view,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.semantic_artifacts import (
    accepted_semantic_declaration,
)


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
    "semantic_artifact",
    "verification_report",
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
                and node_kinds_view(projection).get(node_id) in {"worker", "verifier", "check"}
            ):
                return PatchValidationResult(
                    accepted=False,
                    rejection_reason=f"gap planner cannot retire executable node: {node_id}",
                )
            if (
                isinstance(node_id, str)
                and node_states_view(projection).get(node_id) in RUNNING_STATES
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
                if kind == "worker":
                    worker_contract_error = _validate_worker_contract(typed_node)
                    if worker_contract_error is not None:
                        return PatchValidationResult(
                            accepted=False,
                            rejection_reason=worker_contract_error,
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

    semantic_stage_error = _validate_semantic_stage_invariants(ops, projection)
    if semantic_stage_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=semantic_stage_error)

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
            if edge_id in seen_edge_ids or edge_id in edges_view(projection):
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
    if node_id in seen_node_ids or node_id in node_kinds_view(projection):
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
    kind = node_kinds_view(projection).get(node_id)
    if not isinstance(kind, str):
        return None
    role = node_roles_view(projection).get(node_id)
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


def _validate_worker_contract(node: dict[str, Any]) -> str | None:
    node_id = node.get("node_id")

    objective = node.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return f"worker node requires objective: {node_id}"

    access_mode = node.get("access_mode")
    if access_mode is None:
        return f"worker node requires access_mode: {node_id}"
    if access_mode not in ("read_only", "write"):
        return f"worker node access_mode must be read_only or write: {node_id}"

    acceptance = node.get("acceptance")
    if not acceptance:
        return f"worker node requires acceptance: {node_id}"
    if not isinstance(acceptance, list) or not all(
        isinstance(item, str) and item.strip() for item in cast(list[Any], acceptance)
    ):
        return f"worker node acceptance must be a list of non-empty strings: {node_id}"

    override_justification = node.get("access_mode_override_justification")
    has_override = override_justification is not None
    if has_override and (
        not isinstance(override_justification, str) or not override_justification.strip()
    ):
        return f"access_mode_override_justification must be a non-empty string: {node_id}"

    role = node.get("role")
    is_discovery_write = role == "discovery" and access_mode == "write"
    if is_discovery_write:
        return (
            "discovery worker cannot declare access_mode write; "
            f"use a separate effectful artifact-writer region: {node_id}"
        )
    if has_override:
        return (
            f"access_mode_override_justification cannot grant repository write authority: {node_id}"
        )

    if access_mode == "read_only":
        authority = node.get("authority")
        raw_claims = (
            cast(dict[str, Any], authority).get("resource_claims")
            if isinstance(authority, dict)
            else None
        )
        for claim in resource_claim_dicts(raw_claims):
            mode = claim.get("mode")
            rank = MODE_RANK.get(mode) if isinstance(mode, str) else None
            if rank is not None and rank > MODE_RANK["read"]:
                return f"read_only worker cannot claim {mode} authority: {node_id}"

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

    for edge in edges_view(projection).values():
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
        if node.get("semantic_stage") == "corrective_work":
            if "verification_report" not in ports:
                return "corrective worker requires exact failed verification_report input edge"
            if "check_result" not in ports:
                return "corrective worker requires exact failed check_result input edge"
        if (
            kind == "check"
            and role == "invariant_gate"
            and ports.isdisjoint({"verification_evidence", "verification_report"})
        ):
            return "invariant check requires verification input edge"
    return None


def _validate_semantic_stage_invariants(
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> str | None:
    """Enforce reliable-plan semantics on staged nodes, not merely prompts."""
    created = _created_nodes_by_id(ops)
    edge_ops = [op for op in ops if op.get("op") == "create_edge"]
    all_edges = [edge.model_dump(mode="json") for edge in edges_view(projection).values()]
    all_edges.extend(edge_ops)
    declared_batches = _accepted_declared_batch_ids(projection)
    known_payloads = {
        node_id: payload
        for node_id in node_kinds_view(projection)
        if (payload := node_payload_view(projection, node_id)) is not None
    }
    all_payloads = {**known_payloads, **created}
    declarations = semantic_schema_declarations_view(projection)

    existing_batch_regions: dict[str, str] = {}
    for payload in known_payloads.values():
        batch_id = payload.get("declared_batch_id")
        region_id = payload.get("task_region_id")
        if isinstance(batch_id, str) and isinstance(region_id, str):
            existing_batch_regions.setdefault(batch_id, region_id)

    region_batches: dict[str, set[str]] = {}
    for payload in all_payloads.values():
        if payload.get("semantic_stage") != "effectful_batch":
            continue
        batch_id = payload.get("declared_batch_id")
        region_id = payload.get("task_region_id")
        if isinstance(batch_id, str) and isinstance(region_id, str):
            region_batches.setdefault(region_id, set()).add(batch_id)
    collapsed = next(
        ((region_id, batches) for region_id, batches in region_batches.items() if len(batches) > 1),
        None,
    )
    if collapsed is not None:
        return (
            f"declared batches must use distinct task regions: {collapsed[0]} contains "
            + ", ".join(sorted(collapsed[1]))
        )

    for node_id, node in created.items():
        kind = node.get("kind")
        stage = node.get("semantic_stage")
        if stage == "discovery":
            if kind != "worker" or node.get("role") != "discovery":
                return "semantic discovery stage must be a discovery worker"
            if node.get("access_mode") != "read_only":
                return "semantic discovery stage must be read_only"
            if not _declares_semantic_artifact_output(node):
                return "semantic discovery stage must declare a semantic_artifact output"
            schema_id = node.get("semantic_schema_id")
            schema_version = node.get("semantic_schema_version")
            if (
                not isinstance(schema_id, str)
                or not isinstance(schema_version, int)
                or (accepted_semantic_declaration(declarations, schema_id, schema_version) is None)
            ):
                return "semantic discovery stage requires an accepted exact schema declaration"

        if stage == "plan_verification":
            if kind != "verifier":
                return "plan verification stage must be an independent verifier"
            incoming = [edge for edge in all_edges if edge.get("to_node_id") == node_id]
            semantic_edges = [
                edge for edge in incoming if edge.get("to_port") == "semantic_artifact"
            ]
            if len(semantic_edges) != 1:
                return "plan verification requires exactly one declared semantic artifact input"
            if semantic_edges[0].get("from_node_id") == node_id:
                return "plan verification must be independent from artifact production"
            if not any(
                str(edge.get("to_port", "")).startswith("requirement_") for edge in incoming
            ):
                return "plan verification requires bound requirement evidence"
            schema_id = node.get("semantic_schema_id")
            schema_version = node.get("semantic_schema_version")
            if (
                not isinstance(schema_id, str)
                or not isinstance(schema_version, int)
                or (accepted_semantic_declaration(declarations, schema_id, schema_version) is None)
            ):
                return "plan verification requires an accepted exact schema declaration"

        if stage == "corrective_work":
            correction_error = _corrective_evidence_error(node_id, node, all_edges, projection)
            if correction_error is not None:
                return correction_error

        if kind == "worker" and node.get("access_mode") == "write" and declared_batches:
            if stage != "effectful_batch":
                return "implementation against a declared batch plan must use effectful_batch semantics"

        if stage == "effectful_batch" and kind == "worker":
            batch_id = node.get("declared_batch_id")
            region_id = node.get("task_region_id")
            amendment = node.get("accepted_plan_amendment_record_id")
            if not isinstance(batch_id, str) or not isinstance(region_id, str):
                return "effectful batch requires declared_batch_id and distinct task_region_id"
            if declared_batches and batch_id not in declared_batches:
                amendment_error = _plan_amendment_error(projection, amendment, batch_id)
                if amendment_error is not None:
                    return amendment_error
            existing_region = existing_batch_regions.get(batch_id)
            if (
                existing_region is not None
                and existing_region != region_id
                and not isinstance(amendment, str)
            ):
                return f"batch {batch_id} is already represented by region {existing_region}"
            error = _effectful_batch_shape_error(
                node_id,
                batch_id,
                region_id,
                all_edges,
                all_payloads,
            )
            if error is not None:
                return error

    if declared_batches:
        final_gates = {
            node_id: node
            for node_id, node in all_payloads.items()
            if node.get("kind") == "final_gate"
        }
        for node_id, node in final_gates.items():
            error = _final_gate_semantic_error(
                node_id, node, all_edges, all_payloads, declared_batches
            )
            if error is not None:
                return error
    return None


def _corrective_evidence_error(
    node_id: str,
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    projection: GraphProjection,
) -> str | None:
    incoming = [edge for edge in edges if edge.get("to_node_id") == node_id]
    records = record_payloads_view(projection)

    exact: dict[str, list[dict[str, Any]]] = {
        "verification_report": [],
        "check_result": [],
        "classified_gap": [],
    }
    for edge in incoming:
        to_port = edge.get("to_port")
        if to_port not in exact:
            continue
        source = edge.get("from_node_id")
        record_id = _selector_field(edge, "record_id")
        if not isinstance(source, str) or not isinstance(record_id, str):
            return f"corrective worker {to_port} edge requires an exact immutable record_id"
        payload = records.get(record_id)
        if payload is None or payload.get("producer_node_id") != source:
            return f"corrective worker {to_port} record must exist and match its edge producer"
        exact[cast(str, to_port)].append(payload)

    failed_reports = exact["verification_report"]
    failed_checks = exact["check_result"]
    gap_records = exact["classified_gap"]
    if len(failed_reports) != 1:
        return "corrective worker requires one exact failed verification record"
    if not failed_checks:
        return "corrective worker requires exact failed check records"
    if len(gap_records) != 1:
        return "corrective worker requires one accepted gap analysis record"
    expected_report_id = node.get("failed_verification_record_id")
    expected_check_ids = node.get("failed_check_record_ids")
    expected_gap_id = node.get("classified_gap_record_id")
    if expected_report_id != failed_reports[0].get("record_id"):
        return "corrective worker verification binding does not match its immutable record ID"
    typed_expected_check_ids: set[str] = (
        {item for item in cast(list[Any], expected_check_ids) if isinstance(item, str)}
        if isinstance(expected_check_ids, list)
        else set()
    )
    if not isinstance(expected_check_ids, list) or typed_expected_check_ids != {
        check.get("record_id") for check in failed_checks
    }:
        return "corrective worker check bindings do not match their immutable record IDs"
    if expected_gap_id != gap_records[0].get("record_id"):
        return "corrective worker gap binding does not match its immutable record ID"
    if (
        failed_reports[0].get("record_type") != "verification_report"
        or _terminal_value(failed_reports[0], "outcome") != "failed"
    ):
        return "corrective verification record must be failed"
    if any(
        check.get("record_type") != "check_result" or _terminal_value(check, "status") != "failed"
        for check in failed_checks
    ):
        return "corrective check records must be failed"
    if gap_records[0].get("record_type") not in {"gap_classification", "classified_gap"} or (
        _terminal_value(gap_records[0], "classification") != "corrective_work_required"
    ):
        return "corrective gap analysis must be accepted corrective_work_required evidence"
    candidate_id = failed_reports[0].get("candidate_id")
    if not isinstance(candidate_id, str) or any(
        check.get("candidate_id") != candidate_id for check in failed_checks
    ):
        return "corrective verification and checks must cite the same failed candidate"
    required_ids = {
        cast(str, record["record_id"])
        for record in [*failed_reports, *failed_checks]
        if isinstance(record.get("record_id"), str)
    }
    provenance = gap_records[0].get("provenance")
    cited_ids: set[str] = (
        {
            item
            for item in cast(
                list[Any], cast(dict[str, Any], provenance).get("evaluated_record_ids", [])
            )
            if isinstance(item, str)
        }
        if isinstance(provenance, dict)
        else set()
    )
    if not required_ids.issubset(cited_ids):
        return "corrective gap analysis must cite exact failed verification and check records"
    return None


def _terminal_value(payload: dict[str, Any], field: str) -> Any:
    direct = payload.get(field)
    if direct is not None:
        return direct
    value = payload.get("value")
    return cast(dict[str, Any], value).get(field) if isinstance(value, dict) else None


def _plan_amendment_error(projection: GraphProjection, record_id: Any, batch_id: str) -> str | None:
    if not isinstance(record_id, str):
        return f"batch {batch_id} is not declared by the accepted plan"
    records = output_record_payloads_view(projection)
    record = records.get(record_id)
    if not isinstance(record, SemanticArtifactRecord):
        return "accepted_plan_amendment_record_id must resolve to a semantic artifact"
    if (
        record.value.authority_status != "accepted"
        or record.value.semantic_role != "plan_amendment"
        or record.value.content is None
    ):
        return "plan amendment must be an accepted typed plan_amendment artifact"
    if node_kinds_view(projection).get(record.producer_node_id) != "planner" or (
        node_roles_view(projection).get(record.producer_node_id) not in {"planner", "gap_planner"}
    ):
        return "plan amendment must be produced by an authorized planner"
    amended_plan_id = record.value.content.get("amends_plan_record_id")
    amended_plan = records.get(amended_plan_id) if isinstance(amended_plan_id, str) else None
    if not isinstance(amended_plan, SemanticArtifactRecord) or (
        amended_plan.value.authority_status != "accepted"
    ):
        return "plan amendment must relate to an accepted plan artifact"
    provenance = record.value.provenance
    if amended_plan_id not in record.value.source_record_ids or (
        provenance.get("source_plan_record_id") != amended_plan_id
    ):
        return "plan amendment must preserve exact source-plan lineage and provenance"
    cited_verification_id = provenance.get("plan_verification_record_id")
    verification = (
        records.get(cited_verification_id) if isinstance(cited_verification_id, str) else None
    )
    if (
        cited_verification_id not in record.value.source_record_ids
        or not isinstance(verification, VerificationReportRecord)
        or verification.outcome != "passed"
        or amended_plan_id not in verification.evaluated_record_ids
    ):
        return "plan amendment must cite the exact passing verification of its source plan"
    raw_batches = record.value.content.get("batch_ids")
    if (
        not isinstance(raw_batches, Sequence)
        or isinstance(raw_batches, (str, bytes))
        or batch_id not in raw_batches
    ):
        return f"accepted plan amendment does not declare batch {batch_id}"
    return None


def _effectful_batch_shape_error(
    worker_id: str,
    batch_id: str,
    region_id: str,
    edges: list[dict[str, Any]],
    payloads: dict[str, dict[str, Any]],
) -> str | None:
    incoming = [edge for edge in edges if edge.get("to_node_id") == worker_id]
    if not any(
        edge.get("to_port") == "semantic_artifact"
        and _selector_field(edge, "record_type") == "semantic_artifact"
        and _selector_field(edge, "authority_status") == "accepted"
        for edge in incoming
    ):
        return f"effectful batch {batch_id} requires its accepted plan artifact"
    verification_edges = [
        edge
        for edge in incoming
        if edge.get("to_port") == "verification_report"
        and _selector_field(edge, "outcome") == "passed"
    ]
    if not verification_edges:
        return f"effectful batch {batch_id} requires accepted plan verification"
    if not all(
        payloads.get(cast(str, edge.get("from_node_id")), {}).get("semantic_stage")
        == "plan_verification"
        for edge in verification_edges
        if isinstance(edge.get("from_node_id"), str)
    ):
        return f"effectful batch {batch_id} plan verification source is not semantic"

    verifier_ids = {
        node_id
        for node_id, payload in payloads.items()
        if payload.get("kind") == "verifier"
        and payload.get("task_region_id") == region_id
        and payload.get("declared_batch_id") == batch_id
    }
    if not verifier_ids:
        return f"effectful batch {batch_id} requires an independent verifier"
    check_ids = {
        node_id
        for node_id, payload in payloads.items()
        if payload.get("kind") == "check"
        and payload.get("task_region_id") == region_id
        and payload.get("declared_batch_id") == batch_id
    }
    if not check_ids:
        return f"effectful batch {batch_id} requires deterministic checks"
    for verifier_id in verifier_ids:
        verifier_incoming = [edge for edge in edges if edge.get("to_node_id") == verifier_id]
        if not any(
            edge.get("from_node_id") == worker_id and edge.get("to_port") == "candidate_under_test"
            for edge in verifier_incoming
        ):
            return f"batch verifier {verifier_id} is not bound to its candidate"
        missing_checks = sorted(
            check_id
            for check_id in check_ids
            if not any(
                edge.get("from_node_id") == check_id
                and str(edge.get("to_port", "")).startswith("check_result")
                and _selector_accepts_terminal_check(edge)
                for edge in verifier_incoming
            )
        )
        if missing_checks:
            return f"batch verifier {verifier_id} is missing passed check evidence"
    return None


def _selector_accepts_terminal_check(edge: dict[str, Any]) -> bool:
    selector = edge.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return False
    typed_selector = cast(dict[str, Any], selector)
    statuses: set[str] = set()
    if typed_selector.get("record_type") == "check_result" and isinstance(
        typed_selector.get("status"), str
    ):
        statuses.add(cast(str, typed_selector["status"]))
    raw_selectors = typed_selector.get("selectors")
    if isinstance(raw_selectors, list):
        for raw_item in cast(list[Any], raw_selectors):
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[str, Any], raw_item)
            status = item.get("status")
            if item.get("record_type") == "check_result" and isinstance(status, str):
                statuses.add(status)
    return {"passed", "failed"}.issubset(statuses)


def _final_gate_semantic_error(
    node_id: str,
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    payloads: dict[str, dict[str, Any]],
    declared_batches: set[str],
) -> str | None:
    configured = node.get("declared_batch_ids")
    configured_ids: set[str] = (
        {item for item in cast(list[Any], configured) if isinstance(item, str)}
        if isinstance(configured, list)
        else set()
    )
    if configured_ids != declared_batches:
        return "final gate declared_batch_ids must exactly match the accepted plan"
    incoming = [edge for edge in edges if edge.get("to_node_id") == node_id]
    passed_sources = {
        cast(str, edge.get("from_node_id"))
        for edge in incoming
        if isinstance(edge.get("from_node_id"), str)
        and _selector_field(edge, "outcome") == "passed"
    }
    verified_batches = {
        cast(str, payloads[source].get("declared_batch_id"))
        for source in passed_sources
        if source in payloads
        and payloads[source].get("semantic_stage") == "effectful_batch"
        and isinstance(payloads[source].get("declared_batch_id"), str)
    }
    if verified_batches != declared_batches:
        return "final gate requires passed verification from every declared batch"
    batch_sources = {
        source
        for source in passed_sources
        if payloads.get(source, {}).get("semantic_stage") == "effectful_batch"
    }
    for source in batch_sources:
        error = _batch_verifier_topology_error(source, edges, payloads)
        if error is not None:
            return error
    audit_sources = {
        source
        for source in passed_sources
        if payloads.get(source, {}).get("semantic_stage") == "final_audit"
    }
    if not audit_sources:
        return "final gate requires a passed final independent audit"
    for audit_source in audit_sources:
        audit_incoming_sources = {
            cast(str, edge.get("from_node_id"))
            for edge in edges
            if edge.get("to_node_id") == audit_source
            and isinstance(edge.get("from_node_id"), str)
            and _selector_field(edge, "outcome") == "passed"
        }
        if not batch_sources.issubset(audit_incoming_sources):
            return "final audit must consume passed verification from every batch verifier"
    return None


def _batch_verifier_topology_error(
    verifier_id: str,
    edges: list[dict[str, Any]],
    payloads: dict[str, dict[str, Any]],
) -> str | None:
    verifier = payloads.get(verifier_id, {})
    if verifier.get("kind") != "verifier":
        return "final gate batch evidence must come from a verifier"
    batch_id = verifier.get("declared_batch_id")
    region_id = verifier.get("task_region_id")
    incoming = [edge for edge in edges if edge.get("to_node_id") == verifier_id]
    worker_sources = {
        cast(str, edge.get("from_node_id"))
        for edge in incoming
        if edge.get("to_port") == "candidate_under_test"
        and isinstance(edge.get("from_node_id"), str)
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("kind") == "worker"
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("declared_batch_id")
        == batch_id
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("task_region_id") == region_id
    }
    if not worker_sources:
        return f"batch verifier {verifier_id} lacks its bound batch worker candidate"
    check_sources = {
        cast(str, edge.get("from_node_id"))
        for edge in incoming
        if str(edge.get("to_port", "")).startswith("check_result")
        and isinstance(edge.get("from_node_id"), str)
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("kind") == "check"
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("declared_batch_id")
        == batch_id
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("task_region_id") == region_id
        and _selector_accepts_terminal_check(edge)
    }
    if not check_sources:
        return f"batch verifier {verifier_id} lacks bound deterministic check evidence"
    return None


def _accepted_declared_batch_ids(projection: GraphProjection) -> set[str]:
    batch_ids: set[str] = set()
    for record in output_record_payloads_view(projection).values():
        if not isinstance(record, SemanticArtifactRecord):
            continue
        if record.value.authority_status != "accepted" or record.value.content is None:
            continue
        raw_batches = record.value.content.get("batches")
        if not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes)):
            continue
        for raw_batch in cast(Sequence[Any], raw_batches):
            if isinstance(raw_batch, str):
                batch_ids.add(raw_batch)
            elif isinstance(raw_batch, Mapping):
                typed_batch = cast(Mapping[str, Any], raw_batch)
                batch_id = typed_batch.get("batch_id", typed_batch.get("id"))
                if isinstance(batch_id, str):
                    batch_ids.add(batch_id)
    return batch_ids


def _selector_field(edge: dict[str, Any], field: str) -> Any:
    selector = edge.get("accepted_record_selector")
    return cast(dict[str, Any], selector).get(field) if isinstance(selector, dict) else None


def _declares_semantic_artifact_output(node: dict[str, Any]) -> bool:
    return any(
        port.get("port") == "semantic_artifact" and port.get("schema") == "SemanticArtifact"
        for port in _port_dicts(node.get("outputs"))
    )


def _validate_no_poisoned_final_invariant_edges(
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> str | None:
    created_nodes = _created_nodes_by_id(ops)
    edge_ops = [op for op in ops if op.get("op") == "create_edge"]
    existing_edges = edges_view(projection).values()

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
    return node_kinds_view(projection).get(node_id), node_roles_view(projection).get(node_id)


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
    claims = list(resource_claim_dicts(op.get("resource_claims")))
    for node_key in ("node", "worker_node", "verifier_node"):
        node = op.get(node_key)
        if not isinstance(node, dict):
            continue
        authority = cast(dict[str, Any], node).get("authority")
        if isinstance(authority, dict):
            claims.extend(
                resource_claim_dicts(cast(dict[str, Any], authority).get("resource_claims"))
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

    for claim in resource_claim_dicts(op.get("resource_claims")):
        mode = claim.get("mode")
        requested_rank = MODE_RANK.get(mode) if isinstance(mode, str) else None
        if requested_rank is not None and requested_rank > existing_rank:
            return f"resource claim escalation for {node_id}: {mode}"
    return None


def _existing_resource_claim_rank(projection: GraphProjection, node_id: str) -> int | None:
    ranks = [
        rank
        for claim in resource_claim_dicts(resource_claims_for_node(projection, node_id))
        if isinstance(claim.get("mode"), str)
        for rank in [MODE_RANK.get(claim["mode"])]
        if rank is not None
    ]
    return max(ranks) if ranks else None


def resource_claim_dicts(raw_claims: Any) -> list[dict[str, Any]]:
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
