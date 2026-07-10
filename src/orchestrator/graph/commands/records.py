"""Record/evaluation command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    EventEnvelope,
    apply_evaluate_final_gate,
    apply_evaluate_join,
)


def handle_evaluate_join(
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
    return apply_evaluate_join(projection, payload, make_event, id_gen)


def handle_evaluate_final_gate(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del clock
    del command_type
    return apply_evaluate_final_gate(projection, events, payload, make_event, id_gen)


__all__ = [
    "handle_evaluate_final_gate",
    "handle_evaluate_join",
]
