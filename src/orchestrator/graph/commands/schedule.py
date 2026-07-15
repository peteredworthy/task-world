"""Scheduling and seeding command handlers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast
from pydantic import Field

from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.commands.source_repair import (
    TERMINAL_RUN_STATES,
    active_lease_node_ids,
    dedupe_repair_events,
    failed_check_recovery_events,
    failed_verification_recovery_events,
    no_successor_recovery_terminal_failure_events,
    passed_check_terminalization_events,
    passed_verification_terminalization_events,
)
from orchestrator.graph.commands.event_creator import TypedEventCreator
from orchestrator.graph.events.leases import (
    LEASE_EXPIRED,
    LEASE_GRANTED,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
)
from orchestrator.graph.events.lifecycle import COMMAND_REJECTED, CommandRejectedPayload
from orchestrator.graph.events.records import OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload
from orchestrator.graph.events.topology import (
    DEAD_INPUT_DETECTED,
    NODE_DEFERRED,
    NODE_READY,
    NODE_STATE_CHANGED,
    SESSION_STATE_CHANGED,
    DeadInputDetectedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeStateChangedPayload,
    PlannerSessionStateChangedPayload,
)
from orchestrator.graph.models import (
    ResourceClaimProjection,
    StrictFailureRecord,
    StrictFailureRecordValue,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph.scheduler import (
    InputEdgeInfo,
    NodeScheduleInfo,
    ResourceClaim,
    evaluate_readiness,
    schedule,
)


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
    command: ScheduleTickCommand,
    node_id: str,
) -> NodeScheduleInfo:
    priorities = command.priorities or {}
    region_order = command.region_order or {}
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
    typed_claim = ResourceClaimProjection.model_validate(claim)
    mode = typed_claim.mode
    scope = typed_claim.scope
    paths = list(typed_claim.paths or [])
    if mode in {"read", "write"} and scope not in {"repo", ""}:
        if scope not in paths:
            paths.append(scope)
        scope = "repo"
    return ResourceClaim(
        mode=mode,
        scope=scope,
        paths=paths,
        snapshot_id=None,
        external_resource_key=typed_claim.external_resource_key,
        exclusive=False,
    )


def _typed_schedule(
    command: ScheduleTickCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    return schedule_tick_events(
        command,
        projection,
        events,
        context,
        TypedEventCreator(context, causation_id="schedule_tick"),
    )


def schedule_tick_events(
    command: ScheduleTickCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    """Apply one scheduler tick with typed command data and typed event payloads."""

    output = _expired_lease_events(projection, context.clock.now(), creator)
    expired_lease_ids = _expired_active_lease_ids(projection, context.clock.now())
    active_claims = [
        _claim_from_projection(claim)
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        and isinstance(lease.get("lease_id"), str)
        and lease.get("lease_id") not in expired_lease_ids
        for claim in cast(list[Any], lease.get("resource_claims", []))
    ]
    active_lease_node_ids = [
        str(lease["node_id"])
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        and isinstance(lease.get("lease_id"), str)
        and lease.get("lease_id") not in expired_lease_ids
        and isinstance(lease.get("node_id"), str)
    ]
    nodes: list[NodeScheduleInfo] = []
    readied_node_ids: set[str] = set()
    for node_id, node_state in projection["node_states"].items():
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        node = node_schedule_info(projection, command, node_id)
        backoff_reason = _retry_backoff_deferred_reason(projection, node_id, context.clock.now())
        if backoff_reason is not None:
            _append_node_deferred_if_changed(output, projection, node_id, backoff_reason, creator)
            continue
        readiness_node = replace(node, state="planned") if node_state == "ready" else node
        ready, reason = evaluate_readiness(
            readiness_node,
            projection["run_state"] or "draft",
            active_lease_node_ids,
            active_claims,
        )
        if not ready:
            dead_input = _dead_input_from_readiness(node, reason)
            if (
                dead_input is not None
                and projection.get("last_deferred_reasons", {}).get(node_id) != reason
            ):
                output.append(
                    creator.create(
                        DEAD_INPUT_DETECTED,
                        DeadInputDetectedPayload(
                            node_id=node_id,
                            from_node_id=dead_input[0],
                            to_port=dead_input[1],
                            reason=reason,
                        ),
                    )
                )
            _append_node_deferred_if_changed(output, projection, node_id, reason, creator)
            continue
        if node_state != "ready":
            output.append(creator.create(NODE_READY, NodeReadyPayload(node_id=node_id)))
            output.append(
                creator.create(
                    NODE_STATE_CHANGED,
                    NodeStateChangedPayload(
                        node_id=node_id,
                        new_state="ready",
                        trigger="readiness_evaluator",
                    ),
                )
            )
            readied_node_ids.add(node_id)
        nodes.append(replace(node, state="ready"))
    decision = schedule(
        nodes,
        projection["run_state"] or "draft",
        active_claims,
        _current_position(events, context),
        max_grants=command.max_grants,
    )
    for node_id in decision.selected:
        claims = projection["node_resource_claims"].get(node_id, [])
        lease_id = command.lease_ids.get(node_id) if command.lease_ids is not None else None
        if lease_id is None:
            lease_id = context.id_generator.next_id("lease")
        base_snapshot_id = _base_snapshot_id_for_node(projection, command, node_id)
        if base_snapshot_id is None:
            _append_node_deferred_if_changed(
                output, projection, node_id, "missing_base_snapshot", creator
            )
            continue
        if node_id not in readied_node_ids:
            output.append(creator.create(NODE_READY, NodeReadyPayload(node_id=node_id)))
        planner_session_id = _planner_session_id(projection, node_id, context)
        lease_generation = _next_lease_generation(projection, node_id)
        output.append(
            creator.create(
                LEASE_GRANTED,
                LeaseGrantedPayload(
                    lease_id=lease_id,
                    node_id=node_id,
                    generation=lease_generation,
                    execution_id=context.id_generator.next_id("exec"),
                    base_snapshot_id=base_snapshot_id,
                    expires_at=context.clock.now() + timedelta(seconds=command.lease_seconds),
                    resource_claims=tuple(
                        ResourceClaimProjection.model_validate(claim) for claim in claims
                    ),
                    session_id=planner_session_id,
                ),
            )
        )
        if planner_session_id is not None:
            output.append(
                creator.create(
                    SESSION_STATE_CHANGED,
                    PlannerSessionStateChangedPayload(
                        session_id=planner_session_id,
                        state="attached",
                        node_id=node_id,
                        lease_generation=lease_generation,
                        carryover_record_id=_session_carryover_record_id(projection, node_id),
                    ),
                )
            )
        output.append(
            creator.create(
                NODE_STATE_CHANGED,
                NodeStateChangedPayload(
                    node_id=node_id,
                    new_state="leased",
                    trigger="scheduler_grants_lease",
                ),
            )
        )
    for node_id in decision.deferred:
        _append_node_deferred_if_changed(
            output, projection, node_id, decision.deferred_reasons[node_id], creator
        )
    return output


def _append_node_deferred_if_changed(
    output: list[HydratedEvent],
    projection: GraphProjection,
    node_id: str,
    reason: str,
    creator: TypedEventCreator,
) -> None:
    if projection.get("last_deferred_reasons", {}).get(node_id) == reason:
        return
    output.append(
        creator.create(NODE_DEFERRED, NodeDeferredPayload(node_id=node_id, reason=reason))
    )


def _dead_input_from_readiness(node: NodeScheduleInfo, reason: str) -> tuple[str, str] | None:
    prefix = "upstream_failed:"
    if not reason.startswith(prefix):
        return None
    from_node_id = reason.removeprefix(prefix)
    for edge in node.required_edges:
        if edge.from_node_id == from_node_id:
            return from_node_id, edge.to_port
    return from_node_id, ""


def _base_snapshot_id_for_node(
    projection: GraphProjection,
    command: ScheduleTickCommand,
    node_id: str,
) -> str | None:
    if command.base_snapshot_id:
        return command.base_snapshot_id
    bindings = projection["input_bindings"].get(node_id, {})
    for port in ("base_snapshot", "root_snapshot", "routine_snapshot"):
        record_ids = bindings.get(port, {}).get("record_ids")
        if isinstance(record_ids, list) and record_ids:
            first_record_id = cast(list[Any], record_ids)[0]
            if isinstance(first_record_id, str) and first_record_id:
                return first_record_id
    return None


def _retry_backoff_deferred_reason(
    projection: GraphProjection, node_id: str, now: datetime
) -> str | None:
    retry_not_before = projection["retry_not_before_by_node"].get(node_id)
    if retry_not_before is None:
        return None
    try:
        retry_at = datetime.fromisoformat(retry_not_before)
    except ValueError:
        return None
    if retry_at <= now:
        return None
    return f"retry_backoff_until:{retry_not_before}"


def _planner_session_id(
    projection: GraphProjection,
    node_id: str,
    context: CommandExecutionContext,
) -> str | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = projection["planner_sessions"].values.get(node_id)
    if isinstance(session_id, str):
        return session_id
    return context.id_generator.next_id("session")


def _next_lease_generation(projection: GraphProjection, node_id: str) -> int:
    if not _is_chain_planner(projection, node_id):
        return 1
    session_id = projection["planner_sessions"].values.get(node_id)
    generations = [
        lease.get("generation")
        for lease in projection["leases"].values()
        if session_id is not None
        and lease.get("session_id") == session_id
        and isinstance(lease.get("generation"), int)
    ]
    return max(cast(list[int], generations), default=0) + 1


def _session_carryover_record_id(projection: GraphProjection, node_id: str) -> str | None:
    binding = projection["input_bindings"].get(node_id, {}).get("session_carryover")
    if binding is None:
        return None
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list) or not record_ids:
        return None
    record_id = cast(list[Any], record_ids)[0]
    return record_id if isinstance(record_id, str) else None


def _is_chain_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "planner"
        and projection["node_roles"].get(node_id) == "planner"
    )


def _expired_lease_events(
    projection: GraphProjection, now: datetime, creator: TypedEventCreator
) -> list[HydratedEvent]:
    expired: list[HydratedEvent] = []
    for lease in projection["leases"].values():
        if not _lease_is_expired(lease, now):
            continue
        node_id = lease.get("node_id")
        expires_at = datetime.fromisoformat(cast(str, lease.get("expires_at")))
        expired.append(
            creator.create(
                LEASE_EXPIRED,
                LeaseExpiredPayload(
                    lease_id=cast(str, lease.get("lease_id")),
                    node_id=cast(str, node_id),
                    generation=cast(int, lease.get("generation")),
                    execution_id=cast(str, lease.get("execution_id")),
                    expires_at=expires_at,
                    reason="lease_expired_without_callback",
                ),
            )
        )
        if isinstance(node_id, str):
            lease_id = lease.get("lease_id")
            typed_lease_id = lease_id if isinstance(lease_id, str) else None
            expired.append(
                creator.create(
                    OUTPUT_RECORD_ACCEPTED,
                    OutputRecordAcceptedPayload(
                        record=StrictFailureRecord(
                            record_id=(
                                f"failure-{node_id}-"
                                f"{typed_lease_id or 'lease_expired_without_callback'}"
                            ),
                            record_kind="graph_record",
                            record_type="failure_record",
                            producer_node_id=node_id,
                            port="failure_record",
                            schema="FailureRecord",
                            value=StrictFailureRecordValue(
                                failed_node_id=node_id,
                                phase="runtime",
                                error_class="lease_expired_without_callback",
                                retryable=False,
                                lease_id=typed_lease_id,
                                execution_id=cast(str | None, lease.get("execution_id")),
                                lease_generation=cast(int | None, lease.get("generation")),
                                reason="lease_expired_without_callback",
                                expires_at=cast(str | None, lease.get("expires_at")),
                            ),
                        )
                    ),
                )
            )
            expired.append(
                creator.create(
                    NODE_STATE_CHANGED,
                    NodeStateChangedPayload(
                        node_id=node_id,
                        new_state="failed",
                        trigger="lease_expired_without_callback",
                        reason="lease_expired_without_callback",
                    ),
                )
            )
    return expired


def _expired_active_lease_ids(projection: GraphProjection, now: datetime) -> set[str]:
    return {
        lease_id
        for lease in projection["leases"].values()
        if isinstance((lease_id := lease.get("lease_id")), str) and _lease_is_expired(lease, now)
    }


def _lease_is_expired(lease: dict[str, Any], now: datetime) -> bool:
    if lease.get("state") != "active":
        return False
    expires_at = lease.get("expires_at")
    return isinstance(expires_at, str) and datetime.fromisoformat(expires_at) <= now


def _current_position(events: tuple[HydratedEvent, ...], context: CommandExecutionContext) -> int:
    if not events:
        return context.current_position
    return max(event.metadata.position for event in events)


def _typed_reconcile(
    command: ReconcileCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
):
    del command
    return reconcile_events(
        projection, events, context, TypedEventCreator(context, causation_id="reconcile")
    )


def reconcile_events(
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    """Produce typed recovery events for a quiescent active graph."""

    del events
    del context
    run_state = projection["run_state"]
    if run_state in TERMINAL_RUN_STATES:
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(
                    command_type="reconcile",
                    reason=f"terminal run: {run_state}",
                ),
            )
        ]
    active_leases = active_lease_node_ids(projection)
    output: list[HydratedEvent] = []
    output.extend(failed_check_recovery_events(projection, active_leases, creator))
    output.extend(failed_verification_recovery_events(projection, active_leases, creator))
    output.extend(passed_verification_terminalization_events(projection, active_leases, creator))
    output.extend(passed_check_terminalization_events(projection, active_leases, creator))
    output.extend(no_successor_recovery_terminal_failure_events(projection, active_leases, creator))
    return dedupe_repair_events(output)


SCHEDULE_TICK = CommandSpecification("schedule_tick", ScheduleTickCommand, _typed_schedule)
RECONCILE = CommandSpecification("reconcile", ReconcileCommand, _typed_reconcile)
COMMAND_SPECIFICATIONS = (SCHEDULE_TICK, RECONCILE)


__all__ = [
    "RECONCILE",
    "SCHEDULE_TICK",
    "ReconcileCommand",
    "ScheduleTickCommand",
]
