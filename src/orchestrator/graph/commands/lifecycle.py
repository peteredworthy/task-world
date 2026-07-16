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
from orchestrator.graph.command_models import GraphCommandContext, StrictCommandPayload


def handle_lifecycle_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: StrictCommandPayload,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    return apply_lifecycle_command(
        projection,
        events,
        command_type,
        payload.model_dump(mode="python", exclude_none=True),
        context,
        make_event,
        id_gen,
    )


def handle_record_heartbeat(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: StrictCommandPayload,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del events
    del command_type
    del context
    del id_gen
    return apply_record_heartbeat(
        projection,
        payload.model_dump(mode="python", exclude_none=True),
        clock,
        make_event,
    )


__all__ = [
    "handle_lifecycle_command",
    "handle_record_heartbeat",
]
