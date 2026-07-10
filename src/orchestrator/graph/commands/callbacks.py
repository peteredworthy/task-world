"""Callback and output/evidence command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from pydantic import Field

from orchestrator.graph._commands import (
    Clock,
    EventEnvelope,
    GraphProjection,
    IdGenerator,
    apply_acknowledge_start,
    apply_callback_command,
    apply_raise_appeal,
    apply_record_cleanup_applied,
    apply_record_decision,
    apply_record_gatekeeper_verdicts,
    apply_record_requirement_revision,
    apply_record_support_evidence,
    event_factory,
)
from orchestrator.graph.events.lifecycle import (
    CALLBACK_ACCEPTED,
    CALLBACK_DUPLICATE_RETURNED,
    CALLBACK_REJECTED_CONFLICT,
    CALLBACK_REJECTED_STALE,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
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
            converted.append(event)
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
    output = apply_callback_command(projection, list(events), payload, make_event)
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
    return [*apply_acknowledge_start(projection, command.model_dump(mode="python"), make_event)]


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
    return apply_callback_command(projection, events, raw_payload, make_event)


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
    return apply_acknowledge_start(projection, raw_payload, make_event)


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
]
