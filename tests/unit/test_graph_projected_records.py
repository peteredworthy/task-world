"""Boundary conversion contracts for immutable projected records."""

from typing import Any, cast

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
    project_record,
)
from tests.unit.test_output_record_event_payloads import OUTPUT_RECORD_CASES


def test_projected_record_contracts_are_public_graph_interfaces() -> None:
    assert all(
        isinstance(contract, type)
        for contract in (
            ProjectedRecordBase,
            ProjectedCandidateRecordValue,
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


PROJECTED_RECORD_SEMANTICS = (
    ("analysis_summary", "output", "analysis_summary", "AnalysisSummary"),
    ("artifact_reference", "graph_record", "artifact", "ContextArtifact"),
    ("authority_decision", "output", "authority_decision", "AuthorityDecision"),
    ("authority_request_record", "graph_record", "authority_request_record", "AuthorityRequest"),
    ("candidate", "output", "candidate", "ImplementationCandidate"),
    ("check_result", "output", "check_result", "CheckResult"),
    ("classified_gap", "output", "classified_gap", "GapClassification"),
    ("completion_decision", "output", "completion_decision", "CompletionDecision"),
    ("decision_record", "output", "decision_record", "DecisionRecord"),
    ("decision_request", "graph_record", "decision_request", "DecisionRequest"),
    ("failure_record", "graph_record", "failure_record", "FailureRecord"),
    ("fan_out_inputs", "output", "candidate", "ImplementationCandidate"),
    ("file_state", "file_state", "file_state", "FileStateRecord"),
    ("gap_classification", "output", "gap_classification", "GapClassification"),
    ("gap_plan", "output", "gap_plan", "GapClassification"),
    ("graph_patch_proposal", "output", "graph_patch_proposal", "GraphPatch"),
    ("join_result", "output", "join_result", "JoinResult"),
    ("recovery_plan", "output", "recovery_plan", "RecoveryPlan"),
    ("requirement_record", "graph_record", "requirement", "RequirementRecord"),
    ("routine_snapshot", "graph_record", "snapshot", "RoutineSnapshot"),
    ("run_context", "graph_record", "run_context", "RunContext"),
    ("verification_report", "verification", "verification_report", "VerificationReport"),
)


@pytest.mark.parametrize(
    ("record_type", "record_kind", "port", "schema"), PROJECTED_RECORD_SEMANTICS
)
def test_project_record_has_explicit_canonical_contract(
    record_type: str, record_kind: str, port: str, schema: str
) -> None:
    source_type = OUTPUT_RECORD_MODELS_BY_TYPE[record_type]
    source = source_type.model_validate(OUTPUT_RECORD_CASES[record_type])

    projected = project_record(source)

    assert projected.record_type == record_type
    assert projected.record_kind == record_kind
    assert projected.port == port
    assert projected.schema_ == schema
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
