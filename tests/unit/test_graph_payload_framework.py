from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.graph.catalog import (
    DuplicateGraphSpecificationError,
    GraphCatalog,
    UnknownGraphCommandError,
    UnknownGraphEventError,
    build_graph_catalog,
)
from orchestrator.graph.commands.lifecycle import RECORD_HEARTBEAT, RecordHeartbeatCommand
from orchestrator.graph.events.lifecycle import HEARTBEAT_RECORDED, HeartbeatRecordedPayload
from orchestrator.graph.models import Actor, ActorKind
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


class ExamplePayload(StrictPayload):
    node_id: str
    generation: int


class DerivedExamplePayload(ExamplePayload):
    pass


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class FixedIds:
    def next_id(self, prefix: str = "") -> str:
        return f"{prefix}-1"


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
ACTOR = Actor(kind=ActorKind.CONTROLLER)


def metadata(event_type: str = "example") -> EventMetadata:
    return EventMetadata(
        event_id="event-1",
        run_id="run-1",
        position=4,
        event_type=event_type,
        payload_schema_generation=2,
        actor=ACTOR,
        timestamp=NOW,
    )


def test_strict_payload_rejects_unknown_and_coerced_fields() -> None:
    with pytest.raises(ValidationError):
        ExamplePayload.model_validate({"node_id": "n-1", "generation": "1"})
    with pytest.raises(ValidationError):
        ExamplePayload.model_validate({"node_id": "n-1", "generation": 1, "typo": True})


def test_strict_payload_is_frozen_and_serializes_json_values() -> None:
    payload = HeartbeatRecordedPayload(
        node_id="n-1",
        lease_id="lease-1",
        lease_generation=2,
        observed_at=NOW,
    )

    with pytest.raises(ValidationError):
        payload.node_id = "n-2"
    assert payload.to_json()["observed_at"] == "2026-07-10T12:00:00Z"


def test_event_specification_requires_exact_payload_class_and_round_trips_json() -> None:
    spec = EventSpecification(
        name="example",
        payload_type=ExamplePayload,
        reducer=lambda state, payload, meta: {**state, payload.node_id: meta.position},
        projection_participation=ProjectionParticipation.MUTATES,
    )
    payload = ExamplePayload(node_id="n-1", generation=1)

    event = spec.create(metadata(), payload)
    stored = spec.serialize(event)
    hydrated = spec.hydrate(stored)

    assert hydrated.payload == payload
    assert spec.reduce({}, hydrated) == {"n-1": 4}
    with pytest.raises(TypeError, match="exact payload class ExamplePayload"):
        spec.create(metadata(), DerivedExamplePayload(node_id="n-1", generation=1))


def test_command_specification_validates_once_and_requires_exact_class_at_dispatch() -> None:
    seen: list[ExamplePayload] = []

    def handle(payload: ExamplePayload, context: CommandExecutionContext) -> list[object]:
        del context
        seen.append(payload)
        return []

    spec = CommandSpecification(name="example", payload_type=ExamplePayload, handler=handle)
    command = spec.validate({"node_id": "n-1", "generation": 1})
    context = CommandExecutionContext(
        run_id="run-1",
        current_position=4,
        clock=FixedClock(NOW),
        id_generator=FixedIds(),
        actor=ACTOR,
        events=(),
    )

    assert spec.handle(command, context) == []
    assert seen == [command]
    with pytest.raises(TypeError, match="exact command class ExamplePayload"):
        spec.handle(DerivedExamplePayload(node_id="n-1", generation=1), context)


def test_catalog_rejects_duplicate_names() -> None:
    with pytest.raises(DuplicateGraphSpecificationError, match="heartbeat_recorded"):
        GraphCatalog.compose(
            event_specs=(HEARTBEAT_RECORDED, HEARTBEAT_RECORDED),
            command_specs=(),
        )


def test_catalog_is_immutable_and_unknown_names_raise_typed_errors() -> None:
    catalog = GraphCatalog.compose((HEARTBEAT_RECORDED,), (RECORD_HEARTBEAT,))

    with pytest.raises(TypeError):
        catalog.event_specs["other"] = HEARTBEAT_RECORDED
    with pytest.raises(UnknownGraphEventError, match="missing"):
        catalog.resolve_event("missing")
    with pytest.raises(UnknownGraphCommandError, match="missing"):
        catalog.resolve_command("missing")


def test_heartbeat_command_emits_projection_neutral_typed_event() -> None:
    catalog = build_graph_catalog()
    command = catalog.resolve_command("record_heartbeat").validate(
        {"node_id": "worker-1", "lease_id": "lease-1", "lease_generation": 2}
    )
    context = CommandExecutionContext(
        run_id="run-1",
        current_position=4,
        clock=FixedClock(NOW),
        id_generator=FixedIds(),
        actor=ACTOR,
        events=(),
    )

    events = catalog.resolve_command("record_heartbeat").handle(command, context)
    event = events[0]
    spec = catalog.resolve_event(event.metadata.event_type)

    assert type(command) is RecordHeartbeatCommand
    assert type(event.payload) is HeartbeatRecordedPayload
    assert event.payload.observed_at == NOW
    assert spec.projection_participation is ProjectionParticipation.NEUTRAL
    projection = {"kept": True}
    assert spec.reduce(projection, event) is projection
