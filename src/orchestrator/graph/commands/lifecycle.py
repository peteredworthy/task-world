"""Lifecycle command specifications and compatibility handlers."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Protocol
from orchestrator.graph.projections import (
    GraphProjection,
    final_invariant_blockers_for_events,
)
from orchestrator.graph.events.lifecycle import (
    RUN_LIFECYCLE_CHANGED,
    COMMAND_REJECTED,
    RUNTIME_RETRY_SCHEDULED,
    AGENT_DIED,
    AgentDiedPayload,
    CommandRejectedPayload,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
)
from orchestrator.graph.events.leases import (
    LEASE_RENEWED,
    LEASE_REVOKED,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
)
from pydantic import Field

from orchestrator.graph.events.lifecycle import (
    HEARTBEAT_RECORDED,
    HeartbeatRecordedPayload,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.commands.event_creator import TypedEventCreator
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph.events.records import OUTPUT_RECORD_ACCEPTED
from orchestrator.graph.events.records import OutputRecordAcceptedPayload
from orchestrator.graph.events.topology import NODE_STATE_CHANGED, NodeStateChangedPayload
from orchestrator.graph.models import (
    StrictCompletionDecisionRecord,
    StrictCompletionDecisionValue,
    StrictFailureRecord,
    StrictFailureRecordValue,
    StrictRecoveryPlanRecord,
    StrictRecoveryPlanValue,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


RUN_LIFECYCLE_TRANSITIONS: dict[str, dict[str, str]] = {
    "accept_run": {"draft": "queued"},
    "start": {"queued": "active"},
    "pause": {"active": "pausing", "pausing": "paused"},
    "resume": {"paused": "resuming", "resuming": "active", "failed": "resuming"},
    "cancel": {"active": "cancelling", "paused": "cancelling", "cancelling": "cancelled"},
    "complete": {"active": "completed"},
}
REOPEN_ACTOR_ROLES = {"human", "operator"}
TERMINAL_RUN_STATES = {"cancelled", "completed", "failed"}
NONTERMINAL_RUN_STATES = {
    "draft",
    "queued",
    "active",
    "pausing",
    "paused",
    "resuming",
    "cancelling",
}


def _command_rejected(
    creator: TypedEventCreator,
    command_type: str,
    reason: str,
    *,
    blockers: list[dict[str, Any]] | None = None,
) -> HydratedEvent:
    return creator.create(
        COMMAND_REJECTED,
        CommandRejectedPayload(command_type=command_type, reason=reason, blockers=blockers),
    )


def _lifecycle_event(
    creator: TypedEventCreator,
    command_type: str,
    from_state: str,
    to_state: str,
    trigger: str,
) -> HydratedEvent:
    return creator.create(
        RUN_LIFECYCLE_CHANGED,
        RunLifecycleChangedPayload(
            command_type=command_type,
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
        ),
    )


def _is_rate_limit_death(reason: str) -> bool:
    normalized = reason.lower()
    return any(token in normalized for token in ("rate limit", "usage limit", "quota"))


def _require_future_outcomes(
    output: list[HydratedEvent],
) -> list[HydratedEvent]:
    return output


def _is_non_retryable_runtime_death(reason: str) -> bool:
    return reason.startswith("check node missing command_definition") or reason.startswith(
        "check command_definition requires "
    )


def _non_gap_planner_has_accepted_patch(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection.get("node_kinds", {}).get(node_id) == "planner"
        and projection.get("node_roles", {}).get(node_id) != "gap_planner"
        and bool(projection.get("accepted_graph_patches_by_node", {}).get(node_id))
    )


class RecordHeartbeatCommand(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)


class EmptyLifecycleCommand(StrictPayload):
    pass


class FailCommand(StrictPayload):
    reason: str = "command_failed"


class AgentDiedCommand(StrictPayload):
    lease_id: str
    execution_id: str | None = None
    reason: str = "runtime_process_died"
    max_attempts: int = Field(default=0, ge=0)
    retry_backoff_seconds: int = Field(default=0, ge=0)


class FailureRecordInput(StrictPayload):
    node_id: str
    error_class: str
    lease_id: str
    execution_id: str
    generation: int = Field(ge=0)
    reason: str
    attempt_number: int | None = Field(default=None, ge=0)
    max_attempts: int | None = Field(default=None, ge=0)


class RecoveryPlanRecordInput(StrictPayload):
    node_id: str
    retry: RuntimeRetryScheduledPayload
    retry_backoff_seconds: int = Field(ge=0)


def _completion_decision_event(creator: TypedEventCreator, id_gen: IdGenerator) -> HydratedEvent:
    record = StrictCompletionDecisionRecord(
        record_id=id_gen.next_id("completion-decision"),
        record_kind="output",
        record_type="completion_decision",
        producer_node_id="run_lifecycle",
        port="completion_decision",
        schema="CompletionDecision",
        value=StrictCompletionDecisionValue(status="passed", blockers=[]),
        provenance={"source": "lifecycle_complete"},
    )
    return creator.create(OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload(record=record))


def _cancel_active_lease_events(
    projection: GraphProjection, creator: TypedEventCreator, trigger: str
) -> list[HydratedEvent]:
    output: list[HydratedEvent] = []
    for lease_id, lease in sorted(projection["leases"].items()):
        if lease.get("state") not in {"active", "suspended"}:
            continue
        node_id = lease.get("node_id")
        generation = lease.get("generation")
        execution_id = lease.get("execution_id")
        if not (
            isinstance(node_id, str)
            and isinstance(generation, int)
            and not isinstance(generation, bool)
            and isinstance(execution_id, str)
        ):
            continue
        output.append(
            creator.create(
                LEASE_REVOKED,
                LeaseRevokedPayload(
                    lease_id=lease_id,
                    node_id=node_id,
                    generation=generation,
                    execution_id=execution_id,
                    trigger=trigger,
                    reason="run_cancelled",
                ),
            )
        )
        if projection["node_states"].get(node_id) not in {
            "completed",
            "failed",
            "cancelled",
            "retired",
        }:
            output.append(
                creator.create(
                    NODE_STATE_CHANGED,
                    NodeStateChangedPayload(
                        node_id=node_id,
                        new_state="cancelled",
                        trigger="run_cancelled",
                        reason="run_cancelled",
                    ),
                )
            )
    return output


def _lease_revoked_event(creator: TypedEventCreator, died: AgentDiedPayload) -> HydratedEvent:
    if died.execution_id is None:
        raise ValueError("active lease agent death requires an execution_id")
    return creator.create(
        LEASE_REVOKED,
        LeaseRevokedPayload(
            lease_id=died.lease_id,
            node_id=died.node_id,
            generation=died.generation,
            execution_id=died.execution_id,
            trigger="agent_died",
            reason=died.reason,
        ),
    )


def _failure_record_event(creator: TypedEventCreator, request: FailureRecordInput) -> HydratedEvent:
    record = StrictFailureRecord(
        record_id=f"failure-{request.node_id}-{request.lease_id}",
        record_kind="graph_record",
        record_type="failure_record",
        producer_node_id=request.node_id,
        port="failure_record",
        schema="FailureRecord",
        value=StrictFailureRecordValue(
            failed_node_id=request.node_id,
            phase="runtime",
            error_class=request.error_class,
            retryable=False,
            lease_id=request.lease_id,
            execution_id=request.execution_id,
            lease_generation=request.generation,
            reason=request.reason,
            attempt_number=request.attempt_number,
            max_attempts=request.max_attempts,
        ),
    )
    return creator.create(OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload(record=record))


def _recovery_plan_record_event(
    creator: TypedEventCreator, request: RecoveryPlanRecordInput
) -> HydratedEvent:
    state = "ready" if request.retry_backoff_seconds <= 0 else "blocked"
    record = StrictRecoveryPlanRecord(
        record_id=f"recovery-plan-{request.node_id}-{request.retry.lease_id}",
        record_kind="output",
        record_type="recovery_plan",
        producer_node_id=request.node_id,
        port="recovery_plan",
        schema="RecoveryPlan",
        value=StrictRecoveryPlanValue(
            action="retry",
            responsible_actor="controller",
            graph_changes=[{"op": "set_node_state", "node_id": request.node_id, "state": state}],
            reason=request.retry.reason,
            retry_after_seconds=request.retry.retry_after_seconds,
            retry_not_before=request.retry.retry_not_before,
        ),
    )
    return creator.create(OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload(record=record))


def _lifecycle_handler(command_type: str):
    def handler(
        command: EmptyLifecycleCommand | FailCommand,
        projection: GraphProjection,
        events: tuple[HydratedEvent, ...],
        context: CommandExecutionContext,
    ) -> list[HydratedEvent]:
        actor_role = context.actor.role
        if actor_role is None and context.actor.kind.value == "human":
            actor_role = "human"
        creator = TypedEventCreator(context, assign_position=False, causation_id=command_type)
        output = apply_lifecycle_effects(
            projection,
            list(events),
            command_type,
            command,
            actor_role,
            creator,
            context.id_generator,
        )
        return _require_future_outcomes(output)

    return handler


def handle_record_heartbeat(
    command: RecordHeartbeatCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    heartbeat = HeartbeatRecordedPayload(
        node_id=command.node_id,
        lease_id=command.lease_id,
        lease_generation=command.lease_generation,
        observed_at=context.clock.now(),
    )
    creator = TypedEventCreator(context)
    lease = projection["leases"].get(command.lease_id)
    if lease is None:
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(
                    command_type="record_heartbeat", reason=f"unknown lease: {command.lease_id}"
                ),
            )
        ]
    if projection["run_state"] != "active":
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(command_type="record_heartbeat", reason="run_not_active"),
            )
        ]
    if lease.get("state") != "active":
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(
                    command_type="record_heartbeat", reason=f"lease_not_active:{lease.get('state')}"
                ),
            )
        ]
    if lease.get("node_id") != command.node_id:
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(command_type="record_heartbeat", reason="node_id_mismatch"),
            )
        ]
    generation = lease.get("generation")
    execution_id = lease.get("execution_id")
    if generation != command.lease_generation or not isinstance(execution_id, str):
        return [
            creator.create(
                COMMAND_REJECTED,
                CommandRejectedPayload(
                    command_type="record_heartbeat", reason="lease_generation_mismatch"
                ),
            )
        ]
    observed_at = context.clock.now()
    renewal_seconds = 300
    expires_at = lease.get("expires_at")
    if isinstance(expires_at, str) and datetime.fromisoformat(expires_at) <= observed_at:
        renewal_seconds = 3600
    return [
        creator.create(HEARTBEAT_RECORDED, heartbeat),
        creator.create(
            LEASE_RENEWED,
            LeaseRenewedPayload(
                lease_id=command.lease_id,
                node_id=command.node_id,
                generation=command.lease_generation,
                execution_id=execution_id,
                observed_at=observed_at,
                expires_at=observed_at + timedelta(seconds=renewal_seconds),
            ),
        ),
    ]


ACCEPT_RUN = CommandSpecification(
    "accept_run", EmptyLifecycleCommand, _lifecycle_handler("accept_run")
)
START = CommandSpecification("start", EmptyLifecycleCommand, _lifecycle_handler("start"))
PAUSE = CommandSpecification("pause", EmptyLifecycleCommand, _lifecycle_handler("pause"))
RESUME = CommandSpecification("resume", EmptyLifecycleCommand, _lifecycle_handler("resume"))
CANCEL = CommandSpecification("cancel", EmptyLifecycleCommand, _lifecycle_handler("cancel"))
COMPLETE = CommandSpecification("complete", EmptyLifecycleCommand, _lifecycle_handler("complete"))
FAIL = CommandSpecification("fail", FailCommand, _lifecycle_handler("fail"))

RECORD_HEARTBEAT = CommandSpecification(
    name="record_heartbeat",
    payload_type=RecordHeartbeatCommand,
    handler=handle_record_heartbeat,
)


def handle_agent_died_command(
    command: AgentDiedCommand,
    projection: GraphProjection,
    events: tuple[HydratedEvent, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(context, assign_position=False, causation_id="agent_died")
    output = build_agent_died_effects(
        projection,
        command,
        context.clock,
        creator,
    )
    return _require_future_outcomes(output)


AGENT_DIED_COMMAND = CommandSpecification("agent_died", AgentDiedCommand, handle_agent_died_command)

COMMAND_SPECIFICATIONS: tuple[CommandSpecification[Any], ...] = (
    ACCEPT_RUN,
    START,
    PAUSE,
    RESUME,
    CANCEL,
    COMPLETE,
    FAIL,
    RECORD_HEARTBEAT,
    AGENT_DIED_COMMAND,
)


__all__ = [
    "COMMAND_SPECIFICATIONS",
    "ACCEPT_RUN",
    "START",
    "PAUSE",
    "RESUME",
    "CANCEL",
    "COMPLETE",
    "FAIL",
    "AGENT_DIED_COMMAND",
    "RECORD_HEARTBEAT",
    "RecordHeartbeatCommand",
    "handle_record_heartbeat",
    "apply_lifecycle_effects",
    "build_agent_died_effects",
]


def apply_lifecycle_effects(
    projection: GraphProjection,
    events: list[HydratedEvent],
    command_type: str,
    command: EmptyLifecycleCommand | FailCommand,
    actor_role: str | None,
    creator: TypedEventCreator,
    id_gen: IdGenerator,
) -> list[HydratedEvent]:
    current_state = projection["run_state"] or "draft"
    if command_type == "fail":
        if current_state in NONTERMINAL_RUN_STATES:
            return [
                _lifecycle_event(
                    creator,
                    command_type,
                    current_state,
                    "failed",
                    command.reason
                    if isinstance(command, FailCommand)
                    else "unrecoverable_controller_error",
                )
            ]
        return [_command_rejected(creator, command_type, f"terminal run: {current_state}")]

    next_state = RUN_LIFECYCLE_TRANSITIONS[command_type].get(current_state)
    if next_state is None:
        reason = (
            f"terminal run: {current_state}"
            if current_state in TERMINAL_RUN_STATES
            else f"illegal transition from {current_state}"
        )
        return [_command_rejected(creator, command_type, reason)]
    if command_type == "resume" and current_state == "failed":
        if actor_role not in REOPEN_ACTOR_ROLES:
            return [
                _command_rejected(
                    creator,
                    command_type,
                    "reopen from failed requires an operator: "
                    f"actor_role must be one of {sorted(REOPEN_ACTOR_ROLES)}",
                )
            ]
    if command_type == "complete":
        blockers = final_invariant_blockers_for_events(events, projection)
        if blockers:
            rejected: list[HydratedEvent] = [
                _command_rejected(
                    creator,
                    command_type,
                    "final invariant blockers remain",
                    blockers=[dict(blocker) for blocker in blockers],
                )
            ]
            return rejected
    trigger = f"{command_type}_command_accepted"
    output: list[HydratedEvent] = []
    if command_type == "complete" and not projection["completion_decision_passed"]:
        output.append(_completion_decision_event(creator, id_gen))
    output.append(
        _lifecycle_event(
            creator,
            command_type,
            current_state,
            next_state,
            trigger,
        )
    )
    if command_type == "cancel":
        output.extend(_cancel_active_lease_events(projection, creator, trigger))
    return output


def build_agent_died_effects(
    projection: GraphProjection,
    command: AgentDiedCommand,
    clock: Clock,
    creator: TypedEventCreator,
) -> list[HydratedEvent]:
    lease_id = command.lease_id

    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(creator, "agent_died", "unknown lease")]
    if lease.get("state") != "active":
        return [_command_rejected(creator, "agent_died", "lease not active")]

    execution_id = command.execution_id
    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str):
        # A lease with a recorded execution requires the caller to present the
        # matching execution identity — omitting it cannot revoke the lease.
        if not isinstance(execution_id, str):
            return [_command_rejected(creator, "agent_died", "missing execution_id")]
        if execution_id != lease_execution_id:
            return [_command_rejected(creator, "agent_died", "execution_incompatible")]

    node_id = str(lease.get("node_id"))
    generation_value = lease.get("generation")
    generation = generation_value if isinstance(generation_value, int) else 0
    reason = command.reason
    agent_died_payload = AgentDiedPayload(
        lease_id=lease_id,
        node_id=node_id,
        generation=generation,
        execution_id=lease_execution_id if isinstance(lease_execution_id, str) else execution_id,
        reason=reason,
    )
    if agent_died_payload.execution_id is None:
        return [_command_rejected(creator, "agent_died", "missing execution_id")]

    if _non_gap_planner_has_accepted_patch(projection, node_id):
        return [
            creator.create(AGENT_DIED, agent_died_payload),
            _lease_revoked_event(creator, agent_died_payload),
            creator.create(
                NODE_STATE_CHANGED,
                NodeStateChangedPayload(
                    node_id=node_id,
                    new_state="completed",
                    trigger="accepted_graph_patch_before_agent_death",
                ),
            ),
        ]

    if _is_rate_limit_death(reason):
        return [
            creator.create(AGENT_DIED, agent_died_payload),
            _lease_revoked_event(creator, agent_died_payload),
            _failure_record_event(
                creator,
                FailureRecordInput(
                    node_id=node_id,
                    error_class="agent_rate_limited",
                    lease_id=lease_id,
                    execution_id=agent_died_payload.execution_id,
                    generation=generation,
                    reason=reason,
                ),
            ),
            creator.create(
                NODE_STATE_CHANGED,
                NodeStateChangedPayload(
                    node_id=node_id, new_state="failed", trigger="agent_rate_limited", reason=reason
                ),
            ),
        ]

    if _is_non_retryable_runtime_death(reason):
        return [
            creator.create(AGENT_DIED, agent_died_payload),
            _lease_revoked_event(creator, agent_died_payload),
            _failure_record_event(
                creator,
                FailureRecordInput(
                    node_id=node_id,
                    error_class="runtime_configuration_error",
                    lease_id=lease_id,
                    execution_id=agent_died_payload.execution_id,
                    generation=generation,
                    reason=reason,
                ),
            ),
            creator.create(
                NODE_STATE_CHANGED,
                NodeStateChangedPayload(
                    node_id=node_id,
                    new_state="failed",
                    trigger="non_retryable_runtime_error",
                    reason=reason,
                ),
            ),
        ]

    max_attempts = command.max_attempts
    attempt_number = projection["node_attempts"].get(node_id, 0)
    if max_attempts > 0 and attempt_number >= max_attempts:
        return [
            creator.create(AGENT_DIED, agent_died_payload),
            _lease_revoked_event(creator, agent_died_payload),
            _failure_record_event(
                creator,
                FailureRecordInput(
                    node_id=node_id,
                    error_class="max_attempts_exhausted",
                    lease_id=lease_id,
                    execution_id=agent_died_payload.execution_id,
                    generation=generation,
                    reason=reason,
                    attempt_number=attempt_number,
                    max_attempts=max_attempts,
                ),
            ),
            creator.create(
                NODE_STATE_CHANGED,
                NodeStateChangedPayload(
                    node_id=node_id,
                    new_state="failed",
                    trigger="max_attempts_exhausted",
                    reason="max_attempts_exhausted",
                    attempt_number=attempt_number,
                    max_attempts=max_attempts,
                ),
            ),
        ]

    # V1 retry policy: runtime death before an accepted boundary requeues the
    # same executable node. No new retry node is created until output/file-state
    # acceptance semantics exist in the graph runtime slice.
    retry_backoff_seconds = command.retry_backoff_seconds
    retry_payload = RuntimeRetryScheduledPayload(
        node_id=node_id,
        lease_id=lease_id,
        generation=generation,
        policy="v1_requeue_same_node_after_agent_death",
        reason=reason,
    )
    next_attempt_number = attempt_number + 1
    node_state_payload = NodeStateChangedPayload(
        node_id=node_id,
        new_state="ready",
        trigger="agent_died_retry_scheduled",
        attempt_number=next_attempt_number,
    )
    if retry_backoff_seconds > 0:
        retry_not_before = (clock.now() + timedelta(seconds=retry_backoff_seconds)).isoformat()
        retry_payload = retry_payload.model_copy(
            update={
                "retry_after_seconds": retry_backoff_seconds,
                "retry_not_before": retry_not_before,
            }
        )
        node_state_payload = NodeStateChangedPayload(
            node_id=node_id,
            new_state="blocked",
            trigger="agent_died_retry_backoff_scheduled",
            retry_not_before=retry_not_before,
            attempt_number=next_attempt_number,
        )
    return [
        creator.create(AGENT_DIED, agent_died_payload),
        _lease_revoked_event(creator, agent_died_payload),
        creator.create(RUNTIME_RETRY_SCHEDULED, retry_payload),
        _recovery_plan_record_event(
            creator,
            RecoveryPlanRecordInput(
                node_id=node_id, retry=retry_payload, retry_backoff_seconds=retry_backoff_seconds
            ),
        ),
        creator.create(NODE_STATE_CHANGED, node_state_payload),
    ]
