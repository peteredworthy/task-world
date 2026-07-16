"""Patch command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    EventEnvelope,
    apply_patch_command,
)
from orchestrator.graph.command_models import (
    GraphCommandContext,
    PatchCommandContext,
    StrictCommandPayload,
)


def handle_submit_patch(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: StrictCommandPayload,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    del command_type
    del clock
    del id_gen
    if not isinstance(context, PatchCommandContext):
        raise TypeError("submit_patch requires PatchCommandContext")
    return apply_patch_command(
        projection,
        events,
        payload.model_dump(mode="python", exclude_none=True),
        context,
        make_event,
    )


__all__ = [
    "handle_submit_patch",
]
