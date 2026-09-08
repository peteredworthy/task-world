"""Pure graph patch validation helpers."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import posixpath
from typing import Any, cast

from orchestrator.graph.command_bindings import (
    canonicalize_check_command_definition,
    is_known_check_command_binding,
)
from orchestrator.graph.contracts import (
    binding_policy,
    merge_bound_record_ids,
    validate_edge_payload,
    validate_node_payload,
)
from orchestrator.graph.models import (
    EdgeProjection,
    EventEnvelope,
    PatchEnvelope,
    PatchOp,
    SemanticArtifactRecord,
    VerificationReportRecord,
    normalize_record_selector,
    record_selector_matches,
)
from orchestrator.graph.projection_queries import (
    cache_authority_binding,
    cache_authority_is_new_format,
    edges_view,
    effective_active_node_ids_view,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_payload_view,
    node_roles_view,
    node_states_view,
    record_payloads_view,
    reliable_plan_successor_horizon_materialized,
    resource_claims_for_node,
    semantic_schema_declarations_view,
    output_record_payloads_view,
    output_records_by_node_port_view,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.retry_policy import (
    DEFAULT_EXECUTABLE_NODE_MAX_ATTEMPTS,
    EXECUTABLE_NODE_KINDS,
)
from orchestrator.graph.semantic_artifacts import (
    accepted_semantic_declaration,
)
from orchestrator.graph.semantic_applicability import (
    accepted_declared_batch_ids,
    classify_write_worker_semantics,
)


@dataclass(frozen=True)
class PatchValidationResult:
    accepted: bool
    rejection_reason: str | None = None
    diagnostics: dict[str, Any] | None = None
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
ROLE_REQUIRED_EXECUTABLE_NODE_KINDS = {"worker", "verifier", "check", "planner"}
PLANNER_SUCCESSOR_PORTS = {
    "region_summary",
    "accepted_file_state",
    "outstanding_failures",
    "session_carryover",
    "semantic_artifact",
    "verification_report",
}

_PATCH_NODE_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "create_node": (("node", "worker"),),
    "create_gate": (("node", "gate"),),
    "create_appeal": (("node", "appeal"),),
    "create_revision_attempt": (("worker_node", "worker"), ("verifier_node", "verifier")),
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


def normalize_patch_nodes(
    patch: PatchEnvelope,
    projection: GraphProjection,
    events: Sequence[EventEnvelope] = (),
) -> PatchEnvelope:
    """Return the canonical node representation used by validation and events.

    Patch ingress never infers a worker effect contract. Structural defaults,
    authority normalization, cache authority, and deterministic check bindings
    are applied once here for every operation capable of emitting a node.
    """
    normalized_ops: list[dict[str, Any]] = []
    for raw_op in patch.ops:
        op = raw_op.model_dump(mode="json", exclude_none=True)
        op_name = op.get("op")
        specs = _PATCH_NODE_SPECS.get(str(op_name), ())
        for node_key, default_kind in specs:
            raw_node = op.get(node_key)
            if op_name == "create_node" and not isinstance(raw_node, dict):
                continue
            default_node_id: str | None = None
            if op_name == "create_revision_attempt":
                task_region_id = op.get("task_region_id")
                region = task_region_id if isinstance(task_region_id, str) else "revision"
                default_node_id = f"{default_kind}-revision-{region}"
            op[node_key] = normalize_patch_node_payload(
                projection,
                op,
                node_key=node_key,
                default_kind=default_kind,
                default_node_id=default_node_id,
                events=events,
            )
        normalized_ops.append(op)
    return patch.model_copy(
        update={"ops": [PatchOp.model_validate(op) for op in normalized_ops]},
        deep=True,
    )


def iter_patch_node_payloads(
    ops: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    nodes: list[tuple[str, str, dict[str, Any]]] = []
    for op in ops:
        op_name = op.get("op")
        if not isinstance(op_name, str):
            continue
        for node_key, _default_kind in _PATCH_NODE_SPECS.get(op_name, ()):
            node = op.get(node_key)
            if isinstance(node, dict):
                nodes.append((op_name, node_key, cast(dict[str, Any], node)))
    return nodes


def patch_node_default_kind(op_name: str, node_key: str) -> str | None:
    """Return the structural default kind for a patch operation's node field."""
    return dict(_PATCH_NODE_SPECS.get(op_name, ())).get(node_key)


def normalize_patch_node_payload(
    projection: GraphProjection,
    op: Mapping[str, Any],
    *,
    node_key: str,
    default_kind: str,
    default_node_id: str | None = None,
    events: Sequence[EventEnvelope] = (),
) -> dict[str, Any]:
    """Normalize one patch-created node without granting missing authority."""
    raw_node = op.get(node_key)
    node = dict(cast(Mapping[str, Any], raw_node)) if isinstance(raw_node, Mapping) else {}
    node_id = node.get("node_id")
    if not isinstance(node_id, str):
        for key in ("node_id", "gate_id", "appeal_node_id", "revision_node_id"):
            value = op.get(key)
            if isinstance(value, str):
                node_id = value
                break
    node["node_id"] = node_id if isinstance(node_id, str) else (default_node_id or default_kind)
    node.setdefault("kind", default_kind)
    node.setdefault("state", "planned")
    if node["kind"] in EXECUTABLE_NODE_KINDS:
        if node.get("max_attempts") == 0:
            raise ValueError("executable node max_attempts must be at least 1")
        node.setdefault("max_attempts", DEFAULT_EXECUTABLE_NODE_MAX_ATTEMPTS)
        node.setdefault("attempt_number", 1)
    for key in (
        "task_region_id",
        "attempt_number",
        "candidate_id",
        "predecessor_node_ids",
        "appealed_node_id",
        "failed_candidate_id",
    ):
        if key in op and key not in node:
            node[key] = op[key]
    _ensure_default_node_authority(node)
    is_new_format = cache_authority_is_new_format(projection)
    projected_hash = cache_authority_binding(projection).hash
    supplied_hash = node.get("cache_authority_hash")
    if supplied_hash is not None and (not is_new_format or supplied_hash != projected_hash):
        raise ValueError("dynamic node cache_authority_hash differs from routine snapshot")
    if is_new_format:
        node["cache_authority_hash"] = projected_hash
    canonicalize_check_command_definition(node, list(events), projection=projection)
    return node


def _ensure_default_node_authority(node: dict[str, Any]) -> None:
    if node.get("kind") != "worker":
        return
    raw_authority = node.get("authority")
    authority = (
        dict(cast(Mapping[str, Any], raw_authority)) if isinstance(raw_authority, Mapping) else {}
    )
    authority.setdefault(
        "allowed_actions",
        ["submit_records", "request_clarification", "raise_appeal"],
    )
    if node.get("access_mode") == "read_only":
        existing_claims = authority.get("resource_claims")
        has_ranked_claim = any(
            isinstance(claim.get("mode"), str) and claim["mode"] in MODE_RANK
            for claim in resource_claim_dicts(existing_claims)
        )
        if not has_ranked_claim:
            claims = (
                list(cast(Sequence[Any], existing_claims))
                if isinstance(existing_claims, list)
                else []
            )
            claims.append({"mode": "read", "scope": "repo", "paths": ["."]})
            authority["resource_claims"] = claims
    elif "resource_claims" not in authority:
        authority["resource_claims"] = [{"mode": "write", "scope": "repo", "paths": ["."]}]
    node["authority"] = authority


def validate_patch(
    patch: PatchEnvelope,
    current_position: int,
    events_since_base: list[EventEnvelope],
    projection: GraphProjection,
    actor_role: str,
) -> PatchValidationResult:
    try:
        patch = normalize_patch_nodes(patch, projection, events_since_base)
    except ValueError as exc:
        return PatchValidationResult(accepted=False, rejection_reason=str(exc))
    ops = [_op_to_dict(op) for op in patch.ops]
    proposing_node = node_payload_view(projection, patch.proposed_by_node_id) or {}
    reliable_plan_proposer = isinstance(
        proposing_node.get("reliable_plan_skeleton_id"), str
    ) and isinstance(proposing_node.get("reliable_plan_assignment_carrier"), dict)

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
            retired_node = (
                node_payload_view(projection, node_id) if isinstance(node_id, str) else None
            ) or {}
            reliable_finalization_replacement = reliable_plan_proposer and retired_node.get(
                "semantic_stage"
            ) in {"final_acceptance", "final_audit", "final_gate"}
            if (
                actor_role == "gap_planner"
                and isinstance(node_id, str)
                and node_kinds_view(projection).get(node_id) in {"worker", "verifier", "check"}
                and not reliable_finalization_replacement
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
    seen_created_node_ids: set[str] = set()
    existing_node_ids = set(node_kinds_view(projection))
    for _op_name, _node_key, typed_node in iter_patch_node_payloads(ops):
        node_id = typed_node.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        if node_id in seen_created_node_ids or node_id in existing_node_ids:
            return PatchValidationResult(
                accepted=False,
                rejection_reason=f"duplicate node id: {node_id}",
            )
        seen_created_node_ids.add(node_id)
    for op_name, node_key, typed_node in iter_patch_node_payloads(ops):
        expected_kind = dict(_PATCH_NODE_SPECS[op_name])[node_key]
        kind = typed_node.get("kind")
        if op_name != "create_node" and kind != expected_kind:
            return PatchValidationResult(
                accepted=False,
                rejection_reason=f"{op_name} {node_key} must have kind {expected_kind}",
            )
        contract_error = validate_node_payload(typed_node)
        if contract_error is not None:
            return PatchValidationResult(accepted=False, rejection_reason=contract_error)
        role = typed_node.get("role")
        if actor_role == "gap_planner":
            gap_planner_error = _validate_gap_planner_node(
                typed_node,
                reliable_plan=reliable_plan_proposer,
            )
            if gap_planner_error is not None:
                return PatchValidationResult(
                    accepted=False,
                    rejection_reason=gap_planner_error,
                )
        if kind in ROLE_REQUIRED_EXECUTABLE_NODE_KINDS and not isinstance(role, str):
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

    topology_error = _validate_typed_topology(ops, projection, patch.patch_id)
    if topology_error is not None:
        reason, diagnostics = topology_error
        return PatchValidationResult(
            accepted=False,
            rejection_reason=reason,
            diagnostics=diagnostics,
        )

    cycle_error = _validate_no_forbidden_cycles(ops, projection)
    if cycle_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=cycle_error)

    poison_error = _validate_no_poisoned_final_invariant_edges(ops, projection)
    if poison_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=poison_error)

    planner_successor_error = _validate_planner_successor_bindings(ops)
    if planner_successor_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=planner_successor_error)

    dynamic_region_error = _validate_dynamic_region_dependencies(ops, actor_role, projection)
    if dynamic_region_error is not None:
        return PatchValidationResult(accepted=False, rejection_reason=dynamic_region_error)

    semantic_stage_error = _validate_semantic_stage_invariants(
        ops,
        projection,
        actor_role,
        proposed_by_node_id=patch.proposed_by_node_id,
    )
    if semantic_stage_error is not None:
        return PatchValidationResult(
            accepted=False,
            rejection_reason=semantic_stage_error,
            diagnostics=_semantic_stage_diagnostics(patch.patch_id, ops, projection),
        )

    reliable_plan_error = _validate_reliable_plan_topology(patch, ops, projection)
    if reliable_plan_error is not None:
        reason, diagnostics = reliable_plan_error
        return PatchValidationResult(
            accepted=False,
            rejection_reason=reason,
            diagnostics=diagnostics,
        )

    return PatchValidationResult(accepted=True)


def _validate_typed_topology(
    ops: list[dict[str, Any]],
    projection: GraphProjection,
    patch_id: str,
) -> tuple[str, dict[str, Any] | None] | None:
    created_nodes: dict[str, tuple[str, str | None]] = {}
    seen_node_ids: set[str] = set()
    seen_edge_ids: set[str] = set()

    for op in ops:
        op_name = op.get("op")
        if op_name == "create_node" and not isinstance(op.get("node"), dict):
            return "create_node requires node payload", None
        if op_name == "create_edge":
            edge_id = op.get("edge_id")
            if not isinstance(edge_id, str) or not edge_id:
                return "create_edge requires edge_id", None
            if edge_id in seen_edge_ids or edge_id in edges_view(projection):
                return f"duplicate edge id: {edge_id}", None
            seen_edge_ids.add(edge_id)

    for op_name, node_key, node in iter_patch_node_payloads(ops):
        duplicate_error = _register_created_node(
            node,
            created_nodes,
            seen_node_ids,
            projection,
            missing_message=f"{op_name} {node_key} requires node_id",
        )
        if duplicate_error is not None:
            return duplicate_error, None

    for op in ops:
        if op.get("op") != "create_edge":
            continue
        edge = op
        edge_id = edge.get("edge_id")
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        if not isinstance(edge_id, str) or not edge_id:
            return "create_edge requires edge_id", None
        if not isinstance(from_node_id, str) or not from_node_id:
            return f"edge {edge_id} requires from_node_id", None
        if not isinstance(to_node_id, str) or not to_node_id:
            return f"edge {edge_id} requires to_node_id", None

        if from_node_id == "*":
            source = _producer_class_contract_identity(edge)
            if source is None:
                return f"edge {edge_id} producer-class source requires from_node_kind", None
            source_payload = None
        else:
            source = _node_contract_identity(from_node_id, created_nodes, projection)
            if source is None:
                suggestions = _known_record_producers_for_edge(edge, projection)
                suffix = (
                    f"; known matching producers: [{', '.join(suggestions)}]" if suggestions else ""
                )
                return (
                    f"edge {edge_id} references unknown source node: {from_node_id}{suffix}",
                    None,
                )
            source_payload = _concrete_node_payload(from_node_id, ops, projection)
        target = _node_contract_identity(to_node_id, created_nodes, projection)
        if target is None:
            return f"edge {edge_id} references unknown target node: {to_node_id}", None
        target_payload = _concrete_node_payload(to_node_id, ops, projection)

        concrete_port_error = _concrete_declared_port_error(
            patch_id=patch_id,
            edge=edge,
            source_node_id=from_node_id,
            source_payload=source_payload,
            source_port=edge.get("from_port"),
            target_node_id=to_node_id,
            target_payload=target_payload,
            target_port=edge.get("to_port"),
        )
        if concrete_port_error is not None:
            return concrete_port_error

        contract_error = validate_edge_payload(
            edge,
            source_kind=source[0],
            source_role=source[1],
            target_kind=target[0],
            target_role=target[1],
        )
        if contract_error is not None:
            return contract_error, _edge_diagnostics(
                patch_id,
                "edge_schema_or_port_contract",
                edge,
                source_payload,
                target_payload,
            )

    return None


def _edge_diagnostics(
    patch_id: str,
    invariant: str,
    edge: dict[str, Any],
    source_payload: dict[str, Any] | None,
    target_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Render stable, actionable topology facts without parsing error text."""
    facts = _edge_schema_facts(edge, source_payload, target_payload)
    return {
        "patch_id": patch_id,
        "invariant": invariant,
        "edge_id": edge.get("edge_id"),
        "source_node_id": edge.get("from_node_id"),
        "source_port": edge.get("from_port"),
        "target_node_id": edge.get("to_node_id"),
        "target_port": edge.get("to_port"),
        **facts,
        "source_ports": _declared_port_diagnostics(source_payload, "outputs"),
        "target_ports": _declared_port_diagnostics(target_payload, "inputs"),
    }


def _known_record_producers_for_edge(
    edge: dict[str, Any],
    projection: GraphProjection,
) -> list[str]:
    source_port = edge.get("from_port")
    selector = edge.get("accepted_record_selector")
    typed_selector = cast(dict[str, Any], selector) if isinstance(selector, dict) else {}
    expected_schema = typed_selector.get("schema")
    expected_record_type = typed_selector.get("record_type")
    producers: set[str] = set()
    for record in record_payloads_view(projection).values():
        record_port = record.get("producer_port") or record.get("port")
        if isinstance(source_port, str) and record_port != source_port:
            continue
        if isinstance(expected_schema, str) and record.get("schema") != expected_schema:
            continue
        if (
            isinstance(expected_record_type, str)
            and record.get("record_type") != expected_record_type
        ):
            continue
        producer_node_id = record.get("producer_node_id")
        if isinstance(producer_node_id, str):
            producers.add(producer_node_id)
    return sorted(producers)


def _edge_schema_facts(
    edge: dict[str, Any],
    source_payload: dict[str, Any] | None,
    target_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return stable schema facts shared by every typed edge rejection."""
    requested = {item for item in cast(list[Any], edge.get("schemas", [])) if isinstance(item, str)}
    selector = edge.get("accepted_record_selector")
    if isinstance(selector, dict):
        selector_schema = cast(dict[str, Any], selector).get("schema")
        if isinstance(selector_schema, str):
            requested.add(selector_schema)
    source_declared = _schemas_for_declared_port(source_payload, "outputs", edge.get("from_port"))
    target_declared = _schemas_for_declared_port(target_payload, "inputs", edge.get("to_port"))
    accepted = requested & source_declared & target_declared
    declared = source_declared | target_declared
    return {
        # ``edge_schemas`` is retained for read-model compatibility while the
        # named facts make failures actionable without parsing prose.
        "edge_schemas": sorted(requested),
        "requested_schemas": sorted(requested),
        "declared_source_schemas": sorted(source_declared),
        "declared_target_schemas": sorted(target_declared),
        "declared_schemas": sorted(declared),
        "accepted_schemas": sorted(accepted),
        "missing_schemas": sorted(requested - declared),
        "incompatible_schemas": sorted(requested - accepted),
    }


def _schemas_for_declared_port(
    payload: dict[str, Any] | None,
    field_name: str,
    port: Any,
) -> set[str]:
    if payload is None or not isinstance(port, str):
        return set()
    raw_ports = payload.get(field_name)
    if not isinstance(raw_ports, list):
        return set()
    schemas: set[str] = set()
    for raw in cast(list[Any], raw_ports):
        if not isinstance(raw, dict):
            continue
        item = cast(dict[str, Any], raw)
        if item.get("port") != port:
            continue
        schema = item.get("schema")
        if isinstance(schema, str):
            schemas.add(schema)
        raw_schemas = item.get("schemas")
        if isinstance(raw_schemas, list):
            schemas.update(
                value for value in cast(list[Any], raw_schemas) if isinstance(value, str)
            )
    return schemas


def _declared_port_diagnostics(
    payload: dict[str, Any] | None,
    field_name: str,
) -> list[dict[str, Any]]:
    if payload is None or not isinstance(payload.get(field_name), list):
        return []
    return [
        {
            "port": item.get("port"),
            "schema": item.get("schema"),
            "schemas": item.get("schemas"),
            "required": item.get("required"),
        }
        for raw in cast(list[Any], payload[field_name])
        if isinstance(raw, dict)
        for item in [cast(dict[str, Any], raw)]
    ]


def _concrete_node_payload(
    node_id: str,
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> dict[str, Any] | None:
    for _op_name, _node_key, node in iter_patch_node_payloads(ops):
        if node.get("node_id") == node_id:
            return node
    return node_payload_view(projection, node_id)


def _concrete_declared_port_error(
    *,
    patch_id: str,
    edge: dict[str, Any],
    source_node_id: str,
    source_payload: dict[str, Any] | None,
    source_port: Any,
    target_node_id: str,
    target_payload: dict[str, Any] | None,
    target_port: Any,
) -> tuple[str, dict[str, Any]] | None:
    edge_id = cast(str, edge["edge_id"])
    for node_id, payload, field_name, port, direction in (
        (source_node_id, source_payload, "outputs", source_port, "source"),
        (target_node_id, target_payload, "inputs", target_port, "target"),
    ):
        if payload is None:
            continue
        raw_ports = payload.get(field_name)
        if not isinstance(raw_ports, list):
            continue
        declared_names: set[str] = set()
        for item in cast(list[Any], raw_ports):
            if not isinstance(item, dict):
                continue
            typed_item = cast(dict[str, Any], item)
            declared_port = typed_item.get("port")
            if isinstance(declared_port, str):
                declared_names.add(declared_port)
        declared = sorted(declared_names)
        if isinstance(port, str) and port in declared:
            continue
        diagnostics = {
            "patch_id": patch_id,
            "invariant": "edge_concrete_declared_port",
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "source_port": source_port,
            "target_node_id": target_node_id,
            "target_port": target_port,
            "node_id": node_id,
            "direction": direction,
            "port": port,
            "declared_ports": declared,
            **_edge_schema_facts(edge, source_payload, target_payload),
        }
        return (
            f"patch {patch_id} edge {edge_id} references nonexistent concrete "
            f"{direction} port {node_id}.{port}; declared ports: {', '.join(declared) or '<none>'}",
            diagnostics,
        )
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


def _validate_gap_planner_node(node: dict[str, Any], *, reliable_plan: bool = False) -> str | None:
    kind = node.get("kind")
    if kind == "planner":
        if reliable_plan and (
            (node.get("role") == "planner" and node.get("semantic_stage") == "successor_planning")
            or node.get("role") == "gap_planner"
        ):
            # Reliable-plan topology validation below constrains both planner
            # forms to the exact controller-completed continuation count.  A
            # corrective patch needs its passed-evidence successor and its
            # failed-evidence recovery branch in the same atomic patch.
            return None
        return "gap planner cannot create planner successor"
    reliable_corrective_or_finalization = reliable_plan and node.get("semantic_stage") in {
        "corrective_work",
        "final_acceptance",
        "final_audit",
    }
    if kind in {"worker", "verifier", "check"} and not (
        node.get("task_region_id") == "corrective_work_region"
        or reliable_corrective_or_finalization
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

    effect_contract = node.get("effect_contract")
    if effect_contract not in ("read_only_semantic", "effectful_write"):
        return f"worker node requires a valid effect_contract: {node_id}"
    expected_effect_contract = (
        "read_only_semantic" if access_mode == "read_only" else "effectful_write"
    )
    if effect_contract != expected_effect_contract:
        return f"worker node effect_contract conflicts with access_mode: {node_id}"

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
    hidden_oracle_command = node.get("hidden_oracle_command")
    if isinstance(hidden_oracle_command, str) and hidden_oracle_command.strip():
        if actor_role in {"planner", "gap_planner"}:
            node_id = node.get("node_id")
            if isinstance(node_id, str):
                return f"check node cannot expose hidden_oracle_command; use command_binding: {node_id}"
            return "check node cannot expose hidden_oracle_command; use command_binding"
        return None

    command_definition = node.get("command_definition")
    if isinstance(command_definition, dict):
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
    for _op_name, _node_key, typed_node in iter_patch_node_payloads(ops):
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
    projection: GraphProjection,
) -> str | None:
    created_nodes = _created_nodes_by_id(ops)

    if not created_nodes:
        return None

    incoming_ports = _required_incoming_ports_by_node(ops, set(created_nodes))
    all_edges = [edge.model_dump(mode="json") for edge in edges_view(projection).values()]
    all_edges.extend(op for op in ops if op.get("op") == "create_edge")
    for node_id, node in created_nodes.items():
        kind = node.get("kind")
        role = node.get("role")
        ports = incoming_ports.get(node_id, set())
        write_applicability = classify_write_worker_semantics(
            node_id,
            node,
            projection,
            edges=all_edges,
            nodes=created_nodes,
        )
        exact_correction = write_applicability in {
            "semantic_plan_revision",
            "declared_batch_correction",
        }
        if (
            kind == "planner"
            and role == "gap_planner"
            and ports.isdisjoint({"verification_evidence", "verification_report"})
        ):
            return "gap planner requires verification input edge"
        if (
            actor_role not in {"gap_planner", "human"}
            and _is_corrective_worker(node_id, node)
            and not exact_correction
            and "classified_gap" not in ports
        ):
            return "corrective worker requires classified_gap input edge"
        if (
            actor_role != "human"
            and kind == "worker"
            and node.get("semantic_stage") == "corrective_work"
            and not exact_correction
        ):
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
    actor_role: str,
    *,
    proposed_by_node_id: str,
) -> str | None:
    """Enforce reliable-plan semantics on staged nodes, not merely prompts."""
    created = _created_nodes_by_id(ops)
    edge_ops = [op for op in ops if op.get("op") == "create_edge"]
    declared_batches = accepted_declared_batch_ids(projection)
    known_payloads = {
        node_id: payload
        for node_id in node_kinds_view(projection)
        if (payload := node_payload_view(projection, node_id)) is not None
    }
    retired_node_ids = {
        cast(str, op["node_id"])
        for op in ops
        if op.get("op") == "retire_node" and isinstance(op.get("node_id"), str)
    }
    active_existing_ids = set(
        effective_active_node_ids_view(
            projection,
            additionally_retired_node_ids=tuple(sorted(retired_node_ids)),
        )
    )
    active_node_ids = active_existing_ids | set(created)
    known_payloads = {
        node_id: payload
        for node_id, payload in known_payloads.items()
        if node_id in active_existing_ids
    }
    all_payloads = {**known_payloads, **created}
    all_edges = [
        edge.model_dump(mode="json")
        for edge in edges_view(projection).values()
        if edge.from_node_id in active_node_ids and edge.to_node_id in active_node_ids
    ]
    all_edges.extend(
        edge
        for edge in edge_ops
        if edge.get("from_node_id") in active_node_ids and edge.get("to_node_id") in active_node_ids
    )
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
        write_applicability = classify_write_worker_semantics(
            node_id,
            node,
            projection,
            # A newly created correction cites immutable records through
            # patch-local edges even when their producer nodes are retired in
            # this same replacement.  Active-topology filtering must not erase
            # that historical provenance while classifying the new worker.
            edges=edge_ops,
            nodes=created,
        )
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

        if (
            actor_role != "human"
            and kind == "worker"
            and stage == "corrective_work"
            and write_applicability not in {"semantic_plan_revision", "declared_batch_correction"}
        ):
            correction_error = _corrective_evidence_error(
                node_id,
                node,
                edge_ops,
                projection,
                proposed_by_node_id=proposed_by_node_id,
            )
            if correction_error is not None:
                return correction_error

        if (
            kind == "worker"
            and stage == "corrective_work"
            and write_applicability == "semantic_plan_revision"
            and not _declares_required_semantic_artifact_output(node)
        ):
            return "semantic plan revision must declare a required semantic_artifact output"

        if kind == "worker" and node.get("access_mode") == "write" and declared_batches:
            if write_applicability == "invalid_declared_batch_write":
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
            if node.get("kind") == "final_gate" and node_id not in retired_node_ids
        }
        for node_id, node in final_gates.items():
            error = _final_gate_semantic_error(
                node_id, node, all_edges, all_payloads, declared_batches
            )
            if error is not None:
                return error
    return None


def _validate_reliable_plan_topology(
    patch: PatchEnvelope,
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> tuple[str, dict[str, Any]] | None:
    parent = node_payload_view(projection, patch.proposed_by_node_id) or {}
    skeleton_id = parent.get("reliable_plan_skeleton_id")
    if not isinstance(skeleton_id, str):
        return None

    created = _created_nodes_by_id(ops)
    edges = [op for op in ops if op.get("op") == "create_edge"]
    edge_facts = [
        {
            "edge_id": edge.get("edge_id"),
            "source_node_id": edge.get("from_node_id"),
            "source_port": edge.get("from_port"),
            "target_node_id": edge.get("to_node_id"),
            "target_port": edge.get("to_port"),
            **_edge_schema_facts(
                edge,
                _concrete_node_payload(str(edge.get("from_node_id")), ops, projection),
                _concrete_node_payload(str(edge.get("to_node_id")), ops, projection),
            ),
        }
        for edge in edges
    ]
    requested_semantic_schemas = {
        f"{node.get('semantic_schema_id')}@{node.get('semantic_schema_version')}"
        for node in created.values()
        if isinstance(node.get("semantic_schema_id"), str)
        and isinstance(node.get("semantic_schema_version"), int)
    }
    accepted_semantic_schemas = {
        f"{schema_id}@{version}"
        for schema_id, version in semantic_schema_declarations_view(projection)
    }
    single_edge = edge_facts[0] if len(edge_facts) == 1 else {}
    diagnostics: dict[str, Any] = {
        "patch_id": patch.patch_id,
        "invariant": "reliable_plan_verified_topology",
        "proposed_by_node_id": patch.proposed_by_node_id,
        "reliable_plan_skeleton_id": skeleton_id,
        "created_node_ids": sorted(created),
        "source_node_id": single_edge.get("source_node_id"),
        "source_port": single_edge.get("source_port"),
        "target_node_id": single_edge.get("target_node_id"),
        "target_port": single_edge.get("target_port"),
        "edge_facts": edge_facts,
        "requested_schemas": sorted(requested_semantic_schemas),
        "declared_schemas": sorted(accepted_semantic_schemas),
        "accepted_schemas": sorted(requested_semantic_schemas & accepted_semantic_schemas),
        "missing_schemas": sorted(requested_semantic_schemas - accepted_semantic_schemas),
        "incompatible_schemas": [],
    }

    if parent.get("semantic_stage") == "successor_planning" and not (
        reliable_plan_successor_horizon_materialized(projection, patch.proposed_by_node_id)
    ):
        remaining = parent.get("reliable_plan_remaining_horizons")
        horizon_workers = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "worker" and node.get("semantic_stage") == "effectful_batch"
        }
        successor_planners = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "planner"
            and node.get("role") == "planner"
            and node.get("semantic_stage") == "successor_planning"
        }
        final_acceptance_checks = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "check"
            and node.get("semantic_stage") == "final_acceptance"
            and node.get("command_binding") == "dynamic_feature_acceptance"
        }
        final_audits = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "verifier" and node.get("semantic_stage") == "final_audit"
        }
        final_gates = {
            node_id for node_id, node in created.items() if node.get("kind") == "final_gate"
        }
        recovery_planners = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "planner" and node.get("role") == "gap_planner"
        }
        diagnostics.update(
            {
                "horizon_worker_ids": sorted(horizon_workers),
                "successor_planner_ids": sorted(successor_planners),
                "final_acceptance_check_ids": sorted(final_acceptance_checks),
                "final_audit_ids": sorted(final_audits),
                "final_gate_ids": sorted(final_gates),
                "recovery_planner_ids": sorted(recovery_planners),
            }
        )
        if len(horizon_workers) != 1:
            return (
                f"patch {patch.patch_id} reliable-plan horizon must atomically create exactly "
                "one complete effectful batch region",
                {**diagnostics, "violation": "incomplete_reliable_plan_horizon"},
            )
        if isinstance(remaining, int) and not isinstance(remaining, bool) and remaining > 1:
            if (
                len(successor_planners) != 1
                or len(recovery_planners) != 1
                or final_acceptance_checks
                or final_audits
                or final_gates
            ):
                return (
                    f"patch {patch.patch_id} nonfinal reliable-plan horizon must atomically "
                    "create its batch and exactly one successor planner",
                    {**diagnostics, "violation": "incomplete_reliable_plan_horizon"},
                )
        elif remaining == 1:
            if (
                successor_planners
                or len(recovery_planners) != 3
                or len(final_acceptance_checks) != 1
                or len(final_audits) != 1
                or len(final_gates) != 1
            ):
                return (
                    f"patch {patch.patch_id} final reliable-plan horizon must atomically create "
                    "its batch, dynamic acceptance check, final audit, and final gate",
                    {**diagnostics, "violation": "incomplete_reliable_plan_final_horizon"},
                )
        else:
            return (
                f"patch {patch.patch_id} reliable-plan horizon has invalid remaining authority",
                {**diagnostics, "violation": "invalid_successor_horizon"},
            )

    if parent.get("role") == "gap_planner":
        corrective_workers = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "worker" and node.get("semantic_stage") == "corrective_work"
        }
        successor_planners = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "planner"
            and node.get("role") == "planner"
            and node.get("semantic_stage") == "successor_planning"
        }
        final_acceptance_checks = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "check"
            and node.get("semantic_stage") == "final_acceptance"
            and node.get("command_binding") == "dynamic_feature_acceptance"
        }
        final_audits = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "verifier" and node.get("semantic_stage") == "final_audit"
        }
        final_gates = {
            node_id for node_id, node in created.items() if node.get("kind") == "final_gate"
        }
        recovery_planners = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "planner" and node.get("role") == "gap_planner"
        }
        if corrective_workers:
            nonfinal_complete = (
                len(successor_planners) == 1
                and not final_acceptance_checks
                and not final_audits
                and not final_gates
                and len(recovery_planners) == 1
            )
            final_complete = (
                not successor_planners
                and len(final_acceptance_checks) == 1
                and len(final_audits) == 1
                and len(final_gates) == 1
                and len(recovery_planners) == 3
            )
            if len(corrective_workers) != 1 or not (nonfinal_complete or final_complete):
                return (
                    f"patch {patch.patch_id} reliable-plan correction requires exactly one "
                    "corrective worker with complete success and failure continuations",
                    {**diagnostics, "violation": "invalid_reliable_plan_correction"},
                )
            return None

    if (
        parent.get("reliable_plan_one_horizon_authorized") is True
        and parent.get("semantic_stage") != "successor_planning"
    ):
        discovery_ids = {
            node_id
            for node_id, node in created.items()
            if node.get("semantic_stage") == "discovery"
        }
        verifier_ids = {
            node_id
            for node_id, node in created.items()
            if node.get("semantic_stage") == "plan_verification"
        }
        successor_ids = {
            node_id
            for node_id, node in created.items()
            if node.get("semantic_stage") == "successor_planning"
        }
        recovery_ids = {
            node_id
            for node_id, node in created.items()
            if node.get("kind") == "planner" and node.get("role") == "gap_planner"
        }
        diagnostics.update(
            {
                "discovery_node_ids": sorted(discovery_ids),
                "plan_verifier_node_ids": sorted(verifier_ids),
                "successor_node_ids": sorted(successor_ids),
                "recovery_node_ids": sorted(recovery_ids),
            }
        )
        expected_executable_ids = discovery_ids | verifier_ids | successor_ids | recovery_ids
        dispatchable_ids = {
            node_id
            for node_id, node in created.items()
            if node.get("state", "planned") not in {"completed", "cancelled", "failed", "retired"}
        }
        diagnostics.update(
            {
                "executable_node_ids": sorted(dispatchable_ids),
                "expected_executable_node_ids": sorted(expected_executable_ids),
            }
        )
        if any(node.get("semantic_stage") == "effectful_batch" for node in created.values()):
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton cannot create "
                "effectful work before passed plan verification",
                {**diagnostics, "violation": "preverification_effectful_work"},
            )
        if len(discovery_ids) != 1:
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton requires exactly one "
                "analysis-only discovery node",
                {**diagnostics, "violation": "missing_or_ambiguous_discovery"},
            )
        if len(verifier_ids) != 1:
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton requires exactly one "
                "independent plan verifier",
                {**diagnostics, "violation": "missing_or_ambiguous_plan_verifier"},
            )
        if len(successor_ids) != 1:
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton requires exactly one "
                "successor planner",
                {**diagnostics, "violation": "missing_or_ambiguous_successor"},
            )
        if len(recovery_ids) != 1:
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton requires exactly one "
                "failed-plan recovery planner",
                {**diagnostics, "violation": "missing_or_ambiguous_plan_recovery"},
            )
        if dispatchable_ids != expected_executable_ids:
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton executable set must "
                "contain only discovery, independent plan verifier, successor, and recovery "
                "planner",
                {
                    **diagnostics,
                    "violation": "unexpected_initial_executable_nodes",
                    "unexpected_executable_node_ids": sorted(
                        dispatchable_ids - expected_executable_ids
                    ),
                },
            )

        discovery_id = next(iter(discovery_ids))
        verifier_id = next(iter(verifier_ids))
        successor_id = next(iter(successor_ids))
        contract_error = _reliable_plan_initial_contract_error(
            discovery_id=discovery_id,
            discovery=created[discovery_id],
            verifier_id=verifier_id,
            verifier=created[verifier_id],
            successor_id=successor_id,
            successor=created[successor_id],
        )
        if contract_error is not None:
            violation, detail = contract_error
            return (
                f"patch {patch.patch_id} reliable-plan initial skeleton has invalid {detail}",
                {**diagnostics, "violation": violation, "contract_error": detail},
            )
        discovery_requirement_edges = [
            edge
            for edge in edges
            if edge.get("to_node_id") == discovery_id
            and str(edge.get("to_port", "")).startswith("requirement_")
            and edge.get("required") is not False
        ]
        verifier_requirement_edges = [
            edge
            for edge in edges
            if edge.get("to_node_id") == verifier_id
            and str(edge.get("to_port", "")).startswith("requirement_")
            and edge.get("required") is not False
        ]
        if not discovery_requirement_edges or not verifier_requirement_edges:
            return (
                f"patch {patch.patch_id} reliable-plan discovery and plan verifier must both "
                "bind required requirement evidence",
                {**diagnostics, "violation": "missing_requirement_bindings"},
            )
        if not any(
            edge.get("from_node_id") == discovery_id
            and edge.get("from_port") == "semantic_artifact"
            and edge.get("to_node_id") == verifier_id
            and edge.get("to_port") == "semantic_artifact"
            for edge in edges
        ):
            return (
                f"patch {patch.patch_id} plan verifier must consume the exact discovery "
                "semantic_artifact",
                {**diagnostics, "violation": "unbound_discovery_plan"},
            )
        successor_edges = [
            edge
            for edge in edges
            if edge.get("from_node_id") == verifier_id
            and edge.get("from_port") == "verification_report"
            and edge.get("to_node_id") == successor_id
            and edge.get("to_port") == "verification_report"
        ]
        if len(successor_edges) != 1 or _selector_field(successor_edges[0], "outcome") != "passed":
            return (
                f"patch {patch.patch_id} successor planner must be bound to the independent "
                "plan verifier's passed verification_report",
                {**diagnostics, "violation": "successor_not_pass_gated"},
            )
        recovery_id = next(iter(recovery_ids))
        recovery_edges = [
            edge
            for edge in edges
            if edge.get("from_node_id") == verifier_id
            and edge.get("from_port") == "verification_report"
            and edge.get("to_node_id") == recovery_id
            and edge.get("to_port") == "verification_evidence"
        ]
        recovery_selector = (
            cast(dict[str, Any], recovery_edges[0].get("accepted_record_selector"))
            if len(recovery_edges) == 1
            and isinstance(recovery_edges[0].get("accepted_record_selector"), dict)
            else {}
        )
        recovery_options = recovery_selector.get("selectors")
        typed_recovery_options = (
            cast(list[Any], recovery_options) if isinstance(recovery_options, list) else []
        )
        recovery_is_failed_report = False
        for raw_option in typed_recovery_options:
            if not isinstance(raw_option, dict):
                continue
            option = cast(dict[str, Any], raw_option)
            if (
                option.get("record_type") == "verification_report"
                and option.get("outcome") == "failed"
            ):
                recovery_is_failed_report = True
                break
        if len(recovery_edges) != 1 or not recovery_is_failed_report:
            return (
                f"patch {patch.patch_id} recovery planner must be bound to the independent "
                "plan verifier's failed verification_report",
                {**diagnostics, "violation": "plan_recovery_not_failure_gated"},
            )
        return None

    effectful_ids = {
        node_id
        for node_id, node in created.items()
        if node.get("semantic_stage") == "effectful_batch" and node.get("kind") == "worker"
    }
    if not effectful_ids:
        if parent.get("semantic_stage") == "successor_planning" and any(
            node.get("kind") == "planner" and node.get("role") == "planner"
            for node in created.values()
        ):
            return _validate_materialized_horizon_successor(
                patch=patch,
                created=created,
                edges=edges,
                projection=projection,
                diagnostics=diagnostics,
            )
        return None
    diagnostics["effectful_node_ids"] = sorted(effectful_ids)
    if len(effectful_ids) != 1:
        return (
            f"patch {patch.patch_id} reliable-plan sequential profile requires exactly one "
            "effectful batch per horizon",
            {**diagnostics, "violation": "non_sequential_effectful_horizon"},
        )
    if parent.get("semantic_stage") != "successor_planning":
        return (
            f"patch {patch.patch_id} effectful batch may only be proposed by the verified-plan "
            "successor planner",
            {**diagnostics, "violation": "unauthorized_effectful_proposer"},
        )
    parent_horizon = parent.get("planning_horizon")
    effectful_horizon = created[next(iter(effectful_ids))].get("planning_horizon")
    if isinstance(parent_horizon, int) and effectful_horizon != parent_horizon:
        return (
            f"patch {patch.patch_id} effectful batch horizon must match its proposing "
            "successor planner",
            {
                **diagnostics,
                "violation": "non_sequential_effectful_horizon",
                "proposer_horizon": parent_horizon,
                "effectful_horizon": effectful_horizon,
            },
        )
    verification_binding = (
        input_bindings_view(projection)
        .get(patch.proposed_by_node_id, {})
        .get("verification_report")
    )
    record_ids = verification_binding.record_ids if verification_binding is not None else []
    records = record_payloads_view(projection)
    passed_reports = [
        record_id
        for record_id in record_ids
        if (record := records.get(record_id)) is not None
        and record.get("record_type") == "verification_report"
        and (
            record.get("outcome") == "passed"
            or (
                isinstance(record.get("value"), dict)
                and cast(dict[str, Any], record["value"]).get("outcome") == "passed"
            )
        )
    ]
    if not passed_reports:
        return (
            f"patch {patch.patch_id} effectful batch requires a durably bound passed "
            "verification_report on successor {patch.proposed_by_node_id}",
            {
                **diagnostics,
                "violation": "missing_bound_passed_verification",
                "bound_verification_record_ids": record_ids,
            },
        )
    parent_horizon = parent.get("planning_horizon")
    if isinstance(parent_horizon, int) and parent_horizon > 1:
        typed_records = output_record_payloads_view(projection)
        predecessor_reports = [
            record_id
            for record_id in passed_reports
            if isinstance((record := typed_records.get(record_id)), VerificationReportRecord)
            and (producer := node_payload_view(projection, record.producer_node_id)) is not None
            and producer.get("semantic_stage") in {"effectful_batch", "corrective_work"}
            and producer.get("planning_horizon") == parent_horizon - 1
        ]
        if not predecessor_reports:
            return (
                f"patch {patch.patch_id} successor horizon requires accepted evidence from "
                "the immediately preceding effectful horizon",
                {
                    **diagnostics,
                    "violation": "missing_sequential_predecessor_evidence",
                    "proposer_horizon": parent_horizon,
                    "bound_verification_record_ids": record_ids,
                },
            )
    plan_edges = [
        edge
        for edge in edges
        if edge.get("to_node_id") in effectful_ids and edge.get("to_port") == "semantic_artifact"
    ]
    verification_edges = [
        edge
        for edge in edges
        if edge.get("to_node_id") in effectful_ids and edge.get("to_port") == "verification_report"
    ]
    effective_plan_record_ids: list[str] = []
    effective_report_ids: list[str] = []
    lineage_verified_report_ids: list[str] = []
    typed_records = output_record_payloads_view(projection)
    for effectful_id in sorted(effectful_ids):
        node_plan_edges = [edge for edge in plan_edges if edge.get("to_node_id") == effectful_id]
        node_verification_edges = [
            edge for edge in verification_edges if edge.get("to_node_id") == effectful_id
        ]
        if len(node_plan_edges) != 1 or len(node_verification_edges) != 1:
            continue
        effective_plans = _effective_edge_backfill_record_ids(projection, node_plan_edges[0])
        effective_reports = _effective_edge_backfill_record_ids(
            projection, node_verification_edges[0]
        )
        effective_plan_record_ids.extend(effective_plans)
        effective_report_ids.extend(effective_reports)
        if len(effective_plans) != 1 or len(effective_reports) != 1:
            continue
        plan_record_id = effective_plans[0]
        report_record_id = effective_reports[0]
        plan = typed_records.get(plan_record_id)
        report = typed_records.get(report_record_id)
        if (
            isinstance(plan, SemanticArtifactRecord)
            and plan.value.authority_status == "accepted"
            and isinstance(report, VerificationReportRecord)
            and report.outcome == "passed"
            and plan_record_id in report.evaluated_record_ids
        ):
            lineage_verified_report_ids.append(report_record_id)
    diagnostics.update(
        {
            "bound_verification_record_ids": sorted(record_ids),
            "accepted_plan_record_ids": effective_plan_record_ids,
            "effective_plan_record_ids": effective_plan_record_ids,
            "effective_verification_record_ids": effective_report_ids,
            "lineage_verified_report_ids": lineage_verified_report_ids,
            "plan_source_ports": sorted(
                {f"{edge.get('from_node_id')}.{edge.get('from_port')}" for edge in plan_edges}
            ),
            "verification_source_ports": sorted(
                {
                    f"{edge.get('from_node_id')}.{edge.get('from_port')}"
                    for edge in verification_edges
                }
            ),
        }
    )
    if (not isinstance(parent_horizon, int) or parent_horizon <= 1) and not set(
        lineage_verified_report_ids
    ).intersection(passed_reports):
        return (
            f"patch {patch.patch_id} first effectful horizon must consume the exact plan "
            "verification bound to its successor planner",
            {**diagnostics, "violation": "unverified_exact_plan_lineage"},
        )
    if (
        len(effective_plan_record_ids) != len(effectful_ids)
        or len(effective_report_ids) != len(effectful_ids)
        or len(lineage_verified_report_ids) != len(effectful_ids)
    ):
        return (
            f"patch {patch.patch_id} effectful batch requires a bound passing verification "
            "report that evaluated the exact accepted plan artifact used by the batch",
            {**diagnostics, "violation": "unverified_exact_plan_lineage"},
        )
    return _validate_materialized_horizon_successor(
        patch=patch,
        created=created,
        edges=edges,
        projection=projection,
        diagnostics=diagnostics,
    )


def _validate_materialized_horizon_successor(
    *,
    patch: PatchEnvelope,
    created: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    projection: GraphProjection,
    diagnostics: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Validate a successor created with or after its bounded batch topology."""
    created_successors = {
        node_id: node
        for node_id, node in created.items()
        if node.get("kind") == "planner"
        and node.get("role") == "planner"
        and node.get("semantic_stage") == "successor_planning"
    }
    if not created_successors:
        return None

    parent = node_payload_view(projection, patch.proposed_by_node_id) or {}
    parent_horizon = parent.get("planning_horizon")
    if not isinstance(parent_horizon, int):
        return (
            f"patch {patch.patch_id} reliable-plan successor proposer requires a planning horizon",
            {**diagnostics, "violation": "invalid_successor_horizon"},
        )

    known_payloads = {
        node_id: payload
        for node_id in node_kinds_view(projection)
        if (payload := node_payload_view(projection, node_id)) is not None
    }
    all_payloads = {**known_payloads, **created}
    horizon_workers = {
        node_id: node
        for node_id, node in all_payloads.items()
        if node.get("kind") == "worker"
        and node.get("semantic_stage") == "effectful_batch"
        and node.get("planning_horizon") == parent_horizon
    }
    if len(horizon_workers) != 1:
        return (
            f"patch {patch.patch_id} reliable-plan successor cannot advance without "
            "exactly one materialized bounded effectful batch",
            {
                **diagnostics,
                "violation": "empty_sequential_horizon",
                "materialized_effectful_node_ids": sorted(horizon_workers),
                "proposer_horizon": parent_horizon,
            },
        )

    batch_worker = next(iter(horizon_workers.values()))
    batch_id = batch_worker.get("declared_batch_id")
    region_id = batch_worker.get("task_region_id")
    batch_verifiers = {
        node_id
        for node_id, node in all_payloads.items()
        if node.get("kind") == "verifier"
        and node.get("semantic_stage") == "effectful_batch"
        and node.get("planning_horizon") == parent_horizon
        and node.get("declared_batch_id") == batch_id
        and node.get("task_region_id") == region_id
    }
    expected_horizon = parent_horizon + 1
    all_next_successors = {
        node_id
        for node_id, node in all_payloads.items()
        if node.get("kind") == "planner"
        and node.get("role") == "planner"
        and node.get("semantic_stage") == "successor_planning"
        and node.get("planning_horizon") == expected_horizon
    }
    if len(created_successors) != 1 or len(all_next_successors) != 1:
        return (
            f"patch {patch.patch_id} reliable-plan horizon requires exactly one successor planner",
            {
                **diagnostics,
                "violation": "missing_or_ambiguous_successor",
                "successor_node_ids": sorted(all_next_successors),
            },
        )

    successor_id, successor = next(iter(created_successors.items()))
    if successor.get("planning_horizon") != expected_horizon:
        return (
            f"patch {patch.patch_id} reliable-plan successor horizon must immediately follow "
            "its materialized batch",
            {
                **diagnostics,
                "violation": "invalid_successor_horizon",
                "proposer_horizon": parent_horizon,
                "successor_horizon": successor.get("planning_horizon"),
            },
        )
    successor_edges = [
        edge
        for edge in edges
        if edge.get("from_node_id") in batch_verifiers
        and edge.get("from_port") == "verification_report"
        and edge.get("to_node_id") == successor_id
        and edge.get("to_port") == "verification_report"
        and _selector_field(edge, "outcome") == "passed"
    ]
    if len(batch_verifiers) != 1 or len(successor_edges) != 1:
        return (
            f"patch {patch.patch_id} reliable-plan successor must be bound to its bounded "
            "batch verifier's passed verification_report",
            {
                **diagnostics,
                "violation": "successor_not_batch_pass_gated",
                "batch_verifier_node_ids": sorted(batch_verifiers),
                "successor_node_id": successor_id,
            },
        )
    return None


def _reliable_plan_initial_contract_error(
    *,
    discovery_id: str,
    discovery: dict[str, Any],
    verifier_id: str,
    verifier: dict[str, Any],
    successor_id: str,
    successor: dict[str, Any],
) -> tuple[str, str] | None:
    """Validate the concrete identities/contracts of the initial three nodes."""
    if discovery.get("kind") != "worker" or discovery.get("role") != "discovery":
        return "invalid_discovery_contract", f"discovery node {discovery_id} kind/role"
    if discovery.get("access_mode") != "read_only" or _has_effectful_resource_claim(discovery):
        return "invalid_discovery_contract", f"discovery node {discovery_id} read-only authority"
    if not _has_required_port(discovery, "outputs", "semantic_artifact", "SemanticArtifact"):
        return "invalid_discovery_contract", f"discovery node {discovery_id} output contract"

    if verifier.get("kind") != "verifier" or verifier.get("role") != "verifier":
        return "invalid_plan_verifier_contract", f"plan verifier {verifier_id} kind/role"
    if _has_effectful_resource_claim(verifier) or not _has_required_port(
        verifier, "inputs", "semantic_artifact", "SemanticArtifact"
    ):
        return "invalid_plan_verifier_contract", f"plan verifier {verifier_id} input contract"
    if not _has_required_port(verifier, "outputs", "verification_report", "VerificationReport"):
        return "invalid_plan_verifier_contract", f"plan verifier {verifier_id} output contract"

    if successor.get("kind") != "planner" or successor.get("role") != "planner":
        return "invalid_successor_contract", f"successor node {successor_id} kind/role"
    if successor.get("planning_horizon") != 1 or _has_effectful_resource_claim(successor):
        return "invalid_successor_contract", f"successor node {successor_id} horizon/authority"
    if not _has_required_port(successor, "inputs", "verification_report", "VerificationReport"):
        return "invalid_successor_contract", f"successor node {successor_id} input contract"
    return None


def _has_required_port(
    node: dict[str, Any],
    field_name: str,
    port: str,
    schema: str,
) -> bool:
    return any(
        item.get("port") == port
        and item.get("schema") == schema
        and item.get("required") is not False
        for item in _port_dicts(node.get(field_name))
    )


def _has_effectful_resource_claim(node: dict[str, Any]) -> bool:
    authority = node.get("authority")
    if not isinstance(authority, dict):
        return False
    claims = cast(dict[str, Any], authority).get("resource_claims")
    if not isinstance(claims, list):
        return False
    return any(
        isinstance(claim, dict)
        and cast(dict[str, Any], claim).get("mode") in {"write", "review_write", "external"}
        for claim in cast(list[Any], claims)
    )


def _effective_edge_backfill_record_ids(
    projection: GraphProjection,
    edge: dict[str, Any],
) -> list[str]:
    """Mirror deterministic edge-backfill merge semantics used during patch apply."""
    source = edge.get("from_node_id")
    port = edge.get("from_port")
    if not isinstance(source, str) or not isinstance(port, str) or source == "*":
        return []
    records = output_records_by_node_port_view(projection).get(source, {}).get(port, [])
    policy = binding_policy(edge.get("binding_policy"), None)
    bound: list[str] = []
    for record in records:
        payload = record.model_dump(mode="json")
        record_id = payload.get("record_id")
        if not isinstance(record_id, str) or not record_selector_matches(
            edge.get("accepted_record_selector"), payload
        ):
            continue
        bound = merge_bound_record_ids(
            policy,
            bound,
            [record_id],
            supersedes_record_id=payload.get("supersedes_record_id"),
        )
    return bound


def _semantic_stage_diagnostics(
    patch_id: str,
    ops: list[dict[str, Any]],
    projection: GraphProjection,
) -> dict[str, Any]:
    created = _created_nodes_by_id(ops)
    schema_keys = sorted(
        f"{schema_id}@{version}"
        for schema_id, version in semantic_schema_declarations_view(projection)
    )
    requested_schemas = sorted(
        {
            f"{node.get('semantic_schema_id')}@{node.get('semantic_schema_version')}"
            for node in created.values()
            if node.get("semantic_schema_id") is not None
            or node.get("semantic_schema_version") is not None
        }
    )
    return {
        "patch_id": patch_id,
        "invariant": "semantic_stage_topology",
        "node_ids": sorted(created),
        "ports": sorted(
            {
                f"{edge.get('from_node_id')}.{edge.get('from_port')}->"
                f"{edge.get('to_node_id')}.{edge.get('to_port')}"
                for edge in ops
                if edge.get("op") == "create_edge"
            }
        ),
        "requested_schemas": requested_schemas,
        "accepted_schemas": schema_keys,
        "missing_schemas": sorted(set(requested_schemas) - set(schema_keys)),
    }


def _corrective_evidence_error(
    node_id: str,
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    projection: GraphProjection,
    *,
    proposed_by_node_id: str,
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
        promised_current_gap = (
            to_port == "classified_gap"
            and source == proposed_by_node_id
            and any(
                lease.node_id == proposed_by_node_id
                and lease.state == "active"
                and record_id == f"classified-gap-{lease.execution_id}"
                for lease in leases_view(projection).values()
            )
        )
        if payload is None and promised_current_gap:
            promised_cited_ids = [
                record_id
                for binding in input_bindings_view(projection).get(proposed_by_node_id, {}).values()
                for record_id in binding.record_ids
            ]
            for cited_id in tuple(promised_cited_ids):
                cited_record = records.get(cited_id)
                evaluated_ids = (
                    cited_record.get("evaluated_record_ids")
                    if isinstance(cited_record, dict)
                    else None
                )
                if isinstance(evaluated_ids, list):
                    promised_cited_ids.extend(
                        item for item in cast(list[Any], evaluated_ids) if isinstance(item, str)
                    )
            payload = {
                "record_id": record_id,
                "producer_node_id": source,
                "record_type": "gap_classification",
                "value": {"classification": "corrective_work_required"},
                "provenance": {"evaluated_record_ids": promised_cited_ids},
            }
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
    correction_trigger = node.get("correction_trigger", "failed_batch")
    expected_report_outcome = (
        "passed" if correction_trigger == "failed_final_acceptance" else "failed"
    )
    expected_check_status = "passed" if correction_trigger == "failed_final_audit" else "failed"
    if (
        failed_reports[0].get("record_type") != "verification_report"
        or _terminal_value(failed_reports[0], "outcome") != expected_report_outcome
    ):
        return "corrective verification record has the wrong terminal outcome"
    if any(
        check.get("record_type") != "check_result"
        or _terminal_value(check, "status") != expected_check_status
        for check in failed_checks
    ):
        return "corrective check records have the wrong terminal status"
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
        expected = ", ".join(sorted(declared_batches))
        return (
            f"final gate {node_id} declared_batch_ids must exactly match the accepted plan; "
            f"expected: [{expected}]"
        )
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
        and payloads[source].get("semantic_stage") in {"effectful_batch", "corrective_work"}
        and isinstance(payloads[source].get("declared_batch_id"), str)
    }
    if verified_batches != declared_batches:
        return "final gate requires passed verification from every declared batch"
    batch_sources = {
        source
        for source in passed_sources
        if payloads.get(source, {}).get("semantic_stage") in {"effectful_batch", "corrective_work"}
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
    acceptance_sources = {
        cast(str, edge.get("from_node_id"))
        for edge in incoming
        if isinstance(edge.get("from_node_id"), str)
        and _selector_field(edge, "status") == "passed"
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("kind") == "check"
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("semantic_stage")
        == "final_acceptance"
        and payloads.get(cast(str, edge.get("from_node_id")), {}).get("command_binding")
        == "dynamic_feature_acceptance"
    }
    if len(acceptance_sources) != 1:
        return "final gate requires exactly one passed dynamic feature acceptance receipt"
    acceptance_source = next(iter(acceptance_sources))
    acceptance_incoming_sources = {
        cast(str, edge.get("from_node_id"))
        for edge in edges
        if edge.get("to_node_id") == acceptance_source
        and isinstance(edge.get("from_node_id"), str)
        and _selector_field(edge, "outcome") == "passed"
    }
    if not batch_sources.issubset(acceptance_incoming_sources):
        return "dynamic feature acceptance must consume passed verification from every batch"
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
        audit_acceptance_sources = {
            cast(str, edge.get("from_node_id"))
            for edge in edges
            if edge.get("to_node_id") == audit_source
            and isinstance(edge.get("from_node_id"), str)
            and _selector_field(edge, "status") == "passed"
        }
        if acceptance_source not in audit_acceptance_sources:
            return "final audit must consume the passed dynamic feature acceptance receipt"
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


def _selector_field(edge: dict[str, Any], field: str) -> Any:
    selector = edge.get("accepted_record_selector")
    return cast(dict[str, Any], selector).get(field) if isinstance(selector, dict) else None


def _declares_semantic_artifact_output(node: dict[str, Any]) -> bool:
    return any(
        port.get("port") == "semantic_artifact" and port.get("schema") == "SemanticArtifact"
        for port in _port_dicts(node.get("outputs"))
    )


def _declares_required_semantic_artifact_output(node: dict[str, Any]) -> bool:
    return any(
        port.get("port") == "semantic_artifact"
        and port.get("schema") == "SemanticArtifact"
        and port.get("required") is True
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
    for _op_name, _node_key, typed_node in iter_patch_node_payloads(ops):
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
