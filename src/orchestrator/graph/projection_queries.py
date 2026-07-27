"""Pure queries over graph projection storage.

Each query owns the physical projection access and returns values that cannot
mutate projection containers.
"""

from copy import deepcopy
from collections.abc import Mapping

from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    ApprovalDecisionProjection,
    AuthorityDecisionProjection,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CheckResultProjection,
    CleanupRequestedProjection,
    EdgeProjection,
    EnvironmentFailureProjection,
    FileStateRecord,
    InputBindingProjection,
    InvalidTestBlockProjection,
    LeaseProjection,
    OversightDecisionProjection,
    PendingGateDecisionProjection,
    RequirementRevisionProjection,
    ResourceClaimProjection,
    SupportEvidenceProjection,
    VerificationResultProjection,
    VerifierVerdictProjection,
)
from orchestrator.graph.projections import (
    AcceptedOutputRecord,
    GraphProjection,
    LatestRoutineSnapshotRecord,
    RecoveryNodeIndexEntry,
)


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    return tuple(
        claim.model_copy(deep=True) for claim in projection["node_resource_claims"].get(node_id, ())
    )


def node_exists(projection: GraphProjection, node_id: str) -> bool:
    """Return whether a node has been created."""
    return node_id in projection["node_kinds"]


def node_kind(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's declared kind, if it exists."""
    return projection["node_kinds"].get(node_id)


def node_role(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's declared role, if supplied."""
    return projection["node_roles"].get(node_id)


def node_creation_position(projection: GraphProjection, node_id: str) -> int | None:
    """Return a node's creation position, if it exists."""
    return projection["node_creation_positions"].get(node_id)


def node_task_region(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's task-region identifier, if supplied."""
    return projection["node_task_regions"].get(node_id)


def node_state(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's current runtime state, if it exists."""
    return projection["node_states"].get(node_id)


def node_states(projection: GraphProjection) -> tuple[tuple[str, str], ...]:
    """Return node states in projection insertion order."""
    return tuple(projection["node_states"].items())


def node_attempt(projection: GraphProjection, node_id: str) -> int | None:
    """Return a node's current attempt number, if supplied."""
    return projection["node_attempts"].get(node_id)


def node_candidate_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's current candidate identifier, if supplied."""
    return projection["node_candidates"].get(node_id)


def node_failed_candidate_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's failed candidate identifier, if supplied."""
    return projection["node_failed_candidates"].get(node_id)


def node_allowed_actions(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return a node's allowed actions in declaration order."""
    return tuple(projection["node_allowed_actions"].get(node_id, ()))


def node_preconditions(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return a node's preconditions in declaration order."""
    return tuple(projection["node_preconditions"].get(node_id, ()))


def node_command_definition(
    projection: GraphProjection, node_id: str
) -> Mapping[str, object] | None:
    """Return an independent command-definition copy, if supplied."""
    definition = projection["node_command_definitions"].get(node_id)
    return deepcopy(definition) if definition is not None else None


def node_last_deferred_reason(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's last scheduling deferral reason, if any."""
    return projection["last_deferred_reasons"].get(node_id)


def node_retry_not_before(projection: GraphProjection, node_id: str) -> str | None:
    """Return a node's retry deadline, if one has been scheduled."""
    return projection["retry_not_before_by_node"].get(node_id)


def task_state(projection: GraphProjection, task_region_id: str) -> str | None:
    """Return a task region's current state, if it exists."""
    return projection["task_states"].get(task_region_id)


def task_states(projection: GraphProjection) -> tuple[tuple[str, str], ...]:
    """Return task states in projection insertion order."""
    return tuple(projection["task_states"].items())


def task_candidates(
    projection: GraphProjection, task_region_id: str
) -> tuple[CandidateProjection, ...]:
    """Return independent candidate copies in projection order."""
    return tuple(
        candidate.model_copy(deep=True)
        for candidate in projection["task_candidates"].get(task_region_id, ())
    )


def edge_by_id(projection: GraphProjection, edge_id: str) -> EdgeProjection | None:
    """Return an independent edge copy, if it exists."""
    edge = projection["edges"].get(edge_id)
    return edge.model_copy(deep=True) if edge is not None else None


def iter_edges(projection: GraphProjection) -> tuple[EdgeProjection, ...]:
    """Return independent edge copies in projection insertion order."""
    return tuple(edge.model_copy(deep=True) for edge in projection["edges"].values())


def edges_from_node(projection: GraphProjection, node_id: str) -> tuple[EdgeProjection, ...]:
    """Return outgoing edges in projection insertion order."""
    return tuple(
        edge.model_copy(deep=True)
        for edge in projection["edges"].values()
        if edge.from_node_id == node_id
    )


def edges_to_node(projection: GraphProjection, node_id: str) -> tuple[EdgeProjection, ...]:
    """Return incoming edges in projection insertion order."""
    return tuple(
        edge.model_copy(deep=True)
        for edge in projection["edges"].values()
        if edge.to_node_id == node_id
    )


def input_binding_for_port(
    projection: GraphProjection, node_id: str, port: str
) -> InputBindingProjection | None:
    """Return an independent input-binding copy for a node port, if present."""
    binding = projection["input_bindings"].get(node_id, {}).get(port)
    return binding.model_copy(deep=True) if binding is not None else None


def input_bindings_for_node(
    projection: GraphProjection, node_id: str
) -> tuple[InputBindingProjection, ...]:
    """Return independent node input-binding copies in port insertion order."""
    return tuple(
        binding.model_copy(deep=True)
        for binding in projection["input_bindings"].get(node_id, {}).values()
    )


def bound_record_ids(projection: GraphProjection, node_id: str, port: str) -> tuple[str, ...]:
    """Return record identifiers bound to a node input port in binding order."""
    binding = projection["input_bindings"].get(node_id, {}).get(port)
    return tuple(binding.record_ids) if binding is not None else ()


def lease_by_id(projection: GraphProjection, lease_id: str) -> LeaseProjection | None:
    """Return an independent lease copy, if it exists."""
    lease = projection["leases"].get(lease_id)
    return lease.model_copy(deep=True) if lease is not None else None


def iter_leases(projection: GraphProjection) -> tuple[LeaseProjection, ...]:
    """Return independent lease copies in projection insertion order."""
    return tuple(lease.model_copy(deep=True) for lease in projection["leases"].values())


def active_leases(projection: GraphProjection) -> tuple[LeaseProjection, ...]:
    """Return active leases in projection insertion order."""
    return tuple(
        lease.model_copy(deep=True)
        for lease in projection["leases"].values()
        if lease.state == "active"
    )


def lease_generation(projection: GraphProjection, lease_id: str) -> int | None:
    """Return a lease generation, if the lease exists and has one."""
    lease = projection["leases"].get(lease_id)
    return lease.generation if lease is not None else None


def run_state(projection: GraphProjection) -> str | None:
    """Return the current lifecycle state, or ``None`` before its first event."""
    return projection["run_state"]


def completion_decision_passed(projection: GraphProjection) -> bool:
    """Return whether the latest lifecycle completion decision passed."""
    return projection["completion_decision_passed"]


def output_record_payload(
    projection: GraphProjection, record_id: str
) -> AcceptedOutputRecordPayload | None:
    """Return an independent accepted output-record payload, if present."""
    payload = projection["output_record_payloads"].get(record_id)
    return payload.model_copy(deep=True) if payload is not None else None


def file_state_record(projection: GraphProjection, record_id: str) -> FileStateRecord | None:
    """Return an independent file-state record, if present."""
    record = projection["file_state_records"].get(record_id)
    return record.model_copy(deep=True) if record is not None else None


def output_record_ids_for_node_port(
    projection: GraphProjection, node_id: str, port: str
) -> tuple[str, ...]:
    """Return output record identifiers for a node port in projection order."""
    return tuple(projection["node_output_ports"].get(node_id, {}).get(port, ()))


def accepted_output_records_for_node_port(
    projection: GraphProjection, node_id: str, port: str
) -> tuple[AcceptedOutputRecord, ...]:
    """Return independent accepted output records for a node port in projection order."""
    return tuple(
        deepcopy(record)
        for record in projection["accepted_output_records_by_node_port"]
        .get(node_id, {})
        .get(port, ())
    )


def accepted_output_records(
    projection: GraphProjection,
) -> tuple[tuple[str, str, tuple[AcceptedOutputRecord, ...]], ...]:
    """Return outputs by sorted node/port keys and stored record order."""
    return tuple(
        (node_id, port, accepted_output_records_for_node_port(projection, node_id, port))
        for node_id, ports in sorted(projection["accepted_output_records_by_node_port"].items())
        for port in sorted(ports)
    )


def planner_generation_budget(projection: GraphProjection) -> int:
    """Return the configured planner generation budget."""
    return projection["planner_generation_budget"]


def planner_successor(projection: GraphProjection, node_id: str) -> str | None:
    """Return a planner node's successor, if recorded."""
    return projection["planner_successors"].get(node_id)


def accepted_graph_patch_ids(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return accepted graph patch identifiers in projection order."""
    return tuple(projection["accepted_graph_patches_by_node"].get(node_id, ()))


def accepted_no_successor_patch_ids(projection: GraphProjection, node_id: str) -> tuple[str, ...]:
    """Return accepted no-successor patch identifiers in projection order."""
    return tuple(projection["accepted_no_successor_patches_by_node"].get(node_id, ()))


def accepted_no_successor_patch_id(projection: GraphProjection, node_id: str) -> str | None:
    """Return the latest accepted no-successor patch identifier, if recorded."""
    return projection["accepted_no_successor_patch_ids_by_node"].get(node_id)


def latest_routine_snapshot_record(
    projection: GraphProjection,
) -> LatestRoutineSnapshotRecord | None:
    """Return an independent latest routine snapshot record, if present."""
    record = projection["latest_routine_snapshot_record"]
    return record.model_copy(deep=True) if record is not None else None


def planner_generation(projection: GraphProjection, node_id: str) -> int | None:
    """Return a planner node's generation, if recorded."""
    return projection["planner_generations"].get(node_id)


def planner_session(projection: GraphProjection, node_id: str) -> str | None:
    """Return a planner node's session identifier, if recorded."""
    return projection["planner_sessions"].get(node_id)


def planner_session_state(projection: GraphProjection, session_id: str) -> str | None:
    """Return a planner session's state, if recorded."""
    return projection["planner_session_states"].get(session_id)


def planner_session_current_node(projection: GraphProjection, session_id: str) -> str | None:
    """Return a planner session's current node, if recorded."""
    return projection["planner_session_current_nodes"].get(session_id)


def planner_session_carryover(projection: GraphProjection, session_id: str) -> str | None:
    """Return a planner session's carryover record, if recorded."""
    return projection["planner_session_carryovers"].get(session_id)


def planner_region_label(projection: GraphProjection, node_id: str) -> str | None:
    """Return a planner node's region label, if recorded."""
    return projection["planner_region_labels"].get(node_id)


def approval_decision(
    projection: GraphProjection, node_id: str
) -> ApprovalDecisionProjection | None:
    """Return an independent approval decision, if present."""
    decision = projection["approval_decisions"].get(node_id)
    return decision.model_copy(deep=True) if decision is not None else None


def authority_decision(
    projection: GraphProjection, node_id: str
) -> AuthorityDecisionProjection | None:
    """Return an independent authority decision, if present."""
    decision = projection["authority_decisions"].get(node_id)
    return decision.model_copy(deep=True) if decision is not None else None


def oversight_decision(
    projection: GraphProjection, node_id: str
) -> OversightDecisionProjection | None:
    """Return an independent oversight decision, if present."""
    decision = projection["oversight_decisions"].get(node_id)
    return decision.model_copy(deep=True) if decision is not None else None


def decision_request(
    projection: GraphProjection, node_id: str
) -> PendingGateDecisionProjection | None:
    """Return an independent pending decision request, if present."""
    request = projection["decision_request_details"].get(node_id)
    return request.model_copy(deep=True) if request is not None else None


def open_proposal_blocker(
    projection: GraphProjection, proposal_id: str
) -> Mapping[str, object] | None:
    """Return an independent open-proposal blocker, if present."""
    blocker = projection["open_proposal_blockers"].get(proposal_id)
    return deepcopy(blocker) if blocker is not None else None


def authority_revision_blocker(
    projection: GraphProjection, revision_id: str
) -> Mapping[str, object] | None:
    """Return an independent authority-revision blocker, if present."""
    blocker = projection["authority_revision_blockers"].get(revision_id)
    return deepcopy(blocker) if blocker is not None else None


def requirement_revision(
    projection: GraphProjection, version_id: str
) -> RequirementRevisionProjection | None:
    """Return an independent requirement revision, if present."""
    revision = projection["requirement_revisions"].get(version_id)
    return revision.model_copy(deep=True) if revision is not None else None


def active_requirement_version(projection: GraphProjection, requirement_id: str) -> str | None:
    """Return a requirement's active version identifier, if recorded."""
    return projection["active_requirement_versions"].get(requirement_id)


def support_evidence(
    projection: GraphProjection, support_id: str
) -> SupportEvidenceProjection | None:
    """Return independent support evidence, if present."""
    evidence = projection["support_evidence"].get(support_id)
    return evidence.model_copy(deep=True) if evidence is not None else None


def cleanup_request(
    projection: GraphProjection, cleanup_id: str
) -> CleanupRequestedProjection | None:
    """Return an independent cleanup request, if present."""
    request = projection["cleanup_requested_events"].get(cleanup_id)
    return request.model_copy(deep=True) if request is not None else None


def cleanup_applied(projection: GraphProjection, cleanup_id: str) -> bool:
    """Return whether a cleanup identifier has been applied."""
    return projection["cleanup_applied_ids"].get(cleanup_id, False)


def callback_idempotency_event(
    projection: GraphProjection, idempotency_key: str
) -> CallbackIdempotencyEvent | None:
    """Return an independent callback idempotency event, if present."""
    event = projection["callback_idempotency_events"].get(idempotency_key)
    return event.model_copy(deep=True) if event is not None else None


def environment_failure(
    projection: GraphProjection, task_region_id: str
) -> EnvironmentFailureProjection | None:
    """Return an independent environment failure, if present."""
    failure = projection["environment_failures"].get(task_region_id)
    return failure.model_copy(deep=True) if failure is not None else None


def environment_failures(
    projection: GraphProjection,
) -> tuple[tuple[str, EnvironmentFailureProjection], ...]:
    """Return independent environment failures in projection insertion order."""
    return tuple(
        (task_region_id, failure.model_copy(deep=True))
        for task_region_id, failure in projection["environment_failures"].items()
    )


def verifier_verdict(
    projection: GraphProjection, candidate_id: str
) -> VerifierVerdictProjection | None:
    """Return an independent verifier verdict for a candidate, if present."""
    verdict = projection["verifier_verdicts"].get(candidate_id)
    return verdict.model_copy(deep=True) if verdict is not None else None


def passed_verification_result(
    projection: GraphProjection, record_id: str
) -> VerificationResultProjection | None:
    """Return an independent passed verification result, if present."""
    result = projection["passed_verification_results_by_record_id"].get(record_id)
    return result.model_copy(deep=True) if result is not None else None


def failed_verification_result(
    projection: GraphProjection, record_id: str
) -> VerificationResultProjection | None:
    """Return an independent failed verification result, if present."""
    result = projection["failed_verification_results_by_record_id"].get(record_id)
    return result.model_copy(deep=True) if result is not None else None


def passed_verification_results(
    projection: GraphProjection,
) -> tuple[tuple[str, VerificationResultProjection], ...]:
    """Return passed verification results in projection insertion order."""
    return tuple(
        (key, value.model_copy(deep=True))
        for key, value in projection["passed_verification_results_by_record_id"].items()
    )


def failed_verification_results(
    projection: GraphProjection,
) -> tuple[tuple[str, VerificationResultProjection], ...]:
    """Return failed verification results in projection insertion order."""
    return tuple(
        (key, value.model_copy(deep=True))
        for key, value in projection["failed_verification_results_by_record_id"].items()
    )


def passed_verification_candidate_ids(projection: GraphProjection) -> tuple[str, ...]:
    """Return passed verification candidate identifiers in projection order."""
    return tuple(projection["passed_verification_candidate_ids"])


def failed_verification_candidate_ids(projection: GraphProjection) -> tuple[str, ...]:
    """Return failed verification candidate identifiers in projection insertion order."""
    return tuple(projection["failed_verification_candidate_ids"])


def recovery_nodes_for_record(
    projection: GraphProjection, record_id: str
) -> tuple[RecoveryNodeIndexEntry, ...]:
    """Return independent recovery-node index entries in projection order."""
    return tuple(
        entry.model_copy(deep=True)
        for entry in projection["recovery_nodes_by_record_id"].get(record_id, ())
    )


def recovery_nodes(
    projection: GraphProjection,
) -> tuple[tuple[str, tuple[RecoveryNodeIndexEntry, ...]], ...]:
    """Return the complete recovery-node index in projection insertion order."""
    return tuple(
        (record_id, recovery_nodes_for_record(projection, record_id))
        for record_id in projection["recovery_nodes_by_record_id"]
    )


def check_result(projection: GraphProjection, node_id: str) -> CheckResultProjection | None:
    """Return an independent check result for a node, if present."""
    result = projection["check_results"].get(node_id)
    return result.model_copy(deep=True) if result is not None else None


def check_results(projection: GraphProjection) -> tuple[tuple[str, CheckResultProjection], ...]:
    """Return independent check results in projection insertion order."""
    return tuple(
        (node_id, result.model_copy(deep=True))
        for node_id, result in projection["check_results"].items()
    )


def invalid_test_block(
    projection: GraphProjection, task_region_id: str
) -> InvalidTestBlockProjection | None:
    """Return an independent invalid-test block for a task region, if present."""
    block = projection["invalid_test_blocks"].get(task_region_id)
    return block.model_copy(deep=True) if block is not None else None


def invalid_test_blocks(
    projection: GraphProjection,
) -> tuple[tuple[str, InvalidTestBlockProjection], ...]:
    """Return independent invalid-test blocks in projection insertion order."""
    return tuple(
        (task_region_id, block.model_copy(deep=True))
        for task_region_id, block in projection["invalid_test_blocks"].items()
    )


def configured_gates(projection: GraphProjection, task_region_id: str) -> tuple[str, ...]:
    """Return configured gate identifiers for a task region in insertion order."""
    return tuple(projection["configured_gates"].get(task_region_id, ()))


def gate_decision(projection: GraphProjection, task_region_id: str, gate_id: str) -> bool | None:
    """Return a task-region gate decision, if it has been recorded."""
    return projection["gate_decisions"].get(task_region_id, {}).get(gate_id)


def node_gate_decision(projection: GraphProjection, node_id: str) -> bool:
    """Return a node gate decision, defaulting to the established ``False`` value."""
    return projection["node_gate_decisions"].get(node_id, False)


def node_usage_recorded(projection: GraphProjection, usage_key: str) -> bool:
    """Return whether a node usage key has already been recorded."""
    return usage_key in projection["recorded_node_usage_keys"]
