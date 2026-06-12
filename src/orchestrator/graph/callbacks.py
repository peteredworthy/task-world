"""Pure callback validation for execution graph leases."""

from dataclasses import dataclass
from typing import Any, cast

from orchestrator.graph.models import EventEnvelope
from orchestrator.graph.projections import GraphProjection


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
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    DUPLICATE_IDEMPOTENT = "duplicate_idempotent"


@dataclass(frozen=True)
class CallbackValidationResult:
    outcome: str
    reason: str
    prior_result: dict[str, Any] | None = None


_IDEMPOTENCY_EVENT_TYPES = {
    "callback_accepted",
    "callback_rejected_stale",
    "callback_rejected_conflict",
    "callback_duplicate_returned",
}

_STALE_LEASE_STATES = {"revoked", "expired"}
_TERMINAL_NODE_STATES = {"completed", "failed", "cancelled", "retired"}
_TERMINAL_RUN_STATES = {"cancelled", "failed"}


def validate_callback(
    request: CallbackRequest,
    projection: GraphProjection,
    events: list[EventEnvelope],
) -> CallbackValidationResult:
    """Validate a callback against prior idempotency events and graph projection."""

    idempotency_result = _validate_idempotency(request, events)
    if idempotency_result is not None:
        return idempotency_result

    lease = projection["leases"].get(request.lease_id)
    if lease is None:
        return _rejected_stale("unknown lease")

    lease_state = lease.get("state")
    if lease_state in _STALE_LEASE_STATES:
        return _rejected_stale(f"lease {lease_state}")
    if lease_state == "suspended" and request.is_mutating:
        return _rejected_stale("lease suspended")
    if lease_state == "released":
        return _rejected_stale("lease released, use idempotency key")

    generation = lease.get("generation")
    if isinstance(generation, int) and request.lease_generation < generation:
        return _rejected_stale("old lease generation")

    node_state = projection["node_states"].get(request.node_id)
    if request.is_mutating and node_state in _TERMINAL_NODE_STATES:
        return _rejected_stale(f"node {node_state}")

    run_state = projection["run_state"]
    if run_state in _TERMINAL_RUN_STATES:
        return _rejected_stale(f"run {run_state}")

    return CallbackValidationResult(
        outcome=CallbackOutcome.ACCEPTED,
        reason="accepted",
    )


def _validate_idempotency(
    request: CallbackRequest,
    events: list[EventEnvelope],
) -> CallbackValidationResult | None:
    for event in events:
        if event.event_type not in _IDEMPOTENCY_EVENT_TYPES:
            continue
        if event.payload.get("idempotency_key") != request.idempotency_key:
            continue
        if event.payload.get("node_id") != request.node_id:
            continue

        if _stored_callback_payload(event.payload) == request.payload:
            return CallbackValidationResult(
                outcome=CallbackOutcome.DUPLICATE_IDEMPOTENT,
                reason="duplicate idempotency key",
                prior_result={"outcome": event.event_type, "payload": event.payload},
            )
        return CallbackValidationResult(
            outcome=CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
            reason="idempotency payload conflict",
        )
    return None


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
