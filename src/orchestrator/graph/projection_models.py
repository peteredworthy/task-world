"""Immutable destination models for the future graph-projection cutover.

This module is deliberately passive: production reducers do not construct these
models until the later cutover task.  Conversion copies transport records at the
boundary, preventing mutable event payloads from becoming projected state.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from orchestrator.graph.models import AcceptedOutputRecordPayload, OUTPUT_RECORD_MODELS_BY_TYPE
from orchestrator.graph.projection_collections import FrozenJsonValue, FrozenMap, freeze_json


class ProjectionModel(BaseModel):
    """Strict, immutable base for every model reachable from the scaffold."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, populate_by_name=True)


class LifecycleProjection(ProjectionModel):
    state: StrictStr | None = None
    event_position: StrictInt = 0


class NodeSpecProjection(ProjectionModel):
    node_id: StrictStr
    kind: StrictStr | None = None
    role: StrictStr | None = None
    task_region_id: StrictStr | None = None
    candidate_id: StrictStr | None = None
    attempt_number: StrictInt | None = None
    resource_claims: tuple[FrozenJsonValue, ...] = ()
    allowed_actions: tuple[StrictStr, ...] = ()
    preconditions: tuple[StrictStr, ...] = ()
    inputs: tuple[FrozenJsonValue, ...] = ()
    outputs: tuple[FrozenJsonValue, ...] = ()
    details: FrozenMap[str, FrozenJsonValue] = Field(default_factory=FrozenMap)


class NodesProjection(ProjectionModel):
    by_id: FrozenMap[StrictStr, NodeSpecProjection] = Field(default_factory=FrozenMap)


class TasksProjection(ProjectionModel):
    state_by_region: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)


class TopologyProjection(ProjectionModel):
    edge_ids: tuple[StrictStr, ...] = ()
    input_record_ids_by_port: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )


class RecordStore(ProjectionModel):
    """Canonical full-record ownership; indexes elsewhere retain identifiers only."""

    by_id: FrozenMap[StrictStr, "ProjectedRecord"] = Field(default_factory=FrozenMap)


class RecordsProjection(ProjectionModel):
    store: RecordStore = Field(default_factory=RecordStore)
    ids_by_node_port: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(default_factory=FrozenMap)


class SchedulingProjection(ProjectionModel):
    ready_node_ids: tuple[StrictStr, ...] = ()
    lease_ids_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)


class PlanningProjection(ProjectionModel):
    session_ids: tuple[StrictStr, ...] = ()


class VerificationProjection(ProjectionModel):
    record_ids_by_candidate: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )


class GovernanceProjection(ProjectionModel):
    decision_record_ids: tuple[StrictStr, ...] = ()


class RequirementsProjection(ProjectionModel):
    record_ids: tuple[StrictStr, ...] = ()


class ExecutionProjection(ProjectionModel):
    retry_not_before_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)


class UsageProjection(ProjectionModel):
    usage_keys: tuple[StrictStr, ...] = ()


class ImmutableGraphProjection(ProjectionModel):
    """Unused grouped projection scaffold; production ``GraphProjection`` remains canonical."""

    lifecycle: LifecycleProjection = Field(default_factory=LifecycleProjection)
    nodes: NodesProjection = Field(default_factory=NodesProjection)
    tasks: TasksProjection = Field(default_factory=TasksProjection)
    topology: TopologyProjection = Field(default_factory=TopologyProjection)
    records: RecordsProjection = Field(default_factory=RecordsProjection)
    scheduling: SchedulingProjection = Field(default_factory=SchedulingProjection)
    planning: PlanningProjection = Field(default_factory=PlanningProjection)
    verification: VerificationProjection = Field(default_factory=VerificationProjection)
    governance: GovernanceProjection = Field(default_factory=GovernanceProjection)
    requirements: RequirementsProjection = Field(default_factory=RequirementsProjection)
    execution: ExecutionProjection = Field(default_factory=ExecutionProjection)
    usage: UsageProjection = Field(default_factory=UsageProjection)


class ProjectedRecordBase(ProjectionModel):
    record_id: StrictStr
    record_kind: StrictStr
    producer_node_id: StrictStr | None = None
    port: StrictStr
    schema_: StrictStr = Field(alias="schema")
    data: FrozenMap[StrictStr, FrozenJsonValue]

    @field_validator("data", mode="before")
    @classmethod
    def freeze_data(cls, value: object) -> FrozenMap[str, FrozenJsonValue]:
        frozen = freeze_json(value)
        if not isinstance(frozen, FrozenMap):
            raise ValueError("projected record data must be an object")
        return frozen


class ProjectedAnalysisSummaryRecord(ProjectedRecordBase):
    record_type: Literal["analysis_summary"]


class ProjectedArtifactReferenceRecord(ProjectedRecordBase):
    record_type: Literal["artifact_reference"]


class ProjectedAuthorityDecisionRecord(ProjectedRecordBase):
    record_type: Literal["authority_decision"]


class ProjectedAuthorityRequestRecord(ProjectedRecordBase):
    record_type: Literal["authority_request_record"]


class ProjectedCandidateRecord(ProjectedRecordBase):
    record_type: Literal["candidate"]


class ProjectedCheckResultRecord(ProjectedRecordBase):
    record_type: Literal["check_result"]


class ProjectedClassifiedGapRecord(ProjectedRecordBase):
    record_type: Literal["classified_gap"]


class ProjectedCompletionDecisionRecord(ProjectedRecordBase):
    record_type: Literal["completion_decision"]


class ProjectedDecisionRecord(ProjectedRecordBase):
    record_type: Literal["decision_record"]


class ProjectedDecisionRequestRecord(ProjectedRecordBase):
    record_type: Literal["decision_request"]


class ProjectedFailureRecord(ProjectedRecordBase):
    record_type: Literal["failure_record"]


class ProjectedFanOutInputsRecord(ProjectedRecordBase):
    record_type: Literal["fan_out_inputs"]


class ProjectedFileStateRecord(ProjectedRecordBase):
    record_type: Literal["file_state"]


class ProjectedGapClassificationRecord(ProjectedRecordBase):
    record_type: Literal["gap_classification"]


class ProjectedGapPlanRecord(ProjectedRecordBase):
    record_type: Literal["gap_plan"]


class ProjectedGraphPatchProposalRecord(ProjectedRecordBase):
    record_type: Literal["graph_patch_proposal"]


class ProjectedJoinResultRecord(ProjectedRecordBase):
    record_type: Literal["join_result"]


class ProjectedRecoveryPlanRecord(ProjectedRecordBase):
    record_type: Literal["recovery_plan"]


class ProjectedRequirementRecord(ProjectedRecordBase):
    record_type: Literal["requirement_record"]


class ProjectedRoutineSnapshotRecord(ProjectedRecordBase):
    record_type: Literal["routine_snapshot"]


class ProjectedRunContextRecord(ProjectedRecordBase):
    record_type: Literal["run_context"]


class ProjectedVerificationReportRecord(ProjectedRecordBase):
    record_type: Literal["verification_report"]


ProjectedRecord: TypeAlias = Annotated[
    ProjectedAnalysisSummaryRecord
    | ProjectedArtifactReferenceRecord
    | ProjectedAuthorityDecisionRecord
    | ProjectedAuthorityRequestRecord
    | ProjectedCandidateRecord
    | ProjectedCheckResultRecord
    | ProjectedClassifiedGapRecord
    | ProjectedCompletionDecisionRecord
    | ProjectedDecisionRecord
    | ProjectedDecisionRequestRecord
    | ProjectedFailureRecord
    | ProjectedFanOutInputsRecord
    | ProjectedFileStateRecord
    | ProjectedGapClassificationRecord
    | ProjectedGapPlanRecord
    | ProjectedGraphPatchProposalRecord
    | ProjectedJoinResultRecord
    | ProjectedRecoveryPlanRecord
    | ProjectedRequirementRecord
    | ProjectedRoutineSnapshotRecord
    | ProjectedRunContextRecord
    | ProjectedVerificationReportRecord,
    Field(discriminator="record_type"),
]

_PROJECTED_RECORD_MODELS: FrozenMap[str, type[ProjectedRecordBase]] = FrozenMap(
    {
        "analysis_summary": ProjectedAnalysisSummaryRecord,
        "artifact_reference": ProjectedArtifactReferenceRecord,
        "authority_decision": ProjectedAuthorityDecisionRecord,
        "authority_request_record": ProjectedAuthorityRequestRecord,
        "candidate": ProjectedCandidateRecord,
        "check_result": ProjectedCheckResultRecord,
        "classified_gap": ProjectedClassifiedGapRecord,
        "completion_decision": ProjectedCompletionDecisionRecord,
        "decision_record": ProjectedDecisionRecord,
        "decision_request": ProjectedDecisionRequestRecord,
        "failure_record": ProjectedFailureRecord,
        "fan_out_inputs": ProjectedFanOutInputsRecord,
        "file_state": ProjectedFileStateRecord,
        "gap_classification": ProjectedGapClassificationRecord,
        "gap_plan": ProjectedGapPlanRecord,
        "graph_patch_proposal": ProjectedGraphPatchProposalRecord,
        "join_result": ProjectedJoinResultRecord,
        "recovery_plan": ProjectedRecoveryPlanRecord,
        "requirement_record": ProjectedRequirementRecord,
        "routine_snapshot": ProjectedRoutineSnapshotRecord,
        "run_context": ProjectedRunContextRecord,
        "verification_report": ProjectedVerificationReportRecord,
    }
)

if set(_PROJECTED_RECORD_MODELS) != set(OUTPUT_RECORD_MODELS_BY_TYPE):
    raise RuntimeError("projected record registry must cover every accepted output record type")


def project_record(record: AcceptedOutputRecordPayload) -> ProjectedRecord:
    """Copy a validated accepted record into its immutable projection counterpart."""
    if not hasattr(record, "model_dump"):
        raise ValueError("unknown projected record discriminator")
    payload = record.model_dump(mode="json", by_alias=True)
    record_type = payload.get("record_type")
    if not isinstance(record_type, str) or record_type not in _PROJECTED_RECORD_MODELS:
        raise ValueError("unknown projected record discriminator")
    model = _PROJECTED_RECORD_MODELS[record_type]
    adapter: TypeAdapter[ProjectedRecord] = TypeAdapter(ProjectedRecord)
    return adapter.validate_python(
        model.model_validate(
            {
                "record_id": payload["record_id"],
                "record_kind": payload["record_kind"],
                "producer_node_id": payload.get("producer_node_id"),
                "port": payload["port"],
                "schema": payload["schema"],
                "record_type": record_type,
                "data": payload,
            }
        )
    )
