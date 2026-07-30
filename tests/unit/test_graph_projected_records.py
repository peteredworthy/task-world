"""Boundary conversion contracts for immutable projected records."""

from typing import Any, cast, get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from orchestrator.graph import (
    OUTPUT_RECORD_MODELS_BY_TYPE,
    ProjectedAnalysisSummaryRecord,
    ProjectedArtifactReferenceRecord,
    ProjectedAuthorityDecisionRecord,
    ProjectedAuthorityRequestRecord,
    ProjectedCandidateRecord,
    ProjectedCandidateRecordValue,
    ProjectedCheckResultRecord,
    ProjectedCompletionDecisionRecord,
    ProjectedDecisionRecord,
    ProjectedDecisionRequestRecord,
    ProjectedFailureRecord,
    ProjectedFanOutInputsRecord,
    ProjectedFileStateRecord,
    ProjectedGapClassificationRecord,
    ProjectedGraphPatchProposalRecord,
    ProjectedJoinResultRecord,
    ProjectedRecoveryPlanRecord,
    ProjectedRequirementRecord,
    ProjectedRoutineSnapshotRecord,
    ProjectedRunContextRecord,
    ProjectedRecord,
    ProjectedRecordBase,
    ProjectedVerificationReportRecord,
    ProjectedAnalysisSummaryValue,
    ProjectedArtifactReferenceValue,
    ProjectedAuthorityDecisionRecordValue,
    ProjectedAuthorityRequestRecordValue,
    ProjectedCheckResultRecordValue,
    ProjectedCompletionDecisionValue,
    ProjectedDecisionRecordValue,
    ProjectedDecisionRequestRecordValue,
    ProjectedFailureRecordValue,
    ProjectedFileEntry,
    ProjectedExternalArtifactManifest,
    ProjectedExternalFileEntry,
    ProjectedFanOutInputsValue,
    ProjectedGapClassificationValue,
    ProjectedGraphPatchProposalValue,
    ProjectedGitRef,
    ProjectedGradeRow,
    ProjectedJoinResultValue,
    ProjectedRecoveryPlanValue,
    ProjectedRequirementRecordValue,
    ProjectedRoutineSnapshotValue,
    ProjectedRunContextValue,
    ProjectedStoredArtifactRef,
    ProjectedDecisionActor,
    ProjectedVerificationReportValue,
    FrozenJsonValue,
    FrozenMap,
    project_record,
)
from tests.unit.test_output_record_event_payloads import OUTPUT_RECORD_CASES


def test_projected_record_contracts_are_public_graph_interfaces() -> None:
    assert all(
        isinstance(contract, type)
        for contract in (
            ProjectedRecordBase,
            ProjectedCandidateRecordValue,
            ProjectedAnalysisSummaryValue,
            ProjectedArtifactReferenceValue,
            ProjectedAuthorityDecisionRecordValue,
            ProjectedAuthorityRequestRecordValue,
            ProjectedCheckResultRecordValue,
            ProjectedCompletionDecisionValue,
            ProjectedDecisionRecordValue,
            ProjectedDecisionRequestRecordValue,
            ProjectedFailureRecordValue,
            ProjectedFileEntry,
            ProjectedExternalArtifactManifest,
            ProjectedExternalFileEntry,
            ProjectedGapClassificationValue,
            ProjectedGraphPatchProposalValue,
            ProjectedGitRef,
            ProjectedGradeRow,
            ProjectedJoinResultValue,
            ProjectedRecoveryPlanValue,
            ProjectedRequirementRecordValue,
            ProjectedRoutineSnapshotValue,
            ProjectedRunContextValue,
            ProjectedStoredArtifactRef,
            ProjectedDecisionActor,
            ProjectedVerificationReportValue,
            ProjectedAnalysisSummaryRecord,
            ProjectedArtifactReferenceRecord,
            ProjectedAuthorityDecisionRecord,
            ProjectedAuthorityRequestRecord,
            ProjectedCandidateRecord,
            ProjectedCheckResultRecord,
            ProjectedCompletionDecisionRecord,
            ProjectedDecisionRecord,
            ProjectedDecisionRequestRecord,
            ProjectedFailureRecord,
            ProjectedFanOutInputsRecord,
            ProjectedFileStateRecord,
            ProjectedGapClassificationRecord,
            ProjectedGraphPatchProposalRecord,
            ProjectedJoinResultRecord,
            ProjectedRecoveryPlanRecord,
            ProjectedRequirementRecord,
            ProjectedRoutineSnapshotRecord,
            ProjectedRunContextRecord,
            ProjectedVerificationReportRecord,
        )
    )
    assert ProjectedFanOutInputsValue is not None


PROJECTED_RECORD_SEMANTICS = (
    (
        "analysis_summary",
        OUTPUT_RECORD_MODELS_BY_TYPE["analysis_summary"],
        ProjectedAnalysisSummaryRecord,
        ProjectedAnalysisSummaryValue,
        "output",
        "analysis_summary",
        "AnalysisSummary",
    ),
    (
        "artifact_reference",
        OUTPUT_RECORD_MODELS_BY_TYPE["artifact_reference"],
        ProjectedArtifactReferenceRecord,
        ProjectedArtifactReferenceValue,
        "graph_record",
        "artifact",
        "ContextArtifact",
    ),
    (
        "authority_decision",
        OUTPUT_RECORD_MODELS_BY_TYPE["authority_decision"],
        ProjectedAuthorityDecisionRecord,
        ProjectedAuthorityDecisionRecordValue,
        "output",
        "authority_decision",
        "AuthorityDecision",
    ),
    (
        "authority_request_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["authority_request_record"],
        ProjectedAuthorityRequestRecord,
        ProjectedAuthorityRequestRecordValue,
        "graph_record",
        "authority_request_record",
        "AuthorityRequest",
    ),
    (
        "candidate",
        OUTPUT_RECORD_MODELS_BY_TYPE["candidate"],
        ProjectedCandidateRecord,
        ProjectedCandidateRecordValue,
        "output",
        "candidate",
        "ImplementationCandidate",
    ),
    (
        "check_result",
        OUTPUT_RECORD_MODELS_BY_TYPE["check_result"],
        ProjectedCheckResultRecord,
        ProjectedCheckResultRecordValue,
        "output",
        "check_result",
        "CheckResult",
    ),
    (
        "classified_gap",
        OUTPUT_RECORD_MODELS_BY_TYPE["classified_gap"],
        ProjectedGapClassificationRecord,
        ProjectedGapClassificationValue,
        "output",
        "classified_gap",
        "GapClassification",
    ),
    (
        "completion_decision",
        OUTPUT_RECORD_MODELS_BY_TYPE["completion_decision"],
        ProjectedCompletionDecisionRecord,
        ProjectedCompletionDecisionValue,
        "output",
        "completion_decision",
        "CompletionDecision",
    ),
    (
        "decision_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["decision_record"],
        ProjectedDecisionRecord,
        ProjectedDecisionRecordValue,
        "output",
        "decision_record",
        "DecisionRecord",
    ),
    (
        "decision_request",
        OUTPUT_RECORD_MODELS_BY_TYPE["decision_request"],
        ProjectedDecisionRequestRecord,
        ProjectedDecisionRequestRecordValue,
        "graph_record",
        "decision_request",
        "DecisionRequest",
    ),
    (
        "failure_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["failure_record"],
        ProjectedFailureRecord,
        ProjectedFailureRecordValue,
        "graph_record",
        "failure_record",
        "FailureRecord",
    ),
    (
        "fan_out_inputs",
        OUTPUT_RECORD_MODELS_BY_TYPE["fan_out_inputs"],
        ProjectedFanOutInputsRecord,
        object,
        "output",
        "candidate",
        "ImplementationCandidate",
    ),
    (
        "file_state",
        OUTPUT_RECORD_MODELS_BY_TYPE["file_state"],
        ProjectedFileStateRecord,
        object,
        "file_state",
        "file_state",
        "FileStateRecord",
    ),
    (
        "gap_classification",
        OUTPUT_RECORD_MODELS_BY_TYPE["gap_classification"],
        ProjectedGapClassificationRecord,
        ProjectedGapClassificationValue,
        "output",
        "gap_classification",
        "GapClassification",
    ),
    (
        "gap_plan",
        OUTPUT_RECORD_MODELS_BY_TYPE["gap_plan"],
        ProjectedGapClassificationRecord,
        ProjectedGapClassificationValue,
        "output",
        "gap_plan",
        "GapClassification",
    ),
    (
        "graph_patch_proposal",
        OUTPUT_RECORD_MODELS_BY_TYPE["graph_patch_proposal"],
        ProjectedGraphPatchProposalRecord,
        ProjectedGraphPatchProposalValue,
        "output",
        "graph_patch_proposal",
        "GraphPatch",
    ),
    (
        "join_result",
        OUTPUT_RECORD_MODELS_BY_TYPE["join_result"],
        ProjectedJoinResultRecord,
        ProjectedJoinResultValue,
        "output",
        "join_result",
        "JoinResult",
    ),
    (
        "recovery_plan",
        OUTPUT_RECORD_MODELS_BY_TYPE["recovery_plan"],
        ProjectedRecoveryPlanRecord,
        ProjectedRecoveryPlanValue,
        "output",
        "recovery_plan",
        "RecoveryPlan",
    ),
    (
        "requirement_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["requirement_record"],
        ProjectedRequirementRecord,
        ProjectedRequirementRecordValue,
        "graph_record",
        "requirement",
        "RequirementRecord",
    ),
    (
        "routine_snapshot",
        OUTPUT_RECORD_MODELS_BY_TYPE["routine_snapshot"],
        ProjectedRoutineSnapshotRecord,
        ProjectedRoutineSnapshotValue,
        "graph_record",
        "snapshot",
        "RoutineSnapshot",
    ),
    (
        "run_context",
        OUTPUT_RECORD_MODELS_BY_TYPE["run_context"],
        ProjectedRunContextRecord,
        ProjectedRunContextValue,
        "graph_record",
        "run_context",
        "RunContext",
    ),
    (
        "verification_report",
        OUTPUT_RECORD_MODELS_BY_TYPE["verification_report"],
        ProjectedVerificationReportRecord,
        ProjectedVerificationReportValue,
        "verification",
        "verification_report",
        "VerificationReport",
    ),
)


@pytest.mark.parametrize(
    ("record_type", "source_type", "projected_type", "value_type", "record_kind", "port", "schema"),
    PROJECTED_RECORD_SEMANTICS,
)
def test_project_record_has_explicit_canonical_contract(
    record_type: str,
    source_type: type[object],
    projected_type: type[object],
    value_type: type[object],
    record_kind: str,
    port: str,
    schema: str,
) -> None:
    source = source_type.model_validate(OUTPUT_RECORD_CASES[record_type])

    projected = project_record(source)

    assert projected.record_type == record_type
    assert projected.record_kind == record_kind
    assert projected.port == port
    assert projected.schema_ == schema
    assert type(projected) is projected_type
    if value_type is not object:
        assert type(getattr(projected, "value")) is value_type
    assert projected.model_dump(
        mode="json", by_alias=True, exclude_unset=True
    ) == source.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert "data" not in type(projected).model_fields


@pytest.mark.parametrize("record_type", sorted(OUTPUT_RECORD_MODELS_BY_TYPE))
def test_projected_record_round_trips_public_json(record_type: str) -> None:
    source = OUTPUT_RECORD_MODELS_BY_TYPE[record_type].model_validate(
        OUTPUT_RECORD_CASES[record_type]
    )
    projected = project_record(source)

    restored = TypeAdapter(ProjectedRecord).validate_json(projected.model_dump_json())

    assert restored == projected


def test_project_record_isolated_from_source_event_mutation() -> None:
    raw: dict[str, Any] = dict(OUTPUT_RECORD_CASES["candidate"])
    source = OUTPUT_RECORD_MODELS_BY_TYPE["candidate"].model_validate(raw)
    projected = project_record(source)

    raw["value"]["summary"] = "mutated after projection"

    assert projected.value.summary == "Implemented the requested change"


def test_project_record_rejects_unknown_discriminator() -> None:
    with pytest.raises(ValueError, match="unknown projected record discriminator"):
        project_record(cast(Any, {"record_type": "unknown"}))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"record_type": "unknown"},
        {**OUTPUT_RECORD_CASES["candidate"], "port": "check_result"},
        {**OUTPUT_RECORD_CASES["candidate"], "schema": "CheckResult"},
        {**OUTPUT_RECORD_CASES["verification_report"], "outcome": "failed"},
        {**OUTPUT_RECORD_CASES["gap_plan"], "port": "gap_classification"},
    ],
)
def test_public_projected_record_union_rejects_invalid_contracts(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {**OUTPUT_RECORD_CASES["artifact_reference"], "port": "artifact_reference"},
        {**OUTPUT_RECORD_CASES["artifact_reference"], "schema": "ArtifactReference"},
    ],
)
def test_public_projected_record_union_rejects_crossed_artifact_reference_pairs(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {**OUTPUT_RECORD_CASES["analysis_summary"], "schema": "RegionSummary"},
        {
            **OUTPUT_RECORD_CASES["analysis_summary"],
            "port": "planning_summary",
            "schema": "AnalysisSummary",
        },
        {
            **OUTPUT_RECORD_CASES["analysis_summary"],
            "port": "region_summary",
            "schema": "AnalysisSummary",
        },
    ],
)
def test_public_projected_record_union_rejects_crossed_analysis_summary_pairs(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


@pytest.mark.parametrize(
    "record_type, mutation",
    [
        ("fan_out_inputs", {"port": "check_result"}),
        ("fan_out_inputs", {"schema": "CheckResult"}),
        ("file_state", {"port": "candidate"}),
        ("file_state", {"schema": "ImplementationCandidate"}),
        ("verification_report", {"value": {"outcome": "failed", "grades": []}}),
        (
            "check_result",
            {"value": {**OUTPUT_RECORD_CASES["check_result"]["value"], "timeout_seconds": 0}},
        ),
        (
            "graph_patch_proposal",
            {
                "value": {
                    "patch_id": "patch",
                    "proposed_by_node_id": "node",
                    "base_graph_position": 0,
                }
            },
        ),
        (
            "decision_request",
            {"value": {"decision_type": "approval", "options": [], "consequence_summary": "x"}},
        ),
        ("authority_request_record", {"value": {"requested_authority": ["write"], "reason": "x"}}),
        (
            "decision_record",
            {"value": {"decision": "approved", "decision_type": "approval", "decider": ""}},
        ),
        ("gap_plan", {"port": "gap_classification"}),
    ],
)
def test_public_projected_records_preserve_source_invariants(
    record_type: str, mutation: dict[str, Any]
) -> None:
    payload = {**OUTPUT_RECORD_CASES[record_type], **mutation}

    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


def test_projected_record_envelope_payloads_are_object_only() -> None:
    hints = get_type_hints(ProjectedRecordBase)

    assert "FrozenMap" in str(hints["payload"])
    assert "FrozenMap" in str(hints["provenance"])
    assert FrozenJsonValue not in (hints["payload"], hints["provenance"])
    assert FrozenMap is not None


def test_project_record_preserves_nondefault_verification_check_and_decision_nested_values() -> (
    None
):
    verification_source = OUTPUT_RECORD_MODELS_BY_TYPE["verification_report"].model_validate(
        {
            "record_id": "verification-nested-1",
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": "verifier-1",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": "candidate-1",
            "task_region_id": "region-1",
            "outcome": "passed",
            "value": {
                "outcome": "passed",
                "grades": [{"requirement_id": "R-1", "grade": "A", "reason": "met"}],
                "reason": "all requirements met",
            },
            "evidence": {"checks": ["check-1"], "confidence": 0.9},
            "candidate_record_ids": ["candidate-record-1"],
        }
    )
    check_source = OUTPUT_RECORD_MODELS_BY_TYPE["check_result"].model_validate(
        {
            "record_id": "check-nested-1",
            "record_kind": "output",
            "record_type": "check_result",
            "producer_node_id": "check-1",
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": "candidate-1",
            "task_region_id": "region-1",
            "attempt_number": 2,
            "value": {
                "status": "failed",
                "classification": "failed",
                "command_id": "pytest",
                "command_binding": {"kind": "known", "tags": ["unit"]},
                "command_text": "uv run pytest tests/unit",
                "command": {"argv": ["uv", "run", "pytest"], "shell": False},
                "worktree_path": "/tmp/worktree",
                "source_worktree_path": "/tmp/source",
                "execution_worktree_path": "/tmp/execution",
                "base_snapshot_id": "S0",
                "execution_snapshot_id": "S1",
                "execution_snapshot_ref": "refs/snapshots/S1",
                "execution_id": "execution-1",
                "exit_code": 1,
                "duration_ms": 42,
                "stdout_tail": "partial",
                "stdout_ref": {
                    "artifact_id": "stdout-1",
                    "content_hash": "sha256:" + "a" * 64,
                    "size_bytes": 42,
                    "media_type": "text/plain",
                    "encoding": "utf-8",
                    "storage_uri": "artifact://sha256/" + "a" * 64,
                },
                "stderr_tail": "failure",
                "stderr_truncated": False,
                "stdout_truncated": True,
                "timeout_seconds": 30.5,
                "environment_policy": {"cwd": "/tmp/worktree", "env": {"CI": "1"}},
                "candidate_record_ids": ["candidate-record-1"],
                "file_state_record_ids": ["file-state-1"],
                "verification_report_record_ids": ["verification-nested-1"],
                "evaluated_record_ids": ["requirement-1"],
            },
        }
    )
    decision_source = OUTPUT_RECORD_MODELS_BY_TYPE["decision_record"].model_validate(
        {
            "record_id": "decision-nested-1",
            "record_kind": "output",
            "record_type": "decision_record",
            "producer_node_id": "gate-1",
            "port": "decision_record",
            "schema": "DecisionRecord",
            "value": {
                "decision": "approved",
                "decision_type": "approval",
                "decider": {"kind": "human", "id": "alice"},
                "scope": {"regions": ["region-1"]},
                "expires_at": "2026-07-30T00:00:00Z",
                "reason": "reviewed",
            },
        }
    )

    verification = project_record(verification_source)
    check = project_record(check_source)
    decision = project_record(decision_source)

    assert type(verification.value) is ProjectedVerificationReportValue
    assert type(verification.value.grades[0]) is ProjectedGradeRow
    assert verification.evidence == FrozenMap({"checks": ("check-1",), "confidence": 0.9})
    assert type(check.value) is ProjectedCheckResultRecordValue
    assert type(check.value.stdout_ref) is ProjectedStoredArtifactRef
    assert check.value.command == FrozenMap({"argv": ("uv", "run", "pytest"), "shell": False})
    assert type(decision.value) is ProjectedDecisionRecordValue
    assert type(decision.value.decider) is ProjectedDecisionActor
    assert decision.value.scope == FrozenMap({"regions": ("region-1",)})
    for source, projected in (
        (verification_source, verification),
        (check_source, check),
        (decision_source, decision),
    ):
        assert projected.model_dump(
            mode="json", by_alias=True, exclude_unset=True
        ) == source.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert TypeAdapter(ProjectedRecord).validate_json(projected.model_dump_json()) == projected


def test_project_record_preserves_nondefault_file_state_and_fan_out_nested_values() -> None:
    file_state_source = OUTPUT_RECORD_MODELS_BY_TYPE["file_state"].model_validate(
        {
            "record_id": "file-state-nested-1",
            "record_kind": "file_state",
            "record_type": "file_state",
            "producer_node_id": "worker-1",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": "S1",
            "base_snapshot_id": "S0",
            "git": {"commit_sha": "abc", "tree_sha": "tree", "diff_summary": {"changed": 2}},
            "tracked": [{"path": "src/a.py", "status": "modified", "size_bytes": 12}],
            "external": [
                {
                    "path": "vendor/tool",
                    "source": "external",
                    "manifest": {
                        "path": "vendor/tool",
                        "hash": "sha256:tool",
                        "origin": "registry",
                        "retention": "keep",
                    },
                }
            ],
            "classifications": [
                {"path": "secret.txt", "classification": "secret", "rejected": True}
            ],
            "verdict": "rejected",
            "patch_bundle_id": "bundle-1",
            "cleanup_excluded_paths": ["secret.txt"],
            "compromised": True,
        }
    )
    fan_out_source = OUTPUT_RECORD_MODELS_BY_TYPE["fan_out_inputs"].model_validate(
        {
            "record_id": "fan-out-nested-1",
            "record_kind": "output",
            "record_type": "fan_out_inputs",
            "producer_node_id": "planner-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": "candidate-1",
            "task_region_id": "region-1",
            "attempt_number": 3,
            "file_state_record_ids": ["file-state-nested-1"],
            "value": {"inputs": [{"requirement": "R-1"}], "options": {"retry": True}},
        }
    )

    file_state = project_record(file_state_source)
    fan_out = project_record(fan_out_source)

    assert type(file_state.git) is ProjectedGitRef
    assert type(file_state.tracked[0]) is ProjectedFileEntry
    assert type(file_state.external[0]) is ProjectedExternalFileEntry
    assert type(file_state.external[0].manifest) is ProjectedExternalArtifactManifest
    assert fan_out.value == FrozenMap(
        {"inputs": (FrozenMap({"requirement": "R-1"}),), "options": FrozenMap({"retry": True})}
    )
    for source, projected in ((file_state_source, file_state), (fan_out_source, fan_out)):
        assert projected.model_dump(
            mode="json", by_alias=True, exclude_unset=True
        ) == source.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert TypeAdapter(ProjectedRecord).validate_json(projected.model_dump_json()) == projected
