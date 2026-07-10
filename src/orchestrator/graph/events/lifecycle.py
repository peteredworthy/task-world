"""Strict lifecycle, callback, retry, and dispatch event specifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import Field

from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.models import CallbackIdempotencyEvent
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
    projection_neutral,
)


class RunLifecycleChangedPayload(StrictPayload):
    to_state: str
    command_type: str | None = None
    from_state: str | None = None
    trigger: str | None = None
    node_id: str | None = None
    patch_id: str | None = None
    recovery_of_node_id: str | None = None
    recovery_of_record_id: str | None = None
    recovery_reason: str | None = None
    reason: str | None = None


class CommandRejectedPayload(StrictPayload):
    command_type: str
    reason: str
    blockers: list[dict[str, JsonValue]] | None = None
    patch_id: str | None = None
    base_graph_position: int | str | None = None
    actor_role: str | None = None
    proposed_by_node_id: str | None = None
    rejection_reason: str | None = None
    diagnostics: JsonValue = None
    read_set_diff: dict[str, JsonValue] | None = None
    budget: int | None = None
    count: int | None = None


class CallbackPayload(StrictPayload):
    node_id: str
    lease_id: str | None = None
    lease_generation: int | None = Field(default=None, ge=0)
    idempotency_key: str
    payload: JsonValue
    reason: str


class CallbackAcceptedPayload(CallbackPayload):
    pass


class CallbackRejectedPayload(CallbackPayload):
    pass


class CallbackDuplicateReturnedPayload(CallbackPayload):
    prior_result: JsonValue | None


class RuntimeRetryScheduledPayload(StrictPayload):
    node_id: str
    lease_id: str
    generation: int = Field(ge=0)
    policy: str
    reason: str
    retry_after_seconds: int | None = Field(default=None, ge=0)
    retry_not_before: str | None = None


class HeartbeatRecordedPayload(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    observed_at: datetime


class AgentDiedPayload(StrictPayload):
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)
    execution_id: str | None = None
    reason: str


class AgentDispatchRequestedPayload(StrictPayload):
    lease_granted_event_id: str
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)
    execution_id: str
    base_snapshot_id: str
    resource_claims: list[dict[str, JsonValue]]


def _copy_state(state: Any) -> Any:
    return state.copy() if hasattr(state, "copy") else state


def reduce_run_lifecycle_changed(
    state: Any, payload: RunLifecycleChangedPayload, metadata: EventMetadata
) -> Any:
    del metadata
    next_state = _copy_state(state)
    next_state["run_state"] = payload.to_state
    return next_state


def reduce_callback_accepted(
    state: Any, payload: CallbackAcceptedPayload, metadata: EventMetadata
) -> Any:
    next_state = _copy_state(state)
    if payload.payload is not None and not isinstance(payload.payload, dict):
        return next_state
    callbacks = dict(next_state.get("callback_idempotency_events", {}))
    callbacks[f"{payload.node_id}\0{payload.idempotency_key}"] = CallbackIdempotencyEvent(
        event_type=cast(
            Literal[
                "callback_accepted",
                "callback_rejected_stale",
                "callback_rejected_conflict",
                "callback_duplicate_returned",
            ],
            metadata.event_type,
        ),
        node_id=payload.node_id,
        idempotency_key=payload.idempotency_key,
        outcome=metadata.event_type,
        payload=payload.payload if isinstance(payload.payload, dict) else None,
    )
    next_state["callback_idempotency_events"] = callbacks
    return next_state


def reduce_runtime_retry_scheduled(
    state: Any, payload: RuntimeRetryScheduledPayload, metadata: EventMetadata
) -> Any:
    del metadata
    next_state = _copy_state(state)
    retry_by_node = dict(next_state.get("retry_not_before_by_node", {}))
    if payload.retry_not_before is None:
        retry_by_node.pop(payload.node_id, None)
    else:
        retry_by_node[payload.node_id] = payload.retry_not_before
    next_state["retry_not_before_by_node"] = retry_by_node
    return next_state


RUN_LIFECYCLE_CHANGED = EventSpecification(
    "run_lifecycle_changed",
    RunLifecycleChangedPayload,
    reduce_run_lifecycle_changed,
    ProjectionParticipation.MUTATES,
)
COMMAND_REJECTED = EventSpecification(
    "command_rejected", CommandRejectedPayload, projection_neutral, ProjectionParticipation.NEUTRAL
)
CALLBACK_ACCEPTED = EventSpecification(
    "callback_accepted",
    CallbackAcceptedPayload,
    reduce_callback_accepted,
    ProjectionParticipation.MUTATES,
)
CALLBACK_REJECTED_STALE = EventSpecification(
    "callback_rejected_stale",
    CallbackRejectedPayload,
    projection_neutral,
    ProjectionParticipation.NEUTRAL,
)
CALLBACK_REJECTED_CONFLICT = EventSpecification(
    "callback_rejected_conflict",
    CallbackRejectedPayload,
    projection_neutral,
    ProjectionParticipation.NEUTRAL,
)
CALLBACK_DUPLICATE_RETURNED = EventSpecification(
    "callback_duplicate_returned",
    CallbackDuplicateReturnedPayload,
    projection_neutral,
    ProjectionParticipation.NEUTRAL,
)
RUNTIME_RETRY_SCHEDULED = EventSpecification(
    "runtime_retry_scheduled",
    RuntimeRetryScheduledPayload,
    reduce_runtime_retry_scheduled,
    ProjectionParticipation.MUTATES,
)
HEARTBEAT_RECORDED = EventSpecification(
    "heartbeat_recorded",
    HeartbeatRecordedPayload,
    projection_neutral,
    ProjectionParticipation.NEUTRAL,
)
AGENT_DIED = EventSpecification(
    "agent_died", AgentDiedPayload, projection_neutral, ProjectionParticipation.NEUTRAL
)
AGENT_DISPATCH_REQUESTED = EventSpecification(
    "agent_dispatch_requested",
    AgentDispatchRequestedPayload,
    projection_neutral,
    ProjectionParticipation.NEUTRAL,
)

LIFECYCLE_EVENT_SPECS = (
    RUN_LIFECYCLE_CHANGED,
    COMMAND_REJECTED,
    CALLBACK_ACCEPTED,
    CALLBACK_REJECTED_STALE,
    CALLBACK_REJECTED_CONFLICT,
    CALLBACK_DUPLICATE_RETURNED,
    RUNTIME_RETRY_SCHEDULED,
    HEARTBEAT_RECORDED,
    AGENT_DIED,
    AGENT_DISPATCH_REQUESTED,
)
EVENT_SPECIFICATIONS = LIFECYCLE_EVENT_SPECS

__all__ = [
    "AGENT_DIED",
    "AGENT_DISPATCH_REQUESTED",
    "CALLBACK_ACCEPTED",
    "CALLBACK_DUPLICATE_RETURNED",
    "CALLBACK_REJECTED_CONFLICT",
    "CALLBACK_REJECTED_STALE",
    "COMMAND_REJECTED",
    "EVENT_SPECIFICATIONS",
    "HEARTBEAT_RECORDED",
    "LIFECYCLE_EVENT_SPECS",
    "RUNTIME_RETRY_SCHEDULED",
    "RUN_LIFECYCLE_CHANGED",
    "AgentDiedPayload",
    "AgentDispatchRequestedPayload",
    "CallbackAcceptedPayload",
    "CallbackDuplicateReturnedPayload",
    "CallbackRejectedPayload",
    "CommandRejectedPayload",
    "HeartbeatRecordedPayload",
    "RunLifecycleChangedPayload",
    "RuntimeRetryScheduledPayload",
]
