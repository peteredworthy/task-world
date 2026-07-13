"""Strict record-evaluation command specifications."""

from __future__ import annotations

from orchestrator.graph.events.leases import LEASE_RELEASED, LeaseReleasedPayload
from orchestrator.graph.events.lifecycle import COMMAND_REJECTED, CommandRejectedPayload
from orchestrator.graph.events.records import OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload
from orchestrator.graph.events.topology import NODE_STATE_CHANGED, NodeStateChangedPayload
from orchestrator.graph.models import (
    EventEnvelope,
    StrictCompletionDecisionRecord,
    StrictJoinResultRecord,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.projections import GraphProjection, final_invariant_blockers_for_events
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)


class EvaluateJoinCommand(StrictPayload):
    node_id: str
    record_id: str | None = None
    lease_id: str | None = None
    lease_generation: int | None = None


class EvaluateFinalGateCommand(StrictPayload):
    node_id: str
    record_id: str | None = None
    lease_id: str | None = None
    lease_generation: int | None = None


def _command_rejected(
    command_type: str, reason: str, context: CommandExecutionContext
) -> HydratedEvent:
    return COMMAND_REJECTED.create(
        context.event_metadata(COMMAND_REJECTED.name),
        CommandRejectedPayload(command_type=command_type, reason=reason),
    )


def _lease_release(
    command: EvaluateJoinCommand | EvaluateFinalGateCommand,
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    if command.lease_id is None or command.lease_generation is None:
        return []
    return [
        LEASE_RELEASED.create(
            context.event_metadata(LEASE_RELEASED.name),
            LeaseReleasedPayload(
                node_id=command.node_id,
                lease_id=command.lease_id,
                generation=command.lease_generation,
            ),
        )
    ]


def _join_completed(
    node_id: str, record_id: str, context: CommandExecutionContext
) -> HydratedEvent:
    return NODE_STATE_CHANGED.create(
        context.event_metadata(NODE_STATE_CHANGED.name),
        NodeStateChangedPayload(
            node_id=node_id,
            new_state="completed",
            trigger="join_evaluated",
            join_result_record_id=record_id,
        ),
    )


def handle_evaluate_join(
    command: EvaluateJoinCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    if projection["node_kinds"].get(command.node_id) != "join":
        return [_command_rejected("evaluate_join", "node is not a join", context)]
    source_record_ids: list[str] = []
    for binding in projection["input_bindings"].get(command.node_id, {}).values():
        for record_id in binding.record_ids:
            if record_id not in source_record_ids:
                source_record_ids.append(record_id)
    if not source_record_ids:
        return [_command_rejected("evaluate_join", "join has no bound source records", context)]
    record_id = command.record_id or context.id_generator.next_id("join-result")
    record = StrictJoinResultRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "join_result",
            "producer_node_id": command.node_id,
            "port": "join_result",
            "schema": "JoinResult",
            "value": {"status": "ready", "source_record_ids": source_record_ids},
        }
    )
    return [
        OUTPUT_RECORD_ACCEPTED.create(
            context.event_metadata(OUTPUT_RECORD_ACCEPTED.name),
            OutputRecordAcceptedPayload(record=record),
        ),
        _join_completed(command.node_id, record_id, context),
        *_lease_release(command, context),
    ]


def handle_evaluate_final_gate(
    command: EvaluateFinalGateCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    if projection["node_kinds"].get(command.node_id) != "final_gate":
        return [_command_rejected("evaluate_final_gate", "node is not a final_gate", context)]
    blockers = final_invariant_blockers_for_events(
        list(events), projection, include_completion_decision=False
    )
    status = "blocked" if blockers else "passed"
    record_id = command.record_id or context.id_generator.next_id("completion-decision")
    record = StrictCompletionDecisionRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "completion_decision",
            "producer_node_id": command.node_id,
            "port": "completion_decision",
            "schema": "CompletionDecision",
            "value": {"status": status, "blockers": blockers},
            "provenance": {"source": "final_gate_evaluated"},
        }
    )
    return [
        OUTPUT_RECORD_ACCEPTED.create(
            context.event_metadata(OUTPUT_RECORD_ACCEPTED.name),
            OutputRecordAcceptedPayload(record=record),
        ),
        NODE_STATE_CHANGED.create(
            context.event_metadata(NODE_STATE_CHANGED.name),
            NodeStateChangedPayload(
                node_id=command.node_id,
                new_state="completed",
                trigger="final_gate_evaluated",
                completion_status=status,
                completion_decision_record_id=record_id,
            ),
        ),
        *_lease_release(command, context),
    ]


EVALUATE_JOIN = CommandSpecification("evaluate_join", EvaluateJoinCommand, handle_evaluate_join)
EVALUATE_FINAL_GATE = CommandSpecification(
    "evaluate_final_gate", EvaluateFinalGateCommand, handle_evaluate_final_gate
)
COMMAND_SPECIFICATIONS = (EVALUATE_JOIN, EVALUATE_FINAL_GATE)


__all__ = [
    "EVALUATE_FINAL_GATE",
    "EVALUATE_JOIN",
    "COMMAND_SPECIFICATIONS",
    "EvaluateFinalGateCommand",
    "EvaluateJoinCommand",
    "handle_evaluate_final_gate",
    "handle_evaluate_join",
]
