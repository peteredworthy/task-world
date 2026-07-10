"""Immutable graph specification catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, TypeVar

from orchestrator.graph.specifications import CommandSpecification, EventSpecification


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


def build_graph_catalog() -> GraphCatalog:
    """Compose a fresh catalog from immutable domain declarations."""

    from orchestrator.graph.commands.lifecycle import COMMAND_SPECIFICATIONS
    from orchestrator.graph.events import EVENT_SPECIFICATIONS

    return GraphCatalog.compose(EVENT_SPECIFICATIONS, COMMAND_SPECIFICATIONS)


__all__ = [
    "DuplicateGraphSpecificationError",
    "GraphCatalog",
    "UnknownGraphCommandError",
    "UnknownGraphEventError",
    "build_graph_catalog",
]
