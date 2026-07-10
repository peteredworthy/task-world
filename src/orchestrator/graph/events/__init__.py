"""Public graph event specification groups."""

from typing import Any

from orchestrator.graph.events.lifecycle import (
    EVENT_SPECIFICATIONS as LIFECYCLE_EVENT_SPECIFICATIONS,
)
from orchestrator.graph.specifications import EventSpecification


EVENT_SPECIFICATIONS: tuple[EventSpecification[Any], ...] = (*LIFECYCLE_EVENT_SPECIFICATIONS,)


__all__ = ["EVENT_SPECIFICATIONS", "LIFECYCLE_EVENT_SPECIFICATIONS"]
