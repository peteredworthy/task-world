"""Callback and output/evidence command handlers."""

from __future__ import annotations
from typing import Annotated, Any, Literal

from orchestrator.graph.callbacks import (
    CallbackOutcome,
    CallbackRequest,
    validate_callback,
)
from orchestrator.graph.models import (
    EventEnvelope,
)
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
from orchestrator.graph.commands.future_effects import require_future_effect
from orchestrator.graph.commands.event_creator import TypedEventCreator
from collections.abc import Callable

from pydantic import ConfigDict, Field, RootModel

from orchestrator.graph._commands import (
    Clock,
    IdGenerator,
    apply_record_cleanup_applied,
    apply_record_gatekeeper_verdicts,
    decision_output_record,
    input_bound_events_for_record,
    record_selector_aliases,
    release_active_node_leases,
    event_factory,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
    FutureCommandEffects,
)
from orchestrator.graph._commands import typed_topology_event
from orchestrator.graph.events.leases import LEASE_RELEASED
from orchestrator.graph._commands import make_strict_event
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
)
from orchestrator.graph.events.records import OUTPUT_RECORD_ACCEPTED
from orchestrator.graph.events.topology import INPUT_BOUND, NODE_CREATED, NODE_STATE_CHANGED


class RaiseAppealCommand(StrictPayload):
    node_id: str
    appeal_type: Literal["invalid_test"]
    appeal_node_id: str | None = None
    oversight_node_id: str | None = None
    candidate_id: str | None = None
    task_region_id: str | None = None
    lease_id: str | None = None


class ApprovalDecisionCommand(StrictPayload):
    decision_type: Literal["approval"]
    node_id: str
    decision: Literal["approved", "rejected", "deferred"]
    decider: JsonValue
    scope: dict[str, JsonValue] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None


class AuthorityDecisionCommand(StrictPayload):
    decision_type: Literal["authority"]
    node_id: str
    decision: Literal["granted", "denied", "deferred"]
    decider: JsonValue
    scope: dict[str, JsonValue] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None


class OversightDecisionCommand(StrictPayload):
    decision_type: Literal["oversight"]
    node_id: str
    decision: Literal["accepted", "rejected", "invalid_test_accepted"]
    decider: JsonValue
    scope: dict[str, JsonValue] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None


DecisionCommand = Annotated[
    ApprovalDecisionCommand | AuthorityDecisionCommand | OversightDecisionCommand,
    Field(discriminator="decision_type"),
]


class RecordDecisionCommand(RootModel[DecisionCommand]):
    model_config = ConfigDict(strict=True, frozen=True)

    def to_json(self) -> dict[str, JsonValue]:
        return self.root.to_json()


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
    output: list[EventEnvelope | HydratedEvent],
) -> list[EventEnvelope | HydratedEvent]:
    return [
        require_future_effect(event) if isinstance(event, EventEnvelope) else event
        for event in output
    ]


def handle_submit_callback_command(
    command: SubmitCallbackCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]:
    make_event = event_factory(
        context.run_id, SUBMIT_CALLBACK.name, context.clock, context.id_generator
    )
    output = apply_callback_effects(
        projection,
        list(events),
        command,
        context.run_id,
        make_event,
        TypedEventCreator(context, assign_position=False),
        context.future_effects,
    )
    return _require_future_outcomes(output)


def handle_acknowledge_start_command(
    command: AcknowledgeStartCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]:
    del events
    make_event = event_factory(
        context.run_id, ACKNOWLEDGE_START.name, context.clock, context.id_generator
    )
    return _require_future_outcomes(
        apply_acknowledge_start_effects(
            projection,
            command,
            make_event,
            TypedEventCreator(context, assign_position=False),
            context.future_effects,
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
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(context, assign_position=False)
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
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    decision_command = command.root
    creator = TypedEventCreator(context, assign_position=False)
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
    values = command.to_json()
    values.pop("decision_type")
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
    record = decision_output_record(
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
        make_event = event_factory(
            context.run_id, "record_decision", context.clock, context.id_generator
        )
        for event in input_bound_events_for_record(
            projection,
            decision_command.node_id,
            str(record["port"]),
            str(record["record_id"]),
            record,
            make_event,
            record_selector_aliases(record),
        ):
            output.append(creator.create(INPUT_BOUND, INPUT_BOUND.validate_payload(event.payload)))
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
    make_event = event_factory(
        context.run_id, "record_decision", context.clock, context.id_generator
    )
    for event in release_active_node_leases(projection, decision_command.node_id, make_event):
        output.append(
            creator.create(LEASE_RELEASED, LEASE_RELEASED.validate_payload(event.payload))
        )
    return output


def handle_record_gatekeeper_verdicts(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del clock
    del id_gen
    return apply_record_gatekeeper_verdicts(projection, payload, make_event)


def handle_record_requirement_revision(
    command: RecordRequirementRevisionCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del projection
    del events
    creator = TypedEventCreator(context, assign_position=False)
    return [
        creator.create(
            REQUIREMENT_REVISION_RECORDED,
            REQUIREMENT_REVISION_RECORDED.validate_payload(command.to_json()),
        )
    ]


def handle_record_support_evidence(
    command: RecordSupportEvidenceCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(context, assign_position=False)
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
            SUPPORT_EVIDENCE_RECORDED.validate_payload(
                {**command.to_json(), "requirement_version_id": version_id}
            ),
        )
    ]


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


def handle_record_cleanup_applied(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    del clock
    del id_gen
    return apply_record_cleanup_applied(projection, events, payload, make_event)


__all__ = [
    "ACKNOWLEDGE_START",
    "CALLBACK_COMMAND_SPECIFICATIONS",
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


def apply_callback_effects(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command: SubmitCallbackCommand,
    run_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    creator: TypedEventCreator,
    effects: FutureCommandEffects,
) -> list[EventEnvelope | HydratedEvent]:
    _accepted_output_record_events = effects.accepted_output_record_events
    _file_state_authority_conflict = effects.file_state_authority_conflict
    _file_state_rejected_conflict = effects.file_state_rejected_conflict
    _file_state_rejected_events = effects.file_state_rejected_events
    _lease_node_id = effects.lease_node_id
    _output_record_contract_conflict = effects.output_record_contract_conflict
    _output_record_provenance_conflict = effects.output_record_provenance_conflict
    _planner_session_state_event = effects.planner_session_state_event
    _required_output_record_conflict = effects.required_output_record_conflict
    _source_repair_events = effects.source_repair_events
    _typed_lease_event_payload = effects.typed_lease_event_payload
    _verification_record_conflict = effects.verification_record_conflict
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

    lease_node_id = _lease_node_id(projection, request.lease_id)
    expected_producer_node_id = lease_node_id or request.node_id
    if lease_node_id is not None and request.node_id != lease_node_id:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(
                    "callback node_id does not match lease node: "
                    f"{request.node_id} != {lease_node_id}"
                ),
            )
        ]
    provenance_conflict = _output_record_provenance_conflict(request, expected_producer_node_id)
    if provenance_conflict is not None:
        return [creator.create(CALLBACK_REJECTED_CONFLICT, rejected_payload(provenance_conflict))]
    file_state_rejection_conflict = _file_state_rejected_conflict(
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
    file_state_authority_conflict = _file_state_authority_conflict(
        projection,
        request,
    )
    if file_state_authority_conflict is not None:
        return [
            creator.create(
                CALLBACK_REJECTED_CONFLICT,
                rejected_payload(file_state_authority_conflict),
            )
        ]
    verification_conflict = _verification_record_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if verification_conflict is not None:
        return [creator.create(CALLBACK_REJECTED_CONFLICT, rejected_payload(verification_conflict))]
    output_contract_conflict = _output_record_contract_conflict(
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
    missing_output_conflict = _required_output_record_conflict(
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
    output: list[EventEnvelope | HydratedEvent] = [accepted]
    output.extend(_file_state_rejected_events(request, make_event))
    output.extend(
        _accepted_output_record_events(
            projection,
            request,
            expected_producer_node_id,
            make_event,
        )
    )
    if command.complete_node:
        output.append(
            typed_topology_event(
                make_event,
                "node_state_changed",
                {
                    "node_id": request.node_id,
                    "new_state": command.new_state,
                    "trigger": "callback_accepted",
                },
            )
        )
        output.append(
            make_strict_event(
                make_event,
                LEASE_RELEASED,
                _typed_lease_event_payload(
                    "lease_released",
                    {
                        "node_id": request.node_id,
                        "lease_id": request.lease_id,
                        "generation": request.lease_generation,
                    },
                ),
            )
        )
        session_event = _planner_session_state_event(
            projection,
            request.node_id,
            "suspended",
            request.lease_generation,
            make_event,
        )
        if session_event is not None:
            output.append(session_event)
    future_output = [event for event in output if isinstance(event, EventEnvelope)]
    output.extend(_source_repair_events(projection, events, future_output, make_event))
    return output


def apply_acknowledge_start_effects(
    projection: GraphProjection,
    command: AcknowledgeStartCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    creator: TypedEventCreator,
    effects: FutureCommandEffects,
) -> list[EventEnvelope | HydratedEvent]:
    del effects
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

    event_payload: dict[str, Any] = {
        "node_id": node_id,
        "new_state": "running",
        "trigger": "runtime_start_acknowledged",
    }
    if command.prompt_summary is not None:
        event_payload["prompt_summary"] = dict(command.prompt_summary)

    return [typed_topology_event(make_event, "node_state_changed", event_payload)]
