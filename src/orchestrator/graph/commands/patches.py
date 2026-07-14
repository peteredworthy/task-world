"""Patch command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field
from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    apply_patch_command,
)
from orchestrator.graph.models import PatchOp
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph._commands import event_factory
from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.commands.event_creator import TypedEventCreator


def _empty_macro_invocations() -> list[dict[str, JsonValue]]:
    return []


class SubmitPatchFields(StrictPayload):
    """Command-owned patch fields shared with transport adapters."""

    ops: list[PatchOp] = Field(min_length=1)
    rationale_record_id: str | None = Field(default=None, min_length=1)


class SubmitPatchCommand(SubmitPatchFields):
    patch_id: str
    base_graph_position: int
    actor_role: str
    proposed_by_node_id: str
    macro_invocations: list[dict[str, JsonValue]] = Field(default_factory=_empty_macro_invocations)
    session_id: str | None = None
    carryover_record_id: str | None = None
    diagnostics: dict[str, JsonValue] | None = None
    read_set_diff: dict[str, JsonValue] | None = None
    lease_id: str | None = None
    lease_generation: int | None = Field(default=None, ge=0)
    execution_id: str | None = None
    base_snapshot_id: str | None = None
    observed_graph_position: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = None


def _typed_submit(
    command: SubmitPatchCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
):
    return apply_patch_command(
        projection,
        list(events),
        command.to_json(),
        event_factory(context, "submit_patch"),
        context.catalog,
        TypedEventCreator(context, assign_position=False),
    )


SUBMIT_PATCH = CommandSpecification("submit_patch", SubmitPatchCommand, _typed_submit)
COMMAND_SPECIFICATIONS = (SUBMIT_PATCH,)


def handle_submit_patch(
    projection: GraphProjection,
    events: list[HydratedEvent],
    command_type: str,
    payload: SubmitPatchCommand,
    make_event: Callable[[str, dict[str, Any]], HydratedEvent],
    clock: Clock,
    id_gen: IdGenerator,
    catalog: GraphCatalog,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    del command_type
    del clock
    del id_gen
    return apply_patch_command(projection, events, payload.to_json(), make_event, catalog, creator)


__all__ = [
    "SUBMIT_PATCH",
    "COMMAND_SPECIFICATIONS",
    "SubmitPatchCommand",
    "SubmitPatchFields",
    "handle_submit_patch",
]
