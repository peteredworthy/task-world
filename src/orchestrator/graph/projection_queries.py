"""Pure queries over graph projection storage.

Each query owns the physical projection access and returns values that cannot
mutate projection containers.
"""

from collections.abc import Mapping
from typing import cast

from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    ApprovalDecisionProjection,
    AuthorityDecisionProjection,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CheckResultProjection,
    CommandDefinitionProjection,
    CleanupRequestedProjection,
    EdgeProjection,
    EnvironmentFailureProjection,
    FileStateRecord,
    InputBindingProjection,
    InvalidTestBlockProjection,
    LeaseProjection,
    NodeCreationProjection,
    OUTPUT_RECORD_MODELS_BY_TYPE,
    OutputRecordAcceptedPayload,
    OversightDecisionProjection,
    PendingGateDecisionProjection,
    RequirementRevisionProjection,
    ResourceClaimProjection,
    SupportEvidenceProjection,
    VerificationResultProjection,
    VerifierVerdictProjection,
)
from orchestrator.graph.projection_collections import (
    FrozenJsonValue,
    FrozenMap,
    JsonValue,
    thaw_json,
)
from orchestrator.graph.projection_models import (
    GraphRecordSummaryProjection,
    ProjectedFanOutInputsRecord,
    ProjectedAuthorityRequestRecord,
    ProjectionModel,
)
from orchestrator.graph.projections import (
    AcceptedOutputRecord,
    GraphProjection,
    GraphRecordSummary,
    LatestRoutineSnapshotRecord,
    RecoveryNodeIndexEntry,
)


def accepted_graph_patches_by_node_view(projection: GraphProjection) -> dict[str, list[str]]:
    return {
        node_id: list(ids)
        for node_id, ids in projection.planning.accepted_patch_ids_by_node.items()
    }


def action_count_by_node_kind_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.usage.action_count_by_node_kind)


def approval_decisions_view(
    projection: GraphProjection,
) -> dict[str, ApprovalDecisionProjection]:
    return {
        node_id: ApprovalDecisionProjection.model_validate(
            projection.governance.approval_decisions_by_id[decision_id].model_dump(mode="json")
        )
        for node_id, decision_id in projection.governance.approval_decision_id_by_node.items()
    }


def authority_decisions_view(
    projection: GraphProjection,
) -> dict[str, AuthorityDecisionProjection]:
    return {
        node_id: AuthorityDecisionProjection.model_validate(
            projection.governance.authority_decisions_by_id[decision_id].model_dump(mode="json")
        )
        for node_id, decision_id in projection.governance.authority_decision_id_by_node.items()
    }


def decision_request_details_view(
    projection: GraphProjection,
) -> dict[str, PendingGateDecisionProjection]:
    return {
        node_id: PendingGateDecisionProjection.model_validate(request.model_dump(mode="json"))
        for node_id, request in projection.governance.decision_requests_by_node.items()
    }


def execution_count_by_node_kind_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.usage.execution_count_by_node_kind)


def invalid_test_blocks_view(
    projection: GraphProjection,
) -> dict[str, InvalidTestBlockProjection]:
    return {
        task_id: InvalidTestBlockProjection.model_validate(value.model_dump(mode="json"))
        for task_id, value in projection.verification.invalid_test_blocks_by_task.items()
    }


def latency_ms_by_node_kind_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.usage.latency_ms_by_node_kind)


def node_allowed_actions_view(projection: GraphProjection) -> dict[str, list[str]]:
    return {node_id: list(node.spec.allowed_actions) for node_id, node in projection.nodes.items()}


def node_creation_payloads_view(
    projection: GraphProjection,
) -> dict[str, NodeCreationProjection]:
    return {
        node_id: NodeCreationProjection(
            node_id=node_id,
            position=node.spec.creation_position,
            kind=node.spec.kind,
            role=node.spec.role,
            state=node.runtime.state,
            task_region_id=node.spec.task_region_id,
            attempt_number=node.runtime.attempt_number,
            candidate_id=node.runtime.candidate_id,
            failed_candidate_id=node.runtime.failed_candidate_id,
            resource_claims=[
                ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
                for claim in node.spec.resource_claims
            ],
            allowed_actions=list(node.spec.allowed_actions),
            preconditions=list(node.spec.preconditions),
            planner_generation_budget=projection.planning.generation_budget,
            generation_index=projection.planning.generation_by_node.get(node_id),
            region_label=projection.planning.region_label_by_node.get(node_id),
            session_id=projection.planning.session_id_by_node.get(node_id),
            gate_type=node.spec.gate_type,
            approval_type=node.spec.approval_type,
            reason=node.spec.reason,
            prompt=node.spec.prompt,
            approval_prompt=node.spec.approval_prompt,
            human_prompt=node.spec.human_prompt,
            message=node.spec.message,
            blocker=node.spec.blocker,
            blocker_reason=node.spec.blocker_reason,
            decision_request=(
                node.spec.decision_request.model_dump(mode="json")
                if node.spec.decision_request is not None
                else None
            ),
            authority_request_record_id=node.spec.authority_request_record_id,
            authority_request_record=_authority_request_record_public_value(
                projection, node.spec.authority_request_record_id
            ),
            authority_request=(
                node.spec.authority_request.model_dump(mode="json")
                if node.spec.authority_request is not None
                else None
            ),
            authority=(
                node.spec.authority.model_dump(mode="json")
                if node.spec.authority is not None
                else None
            ),
            command_definition=(
                _command_definition_value(node.spec.command_definition.value)
                if node.spec.command_definition is not None
                else None
            ),
            command_definition_id=node.spec.command_definition_id,
            hidden_oracle_command=node.spec.hidden_oracle_command,
            command_binding=node.spec.command_binding,
            max_attempts=node.spec.max_attempts,
        )
        for node_id, node in projection.nodes.items()
    }


def _authority_request_record_public_value(
    projection: GraphProjection, record_id: str | None
) -> dict[str, object] | None:
    if record_id is None:
        return None
    record = projection.records.by_id.get(record_id)
    if not isinstance(record, ProjectedAuthorityRequestRecord):
        return None
    return record.model_dump(mode="json", by_alias=True)


def node_output_ports_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[str]]]:
    return {
        node_id: {port: list(record_ids) for port, record_ids in ports.items()}
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def output_record_payloads_view(
    projection: GraphProjection,
) -> dict[str, AcceptedOutputRecordPayload]:
    return {
        record_id: OutputRecordAcceptedPayload.model_validate(
            record.model_dump(mode="json", by_alias=True)
        ).root
        for record_id, record in projection.records.by_id.items()
        if record.record_type != "file_state"
    }


def requirement_revisions_view(
    projection: GraphProjection,
) -> dict[str, RequirementRevisionProjection]:
    return {
        version_id: RequirementRevisionProjection.model_validate(revision.model_dump(mode="json"))
        for version_id, revision in projection.requirements.revisions_by_id.items()
    }


def support_evidence_view(
    projection: GraphProjection,
) -> dict[str, SupportEvidenceProjection]:
    return {
        support_id: SupportEvidenceProjection.model_validate(evidence.model_dump(mode="json"))
        for support_id, evidence in projection.requirements.support_by_id.items()
    }


def tokens_by_node_kind_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.usage.tokens_by_node_kind)


def tokens_by_node_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.usage.tokens_by_node)


def accepted_no_successor_patches_by_node_view(
    projection: GraphProjection,
) -> dict[str, list[str]]:
    return {
        node_id: list(ids)
        for node_id, ids in projection.planning.no_successor_patch_ids_by_node.items()
    }


def accepted_output_records_by_node_port_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[AcceptedOutputRecord]]]:
    return {
        node_id: {
            port: [
                {
                    "record_id": record_id,
                    "payload": _accepted_output_record(projection, record_id),
                }
                for record_id in record_ids
            ]
            for port, record_ids in ports.items()
        }
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def accepted_record_summaries_by_id_view(
    projection: GraphProjection,
) -> dict[str, GraphRecordSummary]:
    return {
        record_id: _graph_record_summary(summary)
        for record_id, summary in projection.records.summaries_by_id.items()
    }


def active_requirement_versions_view(projection: GraphProjection) -> dict[str, str]:
    return dict(projection.requirements.active_version_id_by_requirement)


def callback_idempotency_events_view(
    projection: GraphProjection,
) -> dict[str, CallbackIdempotencyEvent]:
    return {
        key: CallbackIdempotencyEvent.model_validate(value.model_dump(mode="json"))
        for key, value in projection.execution.callback_events_by_key.items()
    }


def check_results_view(projection: GraphProjection) -> dict[str, CheckResultProjection]:
    return {
        node_id: CheckResultProjection.model_validate(result.model_dump(mode="json"))
        for node_id, result in projection.verification.check_results_by_node.items()
    }


def cleanup_applied_ids_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.execution.applied_cleanup_ids)


def cleanup_requested_events_view(
    projection: GraphProjection,
) -> dict[str, CleanupRequestedProjection]:
    return {
        cleanup_id: CleanupRequestedProjection.model_validate(request.model_dump(mode="json"))
        for cleanup_id, request in projection.execution.cleanup_requests_by_id.items()
    }


def edges_view(projection: GraphProjection) -> dict[str, EdgeProjection]:
    return {
        edge_id: EdgeProjection.model_validate(edge.model_dump(mode="json"))
        for edge_id, edge in projection.topology.edges.items()
    }


def environment_failures_view(
    projection: GraphProjection,
) -> dict[str, EnvironmentFailureProjection]:
    return {
        task_id: EnvironmentFailureProjection.model_validate(failure.model_dump(mode="json"))
        for task_id, failure in projection.execution.environment_failures_by_task.items()
    }


def failed_verification_candidate_ids_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.verification.failed_candidate_ids)


def failed_verification_results_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, VerificationResultProjection]:
    return {
        record_id: VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        for record_id, result in projection.verification.failed_results_by_record_id.items()
    }


def file_state_records_view(projection: GraphProjection) -> dict[str, FileStateRecord]:
    return {
        record_id: FileStateRecord.model_validate(
            {
                key: value
                for key, value in record.model_dump(mode="json", by_alias=True).items()
                if key != "acceptance_identity"
            }
        )
        for record_id, record in projection.records.by_id.items()
        if record.record_type == "file_state"
    }


def input_bindings_view(
    projection: GraphProjection,
) -> dict[str, dict[str, InputBindingProjection]]:
    return {
        node_id: {
            port: InputBindingProjection.model_validate(ports[port].model_dump(mode="json"))
            for port in projection.topology.input_binding_port_order.get(node_id, ())
        }
        for node_id, ports in projection.topology.input_bindings.items()
    }


def last_deferred_reasons_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.scheduling.last_deferred_reason
        for node_id, node in projection.nodes.items()
        if node.scheduling.last_deferred_reason is not None
    }


def leases_view(projection: GraphProjection) -> dict[str, LeaseProjection]:
    return {
        lease_id: LeaseProjection.model_validate(
            projection.execution.leases[lease_id].model_dump(mode="json")
        )
        for lease_id in projection.execution.lease_ids_in_grant_order
    }


def node_attempts_view(projection: GraphProjection) -> dict[str, int]:
    return {
        node_id: node.runtime.attempt_number
        for node_id, node in projection.nodes.items()
        if node.runtime.attempt_number is not None
    }


def node_command_definitions_view(
    projection: GraphProjection,
) -> dict[str, CommandDefinitionProjection]:
    return {
        node_id: _command_definition_value(node.spec.command_definition.value)
        for node_id, node in projection.nodes.items()
        if node.spec.command_definition is not None
    }


def node_creation_positions_view(projection: GraphProjection) -> dict[str, int]:
    return {node_id: node.spec.creation_position for node_id, node in projection.nodes.items()}


def node_gate_decisions_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.governance.node_gate_decisions)


def node_failed_candidates_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.runtime.failed_candidate_id
        for node_id, node in projection.nodes.items()
        if node.runtime.failed_candidate_id is not None
    }


def node_pending_appeals_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.governance.pending_appeals_by_node)


def node_preconditions_view(projection: GraphProjection) -> dict[str, list[str]]:
    return {node_id: list(node.spec.preconditions) for node_id, node in projection.nodes.items()}


def node_kinds_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.kind
        for node_id, node in projection.nodes.items()
        if node.spec.kind is not None
    }


def node_resource_claims_view(
    projection: GraphProjection,
) -> dict[str, list[ResourceClaimProjection]]:
    return {
        node_id: [
            ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
            for claim in node.spec.resource_claims
        ]
        for node_id, node in projection.nodes.items()
    }


def node_roles_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.role
        for node_id, node in projection.nodes.items()
        if node.spec.role is not None
    }


def node_states_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.runtime.state
        for node_id, node in projection.nodes.items()
        if node.runtime.state is not None
    }


def node_task_regions_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.task_region_id
        for node_id, node in projection.nodes.items()
        if node.spec.task_region_id is not None
    }


def output_records_by_node_port_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[AcceptedOutputRecordPayload]]]:
    return {
        node_id: {
            port: [
                _accepted_output_record(projection, record_id)
                for record_id in record_ids
                if projection.records.by_id[record_id].record_type != "file_state"
            ]
            for port, record_ids in ports.items()
        }
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def _accepted_output_record(
    projection: GraphProjection, record_id: str
) -> AcceptedOutputRecordPayload:
    record = projection.records.by_id[record_id]
    model = OUTPUT_RECORD_MODELS_BY_TYPE[record.record_type]
    values = (
        record.__dict__
        if isinstance(record, ProjectedFanOutInputsRecord)
        else {name: _event_record_value(value) for name, value in record.__dict__.items()}
    )
    if record.record_type == "file_state":
        values = {name: value for name, value in values.items() if name != "acceptance_identity"}
    return cast(
        AcceptedOutputRecordPayload,
        model.model_validate(values),
    )


def _event_record_value(value: object) -> object:
    if isinstance(value, FrozenMap):
        return value.thaw_json()
    if isinstance(value, ProjectionModel):
        return {name: _event_record_value(item) for name, item in value.__dict__.items()}
    if isinstance(value, tuple):
        return tuple(_event_record_value(item) for item in cast(tuple[object, ...], value))
    return value


def passed_verification_candidate_ids_view(projection: GraphProjection) -> list[str]:
    return list(projection.verification.passed_candidate_ids)


def passed_verification_results_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, VerificationResultProjection]:
    return {
        record_id: VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        for record_id, result in projection.verification.passed_results_by_record_id.items()
    }


def planner_generations_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.planning.generation_by_node)


def planner_session_carryovers_view(projection: GraphProjection) -> dict[str, str | None]:
    return {
        session_id: session.carryover_record_id
        for session_id, session in projection.planning.sessions.items()
    }


def planner_sessions_view(projection: GraphProjection) -> dict[str, str]:
    return dict(projection.planning.session_id_by_node)


def ready_nodes_view(projection: GraphProjection) -> list[str]:
    return list(projection.scheduling.ready_node_ids)


def recorded_node_usage_keys_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.usage.recorded_keys)


def recovery_nodes_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, list[RecoveryNodeIndexEntry]]:
    return {
        record_id: [
            RecoveryNodeIndexEntry.model_validate(entry.model_dump(mode="json"))
            for entry in entries
        ]
        for record_id, entries in projection.verification.recovery_nodes_by_record_id.items()
    }


def retry_not_before_by_node_view(projection: GraphProjection) -> dict[str, str | None]:
    return {
        node_id: node.scheduling.retry_not_before
        for node_id, node in projection.nodes.items()
        if node.scheduling.retry_not_before is not None
    }


def task_candidates_view(
    projection: GraphProjection,
) -> dict[str, list[CandidateProjection]]:
    return {
        task_id: [
            CandidateProjection.model_validate(candidate.model_dump(mode="json"))
            for candidate in task.candidates
        ]
        for task_id, task in projection.tasks.items()
        if task.candidates
    }


def task_states_view(projection: GraphProjection) -> dict[str, str]:
    return {
        task_id: task.state for task_id, task in projection.tasks.items() if task.state is not None
    }


def verifier_verdicts_view(
    projection: GraphProjection,
) -> dict[str, VerifierVerdictProjection]:
    return {
        value.candidate_id: VerifierVerdictProjection.model_validate(value.model_dump(mode="json"))
        for value in projection.verification.verdicts_by_node.values()
    }


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    node = projection.nodes.get(node_id)
    if node is None:
        return ()
    return tuple(
        ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
        for claim in node.spec.resource_claims
    )


def node_exists(projection: GraphProjection, node_id: str) -> bool:
    """Return whether a node has been created."""
    return node_id in projection.nodes


def node_kind(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's declared kind, if it exists."""
    node = projection.nodes.get(node_id)
    return node.spec.kind if node is not None else None


def node_role(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's declared role, if supplied."""
    node = projection.nodes.get(node_id)
    return node.spec.role if node is not None else None


def node_creation_position(projection: GraphProjection, node_id: str) -> int | None:
    """Return a node's creation position, if it exists."""
    node = projection.nodes.get(node_id)
    return node.spec.creation_position if node is not None else None


def node_task_region(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's task-region identifier, if supplied."""
    node = projection.nodes.get(node_id)
    return node.spec.task_region_id if node is not None else None


def node_state(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's current runtime state, if it exists."""
    node = projection.nodes.get(node_id)
    return node.runtime.state if node is not None else None


def node_states(projection: GraphProjection) -> tuple[tuple[str, str], ...]:
    """Return node states in deterministic node-ID order."""
    return tuple(
        (node_id, node.runtime.state)
        for node_id, node in sorted(projection.nodes.items())
        if node.runtime.state is not None
    )


def node_attempt(projection: GraphProjection, node_id: str) -> int | None:
    """Return a node's current attempt number, if supplied."""
    node = projection.nodes.get(node_id)
    return node.runtime.attempt_number if node is not None else None


def node_candidate_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's current candidate identifier, if supplied."""
    node = projection.nodes.get(node_id)
    return node.runtime.candidate_id if node is not None else None


def node_failed_candidate_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's failed candidate identifier, if supplied."""
    node = projection.nodes.get(node_id)
    return node.runtime.failed_candidate_id if node is not None else None


def node_allowed_actions(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return a node's allowed actions in declaration order."""
    node = projection.nodes.get(node_id)
    return node.spec.allowed_actions if node is not None else ()


def node_preconditions(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return a node's preconditions in declaration order."""
    node = projection.nodes.get(node_id)
    return node.spec.preconditions if node is not None else ()


def node_command_definition(
    projection: GraphProjection, node_id: str
) -> Mapping[str, object] | None:
    """Return an independent command-definition copy, if supplied."""
    node = projection.nodes.get(node_id)
    if node is None or node.spec.command_definition is None:
        return None
    return _command_definition_value(node.spec.command_definition.value)


def node_last_deferred_reason(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's last scheduling deferral reason, if any."""
    node = projection.nodes.get(node_id)
    return node.scheduling.last_deferred_reason if node is not None else None


def node_retry_not_before(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's retry deadline, if one has been scheduled."""
    node = projection.nodes.get(node_id)
    return node.scheduling.retry_not_before if node is not None else None


def task_state(projection: GraphProjection, task_region_id: str) -> str | None:
    """Return a task region's current state, if it exists."""
    task = projection.tasks.get(task_region_id)
    return task.state if task is not None else None


def task_states(projection: GraphProjection) -> tuple[tuple[str, str], ...]:
    """Return task states in deterministic task-region-ID order."""
    return tuple(
        (task_id, task.state)
        for task_id, task in sorted(projection.tasks.items())
        if task.state is not None
    )


def _command_definition_value(value: FrozenMap[str, FrozenJsonValue]) -> dict[str, JsonValue]:
    """Unwrap the frozen command-definition envelope into its public mapping."""
    definition = thaw_json(value)
    while isinstance(definition, dict) and set(definition) == {"value"}:
        definition = definition["value"]
    if not isinstance(definition, dict):
        raise ValueError("command definition must decode to a JSON object")
    return definition


def _graph_record_summary(summary: GraphRecordSummaryProjection) -> GraphRecordSummary:
    """Return the exact public TypedDict shape without exposing frozen storage."""
    view: GraphRecordSummary = {}
    if summary.record_id is not None:
        view["record_id"] = summary.record_id
    if summary.record_type is not None:
        view["record_type"] = summary.record_type
    if summary.record_kind is not None:
        view["record_kind"] = summary.record_kind
    if summary.schema_ is not None:
        view["schema"] = summary.schema_
    if summary.producer_node_id is not None:
        view["producer_node_id"] = summary.producer_node_id
    if summary.producer_port is not None:
        view["producer_port"] = summary.producer_port
    if summary.position is not None:
        view["position"] = summary.position
    return view


def task_candidates(
    projection: GraphProjection, task_region_id: str
) -> tuple[CandidateProjection, ...]:
    """Return independent candidate copies in projection order."""
    task = projection.tasks.get(task_region_id)
    if task is None:
        return ()
    return tuple(
        CandidateProjection.model_validate(candidate.model_dump(mode="json"))
        for candidate in task.candidates
    )


def edge_by_id(projection: GraphProjection, edge_id: str) -> EdgeProjection | None:
    """Return an independent edge copy, if it exists."""
    edge = projection.topology.edges.get(edge_id)
    return EdgeProjection.model_validate(edge.model_dump(mode="json")) if edge is not None else None


def iter_edges(projection: GraphProjection) -> tuple[EdgeProjection, ...]:
    """Return independent edge copies in deterministic edge-ID order."""
    return tuple(
        EdgeProjection.model_validate(edge.model_dump(mode="json"))
        for _, edge in sorted(projection.topology.edges.items())
    )


def edges_from_node(projection: GraphProjection, node_id: str) -> tuple[EdgeProjection, ...]:
    """Return outgoing edges in deterministic edge-ID order."""
    return tuple(
        EdgeProjection.model_validate(edge.model_dump(mode="json"))
        for _, edge in sorted(projection.topology.edges.items())
        if edge.from_node_id == node_id
    )


def edges_to_node(projection: GraphProjection, node_id: str) -> tuple[EdgeProjection, ...]:
    """Return incoming edges in deterministic edge-ID order."""
    return tuple(
        EdgeProjection.model_validate(edge.model_dump(mode="json"))
        for _, edge in sorted(projection.topology.edges.items())
        if edge.to_node_id == node_id
    )


def input_binding_for_port(
    projection: GraphProjection, node_id: str, port: str
) -> InputBindingProjection | None:
    """Return an independent input-binding copy for a node port, if present."""
    binding = projection.topology.input_bindings.get(node_id, {}).get(port)
    return (
        InputBindingProjection.model_validate(binding.model_dump(mode="json")) if binding else None
    )


def input_bindings_for_node(
    projection: GraphProjection, node_id: str
) -> tuple[InputBindingProjection, ...]:
    """Return independent node input-binding copies in port insertion order."""
    bindings = projection.topology.input_bindings.get(node_id, {})
    return tuple(
        InputBindingProjection.model_validate(bindings[port].model_dump(mode="json"))
        for port in projection.topology.input_binding_port_order.get(node_id, ())
        if port in bindings
    )


def bound_record_ids(projection: GraphProjection, node_id: str, port: str) -> tuple[str, ...]:
    """Return record identifiers bound to a node input port in binding order."""
    binding = projection.topology.input_bindings.get(node_id, {}).get(port)
    return tuple(binding.record_ids) if binding is not None else ()


def lease_by_id(projection: GraphProjection, lease_id: str) -> LeaseProjection | None:
    """Return an independent lease copy, if it exists."""
    lease = projection.execution.leases.get(lease_id)
    return (
        LeaseProjection.model_validate(lease.model_dump(mode="json")) if lease is not None else None
    )


def iter_leases(projection: GraphProjection) -> tuple[LeaseProjection, ...]:
    """Return independent lease copies in deterministic lease-ID order."""
    return tuple(
        LeaseProjection.model_validate(lease.model_dump(mode="json"))
        for _, lease in sorted(projection.execution.leases.items())
    )


def active_leases(projection: GraphProjection) -> tuple[LeaseProjection, ...]:
    """Return active leases in deterministic lease-ID order."""
    return tuple(
        LeaseProjection.model_validate(lease.model_dump(mode="json"))
        for _, lease in sorted(projection.execution.leases.items())
        if lease.state == "active"
    )


def lease_generation(projection: GraphProjection, lease_id: str) -> int | None:
    """Return a lease generation, if the lease exists and has one."""
    lease = projection.execution.leases.get(lease_id)
    return lease.generation if lease is not None else None


def run_state(projection: GraphProjection) -> str | None:
    """Return the current lifecycle state, or ``None`` before its first event."""
    return projection.lifecycle.run_state


def completion_decision_passed(projection: GraphProjection) -> bool:
    """Return whether the latest lifecycle completion decision passed."""
    return projection.lifecycle.completion_decision_passed


def output_record_payload(
    projection: GraphProjection, record_id: str
) -> AcceptedOutputRecordPayload | None:
    """Return an independent accepted output-record payload, if present."""
    record = projection.records.by_id.get(record_id)
    if record is None or record.record_type == "file_state":
        return None
    return OutputRecordAcceptedPayload.model_validate(
        record.model_dump(mode="json", by_alias=True)
    ).root


def file_state_record(projection: GraphProjection, record_id: str) -> FileStateRecord | None:
    """Return an independent file-state record, if present."""
    record = projection.records.by_id.get(record_id)
    if record is None or record.record_type != "file_state":
        return None
    value = record.model_dump(mode="json", by_alias=True)
    value.pop("acceptance_identity", None)
    return FileStateRecord.model_validate(value)


def output_record_ids_for_node_port(
    projection: GraphProjection, node_id: str, port: str
) -> tuple[str, ...]:
    """Return output record identifiers for a node port in projection order."""
    return tuple(projection.records.ids_by_node_port.get(node_id, {}).get(port, ()))


def accepted_output_records_for_node_port(
    projection: GraphProjection, node_id: str, port: str
) -> tuple[AcceptedOutputRecord, ...]:
    """Return independent accepted output records for a node port in projection order."""
    return tuple(
        {
            "record_id": record_id,
            "payload": _accepted_output_record(projection, record_id),
        }
        for record_id in projection.records.ids_by_node_port.get(node_id, {}).get(port, ())
    )


def accepted_output_records(
    projection: GraphProjection,
) -> tuple[tuple[str, str, tuple[AcceptedOutputRecord, ...]], ...]:
    """Return outputs by sorted node/port keys and stored record order."""
    return tuple(
        (node_id, port, accepted_output_records_for_node_port(projection, node_id, port))
        for node_id, ports in sorted(projection.records.ids_by_node_port.items())
        for port in sorted(ports)
    )


def planner_generation_budget(projection: GraphProjection) -> int:
    """Return the configured planner generation budget."""
    return projection.planning.generation_budget


def planner_successor(projection: GraphProjection, node_id: str) -> str | None:
    """Return a planner node's successor, if recorded."""
    return projection.planning.successor_by_node.get(node_id)


def accepted_graph_patch_ids(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return accepted graph patch identifiers in projection order."""
    return tuple(projection.planning.accepted_patch_ids_by_node.get(node_id, ()))


def accepted_no_successor_patch_ids(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return accepted no-successor patch identifiers in projection order."""
    return tuple(projection.planning.no_successor_patch_ids_by_node.get(node_id, ()))


def accepted_no_successor_patch_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return the latest accepted no-successor patch identifier, if recorded."""
    return projection.planning.latest_no_successor_patch_id_by_node.get(node_id)


def latest_routine_snapshot_record(
    projection: GraphProjection,
) -> LatestRoutineSnapshotRecord | None:
    """Return an independent latest routine snapshot record, if present."""
    record = projection.planning.latest_routine_snapshot
    return (
        LatestRoutineSnapshotRecord.model_validate(record.model_dump(mode="json"))
        if record is not None
        else None
    )


def planner_generation(projection: GraphProjection, node_id: str) -> int | None:
    """Return a planner node's generation, if recorded."""
    return projection.planning.generation_by_node.get(node_id)


def planner_session(projection: GraphProjection, node_id: str) -> str | None:
    """Return a planner node's session identifier, if recorded."""
    return projection.planning.session_id_by_node.get(node_id)


def planner_session_state(projection: GraphProjection, session_id: str) -> str | None:
    """Return a planner session's state, if recorded."""
    session = projection.planning.sessions.get(session_id)
    return session.state if session is not None else None


def planner_session_current_node(projection: GraphProjection, session_id: str) -> str | None:
    """Return a planner session's current node, if recorded."""
    session = projection.planning.sessions.get(session_id)
    return session.current_node_id if session is not None else None


def planner_session_carryover(projection: GraphProjection, session_id: str) -> str | None:
    """Return a planner session's carryover record, if recorded."""
    session = projection.planning.sessions.get(session_id)
    return session.carryover_record_id if session is not None else None


def planner_region_label(projection: GraphProjection, node_id: str) -> str | None:
    """Return a planner node's region label, if recorded."""
    return projection.planning.region_label_by_node.get(node_id)


def approval_decision(
    projection: GraphProjection, node_id: str
) -> ApprovalDecisionProjection | None:
    """Return an independent approval decision, if present."""
    decision_id = projection.governance.approval_decision_id_by_node.get(node_id)
    decision = (
        projection.governance.approval_decisions_by_id.get(decision_id) if decision_id else None
    )
    return (
        ApprovalDecisionProjection.model_validate(decision.model_dump(mode="json"))
        if decision
        else None
    )


def authority_decision(
    projection: GraphProjection, node_id: str
) -> AuthorityDecisionProjection | None:
    """Return an independent authority decision, if present."""
    decision_id = projection.governance.authority_decision_id_by_node.get(node_id)
    decision = (
        projection.governance.authority_decisions_by_id.get(decision_id) if decision_id else None
    )
    return (
        AuthorityDecisionProjection.model_validate(decision.model_dump(mode="json"))
        if decision
        else None
    )


def oversight_decision(
    projection: GraphProjection, node_id: str
) -> OversightDecisionProjection | None:
    """Return an independent oversight decision, if present."""
    decision_id = projection.governance.oversight_decision_id_by_node.get(node_id)
    decision = (
        projection.governance.oversight_decisions_by_id.get(decision_id) if decision_id else None
    )
    return (
        OversightDecisionProjection.model_validate(decision.model_dump(mode="json"))
        if decision
        else None
    )


def decision_request(
    projection: GraphProjection, node_id: str
) -> PendingGateDecisionProjection | None:
    """Return an independent pending decision request, if present."""
    request = projection.governance.decision_requests_by_node.get(node_id)
    return (
        PendingGateDecisionProjection.model_validate(request.model_dump(mode="json"))
        if request is not None
        else None
    )


def open_proposal_blocker(
    projection: GraphProjection, proposal_id: str
) -> Mapping[str, object] | None:
    """Return an independent open-proposal blocker, if present."""
    # Proposal blocker payloads were a legacy checkpoint cache with no final
    # canonical owner.  Accepted patches retain only their resolution ID.
    return None


def authority_revision_blocker(
    projection: GraphProjection, revision_id: str
) -> Mapping[str, object] | None:
    """Return an independent authority-revision blocker, if present."""
    blocker = projection.governance.authority_revision_blockers.get(revision_id)
    return blocker.model_dump(mode="json") if blocker is not None else None


def requirement_revision(
    projection: GraphProjection, version_id: str
) -> RequirementRevisionProjection | None:
    """Return an independent requirement revision, if present."""
    revision = projection.requirements.revisions_by_id.get(version_id)
    return (
        RequirementRevisionProjection.model_validate(revision.model_dump(mode="json"))
        if revision
        else None
    )


def active_requirement_version(projection: GraphProjection, requirement_id: str) -> str | None:
    """Return a requirement's active version identifier, if recorded."""
    return projection.requirements.active_version_id_by_requirement.get(requirement_id)


def support_evidence(
    projection: GraphProjection, support_id: str
) -> SupportEvidenceProjection | None:
    """Return independent support evidence, if present."""
    evidence = projection.requirements.support_by_id.get(support_id)
    return (
        SupportEvidenceProjection.model_validate(evidence.model_dump(mode="json"))
        if evidence
        else None
    )


def cleanup_request(
    projection: GraphProjection, cleanup_id: str
) -> CleanupRequestedProjection | None:
    """Return an independent cleanup request, if present."""
    request = projection.execution.cleanup_requests_by_id.get(cleanup_id)
    return (
        CleanupRequestedProjection.model_validate(request.model_dump(mode="json"))
        if request
        else None
    )


def cleanup_applied(projection: GraphProjection, cleanup_id: str) -> bool:
    """Return whether a cleanup identifier has been applied."""
    return projection.execution.applied_cleanup_ids.get(cleanup_id, False)


def callback_idempotency_event(
    projection: GraphProjection, idempotency_key: str
) -> CallbackIdempotencyEvent | None:
    """Return an independent callback idempotency event, if present."""
    event = next(
        (
            value
            for value in projection.execution.callback_events_by_key.values()
            if value.idempotency_key == idempotency_key
        ),
        None,
    )
    return CallbackIdempotencyEvent.model_validate(event.model_dump(mode="json")) if event else None


def environment_failure(
    projection: GraphProjection, task_region_id: str
) -> EnvironmentFailureProjection | None:
    """Return an independent environment failure, if present."""
    failure = projection.execution.environment_failures_by_task.get(task_region_id)
    return (
        EnvironmentFailureProjection.model_validate(failure.model_dump(mode="json"))
        if failure is not None
        else None
    )


def environment_failures(
    projection: GraphProjection,
) -> tuple[tuple[str, EnvironmentFailureProjection], ...]:
    """Return independent environment failures in deterministic task-region-ID order."""
    return tuple(
        (
            task_region_id,
            EnvironmentFailureProjection.model_validate(failure.model_dump(mode="json")),
        )
        for task_region_id, failure in sorted(
            projection.execution.environment_failures_by_task.items()
        )
    )


def verifier_verdict(
    projection: GraphProjection, candidate_id: str
) -> VerifierVerdictProjection | None:
    """Return an independent verifier verdict for a candidate, if present."""
    # The canonical store is keyed by verifier node; this public query retains
    # the historical candidate-id lookup contract.
    verdict = next(
        (
            item
            for item in projection.verification.verdicts_by_node.values()
            if item.candidate_id == candidate_id
        ),
        None,
    )
    return (
        VerifierVerdictProjection.model_validate(verdict.model_dump(mode="json"))
        if verdict
        else None
    )


def passed_verification_result(
    projection: GraphProjection, record_id: str
) -> VerificationResultProjection | None:
    """Return an independent passed verification result, if present."""
    result = projection.verification.passed_results_by_record_id.get(record_id)
    return (
        VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        if result
        else None
    )


def failed_verification_result(
    projection: GraphProjection, record_id: str
) -> VerificationResultProjection | None:
    """Return an independent failed verification result, if present."""
    result = projection.verification.failed_results_by_record_id.get(record_id)
    return (
        VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        if result
        else None
    )


def passed_verification_results(
    projection: GraphProjection,
) -> tuple[tuple[str, VerificationResultProjection], ...]:
    """Return passed verification results in deterministic record-ID order."""
    return tuple(
        (key, VerificationResultProjection.model_validate(value.model_dump(mode="json")))
        for key, value in sorted(projection.verification.passed_results_by_record_id.items())
    )


def failed_verification_results(
    projection: GraphProjection,
) -> tuple[tuple[str, VerificationResultProjection], ...]:
    """Return failed verification results in deterministic record-ID order."""
    return tuple(
        (key, VerificationResultProjection.model_validate(value.model_dump(mode="json")))
        for key, value in sorted(projection.verification.failed_results_by_record_id.items())
    )


def passed_verification_candidate_ids(projection: GraphProjection) -> tuple[str, ...]:
    """Return passed verification candidate identifiers in projection order."""
    return tuple(projection.verification.passed_candidate_ids)


def failed_verification_candidate_ids(projection: GraphProjection) -> tuple[str, ...]:
    """Return failed verification candidate identifiers in deterministic ID order."""
    return tuple(sorted(projection.verification.failed_candidate_ids))


def recovery_nodes_for_record(
    projection: GraphProjection, record_id: str
) -> tuple[RecoveryNodeIndexEntry, ...]:
    """Return independent recovery-node index entries in projection order."""
    return tuple(
        RecoveryNodeIndexEntry.model_validate(entry.model_dump(mode="json"))
        for entry in projection.verification.recovery_nodes_by_record_id.get(record_id, ())
    )


def recovery_nodes(
    projection: GraphProjection,
) -> tuple[tuple[str, tuple[RecoveryNodeIndexEntry, ...]], ...]:
    """Return the complete recovery-node index in deterministic record-ID order."""
    return tuple(
        (record_id, recovery_nodes_for_record(projection, record_id))
        for record_id in sorted(projection.verification.recovery_nodes_by_record_id)
    )


def check_result(projection: GraphProjection, node_id: str) -> CheckResultProjection | None:
    """Return an independent check result for a node, if present."""
    result = projection.verification.check_results_by_node.get(node_id)
    return (
        CheckResultProjection.model_validate(result.model_dump(mode="json"))
        if result is not None
        else None
    )


def check_results(projection: GraphProjection) -> tuple[tuple[str, CheckResultProjection], ...]:
    """Return independent check results in deterministic node-ID order."""
    return tuple(
        (node_id, CheckResultProjection.model_validate(result.model_dump(mode="json")))
        for node_id, result in sorted(projection.verification.check_results_by_node.items())
    )


def invalid_test_block(
    projection: GraphProjection, task_region_id: str
) -> InvalidTestBlockProjection | None:
    """Return an independent invalid-test block for a task region, if present."""
    block = projection.verification.invalid_test_blocks_by_task.get(task_region_id)
    return (
        InvalidTestBlockProjection.model_validate(block.model_dump(mode="json")) if block else None
    )


def invalid_test_blocks(
    projection: GraphProjection,
) -> tuple[tuple[str, InvalidTestBlockProjection], ...]:
    """Return independent invalid-test blocks in deterministic task-region-ID order."""
    return tuple(
        (task_region_id, InvalidTestBlockProjection.model_validate(block.model_dump(mode="json")))
        for task_region_id, block in sorted(
            projection.verification.invalid_test_blocks_by_task.items()
        )
    )


def configured_gates(projection: GraphProjection, task_region_id: str) -> tuple[str, ...]:
    """Return configured gate identifiers for a task region in deterministic ID order."""
    return tuple(sorted(projection.governance.configured_gates_by_task.get(task_region_id, ())))


def gate_decision(projection: GraphProjection, task_region_id: str, gate_id: str) -> bool | None:
    """Return a task-region gate decision, if it has been recorded."""
    return projection.governance.gate_decisions_by_task.get(task_region_id, {}).get(gate_id)


def node_gate_decision(projection: GraphProjection, node_id: str) -> bool:
    """Return a node gate decision, defaulting to the established ``False`` value."""
    return projection.governance.node_gate_decisions.get(node_id, False)


def node_usage_recorded(projection: GraphProjection, usage_key: str) -> bool:
    """Return whether a node usage key has already been recorded."""
    return usage_key in projection.usage.recorded_keys
