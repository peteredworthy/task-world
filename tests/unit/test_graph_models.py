"""Round-trip tests for execution graph Pydantic models."""

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from orchestrator.graph.models import (
    Actor,
    ActorKind,
    AnalysisSummaryRecord,
    ArtifactReferenceRecord,
    Authority,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CallbackEnvelope,
    CandidateRecord,
    CheckResultRecord,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    DecisionRecord,
    EdgeModel,
    EventEnvelope,
    FileStateRecord,
    FailureRecord,
    GapClassificationRecord,
    GraphRecord,
    GraphRecordKind,
    GraphPatchProposalRecord,
    GraphPatchResultRecord,
    InputBinding,
    JoinResultRecord,
    LeaseModel,
    LeaseState,
    NodeKind,
    NodeMembership,
    NodeModel,
    NodeState,
    OutputRecord,
    PatchEnvelope,
    PatchOp,
    PortModel,
    RecordSelector,
    RequirementRecord,
    RecoveryPlanRecord,
    ResourceClaim,
    RoutineSnapshotRecord,
    RunContextRecord,
    RunLifecycleState,
    RunModel,
    VerificationReportRecord,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def assert_round_trips(model_type: type[ModelT], example: dict[str, Any]) -> None:
    parsed = model_type.model_validate(example)
    dumped = parsed.model_dump(mode="json")
    reparsed = model_type.model_validate(dumped)

    assert reparsed == parsed
    assert dumped == example


def test_run_model_round_trips() -> None:
    assert_round_trips(
        RunModel,
        {
            "run_id": "run-123",
            "routine_snapshot_id": "routine-snap-456",
            "repo_id": "repo-abc",
            "worktree_path": "worktrees/run-run-123",
            "run_branch": "orchestrator/run-run-123",
            "lifecycle_state": "active",
            "root_snapshot_id": "S0",
            "event_position": 128,
        },
    )


def test_node_model_round_trips() -> None:
    assert_round_trips(
        NodeModel,
        {
            "node_id": "build-A-1",
            "run_id": "run-123",
            "kind": "worker",
            "role": "builder",
            "state": "ready",
            "created_by_event": "evt-10",
            "authority": {
                "allowed_actions": [
                    "submit_records",
                    "request_clarification",
                    "raise_appeal",
                ],
                "resource_claims": [
                    {"mode": "write", "scope": "repo", "paths": ["src/**", "tests/**"]}
                ],
            },
            "inputs": [{"port": "requirements", "required": True}],
            "outputs": [{"port": "candidate", "schema": "ImplementationCandidate"}],
        },
    )


def test_node_membership_round_trips() -> None:
    assert_round_trips(
        NodeMembership,
        {
            "task_region_id": "task-A",
            "attempt_number": 2,
            "candidate_id": "candidate-A-2",
            "execution_id": "exec-build-A-2-1",
        },
    )


def test_port_model_round_trips() -> None:
    assert_round_trips(
        PortModel,
        {
            "node_id": "verify-A-1",
            "port": "verification_report",
            "direction": "output",
            "schema": "VerificationReport",
            "record_layers": ["output", "graph_record"],
        },
    )


def test_edge_model_round_trips() -> None:
    assert_round_trips(
        EdgeModel,
        {
            "edge_id": "edge-verify-A",
            "from_node_id": "build-A-1",
            "from_port": "candidate",
            "to_node_id": "verify-A-1",
            "to_port": "candidate_under_test",
            "required": True,
            "accepted_record_selector": {
                "record_kinds": ["output", "file_state"],
                "schema": "ImplementationCandidate",
            },
        },
    )


def test_input_binding_round_trips() -> None:
    assert_round_trips(
        InputBinding,
        {
            "edge_id": "edge-verify-A",
            "to_node_id": "verify-A-1",
            "to_port": "candidate_under_test",
            "record_ids": ["rec-output-1", "rec-file-S1"],
            "bound_at_position": 43,
        },
    )


def test_output_record_round_trips() -> None:
    assert_round_trips(
        OutputRecord,
        {
            "record_id": "rec-output-1",
            "record_kind": "output",
            "producer_node_id": "build-A-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "value": {
                "summary": "Implemented validation path",
                "changed_paths": ["src/foo.py", "tests/unit/test_foo.py"],
                "requirements_addressed": ["R1", "R4"],
            },
        },
    )


def test_output_record_optional_base_fields_round_trip() -> None:
    assert_round_trips(
        OutputRecord,
        {
            "record_id": "rec-output-1",
            "record_kind": "output",
            "record_type": "candidate",
            "schema_version": 1,
            "producer_node_id": "build-A-1",
            "producer_port": "candidate",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "run_id": "run-123",
            "graph_position": 42,
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"summary": "Implemented validation path"},
            "file_state_record_id": "file-state-1",
            "file_state_record_ids": ["file-state-1"],
            "provenance": {"source": "callback", "file_state_record_ids": ["file-state-1"]},
            "value": {
                "summary": "Implemented validation path",
                "file_state_record_ids": ["file-state-1"],
            },
        },
    )


def test_output_record_rejects_producer_port_mismatch() -> None:
    with pytest.raises(ValueError, match="producer_port must match port"):
        OutputRecord.model_validate(
            {
                "record_id": "rec-output-1",
                "record_kind": "output",
                "producer_node_id": "build-A-1",
                "producer_port": "check_result",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            }
        )


def test_run_context_record_round_trips() -> None:
    assert_round_trips(
        RunContextRecord,
        {
            "record_id": "run-context-1",
            "record_kind": "graph_record",
            "record_type": "run_context",
            "producer_node_id": "root",
            "port": "run_context",
            "schema": "RunContext",
            "value": {
                "routine_id": "routine-1",
                "routine_name": "Routine",
                "planner_generation_budget": 3,
            },
        },
    )


def test_run_context_record_rejects_wrong_type() -> None:
    with pytest.raises(ValueError, match="record_type must be run_context"):
        RunContextRecord.model_validate(
            {
                "record_id": "run-context-1",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "root",
                "port": "run_context",
                "schema": "RunContext",
                "value": {"routine_id": "routine-1", "routine_name": "Routine"},
            }
        )


def test_routine_snapshot_record_round_trips() -> None:
    assert_round_trips(
        RoutineSnapshotRecord,
        {
            "record_id": "routine-snapshot-record",
            "record_kind": "graph_record",
            "record_type": "routine_snapshot",
            "producer_node_id": "routine-snapshot",
            "port": "snapshot",
            "schema": "RoutineSnapshot",
            "value": {
                "routine_id": "routine-1",
                "name": "Routine",
                "description": "Example routine",
                "content_hash": "abc123",
                "source_path": "routines/routine.yaml",
                "source_ref": "main",
                "step_count": 1,
                "task_count": 2,
                "builder_agent": "Builder",
                "verifier_agent": "Verifier",
                "dynamic_feature": {"patch_budget": 2},
            },
        },
    )


def test_routine_snapshot_record_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        RoutineSnapshotRecord.model_validate(
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine",
                    "content_hash": "abc123",
                    "step_count": -1,
                    "task_count": 2,
                },
            }
        )


def test_artifact_reference_record_round_trips() -> None:
    assert_round_trips(
        ArtifactReferenceRecord,
        {
            "record_id": "artifact-reference-1",
            "record_kind": "graph_record",
            "record_type": "artifact_reference",
            "producer_node_id": "context-1",
            "port": "artifact",
            "schema": "ContextArtifact",
            "value": {
                "artifact_id": "spec",
                "artifact_type": "context_source",
                "uri": "docs/spec.md",
                "summary": "Feature spec",
                "source_record_ids": ["routine-snapshot-record"],
            },
        },
    )


def test_artifact_reference_record_rejects_wrong_port() -> None:
    with pytest.raises(ValueError):
        ArtifactReferenceRecord.model_validate(
            {
                "record_id": "artifact-reference-1",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": "context-1",
                "port": "candidate",
                "schema": "ContextArtifact",
                "value": {
                    "artifact_id": "spec",
                    "artifact_type": "context_source",
                    "uri": "docs/spec.md",
                },
            }
        )


def test_file_state_record_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be positive"):
        FileStateRecord.model_validate(
            {
                "record_id": "rec-file-S1",
                "record_kind": "file_state",
                "schema_version": 0,
                "snapshot_id": "S1",
            }
        )


def test_verification_report_record_round_trips() -> None:
    assert_round_trips(
        VerificationReportRecord,
        {
            "record_id": "verification-1",
            "record_kind": "verification",
            "producer_node_id": "verify-A-1",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": "candidate-A-1",
            "verdict": "passed",
            "candidate_record_ids": ["candidate-A-1"],
            "file_state_record_ids": ["file-state-A-1"],
            "evaluated_record_ids": ["candidate-A-1", "file-state-A-1"],
            "evidence": {
                "candidate_record_ids": ["candidate-A-1"],
                "file_state_record_ids": ["file-state-A-1"],
                "evaluated_record_ids": ["candidate-A-1", "file-state-A-1"],
            },
            "provenance": {
                "candidate_record_ids": ["candidate-A-1"],
                "file_state_record_ids": ["file-state-A-1"],
                "evaluated_record_ids": ["candidate-A-1", "file-state-A-1"],
            },
            "value": {
                "grades": [
                    {
                        "requirement_id": "R-1",
                        "grade": "A",
                        "reason": "satisfied",
                    }
                ]
            },
        },
    )


def test_completion_decision_record_round_trips() -> None:
    assert_round_trips(
        CompletionDecisionRecord,
        {
            "record_id": "completion-1",
            "record_kind": "output",
            "record_type": "completion_decision",
            "producer_node_id": "gate-final",
            "port": "completion_decision",
            "schema": "CompletionDecision",
            "value": {
                "status": "blocked",
                "blockers": [
                    {
                        "kind": "task_not_accepted",
                        "reason": "task region has not reached accepted",
                    }
                ],
            },
        },
    )


def test_completion_decision_record_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="Input should be 'passed' or 'blocked'"):
        CompletionDecisionRecord.model_validate(
            {
                "record_id": "completion-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {"status": "unknown", "blockers": []},
            }
        )


def test_completion_decision_record_rejects_non_list_blockers() -> None:
    with pytest.raises(ValueError, match="Input should be a valid list"):
        CompletionDecisionRecord.model_validate(
            {
                "record_id": "completion-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {"status": "blocked", "blockers": {"kind": "missing"}},
            }
        )


def test_join_result_record_round_trips() -> None:
    assert_round_trips(
        JoinResultRecord,
        {
            "record_id": "join-result-1",
            "record_kind": "output",
            "record_type": "join_result",
            "producer_node_id": "join-1",
            "port": "join_result",
            "schema": "JoinResult",
            "value": {
                "status": "ready",
                "source_record_ids": ["candidate-1", "check-result-1"],
                "missing_optional_inputs": [],
            },
        },
    )


def test_join_result_record_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="Input should be 'ready' or 'blocked'"):
        JoinResultRecord.model_validate(
            {
                "record_id": "join-result-1",
                "record_kind": "output",
                "record_type": "join_result",
                "producer_node_id": "join-1",
                "port": "join_result",
                "schema": "JoinResult",
                "value": {"status": "complete", "source_record_ids": ["candidate-1"]},
            }
        )


def test_join_result_record_rejects_non_string_source_record_ids() -> None:
    with pytest.raises(ValueError, match="Input should be a valid string"):
        JoinResultRecord.model_validate(
            {
                "record_id": "join-result-1",
                "record_kind": "output",
                "record_type": "join_result",
                "producer_node_id": "join-1",
                "port": "join_result",
                "schema": "JoinResult",
                "value": {"status": "ready", "source_record_ids": ["candidate-1", 7]},
            }
        )


def _check_result_value(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": "passed",
        "classification": "passed",
        "command_id": "pytest-graph",
        "command_binding": {"kind": "known", "id": "unit"},
        "command_text": "uv run pytest tests/unit/test_graph_models.py",
        "command": {
            "id": "pytest-graph",
            "argv": ["uv", "run", "pytest", "tests/unit/test_graph_models.py"],
        },
        "worktree_path": "/tmp/worktree",
        "base_snapshot_id": "S0",
        "execution_id": "exec-check",
        "exit_code": 0,
        "duration_ms": 12,
        "stdout": "ok",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 300,
        "environment_policy": {"cwd": "/tmp/worktree", "env": "inherited", "shell": False},
    }
    value.update(overrides)
    return value


def test_check_result_record_round_trips() -> None:
    assert_round_trips(
        CheckResultRecord,
        {
            "record_id": "check-exec",
            "record_kind": "output",
            "record_type": "check_result",
            "producer_node_id": "check-1",
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": "candidate-1",
            "task_region_id": "task-1",
            "attempt_number": 1,
            "value": _check_result_value(),
        },
    )


def test_check_result_record_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="Input should be 'passed', 'failed' or 'timeout'"):
        CheckResultRecord.model_validate(
            {
                "record_id": "check-exec",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "attempt_number": 1,
                "value": _check_result_value(status="unknown"),
            }
        )


def test_check_result_record_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        CheckResultRecord.model_validate(
            {
                "record_id": "check-exec",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "attempt_number": 1,
                "value": _check_result_value(duration_ms=-1),
            }
        )


def test_candidate_record_round_trips() -> None:
    assert_round_trips(
        CandidateRecord,
        {
            "record_id": "candidate-1",
            "record_kind": "output",
            "record_type": "candidate",
            "producer_node_id": "worker-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": "candidate-1",
            "task_region_id": "task-1",
            "attempt_number": 1,
            "value": {
                "summary": "implemented the feature",
                "changed_paths": ["src/example.py"],
                "requirements_addressed": ["R-1"],
                "file_state_record_id": "file-state-1",
                "file_state_record_ids": ["file-state-1"],
            },
        },
    )


def test_candidate_record_rejects_missing_summary() -> None:
    with pytest.raises(ValueError, match="Field required"):
        CandidateRecord.model_validate(
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "value": {},
            }
        )


def test_candidate_record_rejects_non_string_changed_paths() -> None:
    with pytest.raises(ValueError, match="Input should be a valid string"):
        CandidateRecord.model_validate(
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "value": {"summary": "done", "changed_paths": ["src/example.py", 3]},
            }
        )


def test_gap_classification_record_round_trips() -> None:
    assert_round_trips(
        GapClassificationRecord,
        {
            "record_id": "classified-gap-1",
            "record_kind": "output",
            "record_type": "classified_gap",
            "producer_node_id": "gap-planner-1",
            "port": "classified_gap",
            "schema": "GapClassification",
            "value": {
                "milestone_kind": "gap_analysis",
                "classification": "corrective_work_required",
                "source": "accepted_gap_planner_patch",
                "task_region_id": "task-1",
                "attempt_number": 2,
            },
        },
    )


def test_gap_classification_record_rejects_record_type_port_mismatch() -> None:
    with pytest.raises(ValueError, match="record_type must match port"):
        GapClassificationRecord.model_validate(
            {
                "record_id": "classified-gap-1",
                "record_kind": "output",
                "record_type": "gap_plan",
                "producer_node_id": "gap-planner-1",
                "port": "classified_gap",
                "schema": "GapClassification",
                "value": {
                    "milestone_kind": "gap_analysis",
                    "classification": "corrective_work_required",
                    "source": "accepted_gap_planner_patch",
                    "task_region_id": "task-1",
                    "attempt_number": 2,
                },
            }
        )


def test_gap_classification_record_rejects_invalid_classification() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        GapClassificationRecord.model_validate(
            {
                "record_id": "classified-gap-1",
                "record_kind": "output",
                "record_type": "classified_gap",
                "producer_node_id": "gap-planner-1",
                "port": "classified_gap",
                "schema": "GapClassification",
                "value": {
                    "milestone_kind": "gap_analysis",
                    "classification": "unknown",
                    "source": "accepted_gap_planner_patch",
                    "task_region_id": "task-1",
                    "attempt_number": 2,
                },
            }
        )


def test_decision_record_round_trips() -> None:
    assert_round_trips(
        DecisionRecord,
        {
            "record_id": "decision_record-gate-1",
            "record_kind": "output",
            "record_type": "decision_record",
            "producer_node_id": "gate-1",
            "port": "decision_record",
            "schema": "DecisionRecord",
            "value": {
                "decision": "approved",
                "decision_type": "approval",
                "decider": {"kind": "human", "id": "alice"},
                "reason": "looks safe",
            },
        },
    )


def test_decision_record_rejects_invalid_decision() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        DecisionRecord.model_validate(
            {
                "record_id": "decision_record-gate-1",
                "record_kind": "output",
                "record_type": "decision_record",
                "producer_node_id": "gate-1",
                "port": "decision_record",
                "schema": "DecisionRecord",
                "value": {
                    "decision": "granted",
                    "decision_type": "approval",
                    "decider": {"kind": "human", "id": "alice"},
                },
            }
        )


def test_decision_record_rejects_non_object_scope() -> None:
    with pytest.raises(ValueError, match="Input should be a valid dictionary"):
        DecisionRecord.model_validate(
            {
                "record_id": "decision_record-gate-1",
                "record_kind": "output",
                "record_type": "decision_record",
                "producer_node_id": "gate-1",
                "port": "decision_record",
                "schema": "DecisionRecord",
                "value": {
                    "decision": "approved",
                    "decision_type": "approval",
                    "decider": {"kind": "human", "id": "alice"},
                    "scope": "repo",
                },
            }
        )


def test_authority_decision_record_round_trips() -> None:
    assert_round_trips(
        AuthorityDecisionRecord,
        {
            "record_id": "authority_decision-authority-1",
            "record_kind": "output",
            "record_type": "authority_decision",
            "producer_node_id": "authority-1",
            "port": "authority_decision",
            "schema": "AuthorityDecision",
            "value": {
                "decision": "granted",
                "decision_type": "authority",
                "decider": {"kind": "human", "id": "alice"},
                "scope": {"tools": ["graph_write"]},
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
        },
    )


def test_authority_decision_record_rejects_approval_value() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        AuthorityDecisionRecord.model_validate(
            {
                "record_id": "authority_decision-authority-1",
                "record_kind": "output",
                "record_type": "authority_decision",
                "producer_node_id": "authority-1",
                "port": "authority_decision",
                "schema": "AuthorityDecision",
                "value": {
                    "decision": "approved",
                    "decision_type": "authority",
                    "decider": {"kind": "human", "id": "alice"},
                },
            }
        )


def test_analysis_summary_record_round_trips() -> None:
    assert_round_trips(
        AnalysisSummaryRecord,
        {
            "record_id": "summary-1",
            "record_kind": "output",
            "record_type": "analysis_summary",
            "producer_node_id": "summarizer-1",
            "port": "analysis_summary",
            "schema": "AnalysisSummary",
            "value": {
                "summary": "Requirement evidence has been condensed.",
                "source_record_ids": ["candidate-1", "verification-1"],
                "lossy": True,
                "omitted_details": ["full stdout omitted"],
            },
        },
    )


def test_analysis_summary_record_rejects_missing_summary() -> None:
    with pytest.raises(ValueError, match="Field required"):
        AnalysisSummaryRecord.model_validate(
            {
                "record_id": "summary-1",
                "record_kind": "output",
                "record_type": "analysis_summary",
                "producer_node_id": "summarizer-1",
                "port": "analysis_summary",
                "schema": "AnalysisSummary",
                "value": {
                    "source_record_ids": ["candidate-1"],
                    "lossy": False,
                    "omitted_details": [],
                },
            }
        )


def test_analysis_summary_record_rejects_non_string_source_record_id() -> None:
    with pytest.raises(ValueError, match="Input should be a valid string"):
        AnalysisSummaryRecord.model_validate(
            {
                "record_id": "summary-1",
                "record_kind": "output",
                "record_type": "analysis_summary",
                "producer_node_id": "summarizer-1",
                "port": "region_summary",
                "schema": "RegionSummary",
                "value": {
                    "summary": "Region evidence was condensed.",
                    "source_record_ids": ["candidate-1", 7],
                    "lossy": True,
                    "omitted_details": [],
                },
            }
        )


def test_graph_patch_proposal_record_round_trips() -> None:
    assert_round_trips(
        GraphPatchProposalRecord,
        {
            "record_id": "proposal-1",
            "record_kind": "output",
            "record_type": "graph_patch_proposal",
            "producer_node_id": "planner-1",
            "port": "graph_patch_proposal",
            "schema": "GraphPatch",
            "value": {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 3,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {"node_id": "worker-1", "kind": "worker", "role": "builder"},
                    }
                ],
                "expected_downstream_effects": ["creates worker-1"],
            },
        },
    )


def test_graph_patch_proposal_record_accepts_macro_invocation_plan() -> None:
    assert_round_trips(
        GraphPatchProposalRecord,
        {
            "record_id": "proposal-1",
            "record_kind": "output",
            "record_type": "graph_patch_proposal",
            "producer_node_id": "planner-1",
            "port": "graph_patch",
            "schema": "GraphPatch",
            "value": {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 3,
                "macro_invocations": [
                    {
                        "macro": "create_work_region",
                        "args": {"region_id": "feature-region"},
                    }
                ],
                "expected_downstream_effects": [],
            },
        },
    )


def test_graph_patch_proposal_record_rejects_empty_plan() -> None:
    with pytest.raises(ValueError, match="must include ops or macro_invocations"):
        GraphPatchProposalRecord.model_validate(
            {
                "record_id": "proposal-1",
                "record_kind": "output",
                "record_type": "graph_patch_proposal",
                "producer_node_id": "planner-1",
                "port": "graph_patch_proposal",
                "schema": "GraphPatch",
                "value": {
                    "patch_id": "patch-1",
                    "proposed_by_node_id": "planner-1",
                    "base_graph_position": 3,
                    "ops": [],
                    "macro_invocations": [],
                },
            }
        )


def test_graph_patch_result_record_round_trips_accepted() -> None:
    assert_round_trips(
        GraphPatchResultRecord,
        {
            "patch_id": "patch-1",
            "proposed_by_node_id": "planner-1",
            "base_graph_position": 2,
            "current_graph_position": 5,
            "status": "accepted",
            "accepted_event_id": "event-accepted",
            "accepted_position": 3,
            "created_node_ids": ["worker-1"],
            "created_edge_ids": ["edge-1"],
            "diagnostics": {"actor_role": "planner"},
        },
    )


def test_graph_patch_result_record_rejects_rejected_without_reason() -> None:
    with pytest.raises(ValueError, match="requires rejection_reason"):
        GraphPatchResultRecord.model_validate(
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
                "current_graph_position": 5,
                "status": "rejected",
                "rejected_event_id": "event-rejected",
                "rejected_position": 3,
            }
        )


def test_requirement_record_round_trips() -> None:
    assert_round_trips(
        RequirementRecord,
        {
            "record_id": "requirement-s-01-t-01-r-01",
            "record_kind": "graph_record",
            "record_type": "requirement_record",
            "producer_node_id": "requirement-s-01-t-01-r-01",
            "port": "requirement",
            "schema": "RequirementRecord",
            "value": {
                "id": "R-01",
                "text": "Must be done",
                "desc": "Must be done",
                "priority": "critical",
                "acceptance_criteria": [],
                "source": "routine",
                "version": "initial",
                "must": True,
            },
        },
    )


def test_requirement_record_rejects_missing_text() -> None:
    with pytest.raises(ValueError, match="Field required"):
        RequirementRecord.model_validate(
            {
                "record_id": "requirement-s-01-t-01-r-01",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-s-01-t-01-r-01",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "R-01",
                    "priority": "critical",
                },
            }
        )


def test_requirement_record_rejects_universal_field_mismatch() -> None:
    with pytest.raises(ValueError, match="producer_port must match port"):
        RequirementRecord.model_validate(
            {
                "record_id": "requirement-s-01-t-01-r-01",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-s-01-t-01-r-01",
                "producer_port": "candidate",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "R-01",
                    "text": "Must be done",
                },
            }
        )


def test_decision_request_record_round_trips() -> None:
    assert_round_trips(
        DecisionRequestRecord,
        {
            "record_id": "decision-request-1",
            "record_kind": "graph_record",
            "record_type": "decision_request",
            "producer_node_id": "gate-1",
            "port": "decision_request",
            "schema": "DecisionRequest",
            "value": {
                "decision_type": "approval",
                "options": ["approved", "rejected", "deferred"],
                "default_option": "deferred",
                "consequence_summary": "Approval releases the gated worker.",
            },
        },
    )


def test_decision_request_record_rejects_universal_field_mismatch() -> None:
    with pytest.raises(ValueError, match="producer_port must match port"):
        DecisionRequestRecord.model_validate(
            {
                "record_id": "decision-request-1",
                "record_kind": "graph_record",
                "record_type": "decision_request",
                "producer_node_id": "gate-1",
                "producer_port": "authority_request_record",
                "port": "decision_request",
                "schema": "DecisionRequest",
                "value": {
                    "decision_type": "approval",
                    "options": ["approved", "rejected"],
                    "consequence_summary": "Approval releases the gated worker.",
                },
            }
        )


def test_authority_request_record_rejects_missing_target() -> None:
    with pytest.raises(ValueError, match="requires target_node_id or target_region_id"):
        AuthorityRequestRecord.model_validate(
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "planner-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["graph_write"],
                    "reason": "Need to add corrective work.",
                },
            }
        )


def test_authority_request_record_round_trips() -> None:
    assert_round_trips(
        AuthorityRequestRecord,
        {
            "record_id": "authority-request-1",
            "record_kind": "graph_record",
            "record_type": "authority_request_record",
            "producer_node_id": "planner-1",
            "port": "authority_request_record",
            "schema": "AuthorityRequest",
            "value": {
                "requested_authority": ["graph_write"],
                "target_region_id": "feature-region",
                "reason": "Need to add corrective work.",
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
        },
    )


def test_authority_request_record_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be positive"):
        AuthorityRequestRecord.model_validate(
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "schema_version": 0,
                "producer_node_id": "planner-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["graph_write"],
                    "target_region_id": "feature-region",
                    "reason": "Need to add corrective work.",
                },
            }
        )


def test_failure_record_round_trips() -> None:
    assert_round_trips(
        FailureRecord,
        {
            "record_id": "failure-1",
            "record_kind": "graph_record",
            "record_type": "failure_record",
            "producer_node_id": "runtime",
            "port": "failure_record",
            "schema": "FailureRecord",
            "value": {
                "failed_node_id": "worker-1",
                "phase": "agent_execution",
                "error_class": "lease_expired",
                "retryable": True,
                "lease_id": "lease-1",
                "execution_id": "exec-1",
                "reason": "lease expired without callback",
            },
        },
    )


def test_failure_record_rejects_universal_field_mismatch() -> None:
    with pytest.raises(ValueError, match="producer_port must match port"):
        FailureRecord.model_validate(
            {
                "record_id": "failure-1",
                "record_kind": "graph_record",
                "record_type": "failure_record",
                "producer_node_id": "runtime",
                "producer_port": "candidate",
                "port": "failure_record",
                "schema": "FailureRecord",
                "value": {
                    "failed_node_id": "worker-1",
                    "phase": "agent_execution",
                    "error_class": "lease_expired",
                    "retryable": True,
                },
            }
        )


def test_recovery_plan_record_round_trips() -> None:
    assert_round_trips(
        RecoveryPlanRecord,
        {
            "record_id": "recovery-1",
            "record_kind": "output",
            "record_type": "recovery_plan",
            "producer_node_id": "recovery-1",
            "port": "recovery_plan",
            "schema": "RecoveryPlan",
            "value": {
                "action": "retry",
                "responsible_actor": "controller",
                "graph_changes": [{"op": "set_node_state", "node_id": "worker-1"}],
                "reason": "retryable lease expiry",
            },
        },
    )


def test_recovery_plan_record_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be positive"):
        RecoveryPlanRecord.model_validate(
            {
                "record_id": "recovery-1",
                "record_kind": "output",
                "record_type": "recovery_plan",
                "schema_version": 0,
                "producer_node_id": "recovery-1",
                "port": "recovery_plan",
                "schema": "RecoveryPlan",
                "value": {
                    "action": "retry",
                    "responsible_actor": "controller",
                    "graph_changes": [],
                },
            }
        )


def test_recovery_plan_record_rejects_invalid_action() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        RecoveryPlanRecord.model_validate(
            {
                "record_id": "recovery-1",
                "record_kind": "output",
                "record_type": "recovery_plan",
                "producer_node_id": "recovery-1",
                "port": "recovery_plan",
                "schema": "RecoveryPlan",
                "value": {
                    "action": "ignore",
                    "responsible_actor": "controller",
                    "graph_changes": [],
                },
            }
        )


def test_file_state_record_round_trips() -> None:
    assert_round_trips(
        FileStateRecord,
        {
            "record_id": "rec-file-S1",
            "record_kind": "file_state",
            "snapshot_id": "S1",
            "base_snapshot_id": "S0",
            "producer_node_id": "build-A-1",
            "git": {
                "commit_sha": "abc123",
                "tree_sha": "def456",
                "no_commit_reason": None,
            },
            "tracked": [{"path": "src/foo.py", "status": "modified"}],
            "untracked": [],
            "ignored": [
                {
                    "path": ".pytest_cache",
                    "classification": "tool_cache",
                    "policy": "ephemeral_allowed",
                }
            ],
            "external": [],
        },
    )


def test_graph_record_round_trips() -> None:
    assert_round_trips(
        GraphRecord,
        {
            "record_id": "rec-graph-1",
            "record_kind": "node_state_changed",
            "run_id": "run-123",
            "producer_node_id": "controller",
            "payload": {"node_id": "build-A-1", "new_state": "completed"},
        },
    )


def test_actor_round_trips() -> None:
    assert_round_trips(Actor, {"kind": "controller"})


def test_event_envelope_round_trips_and_accepts_iso_timestamp() -> None:
    assert_round_trips(
        EventEnvelope,
        {
            "event_id": "evt-123",
            "run_id": "run-123",
            "position": 42,
            "event_type": "node_state_changed",
            "schema_version": 1,
            "actor": {"kind": "controller"},
            "causation_id": "callback-789",
            "correlation_id": "build-A-1",
            "timestamp": "2026-06-10T10:00:00Z",
            "payload": {},
        },
    )


def test_patch_envelope_round_trips() -> None:
    assert_round_trips(
        PatchEnvelope,
        {
            "patch_id": "patch-123",
            "proposed_by_node_id": "planner-1",
            "base_graph_position": 42,
            "ops": [
                {
                    "op": "create_node",
                    "node": {"node_id": "build-A2-1", "kind": "worker", "role": "builder"},
                },
                {
                    "op": "create_edge",
                    "from_node_id": "read-tests",
                    "from_port": "findings",
                    "to_node_id": "synthesis",
                    "to_port": "context",
                },
            ],
            "rationale_record_id": "rec-plan-rationale-1",
        },
    )


def test_lease_model_round_trips() -> None:
    assert_round_trips(
        LeaseModel,
        {
            "lease_id": "lease-1",
            "generation": 3,
            "run_id": "run-123",
            "node_id": "build-A-1",
            "session_id": "session-W7",
            "base_snapshot_id": "S0",
            "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["**"]}],
            "expires_at": "2026-06-10T10:20:00Z",
            "state": "active",
        },
    )


def test_callback_envelope_round_trips() -> None:
    assert_round_trips(
        CallbackEnvelope,
        {
            "run_id": "run-123",
            "node_id": "build-A-1",
            "execution_id": "exec-1",
            "lease_id": "lease-1",
            "lease_generation": 3,
            "base_snapshot_id": "S0",
            "observed_graph_position": 42,
            "idempotency_key": "callback-uuid",
            "records": [
                {"record_kind": "output", "port": "candidate", "value": {}},
                {"record_kind": "file_state", "port": "file_state", "value": {}},
            ],
            "proposed_graph_patches": [],
        },
    )


def test_all_models_import_and_enums_cover_prd_values() -> None:
    assert RunModel.__name__ == "RunModel"
    assert set(RunLifecycleState) == {
        RunLifecycleState.DRAFT,
        RunLifecycleState.QUEUED,
        RunLifecycleState.ACTIVE,
        RunLifecycleState.PAUSING,
        RunLifecycleState.PAUSED,
        RunLifecycleState.RESUMING,
        RunLifecycleState.CANCELLING,
        RunLifecycleState.CANCELLED,
        RunLifecycleState.COMPLETED,
        RunLifecycleState.FAILED,
    }
    assert {kind.value for kind in NodeKind} == {
        "root",
        "run_root",
        "routine_snapshot",
        "task_projection",
        "worker",
        "verifier",
        "check",
        "planner",
        "gap_planner",
        "summarizer",
        "join",
        "final_gate",
        "human_gate",
        "authority_request",
        "oversight",
        "appeal",
        "gate",
        "recovery",
        "review",
        "artifact",
        "artifact_index",
        "requirement",
        "file_state",
        "session",
    }
    assert {state.value for state in NodeState} == {
        "planned",
        "blocked",
        "ready",
        "leased",
        "running",
        "suspended",
        "completed",
        "failed",
        "retired",
        "cancelled",
    }
    assert {kind.value for kind in GraphRecordKind} == {
        "node_created",
        "edge_created",
        "node_retired",
        "node_state_changed",
        "lease_granted",
        "lease_suspended",
        "lease_revoked",
        "callback_received",
        "callback_accepted",
        "callback_rejected_stale",
        "verification_passed",
        "verification_failed",
        "revision_created",
        "appeal_opened",
        "oversight_decision_recorded",
        "approval_decision_recorded",
        "graph_patch_accepted",
        "file_state_accepted",
    }
    assert {state.value for state in LeaseState} == {
        "active",
        "suspended",
        "revoked",
        "expired",
        "released",
    }
    assert Actor.model_validate({"kind": ActorKind.CONTROLLER}) == Actor(kind="controller")
    assert PatchOp.model_validate({"op": "retire_node", "node_id": "build-A-1"}).op
    assert ResourceClaim.model_validate({"mode": "read", "scope": "repo"}).mode == "read"
    assert Authority.model_validate({"allowed_actions": []}).allowed_actions == []
    assert RecordSelector.model_validate({"record_kinds": ["output"]}).record_kinds == ["output"]


def test_external_resource_claim_requires_key() -> None:
    with pytest.raises(ValueError, match="external_resource_key"):
        ResourceClaim.model_validate({"mode": "external", "scope": "external"})
