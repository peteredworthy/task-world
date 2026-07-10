"""Typed graph event and command specifications."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, SerializeAsAny

from orchestrator.graph.models import Actor
from orchestrator.graph.payloads import JsonValue, StrictPayload


PayloadT = TypeVar("PayloadT", bound=StrictPayload)
CommandT = TypeVar("CommandT", bound=StrictPayload)
ProjectionT = TypeVar("ProjectionT")


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


class EventMetadata(BaseModel):
    """Durable event identity and stream metadata."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    event_id: str
    run_id: str
    position: int
    event_type: str
    payload_schema_generation: int
    actor: Actor
    causation_id: str | None = None
    correlation_id: str | None = None
    timestamp: datetime


class StoredEventEnvelope(BaseModel):
    """JSON storage boundary for graph events."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    event_id: str
    run_id: str
    position: int
    event_type: str
    payload_schema_generation: int
    actor: Actor
    causation_id: str | None = None
    correlation_id: str | None = None
    timestamp: datetime
    payload: dict[str, JsonValue]


class HydratedEvent(BaseModel):
    """Kernel event carrying one validated concrete payload."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    metadata: EventMetadata
    payload: SerializeAsAny[StrictPayload]


class ProjectionParticipation(str, Enum):
    MUTATES = "mutates"
    NEUTRAL = "neutral"


EventReducer = Callable[[Any, PayloadT, EventMetadata], Any]
CommandHandler = Callable[[CommandT, "CommandExecutionContext"], list[HydratedEvent]]


@dataclass(frozen=True)
class CommandExecutionContext:
    """Injected capabilities and universal metadata for command execution."""

    run_id: str
    current_position: int
    clock: Clock
    id_generator: IdGenerator
    actor: Actor
    events: tuple[HydratedEvent, ...]

    def event_metadata(self, event_type: str) -> EventMetadata:
        return EventMetadata(
            event_id=self.id_generator.next_id("event"),
            run_id=self.run_id,
            position=self.current_position + 1,
            event_type=event_type,
            payload_schema_generation=2,
            actor=self.actor,
            timestamp=self.clock.now(),
        )


@dataclass(frozen=True)
class EventSpecification(Generic[PayloadT]):
    name: str
    payload_type: type[PayloadT]
    reducer: EventReducer[PayloadT]
    projection_participation: ProjectionParticipation

    def validate_payload(self, payload: Mapping[str, object]) -> PayloadT:
        return self.payload_type.model_validate(payload)

    def create(self, metadata: EventMetadata, payload: PayloadT) -> HydratedEvent:
        self._require_exact_payload(payload)
        if metadata.event_type != self.name:
            msg = f"event metadata type {metadata.event_type!r} does not match {self.name!r}"
            raise ValueError(msg)
        return HydratedEvent(metadata=metadata, payload=payload)

    def hydrate(self, stored: StoredEventEnvelope) -> HydratedEvent:
        if stored.event_type != self.name:
            msg = f"stored event type {stored.event_type!r} does not match {self.name!r}"
            raise ValueError(msg)
        payload = self.payload_type.model_validate(stored.payload)
        metadata = EventMetadata.model_validate(stored.model_dump(exclude={"payload"}))
        return self.create(metadata, payload)

    def serialize(self, event: HydratedEvent) -> StoredEventEnvelope:
        self._require_exact_payload(event.payload)
        if event.metadata.event_type != self.name:
            msg = f"event metadata type {event.metadata.event_type!r} does not match {self.name!r}"
            raise ValueError(msg)
        return StoredEventEnvelope(
            **event.metadata.model_dump(),
            payload=event.payload.to_json(),
        )

    def reduce(self, state: ProjectionT, event: HydratedEvent) -> ProjectionT:
        self._require_exact_payload(event.payload)
        reducer = cast(Callable[[ProjectionT, PayloadT, EventMetadata], ProjectionT], self.reducer)
        return reducer(state, cast(PayloadT, event.payload), event.metadata)

    def _require_exact_payload(self, payload: StrictPayload) -> None:
        if type(payload) is not self.payload_type:
            msg = f"{self.name} requires exact payload class {self.payload_type.__name__}"
            raise TypeError(msg)


@dataclass(frozen=True)
class CommandSpecification(Generic[CommandT]):
    name: str
    payload_type: type[CommandT]
    handler: CommandHandler[CommandT]

    def validate(self, payload: Mapping[str, object]) -> CommandT:
        return self.payload_type.model_validate(payload)

    def handle(
        self,
        command: StrictPayload,
        context: CommandExecutionContext,
    ) -> list[HydratedEvent]:
        if type(command) is not self.payload_type:
            msg = f"{self.name} requires exact command class {self.payload_type.__name__}"
            raise TypeError(msg)
        return self.handler(cast(CommandT, command), context)


def projection_neutral(
    state: ProjectionT,
    payload: StrictPayload,
    metadata: EventMetadata,
) -> ProjectionT:
    del payload
    del metadata
    return state


__all__ = [
    "CommandExecutionContext",
    "CommandSpecification",
    "EventMetadata",
    "EventSpecification",
    "HydratedEvent",
    "ProjectionParticipation",
    "StoredEventEnvelope",
    "projection_neutral",
]
