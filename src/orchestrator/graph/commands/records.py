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
    apply_agent_died,
)
from orchestrator.graph.command_models import GraphCommandContext, StrictCommandPayload


def handle_evaluate_join(
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
    del clock
    del context
    return apply_evaluate_join(
        projection,
        payload.model_dump(mode="python", exclude_none=True),
        make_event,
        id_gen,
    )


def handle_evaluate_final_gate(
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
    del command_type
    del context
    return apply_evaluate_final_gate(
        projection,
        events,
        payload.model_dump(mode="python", exclude_none=True),
        make_event,
        id_gen,
    )


def handle_agent_died(
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
    del id_gen
    del context
    return apply_agent_died(
        projection,
        payload.model_dump(mode="python", exclude_none=True),
        clock,
        make_event,
    )


__all__ = [
    "handle_agent_died",
    "handle_evaluate_final_gate",
    "handle_evaluate_join",
]
