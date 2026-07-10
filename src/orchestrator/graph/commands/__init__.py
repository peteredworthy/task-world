"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable
from typing import Any, overload

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
from orchestrator.graph.commands.callbacks import (
    handle_acknowledge_start,
    handle_raise_appeal,
    handle_record_cleanup_applied,
    handle_record_decision,
    handle_record_gatekeeper_verdicts,
    handle_record_requirement_revision,
    handle_record_support_evidence,
    handle_submit_callback,
)
from orchestrator.graph.commands.lifecycle import RECORD_HEARTBEAT, handle_lifecycle_command
from orchestrator.graph.commands.patches import handle_submit_patch
from orchestrator.graph.commands.records import (
    handle_agent_died,
    handle_evaluate_final_gate,
    handle_evaluate_join,
)
from orchestrator.graph.commands.schedule import (
    handle_reconcile,
    handle_schedule_tick,
    handle_seed_compiled_events,
)
from orchestrator.graph.specifications import CommandExecutionContext, HydratedEvent

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
    "accept_run": handle_lifecycle_command,
    "start": handle_lifecycle_command,
    "pause": handle_lifecycle_command,
    "resume": handle_lifecycle_command,
    "cancel": handle_lifecycle_command,
    "complete": handle_lifecycle_command,
    "fail": handle_lifecycle_command,
    "seed_compiled_events": handle_seed_compiled_events,
    "submit_callback": handle_submit_callback,
    "submit_patch": handle_submit_patch,
    "schedule_tick": handle_schedule_tick,
    "reconcile": handle_reconcile,
    "acknowledge_start": handle_acknowledge_start,
    "agent_died": handle_agent_died,
    "raise_appeal": handle_raise_appeal,
    "record_decision": handle_record_decision,
    "record_gatekeeper_verdicts": handle_record_gatekeeper_verdicts,
    "record_requirement_revision": handle_record_requirement_revision,
    "record_support_evidence": handle_record_support_evidence,
    "evaluate_join": handle_evaluate_join,
    "evaluate_final_gate": handle_evaluate_final_gate,
    "record_cleanup_applied": handle_record_cleanup_applied,
}


COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT,)


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
) -> list[EventEnvelope] | list[HydratedEvent]: ...


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
) -> list[EventEnvelope] | list[HydratedEvent]:
    """Apply a pure graph command and return events a controller would append."""

    run_id_value = run_id(events, payload)
    make_event = event_factory(run_id_value, command_type, clock, id_gen)
    specification = catalog.command_specs.get(command_type) if catalog is not None else None
    if specification is not None:
        if context is None:
            msg = f"typed graph command {command_type!r} requires an execution context"
            raise ValueError(msg)
        return specification.handle(specification.validate(payload), context)
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
]
