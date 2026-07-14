"""Direct creation of typed graph-domain events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    EventMetadata,
    EventSpecification,
    HydratedEvent,
)


PayloadT = TypeVar("PayloadT", bound=StrictPayload)


class TypedEventCreator:
    """Create hydrated events using one command's injected capabilities."""

    def __init__(
        self,
        context: CommandExecutionContext,
        *,
        assign_position: bool = True,
        causation_id: str | None = None,
    ) -> None:
        self._context = context
        self._assign_position = assign_position
        self._causation_id = causation_id
        self._created_count = 0

    def create(
        self,
        specification: EventSpecification[PayloadT],
        payload: PayloadT,
    ) -> HydratedEvent:
        metadata = self._metadata(specification)
        self._created_count += 1
        return specification.create(metadata, payload)

    def create_named(self, event_type: str, payload: Mapping[str, object]) -> HydratedEvent:
        """Validate a named payload through the injected catalog and create it."""
        specification = self._context.catalog.resolve_event(event_type)
        return self.create(specification, specification.validate_payload(payload))

    def _metadata(self, specification: EventSpecification[Any]) -> EventMetadata:
        context = self._context
        return EventMetadata(
            event_id=context.id_generator.next_id("event"),
            run_id=context.run_id,
            position=(
                context.current_position + self._created_count + 1 if self._assign_position else -1
            ),
            event_type=specification.name,
            payload_schema_generation=2,
            actor=context.actor,
            causation_id=self._causation_id,
            timestamp=context.clock.now(),
        )


__all__ = ["TypedEventCreator"]
