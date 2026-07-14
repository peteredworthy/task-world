"""Unit tests for pure graph callback validation."""

from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    CallbackAcceptedPayload,
    CallbackOutcome,
    CallbackRejectedPayload,
    CallbackRequest,
    FakeClock,
    GraphProjection,
    HydratedEvent,
    initial_projection,
    reduce_event,
    validate_callback,
)
from orchestrator.graph import build_graph_catalog
from orchestrator.graph import StoredEventEnvelope


def _projection(
    *,
    run_state: str | None = "active",
    node_states: dict[str, str] | None = None,
    leases: dict[str, dict[str, Any]] | None = None,
) -> GraphProjection:
    projection = initial_projection()
    projection["run_state"] = run_state
    projection["node_states"] = node_states or {"worker-1": "running"}
    projection["leases"] = leases or {
        "lease-1": {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "state": "active",
            "execution_id": "exec-1",
            "base_snapshot_id": "snapshot-1",
        }
    }
    return projection


def _request(
    *,
    node_id: str = "worker-1",
    lease_id: str = "lease-1",
    lease_generation: int = 1,
    idempotency_key: str = "key-1",
    payload: dict[str, Any] | None = None,
    is_mutating: bool = True,
) -> CallbackRequest:
    return CallbackRequest(
        run_id="run-1",
        node_id=node_id,
        execution_id="exec-1",
        lease_id=lease_id,
        lease_generation=lease_generation,
        base_snapshot_id="snapshot-1",
        observed_graph_position=1,
        idempotency_key=idempotency_key,
        payload=payload or {"payload_hash": "hash-a"},
        is_mutating=is_mutating,
    )


def _event(event_type: str, payload: dict[str, Any]) -> HydratedEvent:
    return (
        build_graph_catalog()
        .resolve_event(event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=f"{event_type}-event",
                run_id="run-1",
                position=-1,
                event_type=event_type,
                payload_schema_generation=2,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=FakeClock().now(),
                payload=payload,
            )
        )
    )


def _lease(state: str, generation: int = 1) -> dict[str, Any]:
    return {
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "generation": generation,
        "state": state,
        "execution_id": "exec-1",
        "base_snapshot_id": "snapshot-1",
    }


def test_callback_accepted() -> None:
    result = validate_callback(_request(), _projection(), [])

    assert result.outcome == CallbackOutcome.ACCEPTED
    assert result.reason == "accepted"


def test_duplicate_same_payload_returns_prior() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "accepted",
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert result.outcome == CallbackOutcome.DUPLICATE_IDEMPOTENT
    assert isinstance(event.payload, CallbackAcceptedPayload)
    assert result.prior_result == {
        "outcome": "callback_accepted",
        "payload": event.payload.model_dump(mode="json"),
    }


def test_duplicate_different_payload_rejected() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-b"},
            "reason": "accepted",
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert result.outcome == CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT


def test_corrupt_callback_accepted_history_raises_during_duplicate_validation() -> None:
    accepted = _event(
        "callback_accepted",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "accepted",
        },
    )
    corrupt = accepted.model_copy(
        update={
            "payload": _event(
                "callback_rejected_conflict",
                {
                    "node_id": "worker-1",
                    "idempotency_key": "key-1",
                    "payload": {"payload_hash": "hash-a"},
                    "reason": "conflict",
                },
            ).payload
        }
    )

    with pytest.raises(TypeError, match="callback_accepted history event"):
        validate_callback(_request(), _projection(), [corrupt])


def test_corrupt_lease_expired_history_raises_during_stale_validation() -> None:
    expired = _event(
        "lease_expired",
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-1",
            "reason": "lease_expired_without_callback",
            "expires_at": "2026-01-01T00:00:00+00:00",
        },
    )
    corrupt = expired.model_copy(
        update={
            "payload": _event(
                "callback_accepted",
                {
                    "node_id": "worker-1",
                    "idempotency_key": "key-1",
                    "payload": {"payload_hash": "hash-a"},
                    "reason": "accepted",
                },
            ).payload
        }
    )

    with pytest.raises(TypeError, match="lease_expired history event"):
        validate_callback(
            _request(),
            _projection(
                node_states={"worker-1": "failed"},
                leases={"lease-1": _lease("expired")},
            ),
            [corrupt],
        )


def test_corrupt_node_state_history_raises_during_stale_validation() -> None:
    lease_expired = _event(
        "lease_expired",
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-1",
            "reason": "lease_expired_without_callback",
            "expires_at": "2026-01-01T00:00:00+00:00",
        },
    )
    node_state_changed = _event(
        "node_state_changed",
        {
            "node_id": "worker-1",
            "new_state": "failed",
            "trigger": "lease_expired_without_callback",
            "reason": "lease_expired_without_callback",
        },
    )
    corrupt = node_state_changed.model_copy(
        update={
            "payload": _event(
                "callback_accepted",
                {
                    "node_id": "worker-1",
                    "idempotency_key": "key-1",
                    "payload": {"payload_hash": "hash-a"},
                    "reason": "accepted",
                },
            ).payload
        }
    )

    with pytest.raises(TypeError, match="node_state_changed history event"):
        validate_callback(
            _request(),
            _projection(
                node_states={"worker-1": "failed"},
                leases={"lease-1": _lease("expired")},
            ),
            [lease_expired, corrupt],
        )


def test_projected_prior_rejection_does_not_return_duplicate() -> None:
    projection = reduce_event(
        build_graph_catalog(),
        _projection(),
        _event(
            "callback_rejected_conflict",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": {"payload_hash": "hash-a"},
                "reason": "idempotency payload conflict",
            },
        ),
    )

    result = validate_callback(_request(), projection, [])

    assert result.outcome == CallbackOutcome.ACCEPTED


def test_first_callback_not_duplicate() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-2",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "accepted",
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert isinstance(event.payload, CallbackAcceptedPayload)
    assert result.outcome == CallbackOutcome.ACCEPTED


def test_revoked_lease_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(leases={"lease-1": _lease("revoked")}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease revoked"


def test_expired_lease_without_expiry_event_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(
            node_states={"worker-1": "failed"},
            leases={"lease-1": _lease("expired")},
        ),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease expired"


def test_expired_uncontested_lease_with_matching_execution_accepted() -> None:
    events = [
        _event(
            "lease_expired",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-1",
                "reason": "lease_expired_without_callback",
                "expires_at": "2026-01-01T00:00:00+00:00",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "failed",
                "trigger": "lease_expired_without_callback",
                "reason": "lease_expired_without_callback",
            },
        ),
    ]

    result = validate_callback(
        _request(),
        _projection(
            node_states={"worker-1": "failed"},
            leases={"lease-1": _lease("expired")},
        ),
        events,
    )

    assert result.outcome == CallbackOutcome.ACCEPTED
    assert result.reason == "accepted_late_expired_lease"


def test_expired_redispatched_lease_rejected_as_contested() -> None:
    result = validate_callback(
        _request(),
        _projection(
            leases={
                "lease-1": _lease("expired"),
                "lease-2": {
                    **_lease("active", generation=2),
                    "lease_id": "lease-2",
                    "execution_id": "exec-2",
                },
            },
        ),
        [
            _event(
                "lease_expired",
                {
                    "lease_id": "lease-1",
                    "node_id": "worker-1",
                    "generation": 1,
                    "execution_id": "exec-test",
                    "expires_at": "2026-01-01T00:00:00+00:00",
                    "reason": "test_expiry",
                },
            ),
            _event(
                "lease_granted",
                {
                    "lease_id": "lease-2",
                    "node_id": "worker-1",
                    "generation": 2,
                    "execution_id": "exec-2",
                    "base_snapshot_id": "S0",
                    "expires_at": "2026-01-01T00:05:00+00:00",
                    "resource_claims": [],
                },
            ),
        ],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease expired and redispatched"


def test_expired_lease_rejected_after_completed_redispatch() -> None:
    result = validate_callback(
        _request(),
        _projection(
            node_states={"worker-1": "completed"},
            leases={
                "lease-1": _lease("expired"),
                "lease-2": {
                    **_lease("released", generation=2),
                    "lease_id": "lease-2",
                    "execution_id": "exec-2",
                },
            },
        ),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease expired"


def test_suspended_lease_mutating_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(leases={"lease-1": _lease("suspended")}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease suspended"


def test_suspended_lease_nonmutating_accepted() -> None:
    result = validate_callback(
        _request(is_mutating=False),
        _projection(leases={"lease-1": _lease("suspended")}),
        [],
    )

    assert result.outcome == CallbackOutcome.ACCEPTED


def test_old_generation_rejected() -> None:
    result = validate_callback(
        _request(lease_generation=1),
        _projection(leases={"lease-1": _lease("active", generation=2)}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease_generation_incompatible"


def test_future_generation_rejected() -> None:
    result = validate_callback(
        _request(lease_generation=2),
        _projection(leases={"lease-1": _lease("active", generation=1)}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease_generation_incompatible"


def test_far_future_generation_rejected() -> None:
    result = validate_callback(
        _request(lease_generation=999),
        _projection(leases={"lease-1": _lease("active", generation=1)}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease_generation_incompatible"


def test_exact_generation_accepted() -> None:
    result = validate_callback(
        _request(lease_generation=3),
        _projection(leases={"lease-1": _lease("active", generation=3)}),
        [],
    )

    assert result.outcome == CallbackOutcome.ACCEPTED


def test_execution_mismatch_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(
            leases={
                "lease-1": {
                    **_lease("active"),
                    "execution_id": "exec-other",
                }
            }
        ),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "execution_incompatible"


def test_snapshot_mismatch_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(
            leases={
                "lease-1": {
                    **_lease("active"),
                    "base_snapshot_id": "snapshot-other",
                }
            }
        ),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "snapshot_incompatible"


def test_node_terminal_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(node_states={"worker-1": "completed"}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "node completed"


def test_mutating_callback_before_start_ack_rejected_as_conflict() -> None:
    result = validate_callback(
        _request(),
        _projection(node_states={"worker-1": "leased"}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_CONFLICT
    assert result.reason == "node not running: leased"


def test_run_cancelled_rejected() -> None:
    result = validate_callback(_request(), _projection(run_state="cancelled"), [])

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "run cancelled"


def test_nonmutating_on_completed_node_accepted() -> None:
    result = validate_callback(
        _request(is_mutating=False),
        _projection(node_states={"worker-1": "completed"}),
        [],
    )

    assert result.outcome == CallbackOutcome.ACCEPTED


def test_rejected_conflict_then_retry_same_payload_validates_fresh() -> None:
    """A prior rejection must not poison the idempotency key (see prod run 8feabee5).

    Retrying with the same payload after a rejection should run full
    validation, not replay the rejection as a duplicate result.
    """
    event = _event(
        "callback_rejected_conflict",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "idempotency payload conflict",
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert isinstance(event.payload, CallbackRejectedPayload)
    assert result.outcome == CallbackOutcome.ACCEPTED


def test_rejected_conflict_then_retry_different_payload_validates_fresh() -> None:
    """A prior rejection must not cause a differently-payloaded retry to be
    treated as an idempotency conflict either -- it should validate fresh."""
    event = _event(
        "callback_rejected_conflict",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "idempotency payload conflict",
        },
    )

    result = validate_callback(_request(payload={"payload_hash": "hash-b"}), _projection(), [event])

    assert result.outcome != CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert result.outcome == CallbackOutcome.ACCEPTED


def test_accepted_then_retry_same_payload_is_duplicate() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "accepted",
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert result.outcome == CallbackOutcome.DUPLICATE_IDEMPOTENT


def test_accepted_then_retry_different_payload_is_conflict() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
            "reason": "accepted",
        },
    )

    result = validate_callback(_request(payload={"payload_hash": "hash-b"}), _projection(), [event])

    assert result.outcome == CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT


def test_pause_before_callback_stale() -> None:
    result = validate_callback(
        _request(),
        _projection(leases={"lease-1": _lease("suspended")}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease suspended"


def test_callback_before_pause_accepted() -> None:
    result = validate_callback(
        _request(),
        _projection(),
        [_event("run_lifecycle_changed", {"to_state": "pausing"})],
    )

    assert result.outcome == CallbackOutcome.ACCEPTED
