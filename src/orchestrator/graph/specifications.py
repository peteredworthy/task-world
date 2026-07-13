"""Typed graph event and command specifications."""

from __future__ import annotations

import json

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, SerializeAsAny

from orchestrator.graph.models import Actor, EventEnvelope
from orchestrator.graph.payloads import JsonValue, StrictPayload


PayloadT = TypeVar("PayloadT", bound=StrictPayload)
CommandT = TypeVar("CommandT", bound=BaseModel)
ProjectionT = TypeVar("ProjectionT")


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


class EventMetadata(BaseModel):
    """Durable event identity and stream metadata."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)

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

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)

    event_id: str
    run_id: str
    position: int
    event_type: str
    payload_schema_generation: int
    source_schema_version: int | None = None
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

    @property
    def event_id(self) -> str:
        return self.metadata.event_id

    @property
    def run_id(self) -> str:
        return self.metadata.run_id

    @property
    def position(self) -> int:
        return self.metadata.position

    @property
    def event_type(self) -> str:
        return self.metadata.event_type

    @property
    def schema_version(self) -> int:
        return self.metadata.payload_schema_generation

    @property
    def actor(self) -> Actor:
        return self.metadata.actor

    @property
    def causation_id(self) -> str | None:
        return self.metadata.causation_id

    @property
    def correlation_id(self) -> str | None:
        return self.metadata.correlation_id

    @property
    def timestamp(self) -> datetime:
        return self.metadata.timestamp


class ProjectionParticipation(str, Enum):
    MUTATES = "mutates"
    NEUTRAL = "neutral"


EventReducer = Callable[[Any, PayloadT, EventMetadata], Any]
# Task 9 deletes this temporary mixed-result bridge after the remaining event
# domains have strict specifications.  Projection and history are explicit
# execution inputs; they are deliberately not command payload fields.
CommandResult = HydratedEvent | EventEnvelope
CommandHandler = Callable[
    [CommandT, Any, tuple[EventEnvelope, ...], "CommandExecutionContext"],
    Sequence[CommandResult],
]


class FutureCommandEffects(Protocol):
    """Task 9 deletion seam for effects owned by future Tasks 3/4/6."""

    accepted_output_record_events: Callable[..., Any]
    file_state_authority_conflict: Callable[..., Any]
    file_state_rejected_conflict: Callable[..., Any]
    file_state_rejected_events: Callable[..., Any]
    lease_node_id: Callable[..., Any]
    output_record_contract_conflict: Callable[..., Any]
    output_record_provenance_conflict: Callable[..., Any]
    planner_session_state_event: Callable[..., Any]
    required_output_record_conflict: Callable[..., Any]
    source_repair_events: Callable[..., Any]
    typed_lease_event_payload: Callable[..., Any]
    verification_record_conflict: Callable[..., Any]
    cancel_active_lease_events: Callable[..., Any]
    lifecycle_completion_decision_event: Callable[..., Any]
    failure_record_payload: Callable[..., Any]
    recovery_plan_record_payload: Callable[..., Any]


@dataclass(frozen=True)
class CommandExecutionContext:
    """Injected capabilities and universal metadata for command execution."""

    run_id: str
    current_position: int
    clock: Clock
    id_generator: IdGenerator
    actor: Actor
    events: tuple[HydratedEvent, ...]
    future_effects: FutureCommandEffects

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
        # Stored payloads are JSON-safe. Validating from JSON preserves strict
        # scalar rules while allowing JSON encodings of native types such as datetime.
        payload = self.payload_type.model_validate_json(json.dumps(stored.payload))
        metadata = EventMetadata.model_validate(
            stored.model_dump(exclude={"payload", "source_schema_version"})
        )
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
        command: BaseModel,
        projection: Any,
        events: tuple[EventEnvelope, ...],
        context: CommandExecutionContext,
    ) -> list[CommandResult]:
        if type(command) is not self.payload_type:
            msg = f"{self.name} requires exact command class {self.payload_type.__name__}"
            raise TypeError(msg)
        return list(self.handler(cast(CommandT, command), projection, events, context))


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
    "CommandResult",
    "CommandSpecification",
    "EventMetadata",
    "EventSpecification",
    "FutureCommandEffects",
    "HydratedEvent",
    "ProjectionParticipation",
    "StoredEventEnvelope",
    "projection_neutral",
]
