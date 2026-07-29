"""Unit tests for pure graph projections."""

from datetime import datetime
from pathlib import Path
import random
from typing import Any, cast

import yaml
import pytest

from orchestrator.graph import (
    accepted_output_records_by_node_port_view,
    approval_decisions_view,
    authority_decisions_view,
    callback_idempotency_events_view,
    check_results_view,
    cleanup_applied_ids_view,
    cleanup_requested_events_view,
    completion_decision_passed,
    decision_request_details_view,
    edges_view,
    environment_failures_view,
    failed_verification_candidate_ids_view,
    failed_verification_results_by_record_id_view,
    file_state_records_view,
    input_bindings_view,
    invalid_test_blocks_view,
    leases_view,
    node_creation_payloads_view,
    node_creation_positions_view,
    node_output_ports_view,
    node_states_view,
    output_record_payloads_view,
    output_records_by_node_port_view,
    passed_verification_results_by_record_id_view,
    recovery_nodes_by_record_id_view,
    requirement_revisions_view,
    retry_not_before_by_node_view,
    task_candidates_view,
    verifier_verdicts_view,
    Actor,
    ActorKind,
    ApprovalDecisionProjection,
    AuthorityDecisionProjection,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CheckResultProjection,
    CleanupRequestedProjection,
    EnvironmentFailureProjection,
    EdgeProjection,
    EventEnvelope,
    FakeClock,
    FileStateRecord,
    FinalInvariantBlocker,
    GraphProjection,
    GraphProjectionSnapshot,
    GraphRunOutcome,
    GraphCommandContext,
    PatchCommandContext,
    InMemoryEventStore,
    InputBindingProjection,
    InvalidTestBlockProjection,
    LeaseProjection,
    NodeCreationProjection,
    OutputRecord,
    OversightDecisionProjection,
    PendingGateDecisionProjection,
    RequirementRevisionProjection,
    SequentialIdGenerator,
    SupportEvidenceProjection,
    VerifierVerdictProjection,
    VerificationResultProjection,
    build_projection,
    initial_projection,
    project_final_invariant_blockers,
    project_active_lease_wait_plan,
    project_graph_blocked_reason,
    project_graph_completion_eligible,
    project_graph_outcome,
    project_graph_projection_snapshot,
    project_graph_patch_attempts,
    project_graph_topology,
    project_decision_view,
    project_decision_view_from_projection,
    project_lease_view,
    project_leases,
    project_node_states,
    project_node_max_attempts,
    project_planner_freshness_packet,
    project_ready_nodes,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_requirement_freshness_facts,
    project_requirement_revisions,
    project_residue_report,
    project_run_state,
    project_task_states,
    project_support_evidence_freshness,
    run_scenario,
    reduce_event,
    support_evidence_freshness_from_projection,
)
from orchestrator.graph import projections
from tests.unit.graph_test_utils import projection_fixture_set, apply_command, command_context
from tests.unit.graph_test_utils import canonical_event_payload

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "graph"


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-event",
        run_id="run-1",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
    )


def _file_state_event(task_region_id: str, candidate_id: str, position: int) -> EventEnvelope:
    return _event(
        "file_state_accepted",
        {
            "record_id": f"file-state-{candidate_id}",
            "record_kind": "file_state",
            "producer_node_id": f"worker-{candidate_id}",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": f"snapshot-{candidate_id}",
            "base_snapshot_id": "S0",
            "task_region_id": task_region_id,
            "candidate_id": candidate_id,
            "verdict": "captured",
        },
    ).model_copy(update={"position": position})


def test_graph_patch_attempt_projection_rejects_malformed_result() -> None:
    events = [
        _event(
            "graph_patch_rejected",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
            },
        ).model_copy(update={"position": 2})
    ]

    with pytest.raises(ValueError, match="requires rejection_reason"):
        project_graph_patch_attempts(events, run_id="run-1", current_graph_position=3)


def test_empty_projection() -> None:
    assert initial_projection() == {
        "run_state": None,
        "node_states": {},
        "task_states": {},
        "leases": {},
        "ready_nodes": [],
        "node_kinds": {},
        "node_roles": {},
        "node_creation_positions": {},
        "node_task_regions": {},
        "node_attempts": {},
        "node_candidates": {},
        "node_failed_candidates": {},
        "node_resource_claims": {},
        "node_allowed_actions": {},
        "node_preconditions": {},
        "node_command_definitions": {},
        "node_output_ports": {},
        "accepted_output_records_by_node_port": {},
        "accepted_record_summaries_by_id": {},
        "output_records_by_node_port": {},
        "edges": {},
        "input_bindings": {},
        "node_pending_appeals": {},
        "node_gate_decisions": {},
        "task_candidates": {},
        "verifier_verdicts": {},
        "completion_decision_passed": False,
        "passed_verification_results_by_record_id": {},
        "failed_verification_results_by_record_id": {},
        "passed_verification_candidate_ids": [],
        "failed_verification_candidate_ids": {},
        "recovery_nodes_by_record_id": {},
        "check_results": {},
        "invalid_test_blocks": {},
        "configured_gates": {},
        "gate_decisions": {},
        "environment_failures": {},
        "file_state_records": {},
        "planner_generation_budget": 8,
        "planner_successors": {},
        "accepted_graph_patches_by_node": {},
        "accepted_no_successor_patches_by_node": {},
        "accepted_no_successor_patch_ids_by_node": {},
        "latest_routine_snapshot_record": None,
        "planner_generations": {},
        "planner_sessions": {},
        "planner_session_states": {},
        "planner_session_current_nodes": {},
        "planner_session_carryovers": {},
        "planner_region_labels": {},
        "requirement_revisions": {},
        "active_requirement_versions": {},
        "support_evidence": {},
        "last_deferred_reasons": {},
        "retry_not_before_by_node": {},
        "node_creation_payloads": {},
        "output_record_payloads": {},
        "approval_decisions": {},
        "authority_decisions": {},
        "oversight_decisions": {},
        "decision_request_details": {},
        "callback_idempotency_events": {},
        "open_proposal_blockers": {},
        "suspect_node_reasons": {},
        "authority_revision_blockers": {},
        "cleanup_requested_events": {},
        "cleanup_applied_ids": {},
        "tokens_by_node": {},
        "tokens_by_node_kind": {},
        "latency_ms_by_node_kind": {},
        "execution_count_by_node_kind": {},
        "num_actions_by_node_kind": {},
        "recorded_node_usage_keys": {},
    }


def test_callback_idempotency_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": {"payload_hash": "hash-a"},
            },
        ),
    )

    projected = callback_idempotency_events_view(projection)["worker-1\0key-1"]

    assert isinstance(projected, CallbackIdempotencyEvent)
    assert projected.outcome == "callback_accepted"
    assert projected.payload == {"payload_hash": "hash-a"}


def test_callback_idempotency_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": {"payload_hash": "hash-a"},
            },
        ),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["callback_idempotency_events"]["worker-1\0key-1"]

    assert isinstance(projected, CallbackIdempotencyEvent)
    assert projected.event_type == "callback_accepted"
    assert projected.payload == {"payload_hash": "hash-a"}


def test_callback_idempotency_projection_allows_empty_callback_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": None,
            },
        ),
    )

    projected = callback_idempotency_events_view(projection)["worker-1\0key-1"]

    assert isinstance(projected, CallbackIdempotencyEvent)
    assert projected.payload is None


def test_approval_decision_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "approval_decision_recorded",
            {
                "node_id": "gate-1",
                "decision": "approved",
                "decider": {"kind": "human", "id": "alice"},
                "task_region_id": "task-1",
                "reason": "looks safe",
            },
        ),
    )

    projected = approval_decisions_view(projection)["gate-1"]

    assert isinstance(projected, ApprovalDecisionProjection)
    assert projected.node_id == "gate-1"
    assert projected.decision == "approved"
    assert projected.reason == "looks safe"


def test_authority_decision_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "authority_decision_recorded",
            {
                "node_id": "authority-1",
                "decision": "granted",
                "decider": {"kind": "human", "id": "alice"},
                "scope": {"tools": ["graph_write"]},
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
        ),
    )

    projected = authority_decisions_view(projection)["authority-1"]

    assert isinstance(projected, AuthorityDecisionProjection)
    assert projected.node_id == "authority-1"
    assert projected.decision == "granted"
    assert projected.scope == {"tools": ["graph_write"]}


def test_decision_projection_accepts_canonical_decision_payloads() -> None:
    projection = reduce_event(
        reduce_event(
            initial_projection(),
            _event(
                "approval_decision_recorded",
                {
                    "node_id": "gate-1",
                    "decision": "approved",
                },
            ),
        ),
        _event(
            "authority_decision_recorded",
            {
                "node_id": "authority-1",
                "decision": "denied",
            },
        ),
    )

    assert approval_decisions_view(projection)["gate-1"].decision == "approved"
    assert authority_decisions_view(projection)["authority-1"].decision == "denied"


def test_decision_projection_checkpoint_round_trips_typed_payloads() -> None:
    projection = reduce_event(
        reduce_event(
            initial_projection(),
            _event(
                "approval_decision_recorded",
                {
                    "node_id": "gate-1",
                    "decision": "approved",
                    "reason": "looks safe",
                },
            ),
        ),
        _event(
            "authority_decision_recorded",
            {
                "node_id": "authority-1",
                "decision": "granted",
                "scope": {"tools": ["graph_write"]},
            },
        ),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    approval = restored["approval_decisions"]["gate-1"]
    authority = restored["authority_decisions"]["authority-1"]

    assert isinstance(approval, ApprovalDecisionProjection)
    assert approval.decision == "approved"
    assert isinstance(authority, AuthorityDecisionProjection)
    assert authority.decision == "granted"
    assert authority.scope == {"tools": ["graph_write"]}


def test_malformed_decision_events_are_rejected_and_checkpoint_rows_are_filtered() -> None:
    with pytest.raises(ValueError):
        reduce_event(
            initial_projection(),
            _event(
                "approval_decision_recorded",
                {"node_id": "gate-1", "decision": "not-a-real-decision"},
            ),
        )
    with pytest.raises(ValueError):
        reduce_event(
            initial_projection(),
            _event(
                "oversight_decision_recorded",
                {"node_id": "oversight-1", "decision": "not-a-real-oversight-decision"},
            ),
        )

    restored = projection_from_checkpoint(
        {
            "approval_decisions": {
                "gate-2": {
                    "node_id": "gate-2",
                    "decision": "still-not-valid",
                }
            },
            "authority_decisions": {
                "authority-1": {
                    "node_id": "authority-1",
                    "decision": "unknown-authority-decision",
                }
            },
            "oversight_decisions": {
                "oversight-1": {
                    "node_id": "oversight-1",
                    "decision": "unknown-oversight-decision",
                    "position": 1,
                }
            },
        }
    )

    assert restored["approval_decisions"] == {}
    assert restored["authority_decisions"] == {}
    assert restored["oversight_decisions"] == {}


def test_decision_view_behavior_is_preserved_with_typed_decision_projection() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "blocked",
                "reason": "approve final scope",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
                "reason": "needs graph_write",
            },
        ),
        _event(
            "authority_decision_recorded",
            {
                "node_id": "authority-1",
                "decision": "granted",
            },
        ),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    expected = [
        {
            "node_id": "human-gate-1",
            "gate_type": "approve final scope",
            "prompt": "approve final scope",
        }
    ]

    assert project_decision_view(events)["pending_gates"] == expected
    assert project_decision_view_from_projection(restored)["pending_gates"] == expected


def test_decision_request_details_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = initial_projection()
    for event in [
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "blocked",
                "reason": "approve final scope",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "producer_node_id": "human-gate-1",
                "record_type": "decision_request",
                "port": "decision_request",
                "value": {
                    "options": ["approve", "reject"],
                    "default_option": "approve",
                    "consequence_summary": "scope is accepted",
                    "expires_at": "2026-01-01T00:00:00Z",
                    "target_node_id": "worker-1",
                    "target_region_id": "task-1",
                },
            },
        ),
    ]:
        projection = reduce_event(projection, event)

    projected = decision_request_details_view(projection)["human-gate-1"]
    assert isinstance(projected, PendingGateDecisionProjection)

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    restored_projected = restored["decision_request_details"]["human-gate-1"]

    assert isinstance(restored_projected, PendingGateDecisionProjection)
    assert restored_projected.model_dump(mode="json") == {
        "options": ["approve", "reject"],
        "default_option": "approve",
        "consequence_summary": "scope is accepted",
        "expires_at": "2026-01-01T00:00:00Z",
        "target_node_id": "worker-1",
        "target_region_id": "task-1",
    }
    assert project_decision_view_from_projection(restored)["pending_gates"] == [
        {
            "node_id": "human-gate-1",
            "gate_type": "approve final scope",
            "prompt": "approve final scope",
            "options": ["approve", "reject"],
            "default_option": "approve",
            "consequence_summary": "scope is accepted",
            "expires_at": "2026-01-01T00:00:00Z",
            "target_node_id": "worker-1",
            "target_region_id": "task-1",
        }
    ]


def test_malformed_decision_request_details_checkpoint_entry_is_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "decision_request_details": {
                "human-gate-1": {
                    "options": ["approve", 3],
                    "expires_at": ["not", "a", "string"],
                }
            }
        }
    )

    assert restored["decision_request_details"] == {}


def test_environment_failure_projection_uses_check_result_record() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "task_region_id": "task-1",
                "node_id": "check-1",
                "record_id": "failure-record-1",
                "record_kind": "check_result",
                "value": {
                    "classification": "tool_unavailable",
                    "reason": "tool missing",
                    "command_text": "uv run pytest",
                    "stderr_tail": "uv: command not found",
                    "exit_code": 127,
                },
            },
        ).model_copy(update={"position": 17}),
    )

    projected = environment_failures_view(projection)["task-1"]

    assert isinstance(projected, EnvironmentFailureProjection)
    assert projected.position == 17
    assert projected.node_id == "check-1"
    assert projected.record_id == "failure-record-1"
    assert projected.classification == "tool_unavailable"
    assert projected.reason == "check tool unavailable while running: uv run pytest"
    assert projected.command_text == "uv run pytest"
    assert projected.stderr_tail == "uv: command not found"
    assert projected.exit_code == 127


def test_environment_failure_projection_checkpoint_round_trips_check_result_record() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "task_region_id": "task-1",
                "node_id": "check-1",
                "record_kind": "check_result",
                "classification": "environment_error",
                "value": {
                    "command_text": "uv run pytest",
                    "stderr_tail": "missing dependency",
                    "exit_code": 1,
                },
            },
        ).model_copy(update={"position": 18}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["environment_failures"]["task-1"]

    assert isinstance(projected, EnvironmentFailureProjection)
    assert projected.position == 18
    assert projected.node_id == "check-1"
    assert projected.classification == "environment_error"
    assert projected.reason == "check environment setup failed while running: uv run pytest"
    assert projected.command_text == "uv run pytest"
    assert projected.stderr_tail == "missing dependency"
    assert projected.exit_code == 1


def test_environment_failure_projection_derives_missing_reason_from_check_record() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ),
        _event(
            "output_record_accepted",
            {
                "task_region_id": "task-1",
                "record_kind": "check_result",
                "value": {"classification": "tool_error"},
            },
        ),
    ]
    projection = reduce_event(
        reduce_event(initial_projection(), events[0]),
        events[1],
    )

    projected = environment_failures_view(projection)["task-1"]

    assert isinstance(projected, EnvironmentFailureProjection)
    assert projected.reason == "check tool error while running: check command"
    assert project_task_states(events)["task-1"] == "blocked_environment"


def test_file_state_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _file_state_event("task-1", "cand-1", 21),
    )

    projected = file_state_records_view(projection)["file-state-cand-1"]

    assert isinstance(projected, FileStateRecord)
    assert projected.record_id == "file-state-cand-1"
    assert projected.snapshot_id == "snapshot-cand-1"
    assert projected.run_id == "run-1"
    assert projected.model_dump(mode="json")["position"] == 21


def test_file_state_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = initial_projection()
    projection = reduce_event(projection, _file_state_event("task-1", "cand-1", 21))
    projection = reduce_event(
        projection,
        _event(
            "cleanup_requested",
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-cand-1",
                "reason": "secret found",
                "paths": ["secrets.env"],
            },
        ).model_copy(update={"position": 22}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["file_state_records"]["file-state-cand-1"]

    assert isinstance(projected, FileStateRecord)
    assert projected.record_id == "file-state-cand-1"
    assert projected.cleanup_id == "cleanup-1"
    assert projected.model_dump(mode="json")["cleanup_reason"] == "secret found"
    assert projected.compromised is True
    assert projected.compromised_paths == ["secrets.env"]


def test_residue_report_reads_typed_file_state_entries() -> None:
    report = project_residue_report(
        [
            _event(
                "file_state_accepted",
                {
                    "record_id": "file-state-cand-1",
                    "record_kind": "file_state",
                    "producer_node_id": "worker-1",
                    "port": "file_state",
                    "schema": "FileStateRecord",
                    "snapshot_id": "snapshot-cand-1",
                    "base_snapshot_id": "S0",
                    "candidate_id": "cand-1",
                    "verdict": "captured",
                    "residue": [
                        {
                            "path": "secrets.env",
                            "classification": "secret",
                            "source": "untracked",
                        }
                    ],
                },
            ).model_copy(update={"position": 22})
        ]
    )

    assert report["secrets.env"][0]["classification"] == "secret"
    assert report["secrets.env"][0]["source"] == "untracked"
    assert report["secrets.env"][0]["record_id"] == "file-state-cand-1"


def test_task_candidate_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "producer_node_id": "worker-1",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 2,
                "file_state_record_ids": ["file-state-1"],
                "supersedes_task_region_ids": ["task-old"],
            },
        ).model_copy(update={"position": 31}),
    )

    projected = task_candidates_view(projection)["task-1"][0]

    assert isinstance(projected, CandidateProjection)
    assert projected.candidate_id == "candidate-1"
    assert projected.attempt_number == 2
    assert projected.position == 31
    assert projected.file_state_record_ids == ["file-state-1"]
    assert projected.supersedes_task_region_ids == ["task-old"]


def test_task_candidate_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "task_region_id": "task-1",
                "record_id": "candidate-1",
                "attempt_number": 1,
            },
        ).model_copy(update={"position": 32}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["task_candidates"]["task-1"][0]

    assert isinstance(projected, CandidateProjection)
    assert projected.candidate_id == "candidate-1"
    assert projected.attempt_number == 1
    assert projected.position == 32
    assert projected.file_state_record_ids == []
    assert projected.supersedes_task_region_ids == []


def test_malformed_task_candidate_checkpoint_entry_is_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "task_candidates": {
                "task-1": [
                    {
                        "candidate_id": ["candidate-bad"],
                        "attempt_number": 1,
                        "position": 33,
                    }
                ]
            }
        }
    )

    assert restored["task_candidates"] == {"task-1": []}


def test_verifier_verdict_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "verification_passed",
            {"candidate_id": "candidate-1"},
        ).model_copy(update={"position": 34}),
    )

    projected = verifier_verdicts_view(projection)["candidate-1"]

    assert isinstance(projected, VerifierVerdictProjection)
    assert projected.candidate_id == "candidate-1"
    assert projected.verdict == "passed"
    assert projected.position == 34


def test_verifier_verdict_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "verification_failed",
            {"candidate_id": "candidate-1"},
        ).model_copy(update={"position": 35}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["verifier_verdicts"]["candidate-1"]

    assert isinstance(projected, VerifierVerdictProjection)
    assert projected.candidate_id == "candidate-1"
    assert projected.verdict == "failed"
    assert projected.position == 35


def test_malformed_verifier_verdict_checkpoint_entry_is_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "verifier_verdicts": {
                "candidate-1": {
                    "candidate_id": "candidate-1",
                    "verdict": "unknown",
                    "position": 36,
                }
            }
        }
    )

    assert restored["verifier_verdicts"] == {}


def test_requirement_revision_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
                "previous_version_id": "R-1.v1",
                "revision_index": 2,
                "classification": "semantic_change",
                "authority_required_reason": "behavior change needs approval",
                "active": True,
            },
        ).model_copy(update={"position": 37}),
    )

    projected = requirement_revisions_view(projection)["R-1.v2"]

    assert isinstance(projected, RequirementRevisionProjection)
    assert projected.model_dump(mode="json", exclude_none=True) == {
        "requirement_id": "R-1",
        "version_id": "R-1.v2",
        "change_classification": "semantic_change",
        "requires_authority": True,
        "position": 37,
        "previous_version_id": "R-1.v1",
        "revision_index": 2,
        "authority_required_reason": "behavior change needs approval",
        "validation_strengthening": False,
    }

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    restored_projected = restored["requirement_revisions"]["R-1.v2"]

    assert isinstance(restored_projected, RequirementRevisionProjection)
    assert restored_projected.model_dump(mode="json") == projected.model_dump(mode="json")


def test_support_evidence_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = initial_projection()
    for event in [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 38}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
                "confidence": "high",
            },
        ).model_copy(update={"position": 39}),
    ]:
        projection = reduce_event(projection, event)

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["support_evidence"]["S-1"]

    assert isinstance(projected, SupportEvidenceProjection)
    assert projected.model_dump(mode="json", exclude_none=True) == {
        "support_id": "S-1",
        "evidence_id": "E-1",
        "requirement_id": "R-1",
        "requirement_version_id": "R-1.v1",
        "status": "active",
        "position": 39,
        "confidence": "high",
    }
    assert support_evidence_freshness_from_projection(restored) == {
        "S-1": {
            "support_id": "S-1",
            "evidence_id": "E-1",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v1",
            "status": "active",
            "freshness": "fresh",
            "stale_reason": None,
        }
    }


def test_malformed_requirement_and_support_checkpoint_entries_are_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "requirement_revisions": {
                "R-1.v1": {
                    "requirement_id": "R-1",
                    "version_id": "R-1.v1",
                    "change_classification": "initial",
                    "requires_authority": False,
                    "position": "bad",
                    "validation_strengthening": False,
                }
            },
            "support_evidence": {
                "S-1": {
                    "support_id": "S-1",
                    "evidence_id": "E-1",
                    "requirement_id": "R-1",
                    "requirement_version_id": "R-1.v1",
                    "status": "active",
                    "position": "bad",
                }
            },
        }
    )

    assert restored["requirement_revisions"] == {}
    assert restored["support_evidence"] == {}


def test_oversight_decision_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "oversight_decision_recorded",
            {
                "node_id": "oversight-1",
                "appeal_node_id": "appeal-1",
                "appealed_node_id": "verifier-1",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "decision": "invalid_test_accepted",
                "appeal_type": "invalid_test",
                "reason": "test assertion was wrong",
            },
        ).model_copy(update={"position": 40}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["oversight_decisions"]["oversight-1"]

    assert isinstance(projected, OversightDecisionProjection)
    assert projected.model_dump(mode="json", exclude_none=True) == {
        "node_id": "oversight-1",
        "decision": "invalid_test_accepted",
        "position": 40,
        "task_region_id": "task-1",
        "candidate_id": "candidate-1",
        "appeal_node_id": "appeal-1",
        "appealed_node_id": "verifier-1",
        "appeal_type": "invalid_test",
        "reason": "test assertion was wrong",
        "decision_type": "oversight",
        "decider": "fixture-controller",
    }
    assert restored["oversight_decisions"]["appeal-1"] is projected


def test_oversight_decision_checkpoint_restore_rebuilds_appeal_alias() -> None:
    restored = projection_from_checkpoint(
        {
            "oversight_decisions": {
                "oversight-1": {
                    "node_id": "oversight-1",
                    "appeal_node_id": "appeal-1",
                    "decision": "invalid_test_accepted",
                    "position": 41,
                }
            }
        }
    )

    projected = restored["oversight_decisions"]["oversight-1"]

    assert restored["oversight_decisions"]["appeal-1"] is projected


def test_oversight_decision_canonical_acceptance_blocks_invalid_test() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
    ]

    assert project_task_states(events) == {"task-1": "blocked_invalid_test"}


def test_malformed_file_state_payload_is_tolerated_without_raw_projection_entry() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "file_state_accepted",
            {
                "record_id": ["file-state-bad-1"],
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "verdict": "captured",
            },
        ).model_copy(update={"position": 23}),
    )

    assert file_state_records_view(projection) == {}


def test_task_projection_accepts_file_state_via_producer_node_task_region_fallback() -> None:
    events = [
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 2}
        ),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-cand-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": "snapshot-cand-1",
                "base_snapshot_id": "S0",
                "candidate_id": "cand-1",
                "verdict": "captured",
            },
        ).model_copy(update={"position": 3}),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_file_state_projection_uses_direct_membership_fields() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-cand-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "record_type": "file_state",
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
            },
        ),
    )

    projected = file_state_records_view(projection)["file-state-cand-1"]

    assert projected.task_region_id == "task-1"
    assert projected.candidate_id == "cand-1"


def test_node_creation_projection_uses_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "step/task",
                "attempt_number": 2,
                "candidate_id": "candidate-1",
                "failed_candidate_id": "candidate-0",
                "resource_claims": [{"paths": ["src/app.py"], "mode": "write", "scope": "repo"}],
                "allowed_actions": ["submit_callback"],
                "preconditions": ["inputs_bound"],
            },
        ).model_copy(update={"position": 23}),
    )

    projected = node_creation_payloads_view(projection)["worker-1"]

    assert isinstance(projected, NodeCreationProjection)
    assert projected.node_id == "worker-1"
    assert projected.kind == "worker"
    assert projected.role == "builder"
    assert projected.state == "planned"
    assert projected.task_region_id == "step/task"
    assert projected.attempt_number == 2
    assert projected.candidate_id == "candidate-1"
    assert projected.failed_candidate_id == "candidate-0"
    assert [claim.model_dump(mode="json") for claim in projected.resource_claims] == [
        {"mode": "write", "scope": "repo", "paths": ["src/app.py"]}
    ]
    assert projected.allowed_actions == ["submit_callback"]
    assert projected.preconditions == ["inputs_bound"]


def test_node_creation_projection_retains_first_typed_retry_limit() -> None:
    events = [
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "max_attempts": 2},
        ).model_copy(update={"position": 1}),
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "max_attempts": 7},
        ).model_copy(update={"position": 2}),
        _event(
            "node_created",
            {"node_id": "worker-2", "kind": "worker", "max_attempts": True},
        ).model_copy(update={"position": 3}),
    ]

    projection = build_projection(events)

    assert node_creation_payloads_view(projection)["worker-1"].max_attempts == 2
    assert "worker-2" not in node_creation_payloads_view(projection)


def test_clone_projection_covers_initial_keys_without_nested_aliasing() -> None:
    state = initial_projection()
    state = projection_fixture_set(
        state, "node_output_ports", ("worker-1",), {"candidate": ["record-1"]}
    )

    cloned = projections._clone_projection(state)

    assert set(cloned) == set(initial_projection())
    cloned["node_output_ports"]["worker-1"]["candidate"].append("record-2")
    assert node_output_ports_view(state)["worker-1"]["candidate"] == ["record-1"]


def test_node_creation_projection_checkpoint_round_trips_typed_payload() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "gate",
                "role": "human_gate",
                "state": "blocked",
                "task_region_id": "step/task",
                "gate_type": "approval",
                "prompt": "Approve the change?",
            },
        ).model_copy(update={"position": 24}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    projected = restored["node_creation_payloads"]["gate-1"]

    assert isinstance(projected, NodeCreationProjection)
    assert projected.node_id == "gate-1"
    assert projected.kind == "gate"
    assert projected.prompt == "Approve the change?"


def test_malformed_node_created_payload_is_tolerated_without_raw_projection_entry() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "node_created",
            {
                "node_id": ["legacy", "bad", "shape"],
                "kind": "worker",
                "state": "planned",
            },
        ),
    )

    assert node_creation_payloads_view(projection) == {}
    assert node_states_view(projection) == {}


def test_input_binding_replay_accumulates_many_cardinality_records() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}),
        _event(
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "required": True,
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-2"],
                "bound_at_position": 5,
            },
        ),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    binding = input_bindings_view(projection)["summarizer-1"]["source_records"]
    assert binding.binding_policy == "bind_all"
    assert binding.record_ids == ["candidate-1", "candidate-2"]
    assert binding.record_bound_positions == {"candidate-1": 4, "candidate-2": 5}


def test_edge_projection_uses_typed_payload_and_preserves_topology_shape() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}),
        _event(
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "required": False,
                "dependency_type": "input_binding",
                "accepted_record_selector": {
                    "record_type": "candidate",
                    "schema": "ImplementationCandidate",
                },
                "prompt_hydration_policy": {"mode": "summary"},
                "metadata": {"priority": "high"},
                "unexpected_payload": {"must": "drop"},
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
        ),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    edge = edges_view(projection)["edge-source-records"]
    assert isinstance(edge, EdgeProjection)
    assert edge.accepted_record_selector == {
        "record_type": "candidate",
        "schema": "ImplementationCandidate",
    }
    assert "unexpected_payload" not in edge.model_dump(mode="json")

    topology = project_graph_topology(events)
    topology_edge = topology["edges"][0]
    assert topology_edge["edge_id"] == "edge-source-records"
    assert topology_edge["required"] is False
    assert topology_edge["accepted_record_selector"] == {
        "record_type": "candidate",
        "schema": "ImplementationCandidate",
    }
    assert topology_edge["metadata"] == {
        "prompt_hydration_policy": {"mode": "summary"},
        "metadata": {"priority": "high"},
    }
    assert topology_edge["binding"] == {
        "edge_id": "edge-source-records",
        "to_node_id": "summarizer-1",
        "to_port": "source_records",
        "record_ids": ["candidate-1"],
        "bound_at_position": 4,
        "record_bound_positions": {"candidate-1": 4},
        "binding_policy": "bind_all",
    }


def test_input_binding_projection_uses_typed_payload_and_drops_raw_event_extras() -> None:
    projection = initial_projection()
    for event in [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}),
        _event(
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
                "trigger": "record_accepted",
            },
        ),
    ]:
        projection = reduce_event(projection, event)

    binding = input_bindings_view(projection)["summarizer-1"]["source_records"]
    assert isinstance(binding, InputBindingProjection)
    assert binding.record_ids == ["candidate-1"]
    assert binding.trigger == "record_accepted"
    assert "raw_payload_only" not in binding


def test_edge_and_input_binding_projection_checkpoint_round_trips_typed_payloads() -> None:
    projection = initial_projection()
    for event in [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}),
        _event(
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "binding_policy": "bind_all",
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
        ),
    ]:
        projection = reduce_event(projection, event)

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    assert isinstance(restored["edges"]["edge-source-records"], EdgeProjection)
    assert isinstance(
        restored["input_bindings"]["summarizer-1"]["source_records"],
        InputBindingProjection,
    )
    assert restored["edges"]["edge-source-records"].binding_policy == "bind_all"
    assert restored["input_bindings"]["summarizer-1"]["source_records"].record_ids == [
        "candidate-1"
    ]


def test_malformed_edge_and_input_binding_checkpoint_entries_are_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "edges": {
                "edge-valid": {
                    "edge_id": "edge-valid",
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "summarizer-1",
                    "to_port": "source_records",
                },
                "edge-invalid-dependency": {
                    "edge_id": "edge-invalid-dependency",
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "summarizer-1",
                    "to_port": "source_records",
                    "dependency_type": "invalid-dependency",
                },
                "edge-mismatched-key": {
                    "edge_id": "edge-other",
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "summarizer-1",
                    "to_port": "source_records",
                },
                "edge-malformed": {
                    "edge_id": "edge-malformed",
                    "from_node_id": "worker-1",
                },
            },
            "input_bindings": {
                "summarizer-1": {
                    "source_records": {
                        "edge_id": "edge-valid",
                        "to_node_id": "summarizer-1",
                        "to_port": "source_records",
                        "record_ids": ["candidate-1"],
                        "bound_at_position": 4,
                    },
                    "mismatched-port": {
                        "edge_id": "edge-valid",
                        "to_node_id": "summarizer-1",
                        "to_port": "source_records",
                        "record_ids": ["candidate-1"],
                        "bound_at_position": 4,
                    },
                    "malformed": {
                        "edge_id": "edge-valid",
                        "to_node_id": "summarizer-1",
                        "to_port": "malformed",
                        "record_ids": "candidate-1",
                        "bound_at_position": 4,
                    },
                },
                "mismatched-node": {
                    "source_records": {
                        "edge_id": "edge-valid",
                        "to_node_id": "summarizer-1",
                        "to_port": "source_records",
                        "record_ids": ["candidate-1"],
                        "bound_at_position": 4,
                    }
                },
            },
        }
    )

    assert list(restored["edges"]) == ["edge-valid"]
    assert list(restored["input_bindings"]["summarizer-1"]) == ["source_records"]
    assert isinstance(restored["edges"]["edge-valid"], EdgeProjection)
    assert isinstance(
        restored["input_bindings"]["summarizer-1"]["source_records"],
        InputBindingProjection,
    )


def test_finite_state_and_kind_checkpoint_entries_are_validated() -> None:
    restored = projection_from_checkpoint(
        {
            "node_states": {
                "worker-1": "running",
                "worker-bad": "definitely-not-a-node-state",
            },
            "task_states": {
                "task-1": "accepted",
                "task-bad": "running",
            },
            "node_kinds": {
                "worker-1": "worker",
                "worker-bad": "definitely-not-a-node-kind",
            },
        }
    )

    assert restored["node_states"] == {"worker-1": "running"}
    assert restored["task_states"] == {"task-1": "accepted"}
    assert restored["node_kinds"] == {"worker-1": "worker"}


def test_structural_index_checkpoint_entries_are_validated() -> None:
    restored = projection_from_checkpoint(
        {
            "node_resource_claims": {
                "worker-1": [
                    {"mode": "read", "scope": "repo", "paths": ["src/"]},
                    {"mode": "external", "scope": "external"},
                    "not-a-claim",
                ],
                "worker-bad": "not-a-list",
            },
            "recovery_nodes_by_record_id": {
                "record-1": [
                    {
                        "node_id": "recovery-1",
                        "recovery_reason": "failed_check",
                        "unexpected": "drop-me",
                    },
                    {"node_id": "", "recovery_reason": "failed_check"},
                    {"node_id": "recovery-empty-reason", "recovery_reason": ""},
                    {"node_id": "recovery-bad"},
                    "not-a-recovery",
                ],
                "record-bad": "not-a-list",
            },
            "latest_routine_snapshot_record": {
                "record_id": "routine-snapshot-1",
                "producer_node_id": "routine-snapshot",
                "port": "routine_snapshot",
                "unexpected": "drop-me",
            },
        }
    )

    assert projection_to_checkpoint(restored)["node_resource_claims"] == {
        "worker-1": [
            {"mode": "read", "scope": "repo", "paths": ["src/"]},
            {"mode": "external", "scope": "external"},
        ]
    }
    assert projection_to_checkpoint(restored)["recovery_nodes_by_record_id"] == {
        "record-1": [{"node_id": "recovery-1", "recovery_reason": "failed_check"}]
    }
    assert projection_to_checkpoint(restored)["latest_routine_snapshot_record"] == {
        "record_id": "routine-snapshot-1",
        "producer_node_id": "routine-snapshot",
        "port": "routine_snapshot",
    }


def test_node_resource_claims_checkpoint_restores_typed_claims() -> None:
    restored = projection_from_checkpoint(
        {
            "node_resource_claims": {
                "worker-1": [
                    {"mode": "read", "scope": "repo", "paths": ["src/"]},
                ],
            },
        }
    )

    claim = restored["node_resource_claims"]["worker-1"][0]
    assert claim.mode == "read"
    assert claim.scope == "repo"
    assert projection_to_checkpoint(restored)["node_resource_claims"] == {
        "worker-1": [{"mode": "read", "scope": "repo", "paths": ["src/"]}]
    }


def test_structural_checkpoint_records_restore_typed_entries() -> None:
    restored = projection_from_checkpoint(
        {
            "recovery_nodes_by_record_id": {
                "record-1": [
                    {"node_id": "recovery-1", "recovery_reason": "failed_check"},
                ],
            },
            "latest_routine_snapshot_record": {
                "record_id": "routine-snapshot-1",
                "producer_node_id": "routine-snapshot",
                "port": "routine_snapshot",
            },
        }
    )

    recovery = restored["recovery_nodes_by_record_id"]["record-1"][0]
    assert recovery.node_id == "recovery-1"
    assert recovery.recovery_reason == "failed_check"
    assert restored["latest_routine_snapshot_record"].record_id == "routine-snapshot-1"
    assert projection_to_checkpoint(restored)["recovery_nodes_by_record_id"] == {
        "record-1": [{"node_id": "recovery-1", "recovery_reason": "failed_check"}]
    }
    assert projection_to_checkpoint(restored)["latest_routine_snapshot_record"] == {
        "record_id": "routine-snapshot-1",
        "producer_node_id": "routine-snapshot",
        "port": "routine_snapshot",
    }


def test_remaining_primitive_checkpoint_maps_are_validated() -> None:
    restored = projection_from_checkpoint(
        {
            "run_state": 3,
            "ready_nodes": ["worker-1", 5],
            "node_roles": {"worker-1": "builder", "worker-bad": 7, 7: "builder"},
            "node_creation_positions": {"worker-1": 3, "worker-bad": "3", "bool": True},
            "node_task_regions": {"worker-1": "task-1", "worker-bad": None},
            "node_attempts": {"worker-1": 2, "worker-bad": False},
            "node_candidates": {"worker-1": "candidate-1", "worker-bad": 5},
            "node_failed_candidates": {"worker-1": "candidate-0", "worker-bad": 5},
            "node_allowed_actions": {
                "worker-1": ["submit_callback", 7],
                "worker-bad": "submit_callback",
            },
            "node_preconditions": {"worker-1": ["inputs_bound", None], "worker-bad": 3},
            "node_command_definitions": {"worker-1": {"command": "test"}, "worker-bad": "test"},
            "node_output_ports": {
                "worker-1": {"result": ["record-1", 9], "bad": "record-2"},
                "worker-bad": ["record-3"],
            },
            "accepted_record_summaries_by_id": {
                "record-1": {
                    "record_id": "record-1",
                    "producer_node_id": "worker-1",
                    "position": 8,
                    "bad": 7,
                },
                "record-bad": "bad",
            },
            "node_pending_appeals": {"worker-1": True, "worker-bad": "true"},
            "node_gate_decisions": {"gate-1": False, "gate-bad": 1},
            "completion_decision_passed": "true",
            "passed_verification_candidate_ids": ["candidate-1", 3],
            "failed_verification_candidate_ids": {"candidate-2": True, "candidate-bad": "true"},
            "configured_gates": {
                "task-1": {"gate-1": True, "gate-bad": "true"},
                "task-bad": "gate-1",
            },
            "gate_decisions": {
                "task-1": {"gate-1": False, "gate-bad": 0},
                "task-bad": "gate-1",
            },
            "planner_successors": {"planner-1": "planner-2", "planner-bad": 2},
            "accepted_graph_patches_by_node": {
                "planner-1": ["patch-1", 1],
                "planner-bad": "patch-2",
            },
            "accepted_no_successor_patches_by_node": {
                "planner-1": ["patch-3", None],
                "planner-bad": "patch-4",
            },
            "accepted_no_successor_patch_ids_by_node": {
                "planner-1": "patch-3",
                "planner-bad": 4,
            },
            "planner_generations": {"planner-1": 4, "planner-bad": True},
            "planner_sessions": {"planner-1": "session-1", "planner-bad": 5},
            "planner_session_states": {"session-1": "active", "session-bad": None},
            "planner_session_current_nodes": {"session-1": "planner-1", "session-bad": 5},
            "planner_session_carryovers": {"session-1": None, "session-2": "record-1", 3: "bad"},
            "planner_region_labels": {"planner-1": "Step 1", "planner-bad": 5},
            "active_requirement_versions": {"req-1": "v1", "req-bad": 2},
            "last_deferred_reasons": {"worker-1": "waiting", "worker-bad": 4},
            "retry_not_before_by_node": {
                "worker-1": None,
                "worker-2": "2026-01-01T00:00:00",
                5: "bad",
            },
            "open_proposal_blockers": {
                "proposal-1": {
                    "kind": "missing_successor",
                    "reason": "planner proposal has not been accepted or rejected",
                    "node_id": "planner-1",
                    "exit_code": 2,
                    "support_ids": ["support-1", 7],
                },
                "proposal-node-only": {"node_id": "planner-2"},
                "proposal-bad": "bad",
            },
            "suspect_node_reasons": {"worker-1": "failed", "worker-bad": 8},
            "authority_revision_blockers": {
                "revision-1": {
                    "kind": "authority_required",
                    "reason": "semantic revision lacks authority",
                    "requirement_id": "req-1",
                },
                "revision-bad": {"kind": 7},
            },
            "cleanup_applied_ids": {"cleanup-1": True, "cleanup-bad": "true"},
        }
    )

    assert restored["run_state"] is None
    assert restored["ready_nodes"] == ["worker-1"]
    assert restored["node_roles"] == {"worker-1": "builder"}
    assert restored["node_creation_positions"] == {"worker-1": 3}
    assert restored["node_task_regions"] == {"worker-1": "task-1"}
    assert restored["node_attempts"] == {"worker-1": 2}
    assert restored["node_candidates"] == {"worker-1": "candidate-1"}
    assert restored["node_failed_candidates"] == {"worker-1": "candidate-0"}
    assert restored["node_allowed_actions"] == {"worker-1": ["submit_callback"]}
    assert restored["node_preconditions"] == {"worker-1": ["inputs_bound"]}
    assert restored["node_command_definitions"] == {"worker-1": {"command": "test"}}
    assert restored["node_output_ports"] == {"worker-1": {"result": ["record-1"]}}
    assert restored["accepted_record_summaries_by_id"] == {
        "record-1": {
            "record_id": "record-1",
            "producer_node_id": "worker-1",
            "position": 8,
        }
    }
    assert restored["node_pending_appeals"] == {"worker-1": True}
    assert restored["node_gate_decisions"] == {"gate-1": False}
    assert restored["completion_decision_passed"] is False
    assert restored["passed_verification_candidate_ids"] == ["candidate-1"]
    assert restored["failed_verification_candidate_ids"] == {"candidate-2": True}
    assert restored["configured_gates"] == {"task-1": {"gate-1": True}}
    assert restored["gate_decisions"] == {"task-1": {"gate-1": False}}
    assert restored["planner_successors"] == {"planner-1": "planner-2"}
    assert restored["accepted_graph_patches_by_node"] == {"planner-1": ["patch-1"]}
    assert restored["accepted_no_successor_patches_by_node"] == {"planner-1": ["patch-3"]}
    assert restored["accepted_no_successor_patch_ids_by_node"] == {"planner-1": "patch-3"}
    assert restored["planner_generations"] == {"planner-1": 4}
    assert restored["planner_sessions"] == {"planner-1": "session-1"}
    assert restored["planner_session_states"] == {"session-1": "active"}
    assert restored["planner_session_current_nodes"] == {"session-1": "planner-1"}
    assert restored["planner_session_carryovers"] == {"session-1": None, "session-2": "record-1"}
    assert restored["planner_region_labels"] == {"planner-1": "Step 1"}
    assert restored["active_requirement_versions"] == {"req-1": "v1"}
    assert restored["last_deferred_reasons"] == {"worker-1": "waiting"}
    assert restored["retry_not_before_by_node"] == {
        "worker-1": None,
        "worker-2": "2026-01-01T00:00:00",
    }
    assert restored["open_proposal_blockers"] == {
        "proposal-1": {
            "kind": "missing_successor",
            "reason": "planner proposal has not been accepted or rejected",
            "node_id": "planner-1",
            "exit_code": 2,
            "support_ids": ["support-1"],
        }
    }
    assert restored["suspect_node_reasons"] == {"worker-1": "failed"}
    assert restored["authority_revision_blockers"] == {
        "revision-1": {
            "kind": "authority_required",
            "reason": "semantic revision lacks authority",
            "requirement_id": "req-1",
        }
    }
    assert restored["cleanup_applied_ids"] == {"cleanup-1": True}


def test_malformed_latest_routine_snapshot_checkpoint_entry_is_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "latest_routine_snapshot_record": {
                "record_id": "routine-snapshot-1",
                "producer_node_id": "routine-snapshot",
            }
        }
    )

    assert restored["latest_routine_snapshot_record"] is None


def test_invalid_persisted_edge_selector_raises_projection_error() -> None:
    projection = initial_projection()
    event = _event(
        "edge_created",
        {
            "edge_id": "edge-invalid-selector",
            "from_node_id": "verifier-1",
            "from_port": "verification_report",
            "to_node_id": "planner-gap",
            "to_port": "verification_evidence",
            "required": True,
            "accepted_record_selector": {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "status": "failed",
            },
        },
    )

    with pytest.raises(ValueError, match="status"):
        reduce_event(projection, event)


def test_replay_determinism() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "ready"}),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}),
    ]

    first = initial_projection()
    second = initial_projection()
    for event in events:
        first = reduce_event(first, event)
        second = reduce_event(second, event)

    assert first == second
    assert project_run_state(events) == "active"
    assert project_node_states(events) == {"worker-1": "ready"}
    assert project_leases(events) == {
        "lease-1": {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "kind": "worker",
            "state": "active",
        }
    }


def test_lease_projection_uses_typed_payload_and_preserves_public_shape() -> None:
    event = _event(
        "lease_granted",
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "generation": 2,
            "execution_id": "exec-1",
            "expires_at": "2026-01-02T00:00:00+00:00",
            "task_region_id": "task-1",
            "kind": "worker",
        },
    )

    projection = reduce_event(initial_projection(), event)
    projected = leases_view(projection)["lease-1"]

    assert isinstance(projected, LeaseProjection)
    assert project_leases([], projection=projection) == {
        "lease-1": {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 2,
            "state": "active",
            "execution_id": "exec-1",
            "expires_at": "2026-01-02T00:00:00+00:00",
            "task_region_id": "task-1",
            "kind": "worker",
        }
    }
    assert project_lease_view([], projection=projection) == {
        "active": [
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 2,
                "state": "active",
                "execution_id": "exec-1",
                "expires_at": "2026-01-02T00:00:00+00:00",
            }
        ],
        "suspended": [],
    }


def test_lease_projection_checkpoint_round_trips_typed_payload_and_drops_malformed_entries() -> (
    None
):
    projection = reduce_event(
        initial_projection(),
        _event(
            "lease_granted",
            {"node_id": "worker-1", "lease_id": "lease-1", "task_region_id": "task-1"},
        ),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    restored_from_historical = projection_from_checkpoint(
        {
            "leases": {
                "lease-2": {"lease_id": "lease-2", "node_id": "worker-2", "state": "active"},
                "bad-state": {"lease_id": "bad-state", "state": 42},
                "bad-entry": "not-a-dict",
            }
        }
    )

    assert isinstance(restored["leases"]["lease-1"], LeaseProjection)
    assert restored["leases"]["lease-1"].task_region_id == "task-1"
    assert restored_from_historical["leases"].keys() == {"lease-2"}
    assert isinstance(restored_from_historical["leases"]["lease-2"], LeaseProjection)
    assert restored_from_historical["leases"]["lease-2"].model_dump(mode="json") == {
        "lease_id": "lease-2",
        "node_id": "worker-2",
        "state": "active",
    }


def test_lease_checkpoint_restores_typed_resource_claims() -> None:
    restored = projection_from_checkpoint(
        {
            "leases": {
                "lease-1": {
                    "lease_id": "lease-1",
                    "state": "active",
                    "resource_claims": [
                        {"mode": "write", "scope": "repo", "paths": ["src/"]},
                    ],
                },
            },
        }
    )

    claim = restored["leases"]["lease-1"].resource_claims[0]
    assert claim.mode == "write"
    assert claim.scope == "repo"
    assert projection_to_checkpoint(restored)["leases"]["lease-1"]["resource_claims"] == [
        {"mode": "write", "scope": "repo", "paths": ["src/"]}
    ]


def test_output_record_payloads_are_typed_at_fold() -> None:
    event = _event(
        "output_record_accepted",
        {
            "record_id": "summary-1",
            "record_kind": "output",
            "record_type": "fan_out_inputs",
            "producer_node_id": "fanout-reader-1",
            "port": "reader_output",
            "schema": "FanOutInputs",
            "value": {"summary": "done"},
        },
    )

    projection = reduce_event(initial_projection(), event)

    payload = output_record_payloads_view(projection)["summary-1"]
    assert isinstance(payload, OutputRecord)
    assert payload.record_id == "summary-1"
    assert payload.producer_node_id == "fanout-reader-1"
    assert payload.port == "reader_output"

    by_port = output_records_by_node_port_view(projection)["fanout-reader-1"]["reader_output"][0]
    assert isinstance(by_port, OutputRecord)
    assert by_port.value == {"summary": "done"}

    accepted = accepted_output_records_by_node_port_view(projection)["fanout-reader-1"][
        "reader_output"
    ][0]
    assert isinstance(accepted["payload"], OutputRecord)
    assert accepted["payload"].schema_ == "FanOutInputs"


def test_output_record_checkpoint_round_trip_preserves_typed_payloads() -> None:
    events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "summary-1",
                "record_kind": "output",
                "record_type": "fan_out_inputs",
                "producer_node_id": "fanout-reader-1",
                "port": "reader_output",
                "schema": "FanOutInputs",
                "value": {"summary": "done"},
            },
        ),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    summary_payload = restored["output_record_payloads"]["summary-1"]
    assert isinstance(summary_payload, OutputRecord)
    assert summary_payload.value == {"summary": "done"}
    assert isinstance(
        restored["output_records_by_node_port"]["fanout-reader-1"]["reader_output"][0],
        OutputRecord,
    )
    assert isinstance(
        restored["accepted_output_records_by_node_port"]["fanout-reader-1"]["reader_output"][0][
            "payload"
        ],
        OutputRecord,
    )


def test_verification_result_projections_are_typed_at_fold() -> None:
    projection = initial_projection()
    for event in [
        _event(
            "verification_passed",
            {
                "record_id": "verification-pass-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "verification_failed",
            {
                "record_id": "verification-fail-1",
                "node_id": "verifier-2",
                "candidate_id": "candidate-2",
            },
        ),
    ]:
        projection = reduce_event(projection, event)

    passed = passed_verification_results_by_record_id_view(projection)["verification-pass-1"]
    assert isinstance(passed, VerificationResultProjection)
    assert passed.node_id == "verifier-1"
    assert passed.candidate_id == "candidate-1"
    assert passed.task_region_id == "task-1"

    failed = failed_verification_results_by_record_id_view(projection)["verification-fail-1"]
    assert isinstance(failed, VerificationResultProjection)
    assert failed.node_id == "verifier-2"
    assert failed.candidate_id == "candidate-2"
    assert failed.task_region_id is None


def test_canonical_verification_result_payload_projects_required_identifiers() -> None:
    projection = initial_projection()
    for event in [
        _event("verification_passed", {"record_id": "missing-node"}),
        _event("verification_failed", {"node_id": "missing-record"}),
    ]:
        projection = reduce_event(projection, event)

    assert set(passed_verification_results_by_record_id_view(projection)) == {"missing-node"}
    assert set(failed_verification_results_by_record_id_view(projection)) == {
        "verification-candidate-1"
    }


def test_verification_result_checkpoint_round_trip_preserves_typed_payloads() -> None:
    projection = initial_projection()
    projection = reduce_event(
        projection,
        _event(
            "verification_passed",
            {
                "record_id": "verification-pass-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    passed = restored["passed_verification_results_by_record_id"]["verification-pass-1"]
    assert isinstance(passed, VerificationResultProjection)
    assert passed.node_id == "verifier-1"
    assert passed.record_id == "verification-pass-1"
    assert passed.candidate_id == "candidate-1"
    assert passed.task_region_id == "task-1"


def test_check_result_projection_summary_is_typed_at_fold() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-1"],
                "file_state_record_ids": ["file-state-candidate-1"],
                "evaluated_record_ids": ["candidate-1", "file-state-candidate-1"],
                "value": {
                    "status": "failed",
                    "classification": "tool_error",
                    "command_text": "pytest",
                    "stderr_tail": "failed",
                    "exit_code": 1,
                },
            },
        ).model_copy(update={"position": 12}),
    )

    check_result = check_results_view(projection)["check-1"]
    assert isinstance(check_result, CheckResultProjection)
    assert check_result.status == "failed"
    assert check_result.position == 12
    assert check_result.record_id == "check-result-1"
    assert check_result.task_region_id == "task-1"
    assert check_result.classification == "tool_error"
    assert check_result.candidate_record_ids == ["candidate-1"]
    assert check_result.file_state_record_ids == ["file-state-candidate-1"]
    assert check_result.evaluated_record_ids == ["candidate-1", "file-state-candidate-1"]


def test_sparse_check_result_fixture_is_completed_to_a_canonical_failed_summary() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-legacy",
                "record_kind": "check_result",
                "producer_node_id": "check-legacy",
            },
        ),
    )

    check_result = check_results_view(projection)["check-legacy"]
    assert isinstance(check_result, CheckResultProjection)
    assert check_result.status == "failed"
    assert check_result.record_id == "check-result-legacy"

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    restored_check_result = restored["check_results"]["check-legacy"]
    assert isinstance(restored_check_result, CheckResultProjection)
    assert restored_check_result.status == "failed"
    assert restored_check_result.record_id == "check-result-legacy"


def test_check_result_checkpoint_round_trip_preserves_typed_summary() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "task_region_id": "task-1",
                "value": {"status": "passed"},
            },
        ).model_copy(update={"position": 12}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    check_result = restored["check_results"]["check-1"]
    assert isinstance(check_result, CheckResultProjection)
    assert check_result.status == "passed"
    assert check_result.position == 12
    assert check_result.record_id == "check-result-1"
    assert check_result.task_region_id == "task-1"


def _accepted_output_records_as_dicts(
    records: dict[str, dict[str, list[Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {
        node_id: {
            port: [
                {
                    "record_id": record["record_id"],
                    "payload": record["payload"].model_dump(mode="json"),
                }
                for record in port_records
            ]
            for port, port_records in ports.items()
        }
        for node_id, ports in records.items()
    }


def test_graph_projection_derived_indexes_match_legacy_event_scan() -> None:
    def legacy_indexes(
        stream: list[EventEnvelope],
    ) -> tuple[
        dict[str, dict[str, list[dict[str, Any]]]],
        dict[str, dict[str, str]],
        dict[str, list[dict[str, str]]],
    ]:
        accepted_by_port: dict[str, dict[str, list[dict[str, Any]]]] = {}
        failed_by_record_id: dict[str, dict[str, str]] = {}
        passed_candidates: set[str] = set()
        recovery_by_record_id: dict[str, list[dict[str, str]]] = {}
        for graph_event in stream:
            if graph_event.event_type == "output_record_accepted":
                node_id = graph_event.payload.get("producer_node_id") or graph_event.payload.get(
                    "node_id"
                )
                port = graph_event.payload.get("port")
                record_id = graph_event.payload.get("record_id")
                if all(isinstance(value, str) and value for value in (node_id, port, record_id)):
                    accepted_by_port.setdefault(cast(str, node_id), {}).setdefault(
                        cast(str, port), []
                    ).append(
                        {
                            "record_id": cast(str, record_id),
                            "payload": graph_event.payload,
                        }
                    )
            elif graph_event.event_type in {"verification_passed", "verification_failed"}:
                candidate_id = graph_event.payload.get("candidate_id")
                if (
                    isinstance(candidate_id, str)
                    and graph_event.event_type == "verification_passed"
                ):
                    passed_candidates.add(candidate_id)
                if graph_event.event_type != "verification_failed":
                    continue
                node_id = graph_event.payload.get("verifier_node_id") or graph_event.payload.get(
                    "node_id"
                )
                record_id = graph_event.payload.get("record_id")
                if not isinstance(node_id, str) or not isinstance(record_id, str):
                    continue
                failed = {"node_id": node_id, "record_id": record_id}
                if isinstance(candidate_id, str) and candidate_id:
                    failed["candidate_id"] = candidate_id
                task_region_id = graph_event.payload.get("task_region_id")
                if isinstance(task_region_id, str) and task_region_id:
                    failed["task_region_id"] = task_region_id
                failed_by_record_id[record_id] = failed
            elif graph_event.event_type == "node_created":
                node_id = graph_event.payload.get("node_id")
                recovery_reason = graph_event.payload.get("recovery_reason")
                record_id = graph_event.payload.get("recovery_of_record_id")
                if not all(
                    isinstance(value, str) and value
                    for value in (node_id, recovery_reason, record_id)
                ):
                    continue
                if recovery_reason not in {"failed_required_check", "failed_verification"}:
                    continue
                recovery_by_record_id.setdefault(cast(str, record_id), []).append(
                    {
                        "node_id": cast(str, node_id),
                        "recovery_reason": cast(str, recovery_reason),
                    }
                )
        current_failed = {
            record_id: failed
            for record_id, failed in failed_by_record_id.items()
            if failed.get("candidate_id") not in passed_candidates
        }
        return accepted_by_port, current_failed, recovery_by_record_id

    store = InMemoryEventStore()
    clock = FakeClock()
    id_gen = SequentialIdGenerator()

    def append_event(event_type: str, payload: dict[str, Any]) -> None:
        store.append(_event(event_type, payload))

    def append_command(command_type: str, payload: dict[str, Any]) -> None:
        events_before = store.read_from("run-1")
        command_projection = initial_projection()
        for graph_event in events_before:
            command_projection = reduce_event(command_projection, graph_event)
        for graph_event in apply_command(
            command_projection,
            events_before,
            command_type,
            payload,
            command_context(events_before),
            clock,
            id_gen,
        ):
            store.append(graph_event)

    append_event("run_lifecycle_changed", {"to_state": "active"})
    append_event(
        "node_created",
        {
            "node_id": "routine-snapshot",
            "kind": "root",
            "state": "completed",
        },
    )
    append_event(
        "output_record_accepted",
        {
            "record_id": "routine-snapshot-record",
            "record_kind": "graph_record",
            "record_type": "routine_snapshot",
            "producer_node_id": "routine-snapshot",
            "port": "snapshot",
            "schema": "RoutineSnapshot",
            "value": {
                "routine_id": "routine-1",
                "name": "Routine 1",
                "content_hash": "hash-routine-1",
                "step_count": 1,
                "task_count": 1,
            },
        },
    )
    append_event(
        "node_created",
        {
            "node_id": "worker-1",
            "kind": "worker",
            "state": "running",
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
        },
    )
    append_event(
        "node_created",
        {
            "node_id": "verifier-1",
            "kind": "verifier",
            "state": "planned",
            "task_region_id": "task-1",
        },
    )
    append_event(
        "edge_created",
        {
            "edge_id": "edge-worker-verifier",
            "from_node_id": "worker-1",
            "from_port": "candidate",
            "to_node_id": "verifier-1",
            "to_port": "candidate_under_test",
            "required": True,
            "accepted_record_selector": {
                "record_type": "candidate",
                "schema": "ImplementationCandidate",
            },
        },
    )
    append_event(
        "lease_granted",
        {
            "node_id": "worker-1",
            "lease_id": "lease-worker",
            "generation": 1,
            "execution_id": "exec-worker",
            "base_snapshot_id": "S0",
        },
    )
    append_command(
        "submit_callback",
        {
            "node_id": "worker-1",
            "execution_id": "exec-worker",
            "lease_id": "lease-worker",
            "lease_generation": 1,
            "base_snapshot_id": "S0",
            "observed_graph_position": store.snapshot_position("run-1"),
            "idempotency_key": "worker-submit",
            "payload_hash": "hash-worker",
            "payload": {
                "payload_hash": "hash-worker",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "record_type": "candidate",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "candidate_id": "candidate-1",
                        "value": {"summary": "done"},
                    }
                ],
            },
        },
    )
    append_event(
        "node_state_changed",
        {
            "node_id": "verifier-1",
            "new_state": "running",
            "trigger": "test_dispatch",
        },
    )
    append_event(
        "lease_granted",
        {
            "node_id": "verifier-1",
            "lease_id": "lease-verifier",
            "generation": 1,
            "execution_id": "exec-verifier",
            "base_snapshot_id": "S0",
        },
    )
    append_command(
        "submit_callback",
        {
            "node_id": "verifier-1",
            "execution_id": "exec-verifier",
            "lease_id": "lease-verifier",
            "lease_generation": 1,
            "base_snapshot_id": "S0",
            "observed_graph_position": store.snapshot_position("run-1"),
            "idempotency_key": "verifier-submit",
            "payload_hash": "hash-verifier",
            "payload": {
                "payload_hash": "hash-verifier",
                "output_records": [
                    {
                        "record_id": "verification-1",
                        "record_kind": "verification",
                        "record_type": "verification_report",
                        "producer_node_id": "verifier-1",
                        "port": "verification_report",
                        "candidate_id": "candidate-1",
                        "outcome": "failed",
                        "value": {
                            "outcome": "failed",
                            "grades": [{"requirement_id": "req-1", "grade": "C"}],
                        },
                    }
                ],
            },
        },
    )
    append_command(
        "schedule_tick",
        {
            "lease_seconds": 300,
            "max_grants": 0,
            "base_snapshot_id": "S0",
        },
    )

    events = store.read_from("run-1")
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    legacy_accepted_by_port, legacy_failed_verifications, legacy_recovery_nodes = legacy_indexes(
        events
    )

    assert (
        _accepted_output_records_as_dicts(accepted_output_records_by_node_port_view(projection))
        == legacy_accepted_by_port
    )
    assert {
        record_id: result.model_dump(mode="json")
        for record_id, result in failed_verification_results_by_record_id_view(projection).items()
    } == legacy_failed_verifications
    assert recovery_nodes_by_record_id_view(projection) == legacy_recovery_nodes


def test_residual_command_projection_fields_fold_incrementally() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}
        ).model_copy(update={"position": 3}),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-1",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "value": {"status": "passed"},
            },
        ).model_copy(update={"position": 4}),
        _event(
            "verification_passed",
            {
                "record_id": "verification-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 5}),
        _event(
            "verification_failed",
            {
                "record_id": "verification-2",
                "verifier_node_id": "verifier-2",
                "candidate_id": "candidate-2",
            },
        ).model_copy(update={"position": 6}),
        _event(
            "runtime_retry_scheduled",
            {
                "node_id": "worker-1",
                "retry_not_before": "2025-01-01T00:01:00+00:00",
            },
        ).model_copy(update={"position": 7}),
        _event(
            "cleanup_requested",
            {"cleanup_id": "cleanup-1", "file_state_record_id": "file-state-1"},
        ).model_copy(update={"position": 8}),
        _event(
            "cleanup_requested",
            {"cleanup_id": "cleanup-1", "file_state_record_id": "file-state-2"},
        ).model_copy(update={"position": 9}),
        _event("cleanup_applied", {"cleanup_id": "cleanup-1"}).model_copy(update={"position": 10}),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    assert node_creation_positions_view(projection) == {"worker-1": 3}
    assert completion_decision_passed(projection) is True
    assert {
        record_id: result.model_dump(mode="json")
        for record_id, result in passed_verification_results_by_record_id_view(projection).items()
    } == {
        "verification-1": {
            "node_id": "verifier-1",
            "record_id": "verification-1",
            "candidate_id": "candidate-1",
            "task_region_id": "task-1",
        }
    }
    assert failed_verification_candidate_ids_view(projection) == {"candidate-2": True}
    assert retry_not_before_by_node_view(projection) == {"worker-1": "2025-01-01T00:01:00+00:00"}
    assert cleanup_requested_events_view(projection)["cleanup-1"].position == 8
    assert (
        cleanup_requested_events_view(projection)["cleanup-1"].file_state_record_id
        == "file-state-1"
    )
    assert cleanup_applied_ids_view(projection) == {"cleanup-1": True}


def test_cleanup_requested_events_checkpoint_round_trips_typed_envelopes() -> None:
    projection = initial_projection()
    for event in [
        _event(
            "cleanup_requested",
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "paths": ["secrets.env"],
            },
        ).model_copy(update={"position": 8}),
        _event(
            "cleanup_requested",
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-2",
                "paths": ["ignored.env"],
            },
        ).model_copy(update={"position": 9}),
    ]:
        projection = reduce_event(projection, event)

    projected = cleanup_requested_events_view(projection)["cleanup-1"]

    assert isinstance(projected, CleanupRequestedProjection)
    assert projected.cleanup_id == "cleanup-1"
    assert projected.position == 8
    assert projected.file_state_record_id == "file-state-1"
    assert projected.paths == ["secrets.env"]

    checkpoint = projection_to_checkpoint(projection)
    assert checkpoint["cleanup_requested_events"]["cleanup-1"]["position"] == 8

    restored = projection_from_checkpoint(checkpoint)
    restored_projected = restored["cleanup_requested_events"]["cleanup-1"]

    assert isinstance(restored_projected, CleanupRequestedProjection)
    assert restored_projected.position == 8
    assert restored_projected.paths == ["secrets.env"]


def test_malformed_cleanup_requested_checkpoint_entry_is_dropped() -> None:
    restored = projection_from_checkpoint(
        {
            "cleanup_requested_events": {
                "cleanup-1": {
                    "event_id": "cleanup-requested-event",
                    "position": "bad",
                    "event_type": "cleanup_requested",
                    "payload": {"cleanup_id": "cleanup-1"},
                }
            }
        }
    )

    assert restored["cleanup_requested_events"] == {}


def test_requirement_revisions_replay_active_versions() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v1",
                "revision_index": 1,
                "classification": "initial",
            },
        ).model_copy(update={"position": 1}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
                "previous_version_id": "R-1.v1",
                "revision_index": 2,
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 2}),
    ]

    revisions = project_requirement_revisions(events)

    assert revisions["R-1.v1"]["requirement_id"] == "R-1"
    assert revisions["R-1.v2"] == {
        "requirement_id": "R-1",
        "version_id": "R-1.v2",
        "change_classification": "validation_strengthening",
        "requires_authority": False,
        "position": 2,
        "previous_version_id": "R-1.v1",
        "revision_index": 2,
        "validation_strengthening": True,
    }
    assert project_requirement_freshness_facts(events) == [
        {
            "requirement_id": "R-1",
            "active_version_id": "R-1.v2",
            "revision_classification": "validation_strengthening",
            "requires_authority": False,
            "authority_required_reason": None,
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        }
    ]


def test_support_evidence_freshness_can_be_queried_from_projection() -> None:
    state = initial_projection()
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
        ).model_copy(update={"position": 2}),
    ]
    for event in events:
        state = reduce_event(state, event)

    assert support_evidence_freshness_from_projection(state) == {
        "S-1": {
            "support_id": "S-1",
            "evidence_id": "E-1",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v1",
            "status": "active",
            "freshness": "fresh",
            "stale_reason": None,
        }
    }


def test_validation_strengthening_revision_invalidates_older_support_evidence() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-old",
                "evidence_id": "E-old",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
                "previous_version_id": "R-1.v1",
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 3}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-new",
                "evidence_id": "E-new",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v2",
            },
        ).model_copy(update={"position": 4}),
    ]

    assert project_support_evidence_freshness(events) == {
        "S-new": {
            "support_id": "S-new",
            "evidence_id": "E-new",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v2",
            "status": "active",
            "freshness": "fresh",
            "stale_reason": None,
        },
        "S-old": {
            "support_id": "S-old",
            "evidence_id": "E-old",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v1",
            "status": "stale",
            "freshness": "stale",
            "stale_reason": (
                "Evidence was produced for an older requirement version and does not "
                "prove the strengthened validation definition."
            ),
        },
    }


def test_semantic_and_new_behavior_revisions_require_explicit_authority() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v1",
                "classification": "semantic",
            },
        ).model_copy(update={"position": 1}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-2",
                "version_id": "R-2.v1",
                "new_behavior": True,
            },
        ).model_copy(update={"position": 2}),
    ]

    facts = project_requirement_freshness_facts(events)

    assert facts == [
        {
            "requirement_id": "R-1",
            "active_version_id": "R-1.v1",
            "revision_classification": "semantic",
            "requires_authority": True,
            "authority_required_reason": "semantic",
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        },
        {
            "requirement_id": "R-2",
            "active_version_id": "R-2.v1",
            "revision_classification": "new_behavior",
            "requires_authority": True,
            "authority_required_reason": "new_behavior",
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        },
    ]


def test_planner_freshness_packet_is_compact_gap_planner_input() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-2",
                "version_id": "R-2.v1",
                "classification": "semantic",
            },
        ).model_copy(update={"position": 3}),
    ]

    assert project_planner_freshness_packet(events) == {
        "requirement_freshness": [
            {
                "requirement_id": "R-1",
                "active_version_id": "R-1.v1",
                "revision_classification": "initial",
                "requires_authority": False,
                "authority_required_reason": None,
                "fresh_support_ids": ["S-1"],
                "stale_support_ids": [],
                "unsupported": False,
            },
            {
                "requirement_id": "R-2",
                "active_version_id": "R-2.v1",
                "revision_classification": "semantic",
                "requires_authority": True,
                "authority_required_reason": "semantic",
                "fresh_support_ids": [],
                "stale_support_ids": [],
                "unsupported": True,
            },
        ],
        "unsupported_requirement_ids": ["R-2"],
        "stale_support_ids": [],
        "authority_required_requirement_ids": ["R-2"],
    }


def test_projection_immutability() -> None:
    state: GraphProjection = {
        "run_state": "active",
        "node_states": {"worker-1": "ready"},
        "task_states": {"task-1": "running"},
        "leases": {"lease-1": {"lease_id": "lease-1", "state": "active"}},
        "ready_nodes": ["worker-1"],
        "node_kinds": {},
        "node_roles": {},
        "node_creation_positions": {},
        "node_task_regions": {},
        "node_attempts": {},
        "node_candidates": {},
        "node_failed_candidates": {},
        "node_resource_claims": {},
        "node_allowed_actions": {},
        "node_preconditions": {},
        "node_command_definitions": {},
        "edges": {},
        "input_bindings": {},
        "node_pending_appeals": {},
        "node_gate_decisions": {},
        "task_candidates": {},
        "verifier_verdicts": {},
        "completion_decision_passed": False,
        "passed_verification_results_by_record_id": {},
        "failed_verification_candidate_ids": {},
        "invalid_test_blocks": {},
        "configured_gates": {},
        "gate_decisions": {},
        "environment_failures": {},
        "file_state_records": {},
        "planner_generation_budget": 8,
        "planner_successors": {},
        "planner_generations": {},
        "retry_not_before_by_node": {},
        "cleanup_requested_events": {},
        "cleanup_applied_ids": {},
    }

    next_state = reduce_event(
        state,
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
    )

    assert next_state is not state
    assert state == {
        "run_state": "active",
        "node_states": {"worker-1": "ready"},
        "task_states": {"task-1": "running"},
        "leases": {"lease-1": {"lease_id": "lease-1", "state": "active"}},
        "ready_nodes": ["worker-1"],
        "node_kinds": {},
        "node_roles": {},
        "node_creation_positions": {},
        "node_task_regions": {},
        "node_attempts": {},
        "node_candidates": {},
        "node_failed_candidates": {},
        "node_resource_claims": {},
        "node_allowed_actions": {},
        "node_preconditions": {},
        "node_command_definitions": {},
        "edges": {},
        "input_bindings": {},
        "node_pending_appeals": {},
        "node_gate_decisions": {},
        "task_candidates": {},
        "verifier_verdicts": {},
        "completion_decision_passed": False,
        "passed_verification_results_by_record_id": {},
        "failed_verification_candidate_ids": {},
        "invalid_test_blocks": {},
        "configured_gates": {},
        "gate_decisions": {},
        "environment_failures": {},
        "file_state_records": {},
        "planner_generation_budget": 8,
        "planner_successors": {},
        "planner_generations": {},
        "retry_not_before_by_node": {},
        "cleanup_requested_events": {},
        "cleanup_applied_ids": {},
    }
    assert node_states_view(next_state) == {"worker-1": "running"}


def test_run_state_transitions() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "draft", "to_state": "queued"}),
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_run_state(events) == "completed"


def test_final_invariant_blockers_are_projected_from_graph_events() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "ready",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "gate-planner-budget-planner-1",
                "kind": "gate",
                "role": "planner_generation_budget_gate",
                "state": "planned",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
    ]

    blockers: list[FinalInvariantBlocker] = project_final_invariant_blockers(events)
    assert blockers == [
        {
            "kind": "pending_planner_generation_budget_gate",
            "reason": "planner generation budget gate is unresolved",
            "node_id": "gate-planner-budget-planner-1",
            "state": "planned",
        },
        {
            "kind": "pending_planner",
            "reason": "planner node has not completed",
            "node_id": "planner-1",
            "state": "ready",
        },
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        },
    ]


def test_final_invariant_blockers_include_generic_non_terminal_nodes() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "blocked",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "state": "suspended",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "running",
                "task_region_id": "task-1",
            },
        ),
    ]

    blockers: list[FinalInvariantBlocker] = project_final_invariant_blockers(events)

    assert blockers == [
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "authority-1",
            "state": "blocked",
        },
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "human-gate-1",
            "state": "blocked",
        },
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "verifier-1",
            "state": "suspended",
            "task_region_id": "task-1",
        },
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "worker-1",
            "state": "running",
            "task_region_id": "task-1",
        },
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        },
    ]


def test_check_only_task_region_uses_contract_fulfillment() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-check-only",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-1-result",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "task_region_id": "task-check-only",
                "value": {"status": "passed"},
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert blockers == []
    assert project_task_states(events) == {"task-check-only": "accepted"}


def test_check_only_task_region_missing_contract_output_is_blocked() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-check-only",
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert {
        "kind": "node_unfulfilled",
        "reason": "node contract fulfillment outputs are missing",
        "node_id": "check-1",
        "state": "completed",
        "support_ids": ["check_result"],
        "task_region_id": "task-check-only",
    } in blockers
    assert {
        "kind": "task_not_accepted",
        "reason": "task region has not reached accepted",
        "task_region_id": "task-check-only",
        "state": "pending",
    } in blockers


def test_final_invariant_blockers_explain_required_edge_with_missing_producer() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-missing-candidate",
                "from_node_id": "missing-worker",
                "from_port": "candidate",
                "to_node_id": "worker-1",
                "to_port": "candidate",
                "required": True,
                "dependency_type": "input_binding",
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert {
        "kind": "impossible_input",
        "reason": "required input edge has no producer node",
        "node_id": "worker-1",
        "edge_id": "edge-missing-candidate",
        "to_port": "candidate",
        "task_region_id": "task-1",
        "state": "planned",
    } in blockers


def test_gap_planner_task_region_uses_contract_fulfillment() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "completed",
                "task_region_id": "task-planner-only",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "gap-planner-1",
                "kind": "gap_planner",
                "state": "completed",
                "task_region_id": "task-gap-only",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "classified-gap-1",
                "record_kind": "output",
                "record_type": "classified_gap",
                "producer_node_id": "gap-planner-1",
                "port": "classified_gap",
                "schema": "GapClassification",
                "value": {
                    "milestone_kind": "gap_analysis",
                    "classification": "no_gap",
                    "source": "test",
                    "task_region_id": "task-gap-only",
                    "attempt_number": 0,
                },
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert {
        "kind": "task_not_accepted",
        "reason": "task region has not reached accepted",
        "task_region_id": "task-planner-only",
        "state": "pending",
    } in blockers
    assert all(blocker.get("task_region_id") != "task-gap-only" for blocker in blockers)
    assert project_task_states(events) == {
        "task-gap-only": "accepted",
        "task-planner-only": "pending",
    }


def test_active_nonterminal_random_graph_shapes_have_explicit_blockers() -> None:
    rng = random.Random(17)
    node_kinds = ["worker", "verifier", "check", "human_gate", "authority_request"]
    node_states = ["planned", "ready", "leased", "running", "blocked", "suspended"]

    for graph_index in range(30):
        events = [_event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"})]
        node_count = rng.randint(1, 6)
        expected_node_ids: set[str] = set()
        for node_index in range(node_count):
            kind = rng.choice(node_kinds)
            state = rng.choice(node_states)
            node_id = f"{kind}-{graph_index}-{node_index}"
            task_region_id = f"task-{graph_index}-{rng.randint(1, 3)}"
            payload: dict[str, Any] = {
                "node_id": node_id,
                "kind": kind,
                "state": state,
            }
            if kind not in {"human_gate", "authority_request"}:
                payload["task_region_id"] = task_region_id
            events.append(_event("node_created", payload))
            expected_node_ids.add(node_id)

        blockers = project_final_invariant_blockers(events)
        blocker_node_ids = {
            node_id for blocker in blockers if isinstance((node_id := blocker.get("node_id")), str)
        }

        assert blockers, f"graph {graph_index} silently quiesced"
        assert expected_node_ids <= blocker_node_ids


def test_decision_view_projects_human_gate_and_authority_request() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "blocked",
                "reason": "approve final scope",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
                "reason": "needs graph_write",
            },
        ),
    ]

    view = project_decision_view(events)

    assert view["pending_gates"] == [
        {
            "node_id": "authority-1",
            "gate_type": "authority_request",
            "prompt": "needs graph_write",
        },
        {
            "node_id": "human-gate-1",
            "gate_type": "approve final scope",
            "prompt": "approve final scope",
        },
    ]


def test_decision_view_clears_resolved_authority_request() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
                "reason": "needs graph_write",
            },
        ),
        _event(
            "authority_decision_recorded",
            {
                "node_id": "authority-1",
                "decision": "granted",
                "decider": {"kind": "human", "id": "alice"},
            },
        ),
    ]

    assert project_decision_view(events)["pending_gates"] == []


def test_completed_lifecycle_projects_active_while_final_blockers_remain() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        }
    ]
    assert project_run_state(events) == "active"


def test_final_blockers_report_dead_required_input_from_terminal_source() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-dead",
                "kind": "worker",
                "state": "failed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-blocked",
                "kind": "verifier",
                "state": "blocked",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-dead-candidate",
                "from_node_id": "worker-dead",
                "from_port": "candidate",
                "to_node_id": "verifier-blocked",
                "to_port": "candidate_under_test",
                "required": True,
            },
        ),
    ]

    assert {
        "kind": "dead_required_input",
        "reason": "required input source is terminal before producing a bound record",
        "node_id": "verifier-blocked",
        "edge_id": "edge-dead-candidate",
        "from_node_id": "worker-dead",
        "to_port": "candidate_under_test",
        "state": "blocked",
        "task_region_id": "task-1",
    } in project_final_invariant_blockers(events)


def test_final_gate_requires_passed_completion_decision_for_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "missing_completion_decision",
            "reason": "final gate has not produced a completion_decision",
            "node_id": "gate-final",
            "state": "completed",
        }
    ]
    assert project_run_state(events) == "active"


def test_blocked_final_gate_completion_decision_keeps_projected_run_active() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {
                    "status": "blocked",
                    "blockers": [
                        {
                            "kind": "open_planner_proposal",
                            "reason": "planner proposal has not been accepted or rejected",
                            "proposal_id": "proposal-1",
                        }
                    ],
                },
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "open_planner_proposal",
            "reason": "planner proposal has not been accepted or rejected",
            "proposal_id": "proposal-1",
        }
    ]
    assert project_run_state(events) == "active"


def test_passed_final_gate_completion_decision_allows_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {"status": "passed", "blockers": []},
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_pending_gap_planner_blocks_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "gap-planner-1",
                "kind": "gap_planner",
                "role": "gap_planner",
                "state": "leased",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "pending_gap_planner",
            "reason": "planner node has not completed",
            "node_id": "gap-planner-1",
            "state": "leased",
        }
    ]
    assert project_run_state(events) == "active"


def test_pending_check_blocks_projected_completion_after_task_acceptance() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "planned",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}
    assert project_final_invariant_blockers(events) == [
        {
            "kind": "pending_check",
            "reason": "check node has not completed",
            "node_id": "check-final-1",
            "state": "planned",
        }
    ]
    assert project_run_state(events) == "active"


def test_failed_check_result_blocks_projected_completion_after_task_acceptance() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-1"],
                "file_state_record_ids": ["file-state-candidate-1"],
                "evaluated_record_ids": ["candidate-1", "file-state-candidate-1"],
                "value": {
                    "status": "failed",
                    "exit_code": 1,
                    "candidate_record_ids": ["candidate-1"],
                    "file_state_record_ids": ["file-state-candidate-1"],
                    "evaluated_record_ids": ["candidate-1", "file-state-candidate-1"],
                },
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    check_result = check_results_view(projection)["check-final-1"]
    assert check_result.candidate_record_ids == ["candidate-1"]
    assert check_result.file_state_record_ids == ["file-state-candidate-1"]
    assert check_result.evaluated_record_ids == ["candidate-1", "file-state-candidate-1"]
    assert project_task_states(events) == {"task-1": "pending"}
    assert project_final_invariant_blockers(events) == [
        {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
            "classification": "failed",
            "command_text": "check command",
            "stderr_tail": "",
            "exit_code": 1,
            "node_id": "check-final-1",
            "task_region_id": "task-1",
            "state": "failed",
        },
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        },
    ]
    assert project_run_state(events) == "active"


def test_failed_check_result_recovery_lineage_unblocks_original_task() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-1"],
                "file_state_record_ids": ["file-state-candidate-1"],
                "value": {"status": "failed"},
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-check-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-task-1",
                "recovery_reason": "failed_required_check",
                "recovery_of_record_id": "check-result-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-repair",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-recovery-to-repair",
                "from_node_id": "planner-recover-check-1",
                "from_port": "classified_gap",
                "to_node_id": "worker-repair",
                "to_port": "classified_gap",
                "required": True,
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-repair",
                "record_kind": "output",
                "producer_node_id": "worker-repair",
                "port": "candidate",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-repair",
            },
        ),
        _file_state_event("corrective_work_region", "candidate-repair", 11),
        _event(
            "node_created",
            {
                "node_id": "verifier-repair",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-repair-to-verifier",
                "from_node_id": "worker-repair",
                "from_port": "candidate",
                "to_node_id": "verifier-repair",
                "to_port": "candidate_under_test",
                "required": True,
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-repair",
                "candidate_id": "candidate-repair",
                "task_region_id": "corrective_work_region",
                "record_id": "verification-repair",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events)["task-1"] == "accepted"
    assert not any(
        blocker["kind"] == "failed_check_result"
        for blocker in project_final_invariant_blockers(events)
    )


def test_failed_verification_recovery_lineage_unblocks_original_task() -> None:
    events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 1,
            },
        ),
        _file_state_event("task-1", "candidate-1", 1),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "record_id": "verification-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-verification-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-task-1",
                "recovery_reason": "failed_verification",
                "recovery_of_record_id": "verification-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-repair",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-recovery-to-repair",
                "from_node_id": "planner-recover-verification-1",
                "from_port": "classified_gap",
                "to_node_id": "worker-repair",
                "to_port": "classified_gap",
                "required": True,
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-repair",
                "record_kind": "output",
                "producer_node_id": "worker-repair",
                "port": "candidate",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-repair",
            },
        ),
        _file_state_event("corrective_work_region", "candidate-repair", 6),
        _event(
            "node_created",
            {
                "node_id": "verifier-repair",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-repair-to-verifier",
                "from_node_id": "worker-repair",
                "from_port": "candidate",
                "to_node_id": "verifier-repair",
                "to_port": "candidate_under_test",
                "required": True,
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-repair",
                "candidate_id": "candidate-repair",
                "task_region_id": "corrective_work_region",
                "record_id": "verification-repair",
            },
        ),
    ]

    assert project_task_states(events)["task-1"] == "accepted"


def test_task_state_projection_matches_full_projection_for_recovery_supersession() -> None:
    events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 1,
            },
        ),
        _file_state_event("task-1", "candidate-1", 1),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "record_id": "verification-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-verification-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-task-1",
                "recovery_reason": "failed_verification",
                "recovery_of_record_id": "verification-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-repair",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-recovery-to-verifier",
                "from_node_id": "planner-recover-verification-1",
                "from_port": "classified_gap",
                "to_node_id": "verifier-repair",
                "to_port": "classified_gap",
                "required": True,
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-repair",
                "candidate_id": "candidate-repair",
                "task_region_id": "corrective_work_region",
                "record_id": "verification-repair",
            },
        ),
    ]

    full_projection = initial_projection()
    for event in events:
        full_projection = reduce_event(full_projection, event)

    assert project_task_states(events, projection=full_projection) == project_task_states(events)


def test_failed_verification_recovery_without_corrective_file_state_does_not_accept_origin() -> (
    None
):
    events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 1,
            },
        ),
        _file_state_event("task-1", "candidate-1", 1),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "record_id": "verification-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-verification-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-task-1",
                "recovery_reason": "failed_verification",
                "recovery_of_record_id": "verification-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-repair",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-recovery-to-verifier",
                "from_node_id": "planner-recover-verification-1",
                "from_port": "classified_gap",
                "to_node_id": "verifier-repair",
                "to_port": "classified_gap",
                "required": True,
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-repair",
                "candidate_id": "candidate-repair",
                "task_region_id": "corrective_work_region",
                "record_id": "verification-repair",
            },
        ),
    ]

    assert project_task_states(events)["task-1"] == "needs_revision"


def test_check_result_candidate_id_does_not_replace_latest_task_candidate() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 1}),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 2}),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-check-final-1",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-1"],
                "evaluated_record_ids": ["candidate-1"],
                "value": {
                    "status": "passed",
                    "exit_code": 0,
                    "candidate_record_ids": ["candidate-1"],
                    "evaluated_record_ids": ["candidate-1"],
                },
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    candidate = task_candidates_view(projection)["task-1"][0]
    assert isinstance(candidate, CandidateProjection)
    assert candidate.candidate_id == "candidate-1"
    assert candidate.attempt_number == 0
    assert candidate.position == 1
    assert candidate.file_state_record_ids == []
    assert candidate.supersedes_task_region_ids == []
    assert project_task_states(events) == {"task-1": "accepted"}
    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_uncited_check_result_does_not_accept_task_region() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "file_state_record_ids": ["file-state-candidate-1"],
                "value": {"file_state_record_ids": ["file-state-candidate-1"]},
            },
        ).model_copy(update={"position": 1}),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 2}),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-check-final-1",
                "task_region_id": "task-1",
                "value": {"status": "passed", "exit_code": 0},
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events) == {"task-1": "pending"}
    assert project_final_invariant_blockers(events) == [
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        }
    ]
    assert project_run_state(events) == "active"


def test_check_result_must_cite_latest_candidate_file_state() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-old",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-old",
                "task_region_id": "task-1",
                "attempt_number": 1,
                "file_state_record_ids": ["file-state-old"],
                "value": {"file_state_record_ids": ["file-state-old"]},
            },
        ).model_copy(update={"position": 1}),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-new",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-new",
                "task_region_id": "task-1",
                "attempt_number": 2,
                "file_state_record_ids": ["file-state-candidate-new"],
                "value": {"file_state_record_ids": ["file-state-candidate-new"]},
            },
        ).model_copy(update={"position": 2}),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-new",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 3}),
        _file_state_event("task-1", "candidate-new", 4),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-old"],
                "file_state_record_ids": ["file-state-old"],
                "value": {
                    "status": "passed",
                    "candidate_record_ids": ["candidate-old"],
                    "file_state_record_ids": ["file-state-old"],
                },
            },
        ).model_copy(update={"position": 5}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events) == {"task-1": "pending"}
    assert project_run_state(events) == "active"


def test_freshness_and_authority_facts_block_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-01", "version_id": "R-01.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-old",
                "evidence_id": "E-old",
                "requirement_id": "R-01",
                "requirement_version_id": "R-01.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-01",
                "version_id": "R-01.v2",
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 3}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-02",
                "version_id": "R-02.v1",
                "classification": "semantic",
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "stale_support_evidence",
            "reason": "active requirement is supported only by stale evidence",
            "requirement_id": "R-01",
            "support_ids": ["S-old"],
        },
        {
            "kind": "unsupported_active_requirement",
            "reason": "active requirement has no current supporting evidence",
            "requirement_id": "R-01",
            "support_ids": ["S-old"],
        },
        {
            "kind": "unsupported_active_requirement",
            "reason": "active requirement has no current supporting evidence",
            "requirement_id": "R-02",
            "support_ids": [],
        },
        {
            "kind": "unresolved_authority_required_revision",
            "reason": "semantic or new-behavior requirement revision lacks authority resolution",
            "revision_id": "R-02.v1",
            "requirement_id": "R-02",
        },
    ]
    assert project_run_state(events) == "active"


def test_later_fresh_support_clears_requirement_freshness_blocker() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-01", "version_id": "R-01.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-old",
                "evidence_id": "E-old",
                "requirement_id": "R-01",
                "requirement_version_id": "R-01.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-01",
                "version_id": "R-01.v2",
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 3}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-fresh",
                "evidence_id": "E-fresh",
                "requirement_id": "R-01",
                "requirement_version_id": "R-01.v2",
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_suspect_and_blocked_requirement_facts_block_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}),
        _event(
            "node_created",
            {
                "node_id": "requirement-1",
                "kind": "requirement",
                "state": "blocked",
                "requirement": {"id": "R-01", "priority": "expected"},
            },
        ),
        _event(
            "plan_region_marked_suspect",
            {"region_node_ids": ["worker-1"], "reason": "requirement_changed"},
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "suspect_active_node",
            "reason": "requirement_changed",
            "node_id": "worker-1",
            "state": "ready",
        },
        {
            "kind": "blocked_requirement",
            "reason": "must or expected requirement is blocked without accepted blocker",
            "node_id": "requirement-1",
            "requirement_id": "R-01",
            "state": "blocked",
        },
    ]
    assert project_run_state(events) == "active"


def test_run_unknown_event_ignored() -> None:
    initial = initial_projection()
    next_state = reduce_event(initial, _event("unknown_event", {"to_state": "failed"}))

    assert next_state == initial
    assert next_state is not initial


def test_node_created_sets_planned() -> None:
    events = [_event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"})]

    assert project_node_states(events) == {"worker-1": "planned"}


def test_node_state_transitions() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "ready"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "completed"}),
    ]

    assert project_node_states(events) == {"worker-1": "completed"}


def test_ready_nodes_derived() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}),
        _event("node_created", {"node_id": "worker-2", "kind": "worker", "state": "planned"}),
        _event("node_state_changed", {"node_id": "worker-2", "new_state": "ready"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
    ]

    assert project_ready_nodes(events) == ["worker-2"]


def test_lease_lifecycle() -> None:
    events = [
        _event(
            "lease_granted",
            {"node_id": "worker-1", "lease_id": "lease-1", "generation": 2},
        ),
        _event("lease_suspended", {"lease_id": "lease-1"}),
        _event("lease_revoked", {"lease_id": "lease-1"}),
        _event("lease_expired", {"lease_id": "lease-1"}),
        _event("lease_released", {"lease_id": "lease-1"}),
    ]

    assert project_leases(events) == {
        "lease-1": {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 2,
            "state": "released",
        }
    }


def test_task_projection_accepted() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_passed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _file_state_event("task-1", "cand-1", 2),
        _event(
            "approval_decision_recorded",
            {"task_region_id": "task-1", "gate_id": "gate-1", "decision": "approved"},
        ).model_copy(update={"position": 3}),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_accepts_no_verifier_region_after_file_state() -> None:
    events = [
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 1}),
        _file_state_event("task-1", "candidate-1", 2),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_configured_gate_requires_decision() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "gate",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 2}
        ),
        _file_state_event("task-1", "cand-1", 3),
    ]

    assert project_task_states(events) == {"task-1": "pending"}

    approved_events = [
        *events,
        _event(
            "approval_decision_recorded",
            {"node_id": "gate-1", "decision": "approved"},
        ).model_copy(update={"position": 3}),
    ]
    assert project_task_states(approved_events) == {"task-1": "accepted"}

    rejected_events = [
        *events,
        _event(
            "approval_decision_recorded",
            {"node_id": "gate-1", "decision": "rejected"},
        ).model_copy(update={"position": 3}),
    ]
    assert project_task_states(rejected_events) == {"task-1": "pending"}


def test_task_projection_needs_revision() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
    ]

    assert project_task_states(events) == {"task-1": "needs_revision"}


def test_corrective_region_pass_supersedes_origin_needs_revision() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "origin", "candidate_id": "cand-origin", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-origin"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "output_record_accepted",
            {
                "task_region_id": "corrective",
                "candidate_id": "cand-fix",
                "attempt_number": 1,
                "supersedes_task_region_id": "origin",
            },
        ).model_copy(update={"position": 2}),
        _event("verification_passed", {"candidate_id": "cand-fix"}).model_copy(
            update={"position": 3}
        ),
        _file_state_event("corrective", "cand-fix", 4),
    ]

    assert project_task_states(events) == {
        "corrective": "accepted",
        "origin": "accepted",
    }


def test_verification_output_record_is_not_projected_as_candidate() -> None:
    events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 1,
            },
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "task_region_id": "task-1",
                "candidate_id": "candidate-2",
                "attempt_number": 99,
            },
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "candidate-1"}).model_copy(
            update={"position": 2}
        ),
        _file_state_event("task-1", "candidate-1", 3),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_blocked_invalid_test() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
    ]

    assert project_task_states(events) == {"task-1": "blocked_invalid_test"}


def test_invalid_test_block_projection_uses_typed_payload_and_preserves_task_state_behavior() -> (
    None
):
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    projected = invalid_test_blocks_view(projection)["task-1"]

    assert isinstance(projected, InvalidTestBlockProjection)
    assert projected.accepted is True
    assert project_task_states(events) == {"task-1": "blocked_invalid_test"}


def test_invalid_test_block_checkpoint_round_trips_typed_payload_and_drops_malformed_entries() -> (
    None
):
    projection = reduce_event(
        initial_projection(),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    restored_from_historical = projection_from_checkpoint(
        {
            "invalid_test_blocks": {
                "task-2": {"accepted": True, "candidate_id": "cand-2", "position": 4},
                "bad-position": {"accepted": True, "position": "late"},
                "bad-entry": "not-a-dict",
            }
        }
    )

    assert isinstance(restored["invalid_test_blocks"]["task-1"], InvalidTestBlockProjection)
    assert restored["invalid_test_blocks"]["task-1"].position == 2
    assert restored_from_historical["invalid_test_blocks"].keys() == {"task-2"}
    assert isinstance(
        restored_from_historical["invalid_test_blocks"]["task-2"],
        InvalidTestBlockProjection,
    )
    assert restored_from_historical["invalid_test_blocks"]["task-2"].model_dump(mode="json") == {
        "accepted": True,
        "candidate_id": "cand-2",
        "position": 4,
    }


def test_task_projection_blocked_environment() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {
                "task_region_id": "task-1",
                "record_kind": "check_result",
                "value": {"classification": "tool_unavailable"},
            },
        ).model_copy(update={"position": 1}),
    ]

    assert project_task_states(events) == {"task-1": "blocked_environment"}


def test_task_projection_in_progress() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"}
        ),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}),
    ]

    assert project_task_states(events) == {"task-1": "in_progress"}


def test_task_projection_pending() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"}
        )
    ]

    assert project_task_states(events) == {"task-1": "pending"}


def test_task_projection_latest_candidate_by_attempt_then_position() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-old", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-new-pos", "attempt_number": 1},
        ).model_copy(update={"position": 2}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-new-attempt", "attempt_number": 2},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-new-pos"}).model_copy(
            update={"position": 3}
        ),
        _event("verification_failed", {"candidate_id": "cand-new-attempt"}).model_copy(
            update={"position": 4}
        ),
    ]

    assert project_task_states(events) == {"task-1": "needs_revision"}


def test_task_projection_latest_candidate_position_tiebreak() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-old", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-later", "attempt_number": 1},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-later"}).model_copy(
            update={"position": 2}
        ),
        _file_state_event("task-1", "cand-later", 3),
        _event("verification_failed", {"candidate_id": "cand-old"}).model_copy(
            update={"position": 4}
        ),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_ignores_mismatched_verdict_candidate() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_passed", {"candidate_id": "other-candidate"}).model_copy(
            update={"position": 1}
        ),
    ]

    assert project_task_states(events) == {"task-1": "pending"}


def test_task_projection_active_appeal_overrides_latest_failure() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "appeal_opened",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
            },
        ).model_copy(update={"position": 2}),
    ]

    assert project_task_states(events) == {"task-1": "pending"}


def test_task_projection_invalid_test_block_exits_after_replacement_pass() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-2", "attempt_number": 2},
        ).model_copy(update={"position": 3}),
        _event("verification_passed", {"candidate_id": "cand-2"}).model_copy(
            update={"position": 4}
        ),
        _file_state_event("task-1", "cand-2", 5),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def _policy_snapshot(**overrides: Any) -> GraphProjectionSnapshot:
    values: dict[str, Any] = {
        "run_state": "active",
        "ready_nodes": [],
        "active_leases": {},
        "schedulable_nodes": [],
        "task_states": {},
    }
    values.update(overrides)
    return GraphProjectionSnapshot(**values)


def test_graph_projection_snapshot_builds_driver_policy_views() -> None:
    events = [
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "ready", "max_attempts": 2},
        ),
        _event(
            "node_created",
            {"node_id": "worker-2", "kind": "worker", "state": "planned", "max_attempts": 4},
        ),
    ]

    snapshot = project_graph_projection_snapshot(events)

    assert snapshot.ready_nodes == ["worker-1"]
    assert snapshot.schedulable_nodes == ["worker-1", "worker-2"]
    assert snapshot.node_max_attempts == {"worker-1": 2, "worker-2": 4}
    assert project_node_max_attempts(events) == snapshot.node_max_attempts


def test_graph_outcome_policy_covers_completed_blocked_and_failed_runs() -> None:
    completed = project_graph_outcome("run-completed", _policy_snapshot(run_state="completed"))
    blocked = project_graph_outcome("run-blocked", _policy_snapshot())
    failed = project_graph_outcome("run-failed", _policy_snapshot(run_state="failed"))

    assert completed == GraphRunOutcome("run-completed", "completed", completed=True)
    assert blocked.blocked_reason == "graph quiescent without completion"
    assert failed.blocked_reason == "graph failed"


def test_graph_blocker_policy_explains_ready_failed_missing_input_and_environment() -> None:
    assert (
        project_graph_blocked_reason(_policy_snapshot(ready_nodes=["planner-gap"]))
        == "graph has ready node(s) not dispatched: planner-gap"
    )
    assert (
        project_graph_blocked_reason(
            _policy_snapshot(
                node_states={"worker-1": "failed"},
                failed_node_reasons={"worker-1": "runner rate limited"},
            )
        )
        == "graph has failed node(s): worker-1: runner rate limited"
    )
    assert project_graph_blocked_reason(
        _policy_snapshot(
            node_states={"check-1": "planned"},
            node_deferral_reasons={"check-1": "missing_required_input:evidence"},
            missing_input_sources={"check-1": ["evidence from verifier-1=failed"]},
        )
    ) == (
        "graph quiescent with non-terminal node(s): check-1=planned: "
        "missing_required_input:evidence (evidence from verifier-1=failed)"
    )
    assert (
        project_graph_blocked_reason(
            _policy_snapshot(
                environment_failures={
                    "step/task": EnvironmentFailureProjection(
                        position=1, classification="tool_unavailable", reason="missing tool"
                    )
                }
            )
        )
        == "graph needs human/operator help for check environment issue(s): step/task: tool_unavailable: missing tool"
    )


def test_graph_completion_policy_requires_active_accepted_tasks() -> None:
    assert (
        project_graph_completion_eligible(_policy_snapshot(task_states={"step/task": "accepted"}))
        is True
    )
    assert project_graph_completion_eligible(_policy_snapshot(task_states={})) is False
    assert (
        project_graph_completion_eligible(
            _policy_snapshot(run_state="paused", task_states={"step/task": "accepted"})
        )
        is False
    )


def test_active_lease_wait_policy_uses_nearest_deadline_and_execution_ids() -> None:
    now = datetime.fromisoformat("2026-06-27T19:30:00+00:00")
    nearest = project_active_lease_wait_plan(
        _policy_snapshot(
            active_leases={
                "expired": {"execution_id": "exec-1", "expires_at": "2026-06-27T19:29:59+00:00"},
                "future": {"execution_id": "exec-2", "expires_at": "2026-06-27T19:30:10+00:00"},
            }
        ),
        now,
    )
    missing_ids = project_active_lease_wait_plan(
        _policy_snapshot(active_leases={"missing": {"expires_at": "2026-06-27T19:30:10+00:00"}}),
        now,
    )
    no_expiry = project_active_lease_wait_plan(
        _policy_snapshot(active_leases={"live": {"execution_id": "exec-live"}}), now
    )

    assert nearest.execution_ids == {"exec-1", "exec-2"}
    assert nearest.timeout_seconds == 0.0
    assert missing_ids.execution_ids == set()
    assert missing_ids.timeout_seconds == 0.0
    assert no_expiry.execution_ids == {"exec-live"}
    assert no_expiry.timeout_seconds is None


def test_fixture_corpus_then_projections_satisfied() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        assert isinstance(raw, list), f"{path.name} must contain a list of scenarios"
        for scenario in raw:
            assert isinstance(scenario, dict), f"{path.name} contains a non-mapping scenario"
            typed_scenario = cast(dict[str, Any], scenario)
            then_projection = typed_scenario.get("then_projection")
            assert isinstance(then_projection, dict)
            assert then_projection, f"{path.name}::{typed_scenario['name']} has empty projection"

            result = run_scenario(
                typed_scenario,
                (
                    PatchCommandContext.model_validate(
                        {
                            "run_id": str(typed_scenario.get("run_id", "run-1")),
                            "current_graph_position": len(typed_scenario.get("given_events", [])),
                            **typed_scenario["command_context"],
                        }
                    )
                    if isinstance(typed_scenario.get("when_command"), dict)
                    and "submit_patch" in typed_scenario["when_command"]
                    else GraphCommandContext(
                        run_id=str(typed_scenario.get("run_id", "run-1")),
                        current_graph_position=(
                            len(typed_scenario.get("given_events", []))
                            if typed_scenario.get("when_command")
                            else -1
                        ),
                    )
                ),
                InMemoryEventStore(),
                FakeClock(),
                SequentialIdGenerator(),
            )

            assert result.passed, f"{typed_scenario['name']}: {result.failures}"
