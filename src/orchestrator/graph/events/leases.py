"""Strict lease event specifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from orchestrator.graph.models import LeaseProjection, ResourceClaimProjection
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


class LeaseGrantedPayload(StrictPayload):
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)
    execution_id: str
    base_snapshot_id: str
    expires_at: datetime
    resource_claims: tuple[ResourceClaimProjection, ...]
    session_id: str | None = None


class LeaseRenewedPayload(StrictPayload):
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)
    execution_id: str
    observed_at: datetime
    expires_at: datetime


class LeaseReleasedPayload(StrictPayload):
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)


class LeaseRevokedPayload(StrictPayload):
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)
    execution_id: str
    trigger: str
    reason: str


class LeaseExpiredPayload(StrictPayload):
    lease_id: str
    node_id: str
    generation: int = Field(ge=0)
    execution_id: str
    expires_at: datetime
    reason: str


LeasePayload = (
    LeaseGrantedPayload
    | LeaseRenewedPayload
    | LeaseReleasedPayload
    | LeaseRevokedPayload
    | LeaseExpiredPayload
)


def _reduce_lease(state: Any, payload: LeasePayload, metadata: EventMetadata) -> Any:
    next_state = dict(state)
    next_state["leases"] = dict(state.get("leases", {}))
    next_state["planner_sessions"] = dict(state.get("planner_sessions", {}))
    existing = next_state["leases"].get(payload.lease_id)
    lease: dict[str, Any] = (
        existing.model_dump(mode="python") if isinstance(existing, LeaseProjection) else {}
    )

    if isinstance(payload, LeaseGrantedPayload):
        claims = list(payload.resource_claims) or list(
            state.get("node_resource_claims", {}).get(payload.node_id, [])
        )
        lease = {
            "lease_id": payload.lease_id,
            "node_id": payload.node_id,
            "state": "active",
            "generation": payload.generation,
            "execution_id": payload.execution_id,
            "base_snapshot_id": payload.base_snapshot_id,
            "expires_at": payload.expires_at.isoformat(),
        }
        if claims:
            lease["resource_claims"] = claims
        task_region_id = state.get("node_task_regions", {}).get(payload.node_id)
        if task_region_id is not None:
            lease["task_region_id"] = task_region_id
        kind = state.get("node_kinds", {}).get(payload.node_id)
        if kind is not None:
            lease["kind"] = kind
        if payload.session_id is not None:
            lease["session_id"] = payload.session_id
        if payload.session_id is not None:
            next_state["planner_sessions"][payload.node_id] = payload.session_id
    elif isinstance(payload, LeaseRenewedPayload):
        lease.update(
            node_id=payload.node_id,
            state="active",
            generation=payload.generation,
            execution_id=payload.execution_id,
            expires_at=payload.expires_at.isoformat(),
        )
    else:
        lease["state"] = metadata.event_type.removeprefix("lease_")

    next_state["leases"][payload.lease_id] = LeaseProjection.model_validate(lease)
    # Lease terminality participates in task-region completion. Keep the
    # shared derived views synchronized after the typed lease mutation just as
    # the monolithic reducer did for every event.
    from orchestrator.graph.projections import refresh_derived_topology_state

    refresh_derived_topology_state(next_state)
    return next_state


LEASE_GRANTED = EventSpecification(
    "lease_granted", LeaseGrantedPayload, _reduce_lease, ProjectionParticipation.MUTATES
)
LEASE_RENEWED = EventSpecification(
    "lease_renewed", LeaseRenewedPayload, _reduce_lease, ProjectionParticipation.MUTATES
)
LEASE_RELEASED = EventSpecification(
    "lease_released", LeaseReleasedPayload, _reduce_lease, ProjectionParticipation.MUTATES
)
LEASE_REVOKED = EventSpecification(
    "lease_revoked", LeaseRevokedPayload, _reduce_lease, ProjectionParticipation.MUTATES
)
LEASE_EXPIRED = EventSpecification(
    "lease_expired", LeaseExpiredPayload, _reduce_lease, ProjectionParticipation.MUTATES
)
EVENT_SPECIFICATIONS = (LEASE_GRANTED, LEASE_RENEWED, LEASE_RELEASED, LEASE_REVOKED, LEASE_EXPIRED)
