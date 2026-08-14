"""Round-trip tests for execution graph Pydantic models."""

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from orchestrator.graph import GradeRow, StoredArtifactRef
from orchestrator.graph import (
    Actor,
    ActorKind,
    AnalysisSummaryValue,
    AnalysisSummaryRecord,
    ArtifactReferenceValue,
    ArtifactReferenceRecord,
    Authority,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CallbackEnvelope,
    CandidateProjection,
    CandidateRecord,
    CheckResultRecord,
    CheckResultValue,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    DecisionRecord,
    EdgeModel,
    EventEnvelope,
    FileStateRecord,
    FileEntry,
    FailureRecord,
    FailureRecordValue,
    GapClassificationRecord,
    GapClassificationValue,
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
    PlannerChainRegionPayload,
    PortModel,
    RecordSelector,
    RequirementRecord,
    RequirementRecordValue,
    RecoveryPlanRecord,
    RecoveryPlanValue,
    ResourceClaim,
    RoutineSnapshotRecord,
    RoutineSnapshotValue,
    RunContextRecord,
    RunContextValue,
    RunLifecycleState,
    RunModel,
    VerificationReportRecord,
    VerificationReportValue,
    VerifierVerdictProjection,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def assert_round_trips(model_type: type[ModelT], example: dict[str, Any]) -> None:
    parsed = model_type.model_validate(example)
    dumped = parsed.model_dump(mode="json")
    reparsed = model_type.model_validate(dumped)

    assert reparsed == parsed
    assert dumped == example


def test_stored_artifact_ref_is_strict_and_portable() -> None:
    ref = StoredArtifactRef.model_validate(
        {
            "artifact_id": "check-output-1",
            "content_hash": f"sha256:{'a' * 64}",
            "size_bytes": 1_048_576,
            "media_type": "text/plain",
            "encoding": "utf-8",
            "storage_uri": f"artifact://sha256/{'a' * 64}",
        }
    )
    assert ref.size_bytes == 1_048_576
    assert ref.storage_uri.startswith("artifact://sha256/")


@pytest.mark.parametrize(
    "update",
    [
        {"content_hash": "sha256:../escape"},
        {"content_hash": "md5:" + "a" * 32},
        {"size_bytes": -1},
        {"size_bytes": "12"},
        {"storage_uri": "file:///tmp/output"},
        {"unknown": True},
    ],
)
def test_stored_artifact_ref_rejects_noncanonical_identity(update: dict[str, Any]) -> None:
    payload = {
        "artifact_id": "check-output-1",
        "content_hash": f"sha256:{'a' * 64}",
        "size_bytes": 12,
        "media_type": "text/plain",
        "encoding": "utf-8",
        "storage_uri": f"artifact://sha256/{'a' * 64}",
    }
    payload.update(update)
    with pytest.raises(ValidationError):
        StoredArtifactRef.model_validate(payload)


def test_grade_row_is_strict_and_complete() -> None:
    row = GradeRow.model_validate({"requirement_id": "R1", "grade": "pass", "reason": "covered"})
    assert row.grade == "pass"
    with pytest.raises(ValidationError):
        GradeRow.model_validate({"requirement_id": "R1"})
    with pytest.raises(ValidationError):
        GradeRow.model_validate({"requirement_id": "R1", "grade": "pass", "legacy": True})


def test_grade_row_allows_partial_reason_and_unknown_grade() -> None:
    report = VerificationReportValue.model_validate(
        {
            "outcome": "passed",
            "grades": [
                {"requirement_id": "R1", "grade": "partial"},
                {"requirement_id": "R2", "grade": "future-grade"},
            ],
        }
    )

    assert report.grades[0].reason is None
    assert report.grades[1].grade == "future-grade"


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


@pytest.mark.parametrize(
    ("model_type", "payload"),
    [
        (PortModel, {"port": "input", "required": 1}),
        (
            NodeMembership,
            {
                "task_region_id": "task-1",
                "attempt_number": "2",
                "candidate_id": "candidate-1",
                "execution_id": "exec-1",
            },
        ),
        (
            RunContextValue,
            {
                "routine_id": "routine-1",
                "routine_name": "Routine",
                "planner_generation_budget": "2",
            },
        ),
        (
            RoutineSnapshotValue,
            {
                "routine_id": "routine-1",
                "name": "Routine",
                "content_hash": "hash",
                "step_count": "1",
                "task_count": 1,
            },
        ),
        (
            ArtifactReferenceValue,
            {
                "artifact_id": "artifact-1",
                "artifact_type": "context",
                "uri": "file:///artifact",
                "summarize": "true",
            },
        ),
        (
            ArtifactReferenceValue,
            {
                "artifact_id": "artifact-1",
                "artifact_type": "context",
                "uri": "file:///artifact",
                "max_tokens": "1000",
            },
        ),
        (
            ArtifactReferenceValue,
            {
                "artifact_id": "artifact-1",
                "artifact_type": "context",
                "uri": "file:///artifact",
                "required": 1,
            },
        ),
        (PlannerChainRegionPayload, {"generation_index": "1"}),
        (
            CheckResultValue,
            {
                "status": "passed",
                "classification": "passed",
                "command_id": "check-1",
                "command_text": "true",
                "command": {},
                "worktree_path": "/tmp/worktree",
                "base_snapshot_id": "S0",
                "execution_id": "exec-1",
                "duration_ms": "1",
                "stdout_tail": "",
                "stderr_tail": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "timeout_seconds": 60,
                "environment_policy": {},
            },
        ),
        (
            GapClassificationValue,
            {
                "milestone_kind": "verification",
                "classification": "no_gap",
                "source": "verifier",
                "task_region_id": "task-1",
                "attempt_number": "1",
            },
        ),
        (
            AnalysisSummaryValue,
            {
                "summary": "summary",
                "source_record_ids": [],
                "lossy": 1,
                "omitted_details": [],
            },
        ),
        (RequirementRecordValue, {"id": "R-1", "text": "Requirement", "must": "true"}),
        (
            FailureRecordValue,
            {
                "failed_node_id": "worker-1",
                "phase": "runtime",
                "error_class": "process_exit",
                "retryable": 1,
            },
        ),
        (
            RecoveryPlanValue,
            {
                "action": "retry",
                "responsible_actor": "controller",
                "graph_changes": [],
                "retry_after_seconds": "60",
            },
        ),
        (FileEntry, {"path": "artifact.xml", "needs_gatekeeper": "false"}),
        (FileEntry, {"path": "artifact.xml", "size_bytes": "42"}),
        (FileEntry, {"path": "artifact.xml", "entropy": "4.2"}),
        (FileEntry, {"path": "artifact.xml", "gatekeeper_confidence": "0.9"}),
    ],
)
def test_w5_nested_scalar_models_reject_coercion(
    model_type: type[BaseModel], payload: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model_type.model_validate(payload)


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
                "record_type": "candidate",
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
            "record_type": "fan_out_inputs",
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
            "record_type": "fan_out_inputs",
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
                "record_type": "fan_out_inputs",
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
                "record_type": "file_state",
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
            "record_type": "verification_report",
            "producer_node_id": "verify-A-1",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": "candidate-A-1",
            "outcome": "passed",
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
                "outcome": "passed",
                "grades": [
                    {
                        "requirement_id": "R-1",
                        "grade": "A",
                        "reason": "satisfied",
                    }
                ],
            },
        },
    )


def test_verification_report_record_rejects_legacy_verdict_outcome() -> None:
    with pytest.raises(ValidationError):
        VerificationReportRecord.model_validate(
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verify-A-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-A-1",
                "verdict": "failed",
                "value": {
                    "grades": [
                        {
                            "requirement_id": "R-1",
                            "grade": "C",
                            "reason": "missing coverage",
                        }
                    ]
                },
            }
        )


def test_verification_report_record_rejects_noncanonical_port() -> None:
    with pytest.raises(ValidationError):
        VerificationReportRecord.model_validate(
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verify-A-1",
                "port": "verification_result",
                "schema": "VerificationReport",
                "candidate_id": "candidate-A-1",
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
            }
        )


def test_file_state_record_rejects_nested_membership_without_direct_fields() -> None:
    with pytest.raises(ValidationError):
        FileStateRecord.model_validate(
            {
                "record_id": "file-state-1",
                "membership": {
                    "task_region_id": "task-1",
                    "candidate_id": "candidate-1",
                },
            }
        )


def test_verification_report_record_rejects_top_level_status() -> None:
    with pytest.raises(ValidationError):
        VerificationReportRecord.model_validate(
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verify-A-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-A-1",
                "outcome": "passed",
                "status": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "R-1", "grade": "A"}],
                },
            }
        )


def test_verification_report_record_rejects_value_status() -> None:
    with pytest.raises(ValidationError):
        VerificationReportRecord.model_validate(
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verify-A-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-A-1",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "status": "passed",
                    "grades": [{"requirement_id": "R-1", "grade": "A"}],
                },
            }
        )


def test_verification_report_selector_rejects_status_field() -> None:
    with pytest.raises(ValueError, match="status"):
        RecordSelector.model_validate(
            {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "status": "failed",
            }
        )


@pytest.mark.parametrize(
    "selector",
    [
        {"record_kinds": ["verification_report"]},
        {
            "record_kinds": ["verification_report"],
            "value_matches": {"outcome": "failed"},
        },
        {
            "record_type": "verification_report",
            "schema": "VerificationReport",
            "value_matches": {"outcome": "failed"},
        },
    ],
)
def test_record_selector_rejects_legacy_keys(selector: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RecordSelector.model_validate(selector)


def test_record_selector_round_trips_canonical_verification_selector() -> None:
    selector = RecordSelector.model_validate(
        {
            "record_type": "verification_report",
            "schema": "VerificationReport",
            "outcome": "failed",
        }
    )

    assert selector.model_dump(mode="json") == {
        "record_type": "verification_report",
        "schema": "VerificationReport",
        "outcome": "failed",
    }


@pytest.mark.parametrize(
    ("record_type", "schema"),
    (
        ("decision_request", "DecisionRequest"),
        ("authority_request_record", "AuthorityRequest"),
    ),
)
def test_record_selector_round_trips_request_record_selectors(
    record_type: str, schema: str
) -> None:
    selector = RecordSelector.model_validate({"record_type": record_type, "schema": schema})

    assert selector.model_dump(mode="json") == {"record_type": record_type, "schema": schema}


@pytest.mark.parametrize(
    "selector",
    [
        {"record_kinds": ["verification"]},
        {"record_kinds": ["verification_evidence"]},
        {
            "record_kinds": ["verification_report"],
            "value_matches": {"verdict": "failed"},
        },
        {
            "record_kinds": ["verification_report"],
            "value_matches": {"outcome": "pass"},
        },
    ],
)
def test_verification_selector_rejects_noncanonical_aliases(selector: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RecordSelector.model_validate(selector)


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
        "stdout_tail": "ok",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 300,
        "environment_policy": {"cwd": "/tmp/worktree", "env": "inherited", "shell": False},
    }
    value.update(overrides)
    return value


def test_check_output_artifact_fields_replace_inline_output_atomically() -> None:
    value = _check_result_value(
        stdout_tail="stdout tail",
        stdout_ref=None,
        stderr_tail="stderr tail",
        stderr_ref=None,
    )
    result = CheckResultValue.model_validate(value)

    assert result.stdout_tail == "stdout tail"
    assert result.stdout_ref is None
    assert result.stderr_tail == "stderr tail"
    assert result.stderr_ref is None
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        CheckResultValue.model_validate(_check_result_value(stdout="", stderr=""))


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


def test_candidate_projection_round_trips() -> None:
    assert_round_trips(
        CandidateProjection,
        {
            "candidate_id": "candidate-1",
            "attempt_number": 2,
            "position": 31,
            "file_state_record_ids": ["file-state-1"],
            "supersedes_task_region_ids": ["task-old"],
        },
    )


def test_candidate_projection_rejects_negative_attempt_number() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        CandidateProjection.model_validate(
            {
                "candidate_id": "candidate-1",
                "attempt_number": -1,
                "position": 31,
            }
        )


def test_verifier_verdict_projection_round_trips() -> None:
    assert_round_trips(
        VerifierVerdictProjection,
        {
            "candidate_id": "candidate-1",
            "verdict": "passed",
            "position": 34,
        },
    )


def test_verifier_verdict_projection_rejects_invalid_verdict() -> None:
    with pytest.raises(ValueError, match="Input should be 'passed' or 'failed'"):
        VerifierVerdictProjection.model_validate(
            {
                "candidate_id": "candidate-1",
                "verdict": "unknown",
                "position": 34,
            }
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
    historical = {
        "record_id": "rec-file-S1",
        "record_kind": "file_state",
        "record_type": "file_state",
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
    }
    record = FileStateRecord.model_validate(historical)
    canonical = record.model_dump(mode="json", by_alias=True)

    assert "tracked" not in canonical
    assert "ignored" not in canonical
    assert canonical["paths"] == [
        {"path": "src/foo.py", "source": "tracked", "status": "modified"},
        {
            "path": ".pytest_cache",
            "source": "ignored",
            "classification": "tool_cache",
            "policy": "ephemeral_allowed",
        },
    ]
    assert (
        FileStateRecord.model_validate(canonical).model_dump(mode="json", by_alias=True)
        == canonical
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
    selector = RecordSelector.model_validate(
        {"record_type": "candidate", "schema": "ImplementationCandidate"}
    )
    assert selector.model_dump(mode="json") == {
        "record_type": "candidate",
        "schema": "ImplementationCandidate",
    }


def test_external_resource_claim_requires_key() -> None:
    with pytest.raises(ValueError, match="external_resource_key"):
        ResourceClaim.model_validate({"mode": "external", "scope": "external"})
