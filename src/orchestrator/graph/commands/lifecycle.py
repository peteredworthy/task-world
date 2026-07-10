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
    apply_lifecycle_command,
)
from orchestrator.graph.events.lifecycle import HEARTBEAT_RECORDED, HeartbeatRecordedPayload
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)


class RecordHeartbeatCommand(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)


def handle_record_heartbeat(
    command: RecordHeartbeatCommand,
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
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


RECORD_HEARTBEAT = CommandSpecification(
    name="record_heartbeat",
    payload_type=RecordHeartbeatCommand,
    handler=handle_record_heartbeat,
)

COMMAND_SPECIFICATIONS: tuple[CommandSpecification[Any], ...] = (RECORD_HEARTBEAT,)


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
    "RECORD_HEARTBEAT",
    "RecordHeartbeatCommand",
    "handle_lifecycle_command",
    "handle_record_heartbeat",
]
