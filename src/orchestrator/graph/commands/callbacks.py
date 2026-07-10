"""Callback and output/evidence command handlers."""

from __future__ import annotations
from typing import Any, cast

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
)
from orchestrator.graph.commands.future_effects import require_future_effect
from collections.abc import Callable

from pydantic import Field

from orchestrator.graph._commands import (
    Clock,
    IdGenerator,
    future_command_effects,
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
    StoredEventEnvelope,
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


_CALLBACK_OUTCOME_SPECS = {
    spec.name: spec
    for spec in (
        CALLBACK_ACCEPTED,
        CALLBACK_REJECTED_STALE,
        CALLBACK_REJECTED_CONFLICT,
        CALLBACK_DUPLICATE_RETURNED,
        COMMAND_REJECTED,
    )
}


def _hydrate_converted_callback_outcomes(
    output: list[EventEnvelope],
) -> list[EventEnvelope | HydratedEvent]:
    """Task 9 deletes this adapter once every callback effect has an event spec."""

    converted: list[EventEnvelope | HydratedEvent] = []
    for event in output:
        specification = _CALLBACK_OUTCOME_SPECS.get(event.event_type)
        if specification is None:
            # Tasks 3/4/6 own output, file-state, node, lease, and session
            # specifications. Keep those effects isolated as legacy envelopes.
            converted.append(require_future_effect(event))
            continue
        stored = event.model_dump()
        stored["payload_schema_generation"] = stored.pop("schema_version")
        converted.append(specification.hydrate(StoredEventEnvelope.model_validate(stored)))
    return converted


def handle_submit_callback_command(
    command: SubmitCallbackCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]:
    make_event = event_factory(
        context.run_id, SUBMIT_CALLBACK.name, context.clock, context.id_generator
    )
    payload = command.model_dump(mode="python")
    payload["run_id"] = context.run_id
    output = temporary_unconverted_callback_effects(
        projection, list(events), payload, make_event, context.future_effects
    )
    return _hydrate_converted_callback_outcomes(output)


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
    return [
        *temporary_unconverted_acknowledge_start_effects(
            projection, command.model_dump(mode="python"), make_event, context.future_effects
        )
    ]


SUBMIT_CALLBACK = CommandSpecification(
    "submit_callback", SubmitCallbackCommand, handle_submit_callback_command
)
ACKNOWLEDGE_START = CommandSpecification(
    "acknowledge_start", AcknowledgeStartCommand, handle_acknowledge_start_command
)
CALLBACK_COMMAND_SPECIFICATIONS = (ACKNOWLEDGE_START, SUBMIT_CALLBACK)


def handle_submit_callback(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: SubmitCallbackCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    del clock
    del id_gen
    compatibility_payload = cast(Any, payload)
    raw_payload = (
        payload.model_dump(mode="python")
        if isinstance(compatibility_payload, SubmitCallbackCommand)
        else compatibility_payload
    )
    return temporary_unconverted_callback_effects(
        projection, events, raw_payload, make_event, future_command_effects()
    )


def handle_acknowledge_start(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: AcknowledgeStartCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del clock
    del id_gen
    compatibility_payload = cast(Any, payload)
    raw_payload = (
        payload.model_dump(mode="python")
        if isinstance(compatibility_payload, AcknowledgeStartCommand)
        else compatibility_payload
    )
    return temporary_unconverted_acknowledge_start_effects(
        projection, raw_payload, make_event, future_command_effects()
    )


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
    "handle_acknowledge_start",
    "handle_raise_appeal",
    "handle_record_cleanup_applied",
    "handle_record_decision",
    "handle_record_gatekeeper_verdicts",
    "handle_record_requirement_revision",
    "handle_record_support_evidence",
    "handle_submit_callback",
    "temporary_unconverted_callback_effects",
    "temporary_unconverted_acknowledge_start_effects",
]


def temporary_unconverted_callback_effects(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    effects: FutureCommandEffects,
) -> list[EventEnvelope]:
    _accepted_output_record_events = effects.accepted_output_record_events
    _callback_payload = effects.callback_payload
    _command_rejected = effects.command_rejected
    _file_state_authority_conflict = effects.file_state_authority_conflict
    _file_state_rejected_conflict = effects.file_state_rejected_conflict
    _file_state_rejected_events = effects.file_state_rejected_events
    _lease_node_id = effects.lease_node_id
    _make_strict_event = effects.make_strict_event
    _output_record_contract_conflict = effects.output_record_contract_conflict
    _output_record_provenance_conflict = effects.output_record_provenance_conflict
    _planner_session_state_event = effects.planner_session_state_event
    _required_output_record_conflict = effects.required_output_record_conflict
    _source_repair_events = effects.source_repair_events
    _typed_lease_event_payload = effects.typed_lease_event_payload
    _verification_record_conflict = effects.verification_record_conflict
    required = [
        "run_id",
        "node_id",
        "execution_id",
        "lease_id",
        "lease_generation",
        "base_snapshot_id",
        "observed_graph_position",
        "idempotency_key",
    ]
    missing = [field for field in required if field not in payload]
    if missing:
        return [
            _command_rejected(
                make_event,
                "submit_callback",
                f"missing callback fields: {', '.join(missing)}",
            )
        ]

    callback_payload = cast(dict[str, Any] | None, _callback_payload(payload))
    # Mutating-ness is derived from the callback's actual effects, never trusted
    # from the caller's flag: completing the node or carrying output records IS
    # a mutation, so a callback claiming is_mutating=False cannot bypass the
    # running-state and suspended-lease guards.
    has_effects = bool(payload.get("complete_node", True)) or bool(
        (callback_payload or {}).get("output_records")
    )
    request = CallbackRequest(
        run_id=str(payload["run_id"]),
        node_id=str(payload["node_id"]),
        execution_id=str(payload["execution_id"]),
        lease_id=str(payload["lease_id"]),
        lease_generation=int(payload["lease_generation"]),
        base_snapshot_id=str(payload["base_snapshot_id"]),
        observed_graph_position=int(payload["observed_graph_position"]),
        idempotency_key=str(payload["idempotency_key"]),
        payload=callback_payload,
        is_mutating=bool(payload.get("is_mutating", True)) or has_effects,
    )
    result = validate_callback(request, projection, events)

    event_payload = {
        "node_id": request.node_id,
        "lease_id": request.lease_id,
        "lease_generation": request.lease_generation,
        "idempotency_key": request.idempotency_key,
        "payload": request.payload,
        "reason": result.reason,
    }
    if result.outcome == CallbackOutcome.REJECTED_STALE:
        return [_make_strict_event(make_event, CALLBACK_REJECTED_STALE, event_payload)]
    if result.outcome in {
        CallbackOutcome.REJECTED_CONFLICT,
        CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
    }:
        return [_make_strict_event(make_event, CALLBACK_REJECTED_CONFLICT, event_payload)]
    if result.outcome == CallbackOutcome.DUPLICATE_IDEMPOTENT:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_DUPLICATE_RETURNED,
                {**event_payload, "prior_result": result.prior_result},
            )
        ]

    lease_node_id = _lease_node_id(projection, request.lease_id)
    expected_producer_node_id = lease_node_id or request.node_id
    if lease_node_id is not None and request.node_id != lease_node_id:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {
                    **event_payload,
                    "reason": (
                        "callback node_id does not match lease node: "
                        f"{request.node_id} != {lease_node_id}"
                    ),
                },
            )
        ]
    provenance_conflict = _output_record_provenance_conflict(request, expected_producer_node_id)
    if provenance_conflict is not None:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {**event_payload, "reason": provenance_conflict},
            )
        ]
    file_state_rejection_conflict = _file_state_rejected_conflict(
        request,
        expected_producer_node_id,
    )
    if file_state_rejection_conflict is not None:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {**event_payload, "reason": file_state_rejection_conflict},
            )
        ]
    file_state_authority_conflict = _file_state_authority_conflict(
        projection,
        request,
    )
    if file_state_authority_conflict is not None:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {**event_payload, "reason": file_state_authority_conflict},
            )
        ]
    verification_conflict = _verification_record_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if verification_conflict is not None:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {**event_payload, "reason": verification_conflict},
            )
        ]
    output_contract_conflict = _output_record_contract_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if output_contract_conflict is not None:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {**event_payload, "reason": output_contract_conflict},
            )
        ]
    missing_output_conflict = _required_output_record_conflict(
        projection,
        request,
        expected_producer_node_id,
        successful_completion=(
            bool(payload.get("complete_node", True))
            and str(payload.get("new_state", "completed")) == "completed"
        ),
    )
    if missing_output_conflict is not None:
        return [
            _make_strict_event(
                make_event,
                CALLBACK_REJECTED_CONFLICT,
                {**event_payload, "reason": missing_output_conflict},
            )
        ]

    accepted = _make_strict_event(make_event, CALLBACK_ACCEPTED, event_payload)
    output: list[EventEnvelope] = [accepted]
    output.extend(_file_state_rejected_events(request, make_event))
    output.extend(
        _accepted_output_record_events(
            projection,
            request,
            expected_producer_node_id,
            make_event,
        )
    )
    if payload.get("complete_node", True):
        output.append(
            make_event(
                "node_state_changed",
                {
                    "node_id": request.node_id,
                    "new_state": str(payload.get("new_state", "completed")),
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
    output.extend(_source_repair_events(projection, events, output, make_event))
    return output


def temporary_unconverted_acknowledge_start_effects(
    projection: GraphProjection,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    effects: FutureCommandEffects,
) -> list[EventEnvelope]:
    _command_rejected = effects.command_rejected
    node_id = payload.get("node_id")
    lease_id = payload.get("lease_id")
    lease_generation = payload.get("lease_generation")
    execution_id = payload.get("execution_id")
    if not isinstance(node_id, str) or not isinstance(lease_id, str):
        return [_command_rejected(make_event, "acknowledge_start", "missing lease identity")]
    if not isinstance(lease_generation, int):
        return [_command_rejected(make_event, "acknowledge_start", "missing lease generation")]
    if not isinstance(execution_id, str):
        return [_command_rejected(make_event, "acknowledge_start", "missing execution_id")]

    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "acknowledge_start", "unknown lease")]
    if lease.get("state") != "active":
        return [_command_rejected(make_event, "acknowledge_start", "lease not active")]
    if lease.get("node_id") != node_id:
        return [_command_rejected(make_event, "acknowledge_start", "node_incompatible")]
    if lease.get("generation") != lease_generation:
        return [_command_rejected(make_event, "acknowledge_start", "generation_incompatible")]
    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str) and lease_execution_id != execution_id:
        return [_command_rejected(make_event, "acknowledge_start", "execution_incompatible")]

    event_payload: dict[str, Any] = {
        "node_id": node_id,
        "new_state": "running",
        "trigger": "runtime_start_acknowledged",
    }
    prompt_summary = payload.get("prompt_summary")
    if isinstance(prompt_summary, dict):
        event_payload["prompt_summary"] = dict(cast(dict[str, Any], prompt_summary))

    return [make_event("node_state_changed", event_payload)]
