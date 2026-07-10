"""Temporary lease-renewal bridge for the strict heartbeat vertical slice.

Task 4 replaces this module with the strict ``LEASE_RENEWED`` event
specification.  Heartbeat itself remains a typed, projection-neutral audit
event; this bridge preserves the existing lease-expiry advancement until the
lease domain is converted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from orchestrator.graph._commands import (
    Clock,
    EventEnvelope,
    GraphProjection,
    command_rejected,
)
from orchestrator.graph.models import LeaseRenewedPayload

if TYPE_CHECKING:
    from orchestrator.graph.commands.lifecycle import RecordHeartbeatCommand


TEMPORARY_ACTIVE_LEASE_RENEWAL_SECONDS = 300
TEMPORARY_EXPIRED_LEASE_RENEWAL_SECONDS = 3600


def apply_temporary_unconverted_lease_renewal(
    projection: GraphProjection,
    command: RecordHeartbeatCommand,
    clock: Clock,
    emit_unconverted_event: Callable[[str, dict[str, object]], EventEnvelope],
) -> EventEnvelope:
    """Validate lease identity and emit one legacy ``lease_renewed`` event."""

    lease = projection["leases"].get(command.lease_id)
    if lease is None:
        return command_rejected(
            emit_unconverted_event,
            "record_heartbeat",
            f"unknown lease: {command.lease_id}",
        )
    if projection["run_state"] != "active":
        return command_rejected(emit_unconverted_event, "record_heartbeat", "run_not_active")
    if lease.get("state") != "active":
        return command_rejected(
            emit_unconverted_event,
            "record_heartbeat",
            f"lease_not_active:{lease.get('state')}",
        )

    node_id = lease.get("node_id")
    if command.node_id != node_id:
        return command_rejected(
            emit_unconverted_event,
            "record_heartbeat",
            "node_id_mismatch",
        )
    if not isinstance(node_id, str):
        return command_rejected(
            emit_unconverted_event,
            "record_heartbeat",
            "lease_missing_node_id",
        )

    lease_generation = lease.get("generation")
    if (
        isinstance(lease_generation, int)
        and not isinstance(lease_generation, bool)
        and command.lease_generation != lease_generation
    ):
        return command_rejected(
            emit_unconverted_event,
            "record_heartbeat",
            "lease_generation_mismatch",
        )

    observed_at = clock.now()
    renewal_seconds = _temporary_renewal_seconds(lease.get("expires_at"), observed_at)
    payload: dict[str, object] = {
        "lease_id": command.lease_id,
        "node_id": node_id,
        "observed_at": observed_at.isoformat(),
        "expires_at": (observed_at + timedelta(seconds=renewal_seconds)).isoformat(),
    }
    if isinstance(lease_generation, int) and not isinstance(lease_generation, bool):
        payload["generation"] = lease_generation
    execution_id = lease.get("execution_id")
    if isinstance(execution_id, str):
        payload["execution_id"] = execution_id
    typed_payload = LeaseRenewedPayload.model_validate(payload)
    return emit_unconverted_event(
        "lease_renewed",
        typed_payload.model_dump(mode="json"),
    )


def _temporary_renewal_seconds(expires_at: object, observed_at: datetime) -> int:
    """Preserve the old default heartbeat TTL and expired-driver override."""

    if not isinstance(expires_at, str):
        return TEMPORARY_ACTIVE_LEASE_RENEWAL_SECONDS
    try:
        deadline = datetime.fromisoformat(expires_at)
    except ValueError:
        return TEMPORARY_ACTIVE_LEASE_RENEWAL_SECONDS
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    if deadline <= observed_at:
        return TEMPORARY_EXPIRED_LEASE_RENEWAL_SECONDS
    return TEMPORARY_ACTIVE_LEASE_RENEWAL_SECONDS


__all__ = ["apply_temporary_unconverted_lease_renewal"]
