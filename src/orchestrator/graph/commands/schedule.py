"""Scheduling and seeding command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from pydantic import Field

from orchestrator.graph._commands import (
    Clock,
    GraphProjection,
    IdGenerator,
    apply_reconcile,
    schedule_tick_effects,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph._commands import event_factory
from orchestrator.graph.scheduler import InputEdgeInfo, NodeScheduleInfo, ResourceClaim


class ScheduleTickCommand(StrictPayload):
    lease_seconds: int = Field(ge=1)
    max_grants: int = Field(ge=0)
    base_snapshot_id: str | None = None
    lease_ids: dict[str, str] | None = None
    priorities: dict[str, int] | None = None
    region_order: dict[str, int] | None = None


class ReconcileCommand(StrictPayload):
    pass


def node_schedule_info(
    projection: GraphProjection,
    payload: dict[str, Any],
    node_id: str,
) -> NodeScheduleInfo:
    priorities = (
        cast(dict[str, Any], payload.get("priorities"))
        if isinstance(payload.get("priorities"), dict)
        else {}
    )
    region_order = (
        cast(dict[str, Any], payload.get("region_order"))
        if isinstance(payload.get("region_order"), dict)
        else {}
    )
    required_edges = _required_edges_for_node(projection, node_id)
    upstream_node_ids = {edge.from_node_id for edge in required_edges}
    return NodeScheduleInfo(
        node_id=node_id,
        kind=projection["node_kinds"].get(node_id, "worker"),
        state=projection["node_states"][node_id],
        priority=int(priorities.get(node_id, 0)),
        region_order=int(region_order.get(node_id, 0)),
        creation_position=projection["node_creation_positions"].get(node_id, 0),
        resource_claims=[
            _claim_from_projection(claim)
            for claim in projection["node_resource_claims"].get(node_id, [])
        ],
        required_edges=required_edges,
        satisfied_input_ports=set(projection["input_bindings"].get(node_id, {})),
        upstream_states={
            upstream_node_id: projection["node_states"][upstream_node_id]
            for upstream_node_id in upstream_node_ids
            if upstream_node_id in projection["node_states"]
        },
        upstream_kinds={
            upstream_node_id: projection["node_kinds"][upstream_node_id]
            for upstream_node_id in upstream_node_ids
            if upstream_node_id in projection["node_kinds"]
        },
        upstream_pending_appeals={
            upstream_node_id
            for upstream_node_id in upstream_node_ids
            if projection["node_pending_appeals"].get(upstream_node_id) is True
        },
        gate_decisions={
            gate_node_id: decision
            for gate_node_id, decision in projection["node_gate_decisions"].items()
            if gate_node_id in upstream_node_ids
        },
        failed_candidate_id=projection["node_failed_candidates"].get(node_id),
        preconditions=projection["node_preconditions"].get(node_id, []),
        command_definition_present=node_id in projection["node_command_definitions"],
    )


def _required_edges_for_node(
    projection: GraphProjection,
    node_id: str,
) -> list[InputEdgeInfo]:
    return [
        InputEdgeInfo(
            from_node_id=str(edge.get("from_node_id", "")),
            from_port=str(edge.get("from_port", "")),
            to_node_id=str(edge.get("to_node_id", "")),
            to_port=str(edge.get("to_port", "")),
            required=edge.get("required") is not False,
            dependency_type=str(edge.get("dependency_type", "input_binding")),
        )
        for edge in projection["edges"].values()
        if edge.get("to_node_id") == node_id
    ]


def _claim_from_projection(claim: Any) -> ResourceClaim:
    payload: dict[str, Any]
    if isinstance(claim, dict):
        payload = cast(dict[str, Any], claim)
    elif hasattr(claim, "model_dump"):
        payload = cast(dict[str, Any], claim.model_dump(mode="python"))
    else:
        payload = {}
    mode = str(payload.get("mode", "read"))
    scope = str(payload.get("scope", "repo"))
    paths = (
        [str(path) for path in payload.get("paths", [])]
        if isinstance(payload.get("paths"), list)
        else []
    )
    if mode in {"read", "write"} and scope not in {"repo", ""}:
        if scope not in paths:
            paths.append(scope)
        scope = "repo"
    return ResourceClaim(
        mode=mode,
        scope=scope,
        paths=paths,
        snapshot_id=cast(str | None, payload.get("snapshot_id")),
        external_resource_key=cast(str | None, payload.get("external_resource_key")),
        exclusive=bool(payload.get("exclusive", False)),
    )


def _execute_schedule_tick(
    command: ScheduleTickCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    """Keep the strict command boundary in the scheduling domain."""

    return schedule_tick_effects(
        projection,
        list(events),
        command.to_json(),
        context.clock,
        context.id_generator,
        event_factory(context, "schedule_tick"),
    )


def _typed_schedule(
    command: ScheduleTickCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
):
    return _execute_schedule_tick(command, projection, events, context)


def _typed_reconcile(
    command: ReconcileCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
):
    del command
    return apply_reconcile(
        projection,
        list(events),
        event_factory(context, "reconcile"),
    )


SCHEDULE_TICK = CommandSpecification("schedule_tick", ScheduleTickCommand, _typed_schedule)
RECONCILE = CommandSpecification("reconcile", ReconcileCommand, _typed_reconcile)
COMMAND_SPECIFICATIONS = (SCHEDULE_TICK, RECONCILE)


def handle_schedule_tick(
    projection: GraphProjection,
    events: list[HydratedEvent],
    command_type: str,
    payload: ScheduleTickCommand,
    make_event: Callable[[str, dict[str, Any]], HydratedEvent],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[HydratedEvent]:
    del command_type
    return schedule_tick_effects(projection, events, payload.to_json(), clock, id_gen, make_event)


def handle_reconcile(
    projection: GraphProjection,
    events: list[HydratedEvent],
    command_type: str,
    payload: ReconcileCommand,
    make_event: Callable[[str, dict[str, Any]], HydratedEvent],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[HydratedEvent]:
    del command_type
    del payload
    del clock
    del id_gen
    return apply_reconcile(projection, events, make_event)


__all__ = [
    "RECONCILE",
    "SCHEDULE_TICK",
    "ReconcileCommand",
    "ScheduleTickCommand",
    "handle_reconcile",
    "handle_schedule_tick",
]
