"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable
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
    future_command_effects,
    run_id,
)
from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.commands.callbacks import (
    handle_raise_appeal,
    handle_record_cleanup_applied,
    handle_record_decision,
    handle_record_gatekeeper_verdicts,
    handle_record_requirement_revision,
    handle_record_support_evidence,
)
from orchestrator.graph.commands.lifecycle import (
    RECORD_HEARTBEAT,
    RecordHeartbeatCommand,
)
from orchestrator.graph.commands.lease_bridge import apply_temporary_unconverted_lease_renewal
from orchestrator.graph.commands.patches import handle_submit_patch
from orchestrator.graph.commands.records import (
    handle_evaluate_final_gate,
    handle_evaluate_join,
)
from orchestrator.graph.commands.schedule import (
    handle_reconcile,
    handle_schedule_tick,
    handle_seed_compiled_events,
)
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    HydratedEvent,
    StoredEventEnvelope,
)
from orchestrator.graph.events.lifecycle import COMMAND_REJECTED
from orchestrator.graph.commands.lifecycle import (
    ACCEPT_RUN,
    START,
    PAUSE,
    RESUME,
    CANCEL,
    COMPLETE,
    FAIL,
    AGENT_DIED_COMMAND,
)
from orchestrator.graph.commands.callbacks import SUBMIT_CALLBACK, ACKNOWLEDGE_START

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


_UNCONVERTED_W5_BRIDGE: dict[str, ApplyCommandHandler] = {
    "seed_compiled_events": handle_seed_compiled_events,
    "submit_patch": handle_submit_patch,
    "schedule_tick": handle_schedule_tick,
    "reconcile": handle_reconcile,
    "raise_appeal": handle_raise_appeal,
    "record_decision": handle_record_decision,
    "record_gatekeeper_verdicts": handle_record_gatekeeper_verdicts,
    "record_requirement_revision": handle_record_requirement_revision,
    "record_support_evidence": handle_record_support_evidence,
    "evaluate_join": handle_evaluate_join,
    "evaluate_final_gate": handle_evaluate_final_gate,
    "record_cleanup_applied": handle_record_cleanup_applied,
}


COMMAND_SPECIFICATIONS = (
    RECORD_HEARTBEAT,
    ACCEPT_RUN,
    START,
    PAUSE,
    RESUME,
    CANCEL,
    COMPLETE,
    FAIL,
    SUBMIT_CALLBACK,
    ACKNOWLEDGE_START,
    AGENT_DIED_COMMAND,
)
_CATALOG_COMMAND_NAMES = frozenset(spec.name for spec in COMMAND_SPECIFICATIONS)


@overload
def apply_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
    *,
    catalog: None = None,
    context: None = None,
) -> list[EventEnvelope]: ...


@overload
def apply_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
    *,
    catalog: GraphCatalog,
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]: ...


def apply_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
    *,
    catalog: GraphCatalog | None = None,
    context: CommandExecutionContext | None = None,
) -> list[EventEnvelope] | list[HydratedEvent] | list[EventEnvelope | HydratedEvent]:
    """Apply a pure graph command and return events a controller would append."""

    run_id_value = run_id(events, payload)
    make_event = event_factory(run_id_value, command_type, clock, id_gen)
    specification = catalog.command_specs.get(command_type) if catalog is not None else None
    if catalog is None and command_type in _CATALOG_COMMAND_NAMES:
        raise ValueError(f"typed graph command {command_type!r} requires a catalog and context")
    if specification is not None:
        if context is None:
            msg = f"typed graph command {command_type!r} requires an execution context"
            raise ValueError(msg)
        command = specification.validate(payload)
        if command_type == RECORD_HEARTBEAT.name:
            typed_command = cast(RecordHeartbeatCommand, command)
            renewal = apply_temporary_unconverted_lease_renewal(
                projection,
                typed_command,
                context.clock,
                make_event,
            )
            if renewal.event_type == "command_rejected":
                stored = renewal.model_dump()
                stored["payload_schema_generation"] = stored.pop("schema_version")
                return [COMMAND_REJECTED.hydrate(StoredEventEnvelope.model_validate(stored))]
            return [
                *specification.handle(typed_command, projection, tuple(events), context),
                renewal,
            ]
        return specification.handle(command, projection, tuple(events), context)
    handler = _UNCONVERTED_W5_BRIDGE.get(command_type)
    if handler is None:
        return [
            command_rejected(
                make_event,
                command_type,
                f"unknown command: {command_type}",
            )
        ]
    return handler(projection, events, command_type, payload, make_event, clock, id_gen)


__all__ = [
    "Clock",
    "EventEnvelope",
    "GraphProjection",
    "IdGenerator",
    "RUN_LIFECYCLE_TRANSITIONS",
    "TERMINAL_RUN_STATES",
    "NONTERMINAL_RUN_STATES",
    "apply_command",
    "future_command_effects",
]
