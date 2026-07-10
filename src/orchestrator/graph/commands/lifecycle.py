"""Lifecycle command specifications and compatibility handlers."""

from __future__ import annotations
from datetime import timedelta
from orchestrator.graph._commands import Clock, future_command_effects
from typing import Any
from orchestrator.graph.models import (
    EventEnvelope,
)
from orchestrator.graph.projections import (
    GraphProjection,
    final_invariant_blockers_for_events,
)
from orchestrator.graph.events.lifecycle import (
    RUN_LIFECYCLE_CHANGED,
    COMMAND_REJECTED,
    RUNTIME_RETRY_SCHEDULED,
    AGENT_DIED,
)
from orchestrator.graph._commands import (
    IdGenerator,
    NONTERMINAL_RUN_STATES,
    REOPEN_ACTOR_ROLES,
    RUN_LIFECYCLE_TRANSITIONS,
    TERMINAL_RUN_STATES,
)

from collections.abc import Callable

from pydantic import Field

from orchestrator.graph._commands import (
    event_factory,
)
from orchestrator.graph.events.lifecycle import (
    HEARTBEAT_RECORDED,
    HeartbeatRecordedPayload,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.commands.future_effects import require_future_effect
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
    FutureCommandEffects,
    StoredEventEnvelope,
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


def _lifecycle_handler(command_type: str):
    def handler(
        command: EmptyLifecycleCommand | FailCommand,
        projection: GraphProjection,
        events: tuple[EventEnvelope, ...],
        context: CommandExecutionContext,
    ) -> list[EventEnvelope | HydratedEvent]:
        payload = command.model_dump(mode="python")
        if context.actor.role is not None:
            payload["actor_role"] = context.actor.role
        elif context.actor.kind.value == "human":
            payload["actor_role"] = "human"
        make_event = event_factory(
            context.run_id, command_type, context.clock, context.id_generator
        )
        output = temporary_unconverted_lifecycle_effects(
            projection,
            list(events),
            command_type,
            payload,
            make_event,
            context.id_generator,
            context.future_effects,
        )
        return _hydrate_converted_lifecycle_outcomes(output)

    return handler


_LIFECYCLE_OUTCOME_SPECS = {
    spec.name: spec
    for spec in (
        RUN_LIFECYCLE_CHANGED,
        COMMAND_REJECTED,
        AGENT_DIED,
        RUNTIME_RETRY_SCHEDULED,
    )
}


def _hydrate_converted_lifecycle_outcomes(
    output: list[EventEnvelope],
) -> list[EventEnvelope | HydratedEvent]:
    """Task 9 deletes this adapter after Tasks 3/4 specify all side effects."""

    converted: list[EventEnvelope | HydratedEvent] = []
    for event in output:
        specification = _LIFECYCLE_OUTCOME_SPECS.get(event.event_type)
        if specification is None:
            converted.append(require_future_effect(event))
            continue
        stored = event.model_dump()
        stored["payload_schema_generation"] = stored.pop("schema_version")
        converted.append(specification.hydrate(StoredEventEnvelope.model_validate(stored)))
    return converted


def handle_record_heartbeat(
    command: RecordHeartbeatCommand,
    projection: GraphProjection,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del projection
    del events
    payload = HeartbeatRecordedPayload(
        node_id=command.node_id,
        lease_id=command.lease_id,
        lease_generation=command.lease_generation,
        observed_at=context.clock.now(),
    )
    return [
        HEARTBEAT_RECORDED.create(
            context.event_metadata(HEARTBEAT_RECORDED.name),
            payload,
        )
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
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[EventEnvelope | HydratedEvent]:
    del events
    make_event = event_factory(
        context.run_id,
        "agent_died",
        context.clock,
        context.id_generator,
    )
    output = build_agent_died_effects(
        projection,
        command.model_dump(mode="python"),
        context.clock,
        make_event,
        context.future_effects,
    )
    return _hydrate_converted_lifecycle_outcomes(output)


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


def handle_lifecycle_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    """Temporary adapter for lifecycle commands outside the Task 1 slice."""

    del clock
    return temporary_unconverted_lifecycle_effects(
        projection,
        events,
        command_type,
        payload,
        make_event,
        id_gen,
        future_command_effects(),
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
    "handle_lifecycle_command",
    "handle_record_heartbeat",
    "temporary_unconverted_lifecycle_effects",
    "_apply_agent_died",
]


def temporary_unconverted_lifecycle_effects(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
    effects: FutureCommandEffects,
) -> list[EventEnvelope]:
    _cancel_active_lease_events = effects.cancel_active_lease_events
    _command_rejected = effects.command_rejected
    _has_passed_completion_decision = effects.has_passed_completion_decision
    _lifecycle_completion_decision_event = effects.lifecycle_completion_decision_event
    _lifecycle_event = effects.lifecycle_event
    _make_strict_event = effects.make_strict_event
    current_state = projection["run_state"] or "draft"
    if command_type == "fail":
        if current_state in NONTERMINAL_RUN_STATES:
            return [
                _lifecycle_event(
                    make_event,
                    command_type,
                    current_state,
                    "failed",
                    payload.get("reason", "unrecoverable_controller_error"),
                )
            ]
        return [_command_rejected(make_event, command_type, f"terminal run: {current_state}")]

    next_state = RUN_LIFECYCLE_TRANSITIONS[command_type].get(current_state)
    if next_state is None:
        reason = (
            f"terminal run: {current_state}"
            if current_state in TERMINAL_RUN_STATES
            else f"illegal transition from {current_state}"
        )
        return [_command_rejected(make_event, command_type, reason)]
    if command_type == "resume" and current_state == "failed":
        actor_role = payload.get("actor_role")
        if actor_role not in REOPEN_ACTOR_ROLES:
            return [
                _command_rejected(
                    make_event,
                    command_type,
                    "reopen from failed requires an operator: "
                    f"actor_role must be one of {sorted(REOPEN_ACTOR_ROLES)}",
                )
            ]
    if command_type == "complete":
        blockers = final_invariant_blockers_for_events(events, projection)
        if blockers:
            return [
                _make_strict_event(
                    make_event,
                    COMMAND_REJECTED,
                    {
                        "command_type": command_type,
                        "reason": "final invariant blockers remain",
                        "blockers": blockers,
                    },
                )
            ]
    trigger = payload.get("trigger", f"{command_type}_command_accepted")
    output: list[EventEnvelope] = []
    if command_type == "complete" and not _has_passed_completion_decision(projection):
        output.append(_lifecycle_completion_decision_event(payload, make_event, id_gen))
    output.append(
        _lifecycle_event(
            make_event,
            command_type,
            current_state,
            next_state,
            trigger,
        )
    )
    if command_type == "cancel":
        output.extend(_cancel_active_lease_events(projection, make_event, trigger))
    return output


def _apply_agent_died(
    projection: GraphProjection,
    payload: dict[str, Any],
    clock: Clock,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    effects: FutureCommandEffects,
) -> list[EventEnvelope]:
    _command_rejected = effects.command_rejected
    _failure_record_payload = effects.failure_record_payload
    _is_non_retryable_runtime_death = effects.is_non_retryable_runtime_death
    _is_rate_limit_death = effects.is_rate_limit_death
    _make_strict_event = effects.make_strict_event
    _non_gap_planner_has_accepted_patch = effects.non_gap_planner_has_accepted_patch
    _positive_int = effects.positive_int
    _recovery_plan_record_payload = effects.recovery_plan_record_payload
    _typed_lease_event_payload = effects.typed_lease_event_payload
    lease_id = payload.get("lease_id")
    if not isinstance(lease_id, str):
        return [_command_rejected(make_event, "agent_died", "missing lease_id")]

    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "agent_died", "unknown lease")]
    if lease.get("state") != "active":
        return [_command_rejected(make_event, "agent_died", "lease not active")]

    execution_id = payload.get("execution_id")
    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str):
        # A lease with a recorded execution requires the caller to present the
        # matching execution identity — omitting it cannot revoke the lease.
        if not isinstance(execution_id, str):
            return [_command_rejected(make_event, "agent_died", "missing execution_id")]
        if execution_id != lease_execution_id:
            return [_command_rejected(make_event, "agent_died", "execution_incompatible")]

    node_id = str(lease.get("node_id"))
    generation = lease.get("generation")
    reason = str(payload.get("reason", "runtime_process_died"))
    event_payload = {
        "lease_id": lease_id,
        "node_id": node_id,
        "generation": generation,
        "execution_id": lease_execution_id if isinstance(lease_execution_id, str) else execution_id,
        "reason": reason,
    }

    if _non_gap_planner_has_accepted_patch(projection, node_id):
        return [
            _make_strict_event(make_event, AGENT_DIED, event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "completed",
                    "trigger": "accepted_graph_patch_before_agent_death",
                },
            ),
        ]

    if _is_rate_limit_death(reason):
        return [
            _make_strict_event(make_event, AGENT_DIED, event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
                    error_class="agent_rate_limited",
                    retryable=False,
                    lease_id=lease_id,
                    execution_id=event_payload.get("execution_id"),
                    generation=generation,
                    reason=reason,
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": "agent_rate_limited",
                    "reason": reason,
                },
            ),
        ]

    if _is_non_retryable_runtime_death(reason):
        return [
            _make_strict_event(make_event, AGENT_DIED, event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
                    error_class="runtime_configuration_error",
                    retryable=False,
                    lease_id=lease_id,
                    execution_id=event_payload.get("execution_id"),
                    generation=generation,
                    reason=reason,
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": "non_retryable_runtime_error",
                    "reason": reason,
                },
            ),
        ]

    max_attempts = _positive_int(payload.get("max_attempts"), 0)
    attempt_number = projection["node_attempts"].get(node_id, 0)
    if max_attempts > 0 and attempt_number >= max_attempts:
        return [
            _make_strict_event(make_event, AGENT_DIED, event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
                    error_class="max_attempts_exhausted",
                    retryable=False,
                    lease_id=lease_id,
                    execution_id=event_payload.get("execution_id"),
                    generation=generation,
                    reason=reason,
                    metadata={"attempt_number": attempt_number, "max_attempts": max_attempts},
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": "max_attempts_exhausted",
                    "reason": "max_attempts_exhausted",
                    "attempt_number": attempt_number,
                    "max_attempts": max_attempts,
                },
            ),
        ]

    # V1 retry policy: runtime death before an accepted boundary requeues the
    # same executable node. No new retry node is created until output/file-state
    # acceptance semantics exist in the graph runtime slice.
    retry_backoff_seconds = _positive_int(payload.get("retry_backoff_seconds"), 0)
    retry_payload: dict[str, Any] = {
        "node_id": node_id,
        "lease_id": lease_id,
        "generation": generation,
        "policy": "v1_requeue_same_node_after_agent_death",
        "reason": reason,
    }
    next_attempt_number = attempt_number + 1
    node_state_payload = {
        "node_id": node_id,
        "new_state": "ready",
        "trigger": "agent_died_retry_scheduled",
        "attempt_number": next_attempt_number,
    }
    if retry_backoff_seconds > 0:
        retry_not_before = (clock.now() + timedelta(seconds=retry_backoff_seconds)).isoformat()
        retry_payload["retry_after_seconds"] = retry_backoff_seconds
        retry_payload["retry_not_before"] = retry_not_before
        node_state_payload = {
            "node_id": node_id,
            "new_state": "blocked",
            "trigger": "agent_died_retry_backoff_scheduled",
            "retry_not_before": retry_not_before,
            "attempt_number": next_attempt_number,
        }
    return [
        _make_strict_event(make_event, AGENT_DIED, event_payload),
        make_event(
            "lease_revoked",
            _typed_lease_event_payload(
                "lease_revoked",
                {
                    "lease_id": lease_id,
                    "node_id": node_id,
                    "generation": generation,
                    "reason": reason,
                },
            ),
        ),
        _make_strict_event(make_event, RUNTIME_RETRY_SCHEDULED, retry_payload),
        make_event(
            "output_record_accepted",
            _recovery_plan_record_payload(
                node_id=node_id,
                retry_payload=retry_payload,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
        ),
        make_event(
            "node_state_changed",
            node_state_payload,
        ),
    ]


# Domain handlers use a policy-oriented name rather than a legacy applier name.
build_agent_died_effects = _apply_agent_died
