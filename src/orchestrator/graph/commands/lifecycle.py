"""Lifecycle and run-state command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    EventEnvelope,
    apply_lifecycle_command,
    apply_record_heartbeat,
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
    del clock
    return apply_lifecycle_command(
        projection,
        events,
        command_type,
        payload,
        make_event,
        id_gen,
    )


def handle_record_heartbeat(
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
    del id_gen
    return apply_record_heartbeat(projection, payload, clock, make_event)


__all__ = [
    "handle_lifecycle_command",
    "handle_record_heartbeat",
]
