"""Callback and output/evidence command handlers."""

from __future__ import annotations
import posixpath
from typing import Annotated, Any, Literal, cast

from orchestrator.graph.callbacks import (
    CallbackOutcome,
    CallbackRequest,
    validate_callback,
)
from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.projections import (
    GraphProjection,
)
from orchestrator.graph.events.lifecycle import (
    CALLBACK_ACCEPTED,
    CALLBACK_REJECTED_STALE,
    CALLBACK_REJECTED_CONFLICT,
    CALLBACK_DUPLICATE_RETURNED,
    COMMAND_REJECTED,
    CallbackAcceptedPayload,
    CallbackDuplicateReturnedPayload,
    CallbackRejectedPayload,
    CommandRejectedPayload,
)
from orchestrator.graph.commands.event_creator import TypedEventCreator

from pydantic import ConfigDict, Field, RootModel, field_validator

from orchestrator.graph.commands.source_repair import (
    active_lease_node_ids,
    dedupe_repair_events,
    failed_check_recovery_events,
    failed_verification_recovery_events,
    no_successor_recovery_terminal_failure_events,
    passed_check_terminalization_events,
    passed_verification_terminalization_events,
    project_with_events,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph.events.leases import LEASE_RELEASED, LeaseReleasedPayload
from orchestrator.graph.events.decisions import (
    APPEAL_OPENED,
    APPROVAL_DECISION_RECORDED,
    AUTHORITY_DECISION_RECORDED,
    OVERSIGHT_DECISION_RECORDED,
    AppealOpenedPayload,
)
from orchestrator.graph.events.requirements import (
    REQUIREMENT_REVISION_RECORDED,
    SUPPORT_EVIDENCE_RECORDED,
    RequirementRevisionPayload,
    SupportEvidencePayload,
)
from orchestrator.graph.events.file_state import (
    FILE_STATE_ACCEPTED,
    FILE_STATE_REJECTED,
    FileStateRejectedPayload,
)
from orchestrator.graph.events.records import (
    OUTPUT_RECORD_ACCEPTED,
    VERIFICATION_FAILED,
    VERIFICATION_PASSED,
    OutputRecordAcceptedPayload,
    VerificationOutcomePayload,
)
from orchestrator.graph.events.patches import GraphPatchAcceptedPayload
from orchestrator.graph.commands.file_state import (
    handle_record_cleanup_applied,
    handle_record_gatekeeper_verdicts,
)
from orchestrator.graph.events.topology import (
    INPUT_BOUND,
    NODE_CREATED,
    NODE_STATE_CHANGED,
    InputBoundPayload,
    NodeStateChangedPayload,
    PlannerSessionStateChangedPayload,
    SESSION_STATE_CHANGED,
)
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
    output_port_contract,
    validate_output_record,
)
from orchestrator.graph.models import (
    AnalysisSummaryRecord,
    ArtifactReferenceRecord,
    AuthorityDecisionRecord,
    CandidateRecord,
    CheckResultRecord,
    DecisionRecord,
    FileStateRecord,
    OutputRecord,
    StrictFileStateRecord,
    StrictCheckResultRecord,
    StrictOutputRecordBase,
    StrictVerificationReportRecord,
    VerificationReportRecord,
    record_selector_matches,
)
from orchestrator.graph.scheduler import ResourceClaim, claims_conflict

ANALYSIS_SUMMARY_PORTS = frozenset({"analysis_summary", "planning_summary", "region_summary"})


class RaiseAppealCommand(StrictPayload):
    node_id: str
    appeal_type: Literal["invalid_test"]
    appeal_node_id: str | None = None
    oversight_node_id: str | None = None
    candidate_id: str | None = None
    task_region_id: str | None = None
    lease_id: str | None = None


class DecisionCommandFields(StrictPayload):
    node_id: str
    decider: JsonValue
    scope: dict[str, JsonValue] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None

    @field_validator("decider")
    @classmethod
    def validate_decider_identity(cls, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            if value.strip():
                return value
            raise ValueError("decider identity must be non-empty")
        if isinstance(value, dict):
            kind = value.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError("decider object must include a non-empty kind")
            for field in ("id", "node_id", "role"):
                identity = value.get(field)
                if identity is not None and (not isinstance(identity, str) or not identity.strip()):
                    raise ValueError(f"decider {field} must be non-empty when provided")
            return value
        raise ValueError("decider must be a non-empty string or identity object")


class ApprovalDecisionCommand(DecisionCommandFields):
    decision_type: Literal["approval"]
    decision: Literal["approved", "rejected", "deferred"]


class AuthorityDecisionCommand(DecisionCommandFields):
    decision_type: Literal["authority"]
    decision: Literal["granted", "denied", "deferred"]


class OversightDecisionCommand(DecisionCommandFields):
    decision_type: Literal["oversight"]
    decision: Literal["accepted", "rejected", "invalid_test_accepted"]


DecisionCommand = Annotated[
    ApprovalDecisionCommand | AuthorityDecisionCommand | OversightDecisionCommand,
    Field(discriminator="decision_type"),
]


class RecordDecisionCommand(RootModel[DecisionCommand]):
    model_config = ConfigDict(strict=True, frozen=True)


class RecordRequirementRevisionCommand(StrictPayload):
    requirement_id: str
    version_id: str
    record_id: str | None = None
    classification: str | None = None
    change_classification: str | None = None
    requires_authority: bool | None = None
    new_behavior: bool | None = None
    behavior_change: bool | None = None
    semantic_change: bool | None = None
    validation_strengthening: bool | None = None
    active: bool | None = None
    previous_version_id: str | None = None


class RecordSupportEvidenceCommand(StrictPayload):
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str | None = None
    status: Literal["active", "stale"] | None = None
    stale_reason: str | None = None
    confidence: str | None = None


def _command_rejected(creator: TypedEventCreator, command_type: str, reason: str) -> HydratedEvent:
    return creator.create(
        COMMAND_REJECTED,
        CommandRejectedPayload(command_type=command_type, reason=reason),
    )


class SubmitCallbackCommand(StrictPayload):
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    base_snapshot_id: str
    observed_graph_position: int = Field(ge=0)
    idempotency_key: str
    payload_hash: str | None = None
    payload: JsonValue = None
    complete_node: bool = True
    new_state: str = "completed"
    is_mutating: bool = True


class AcknowledgeStartCommand(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    execution_id: str
    prompt_summary: dict[str, JsonValue] | None = None


def _require_future_outcomes(
    output: list[HydratedEvent],
) -> list[HydratedEvent]:
    return output


def handle_submit_callback_command(
    command: SubmitCallbackCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    output = apply_callback_effects(
        projection,
        list(events),
        command,
        context.run_id,
        TypedEventCreator(context, assign_position=False, causation_id=SUBMIT_CALLBACK.name),
        context.catalog,
    )
    return _require_future_outcomes(output)


def handle_acknowledge_start_command(
    command: AcknowledgeStartCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    return _require_future_outcomes(
        apply_acknowledge_start_effects(
            projection,
            command,
            TypedEventCreator(context, assign_position=False, causation_id=ACKNOWLEDGE_START.name),
        )
    )


SUBMIT_CALLBACK = CommandSpecification(
    "submit_callback", SubmitCallbackCommand, handle_submit_callback_command
)
ACKNOWLEDGE_START = CommandSpecification(
    "acknowledge_start", AcknowledgeStartCommand, handle_acknowledge_start_command
)
CALLBACK_COMMAND_SPECIFICATIONS = (ACKNOWLEDGE_START, SUBMIT_CALLBACK)


def handle_raise_appeal(
    command: RaiseAppealCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(context, assign_position=False, causation_id="raise_appeal")
    node_state = projection["node_states"].get(command.node_id)
    if (
        node_state in {"completed", "failed", "cancelled", "retired"}
        and projection["node_kinds"].get(command.node_id) != "verifier"
    ):
        return [_command_rejected(creator, "raise_appeal", f"terminal target node: {node_state}")]
    appeal_id = command.appeal_node_id or context.id_generator.next_id("appeal")
    oversight_id = command.oversight_node_id or context.id_generator.next_id("oversight")
    from orchestrator.graph.events.topology import NodeCreatedPayload

    return [
        creator.create(
            APPEAL_OPENED,
            AppealOpenedPayload(
                node_id=appeal_id,
                appealed_node_id=command.node_id,
                appeal_type=command.appeal_type,
                candidate_id=command.candidate_id,
                task_region_id=command.task_region_id,
                lease_id=command.lease_id,
            ),
        ),
        creator.create(
            NODE_CREATED,
            NodeCreatedPayload(
                node_id=oversight_id,
                kind="oversight",
                state="planned",
                task_region_id=command.task_region_id,
            ),
        ),
    ]


def handle_record_decision(
    command: RecordDecisionCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    decision_command = command.root
    creator = TypedEventCreator(context, assign_position=False, causation_id="record_decision")
    if (
        decision_command.node_id not in projection["node_states"]
        and decision_command.node_id not in projection["node_kinds"]
    ):
        return [
            _command_rejected(
                creator, "record_decision", f"unknown target node: {decision_command.node_id}"
            )
        ]
    if (
        decision_command.decision_type == "authority"
        and projection["node_kinds"].get(decision_command.node_id) != "authority_request"
    ):
        return [
            _command_rejected(
                creator, "record_decision", "authority decisions require authority_request target"
            )
        ]
    node_state = projection["node_states"].get(decision_command.node_id)
    if node_state in {"completed", "failed", "cancelled", "retired"}:
        return [
            _command_rejected(creator, "record_decision", f"terminal target node: {node_state}")
        ]
    if projection["run_state"] in {"cancelled", "failed"}:
        return [
            _command_rejected(
                creator, "record_decision", f"terminal run: {projection['run_state']}"
            )
        ]
    values = _decision_event_values(decision_command)
    task_region_id = projection["node_task_regions"].get(decision_command.node_id)
    if task_region_id is not None:
        values["task_region_id"] = task_region_id
    if decision_command.decision_type == "approval":
        event_spec = APPROVAL_DECISION_RECORDED
        first = creator.create(event_spec, event_spec.validate_payload(values))
    elif decision_command.decision_type == "authority":
        event_spec = AUTHORITY_DECISION_RECORDED
        first = creator.create(event_spec, event_spec.validate_payload(values))
    else:
        event_spec = OVERSIGHT_DECISION_RECORDED
        first = creator.create(event_spec, event_spec.validate_payload(values))
    output: list[HydratedEvent] = [first]
    record = _decision_output_record(
        projection,
        decision_command.node_id,
        {**values, "decision_type": decision_command.decision_type},
        decision_command.decision_type,
    )
    if record is not None:
        output.append(
            creator.create(
                OUTPUT_RECORD_ACCEPTED,
                OUTPUT_RECORD_ACCEPTED.validate_payload({"record": record}),
            )
        )
        output.extend(
            _typed_input_bound_events_for_record(
                projection,
                decision_command.node_id,
                str(record["port"]),
                str(record["record_id"]),
                record,
                creator,
                _record_selector_aliases(record),
            )
        )
    output.append(
        creator.create(
            NODE_STATE_CHANGED,
            NODE_STATE_CHANGED.payload_type(
                node_id=decision_command.node_id,
                new_state="completed",
                trigger=f"{event_spec.name}_accepted",
            ),
        )
    )
    output.extend(_release_active_node_leases(projection, decision_command.node_id, creator))
    return output


def handle_record_requirement_revision(
    command: RecordRequirementRevisionCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del projection
    del events
    creator = TypedEventCreator(
        context, assign_position=False, causation_id="record_requirement_revision"
    )
    return [
        creator.create(
            REQUIREMENT_REVISION_RECORDED,
            RequirementRevisionPayload(
                requirement_id=command.requirement_id,
                version_id=command.version_id,
                record_id=command.record_id,
                classification=command.classification,
                change_classification=command.change_classification,
                requires_authority=command.requires_authority,
                new_behavior=command.new_behavior,
                behavior_change=command.behavior_change,
                semantic_change=command.semantic_change,
                validation_strengthening=command.validation_strengthening,
                active=True if command.active is None else command.active,
                previous_version_id=command.previous_version_id,
            ),
        )
    ]


def handle_record_support_evidence(
    command: RecordSupportEvidenceCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(
        context, assign_position=False, causation_id="record_support_evidence"
    )
    version_id = command.requirement_version_id or projection["active_requirement_versions"].get(
        command.requirement_id
    )
    if version_id is None:
        return [
            _command_rejected(
                creator,
                "record_support_evidence",
                f"unknown active requirement version: {command.requirement_id}",
            )
        ]
    return [
        creator.create(
            SUPPORT_EVIDENCE_RECORDED,
            SupportEvidencePayload(
                support_id=command.support_id,
                evidence_id=command.evidence_id,
                requirement_id=command.requirement_id,
                requirement_version_id=version_id,
                status="active" if command.status is None else command.status,
                stale_reason=command.stale_reason,
                confidence=command.confidence,
            ),
        )
    ]


def _decision_event_values(command: DecisionCommandFields) -> dict[str, JsonValue]:
    return {
        "node_id": command.node_id,
        "decider": command.decider,
        "scope": command.scope,
        "expires_at": command.expires_at,
        "reason": command.reason,
        "record_id": command.record_id,
        "decision": getattr(command, "decision"),
    }


def _decision_output_record(
    projection: GraphProjection,
    node_id: str,
    event_payload: dict[str, Any],
    decision_type: str,
) -> dict[str, Any] | None:
    node_kind = projection["node_kinds"].get(node_id)
    if decision_type == "authority" or node_kind == "authority_request":
        record_type, port, schema, record_model = (
            "authority_decision",
            "authority_decision",
            "AuthorityDecision",
            AuthorityDecisionRecord,
        )
    elif decision_type == "approval" or node_kind in {"gate", "human_gate"}:
        record_type, port, schema, record_model = (
            "decision_record",
            "decision_record",
            "DecisionRecord",
            DecisionRecord,
        )
    else:
        return None
    record_id = event_payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = f"{record_type}-{node_id}"
    value = {
        "decision": event_payload.get("decision"),
        "decision_type": decision_type,
        "decider": event_payload.get("decider"),
        "scope": event_payload.get("scope"),
        "expires_at": event_payload.get("expires_at"),
        "reason": event_payload.get("reason"),
    }
    return record_model.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": record_type,
            "producer_node_id": node_id,
            "port": port,
            "schema": schema,
            "value": {key: entry for key, entry in value.items() if entry is not None},
        }
    ).model_dump(mode="json")


def _record_selector_aliases(record_payload: dict[str, Any]) -> set[str]:
    if record_payload.get("record_kind") == "verification":
        return {"verification_result"}
    if record_payload.get("record_kind") == "file_state":
        return {"accepted_file_state", "file_state"}
    return set()


def _release_active_node_leases(
    projection: GraphProjection, node_id: str, creator: TypedEventCreator
) -> list[HydratedEvent]:
    output: list[HydratedEvent] = []
    for lease_id, lease in sorted(projection["leases"].items()):
        if lease.get("node_id") != node_id or lease.get("state") not in {"active", "suspended"}:
            continue
        generation = lease.get("generation")
        if not isinstance(generation, int):
            continue
        output.append(
            creator.create(
                LEASE_RELEASED,
                LeaseReleasedPayload(
                    node_id=node_id,
                    lease_id=lease_id,
                    generation=generation,
                ),
            )
        )
    return output


RAISE_APPEAL = CommandSpecification("raise_appeal", RaiseAppealCommand, handle_raise_appeal)
RECORD_DECISION = CommandSpecification(
    "record_decision", RecordDecisionCommand, handle_record_decision
)
RECORD_REQUIREMENT_REVISION = CommandSpecification(
    "record_requirement_revision",
    RecordRequirementRevisionCommand,
    handle_record_requirement_revision,
)
RECORD_SUPPORT_EVIDENCE = CommandSpecification(
    "record_support_evidence", RecordSupportEvidenceCommand, handle_record_support_evidence
)


POLICY_COMMAND_SPECIFICATIONS = (
    RAISE_APPEAL,
    RECORD_DECISION,
    RECORD_REQUIREMENT_REVISION,
    RECORD_SUPPORT_EVIDENCE,
)
COMMAND_SPECIFICATIONS = (*CALLBACK_COMMAND_SPECIFICATIONS, *POLICY_COMMAND_SPECIFICATIONS)


__all__ = [
    "ACKNOWLEDGE_START",
    "CALLBACK_COMMAND_SPECIFICATIONS",
    "COMMAND_SPECIFICATIONS",
    "SUBMIT_CALLBACK",
    "AcknowledgeStartCommand",
    "SubmitCallbackCommand",
    "handle_raise_appeal",
    "handle_record_cleanup_applied",
    "handle_record_decision",
    "handle_record_gatekeeper_verdicts",
    "handle_record_requirement_revision",
    "handle_record_support_evidence",
    "apply_callback_effects",
    "apply_acknowledge_start_effects",
]


def lease_node_id(projection: GraphProjection, lease_id: str) -> str | None:
    lease = projection["leases"].get(lease_id)
    if lease is None:
        return None
    node_id = lease.get("node_id")
    return node_id if isinstance(node_id, str) else None


def output_record_provenance_conflict(
    request: CallbackRequest, expected_producer_node_id: str
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None
    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        producer_node_id = record_payload.get("producer_node_id", expected_producer_node_id)
        if producer_node_id != expected_producer_node_id:
            return (
                "output record producer_node_id does not match lease node "
                f"at index {index}: {producer_node_id} != {expected_producer_node_id}"
            )
        if record_payload.get("record_kind") == "file_state":
            node_id = record_payload.get("node_id", expected_producer_node_id)
            if node_id != expected_producer_node_id:
                return (
                    "file_state record node_id does not match lease node "
                    f"at index {index}: {node_id} != {expected_producer_node_id}"
                )
    return None


def file_state_rejected_conflict(
    request: CallbackRequest, expected_producer_node_id: str
) -> str | None:
    rejection = request.payload.get("file_state_rejected") if request.payload is not None else None
    if not isinstance(rejection, dict):
        return None
    rejection_payload = cast(dict[str, Any], rejection)
    node_id = rejection_payload.get("node_id", expected_producer_node_id)
    if node_id != expected_producer_node_id:
        return f"file_state_rejected node_id does not match lease node: {node_id} != {expected_producer_node_id}"
    producer_node_id = rejection_payload.get("producer_node_id", expected_producer_node_id)
    if producer_node_id != expected_producer_node_id:
        return (
            "file_state_rejected producer_node_id does not match lease node: "
            f"{producer_node_id} != {expected_producer_node_id}"
        )
    return None


def file_state_authority_conflict(
    projection: GraphProjection, request: CallbackRequest
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None
    lease = projection["leases"].get(request.lease_id)
    if lease is None:
        return None
    node_id = lease_node_id(projection, request.lease_id) or request.node_id
    if projection["node_kinds"].get(node_id) != "worker":
        return None
    raw_claims = lease.get("resource_claims", [])
    if not isinstance(raw_claims, list):
        raw_claims = []
    write_claims: list[ResourceClaim] = [
        _claim_from_dict(raw_claim) for raw_claim in cast(list[Any], raw_claims)
    ]
    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        if record_payload.get("record_kind") != "file_state":
            continue
        unauthorized = [
            path
            for path in _file_state_changed_paths(record_payload)
            if not _repo_write_claim_covers_path(write_claims, path)
        ]
        if unauthorized:
            return (
                f"file_state path outside lease write authority at index {index}: {unauthorized[0]}"
            )
    return None


def file_state_rejected_events(
    request: CallbackRequest, creator: TypedEventCreator
) -> list[HydratedEvent]:
    rejection = request.payload.get("file_state_rejected") if request.payload is not None else None
    if not isinstance(rejection, dict):
        return []
    payload = dict(cast(dict[str, Any], rejection))
    payload.setdefault("node_id", request.node_id)
    payload.setdefault("run_id", request.run_id)
    payload.setdefault("execution_id", request.execution_id)
    payload.setdefault("lease_id", request.lease_id)
    payload.setdefault("lease_generation", request.lease_generation)
    payload.setdefault("base_snapshot_id", request.base_snapshot_id)
    return [creator.create(FILE_STATE_REJECTED, FileStateRejectedPayload.model_validate(payload))]


def output_record_contract_conflict(
    projection: GraphProjection, request: CallbackRequest, expected_producer_node_id: str
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None
    typed_raw_records = cast(list[Any], raw_records)
    file_state_records = _same_callback_file_state_records(
        typed_raw_records, expected_producer_node_id
    )
    node_kind = projection["node_kinds"].get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = projection["node_roles"].get(expected_producer_node_id)
    typed_role = node_role if isinstance(node_role, str) else None
    for index, raw_record in enumerate(typed_raw_records):
        if not isinstance(raw_record, dict):
            return f"malformed output record at index {index}"
        record_payload = dict(cast(dict[str, Any], raw_record))
        if record_payload.get("record_kind") == "file_state":
            record_payload.setdefault("port", "file_state")
            record_payload.setdefault("record_type", "file_state")
        if record_payload.get("record_kind") == "verification":
            record_payload.setdefault("port", "verification_report")
        record_run_id = record_payload.get("run_id")
        if record_run_id is not None and record_run_id != request.run_id:
            return f"output record at index {index} run_id does not match callback run: {record_run_id}"
        if _is_candidate_record_payload(record_payload):
            record_payload = _candidate_record_payload_for_validation(
                record_payload, expected_producer_node_id
            )
            conflict = _candidate_file_state_citation_conflict(
                record_payload,
                _file_state_record_ids_for_candidate(record_payload, file_state_records),
                index,
            )
            if conflict is not None:
                return conflict
        if _is_check_result_record_payload(record_payload):
            record_payload = _check_result_record_payload_for_validation(
                record_payload, expected_producer_node_id
            )
            conflict = _evaluated_record_citation_conflict(
                projection, expected_producer_node_id, record_payload, index
            )
            if conflict is not None:
                return conflict
        error = validate_output_record(
            node_kind=node_kind, node_role=typed_role, record_payload=record_payload, index=index
        )
        if error is not None:
            return error
        try:
            if _is_candidate_record_payload(record_payload):
                CandidateRecord.model_validate(record_payload)
            elif _is_check_result_record_payload(record_payload):
                CheckResultRecord.model_validate(record_payload)
            elif _is_verification_report_record_payload(record_payload):
                _parse_verification_report_record(record_payload, expected_producer_node_id)
            elif _is_analysis_summary_record_payload(record_payload):
                AnalysisSummaryRecord.model_validate(
                    _analysis_summary_record_payload_for_validation(
                        record_payload, expected_producer_node_id
                    )
                )
            elif _is_artifact_reference_record_payload(record_payload):
                ArtifactReferenceRecord.model_validate(
                    _artifact_reference_record_payload_for_validation(
                        record_payload, expected_producer_node_id
                    )
                )
        except ValueError as exc:
            if _is_check_result_record_payload(record_payload):
                kind = "check_result"
            elif _is_candidate_record_payload(record_payload):
                kind = "candidate"
            elif _is_analysis_summary_record_payload(record_payload):
                kind = "analysis_summary"
            else:
                kind = "output"
            return f"{kind} record at index {index} is invalid: {exc}"
    return None


def verification_record_conflict(
    projection: GraphProjection, request: CallbackRequest, expected_producer_node_id: str
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None
    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        if not _is_verification_report_record_payload(record_payload):
            continue
        try:
            record = _parse_verification_report_record(record_payload, expected_producer_node_id)
        except ValueError as exc:
            return f"verification record at index {index} is invalid: {exc}"
        if projection["node_kinds"].get(expected_producer_node_id) != "verifier":
            return f"verification record at index {index} was not produced by a verifier"
        if not _candidate_is_bound_to_verifier(
            projection, expected_producer_node_id, record.candidate_id
        ):
            return f"verification record candidate_id at index {index} is not bound to verifier input: {record.candidate_id}"
        if not record.value.grades:
            return f"verification record at index {index} missing grades"
        conflict = _evaluated_record_citation_conflict(
            projection, expected_producer_node_id, record.model_dump(mode="json"), index
        )
        if conflict is not None:
            return conflict
    return None


def required_output_record_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    *,
    successful_completion: bool,
) -> str | None:
    if not successful_completion:
        return None
    node_kind = projection["node_kinds"].get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = projection["node_roles"].get(expected_producer_node_id)
    contract = DEFAULT_NODE_CONTRACTS.contract_for(
        node_kind, node_role if isinstance(node_role, str) else None
    )
    if contract is None:
        return f"output records produced by unknown node type: {node_kind}"
    required_ports = {port.name for port in contract.output_ports.values() if port.required}
    raw_records: list[Any] = (
        cast(list[Any], request.payload.get("output_records"))
        if request.payload is not None and isinstance(request.payload.get("output_records"), list)
        else []
    )
    produced_ports = {
        port
        for raw_record in raw_records
        if isinstance(raw_record, dict)
        for port in [_output_record_contract_port(contract, cast(dict[str, Any], raw_record))]
        if port is not None
    }
    missing = sorted(required_ports - produced_ports)
    if missing:
        return f"node completion missing required output record ports: {', '.join(missing)}"
    return None


def planner_session_state_event(
    projection: GraphProjection,
    node_id: str,
    state: str,
    lease_generation: int,
    creator: TypedEventCreator,
) -> HydratedEvent | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = projection["planner_sessions"].values.get(node_id)
    if not isinstance(session_id, str):
        return None
    return creator.create(
        SESSION_STATE_CHANGED,
        PlannerSessionStateChangedPayload(
            session_id=session_id,
            state=state,
            node_id=node_id,
            lease_generation=lease_generation,
            carryover_record_id=_session_carryover_record_id(projection, node_id),
        ),
    )


def _typed_input_bound_events_for_record(
    projection: GraphProjection,
    producer_node_id: str,
    port: str,
    record_id: str,
    record_payload: dict[str, Any],
    creator: TypedEventCreator,
    aliases: set[str] | None = None,
) -> list[HydratedEvent]:
    output: list[HydratedEvent] = []
    for edge in projection["edges"].values():
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        from_node_id = edge.get("from_node_id")
        if edge.get("from_port") != port:
            continue
        if from_node_id != producer_node_id:
            if from_node_id != "*":
                continue
            expected_kind = edge.get("from_node_kind")
            expected_role = edge.get("from_node_role")
            if (
                isinstance(expected_kind, str)
                and projection["node_kinds"].get(producer_node_id) != expected_kind
            ) or (
                isinstance(expected_role, str)
                and projection["node_roles"].get(producer_node_id) != expected_role
            ):
                continue

        if not record_selector_matches(
            edge.get("accepted_record_selector"), record_payload, aliases
        ):
            continue
        edge_id, to_node_id, to_port = (
            edge.get("edge_id"),
            edge.get("to_node_id"),
            edge.get("to_port"),
        )
        if not all(isinstance(value, str) for value in (edge_id, to_node_id, to_port)):
            continue
        payload = _input_bound_payload_for_record(
            projection,
            edge,
            edge_id=cast(str, edge_id),
            to_node_id=cast(str, to_node_id),
            to_port=cast(str, to_port),
            record_id=record_id,
            record_payload=record_payload,
        )
        if payload is not None:
            output.append(creator.create(INPUT_BOUND, InputBoundPayload.model_validate(payload)))
    return output


def accepted_output_record_events(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return []
    file_state_records = _same_callback_file_state_records(
        cast(list[Any], raw_records), expected_producer_node_id
    )
    output: list[HydratedEvent] = []
    for raw_record in cast(list[Any], raw_records):
        if not isinstance(raw_record, dict):
            continue
        payload = dict(cast(dict[str, Any], raw_record))
        payload.setdefault("producer_node_id", expected_producer_node_id)
        if payload.get("record_kind") == "file_state":
            payload.setdefault("port", "file_state")
            payload.setdefault("record_type", "file_state")
            payload.setdefault("schema", "FileStateRecord")
            try:
                record = FileStateRecord.model_validate(payload)
            except ValueError:
                continue
            record_payload = record.model_dump(mode="json")
            record_payload["record_type"] = "file_state"
            output.extend(
                [
                    creator.create(
                        OUTPUT_RECORD_ACCEPTED,
                        OutputRecordAcceptedPayload.model_validate({"record": record_payload}),
                    ),
                    creator.create(
                        FILE_STATE_ACCEPTED, StrictFileStateRecord.model_validate(record_payload)
                    ),
                ]
            )
            output.extend(
                _typed_input_bound_events_for_record(
                    projection,
                    record.producer_node_id or expected_producer_node_id,
                    record.port,
                    record.record_id,
                    record_payload,
                    creator,
                    {"accepted_file_state", "file_state"},
                )
            )
            continue
        if _is_verification_report_record_payload(payload):
            _add_evaluated_record_citations(payload, projection, expected_producer_node_id)
            try:
                record = _parse_verification_report_record(payload, expected_producer_node_id)
            except ValueError:
                continue
            if record.outcome not in {"passed", "failed"}:
                continue
            record_payload = record.model_dump(mode="json")
            task_region_id = projection["node_task_regions"].get(expected_producer_node_id)
            output.extend(
                [
                    creator.create(
                        OUTPUT_RECORD_ACCEPTED,
                        OutputRecordAcceptedPayload.model_validate({"record": record_payload}),
                    ),
                    creator.create(
                        VERIFICATION_PASSED if record.outcome == "passed" else VERIFICATION_FAILED,
                        VerificationOutcomePayload(
                            node_id=request.node_id,
                            verifier_node_id=expected_producer_node_id,
                            candidate_id=record.candidate_id,
                            outcome=record.outcome,
                            record_id=record.record_id,
                            task_region_id=task_region_id
                            if isinstance(task_region_id, str)
                            else None,
                            evaluated_record_ids=record.evaluated_record_ids,
                            evidence=record_payload.get("evidence"),
                        ),
                    ),
                ]
            )
            output.extend(
                _typed_input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    record_payload,
                    creator,
                    {"verification_result"},
                )
            )
            continue
        if _is_check_result_record_payload(payload):
            _add_evaluated_record_citations(payload, projection, expected_producer_node_id)
            payload = _check_result_record_payload_for_validation(
                payload, expected_producer_node_id
            )
            record_type = CheckResultRecord
        elif _is_candidate_record_payload(payload):
            _add_candidate_file_state_citations(
                payload, _file_state_record_ids_for_candidate(payload, file_state_records)
            )
            payload = _candidate_record_payload_for_validation(payload, expected_producer_node_id)
            record_type = CandidateRecord
        elif _is_analysis_summary_record_payload(payload):
            payload = _analysis_summary_record_payload_for_validation(
                payload, expected_producer_node_id
            )
            record_type = AnalysisSummaryRecord
        elif _is_artifact_reference_record_payload(payload):
            payload = _artifact_reference_record_payload_for_validation(
                payload, expected_producer_node_id
            )
            record_type = ArtifactReferenceRecord
        else:
            record_type = OutputRecord
        try:
            record = record_type.model_validate(payload)
        except ValueError:
            continue
        record_payload = record.model_dump(mode="json")
        output.append(
            creator.create(
                OUTPUT_RECORD_ACCEPTED,
                OutputRecordAcceptedPayload.model_validate({"record": record_payload}),
            )
        )
        output.extend(
            _typed_input_bound_events_for_record(
                projection,
                record.producer_node_id,
                record.port,
                record.record_id,
                record_payload,
                creator,
            )
        )
    return output


def apply_callback_effects(
    projection: GraphProjection,
    events: list[HydratedEvent],
    command: SubmitCallbackCommand,
    run_id: str,
    creator: TypedEventCreator,
    catalog: GraphCatalog,
) -> list[HydratedEvent]:
    raw_callback_payload = command.payload
    if raw_callback_payload is None:
        callback_payload = (
            {"payload_hash": command.payload_hash} if command.payload_hash is not None else None
        )
    elif isinstance(raw_callback_payload, dict):
        callback_payload = raw_callback_payload
    else:
        callback_payload = {"payload": raw_callback_payload}
    # Mutating-ness is derived from the callback's actual effects, never trusted
    # from the caller's flag: completing the node or carrying output records IS
    # a mutation, so a callback claiming is_mutating=False cannot bypass the
    # running-state and suspended-lease guards.
    has_effects = command.complete_node or bool((callback_payload or {}).get("output_records"))
    request = CallbackRequest(
        run_id=run_id,
        node_id=command.node_id,
        execution_id=command.execution_id,
        lease_id=command.lease_id,
        lease_generation=command.lease_generation,
        base_snapshot_id=command.base_snapshot_id,
        observed_graph_position=command.observed_graph_position,
        idempotency_key=command.idempotency_key,
        payload=callback_payload,
        is_mutating=command.is_mutating or has_effects,
    )
    result = validate_callback(request, projection, events)

    def rejected_payload(reason: str) -> CallbackRejectedPayload:
        return CallbackRejectedPayload(
            node_id=request.node_id,
            lease_id=request.lease_id,
            lease_generation=request.lease_generation,
            idempotency_key=request.idempotency_key,
            payload=request.payload,
            reason=reason,
        )

    if result.outcome == CallbackOutcome.REJECTED_STALE:
        return [creator.create(CALLBACK_REJECTED_STALE, rejected_payload(result.reason))]
    if result.outcome in {
        CallbackOutcome.REJECTED_CONFLICT,
        CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
    }:
        return [creator.create(CALLBACK_REJECTED_CONFLICT, rejected_payload(result.reason))]
    if result.outcome == CallbackOutcome.DUPLICATE_IDEMPOTENT:
        return [
            creator.create(
                CALLBACK_DUPLICATE_RETURNED,
                CallbackDuplicateReturnedPayload(
                    node_id=request.node_id,
                    lease_id=request.lease_id,
                    lease_generation=request.lease_generation,
                    idempotency_key=request.idempotency_key,
                    payload=request.payload,
                    reason=result.reason,
                    prior_result=result.prior_result,
                ),
            )
        ]

    leased_node_id = lease_node_id(projection, request.lease_id)
    expected_producer_node_id = leased_node_id or request.node_id
    if leased_node_id is not None and request.node_id != leased_node_id:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(
                    "callback node_id does not match lease node: "
                    f"{request.node_id} != {leased_node_id}"
                ),
            )
        ]
    provenance_conflict = output_record_provenance_conflict(request, expected_producer_node_id)
    if provenance_conflict is not None:
        return [creator.create(CALLBACK_REJECTED_CONFLICT, rejected_payload(provenance_conflict))]
    file_state_rejection_conflict = file_state_rejected_conflict(
        request,
        expected_producer_node_id,
    )
    if file_state_rejection_conflict is not None:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(file_state_rejection_conflict),
            )
        ]
    authority_conflict = file_state_authority_conflict(
        projection,
        request,
    )
    if authority_conflict is not None:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(authority_conflict),
            )
        ]
    verification_conflict = verification_record_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if verification_conflict is not None:
        return [creator.create(CALLBACK_REJECTED_CONFLICT, rejected_payload(verification_conflict))]
    output_contract_conflict = output_record_contract_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if output_contract_conflict is not None:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(output_contract_conflict),
            )
        ]
    missing_output_conflict = required_output_record_conflict(
        projection,
        request,
        expected_producer_node_id,
        successful_completion=(command.complete_node and command.new_state == "completed"),
    )
    if missing_output_conflict is not None:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(missing_output_conflict),
            )
        ]

    accepted = creator.create(
        CALLBACK_ACCEPTED,
        CallbackAcceptedPayload(
            node_id=request.node_id,
            lease_id=request.lease_id,
            lease_generation=request.lease_generation,
            idempotency_key=request.idempotency_key,
            payload=request.payload,
            reason=result.reason,
        ),
    )
    output: list[HydratedEvent] = [accepted]
    output.extend(file_state_rejected_events(request, creator))
    output.extend(
        accepted_output_record_events(
            projection,
            request,
            expected_producer_node_id,
            creator,
        )
    )
    if command.complete_node:
        output.append(
            creator.create(
                NODE_STATE_CHANGED,
                NodeStateChangedPayload(
                    node_id=request.node_id,
                    new_state=command.new_state,
                    trigger="callback_accepted",
                ),
            )
        )
        output.append(
            creator.create(
                LEASE_RELEASED,
                LeaseReleasedPayload(
                    node_id=request.node_id,
                    lease_id=request.lease_id,
                    generation=request.lease_generation,
                ),
            )
        )
        session_event = planner_session_state_event(
            projection,
            request.node_id,
            "suspended",
            request.lease_generation,
            creator,
        )
        if session_event is not None:
            output.append(session_event)
    future_output = list(output)
    output.extend(source_repair_events(projection, events, future_output, catalog, creator))
    return output


def source_repair_events(
    projection: GraphProjection,
    events: list[HydratedEvent],
    source_events: list[HydratedEvent],
    catalog: GraphCatalog,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    """Create typed callback/patch recovery events from already-created effects."""

    accepted_records: list[StrictOutputRecordBase] = []
    for event in source_events:
        if event.event_type != "output_record_accepted":
            continue
        if not isinstance(event.payload, OutputRecordAcceptedPayload):
            raise TypeError("output_record_accepted event has an unexpected payload type")
        record = cast(Any, event.payload.record)
        if not isinstance(record, StrictOutputRecordBase):
            raise TypeError("output_record_accepted event has an unexpected record type")
        accepted_records.append(record)
    repair_node_ids = {
        node_id for event in source_events for node_id in _source_repair_node_ids(event)
    }
    if not accepted_records and not repair_node_ids:
        return []

    scoped_projection = project_with_events(projection, source_events, catalog)
    active_leases = active_lease_node_ids(scoped_projection)
    output: list[HydratedEvent] = []
    for record in accepted_records:
        if isinstance(record, StrictCheckResultRecord):
            if record.value.status in {"passed", "pass", "ok"}:
                output.extend(
                    passed_check_terminalization_events(
                        scoped_projection,
                        active_leases,
                        creator,
                        check_node_ids={record.producer_node_id},
                    )
                )
            else:
                output.extend(
                    failed_check_recovery_events(
                        scoped_projection,
                        active_leases,
                        creator,
                        record_ids={record.record_id},
                    )
                )
        elif isinstance(record, StrictVerificationReportRecord):
            verdict = record.outcome or record.verdict or record.value.outcome
            if verdict in {"passed", "pass"}:
                output.extend(
                    passed_verification_terminalization_events(
                        scoped_projection,
                        active_leases,
                        creator,
                        record_ids={record.record_id},
                    )
                )
            elif verdict in {"failed", "fail"}:
                output.extend(
                    failed_verification_recovery_events(
                        scoped_projection,
                        active_leases,
                        creator,
                        record_ids={record.record_id},
                    )
                )
    if repair_node_ids:
        output.extend(
            no_successor_recovery_terminal_failure_events(
                scoped_projection,
                active_leases,
                creator,
                recovery_node_ids=repair_node_ids,
            )
        )
    return dedupe_repair_events(output)


def _source_repair_node_ids(event: HydratedEvent) -> tuple[str, ...]:
    if event.event_type == "graph_patch_accepted":
        if not isinstance(event.payload, GraphPatchAcceptedPayload):
            raise TypeError("graph_patch_accepted event has an unexpected payload type")
        return (event.payload.proposed_by_node_id,)
    if event.event_type == "node_state_changed":
        if not isinstance(event.payload, NodeStateChangedPayload):
            raise TypeError("node_state_changed event has an unexpected payload type")
        if event.payload.new_state == "completed":
            return (event.payload.node_id,)
    return ()


def apply_acknowledge_start_effects(
    projection: GraphProjection,
    command: AcknowledgeStartCommand,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    node_id = command.node_id
    lease_id = command.lease_id
    lease_generation = command.lease_generation
    execution_id = command.execution_id

    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(creator, "acknowledge_start", "unknown lease")]
    if lease.get("state") != "active":
        return [_command_rejected(creator, "acknowledge_start", "lease not active")]
    if lease.get("node_id") != node_id:
        return [_command_rejected(creator, "acknowledge_start", "node_incompatible")]
    if lease.get("generation") != lease_generation:
        return [_command_rejected(creator, "acknowledge_start", "generation_incompatible")]
    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str) and lease_execution_id != execution_id:
        return [_command_rejected(creator, "acknowledge_start", "execution_incompatible")]

    return [
        creator.create(
            NODE_STATE_CHANGED,
            NodeStateChangedPayload(
                node_id=node_id,
                new_state="running",
                trigger="runtime_start_acknowledged",
                prompt_summary=command.prompt_summary,
            ),
        )
    ]


# Callback-local record and binding support.
def _file_state_changed_paths(record_payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for field in (
        "tracked",
        "untracked",
        "ignored",
        "external",
        "classifications",
        "residue",
        "rejected_paths",
    ):
        raw_entries = record_payload.get(field)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            if entry.get("classification") == "tool_cache":
                continue
            path = entry.get("path")
            if isinstance(path, str) and path not in paths:
                paths.append(path)
    return paths


def _repo_write_claim_covers_path(write_claims: list[ResourceClaim], path: str) -> bool:
    if not _file_state_path_is_repo_relative(path):
        return False
    requested = ResourceClaim(mode="read", scope="repo", paths=[path])
    return any(
        _claim_is_repo_write(claim) and claims_conflict(requested, claim) for claim in write_claims
    )


def _claim_is_repo_write(claim: ResourceClaim) -> bool:
    return claim.mode == "write" and claim.scope == "repo" and _claim_paths_are_repo_relative(claim)


def _claim_paths_are_repo_relative(claim: ResourceClaim) -> bool:
    return all(_file_state_path_is_repo_relative(path) for path in claim.paths)


def _file_state_path_is_repo_relative(path: str) -> bool:
    if path == "":
        return False
    if path.startswith("/"):
        return False
    normalized = posixpath.normpath(path)
    return normalized != ".." and not normalized.startswith("../")


def _output_record_contract_port(
    contract: Any,
    record_payload: dict[str, Any],
) -> str | None:
    record_payload = dict(record_payload)
    if record_payload.get("record_kind") == "file_state":
        record_payload.setdefault("port", "file_state")
    if record_payload.get("record_kind") == "verification":
        record_payload.setdefault("port", "verification_report")
    port = record_payload.get("port")
    if not isinstance(port, str):
        return None
    if output_port_contract(contract, port) is None:
        return None
    if port == "verification_result":
        return "verification_report"
    return port


def _canonicalize_verification_record_port(record_payload: dict[str, Any]) -> None:
    if record_payload.get("port") == "verification_result":
        record_payload["port"] = "verification_report"


def _candidate_is_bound_to_verifier(
    projection: GraphProjection,
    verifier_node_id: str,
    candidate_id: str,
) -> bool:
    binding = projection["input_bindings"].get(verifier_node_id, {}).get("candidate_under_test")
    if binding is None:
        return False
    record_ids = binding.get("record_ids")
    return isinstance(record_ids, list) and candidate_id in record_ids


def _candidate_id_from_payload(payload: dict[str, Any] | FileStateRecord) -> str | None:
    if isinstance(payload, FileStateRecord):
        return payload.candidate_id
    candidate_id = payload.get("candidate_id")
    if isinstance(candidate_id, str):
        return candidate_id
    membership = payload.get("membership")
    if isinstance(membership, dict):
        value = cast(dict[str, Any], membership).get("candidate_id")
        if isinstance(value, str):
            return value
    return None


def _is_check_result_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "check_result"
        or payload.get("port") == "check_result"
        or payload.get("record_kind") == "check_result"
    )


def _is_verification_report_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_kind") == "verification"
        or payload.get("record_type") == "verification_report"
        or payload.get("port") in {"verification_report", "verification_result"}
        or payload.get("schema") == "VerificationReport"
    )


def _verification_report_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output["record_kind"] = "verification"
    output.setdefault("record_type", "verification_report")
    output.setdefault("port", "verification_report")
    output.setdefault("schema", "VerificationReport")
    return output


def _parse_verification_report_record(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> VerificationReportRecord:
    output = _verification_report_record_payload_for_validation(payload, expected_producer_node_id)
    _canonicalize_verification_record_port(output)
    return VerificationReportRecord.model_validate(output)


def _check_result_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "check_result")
    return output


def _is_candidate_record_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") == "candidate" or payload.get("port") == "candidate"


def _candidate_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "candidate")
    record_id = output.get("record_id")
    if isinstance(record_id, str) and record_id:
        output.setdefault("candidate_id", record_id)
    return output


def _is_analysis_summary_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "analysis_summary"
        or payload.get("port") in ANALYSIS_SUMMARY_PORTS
    )


def _analysis_summary_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "analysis_summary")
    return output


def _is_artifact_reference_record_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") == "artifact_reference" or payload.get("port") in {
        "artifact_reference",
        "artifact",
    }


def _artifact_reference_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_kind", "graph_record")
    output.setdefault("record_type", "artifact_reference")
    output.setdefault("schema", "ArtifactReference")
    output.setdefault("port", "artifact_reference")
    return output


def _same_callback_file_state_records(
    raw_records: list[Any],
    expected_producer_node_id: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        if (
            record_payload.get("record_kind") != "file_state"
            and record_payload.get("port") != "file_state"
        ):
            continue
        producer_node_id = record_payload.get("producer_node_id", expected_producer_node_id)
        if producer_node_id != expected_producer_node_id:
            continue
        record_id = record_payload.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        output.append(record_payload)
    return output


def _file_state_record_ids_for_candidate(
    candidate_payload: dict[str, Any],
    file_state_records: list[dict[str, Any]],
) -> list[str]:
    candidate_id = _candidate_id_from_payload(candidate_payload)
    output: list[str] = []
    for record in file_state_records:
        record_candidate_id = _candidate_id_from_payload(record)
        if (
            candidate_id is not None
            and record_candidate_id is not None
            and record_candidate_id != candidate_id
        ):
            continue
        record_id = record.get("record_id")
        if isinstance(record_id, str):
            output.append(record_id)
    return _unique_record_ids(output)


def _candidate_file_state_citation_conflict(
    record_payload: dict[str, Any],
    expected_file_state_ids: list[str],
    index: int,
) -> str | None:
    if not expected_file_state_ids:
        return None
    conflict = _explicit_record_ids_conflict(
        record_payload,
        "file_state_record_ids",
        expected_file_state_ids,
    )
    if conflict is not None:
        return f"output record at index {index} {conflict}"
    file_state_record_id = record_payload.get("file_state_record_id")
    if file_state_record_id is not None:
        if (
            not isinstance(file_state_record_id, str)
            or [file_state_record_id] != expected_file_state_ids
        ):
            return (
                "output record at index "
                f"{index} file_state_record_id does not match same-callback file-state records: "
                f"{file_state_record_id}"
            )
    return None


def _add_candidate_file_state_citations(
    record_payload: dict[str, Any],
    file_state_record_ids: list[str],
) -> None:
    if not file_state_record_ids:
        return
    citations = {"file_state_record_ids": file_state_record_ids}
    record_payload.setdefault("file_state_record_ids", list(file_state_record_ids))
    if len(file_state_record_ids) == 1:
        record_payload.setdefault("file_state_record_id", file_state_record_ids[0])
    _merge_record_citations(record_payload, "value", citations)
    _merge_record_citations(record_payload, "provenance", citations)


def _evaluated_record_citation_conflict(
    projection: GraphProjection,
    node_id: str,
    record_payload: dict[str, Any],
    index: int,
) -> str | None:
    citations = _evaluated_record_citations(projection, node_id)
    for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
        expected = citations.get(field)
        if expected is None:
            continue
        conflict = _explicit_record_ids_conflict(record_payload, field, expected)
        if conflict is not None:
            return f"output record at index {index} {conflict}"
    candidate_record_id = record_payload.get("candidate_record_id")
    expected_candidates = citations.get("candidate_record_ids")
    if candidate_record_id is not None and expected_candidates is not None:
        if not isinstance(candidate_record_id, str) or [candidate_record_id] != expected_candidates:
            return (
                "output record at index "
                f"{index} candidate_record_id does not match bound candidate records: "
                f"{candidate_record_id}"
            )
    return None


def _explicit_record_ids_conflict(
    record_payload: dict[str, Any],
    field: str,
    expected: list[str],
) -> str | None:
    candidates: list[tuple[str, Any]] = [(field, record_payload.get(field))]
    value = record_payload.get("value")
    if isinstance(value, dict):
        candidates.append((f"value.{field}", cast(dict[str, Any], value).get(field)))
    evidence = record_payload.get("evidence")
    if isinstance(evidence, dict):
        candidates.append((f"evidence.{field}", cast(dict[str, Any], evidence).get(field)))
    provenance = record_payload.get("provenance")
    if isinstance(provenance, dict):
        candidates.append((f"provenance.{field}", cast(dict[str, Any], provenance).get(field)))

    for path, value in candidates:
        if value is None:
            continue
        if not isinstance(value, list):
            return f"{path} must be a list of record IDs"
        record_ids = [
            record_id for record_id in cast(list[Any], value) if isinstance(record_id, str)
        ]
        if record_ids != expected:
            return f"{path} does not match bound records: {record_ids} != {expected}"
    return None


def _add_evaluated_record_citations(
    record_payload: dict[str, Any],
    projection: GraphProjection,
    node_id: str,
) -> None:
    citations = _evaluated_record_citations(projection, node_id)
    if not citations:
        return
    for key, value in citations.items():
        record_payload.setdefault(key, list(value))
    candidate_ids = citations.get("candidate_record_ids")
    if candidate_ids is not None and len(candidate_ids) == 1:
        record_payload.setdefault("candidate_record_id", candidate_ids[0])
    _merge_record_citations(record_payload, "provenance", citations)
    if _is_verification_report_record_payload(record_payload):
        _merge_record_citations(record_payload, "evidence", citations)
    if _is_check_result_record_payload(record_payload):
        _merge_record_citations(record_payload, "value", citations)


def _merge_record_citations(
    record_payload: dict[str, Any],
    field: str,
    citations: dict[str, list[str]],
) -> None:
    existing = record_payload.get(field)
    if existing is None:
        record_payload[field] = {key: list(value) for key, value in citations.items()}
        return
    if not isinstance(existing, dict):
        return
    merged = dict(cast(dict[str, Any], existing))
    for key, value in citations.items():
        merged.setdefault(key, list(value))
    record_payload[field] = merged


def _evaluated_record_citations(
    projection: GraphProjection,
    node_id: str,
) -> dict[str, list[str]]:
    candidate_record_ids = _bound_record_ids_for_ports(
        projection,
        node_id,
        ("candidate_under_test", "candidate"),
    )
    file_state_record_ids = _bound_record_ids_for_ports(
        projection,
        node_id,
        ("file_state", "accepted_file_state"),
    )
    if candidate_record_ids:
        file_state_record_ids.extend(
            _file_state_record_ids_for_candidate_records(projection, candidate_record_ids)
        )
    output: dict[str, list[str]] = {}
    unique_candidate_record_ids = _unique_record_ids(candidate_record_ids)
    unique_file_state_record_ids = _unique_record_ids(file_state_record_ids)
    if unique_candidate_record_ids:
        output["candidate_record_ids"] = unique_candidate_record_ids
    if unique_file_state_record_ids:
        output["file_state_record_ids"] = unique_file_state_record_ids
    evaluated_record_ids = _unique_record_ids(
        [*unique_candidate_record_ids, *unique_file_state_record_ids]
    )
    if evaluated_record_ids:
        output["evaluated_record_ids"] = evaluated_record_ids
    return output


def _file_state_record_ids_for_candidate_records(
    projection: GraphProjection,
    candidate_record_ids: list[str],
) -> list[str]:
    wanted = set(candidate_record_ids)
    output: list[str] = []
    for candidates in projection["task_candidates"].values():
        for candidate in candidates:
            candidate_id = candidate.candidate_id
            if candidate_id not in wanted:
                continue
            output.extend(candidate.file_state_record_ids)
    if output:
        return _unique_record_ids(output)
    for record in projection["file_state_records"].values():
        candidate_id = _candidate_id_from_payload(record)
        if candidate_id in wanted:
            output.append(record.record_id)
    return _unique_record_ids(output)


def _bound_record_ids_for_ports(
    projection: GraphProjection,
    node_id: str,
    ports: tuple[str, ...],
) -> list[str]:
    bindings = projection["input_bindings"].get(node_id, {})
    output: list[str] = []
    for port in ports:
        binding = bindings.get(port)
        if binding is None:
            continue
        record_ids = binding.get("record_ids")
        if not isinstance(record_ids, list):
            continue
        output.extend(
            record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)
        )
    return _unique_record_ids(output)


def _unique_record_ids(record_ids: list[str]) -> list[str]:
    output: list[str] = []
    for record_id in record_ids:
        if record_id not in output:
            output.append(record_id)
    return output


def _input_bound_payload_for_record(
    projection: GraphProjection,
    edge: dict[str, Any],
    *,
    edge_id: str,
    to_node_id: str,
    to_port: str,
    record_id: str,
    record_payload: dict[str, Any],
) -> dict[str, Any] | None:
    existing_ids = _existing_bound_record_ids(projection, to_node_id, to_port)
    target_port = _target_port_contract_for_edge(projection, edge)
    policy = binding_policy_for_edge(edge, target_port)
    next_ids = merge_bound_record_ids(
        policy,
        existing_ids,
        [record_id],
        supersedes_record_id=record_payload.get("supersedes_record_id"),
    )
    if next_ids == existing_ids and existing_ids:
        return None

    payload: dict[str, Any] = {
        "edge_id": edge_id,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "record_ids": next_ids,
        "bound_at_position": 0,
    }
    if policy != "bind_first" or isinstance(edge.get("binding_policy"), str):
        payload["binding_policy"] = policy
    supersedes_record_id = record_payload.get("supersedes_record_id")
    if isinstance(supersedes_record_id, str):
        payload["supersedes_record_id"] = supersedes_record_id
    return payload


def _existing_bound_record_ids(
    projection: GraphProjection,
    to_node_id: str,
    to_port: str,
) -> list[str]:
    binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
    if binding is None:
        return []
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return [record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)]


def _target_port_contract_for_edge(
    projection: GraphProjection,
    edge: dict[str, Any],
) -> PortContract | None:
    to_node_id = edge.get("to_node_id")
    to_port = edge.get("to_port")
    if not isinstance(to_node_id, str) or not isinstance(to_port, str):
        return None
    target_kind = projection["node_kinds"].get(to_node_id)
    if target_kind is None:
        return None
    target_role = projection["node_roles"].get(to_node_id)
    target_contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if target_contract is None:
        return None
    return input_port_contract(target_contract, to_port)


def _session_carryover_record_id(projection: GraphProjection, node_id: str) -> str | None:
    binding = projection["input_bindings"].get(node_id, {}).get("session_carryover")
    if binding is None:
        return None
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list) or not record_ids:
        return None
    record_id = cast(list[Any], record_ids)[0]
    return record_id if isinstance(record_id, str) else None


def _is_chain_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "planner"
        and projection["node_roles"].get(node_id) == "planner"
    )


def _claim_from_dict(claim: Any) -> ResourceClaim:
    claim_payload = _resource_claim_payload(claim)
    mode = str(claim_payload.get("mode", "read"))
    scope = str(claim_payload.get("scope", "repo"))
    paths = (
        [str(path) for path in claim_payload.get("paths", [])]
        if isinstance(claim_payload.get("paths"), list)
        else []
    )
    # Self-healing normalization (also applied on replay of historic events): planners
    # sometimes put a repo-relative path prefix directly in `scope` instead of the
    # canonical scope="repo" + paths=[...] shape. For read/write claims (the only modes
    # whose scheduling/authority semantics key off `scope == "repo"`), fold a
    # path-shaped scope into `paths` so both the scheduler-conflict check and the
    # write-authority check (`_claim_is_repo_write`) see identical, correct semantics.
    # external/graph_write/review_write claims use `scope` for other purposes (or not at
    # all) and are left untouched.
    if mode in {"read", "write"} and scope not in ("repo", ""):
        if scope not in paths:
            paths = [*paths, scope]
        scope = "repo"
    return ResourceClaim(
        mode=mode,
        scope=scope,
        paths=paths,
        snapshot_id=cast(str | None, claim_payload.get("snapshot_id")),
        external_resource_key=cast(str | None, claim_payload.get("external_resource_key")),
        exclusive=bool(claim_payload.get("exclusive", False)),
    )


def _resource_claim_payload(claim: Any) -> dict[str, Any]:
    if hasattr(claim, "model_dump"):
        dumped = claim.model_dump(mode="json")
        if isinstance(dumped, dict):
            return cast(dict[str, Any], dumped)
    if isinstance(claim, dict):
        return dict(cast(dict[str, Any], claim))
    return {}
