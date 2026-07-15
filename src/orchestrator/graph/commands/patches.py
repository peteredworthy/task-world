"""Typed submit-patch command handling."""

from __future__ import annotations

from typing import Any, assert_never, cast

from pydantic import Field

from orchestrator.graph.command_bindings import canonicalize_check_command_definition
from orchestrator.graph.events.decisions import APPEAL_OPENED, AppealOpenedPayload
from orchestrator.graph.events.lifecycle import COMMAND_REJECTED, CommandRejectedPayload
from orchestrator.graph.events.records import OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload
from orchestrator.graph.events.patches import (
    GRAPH_PATCH_ACCEPTED,
    GRAPH_PATCH_REJECTED,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
)
from orchestrator.graph.events.topology import (
    EDGE_CREATED,
    INPUT_BOUND,
    NODE_CREATED,
    NODE_AUTHORITY_CHANGED,
    NODE_RETIRED,
    NODE_STATE_CHANGED,
    PLAN_REGION_MARKED_SUSPECT,
    REVISION_CREATED,
    EdgeCreatedPayload,
    InputBoundPayload,
    NodeAuthorityChangedPayload,
    NodeCreatedPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    PlanRegionMarkedSuspectPayload,
    RevisionCreatedPayload,
)
from orchestrator.graph.macros import expand_patch_macros
from orchestrator.graph.models import (
    PatchEnvelope,
    PatchOp,
    PatchAuthorityRequest,
    PatchDecisionRequest,
    PatchNode,
    CreateAppealPatchOp,
    CreateEdgePatchOp,
    CreateGatePatchOp,
    CreateNodePatchOp,
    CreateRevisionAttemptPatchOp,
    MarkPlanRegionSuspectPatchOp,
    RetireNodePatchOp,
    SetAllowedActionsPatchOp,
    SetResourceClaimsPatchOp,
    StrictAuthorityRequestRecord,
    StrictAuthorityRequestValue,
    StrictDecisionRequestRecord,
    StrictDecisionRequestValue,
    parse_patch_ops,
    record_selector_matches,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph.patch_validator import validate_patch
from orchestrator.graph.commands.callbacks import source_repair_events
from orchestrator.graph.commands.event_creator import TypedEventCreator


def patch_successor_planner_node_ids(patch: PatchEnvelope) -> list[str]:
    return [
        node_id
        for op in patch.ops
        if isinstance(op, CreateNodePatchOp)
        and op.node.kind == "planner"
        and op.node.role == "planner"
        and (node_id := op.node.node_id)
    ]


def patch_planner_budget_rejection(
    projection: GraphProjection, patch: PatchEnvelope
) -> dict[str, int] | None:
    attempted_generation = (
        projection["planner_generations"].values.get(patch.proposed_by_node_id, 0) + 1
    )
    budget = projection["planner_generation_budget"]
    return (
        None
        if attempted_generation <= budget
        else {"budget": budget, "count": attempted_generation}
    )


def patch_request_record_validation_error(patch: PatchEnvelope) -> str | None:
    for op in patch.ops:
        if isinstance(op, CreateNodePatchOp):
            try:
                request = op.node.decision_request
                if (
                    request is not None
                    and request.options is not None
                    and request.default_option not in {None, *request.options}
                ):
                    raise ValueError("default_option must be one of options")
                _request_records_for_node(op.node)
            except ValueError as exc:
                return f"invalid request record for node {op.node.node_id}: {exc}"
    return None


def patch_op_events(
    op: PatchOp,
    projection: GraphProjection,
    events: list[HydratedEvent],
    creator: TypedEventCreator,
    *,
    inherited_session_id: str | None = None,
    carryover_record_id: str | None = None,
    generated_revision_id: str | None = None,
) -> list[HydratedEvent]:
    match op:
        case CreateNodePatchOp(node=raw_node):
            node_data = _node_data(raw_node)
            node = _node_created_payload(
                node_data, events, inherited_session_id, carryover_record_id
            )
            return [
                creator.create(NODE_CREATED, node),
                *_request_record_events_for_node(raw_node, creator),
            ]
        case CreateEdgePatchOp():
            edge = _edge_created_payload(op)
            return [
                creator.create(EDGE_CREATED, edge),
                *_input_bound_events_for_edge(projection, edge, creator),
            ]
        case RetireNodePatchOp(node_id=node_id, reason=reason):
            return [
                creator.create(NODE_RETIRED, NodeRetiredPayload(node_id=node_id, reason=reason)),
                creator.create(
                    NODE_STATE_CHANGED,
                    NodeStateChangedPayload(
                        node_id=node_id, new_state="retired", trigger="graph_patch_accepted"
                    ),
                ),
            ]
        case CreateGatePatchOp():
            return [creator.create(NODE_CREATED, _node_payload_for_gate(op))]
        case CreateRevisionAttemptPatchOp():
            output = [
                creator.create(
                    REVISION_CREATED,
                    RevisionCreatedPayload(
                        revision_id=(
                            op.revision_id if op.revision_id is not None else generated_revision_id
                        ),
                        task_region_id=op.task_region_id,
                        attempt_number=op.attempt_number,
                        candidate_id=op.candidate_id,
                        failed_candidate_id=op.failed_candidate_id,
                        reason=op.reason,
                    ),
                )
            ]
            for node, kind in ((op.worker_node, "worker"), (op.verifier_node, "verifier")):
                if node is not None:
                    output.append(
                        creator.create(NODE_CREATED, _node_payload_for_revision_node(node, kind))
                    )
            return output
        case CreateAppealPatchOp():
            node = _node_payload_for_appeal(op)
            return [
                creator.create(NODE_CREATED, node),
                creator.create(
                    APPEAL_OPENED,
                    AppealOpenedPayload(
                        node_id=node.node_id,
                        appealed_node_id=op.appealed_node_id,
                        appeal_type=op.appeal_type,
                        candidate_id=op.candidate_id,
                        task_region_id=op.task_region_id,
                        lease_id=op.lease_id,
                    ),
                ),
            ]
        case SetResourceClaimsPatchOp(node_id=node_id, resource_claims=resource_claims):
            return [
                creator.create(
                    NODE_AUTHORITY_CHANGED,
                    NodeAuthorityChangedPayload(
                        node_id=node_id,
                        resource_claims=cast(Any, [claim.to_json() for claim in resource_claims]),
                    ),
                )
            ]
        case SetAllowedActionsPatchOp(node_id=node_id, allowed_actions=allowed_actions):
            return [
                creator.create(
                    NODE_AUTHORITY_CHANGED,
                    NodeAuthorityChangedPayload(node_id=node_id, allowed_actions=allowed_actions),
                )
            ]
        case MarkPlanRegionSuspectPatchOp(
            region_node_ids=region_node_ids, reason=reason, region_id=region_id
        ):
            return [
                creator.create(
                    PLAN_REGION_MARKED_SUSPECT,
                    PlanRegionMarkedSuspectPayload(
                        region_node_ids=region_node_ids, reason=reason, region_id=region_id
                    ),
                )
            ]
        case _:
            assert_never(op)


def _node_created_payload(
    raw_node: dict[str, Any],
    events: list[HydratedEvent],
    inherited_session_id: str | None,
    carryover_record_id: str | None,
) -> NodeCreatedPayload:
    node = dict(raw_node)
    _ensure_default_node_authority(node)
    canonicalize_check_command_definition(node, events)
    if node.get("kind") == "planner" and node.get("role") == "planner":
        if inherited_session_id is not None:
            node.setdefault("session_id", inherited_session_id)
        _ensure_optional_session_carryover_input(node)
        if carryover_record_id is not None:
            node["carryover_record_id"] = carryover_record_id
    return NodeCreatedPayload(**node)


def _node_data(node: PatchNode) -> dict[str, Any]:
    return cast(dict[str, Any], node.to_json())


def _node_payload_for_gate(op: CreateGatePatchOp) -> NodeCreatedPayload:
    node: dict[str, Any] = (
        _node_data(op.node) if op.node is not None else {"node_id": op.node_id, "kind": "gate"}
    )
    node.setdefault("state", op.state or "planned")
    node.setdefault("task_region_id", op.task_region_id)
    node.setdefault("predecessor_node_ids", op.predecessor_node_ids)
    node.setdefault("reason", op.reason)
    return NodeCreatedPayload(**cast(Any, node))


def _node_payload_for_revision_node(node: PatchNode, default_kind: str) -> NodeCreatedPayload:
    data = _node_data(node)
    data.setdefault("kind", default_kind)
    data.setdefault("state", "planned")
    _ensure_default_node_authority(data)
    return NodeCreatedPayload(**cast(Any, data))


def _node_payload_for_appeal(op: CreateAppealPatchOp) -> NodeCreatedPayload:
    node: dict[str, Any] = (
        _node_data(op.node) if op.node is not None else {"node_id": op.node_id, "kind": "appeal"}
    )
    node.setdefault("state", op.state or "planned")
    node.setdefault("task_region_id", op.task_region_id)
    node.setdefault("appealed_node_id", op.appealed_node_id)
    return NodeCreatedPayload(**cast(Any, node))


def _edge_created_payload(op: CreateEdgePatchOp) -> EdgeCreatedPayload:
    selector = op.accepted_record_selector
    return EdgeCreatedPayload(
        edge_id=op.edge_id,
        from_node_id=op.from_node_id,
        from_port="verification_report" if op.from_port == "verification_result" else op.from_port,
        to_node_id=op.to_node_id,
        to_port=op.to_port,
        required=op.required,
        dependency_type=op.dependency_type,
        accepted_record_selector=selector.to_json() if selector is not None else None,
        binding_policy=op.binding_policy,
        freshness_policy=op.freshness_policy,
        prompt_hydration_policy=op.prompt_hydration_policy,
        purpose=op.purpose,
        description=op.description,
        selection=op.selection,
        metadata=op.metadata,
        from_node_kind=op.from_node_kind,
        from_node_role=op.from_node_role,
    )


def _ensure_default_node_authority(node: dict[str, Any]) -> None:
    if node.get("kind") != "worker":
        return
    authority = dict(node["authority"]) if isinstance(node.get("authority"), dict) else {}
    authority.setdefault(
        "allowed_actions", ["submit_records", "request_clarification", "raise_appeal"]
    )
    authority.setdefault("resource_claims", [{"mode": "write", "scope": "repo", "paths": ["."]}])
    for key in ("resource_claims", "allowed_actions", "preconditions"):
        if key in authority:
            node.setdefault(key, authority[key])
    node.pop("authority", None)


def _ensure_optional_session_carryover_input(node: dict[str, JsonValue]) -> None:
    inputs = node.get("inputs")
    if not isinstance(inputs, list):
        node["inputs"] = [{"port": "session_carryover", "direction": "input", "required": False}]
        return
    for item in inputs:
        if isinstance(item, dict) and item.get("port") == "session_carryover":
            item["required"] = False
            return
    inputs.append({"port": "session_carryover", "direction": "input", "required": False})


def _request_records_for_node(
    node: PatchNode,
) -> list[tuple[StrictDecisionRequestRecord | StrictAuthorityRequestRecord, str]]:
    if node.kind == "human_gate":
        value = _decision_request_value(node.decision_request, node)
        return [
            (
                StrictDecisionRequestRecord(
                    record_id=node.decision_request_record_id or f"decision-request-{node.node_id}",
                    record_kind="graph_record",
                    record_type="decision_request",
                    producer_node_id=node.node_id,
                    port="decision_request",
                    schema="DecisionRequest",
                    value=value,
                ),
                "decision_request",
            )
        ]
    if node.kind == "authority_request":
        value = _authority_request_value(
            node.authority_request_record or node.authority_request,
            node,
        )
        return [
            (
                StrictAuthorityRequestRecord(
                    record_id=node.authority_request_record_id
                    or f"authority-request-{node.node_id}",
                    record_kind="graph_record",
                    record_type="authority_request_record",
                    producer_node_id=node.node_id,
                    port="authority_request_record",
                    schema="AuthorityRequest",
                    value=value,
                ),
                "authority_request_record",
            )
        ]
    return []


def _decision_request_value(
    request: PatchDecisionRequest | None, node: PatchNode
) -> StrictDecisionRequestValue:
    return StrictDecisionRequestValue(
        decision_type=request.decision_type if request and request.decision_type else "approval",
        options=request.options
        if request and request.options is not None
        else ["approve", "reject"],
        default_option=request.default_option if request else None,
        consequence_summary=(
            request.consequence_summary
            if request and request.consequence_summary
            else node.reason or "Manual decision required before graph can continue."
        ),
        expires_at=request.expires_at if request else None,
        target_node_id=request.target_node_id if request else None,
        target_region_id=request.target_region_id if request else None,
        prompt=request.prompt if request else None,
    )


def _authority_request_value(
    request: PatchAuthorityRequest | None, node: PatchNode
) -> StrictAuthorityRequestValue:
    return StrictAuthorityRequestValue(
        requested_authority=request.requested_authority
        if request and request.requested_authority
        else [],
        target_node_id=request.target_node_id if request else None,
        target_region_id=request.target_region_id
        if request and request.target_region_id
        else node.task_region_id,
        reason=request.reason
        if request and request.reason
        else node.reason or "Authority required.",
        expires_at=request.expires_at if request else None,
    )


def _request_record_events_for_node(
    node: PatchNode, creator: TypedEventCreator
) -> list[HydratedEvent]:
    output: list[HydratedEvent] = []
    for record, to_port in _request_records_for_node(node):
        output.append(
            creator.create(OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload(record=record))
        )
        output.append(
            creator.create(
                INPUT_BOUND,
                InputBoundPayload(
                    edge_id=f"edge-{record.record_id}-to-{record.producer_node_id}-{to_port}",
                    to_node_id=record.producer_node_id,
                    to_port=to_port,
                    record_ids=[record.record_id],
                    bound_at_position=0,
                    binding_policy="bind_latest",
                ),
            )
        )
    return output


def _input_bound_events_for_edge(
    projection: GraphProjection, edge: EdgeCreatedPayload, creator: TypedEventCreator
) -> list[HydratedEvent]:
    if edge.dependency_type != "input_binding":
        return []
    output: list[HydratedEvent] = []
    producer_ids = (
        [edge.from_node_id]
        if edge.from_node_id != "*"
        else [
            node_id
            for node_id in sorted(projection["node_kinds"])
            if (
                edge.from_node_kind is None
                or projection["node_kinds"].get(node_id) == edge.from_node_kind
            )
            and (
                edge.from_node_role is None
                or projection["node_roles"].get(node_id) == edge.from_node_role
            )
        ]
    )
    for producer_id in producer_ids:
        for record in (
            projection["output_records_by_node_port"].get(producer_id, {}).get(edge.from_port, [])
        ):
            record_id = record.record_id
            if not record_selector_matches(
                edge.accepted_record_selector,
                dict(record.__dict__),
                {"verification_result"}
                if record.record_kind == "verification"
                else {"accepted_file_state", "file_state"}
                if record.record_kind == "file_state"
                else set(),
            ):
                continue
            output.append(
                creator.create(
                    INPUT_BOUND,
                    InputBoundPayload(
                        edge_id=edge.edge_id,
                        to_node_id=edge.to_node_id,
                        to_port=edge.to_port,
                        record_ids=[record_id],
                        bound_at_position=0,
                        binding_policy=edge.binding_policy,
                        supersedes_record_id=getattr(record, "supersedes_record_id", None),
                        trigger="edge_backfill",
                    ),
                )
            )
    return output


def _empty_macro_invocations() -> list[dict[str, JsonValue]]:
    return []


class SubmitPatchFields(StrictPayload):
    """Command-owned patch fields shared with transport adapters."""

    ops: list[PatchOp] = Field(min_length=1)
    rationale_record_id: str | None = Field(default=None, min_length=1)


class SubmitPatchCommand(SubmitPatchFields):
    patch_id: str
    base_graph_position: int
    actor_role: str
    proposed_by_node_id: str
    macro_invocations: list[dict[str, JsonValue]] = Field(default_factory=_empty_macro_invocations)
    session_id: str | None = None
    carryover_record_id: str | None = None
    diagnostics: dict[str, JsonValue] | None = None
    read_set_diff: dict[str, JsonValue] | None = None
    lease_id: str | None = None
    lease_generation: int | None = Field(default=None, ge=0)
    execution_id: str | None = None
    base_snapshot_id: str | None = None
    observed_graph_position: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = None


def _expanded_ops(command: SubmitPatchCommand) -> list[PatchOp]:
    """Expand typed macro invocations without lowering the command to a payload map."""

    if not command.macro_invocations:
        return list(command.ops)
    expanded = expand_patch_macros(
        {
            "ops": [],
            "macro_invocations": command.macro_invocations,
            "proposed_by_node_id": command.proposed_by_node_id,
        }
    )
    return [*command.ops, *parse_patch_ops(expanded["ops"])]


def _current_position(events: tuple[HydratedEvent, ...], context: CommandExecutionContext) -> int:
    if not events:
        return context.current_position
    return max(event.position for event in events)


def _rejected_payload(
    patch: PatchEnvelope,
    command: SubmitPatchCommand,
    *,
    reason: str,
    read_set_diff: dict[str, JsonValue] | None,
    budget: int | None = None,
    count: int | None = None,
) -> GraphPatchRejectedPayload:
    return GraphPatchRejectedPayload(
        patch_id=patch.patch_id,
        base_graph_position=patch.base_graph_position,
        actor_role=command.actor_role,
        proposed_by_node_id=patch.proposed_by_node_id,
        reason=reason,
        read_set_diff=read_set_diff,
        diagnostics=command.diagnostics,
        budget=budget,
        count=count,
    )


def _typed_submit(
    command: SubmitPatchCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    """Derive all patch effects from typed command values and hydrated history."""

    creator = TypedEventCreator(context, assign_position=False, causation_id="submit_patch")
    if projection["run_state"] is not None and projection["run_state"] != "active":
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(
                    command_type="submit_patch",
                    reason=f"run_not_active:{projection['run_state'] or 'unknown'}",
                ),
            )
        ]
    try:
        patch = PatchEnvelope(
            patch_id=command.patch_id,
            proposed_by_node_id=command.proposed_by_node_id,
            base_graph_position=command.base_graph_position,
            ops=_expanded_ops(command),
            rationale_record_id=command.rationale_record_id,
        )
    except (TypeError, ValueError) as exc:
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(
                    command_type="submit_patch",
                    reason=f"malformed patch: {exc}",
                    patch_id=command.patch_id,
                    base_graph_position=command.base_graph_position,
                    actor_role=command.actor_role,
                    proposed_by_node_id=command.proposed_by_node_id,
                ),
            )
        ]

    result = validate_patch(
        patch,
        _current_position(events, context),
        [event for event in events if event.position > patch.base_graph_position],
        projection,
        command.actor_role,
    )
    if not result.accepted:
        return [
            creator.create(
                GRAPH_PATCH_REJECTED,
                _rejected_payload(
                    patch,
                    command,
                    reason=result.rejection_reason or "patch_rejected",
                    read_set_diff=cast(dict[str, JsonValue] | None, result.read_set_diff),
                ),
            )
        ]

    successor_planner_node_ids = patch_successor_planner_node_ids(patch)
    if command.actor_role == "planner" and len(successor_planner_node_ids) > 1:
        return [
            creator.create(
                GRAPH_PATCH_REJECTED,
                _rejected_payload(
                    patch,
                    command,
                    reason="multiple_successor_planners_not_allowed",
                    read_set_diff=None,
                ),
            )
        ]
    if command.actor_role == "planner" and successor_planner_node_ids:
        budget_rejection = patch_planner_budget_rejection(projection, patch)
        if budget_rejection is not None:
            gate_node_id = f"gate-planner-budget-{patch.proposed_by_node_id}"
            return [
                creator.create(
                    GRAPH_PATCH_REJECTED,
                    _rejected_payload(
                        patch,
                        command,
                        reason="planner_generation_budget_exhausted",
                        read_set_diff=None,
                        budget=budget_rejection["budget"],
                        count=budget_rejection["count"],
                    ),
                ),
                creator.create(
                    NODE_CREATED,
                    NodeCreatedPayload(
                        node_id=gate_node_id,
                        kind="gate",
                        state="planned",
                        role="planner_generation_budget_gate",
                        guarded_planner_node_id=patch.proposed_by_node_id,
                        rejected_patch_id=patch.patch_id,
                        reason="planner_generation_budget_exhausted",
                    ),
                ),
                creator.create(
                    NODE_STATE_CHANGED,
                    NodeStateChangedPayload(
                        node_id=gate_node_id,
                        new_state="ready",
                        trigger="planner_generation_budget_exhausted",
                    ),
                ),
            ]

    request_record_error = patch_request_record_validation_error(patch)
    if request_record_error is not None:
        return [
            creator.create(
                GRAPH_PATCH_REJECTED,
                _rejected_payload(patch, command, reason=request_record_error, read_set_diff=None),
            )
        ]

    parent_session_id = projection["planner_sessions"].values.get(patch.proposed_by_node_id)
    output = [
        creator.create(
            GRAPH_PATCH_ACCEPTED,
            GraphPatchAcceptedPayload(
                patch_id=patch.patch_id,
                base_graph_position=patch.base_graph_position,
                actor_role=command.actor_role,
                proposed_by_node_id=patch.proposed_by_node_id,
                successor_planner_node_ids=successor_planner_node_ids,
                session_id=parent_session_id,
                carryover_record_id=command.carryover_record_id,
                diagnostics=command.diagnostics,
            ),
        )
    ]
    for op in patch.ops:
        generated_revision_id = (
            context.id_generator.next_id("revision")
            if isinstance(op, CreateRevisionAttemptPatchOp)
            and op.revision_id is None
            and op.worker_node is None
            and op.verifier_node is None
            else None
        )
        output.extend(
            patch_op_events(
                op,
                projection,
                list(events),
                creator,
                inherited_session_id=parent_session_id,
                carryover_record_id=command.carryover_record_id,
                generated_revision_id=generated_revision_id,
            )
        )
    if command.carryover_record_id is not None and successor_planner_node_ids:
        output.append(
            creator.create(
                INPUT_BOUND,
                InputBoundPayload(
                    edge_id=f"edge-session-carryover-{successor_planner_node_ids[0]}",
                    to_node_id=successor_planner_node_ids[0],
                    to_port="session_carryover",
                    record_ids=[command.carryover_record_id],
                    bound_at_position=0,
                ),
            )
        )
    output.extend(source_repair_events(projection, list(events), output, context.catalog, creator))
    return output


SUBMIT_PATCH = CommandSpecification("submit_patch", SubmitPatchCommand, _typed_submit)
COMMAND_SPECIFICATIONS = (SUBMIT_PATCH,)


__all__ = ["SUBMIT_PATCH", "COMMAND_SPECIFICATIONS", "SubmitPatchCommand", "SubmitPatchFields"]
