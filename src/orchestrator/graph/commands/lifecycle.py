"""Lifecycle and run-state command handlers."""

from collections.abc import Callable
from typing import Any

from orchestrator.graph._commands import (
    Clock,
    EventEnvelope,
    GraphProjection,
    IdGenerator,
    apply_lifecycle_command,
    apply_record_heartbeat,
)
from orchestrator.graph.command_models import (
    AcceptRunCommand,
    CancelCommand,
    CompleteCommand,
    FailCommand,
    GraphCommandContext,
    PauseCommand,
    RecordHeartbeatCommand,
    ResumeCommand,
    StartCommand,
)

EventFactory = Callable[[str, dict[str, Any]], EventEnvelope]


def _handle_lifecycle(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: AcceptRunCommand
    | StartCommand
    | PauseCommand
    | ResumeCommand
    | CancelCommand
    | CompleteCommand
    | FailCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    return apply_lifecycle_command(
        projection, events, command_type, payload, context, make_event, id_gen
    )


def handle_accept_run(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: AcceptRunCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_start(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: StartCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_pause(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: PauseCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_resume(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: ResumeCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_cancel(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: CancelCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_complete(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: CompleteCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_fail(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: FailCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return _handle_lifecycle(projection, events, command_type, payload, context, make_event, id_gen)


def handle_record_heartbeat(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordHeartbeatCommand,
    context: GraphCommandContext,
    make_event: EventFactory,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events, command_type, context, id_gen
    return apply_record_heartbeat(projection, payload, clock, make_event)


__all__ = [
    "handle_accept_run",
    "handle_cancel",
    "handle_complete",
    "handle_fail",
    "handle_pause",
    "handle_record_heartbeat",
    "handle_resume",
    "handle_start",
]
