"""Immutable graph specification catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import chain
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, TypeVar

from pydantic import ValidationError

from orchestrator.graph.models import EventEnvelope
from orchestrator.graph.payloads import LegacyEventPayload
from orchestrator.graph.specifications import (
    CommandSpecification,
    EventSpecification,
    EventMetadata,
    HydratedEvent,
    StoredEventEnvelope,
)


class NamedSpecification(Protocol):
    @property
    def name(self) -> str: ...


SpecificationT = TypeVar("SpecificationT", bound=NamedSpecification)


class DuplicateGraphSpecificationError(ValueError):
    pass


class UnknownGraphEventError(LookupError):
    pass


class UnknownGraphCommandError(LookupError):
    pass


def _unique_by_name(kind: str, specs: Iterable[SpecificationT]) -> dict[str, SpecificationT]:
    result: dict[str, SpecificationT] = {}
    for spec in specs:
        if spec.name in result:
            msg = f"duplicate graph {kind} specification: {spec.name}"
            raise DuplicateGraphSpecificationError(msg)
        result[spec.name] = spec
    return result


@dataclass(frozen=True)
class GraphCatalog:
    event_specs: Mapping[str, EventSpecification[Any]]
    command_specs: Mapping[str, CommandSpecification[Any]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_specs",
            MappingProxyType(_unique_by_name("event", self.event_specs.values())),
        )
        object.__setattr__(
            self,
            "command_specs",
            MappingProxyType(_unique_by_name("command", self.command_specs.values())),
        )

    @classmethod
    def compose(
        cls,
        event_specs: Iterable[EventSpecification[Any]],
        command_specs: Iterable[CommandSpecification[Any]],
    ) -> GraphCatalog:
        return cls(
            event_specs=_unique_by_name("event", event_specs),
            command_specs=_unique_by_name("command", command_specs),
        )

    @property
    def events(self) -> tuple[EventSpecification[Any], ...]:
        return tuple(self.event_specs.values())

    @property
    def commands(self) -> tuple[CommandSpecification[Any], ...]:
        return tuple(self.command_specs.values())

    def resolve_event(self, name: str) -> EventSpecification[Any]:
        try:
            return self.event_specs[name]
        except KeyError as error:
            raise UnknownGraphEventError(f"unknown graph event: {name}") from error

    def resolve_command(self, name: str) -> CommandSpecification[Any]:
        try:
            return self.command_specs[name]
        except KeyError as error:
            raise UnknownGraphCommandError(f"unknown graph command: {name}") from error

    def hydrate_event(self, stored: StoredEventEnvelope) -> HydratedEvent:
        """Hydrate one durable event through its owning specification."""

        specification = self.event_specs.get(stored.event_type)
        if specification is not None:
            try:
                return specification.hydrate(stored)
            except ValidationError:
                if stored.source_schema_version != 1:
                    raise
        if stored.source_schema_version == 1:
            return HydratedEvent(
                metadata=EventMetadata.model_validate(
                    stored.model_dump(exclude={"payload", "source_schema_version"})
                ),
                payload=LegacyEventPayload(data=stored.payload),
            )
        raise UnknownGraphEventError(f"unknown graph event: {stored.event_type}")

    def reduce_stored_event(self, state: Any, event: EventEnvelope) -> tuple[bool, Any]:
        """Hydrate a catalog-owned event once; leave future-domain events to legacy projection."""

        specification = self.event_specs.get(event.event_type)
        if specification is None:
            return False, state
        stored = event.model_dump()
        stored["payload"] = event.model_dump(mode="json")["payload"]
        stored["payload_schema_generation"] = stored.pop("schema_version")
        hydrated = specification.hydrate(StoredEventEnvelope.model_validate(stored))
        return True, specification.reduce(state, hydrated)


def build_graph_catalog() -> GraphCatalog:
    """Compose a fresh catalog from immutable domain declarations."""

    from orchestrator.graph.commands import COMMAND_SPECIFICATION_GROUPS
    from orchestrator.graph.events import EVENT_SPECIFICATION_GROUPS

    return GraphCatalog.compose(
        chain.from_iterable(EVENT_SPECIFICATION_GROUPS),
        chain.from_iterable(COMMAND_SPECIFICATION_GROUPS),
    )


__all__ = [
    "DuplicateGraphSpecificationError",
    "GraphCatalog",
    "UnknownGraphCommandError",
    "UnknownGraphEventError",
    "build_graph_catalog",
]
