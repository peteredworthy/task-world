"""Strict lifecycle event payloads and specifications."""

from datetime import datetime
from typing import Any

from pydantic import Field

from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    EventSpecification,
    ProjectionParticipation,
    projection_neutral,
)


class HeartbeatRecordedPayload(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    observed_at: datetime


HEARTBEAT_RECORDED = EventSpecification(
    name="heartbeat_recorded",
    payload_type=HeartbeatRecordedPayload,
    reducer=projection_neutral,
    projection_participation=ProjectionParticipation.NEUTRAL,
)

EVENT_SPECIFICATIONS: tuple[EventSpecification[Any], ...] = (HEARTBEAT_RECORDED,)


__all__ = [
    "EVENT_SPECIFICATIONS",
    "HEARTBEAT_RECORDED",
    "HeartbeatRecordedPayload",
]
