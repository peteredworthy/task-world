"""Scheduling and seeding command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    EventEnvelope,
    apply_reconcile,
    apply_seed_compiled_events,
    apply_schedule_tick,
)


def handle_seed_compiled_events(
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
    return apply_seed_compiled_events(projection, payload, make_event)


def handle_schedule_tick(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    return apply_schedule_tick(projection, events, payload, clock, id_gen, make_event)


def handle_reconcile(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    del payload
    del clock
    del id_gen
    return apply_reconcile(projection, events, make_event)


__all__ = [
    "handle_reconcile",
    "handle_seed_compiled_events",
    "handle_schedule_tick",
]
