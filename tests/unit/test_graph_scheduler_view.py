"""Unit tests for pure scheduler and lease view projections."""

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    project_lease_view,
    project_scheduler_view,
)


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
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


def test_scheduler_view_buckets_deferral_reasons() -> None:
    events = [
        _event("node_created", {"node_id": "ready-node", "state": "planned"}, 1),
        _event("node_created", {"node_id": "input-node", "state": "planned"}, 2),
        _event("node_created", {"node_id": "resource-node", "state": "planned"}, 3),
        _event("node_created", {"node_id": "gate-node", "state": "planned"}, 4),
        _event("node_created", {"node_id": "authority-node", "state": "planned"}, 5),
        _event(
            "node_deferred",
            {"node_id": "input-node", "reason": "missing_required_input:candidate"},
            6,
        ),
        _event(
            "node_deferred",
            {"node_id": "resource-node", "reason": "resource_conflict:write:write"},
            7,
        ),
        _event("node_deferred", {"node_id": "gate-node", "reason": "gate_not_approved:gate-1"}, 8),
        _event(
            "node_deferred",
            {"node_id": "authority-node", "reason": "authority_not_granted:authority-1"},
            9,
        ),
        _event("node_state_changed", {"node_id": "ready-node", "new_state": "ready"}, 10),
    ]

    view = project_scheduler_view(events)

    assert view["ready"] == ["ready-node"]
    assert view["blocked"] == [
        {"node_id": "input-node", "reason": "missing_required_input:candidate"}
    ]
    assert view["waiting_resources"] == [
        {"node_id": "resource-node", "reason": "resource_conflict:write:write"}
    ]
    assert view["waiting_gates"] == [
        {"node_id": "authority-node", "reason": "authority_not_granted:authority-1"},
        {"node_id": "gate-node", "reason": "gate_not_approved:gate-1"},
    ]


def test_scheduler_view_buckets_ready_resource_deferral() -> None:
    events = [
        _event("node_created", {"node_id": "writer-a", "state": "leased"}, 1),
        _event("node_created", {"node_id": "writer-b", "state": "planned"}, 2),
        _event("node_state_changed", {"node_id": "writer-b", "new_state": "ready"}, 3),
        _event(
            "node_deferred",
            {"node_id": "writer-b", "reason": "resource_conflict:write:write"},
            4,
        ),
    ]

    view = project_scheduler_view(events)

    assert view["ready"] == ["writer-b"]
    assert view["waiting_resources"] == [
        {"node_id": "writer-b", "reason": "resource_conflict:write:write"}
    ]


def test_lease_view_reports_active_and_suspended() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-active", "kind": "worker", "state": "leased"}, 1
        ),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-active",
                "node_id": "worker-active",
                "generation": 2,
                "execution_id": "exec-active",
                "expires_at": "2026-06-13T12:05:00+00:00",
            },
            2,
        ),
        _event(
            "node_created", {"node_id": "worker-suspended", "kind": "worker", "state": "leased"}, 3
        ),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-suspended",
                "node_id": "worker-suspended",
                "generation": 1,
                "execution_id": "exec-suspended",
                "expires_at": "2026-06-13T12:10:00+00:00",
            },
            4,
        ),
        _event("lease_suspended", {"lease_id": "lease-suspended"}, 5),
    ]

    view = project_lease_view(events)

    assert view["active"] == [
        {
            "lease_id": "lease-active",
            "node_id": "worker-active",
            "generation": 2,
            "state": "active",
            "execution_id": "exec-active",
            "expires_at": "2026-06-13T12:05:00+00:00",
        }
    ]
    assert view["suspended"] == [
        {
            "lease_id": "lease-suspended",
            "node_id": "worker-suspended",
            "generation": 1,
            "state": "suspended",
            "execution_id": "exec-suspended",
            "expires_at": "2026-06-13T12:10:00+00:00",
        }
    ]
