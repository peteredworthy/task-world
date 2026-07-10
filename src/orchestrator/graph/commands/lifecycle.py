"""Lifecycle command specifications and compatibility handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field

from orchestrator.graph._commands import (
    Clock,
    EventEnvelope,
    GraphProjection,
    IdGenerator,
    apply_agent_died,
    apply_lifecycle_command,
    event_factory,
)
from orchestrator.graph.events.lifecycle import (
    HEARTBEAT_RECORDED,
    RUNTIME_RETRY_SCHEDULED,
    HeartbeatRecordedPayload,
)
from orchestrator.graph.events.lifecycle import (
    AGENT_DIED,
    COMMAND_REJECTED,
    RUN_LIFECYCLE_CHANGED,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
    StoredEventEnvelope,
)


class RecordHeartbeatCommand(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)


class EmptyLifecycleCommand(StrictPayload):
    pass


class FailCommand(StrictPayload):
    reason: str = "command_failed"


class AgentDiedCommand(StrictPayload):
    lease_id: str
    execution_id: str | None = None
    reason: str = "runtime_process_died"
    max_attempts: int = Field(default=0, ge=0)
    retry_backoff_seconds: int = Field(default=0, ge=0)


def _lifecycle_handler(command_type: str):
    def handler(
        command: EmptyLifecycleCommand | FailCommand,
        projection: GraphProjection,
        events: tuple[EventEnvelope, ...],
        context: CommandExecutionContext,
    ) -> list[EventEnvelope | HydratedEvent]:
        payload = command.model_dump(mode="python")
        if context.actor.role is not None:
            payload["actor_role"] = context.actor.role
        elif context.actor.kind.value == "human":
            payload["actor_role"] = "human"
        make_event = event_factory(
            context.run_id, command_type, context.clock, context.id_generator
        )
        output = apply_lifecycle_command(
            projection,
            list(events),
            command_type,
            payload,
            make_event,
            context.id_generator,
        )
        return _hydrate_converted_lifecycle_outcomes(output)

    return handler


_LIFECYCLE_OUTCOME_SPECS = {
    spec.name: spec
    for spec in (
        RUN_LIFECYCLE_CHANGED,
        COMMAND_REJECTED,
        AGENT_DIED,
        RUNTIME_RETRY_SCHEDULED,
    )
}


def _hydrate_converted_lifecycle_outcomes(
    output: list[EventEnvelope],
) -> list[EventEnvelope | HydratedEvent]:
    """Task 9 deletes this adapter after Tasks 3/4 specify all side effects."""

    converted: list[EventEnvelope | HydratedEvent] = []
    for event in output:
        specification = _LIFECYCLE_OUTCOME_SPECS.get(event.event_type)
        if specification is None:
            converted.append(event)
            continue
        stored = event.model_dump()
        stored["payload_schema_generation"] = stored.pop("schema_version")
        converted.append(specification.hydrate(StoredEventEnvelope.model_validate(stored)))
    return converted


def handle_record_heartbeat(
    command: RecordHeartbeatCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del projection
    del events
    payload = HeartbeatRecordedPayload(
        node_id=command.node_id,
        lease_id=command.lease_id,
        lease_generation=command.lease_generation,
        observed_at=context.clock.now(),
    )
    return [
        HEARTBEAT_RECORDED.create(
            context.event_metadata(HEARTBEAT_RECORDED.name),
            payload,
        )
    ]


ACCEPT_RUN = CommandSpecification(
    "accept_run", EmptyLifecycleCommand, _lifecycle_handler("accept_run")
)
START = CommandSpecification("start", EmptyLifecycleCommand, _lifecycle_handler("start"))
PAUSE = CommandSpecification("pause", EmptyLifecycleCommand, _lifecycle_handler("pause"))
RESUME = CommandSpecification("resume", EmptyLifecycleCommand, _lifecycle_handler("resume"))
CANCEL = CommandSpecification("cancel", EmptyLifecycleCommand, _lifecycle_handler("cancel"))
COMPLETE = CommandSpecification("complete", EmptyLifecycleCommand, _lifecycle_handler("complete"))
FAIL = CommandSpecification("fail", FailCommand, _lifecycle_handler("fail"))

RECORD_HEARTBEAT = CommandSpecification(
    name="record_heartbeat",
    payload_type=RecordHeartbeatCommand,
    handler=handle_record_heartbeat,
)


def handle_agent_died_command(
    command: AgentDiedCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]:
    del events
    make_event = event_factory(
        context.run_id,
        "agent_died",
        context.clock,
        context.id_generator,
    )
    output = apply_agent_died(
        projection,
        command.model_dump(mode="python"),
        context.clock,
        make_event,
    )
    return _hydrate_converted_lifecycle_outcomes(output)


AGENT_DIED_COMMAND = CommandSpecification("agent_died", AgentDiedCommand, handle_agent_died_command)

COMMAND_SPECIFICATIONS: tuple[CommandSpecification[Any], ...] = (
    ACCEPT_RUN,
    START,
    PAUSE,
    RESUME,
    CANCEL,
    COMPLETE,
    FAIL,
    RECORD_HEARTBEAT,
    AGENT_DIED_COMMAND,
)


def handle_lifecycle_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    """Temporary adapter for lifecycle commands outside the Task 1 slice."""

    del clock
    return apply_lifecycle_command(
        projection,
        events,
        command_type,
        payload,
        make_event,
        id_gen,
    )


__all__ = [
    "COMMAND_SPECIFICATIONS",
    "ACCEPT_RUN",
    "START",
    "PAUSE",
    "RESUME",
    "CANCEL",
    "COMPLETE",
    "FAIL",
    "AGENT_DIED_COMMAND",
    "RECORD_HEARTBEAT",
    "RecordHeartbeatCommand",
    "handle_lifecycle_command",
    "handle_record_heartbeat",
]
