"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable, Mapping
from itertools import chain
from typing import Any, cast, overload

from orchestrator.graph._commands import (
    Clock,
    EventEnvelope,
    GraphProjection,
    IdGenerator,
    NONTERMINAL_RUN_STATES,
    RUN_LIFECYCLE_TRANSITIONS,
    TERMINAL_RUN_STATES,
    command_rejected,
    event_factory,
    run_id,
)
from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.commands.callbacks import COMMAND_SPECIFICATIONS as CALLBACK_COMMAND_SPECS
from orchestrator.graph.commands.file_state import (
    COMMAND_SPECIFICATIONS as FILE_STATE_COMMAND_SPECS,
)
from orchestrator.graph.commands.lifecycle import COMMAND_SPECIFICATIONS as LIFECYCLE_COMMAND_SPECS
from orchestrator.graph.commands.patches import COMMAND_SPECIFICATIONS as PATCH_COMMAND_SPECS
from orchestrator.graph.commands.records import COMMAND_SPECIFICATIONS as RECORD_COMMAND_SPECS
from orchestrator.graph.commands.schedule import COMMAND_SPECIFICATIONS as SCHEDULE_COMMAND_SPECS
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    HydratedEvent,
)
from orchestrator.graph.events.topology import (
    COMMAND_SPECIFICATIONS as TOPOLOGY_COMMAND_SPECS,
    SEED_COMPILED_EVENTS,
    SeedCompiledEventsCommand,
)

ApplyCommandHandler = Callable[
    [
        GraphProjection,
        list[EventEnvelope],
        str,
        dict[str, Any],
        Callable[[str, dict[str, Any]], EventEnvelope],
        Clock,
        IdGenerator,
    ],
    list[EventEnvelope],
]


COMMAND_SPECIFICATION_GROUPS = (
    LIFECYCLE_COMMAND_SPECS,
    CALLBACK_COMMAND_SPECS,
    TOPOLOGY_COMMAND_SPECS,
    SCHEDULE_COMMAND_SPECS,
    PATCH_COMMAND_SPECS,
    RECORD_COMMAND_SPECS,
    FILE_STATE_COMMAND_SPECS,
)
COMMAND_SPECIFICATIONS = tuple(chain.from_iterable(COMMAND_SPECIFICATION_GROUPS))
_CATALOG_COMMAND_NAMES = frozenset(spec.name for spec in COMMAND_SPECIFICATIONS)


@overload
def apply_command(
    catalog_or_projection: GraphCatalog,
    projection_or_events: GraphProjection,
    events_or_command: list[EventEnvelope],
    command_or_payload: str,
    payload_or_clock: Mapping[str, object],
    context_or_id: CommandExecutionContext | None,
) -> list[EventEnvelope | HydratedEvent]: ...


@overload
def apply_command(
    catalog_or_projection: GraphProjection,
    projection_or_events: list[EventEnvelope],
    events_or_command: str,
    command_or_payload: dict[str, Any],
    payload_or_clock: Clock,
    context_or_id: IdGenerator,
    *,
    catalog: None = None,
    context: None = None,
) -> list[EventEnvelope | HydratedEvent]: ...


@overload
def apply_command(
    catalog_or_projection: GraphProjection,
    projection_or_events: list[EventEnvelope],
    events_or_command: str,
    command_or_payload: dict[str, Any],
    payload_or_clock: Clock,
    context_or_id: IdGenerator,
    *,
    catalog: GraphCatalog,
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]: ...


def apply_command(
    catalog_or_projection: GraphCatalog | GraphProjection,
    projection_or_events: GraphProjection | list[EventEnvelope],
    events_or_command: list[EventEnvelope] | str,
    command_or_payload: str | Mapping[str, object],
    payload_or_clock: Mapping[str, object] | Clock,
    context_or_id: CommandExecutionContext | IdGenerator | None,
    *,
    catalog: GraphCatalog | None = None,
    context: CommandExecutionContext | None = None,
) -> list[EventEnvelope] | list[HydratedEvent] | list[EventEnvelope | HydratedEvent]:
    """Apply a strict catalog command, retaining the historical call form for replay fixtures."""

    if isinstance(catalog_or_projection, GraphCatalog):
        if not isinstance(projection_or_events, dict):
            raise TypeError("typed graph command dispatch requires a graph projection")
        if not isinstance(events_or_command, list):
            raise TypeError("typed graph command dispatch requires prior events")
        if not isinstance(command_or_payload, str):
            raise TypeError("typed graph command dispatch requires a command name")
        if not isinstance(payload_or_clock, Mapping):
            raise TypeError("typed graph command dispatch requires an object payload")
        specification = catalog_or_projection.resolve_command(command_or_payload)
        if context_or_id is None or not isinstance(context_or_id, CommandExecutionContext):
            msg = f"typed graph command {command_or_payload!r} requires an execution context"
            raise ValueError(msg)
        command = specification.validate(payload_or_clock)
        if command_or_payload == SEED_COMPILED_EVENTS.name:
            typed_command = cast(SeedCompiledEventsCommand, command)
            for event in typed_command.events:
                catalog_or_projection.resolve_event(event.metadata.event_type).serialize(event)
        return specification.handle(
            command,
            projection_or_events,
            tuple(events_or_command),
            context_or_id,
        )

    projection = catalog_or_projection
    events = cast(list[EventEnvelope], projection_or_events)
    command_type = cast(str, events_or_command)
    payload = cast(dict[str, Any], command_or_payload)
    clock = cast(Clock, payload_or_clock)
    id_gen = cast(IdGenerator, context_or_id)

    run_id_value = run_id(events, payload)
    make_event = event_factory(run_id_value, command_type, clock, id_gen)
    specification = catalog.command_specs.get(command_type) if catalog is not None else None
    if catalog is None and command_type in _CATALOG_COMMAND_NAMES:
        raise ValueError(f"typed graph command {command_type!r} requires a catalog and context")
    if specification is not None:
        assert catalog is not None
        if context is None:
            msg = f"typed graph command {command_type!r} requires an execution context"
            raise ValueError(msg)
        command = specification.validate(payload)
        if command_type == SEED_COMPILED_EVENTS.name:
            typed_command = cast(SeedCompiledEventsCommand, command)
            for event in typed_command.events:
                catalog.resolve_event(event.metadata.event_type).serialize(event)
        return specification.handle(command, projection, tuple(events), context)
    return [command_rejected(make_event, command_type, f"unknown command: {command_type}")]


__all__ = [
    "Clock",
    "EventEnvelope",
    "GraphProjection",
    "IdGenerator",
    "RUN_LIFECYCLE_TRANSITIONS",
    "TERMINAL_RUN_STATES",
    "NONTERMINAL_RUN_STATES",
    "apply_command",
    "COMMAND_SPECIFICATIONS",
    "COMMAND_SPECIFICATION_GROUPS",
]
