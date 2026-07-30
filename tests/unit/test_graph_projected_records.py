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
