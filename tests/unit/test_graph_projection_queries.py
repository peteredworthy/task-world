"""Public query-boundary and migration-disposition behavior."""

from datetime import UTC, datetime
from copy import deepcopy
from pathlib import Path
import pytest
import yaml
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FileStateRecord,
    GraphProjection,
    active_leases,
    active_requirement_version,
    accepted_graph_patch_ids,
    accepted_graph_patches_by_node_view,
    accepted_no_successor_patches_by_node_view,
    accepted_output_records,
    accepted_output_records_by_node_port_view,
    accepted_record_summaries_by_id_view,
    active_requirement_versions_view,
    accepted_output_records_for_node_port,
    accepted_no_successor_patch_id,
    accepted_no_successor_patch_ids,
    approval_decision,
    approval_decisions_view,
    authority_decision,
    authority_decisions_view,
    authority_revision_blocker,
    action_count_by_node_kind_view,
    bound_record_ids,
    callback_idempotency_event,
    callback_idempotency_events_view,
    check_result,
    check_results,
    check_results_view,
    cleanup_applied,
    cleanup_applied_ids_view,
    cleanup_request,
    cleanup_requested_events_view,
    decision_request,
    decision_request_details_view,
    execution_count_by_node_kind_view,
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
    failed_verification_candidate_ids_view,
    failed_verification_result,
    failed_verification_results,
    failed_verification_results_by_record_id_view,
    gate_decision,
    input_binding_for_port,
    input_bindings_for_node,
    input_bindings_view,
    initial_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
    invalid_test_block,
    invalid_test_blocks,
    invalid_test_blocks_view,
    iter_edges,
    iter_leases,
    lease_by_id,
    lease_generation,
    latest_routine_snapshot_record,
    latency_ms_by_node_kind_view,
    node_allowed_actions,
    node_allowed_actions_view,
    node_attempt,
    node_attempts_view,
    node_candidate_id,
    node_command_definition,
    node_command_definitions_view,
    node_creation_position,
    node_creation_payloads_view,
    node_creation_positions_view,
    node_exists,
    node_failed_candidate_id,
    node_failed_candidates_view,
    node_gate_decision,
    node_gate_decisions_view,
    node_pending_appeals_view,
    node_states,
    node_states_view,
    node_kind,
    node_last_deferred_reason,
    last_deferred_reasons_view,
    node_preconditions,
    node_preconditions_view,
    node_retry_not_before,
    node_role,
    node_roles_view,
    node_state,
    node_task_region,
    node_resource_claims_view,
    node_output_ports_view,
    open_proposal_blocker,
    output_record_ids_for_node_port,
    output_record_payload,
    output_record_payloads_view,
    output_records_by_node_port_view,
    oversight_decision,
    planner_generation,
    planner_generations_view,
    planner_generation_budget,
    planner_region_label,
    planner_session,
    planner_session_carryover,
    planner_session_current_node,
    planner_session_state,
    planner_successor,
    passed_verification_candidate_ids,
    passed_verification_candidate_ids_view,
    passed_verification_result,
    passed_verification_results,
    passed_verification_results_by_record_id_view,
    recovery_nodes,
    recovery_nodes_by_record_id_view,
    recovery_nodes_for_record,
    ready_nodes_view,
    requirement_revision,
    requirement_revisions_view,
    recorded_node_usage_keys_view,
    resource_claims_for_node,
    support_evidence_view,
    tokens_by_node_kind_view,
    tokens_by_node_view,
    run_state,
    retry_not_before_by_node_view,
    task_candidates,
    task_candidates_view,
    task_state,
    task_states,
    node_usage_recorded,
    support_evidence,
    verifier_verdict,
    verifier_verdicts_view,
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
from tests.unit.graph_projection_behavior_cases import behavior_cases, case_projection, fold_events


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
    projection = GraphProjection.model_validate(
        {
            "nodes": {
                "node-2": {
                    "spec": {"node_id": "node-2", "creation_position": 2},
                    "runtime": {"state": "running"},
                },
                "node-1": {
                    "spec": {"node_id": "node-1", "creation_position": 1},
                    "runtime": {"state": "ready"},
                },
            },
            "tasks": {"task-2": {"state": "pending"}, "task-1": {"state": "accepted"}},
            "verification": {
                "verdicts_by_node": {
                    "verifier-1": {
                        "candidate_id": "candidate-1",
                        "verdict": "passed",
                        "position": 1,
                    }
                },
                "passed_results_by_record_id": {
                    "passed-1": {
                        "node_id": "verifier-1",
                        "record_id": "passed-1",
                        "candidate_id": "candidate-1",
                    },
                    "passed-2": {"node_id": "verifier-2", "record_id": "passed-2"},
                },
                "failed_results_by_record_id": {
                    "failed-1": {
                        "node_id": "verifier-2",
                        "record_id": "failed-1",
                        "candidate_id": "candidate-2",
                    },
                    "failed-2": {"node_id": "verifier-3", "record_id": "failed-2"},
                },
                "passed_candidate_ids": ["candidate-2", "candidate-1"],
                "failed_candidate_ids": {"candidate-3": True, "candidate-2": True},
                "recovery_nodes_by_record_id": {
                    "failed-1": [
                        {"node_id": "recovery-2", "recovery_reason": "second"},
                        {"node_id": "recovery-1", "recovery_reason": "first"},
                    ],
                    "failed-2": [{"node_id": "recovery-3", "recovery_reason": "third"}],
                },
                "check_results_by_node": {
                    "check-2": {
                        "node_id": "check-2",
                        "status": "failed",
                        "position": 2,
                        "candidate_record_ids": ["candidate-2"],
                    },
                    "check-1": {
                        "node_id": "check-1",
                        "status": "passed",
                        "position": 1,
                        "candidate_record_ids": ["candidate-1"],
                    },
                },
                "invalid_test_blocks_by_task": {
                    "region-2": {"position": 2},
                    "region-1": {"position": 1},
                },
            },
            "governance": {
                "configured_gates_by_task": {"region-1": {"gate-2": True, "gate-1": True}},
                "gate_decisions_by_task": {"region-1": {"gate-2": False}},
                "node_gate_decisions": {"gate-node": True},
            },
            "usage": {"recorded_keys": {"usage-1": True}},
        }
    )

    assert verifier_verdict(projection, "candidate-1") is not None
    assert passed_verification_result(projection, "passed-1") is not None
    assert failed_verification_result(projection, "failed-1") is not None
    assert passed_verification_candidate_ids(projection) == ("candidate-2", "candidate-1")
    assert failed_verification_candidate_ids(projection) == ("candidate-2", "candidate-3")
    assert node_states(projection) == (("node-1", "ready"), ("node-2", "running"))
    assert task_states(projection) == (("task-1", "accepted"), ("task-2", "pending"))
    assert node_usage_recorded(projection, "usage-1") is True
    assert node_usage_recorded(projection, "missing-usage") is False
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
    assert tuple(node_id for node_id, _ in check_results(projection)) == ("check-1", "check-2")
    assert tuple(region_id for region_id, _ in invalid_test_blocks(projection)) == (
        "region-1",
        "region-2",
    )
    assert configured_gates(projection, "region-1") == ("gate-1", "gate-2")
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


def test_task_3c_queries_preserve_present_values_order_and_mutation_isolation() -> None:
    projection = GraphProjection.model_validate(
        {
            "planning": {
                "generation_budget": 13,
                "successor_by_node": {"planner": "next"},
                "accepted_patch_ids_by_node": {"planner": ["patch-1", "patch-2"]},
                "no_successor_patch_ids_by_node": {"planner": ["no-successor-1"]},
                "latest_no_successor_patch_id_by_node": {"planner": "no-successor-1"},
                "generation_by_node": {"planner": 3},
                "session_id_by_node": {"planner": "session-1"},
                "sessions": {
                    "session-1": {
                        "state": "active",
                        "current_node_id": "planner",
                        "carryover_record_id": "carryover-1",
                    }
                },
                "region_label_by_node": {"planner": "region-1"},
            },
            "requirements": {
                "revisions_by_id": {
                    "version-1": {
                        "requirement_id": "requirement-1",
                        "version_id": "version-1",
                        "change_classification": "clarification",
                        "requires_authority": False,
                        "position": 1,
                        "validation_strengthening": False,
                    }
                },
                "active_version_id_by_requirement": {"requirement-1": "version-1"},
                "support_by_id": {
                    "support-1": {
                        "support_id": "support-1",
                        "evidence_id": "evidence-1",
                        "requirement_id": "requirement-1",
                        "requirement_version_id": "version-1",
                        "status": "current",
                        "position": 1,
                    }
                },
            },
            "execution": {
                "cleanup_requests_by_id": {
                    "cleanup-1": {"cleanup_id": "cleanup-1", "position": 1, "paths": ["secret"]}
                },
                "applied_cleanup_ids": {"cleanup-1": True},
                "callback_events_by_key": {
                    "key-1": {
                        "event_type": "callback_accepted",
                        "node_id": "worker",
                        "idempotency_key": "key-1",
                        "outcome": "accepted",
                        "payload": {"nested": ["original"]},
                    }
                },
                "environment_failures_by_task": {
                    "region-2": {"position": 2, "task_region_id": "region-2", "reason": "second"},
                    "region-1": {"position": 1, "task_region_id": "region-1", "reason": "first"},
                },
            },
        }
    )

    assert planner_generation_budget(projection) == 13
    assert planner_successor(projection, "planner") == "next"
    assert accepted_graph_patch_ids(projection, "planner") == ("patch-1", "patch-2")
    assert accepted_no_successor_patch_ids(projection, "planner") == ("no-successor-1",)
    assert accepted_no_successor_patch_id(projection, "planner") == "no-successor-1"
    assert planner_generation(projection, "planner") == 3
    assert planner_session(projection, "planner") == "session-1"
    assert planner_session_state(projection, "session-1") == "active"
    assert planner_session_current_node(projection, "session-1") == "planner"
    assert planner_session_carryover(projection, "session-1") == "carryover-1"
    assert planner_region_label(projection, "planner") == "region-1"
    assert active_requirement_version(projection, "requirement-1") == "version-1"
    assert requirement_revision(projection, "version-1") is not None
    assert support_evidence(projection, "support-1") is not None
    assert cleanup_request(projection, "cleanup-1") is not None
    assert cleanup_applied(projection, "cleanup-1") is True
    assert callback_idempotency_event(projection, "key-1") is not None
    assert tuple(region_id for region_id, _ in environment_failures(projection)) == (
        "region-1",
        "region-2",
    )


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
    projection = GraphProjection.model_validate(
        {
            "topology": {
                "edges": {
                    "edge-1": {
                        "edge_id": "edge-1",
                        "from_node_id": "source",
                        "from_port": "out",
                        "to_node_id": "target",
                        "to_port": "input",
                    },
                    "edge-2": {
                        "edge_id": "edge-2",
                        "from_node_id": "other",
                        "from_port": "out",
                        "to_node_id": "target",
                        "to_port": "other",
                    },
                },
                "input_bindings": {
                    "target": {
                        "input": {
                            "edge_id": "edge-1",
                            "to_node_id": "target",
                            "to_port": "input",
                            "record_ids": ["record-1"],
                            "bound_at_position": 1,
                        }
                    }
                },
                "input_binding_port_order": {"target": ["input"]},
            },
            "execution": {
                "leases": {
                    "lease-active": {
                        "lease_id": "lease-active",
                        "state": "active",
                        "generation": 1,
                    },
                    "lease-released": {
                        "lease_id": "lease-released",
                        "state": "released",
                        "generation": 2,
                    },
                }
            },
        }
    )

    assert tuple(edge.edge_id for edge in iter_edges(projection)) == ("edge-1", "edge-2")
    assert edge_by_id(projection, "edge-1") is not None
    assert tuple(edge.edge_id for edge in edges_from_node(projection, "source")) == ("edge-1",)
    assert tuple(edge.edge_id for edge in edges_to_node(projection, "target")) == (
        "edge-1",
        "edge-2",
    )
    assert bound_record_ids(projection, "target", "input") == ("record-1",)
    assert input_binding_for_port(projection, "target", "input") is not None
    assert tuple(binding.to_port for binding in input_bindings_for_node(projection, "target")) == (
        "input",
    )
    assert lease_generation(projection, "lease-active") == 1
    assert tuple(lease.lease_id for lease in iter_leases(projection)) == (
        "lease-active",
        "lease-released",
    )
    assert tuple(lease.lease_id for lease in active_leases(projection)) == ("lease-active",)


def test_input_bindings_preserve_first_port_insertion_order_across_updates_and_checkpoints() -> (
    None
):
    projection = build_projection(
        [
            _query_event(1, "node_created", {"node_id": "source", "kind": "worker"}),
            _query_event(2, "node_created", {"node_id": "target", "kind": "worker"}),
            _query_event(
                3,
                "output_record_accepted",
                {
                    "record_id": "record-1",
                    "record_kind": "output",
                    "record_type": "fan_out_inputs",
                    "producer_node_id": "source",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": {},
                },
            ),
            _query_event(
                4,
                "edge_created",
                {
                    "edge_id": "edge-a",
                    "from_node_id": "source",
                    "from_port": "candidate",
                    "to_node_id": "target",
                    "to_port": "a",
                },
            ),
            _query_event(
                5,
                "edge_created",
                {
                    "edge_id": "edge-b",
                    "from_node_id": "source",
                    "from_port": "candidate",
                    "to_node_id": "target",
                    "to_port": "b",
                },
            ),
            _query_event(
                6,
                "input_bound",
                {
                    "edge_id": "edge-a",
                    "to_node_id": "target",
                    "to_port": "a",
                    "record_ids": ["record-1"],
                    "bound_at_position": 6,
                },
            ),
            _query_event(
                7,
                "input_bound",
                {
                    "edge_id": "edge-b",
                    "to_node_id": "target",
                    "to_port": "b",
                    "record_ids": ["record-1"],
                    "bound_at_position": 7,
                },
            ),
            _query_event(
                8,
                "input_bound",
                {
                    "edge_id": "edge-a",
                    "to_node_id": "target",
                    "to_port": "a",
                    "record_ids": ["record-1"],
                    "bound_at_position": 8,
                },
            ),
        ]
    )

    assert tuple(binding.to_port for binding in input_bindings_for_node(projection, "target")) == (
        "a",
        "b",
    )
    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    assert tuple(binding.to_port for binding in input_bindings_for_node(restored, "target")) == (
        "a",
        "b",
    )
    assert tuple(input_bindings_view(restored)["target"]) == ("a", "b")


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


@pytest.mark.parametrize(
    "case",
    tuple(case for case in behavior_cases() if case.mutate_query_result is not None),
    ids=lambda case: case.event_type,
)
def test_matrix_public_query_results_cannot_mutate_projection_storage(case) -> None:
    _, projection = case_projection(case)
    checkpoint = deepcopy(projection_to_checkpoint(projection))
    original = case.query(projection)

    assert case.mutate_query_result is not None
    case.mutate_query_result(original)

    assert projection_to_checkpoint(projection) == checkpoint
    case.assert_outcome(fold_events(case.prefix), projection)


def test_exact_collection_views_preserve_shape_and_isolate_nested_values() -> None:
    projection = _query_projection()

    mapping_views = (
        accepted_no_successor_patches_by_node_view,
        action_count_by_node_kind_view,
        approval_decisions_view,
        authority_decisions_view,
        accepted_output_records_by_node_port_view,
        accepted_record_summaries_by_id_view,
        active_requirement_versions_view,
        callback_idempotency_events_view,
        check_results_view,
        cleanup_applied_ids_view,
        cleanup_requested_events_view,
        decision_request_details_view,
        execution_count_by_node_kind_view,
        failed_verification_candidate_ids_view,
        failed_verification_results_by_record_id_view,
        invalid_test_blocks_view,
        last_deferred_reasons_view,
        latency_ms_by_node_kind_view,
        node_allowed_actions_view,
        node_attempts_view,
        node_command_definitions_view,
        node_creation_positions_view,
        node_creation_payloads_view,
        node_gate_decisions_view,
        node_failed_candidates_view,
        node_pending_appeals_view,
        node_preconditions_view,
        node_resource_claims_view,
        node_output_ports_view,
        node_roles_view,
        output_records_by_node_port_view,
        output_record_payloads_view,
        passed_verification_results_by_record_id_view,
        planner_generations_view,
        recorded_node_usage_keys_view,
        recovery_nodes_by_record_id_view,
        requirement_revisions_view,
        retry_not_before_by_node_view,
        task_candidates_view,
        support_evidence_view,
        tokens_by_node_kind_view,
        tokens_by_node_view,
        verifier_verdicts_view,
    )
    assert all(isinstance(view(projection), dict) for view in mapping_views)
    assert isinstance(passed_verification_candidate_ids_view(projection), list)

    states = node_states_view(projection)
    bindings = input_bindings_view(projection)
    patches = accepted_graph_patches_by_node_view(projection)
    ready = ready_nodes_view(projection)

    assert isinstance(states, dict)
    assert isinstance(bindings["worker-query"], dict)
    states["worker-query"] = "changed"
    bindings["worker-query"]["input"].record_ids.append("changed")
    patches.setdefault("worker-query", []).append("changed")
    ready.append("changed")

    assert node_states_view(projection)["worker-query"] == "ready"
    assert input_bindings_view(projection)["worker-query"]["input"].record_ids == ["record-1"]
    assert accepted_graph_patches_by_node_view(projection).get("worker-query", []) == []
    assert "changed" not in ready_nodes_view(projection)


def test_action_count_by_node_kind_view_returns_grouped_usage_totals() -> None:
    projection = build_projection(
        (
            _query_event(
                1,
                "node_created",
                {"node_id": "worker-actions", "kind": "worker", "state": "ready"},
            ),
            _query_event(
                2,
                "node_usage_recorded",
                {
                    "node_id": "worker-actions",
                    "node_kind": "worker",
                    "execution_id": "execution-actions",
                    "usage_index": 0,
                    "usage_count": 1,
                    "usage_key": "execution-actions:0",
                    "model": "model-actions",
                    "num_actions": 3,
                },
            ),
        )
    )

    assert action_count_by_node_kind_view(projection) == {"worker": 3}


def test_output_record_view_thaws_projected_verification_evidence_for_event_transport() -> None:
    projection = build_projection(
        (
            _query_event(
                1,
                "node_created",
                {"node_id": "verifier-serialization", "kind": "verifier", "state": "ready"},
            ),
            _query_event(
                2,
                "output_record_accepted",
                {
                    "record_id": "verification-serialization",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "verifier-serialization",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": "candidate-serialization",
                    "outcome": "failed",
                    "value": {"outcome": "failed", "grades": []},
                    "evidence": {"nested": {"record_ids": ["candidate-serialization"]}},
                },
            ),
        )
    )

    record = output_records_by_node_port_view(projection)["verifier-serialization"][
        "verification_report"
    ][0]
    payload = record.model_dump(mode="json")
    event = EventEnvelope(
        event_id="verification-transport",
        run_id="query-run",
        position=3,
        event_type="output_record_accepted",
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )

    assert payload["evidence"] == {"nested": {"record_ids": ["candidate-serialization"]}}
    assert '"evidence"' in event.model_dump_json()


def test_accepted_output_record_view_hides_file_state_acceptance_identity() -> None:
    projection = build_projection(
        (
            _query_event(
                1,
                "node_created",
                {"node_id": "worker-file-state", "kind": "worker", "state": "ready"},
            ),
            _query_event(
                2,
                "file_state_accepted",
                {
                    "record_id": "file-state-serialization",
                    "record_kind": "file_state",
                    "record_type": "file_state",
                    "producer_node_id": "worker-file-state",
                    "snapshot_id": "snapshot-file-state",
                    "base_snapshot_id": "base-file-state",
                    "git": {
                        "commit_sha": "commit-file-state",
                        "tree_sha": "tree-file-state",
                        "ref": "refs/orchestrator/snapshots/snapshot-file-state",
                    },
                },
            ),
        )
    )

    record = accepted_output_records_by_node_port_view(projection)["worker-file-state"][
        "file_state"
    ][0]["payload"]

    assert "acceptance_identity" not in record.model_dump(mode="json")


def test_accepted_output_records_for_node_port_returns_canonical_file_state() -> None:
    projection = _file_state_query_projection()

    records = accepted_output_records_for_node_port(
        projection, "worker-file-state-query", "file_state"
    )

    assert len(records) == 1
    _assert_public_file_state_payload(records[0]["payload"])


def test_accepted_output_records_aggregate_returns_canonical_file_state() -> None:
    projection = _file_state_query_projection()

    records = accepted_output_records(projection)

    assert len(records) == 1
    assert records[0][:2] == ("worker-file-state-query", "file_state")
    _assert_public_file_state_payload(records[0][2][0]["payload"])


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


def _file_state_query_projection():
    return build_projection(
        (
            _query_event(
                1,
                "node_created",
                {"node_id": "worker-file-state-query", "kind": "worker", "state": "ready"},
            ),
            _query_event(
                2,
                "file_state_accepted",
                {
                    "record_id": "file-state-query",
                    "record_kind": "file_state",
                    "record_type": "file_state",
                    "producer_node_id": "worker-file-state-query",
                    "snapshot_id": "snapshot-query",
                    "base_snapshot_id": "base-query",
                    "git": {
                        "commit_sha": "commit-query",
                        "tree_sha": "tree-query",
                        "ref": "refs/orchestrator/snapshots/snapshot-query",
                    },
                    "verdict": "captured",
                    "patch_bundle_id": "patch-query",
                    "tree_snapshot_id": "tree-snapshot-query",
                    "position": 2,
                    "task_region_id": "task-query",
                    "candidate_id": "candidate-query",
                    "compromised": True,
                    "superseded_pending": True,
                    "supersedes_record_id": "file-state-before-query",
                    "superseded_by_record_id": "file-state-after-query",
                    "cleanup_id": "cleanup-query",
                    "cleanup_excluded_paths": ["secret.txt"],
                    "cleanup_reason": "secret_detected",
                    "cleanup_applied_event_id": "cleanup-applied-query",
                    "compromised_snapshot_deleted": True,
                    "compromised_paths": ["secret.txt"],
                },
            ),
        )
    )


def _assert_public_file_state_payload(payload: FileStateRecord) -> None:
    value = payload.model_dump(mode="json", by_alias=True)
    assert "acceptance_identity" not in value
    assert value == {
        "record_type": "file_state",
        "schema_version": None,
        "producer_port": None,
        "created_at": None,
        "graph_position": None,
        "run_id": "query-run",
        "payload": None,
        "provenance": None,
        "record_id": "file-state-query",
        "record_kind": "file_state",
        "snapshot_id": "snapshot-query",
        "base_snapshot_id": "base-query",
        "producer_node_id": "worker-file-state-query",
        "port": "file_state",
        "schema": "FileStateRecord",
        "git": {
            "commit_sha": "commit-query",
            "tree_sha": "tree-query",
            "ref": "refs/orchestrator/snapshots/snapshot-query",
            "diff_summary": None,
            "no_commit_reason": None,
        },
        "tracked": [],
        "untracked": [],
        "ignored": [],
        "external": [],
        "classifications": [],
        "residue": [],
        "rejected_paths": [],
        "verdict": "captured",
        "patch_bundle_id": "patch-query",
        "tree_snapshot_id": "tree-snapshot-query",
        "position": 2,
        "task_region_id": "task-query",
        "candidate_id": "candidate-query",
        "compromised": True,
        "superseded_pending": True,
        "supersedes_record_id": "file-state-before-query",
        "superseded_by_record_id": "file-state-after-query",
        "cleanup_id": "cleanup-query",
        "cleanup_excluded_paths": ["secret.txt"],
        "cleanup_reason": "secret_detected",
        "cleanup_applied_event_id": "cleanup-applied-query",
        "compromised_snapshot_deleted": True,
        "compromised_paths": ["secret.txt"],
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
