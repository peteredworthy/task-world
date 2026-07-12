"""Public graph event specification groups."""

from typing import Any

from orchestrator.graph.events.lifecycle import (
    EVENT_SPECIFICATIONS as LIFECYCLE_EVENT_SPECIFICATIONS,
)
from orchestrator.graph.events.records import (
    EVENT_SPECIFICATIONS as RECORD_EVENT_SPECIFICATIONS,
)
from orchestrator.graph.events.topology import (
    EVENT_SPECIFICATIONS as TOPOLOGY_EVENT_SPECIFICATIONS,
)
from orchestrator.graph.events.leases import EVENT_SPECIFICATIONS as LEASE_EVENT_SPECIFICATIONS
from orchestrator.graph.events.patches import EVENT_SPECIFICATIONS as PATCH_EVENT_SPECIFICATIONS
from orchestrator.graph.events.decisions import (
    EVENT_SPECIFICATIONS as DECISION_EVENT_SPECIFICATIONS,
)
from orchestrator.graph.events.requirements import (
    EVENT_SPECIFICATIONS as REQUIREMENT_EVENT_SPECIFICATIONS,
)
from orchestrator.graph.specifications import EventSpecification


EVENT_SPECIFICATIONS: tuple[EventSpecification[Any], ...] = (
    *LIFECYCLE_EVENT_SPECIFICATIONS,
    *RECORD_EVENT_SPECIFICATIONS,
    *TOPOLOGY_EVENT_SPECIFICATIONS,
    *LEASE_EVENT_SPECIFICATIONS,
    *PATCH_EVENT_SPECIFICATIONS,
    *DECISION_EVENT_SPECIFICATIONS,
    *REQUIREMENT_EVENT_SPECIFICATIONS,
)


__all__ = [
    "EVENT_SPECIFICATIONS",
    "LIFECYCLE_EVENT_SPECIFICATIONS",
    "RECORD_EVENT_SPECIFICATIONS",
    "TOPOLOGY_EVENT_SPECIFICATIONS",
    "LEASE_EVENT_SPECIFICATIONS",
    "PATCH_EVENT_SPECIFICATIONS",
]
