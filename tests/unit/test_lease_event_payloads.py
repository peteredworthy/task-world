from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
    LeaseSuspendedPayload,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    reduce_event,
)


def test_lease_granted_payload_normalizes_legacy_keys_to_extra() -> None:
    payload = LeaseGrantedPayload.model_validate(
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-1",
            "base_snapshot_id": "snapshot-1",
            "expires_at": "2026-07-08T12:05:00",
            "resource_claims": [
                {"mode": "write", "scope": "repo", "path": "src/app.py"},
                {"mode": "external"},
                "legacy-junk",
            ],
            "session_id": "session-1",
            "task_region_id": "task-1",
            "kind": "worker",
            "legacy_note": "kept",
        }
    )

    assert [claim.model_dump(mode="json") for claim in payload.resource_claims] == [
        {"mode": "write", "scope": "repo", "paths": ["src/app.py"]},
        {"mode": "external", "scope": "repo"},
    ]
    assert payload.extra == {
        "task_region_id": "task-1",
        "kind": "worker",
        "legacy_note": "kept",
    }


def test_terminal_lease_payloads_preserve_known_metadata_and_legacy_extra() -> None:
    revoked = LeaseRevokedPayload.model_validate(
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 2,
            "execution_id": "exec-1",
            "trigger": "run_cancelled",
            "reason": "run_cancelled",
            "operator_note": "legacy note",
        }
    )
    expired = LeaseExpiredPayload.model_validate(
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 2,
            "execution_id": "exec-1",
            "expires_at": "2026-07-08T12:05:00",
            "reason": "lease_expired_without_callback",
            "legacy_clock_skew": 3,
        }
    )
    released = LeaseReleasedPayload.model_validate(
        {"lease_id": "lease-1", "node_id": "worker-1", "legacy": True}
    )
    suspended = LeaseSuspendedPayload.model_validate(
        {"lease_id": "lease-1", "node_id": "worker-1", "legacy": True}
    )

    assert revoked.trigger == "run_cancelled"
    assert revoked.extra == {"operator_note": "legacy note"}
    assert expired.reason == "lease_expired_without_callback"
    assert expired.extra == {"legacy_clock_skew": 3}
    assert released.extra == {"legacy": True}
    assert suspended.extra == {"legacy": True}


def test_lease_reducers_tolerate_legacy_payloads_through_typed_models() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "ready",
                "task_region_id": "task-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "path": "src/app.py"}],
            },
            position=1,
        ),
    )

    projection = reduce_event(
        projection,
        _event(
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "snapshot-1",
                "expires_at": "2026-07-08T12:05:00",
                "resource_claims": [{"mode": "external"}],
                "legacy_note": "kept under extra",
            },
            position=2,
        ),
    )

    lease = projection["leases"]["lease-1"]
    assert lease.state == "active"
    assert lease.task_region_id == "task-1"
    assert lease.kind == "worker"
    assert [claim.model_dump(mode="json") for claim in lease.resource_claims] == [
        {"mode": "external", "scope": "repo"}
    ]

    projection = reduce_event(
        projection,
        _event(
            "lease_renewed",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "observed_at": "2026-07-08T12:01:00",
                "expires_at": "2026-07-08T12:10:00",
                "legacy_note": "kept under extra",
            },
            position=3,
        ),
    )
    assert projection["leases"]["lease-1"].expires_at == "2026-07-08T12:10:00"

    for position, event_type in enumerate(
        ["lease_suspended", "lease_revoked", "lease_expired", "lease_released"],
        start=4,
    ):
        projection = reduce_event(
            projection,
            _event(
                event_type,
                {"lease_id": "lease-1", "node_id": "worker-1", "legacy_note": "kept"},
                position=position,
            ),
        )
        assert projection["leases"]["lease-1"].state == event_type.removeprefix("lease_")


def test_lease_producers_emit_payloads_validated_by_typed_models() -> None:
    events = [
        _event(
            "run_lifecycle_changed",
            {"to_state": "active"},
            position=1,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "ready",
                "task_region_id": "task-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "path": "src/app.py"}],
            },
            position=2,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-1",
                "to_node_id": "worker-1",
                "to_port": "routine_snapshot",
                "record_ids": ["routine-snapshot-record"],
                "bound_at_position": 2,
            },
            position=3,
        ),
    ]

    scheduled = apply_command(
        _project(events),
        events,
        "schedule_tick",
        {"run_id": "run-1", "max_grants": 1, "lease_seconds": 300},
        FakeClock(),
        SequentialIdGenerator(),
    )
    granted_event = next(event for event in scheduled if event.event_type == "lease_granted")
    granted = LeaseGrantedPayload.model_validate(granted_event.payload)
    assert granted.lease_id == "lease-1"
    assert granted.extra == {}

    events = [*events, granted_event]
    renewed = apply_command(
        _project(events),
        events,
        "record_heartbeat",
        {"run_id": "run-1", "lease_id": granted.lease_id},
        FakeClock(),
        SequentialIdGenerator(),
    )
    renewed_payload = LeaseRenewedPayload.model_validate(
        next(event for event in renewed if event.event_type == "lease_renewed").payload
    )
    assert renewed_payload.lease_id == granted.lease_id
    assert renewed_payload.extra == {}


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
