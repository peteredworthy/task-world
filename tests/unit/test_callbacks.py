"""Unit tests for pure graph callback validation."""

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    CallbackOutcome,
    CallbackRequest,
    EventEnvelope,
    FakeClock,
    GraphProjection,
    initial_projection,
    validate_callback,
)


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


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-event",
        run_id="run-1",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
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
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert result.outcome == CallbackOutcome.DUPLICATE_IDEMPOTENT
    assert result.prior_result == {
        "outcome": "callback_accepted",
        "payload": event.payload,
    }


def test_duplicate_different_payload_rejected() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-1",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-b"},
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert result.outcome == CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT


def test_first_callback_not_duplicate() -> None:
    event = _event(
        "callback_accepted",
        {
            "node_id": "worker-2",
            "idempotency_key": "key-1",
            "payload": {"payload_hash": "hash-a"},
        },
    )

    result = validate_callback(_request(), _projection(), [event])

    assert result.outcome == CallbackOutcome.ACCEPTED


def test_revoked_lease_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(leases={"lease-1": _lease("revoked")}),
        [],
    )

    assert result.outcome == CallbackOutcome.REJECTED_STALE
    assert result.reason == "lease revoked"


def test_expired_lease_rejected() -> None:
    result = validate_callback(
        _request(),
        _projection(leases={"lease-1": _lease("expired")}),
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
    assert result.reason == "old lease generation"


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


def test_pause_before_callback_stale() -> None:
    result = validate_callback(
        _request(),
        _projection(leases={"lease-1": _lease("suspended")}),
        [_event("lease_suspended", {"node_id": "worker-1", "lease_id": "lease-1"})],
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
