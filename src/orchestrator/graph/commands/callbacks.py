"""Callback and output/evidence command handlers."""

from __future__ import annotations
from typing import Any

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

from pydantic import Field

from orchestrator.graph._commands import (
    Clock,
    IdGenerator,
    apply_raise_appeal,
    apply_record_cleanup_applied,
    apply_record_decision,
    apply_record_gatekeeper_verdicts,
    apply_record_requirement_revision,
    apply_record_support_evidence,
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
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del projection
    del events
    del command_type
    del clock
    return apply_raise_appeal(payload, make_event, id_gen)


def handle_record_decision(
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
    return apply_record_decision(projection, payload, make_event)


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
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del projection
    del events
    del command_type
    del clock
    del id_gen
    return apply_record_requirement_revision(payload, make_event)


def handle_record_support_evidence(
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
    return apply_record_support_evidence(projection, payload, make_event)


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
            make_event(
                "lease_released",
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
