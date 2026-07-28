"""Public query-boundary and migration-disposition behavior."""

from datetime import UTC, datetime
from pathlib import Path
import pytest
import yaml
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    ApprovalDecisionProjection,
    AuthorityDecisionProjection,
    CallbackIdempotencyEvent,
    CheckResultProjection,
    CleanupRequestedProjection,
    EnvironmentFailureProjection,
    EventEnvelope,
    FileStateRecord,
    InvalidTestBlockProjection,
    RequirementRevisionProjection,
    RecoveryNodeIndexEntry,
    SupportEvidenceProjection,
    VerificationResultProjection,
    VerifierVerdictProjection,
    active_leases,
    active_requirement_version,
    accepted_graph_patch_ids,
    accepted_output_records,
    accepted_output_records_for_node_port,
    accepted_no_successor_patch_id,
    accepted_no_successor_patch_ids,
    approval_decision,
    authority_decision,
    authority_revision_blocker,
    bound_record_ids,
    callback_idempotency_event,
    check_result,
    check_results,
    cleanup_applied,
    cleanup_request,
    decision_request,
    configured_gates,
    build_projection,
    completion_decision_passed,
    edge_by_id,
    edges_from_node,
    edges_to_node,
    environment_failure,
    environment_failures,
    file_state_record,
    failed_verification_candidate_ids,
    failed_verification_result,
    failed_verification_results,
    gate_decision,
    input_binding_for_port,
    input_bindings_for_node,
    initial_projection,
    invalid_test_block,
    invalid_test_blocks,
    iter_edges,
    iter_leases,
    lease_by_id,
    lease_generation,
    latest_routine_snapshot_record,
    node_allowed_actions,
    node_attempt,
    node_candidate_id,
    node_command_definition,
    node_creation_position,
    node_exists,
    node_failed_candidate_id,
    node_gate_decision,
    node_states,
    node_kind,
    node_last_deferred_reason,
    node_preconditions,
    node_retry_not_before,
    node_role,
    node_state,
    node_task_region,
    open_proposal_blocker,
    output_record_ids_for_node_port,
    output_record_payload,
    oversight_decision,
    planner_generation,
    planner_generation_budget,
    planner_region_label,
    planner_session,
    planner_session_carryover,
    planner_session_current_node,
    planner_session_state,
    planner_successor,
    passed_verification_candidate_ids,
    passed_verification_result,
    passed_verification_results,
    recovery_nodes,
    recovery_nodes_for_record,
    requirement_revision,
    resource_claims_for_node,
    run_state,
    task_candidates,
    task_state,
    task_states,
    node_usage_recorded,
    support_evidence,
    verifier_verdict,
)
from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    AccessOccurrence,
    IncompleteMigrationDispositionError,
    MigrationDisposition,
    QueryMigrationManifest,
    UnclassifiedMigrationSite,
    classify_node_task_edge_binding_and_lease_domains,
    classify_lifecycle_domain,
    disposition_site_key,
    load_query_migration_manifest,
    query_migration_skeleton,
    validate_query_migration_manifest,
)
from tests.unit.graph_test_utils import canonical_event_payload
from tests.graph_fr17_fixture import less_used_events


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_manifest.yaml"


def test_lifecycle_queries_preserve_missing_and_default_values() -> None:
    projection = initial_projection()

    assert run_state(projection) is None
    assert completion_decision_passed(projection) is False


def test_task_3c_queries_preserve_missing_values_and_planner_default() -> None:
    projection = initial_projection()

    assert output_record_payload(projection, "missing") is None
    assert file_state_record(projection, "missing") is None
    assert output_record_ids_for_node_port(projection, "missing", "missing") == ()
    assert planner_generation_budget(projection) == 8
    assert planner_successor(projection, "missing") is None
    assert planner_generation(projection, "missing") is None
    assert planner_session(projection, "missing") is None
    assert planner_session_state(projection, "missing") is None
    assert planner_session_current_node(projection, "missing") is None
    assert planner_session_carryover(projection, "missing") is None
    assert planner_region_label(projection, "missing") is None
    assert latest_routine_snapshot_record(projection) is None
    assert approval_decision(projection, "missing") is None
    assert authority_decision(projection, "missing") is None
    assert oversight_decision(projection, "missing") is None
    assert decision_request(projection, "missing") is None
    assert open_proposal_blocker(projection, "missing") is None
    assert authority_revision_blocker(projection, "missing") is None
    assert requirement_revision(projection, "missing") is None
    assert active_requirement_version(projection, "missing") is None
    assert support_evidence(projection, "missing") is None
    assert cleanup_request(projection, "missing") is None
    assert cleanup_applied(projection, "missing") is False
    assert callback_idempotency_event(projection, "missing") is None
    assert environment_failure(projection, "missing") is None
    assert environment_failures(projection) == ()


def test_verification_and_recovery_queries_preserve_missing_values() -> None:
    projection = initial_projection()

    assert verifier_verdict(projection, "missing") is None
    assert passed_verification_result(projection, "missing") is None
    assert failed_verification_result(projection, "missing") is None
    assert passed_verification_candidate_ids(projection) == ()
    assert failed_verification_candidate_ids(projection) == ()
    assert recovery_nodes_for_record(projection, "missing") == ()
    assert check_result(projection, "missing") is None
    assert check_results(projection) == ()
    assert invalid_test_block(projection, "missing") is None
    assert invalid_test_blocks(projection) == ()
    assert configured_gates(projection, "missing") == ()
    assert gate_decision(projection, "missing", "missing") is None
    assert node_gate_decision(projection, "missing") is False
    assert node_states(projection) == ()
    assert task_states(projection) == ()
    assert accepted_output_records_for_node_port(projection, "missing", "missing") == ()
    assert node_usage_recorded(projection, "missing") is False


def test_verification_and_recovery_queries_preserve_order_and_isolation() -> None:
    projection = initial_projection()
    projection["verifier_verdicts"]["candidate-1"] = VerifierVerdictProjection(
        candidate_id="candidate-1", verdict="passed", position=1
    )
    projection["passed_verification_results_by_record_id"]["passed-1"] = (
        VerificationResultProjection(
            node_id="verifier-1", record_id="passed-1", candidate_id="candidate-1"
        )
    )
    projection["failed_verification_results_by_record_id"]["failed-1"] = (
        VerificationResultProjection(
            node_id="verifier-2", record_id="failed-1", candidate_id="candidate-2"
        )
    )
    projection["passed_verification_results_by_record_id"]["passed-2"] = (
        VerificationResultProjection(node_id="verifier-2", record_id="passed-2")
    )
    projection["failed_verification_results_by_record_id"]["failed-2"] = (
        VerificationResultProjection(node_id="verifier-3", record_id="failed-2")
    )
    projection["passed_verification_candidate_ids"].extend(("candidate-2", "candidate-1"))
    projection["failed_verification_candidate_ids"].update(
        {"candidate-3": True, "candidate-2": True}
    )
    projection["recovery_nodes_by_record_id"]["failed-1"] = [
        RecoveryNodeIndexEntry(node_id="recovery-2", recovery_reason="second"),
        RecoveryNodeIndexEntry(node_id="recovery-1", recovery_reason="first"),
    ]
    projection["recovery_nodes_by_record_id"]["failed-2"] = [
        RecoveryNodeIndexEntry(node_id="recovery-3", recovery_reason="third")
    ]
    projection["node_states"].update({"node-2": "running", "node-1": "ready"})
    projection["task_states"].update({"task-2": "pending", "task-1": "accepted"})
    projection["recorded_node_usage_keys"]["usage-1"] = True
    projection["accepted_output_records_by_node_port"]["node-2"] = {
        "z-port": [{"record_id": "record-3", "payload": {"nested": ["original"]}}],
        "a-port": [
            {"record_id": "record-2", "payload": {"nested": ["original"]}},
            {"record_id": "record-1", "payload": {"nested": ["original"]}},
        ],
    }
    projection["accepted_output_records_by_node_port"]["node-1"] = {
        "b-port": [{"record_id": "record-0", "payload": {"nested": ["original"]}}]
    }
    projection["check_results"]["check-2"] = CheckResultProjection(
        node_id="check-2", status="failed", position=2, candidate_record_ids=["candidate-2"]
    )
    projection["check_results"]["check-1"] = CheckResultProjection(
        node_id="check-1", status="passed", position=1, candidate_record_ids=["candidate-1"]
    )
    projection["invalid_test_blocks"]["region-2"] = InvalidTestBlockProjection(position=2)
    projection["invalid_test_blocks"]["region-1"] = InvalidTestBlockProjection(position=1)
    projection["configured_gates"]["region-1"] = {"gate-2": True, "gate-1": True}
    projection["gate_decisions"]["region-1"] = {"gate-2": False}
    projection["node_gate_decisions"]["gate-node"] = True

    assert verifier_verdict(projection, "candidate-1") is not None
    assert passed_verification_result(projection, "passed-1") is not None
    assert failed_verification_result(projection, "failed-1") is not None
    assert passed_verification_candidate_ids(projection) == ("candidate-2", "candidate-1")
    assert failed_verification_candidate_ids(projection) == ("candidate-3", "candidate-2")
    assert node_states(projection) == (("node-2", "running"), ("node-1", "ready"))
    assert task_states(projection) == (("task-2", "pending"), ("task-1", "accepted"))
    assert node_usage_recorded(projection, "usage-1") is True
    assert node_usage_recorded(projection, "missing-usage") is False
    assert tuple(
        record["record_id"]
        for record in accepted_output_records_for_node_port(projection, "node-2", "a-port")
    ) == ("record-2", "record-1")
    assert tuple((node_id, port) for node_id, port, _ in accepted_output_records(projection)) == (
        ("node-1", "b-port"),
        ("node-2", "a-port"),
        ("node-2", "z-port"),
    )
    assert tuple(record_id for record_id, _ in passed_verification_results(projection)) == (
        "passed-1",
        "passed-2",
    )
    assert tuple(record_id for record_id, _ in failed_verification_results(projection)) == (
        "failed-1",
        "failed-2",
    )
    assert tuple(record_id for record_id, _ in recovery_nodes(projection)) == (
        "failed-1",
        "failed-2",
    )
    assert tuple(entry.node_id for entry in recovery_nodes_for_record(projection, "failed-1")) == (
        "recovery-2",
        "recovery-1",
    )
    assert tuple(node_id for node_id, _ in check_results(projection)) == ("check-2", "check-1")
    assert tuple(region_id for region_id, _ in invalid_test_blocks(projection)) == (
        "region-2",
        "region-1",
    )
    assert configured_gates(projection, "region-1") == ("gate-2", "gate-1")
    assert gate_decision(projection, "region-1", "gate-2") is False
    assert node_gate_decision(projection, "gate-node") is True

    verdict = verifier_verdict(projection, "candidate-1")
    assert verdict is not None
    with pytest.raises(ValidationError):
        verdict.position = 99
    result = check_result(projection, "check-2")
    assert result is not None
    result.candidate_record_ids.append("changed")
    fresh_result = check_result(projection, "check-2")
    assert fresh_result is not None
    assert fresh_result.candidate_record_ids == ["candidate-2"]
    assert (
        verifier_verdict(projection, "candidate-1")
        is not projection["verifier_verdicts"]["candidate-1"]
    )
    assert (
        passed_verification_result(projection, "passed-1")
        is not projection["passed_verification_results_by_record_id"]["passed-1"]
    )
    assert (
        failed_verification_result(projection, "failed-1")
        is not projection["failed_verification_results_by_record_id"]["failed-1"]
    )
    assert (
        passed_verification_results(projection)[0][1]
        is not projection["passed_verification_results_by_record_id"]["passed-1"]
    )
    assert (
        failed_verification_results(projection)[0][1]
        is not projection["failed_verification_results_by_record_id"]["failed-1"]
    )
    assert (
        recovery_nodes_for_record(projection, "failed-1")[0]
        is not projection["recovery_nodes_by_record_id"]["failed-1"][0]
    )
    assert (
        recovery_nodes(projection)[0][1][0]
        is not projection["recovery_nodes_by_record_id"]["failed-1"][0]
    )
    accepted = accepted_output_records(projection)[1][2][0]
    accepted["payload"]["nested"].append("changed")
    assert accepted_output_records_for_node_port(projection, "node-2", "a-port")[0]["payload"] == {
        "nested": ["original"]
    }
    assert (
        invalid_test_block(projection, "region-1")
        is not projection["invalid_test_blocks"]["region-1"]
    )
    assert check_results(projection)[0][1] is not projection["check_results"]["check-2"]
    assert (
        invalid_test_blocks(projection)[0][1] is not projection["invalid_test_blocks"]["region-2"]
    )


def test_task_3c_queries_preserve_present_values_order_and_mutation_isolation() -> None:
    projection = build_projection(less_used_events("task-3c-query"))
    projection["file_state_records"]["file-state-query"] = FileStateRecord(
        record_id="file-state-query", record_type="file_state", cleanup_excluded_paths=["secret"]
    )
    projection["output_record_payloads"]["file-state-query"] = projection["file_state_records"][
        "file-state-query"
    ]
    projection["node_output_ports"]["worker-source"] = {
        "failure_record": ["failure-record-1", "failure-record-2"]
    }
    projection["planner_successors"]["planner-fr17"] = "planner-next"
    projection["accepted_graph_patches_by_node"]["planner-fr17"] = ["patch-1", "patch-2"]
    projection["accepted_no_successor_patches_by_node"]["planner-fr17"] = ["no-successor-1"]
    projection["accepted_no_successor_patch_ids_by_node"]["planner-fr17"] = "no-successor-1"
    projection["planner_generations"]["planner-fr17"] = 3
    projection["planner_sessions"]["planner-fr17"] = "session-1"
    projection["planner_session_states"]["session-1"] = "active"
    projection["planner_session_current_nodes"]["session-1"] = "planner-fr17"
    projection["planner_session_carryovers"]["session-1"] = "carryover-1"
    projection["planner_region_labels"]["planner-fr17"] = "region-1"
    projection["open_proposal_blockers"]["proposal-1"] = {"reasons": ["original"]}
    projection["authority_revision_blockers"]["revision-1"] = {"reasons": ["original"]}
    projection["approval_decisions"]["approval-1"] = ApprovalDecisionProjection(
        node_id="approval-1", decision="approved", scope={"items": ["original"]}
    )
    projection["authority_decisions"]["authority-1"] = AuthorityDecisionProjection(
        node_id="authority-1", decision="granted", scope={"items": ["original"]}
    )
    projection["requirement_revisions"]["version-1"] = RequirementRevisionProjection(
        requirement_id="requirement-1",
        version_id="version-1",
        change_classification="clarification",
        requires_authority=False,
        position=1,
        validation_strengthening=False,
    )
    projection["active_requirement_versions"]["requirement-1"] = "version-1"
    projection["support_evidence"]["support-1"] = SupportEvidenceProjection(
        support_id="support-1",
        evidence_id="evidence-1",
        requirement_id="requirement-1",
        requirement_version_id="version-1",
        status="current",
        position=1,
    )
    projection["cleanup_requested_events"]["cleanup-1"] = CleanupRequestedProjection(
        cleanup_id="cleanup-1", position=1, paths=["secret"]
    )
    projection["cleanup_applied_ids"]["cleanup-1"] = True
    projection["callback_idempotency_events"]["key-1"] = CallbackIdempotencyEvent(
        event_type="callback_accepted",
        node_id="worker-source",
        idempotency_key="key-1",
        outcome="accepted",
        payload={"nested": ["original"]},
    )
    projection["environment_failures"]["region-2"] = EnvironmentFailureProjection(
        position=2, task_region_id="region-2", reason="second"
    )
    projection["environment_failures"]["region-1"] = EnvironmentFailureProjection(
        position=1, task_region_id="region-1", reason="first"
    )

    assert output_record_payload(projection, "recovery-plan-1") is not None
    assert output_record_payload(projection, "file-state-query") is not None
    assert file_state_record(projection, "file-state-query") is not None
    assert output_record_ids_for_node_port(projection, "worker-source", "failure_record") == (
        "failure-record-1",
        "failure-record-2",
    )
    assert planner_successor(projection, "planner-fr17") == "planner-next"
    assert planner_generation_budget(projection) == 13
    assert accepted_graph_patch_ids(projection, "planner-fr17") == ("patch-1", "patch-2")
    assert accepted_no_successor_patch_ids(projection, "planner-fr17") == ("no-successor-1",)
    assert accepted_no_successor_patch_id(projection, "planner-fr17") == "no-successor-1"
    assert accepted_graph_patch_ids(projection, "missing") == ()
    assert accepted_no_successor_patch_ids(projection, "missing") == ()
    assert accepted_no_successor_patch_id(projection, "missing") is None
    assert planner_generation(projection, "planner-fr17") == 3
    assert planner_session(projection, "planner-fr17") == "session-1"
    assert planner_session_state(projection, "session-1") == "active"
    assert planner_session_current_node(projection, "session-1") == "planner-fr17"
    assert planner_session_carryover(projection, "session-1") == "carryover-1"
    assert planner_region_label(projection, "planner-fr17") == "region-1"
    snapshot = latest_routine_snapshot_record(projection)
    assert snapshot is not None
    assert snapshot.record_id == "routine-snapshot-fr17"
    assert snapshot.producer_node_id == "root-fr17"
    assert snapshot.port == "snapshot"
    assert decision_request(projection, "gate-pending") is not None
    assert approval_decision(projection, "approval-1") is not None
    assert authority_decision(projection, "authority-1") is not None
    assert oversight_decision(projection, "oversight-1") is not None
    assert open_proposal_blocker(projection, "proposal-1") == {"reasons": ["original"]}
    assert authority_revision_blocker(projection, "revision-1") == {"reasons": ["original"]}
    assert requirement_revision(projection, "version-1") is not None
    assert active_requirement_version(projection, "requirement-1") == "version-1"
    assert support_evidence(projection, "support-1") is not None
    assert cleanup_request(projection, "cleanup-1") is not None
    assert cleanup_applied(projection, "cleanup-1") is True
    assert callback_idempotency_event(projection, "key-1") is not None
    assert environment_failure(projection, "region-1") is not None
    assert tuple(region_id for region_id, _ in environment_failures(projection)) == (
        "region-2",
        "region-1",
    )

    blocker = open_proposal_blocker(projection, "proposal-1")
    assert blocker is not None
    reasons = blocker["reasons"]
    assert isinstance(reasons, list)
    reasons.append("changed")
    authority_blocker = authority_revision_blocker(projection, "revision-1")
    assert authority_blocker is not None
    authority_reasons = authority_blocker["reasons"]
    assert isinstance(authority_reasons, list)
    authority_reasons.append("changed")
    callback = callback_idempotency_event(projection, "key-1")
    assert callback is not None and callback.payload is not None
    nested = callback.payload["nested"]
    assert isinstance(nested, list)
    nested.append("changed")
    file_state = file_state_record(projection, "file-state-query")
    assert file_state is not None
    file_state.cleanup_excluded_paths.append("changed")
    output_payload = output_record_payload(projection, "file-state-query")
    assert isinstance(output_payload, FileStateRecord)
    output_payload.cleanup_excluded_paths.append("output-changed")
    approval = approval_decision(projection, "approval-1")
    assert approval is not None and approval.scope is not None
    approval.scope["items"].append("changed")
    authority = authority_decision(projection, "authority-1")
    assert authority is not None and authority.scope is not None
    authority.scope["items"].append("changed")
    cleanup = cleanup_request(projection, "cleanup-1")
    assert cleanup is not None
    cleanup.paths.append("changed")
    request = decision_request(projection, "gate-pending")
    assert request is not None and request.options is not None
    request.options.append("changed")
    oversight = oversight_decision(projection, "oversight-1")
    assert oversight is not None and oversight.scope is not None
    oversight.scope["items"].append("changed")

    snapshot = latest_routine_snapshot_record(projection)
    assert snapshot is not None
    with pytest.raises(ValidationError):
        snapshot.record_id = "changed"
    revision = requirement_revision(projection, "version-1")
    assert revision is not None
    with pytest.raises(ValidationError):
        revision.position = 99
    support = support_evidence(projection, "support-1")
    assert support is not None
    with pytest.raises(ValidationError):
        support.status = "changed"
    environment = environment_failure(projection, "region-1")
    assert environment is not None
    with pytest.raises(ValidationError):
        environment.position = 99
    environment_collection = environment_failures(projection)
    with pytest.raises(ValidationError):
        environment_collection[0][1].position = 99

    assert open_proposal_blocker(projection, "proposal-1") == {"reasons": ["original"]}
    assert authority_revision_blocker(projection, "revision-1") == {"reasons": ["original"]}
    fresh_callback = callback_idempotency_event(projection, "key-1")
    assert fresh_callback is not None and fresh_callback.payload == {"nested": ["original"]}
    fresh_file_state = file_state_record(projection, "file-state-query")
    assert fresh_file_state is not None
    assert fresh_file_state.cleanup_excluded_paths == ["secret"]
    fresh_output_payload = output_record_payload(projection, "file-state-query")
    assert isinstance(fresh_output_payload, FileStateRecord)
    assert fresh_output_payload.cleanup_excluded_paths == ["secret"]
    fresh_approval = approval_decision(projection, "approval-1")
    assert fresh_approval is not None and fresh_approval.scope == {"items": ["original"]}
    fresh_authority = authority_decision(projection, "authority-1")
    assert fresh_authority is not None and fresh_authority.scope == {"items": ["original"]}
    fresh_cleanup = cleanup_request(projection, "cleanup-1")
    assert fresh_cleanup is not None and fresh_cleanup.paths == ["secret"]
    fresh_request = decision_request(projection, "gate-pending")
    assert fresh_request is not None and fresh_request.options == ["approved", "rejected"]
    fresh_oversight = oversight_decision(projection, "oversight-1")
    assert fresh_oversight is not None
    assert fresh_oversight.scope == {"items": ["original"]}
    fresh_snapshot = latest_routine_snapshot_record(projection)
    assert fresh_snapshot is not None
    assert fresh_snapshot.record_id == "routine-snapshot-fr17"
    fresh_requirement = requirement_revision(projection, "version-1")
    assert fresh_requirement is not projection["requirement_revisions"]["version-1"]
    assert fresh_requirement.position == 1
    fresh_support = support_evidence(projection, "support-1")
    assert fresh_support is not projection["support_evidence"]["support-1"]
    assert fresh_support.status == "current"
    fresh_environment = environment_failure(projection, "region-1")
    assert fresh_environment is not projection["environment_failures"]["region-1"]
    assert fresh_environment.position == 1
    environments = environment_failures(projection)
    assert environments[0][1] is not projection["environment_failures"]["region-2"]
    assert tuple(failure.position for _, failure in environments) == (2, 1)


def test_lifecycle_queries_read_active_and_completed_event_projections() -> None:
    active = build_projection((_event("active", "run_lifecycle_changed", _lifecycle("active")),))
    completed = build_projection(
        (
            _event("active", "run_lifecycle_changed", _lifecycle("active")),
            _event(
                "decision",
                "output_record_accepted",
                {
                    "record_id": "decision-1",
                    "record_type": "completion_decision",
                    "producer_node_id": "gate-final",
                    "port": "completion_decision",
                    "value": {"status": "passed"},
                },
            ),
            _event("completed", "run_lifecycle_changed", _lifecycle("completed")),
        )
    )

    assert run_state(active) == "active"
    assert run_state(completed) == "completed"
    assert completion_decision_passed(completed) is True


def test_node_and_task_queries_preserve_missing_values() -> None:
    projection = initial_projection()

    assert node_exists(projection, "missing") is False
    assert node_kind(projection, "missing") is None
    assert node_role(projection, "missing") is None
    assert node_creation_position(projection, "missing") is None
    assert node_task_region(projection, "missing") is None
    assert node_state(projection, "missing") is None
    assert node_attempt(projection, "missing") is None
    assert node_candidate_id(projection, "missing") is None
    assert node_failed_candidate_id(projection, "missing") is None
    assert node_allowed_actions(projection, "missing") == ()
    assert node_preconditions(projection, "missing") == ()
    assert node_command_definition(projection, "missing") is None
    assert node_last_deferred_reason(projection, "missing") is None
    assert node_retry_not_before(projection, "missing") is None
    assert resource_claims_for_node(projection, "missing") == ()
    assert task_state(projection, "missing") is None
    assert task_candidates(projection, "missing") == ()


def test_topology_and_lease_queries_preserve_fixture_order_and_selection() -> None:
    projection = build_projection(less_used_events("query-fixture"))

    assert node_exists(projection, "worker-source") is True
    assert node_kind(projection, "worker-source") == "worker"
    assert node_role(projection, "worker-source") == "builder"
    assert node_task_region(projection, "worker-source") == "task-fr17"
    assert node_state(projection, "recovery-1") == "completed"
    assert node_last_deferred_reason(projection, "review-1") == "merge_conflicts"
    assert node_allowed_actions(projection, "worker-source") == (
        "submit_records",
        "raise_appeal",
    )
    assert node_preconditions(projection, "recovery-1") == ("failure_record_bound",)
    assert node_command_definition(projection, "recovery-1") is not None
    assert tuple(edge.edge_id for edge in iter_edges(projection)) == (
        "edge-failure-recovery",
        "edge-recovery-consumer",
        "edge-decision-consumer",
    )
    assert edge_by_id(projection, "edge-failure-recovery") is not None
    assert tuple(edge.edge_id for edge in edges_from_node(projection, "recovery-1")) == (
        "edge-recovery-consumer",
    )
    assert tuple(edge.edge_id for edge in edges_to_node(projection, "consumer-1")) == (
        "edge-recovery-consumer",
        "edge-decision-consumer",
    )
    assert bound_record_ids(projection, "recovery-1", "failure_record") == ("failure-record-1",)
    assert input_binding_for_port(projection, "recovery-1", "failure_record") is not None
    assert tuple(
        binding.to_port for binding in input_bindings_for_node(projection, "consumer-1")
    ) == ("outstanding_failures",)
    assert lease_by_id(projection, "lease-recovery") is not None
    assert lease_generation(projection, "lease-recovery") == 1
    assert tuple(lease.lease_id for lease in iter_leases(projection)) == ("lease-recovery",)
    assert active_leases(projection) == ()


def test_node_task_and_lease_queries_preserve_present_and_missing_values() -> None:
    projection = _query_projection()

    assert node_creation_position(projection, "worker-query") == 1
    assert node_attempt(projection, "worker-query") == 2
    assert node_candidate_id(projection, "worker-query") == "candidate-current"
    assert node_failed_candidate_id(projection, "worker-query") == "candidate-failed"
    assert node_retry_not_before(projection, "worker-query") == "2026-01-01T00:01:00+00:00"
    assert task_state(projection, "task-query") == "pending"
    assert tuple(
        candidate.candidate_id for candidate in task_candidates(projection, "task-query")
    ) == ("candidate-current",)
    assert resource_claims_for_node(projection, "worker-query")[0].paths == ["src/"]
    assert tuple(lease.lease_id for lease in active_leases(projection)) == ("lease-query",)
    assert edge_by_id(projection, "missing") is None
    assert input_binding_for_port(projection, "worker-query", "missing") is None
    assert lease_by_id(projection, "missing") is None


def test_query_results_are_mutation_isolated_from_projection_storage() -> None:
    projection = _query_projection()

    definition = node_command_definition(projection, "worker-query")
    assert definition is not None
    definition["nested"]["values"].append("changed")
    candidate = task_candidates(projection, "task-query")[0]
    candidate.file_state_record_ids.append("changed")
    claim = resource_claims_for_node(projection, "worker-query")[0]
    assert claim.paths is not None
    claim.paths.append("changed")
    lease = lease_by_id(projection, "lease-query")
    assert lease is not None
    assert lease.resource_claims[0].paths is not None
    lease.resource_claims[0].paths.append("changed")
    binding = input_binding_for_port(projection, "worker-query", "input")
    assert binding is not None
    binding.record_ids.append("changed")

    fresh_definition = node_command_definition(projection, "worker-query")
    assert fresh_definition is not None
    assert fresh_definition["nested"] == {"values": ["original"]}
    assert task_candidates(projection, "task-query")[0].file_state_record_ids == ["file-state-1"]
    assert resource_claims_for_node(projection, "worker-query")[0].paths == ["src/"]
    fresh_lease = lease_by_id(projection, "lease-query")
    assert fresh_lease is not None
    assert fresh_lease.resource_claims[0].paths == ["worktree/"]
    fresh_binding = input_binding_for_port(projection, "worker-query", "input")
    assert fresh_binding is not None
    assert fresh_binding.record_ids == ["record-1"]


def test_disposition_site_key_is_stable_without_source_position() -> None:
    first = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state']",
        diagnostic_code=None,
    )
    second = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state']",
        diagnostic_code=None,
    )

    assert first == second


def test_diagnostic_site_keys_distinguish_repeated_identical_patterns() -> None:
    first = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state'].values()",
        diagnostic_code="unsupported_call",
        same_pattern_ordinal=0,
    )
    second = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state'].values()",
        diagnostic_code="unsupported_call",
        same_pattern_ordinal=1,
    )

    assert first != second


def test_partial_manifest_reports_exact_unclassified_inventory_counts() -> None:
    manifest = QueryMigrationManifest(
        baseline_revision="baseline",
        dispositions=(),
    )
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="a" * 64,
                relative_path="src/example.py",
                qualified_function="read",
                normalized_expression="projection['run_state']",
                same_expression_ordinal=0,
                old_field_name="run_state",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="not_applicable",
            ),
        ),
        diagnostics=(),
    )

    with pytest.raises(IncompleteMigrationDispositionError) as raised:
        validate_query_migration_manifest(manifest, inventory, Path.cwd())

    assert raised.value.remaining_counts == {"lifecycle": 1}


def test_lifecycle_classification_covers_its_complete_generated_domain() -> None:
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="c" * 64,
                relative_path="src/example.py",
                qualified_function="read",
                normalized_expression="projection['run_state']",
                same_expression_ordinal=0,
                old_field_name="run_state",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="not_applicable",
            ),
            AccessOccurrence(
                occurrence_id="b" * 64,
                relative_path="src/example.py",
                qualified_function="read",
                normalized_expression="projection['node_states']",
                same_expression_ordinal=0,
                old_field_name="node_states",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=2,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
        ),
        diagnostics=(),
    )

    manifest = classify_lifecycle_domain(query_migration_skeleton(inventory, Path.cwd()))

    assert validate_query_migration_manifest(
        manifest, inventory, Path.cwd(), domain="lifecycle"
    ) == {"lifecycle": 1}


def test_node_and_lease_classification_covers_their_generated_domains() -> None:
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="d" * 64,
                relative_path="src/example.py",
                qualified_function="read_node",
                normalized_expression='projection["node_states"]',
                same_expression_ordinal=0,
                old_field_name="node_states",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
            AccessOccurrence(
                occurrence_id="e" * 64,
                relative_path="src/orchestrator/graph_runtime/dispatch.py",
                qualified_function="read_lease",
                normalized_expression='projection["leases"]',
                same_expression_ordinal=0,
                old_field_name="leases",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=2,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
        ),
        diagnostics=(),
    )

    reviewed = MigrationDisposition(
        site_key="d" * 64,
        disposition="query_transform",
        relative_path="src/example.py",
        qualified_function="read_node",
        normalized_source_pattern='projection["node_states"]',
        diagnostic_code=None,
        reason="Reviewed direct node-state read.",
    )
    manifest = classify_node_task_edge_binding_and_lease_domains(
        query_migration_skeleton(inventory, Path.cwd()), (reviewed,)
    )

    assert validate_query_migration_manifest(
        manifest, inventory, Path.cwd(), domain="node_task_edge_binding"
    ) == {"node_task_edge_binding": 1}
    with pytest.raises(IncompleteMigrationDispositionError) as raised:
        validate_query_migration_manifest(manifest, inventory, Path.cwd(), domain="lease")

    assert raised.value.remaining_counts == {"lease": 1}


def test_closed_domain_classification_accepts_only_reviewed_approved_core_keys() -> None:
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="f" * 64,
                relative_path="src/orchestrator/graph/projection_queries.py",
                qualified_function="approved_query",
                normalized_expression='projection["file_state_records"]',
                same_expression_ordinal=0,
                old_field_name="file_state_records",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
        ),
        diagnostics=(),
    )
    reviewed = MigrationDisposition(
        site_key="f" * 64,
        disposition="approved_core",
        relative_path="src/orchestrator/graph/projection_queries.py",
        qualified_function="approved_query",
        normalized_source_pattern='projection["file_state_records"]',
        diagnostic_code=None,
        reason="Reviewed exact query storage read.",
    )

    classified = classify_node_task_edge_binding_and_lease_domains(
        query_migration_skeleton(inventory, Path.cwd()), (reviewed,)
    )

    assert classified.dispositions == (reviewed,)
    assert not classified.unclassified_sites


def test_manifest_load_canonicalizes_yaml_key_chunks_and_rejects_key_aliases(
    tmp_path: Path,
) -> None:
    key = "a" * 64
    payload = {
        "baseline_revision": "baseline",
        "dispositions": [
            {
                "site_key": ["a" * 8] * 8,
                "disposition": "query_transform",
                "relative_path": "src/example.py",
                "qualified_function": "read",
                "normalized_source_pattern": "projection['run_state']",
                "diagnostic_code": None,
                "reason": "Use a lifecycle query.",
            }
        ],
        "unclassified_sites": [
            {
                "site_key": key,
                "relative_path": "src/example.py",
                "qualified_function": "read",
                "normalized_source_pattern": "projection['node_states']",
                "diagnostic_code": None,
                "domain": "node_task_edge_binding",
            }
        ],
    }
    path = tmp_path / "ledger.yaml"
    path.write_text(yaml.safe_dump(payload))

    with pytest.raises(ValidationError, match="duplicate migration disposition site key"):
        load_query_migration_manifest(path)
    with pytest.raises(ValidationError):
        MigrationDisposition.model_validate(payload["dispositions"][0])


def test_manifest_load_rejects_malformed_canonical_key_chunks(tmp_path: Path) -> None:
    path = tmp_path / "ledger.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "baseline_revision": "baseline",
                "dispositions": [],
                "unclassified_sites": [
                    {
                        "site_key": ["a" * 8] * 7,
                        "relative_path": "src/example.py",
                        "qualified_function": "read",
                        "normalized_source_pattern": "projection['run_state']",
                        "diagnostic_code": None,
                        "domain": "lifecycle",
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="eight lowercase hex groups"):
        load_query_migration_manifest(path)


@pytest.mark.parametrize(
    "field_name",
    ("relative_path", "qualified_function", "normalized_source_pattern", "reason"),
)
def test_disposition_rejects_blank_required_text(field_name: str) -> None:
    values = {
        "site_key": "a" * 64,
        "disposition": "query_transform",
        "relative_path": "src/example.py",
        "qualified_function": "read",
        "normalized_source_pattern": "projection['run_state']",
        "diagnostic_code": None,
        "reason": "Use a lifecycle query.",
    }
    values[field_name] = " \t"

    with pytest.raises(ValidationError, match="must not be blank"):
        MigrationDisposition.model_validate(values)


def test_manifest_rejects_blank_baseline_and_unclassified_domain() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        QueryMigrationManifest(baseline_revision=" ", dispositions=())
    with pytest.raises(ValidationError, match="must not be blank"):
        UnclassifiedMigrationSite(
            site_key="a" * 64,
            relative_path="src/example.py",
            qualified_function="read",
            normalized_source_pattern="projection['run_state']",
            domain="\n",
        )


def _event(event_id: str, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id="run-1",
        position={"active": 0, "decision": 1, "completed": 2}[event_id],
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def _lifecycle(to_state: str) -> dict[str, object]:
    return {
        "command_type": "run_lifecycle",
        "from_state": "queued" if to_state == "active" else "active",
        "to_state": to_state,
        "trigger": "test",
    }


def _query_projection():
    events = (
        _query_event(
            1,
            "node_created",
            {
                "node_id": "worker-query",
                "kind": "worker",
                "state": "ready",
                "task_region_id": "task-query",
                "attempt_number": 2,
                "candidate_id": "candidate-current",
                "failed_candidate_id": "candidate-failed",
                "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["src/"]}],
                "command_definition": {"nested": {"values": ["original"]}},
            },
        ),
        _query_event(
            2,
            "runtime_retry_scheduled",
            {
                "node_id": "worker-query",
                "lease_id": "lease-query",
                "generation": 1,
                "policy": "retry",
                "reason": "test",
                "retry_not_before": "2026-01-01T00:01:00+00:00",
            },
        ),
        _query_event(
            3,
            "output_record_accepted",
            {
                "record_id": "record-1",
                "producer_node_id": "worker-query",
                "task_region_id": "task-query",
                "candidate_id": "candidate-current",
                "attempt_number": 2,
                "file_state_record_ids": ["file-state-1"],
            },
        ),
        _query_event(
            4,
            "input_bound",
            {
                "edge_id": "edge-query",
                "to_node_id": "worker-query",
                "to_port": "input",
                "record_ids": ["record-1"],
                "bound_at_position": 4,
            },
        ),
        _query_event(
            5,
            "lease_granted",
            {
                "lease_id": "lease-query",
                "node_id": "worker-query",
                "task_region_id": "lease-task",
                "generation": 1,
                "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["worktree/"]}],
            },
        ),
    )
    return build_projection(events)


def _query_event(position: int, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"query-{position}",
        run_id="query-run",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )
