"""Strict record-event specifications needed by topology compilation.

Only ``output_record_accepted`` lives here during Task 3 so compiled topology
can be hydrated by the catalog.  Verification and gate semantics remain owned
by the later records slice.
"""

from __future__ import annotations

from typing import Any, TypeAlias, cast

from pydantic import field_validator

from orchestrator.graph.models import (
    AnalysisSummaryRecord,
    ArtifactReferenceRecord,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CandidateRecord,
    CheckResultRecord,
    CompletionDecisionRecord,
    DecisionRecord,
    DecisionRequestRecord,
    FailureRecord,
    FileStateRecord,
    GapClassificationRecord,
    GraphPatchProposalRecord,
    JoinResultRecord,
    OutputRecord,
    RecoveryPlanRecord,
    RequirementRecord,
    RunContextRecord,
    RoutineSnapshotRecord,
    VerificationReportRecord,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


StrictOutputRecord: TypeAlias = (
    OutputRecord
    | RunContextRecord
    | RoutineSnapshotRecord
    | ArtifactReferenceRecord
    | VerificationReportRecord
    | CompletionDecisionRecord
    | JoinResultRecord
    | CheckResultRecord
    | CandidateRecord
    | GapClassificationRecord
    | DecisionRecord
    | AuthorityDecisionRecord
    | AnalysisSummaryRecord
    | GraphPatchProposalRecord
    | RequirementRecord
    | DecisionRequestRecord
    | AuthorityRequestRecord
    | FailureRecord
    | RecoveryPlanRecord
    | FileStateRecord
)


class OutputRecordAcceptedPayload(StrictPayload):
    """Strict durable envelope for one already-validated output record."""

    record: StrictOutputRecord

    @field_validator("record", mode="before")
    @classmethod
    def validate_record_variant(cls, value: Any) -> StrictOutputRecord:
        if not isinstance(value, dict):
            raise TypeError("record must be an object")
        typed_value = cast(dict[str, Any], value)
        record_type = typed_value.get("record_type")
        schema = typed_value.get("schema")
        record_kind = typed_value.get("record_kind")
        variants: dict[str, type[Any]] = {
            "analysis_summary": AnalysisSummaryRecord,
            "artifact_reference": ArtifactReferenceRecord,
            "authority_decision": AuthorityDecisionRecord,
            "authority_request_record": AuthorityRequestRecord,
            "candidate": CandidateRecord,
            "check_result": CheckResultRecord,
            "completion_decision": CompletionDecisionRecord,
            "decision_record": DecisionRecord,
            "decision_request": DecisionRequestRecord,
            "failure_record": FailureRecord,
            "gap_classification": GapClassificationRecord,
            "gap_plan": GapClassificationRecord,
            "graph_patch_proposal": GraphPatchProposalRecord,
            "join_result": JoinResultRecord,
            "recovery_plan": RecoveryPlanRecord,
            "requirement_record": RequirementRecord,
            "run_context": RunContextRecord,
            "routine_snapshot": RoutineSnapshotRecord,
            "verification_report": VerificationReportRecord,
        }
        variant = variants.get(record_type) if isinstance(record_type, str) else None
        if variant is None and record_kind == "file_state":
            variant = FileStateRecord
        if variant is None and schema == "ContextArtifact":
            variant = ArtifactReferenceRecord
        if variant is None and schema == "VerificationReport":
            variant = VerificationReportRecord
        if variant is None and record_kind == "output":
            variant = OutputRecord
        if variant is None:
            raise ValueError("unknown strict output record variant")
        allowed_fields = {name for name in variant.model_fields} | {
            field.alias for field in variant.model_fields.values() if field.alias is not None
        }
        unknown = set(typed_value).difference(allowed_fields)
        if unknown:
            raise ValueError(f"unknown strict output record fields: {sorted(unknown)}")
        return variant.model_validate(typed_value)

    def to_json(self) -> dict[str, JsonValue]:
        """Serialize the explicit record envelope without legacy flattening."""

        return cast(
            dict[str, JsonValue], self.model_dump(mode="json", by_alias=True, exclude_none=True)
        )


def reduce_output_record_accepted(
    state: Any,
    payload: OutputRecordAcceptedPayload,
    metadata: EventMetadata,
) -> Any:
    from orchestrator.graph.projections import reduce_typed_output_record_accepted

    return reduce_typed_output_record_accepted(state, payload, metadata)


OUTPUT_RECORD_ACCEPTED = EventSpecification(
    "output_record_accepted",
    OutputRecordAcceptedPayload,
    reduce_output_record_accepted,
    ProjectionParticipation.NEUTRAL,
)


EVENT_SPECIFICATIONS = (OUTPUT_RECORD_ACCEPTED,)


__all__ = [
    "EVENT_SPECIFICATIONS",
    "OUTPUT_RECORD_ACCEPTED",
    "OutputRecordAcceptedPayload",
    "reduce_output_record_accepted",
]
