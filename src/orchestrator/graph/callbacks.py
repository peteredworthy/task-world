"""Pure callback validation for execution graph leases."""

from dataclasses import dataclass
from typing import Any, Sequence, cast

from orchestrator.graph.models import EventEnvelope
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.specifications import HydratedEvent

GraphHistoryEvent = EventEnvelope | HydratedEvent


@dataclass(frozen=True)
class CallbackRequest:
    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int
    base_snapshot_id: str
    observed_graph_position: int
    idempotency_key: str
    payload: dict[str, Any] | None = None
    is_mutating: bool = True


class CallbackOutcome:
    ACCEPTED = "accepted"
    REJECTED_STALE = "rejected_stale"
    REJECTED_CONFLICT = "rejected_conflict"
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    DUPLICATE_IDEMPOTENT = "duplicate_idempotent"


@dataclass(frozen=True)
class CallbackValidationResult:
    outcome: str
    reason: str
    prior_result: dict[str, Any] | None = None


# Only a prior ACCEPTED callback may short-circuit idempotency validation.
# Rejection events (stale/conflict) must never poison the idempotency key: the
# dispatch layer reuses a fixed key per execution, so if a rejection were
# eligible to match here, a corrected retry would be permanently blocked
# (matching payload -> replayed as a "duplicate" of the rejection; corrected
# payload -> rejected as a conflict). `callback_duplicate_returned` is also
# excluded: it merely records a replay of some prior event, so a genuine
# duplicate-of-a-duplicate still finds the original `callback_accepted` event
# via this same lookup, and a duplicate-of-a-rejection correctly falls through
# to fresh validation instead of re-replaying the rejection.
_IDEMPOTENCY_EVENT_TYPES = {
    "callback_accepted",
}

_STALE_LEASE_STATES = {"revoked"}
_TERMINAL_NODE_STATES = {"completed", "failed", "cancelled", "retired"}
_TERMINAL_RUN_STATES = {"cancelled", "failed"}


def validate_callback(
    request: CallbackRequest,
    projection: GraphProjection,
    events: Sequence[GraphHistoryEvent],
) -> CallbackValidationResult:
    """Validate a callback against prior idempotency events and graph projection."""

    idempotency_result = _validate_idempotency(request, projection, events)
    if idempotency_result is not None:
        return idempotency_result

    lease = projection["leases"].get(request.lease_id)
    if lease is None:
        return _rejected_stale("unknown lease")

    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str) and lease_execution_id != request.execution_id:
        return _rejected_stale("execution_incompatible")

    lease_base_snapshot_id = lease.get("base_snapshot_id")
    if (
        isinstance(lease_base_snapshot_id, str)
        and lease_base_snapshot_id != request.base_snapshot_id
    ):
        return _rejected_stale("snapshot_incompatible")

    generation = lease.get("generation")
    if isinstance(generation, int) and request.lease_generation != generation:
        return _rejected_stale("lease_generation_incompatible")

    lease_state = lease.get("state")
    accepting_late_expired_lease = False
    if lease_state in _STALE_LEASE_STATES:
        return _rejected_stale(f"lease {lease_state}")
    if lease_state == "suspended" and request.is_mutating:
        return _rejected_stale("lease suspended")
    if lease_state == "released":
        return _rejected_stale("lease released, use idempotency key")

    run_state = projection["run_state"]
    if run_state in _TERMINAL_RUN_STATES:
        return _rejected_stale(f"run {run_state}")

    if lease_state == "expired":
        expired_result = _validate_expired_lease_callback(
            request,
            projection,
            events,
            lease,
        )
        if expired_result.outcome != CallbackOutcome.ACCEPTED:
            return expired_result
        accepting_late_expired_lease = True

    node_state = projection["node_states"].get(request.node_id)
    if (
        request.is_mutating
        and node_state in _TERMINAL_NODE_STATES
        and not accepting_late_expired_lease
    ):
        return _rejected_stale(f"node {node_state}")
    if request.is_mutating and node_state != "running" and not accepting_late_expired_lease:
        return CallbackValidationResult(
            outcome=CallbackOutcome.REJECTED_CONFLICT,
            reason=f"node not running: {node_state}",
        )

    return CallbackValidationResult(
        outcome=CallbackOutcome.ACCEPTED,
        reason="accepted_late_expired_lease" if accepting_late_expired_lease else "accepted",
    )


def _validate_expired_lease_callback(
    request: CallbackRequest,
    projection: GraphProjection,
    events: Sequence[GraphHistoryEvent],
    request_lease: dict[str, Any],
) -> CallbackValidationResult:
    if _has_replacement_active_lease(projection, request.lease_id, request.node_id):
        return _rejected_stale("lease expired and redispatched")
    if not _lease_expiry_recorded(events, request.lease_id, request.node_id):
        return _rejected_stale("lease expired")
    node_state = projection["node_states"].get(request.node_id)
    if node_state == "running" or _latest_node_failure_is_lease_expiry(events, request.node_id):
        return CallbackValidationResult(
            outcome=CallbackOutcome.ACCEPTED,
            reason="accepted_late_expired_lease",
        )
    return _rejected_stale("lease expired")


def _has_replacement_active_lease(
    projection: GraphProjection,
    request_lease_id: str,
    node_id: str,
) -> bool:
    for lease_id, lease in projection["leases"].items():
        if lease_id == request_lease_id:
            continue
        if lease.get("node_id") != node_id:
            continue
        if lease.get("state") in {"active", "suspended"}:
            return True
    return False


def _lease_expiry_recorded(
    events: Sequence[GraphHistoryEvent],
    lease_id: str,
    node_id: str,
) -> bool:
    return any(
        _history_event_type(event) == "lease_expired"
        and _history_payload_value(event, "lease_id") == lease_id
        and _history_payload_value(event, "node_id") == node_id
        for event in events
    )


def _latest_node_failure_is_lease_expiry(events: Sequence[GraphHistoryEvent], node_id: str) -> bool:
    for event in reversed(events):
        if _history_event_type(event) != "node_state_changed":
            continue
        if _history_payload_value(event, "node_id") != node_id:
            continue
        if _history_payload_value(event, "new_state") != "failed":
            return False
        return (
            _history_payload_value(event, "trigger") == "lease_expired_without_callback"
            or _history_payload_value(event, "reason") == "lease_expired_without_callback"
        )
    return False


def _validate_idempotency(
    request: CallbackRequest,
    projection: GraphProjection,
    events: Sequence[GraphHistoryEvent],
) -> CallbackValidationResult | None:
    if not _has_full_event_history(events):
        projected = projection.get("callback_idempotency_events", {}).get(
            _callback_idempotency_projection_key(request.node_id, request.idempotency_key)
        )
        if projected is not None and projected.event_type == "callback_accepted":
            if projected.payload == request.payload:
                return CallbackValidationResult(
                    outcome=CallbackOutcome.DUPLICATE_IDEMPOTENT,
                    reason="duplicate idempotency key",
                    prior_result={
                        "outcome": projected.outcome,
                        "payload": projected.model_dump(
                            mode="json",
                            exclude={"event_type", "outcome"},
                        ),
                    },
                )
            return CallbackValidationResult(
                outcome=CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
                reason="idempotency payload conflict",
            )
    for event in events:
        if _history_event_type(event) not in _IDEMPOTENCY_EVENT_TYPES:
            continue
        if _history_payload_value(event, "idempotency_key") != request.idempotency_key:
            continue
        if _history_payload_value(event, "node_id") != request.node_id:
            continue

        if _stored_callback_payload(_history_payload(event)) == request.payload:
            return CallbackValidationResult(
                outcome=CallbackOutcome.DUPLICATE_IDEMPOTENT,
                reason="duplicate idempotency key",
                prior_result={
                    "outcome": _history_event_type(event),
                    "payload": _history_payload(event),
                },
            )
        return CallbackValidationResult(
            outcome=CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
            reason="idempotency payload conflict",
        )
    return None


def _has_full_event_history(events: Sequence[GraphHistoryEvent]) -> bool:
    return bool(events) and _history_event_position(events[0]) == 1


def _history_event_type(event: GraphHistoryEvent) -> str:
    if isinstance(event, HydratedEvent):
        return event.metadata.event_type
    return event.event_type


def _history_event_position(event: GraphHistoryEvent) -> int:
    if isinstance(event, HydratedEvent):
        return event.metadata.position
    return event.position


def _history_payload_value(event: GraphHistoryEvent, field: str) -> Any:
    if isinstance(event, HydratedEvent):
        return getattr(event.payload, field, None)
    if event.schema_version == 1 and event.event_type in {
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
        "lease_expired",
        "agent_died",
        "node_state_changed",
    }:
        return event.payload.get(field)
    return None


def _history_payload(event: GraphHistoryEvent) -> dict[str, Any]:
    if isinstance(event, HydratedEvent):
        return event.payload.model_dump(mode="json", exclude_none=True)
    return event.payload


def _callback_idempotency_projection_key(node_id: str, idempotency_key: str) -> str:
    return f"{node_id}\0{idempotency_key}"


def _stored_callback_payload(event_payload: dict[str, Any]) -> dict[str, Any] | None:
    payload = event_payload.get("payload")
    if payload is None:
        return None
    if isinstance(payload, dict):
        return cast(dict[str, Any], payload)
    return {"payload": payload}


def _rejected_stale(reason: str) -> CallbackValidationResult:
    return CallbackValidationResult(
        outcome=CallbackOutcome.REJECTED_STALE,
        reason=reason,
    )
