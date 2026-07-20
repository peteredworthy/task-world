"""Callback and output/evidence command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    EventEnvelope,
    apply_callback_command,
    apply_acknowledge_start,
    apply_record_cleanup_applied,
    apply_record_decision,
    apply_record_gatekeeper_verdicts,
    apply_record_node_usage,
    apply_record_requirement_revision,
    apply_record_support_evidence,
    apply_raise_appeal,
)
from orchestrator.graph.command_models import (
    AcknowledgeStartCommand,
    GraphCommandContext,
    RaiseAppealCommand,
    RecordCleanupAppliedCommand,
    RecordDecisionCommand,
    RecordGatekeeperVerdictsCommand,
    RecordNodeUsageCommand,
    RecordRequirementRevisionCommand,
    RecordSupportEvidenceCommand,
    SubmitCallbackCommand,
)


def handle_submit_callback(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: SubmitCallbackCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    del clock
    del id_gen
    return apply_callback_command(
        projection,
        events,
        payload,
        context.run_id,
        make_event,
    )


def handle_acknowledge_start(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: AcknowledgeStartCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del clock
    del id_gen
    del context
    return apply_acknowledge_start(projection, payload, make_event)


def handle_raise_appeal(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RaiseAppealCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del projection
    del events
    del command_type
    del clock
    del context
    return apply_raise_appeal(payload, make_event, id_gen)


def handle_record_decision(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordDecisionCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del clock
    del id_gen
    del context
    return apply_record_decision(projection, payload, make_event)


def handle_record_gatekeeper_verdicts(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordGatekeeperVerdictsCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del clock
    del id_gen
    del context
    return apply_record_gatekeeper_verdicts(projection, payload, make_event)


def handle_record_node_usage(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordNodeUsageCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del context
    del clock
    del id_gen
    return apply_record_node_usage(projection, payload, make_event)


def handle_record_requirement_revision(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordRequirementRevisionCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del projection
    del events
    del command_type
    del clock
    del id_gen
    del context
    return apply_record_requirement_revision(payload, make_event)


def handle_record_support_evidence(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordSupportEvidenceCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del clock
    del id_gen
    del context
    return apply_record_support_evidence(projection, payload, make_event)


def handle_record_cleanup_applied(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordCleanupAppliedCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    del clock
    del id_gen
    del context
    return apply_record_cleanup_applied(
        projection,
        events,
        payload,
        make_event,
    )


__all__ = [
    "handle_acknowledge_start",
    "handle_raise_appeal",
    "handle_record_cleanup_applied",
    "handle_record_decision",
    "handle_record_gatekeeper_verdicts",
    "handle_record_node_usage",
    "handle_record_requirement_revision",
    "handle_record_support_evidence",
    "handle_submit_callback",
]
