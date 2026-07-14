"""Generic maintenance-cost contracts for graph catalog extensions."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import chain
from typing import Any, cast

from orchestrator.graph import (
    Actor,
    ActorKind,
    CommandExecutionContext,
    CommandSpecification,
    EventMetadata,
    EventSpecification,
    GraphCatalog,
    ProjectionParticipation,
    StrictPayload,
)


class _ExpandedEventPayload(StrictPayload):
    original: str
    added: int


class _ExpandedCommand(StrictPayload):
    original: str
    added: int


def _reduce_expanded(
    state: tuple[str, int], payload: _ExpandedEventPayload, metadata: EventMetadata
) -> tuple[str, int]:
    del state, metadata
    return payload.original, payload.added


def test_added_payload_field_spreads_through_every_generic_event_and_command_path() -> None:
    observed: list[tuple[str, int]] = []

    def handle_expanded(
        command: _ExpandedCommand,
        projection: Any,
        events: tuple[Any, ...],
        context: CommandExecutionContext,
    ) -> list[object]:
        del projection, events, context
        observed.append((command.original, command.added))
        return []

    event_spec = EventSpecification(
        "expanded_event",
        _ExpandedEventPayload,
        _reduce_expanded,
        ProjectionParticipation.MUTATES,
    )
    command_spec = CommandSpecification("expanded_command", _ExpandedCommand, handle_expanded)
    metadata = EventMetadata(
        event_id="event-1",
        run_id="run-1",
        position=1,
        event_type=event_spec.name,
        payload_schema_generation=2,
        actor=Actor(kind=ActorKind.SYSTEM),
        timestamp=datetime(2026, 7, 13, tzinfo=UTC),
    )
    payload_data = {"original": "kept", "added": 7}

    payload = event_spec.validate_payload(payload_data)
    event = event_spec.create(metadata, payload)
    stored = event_spec.serialize(event)
    hydrated = event_spec.hydrate(stored)

    assert set(event_spec.payload_type.model_json_schema()["properties"]) == {
        "original",
        "added",
    }
    assert stored.payload == payload_data
    assert hydrated.payload.to_json() == payload_data
    assert hydrated.model_dump(mode="json")["payload"] == payload_data
    assert event_spec.reduce(("", 0), hydrated) == ("kept", 7)
    assert event_spec.serialize(hydrated) == stored

    command = command_spec.validate(payload_data)
    command_spec.handle(
        command,
        {},
        (),
        CommandExecutionContext(
            run_id="run-1",
            current_position=0,
            clock=cast(Any, object()),
            id_generator=cast(Any, object()),
            actor=Actor(kind=ActorKind.SYSTEM),
            events=(),
            future_effects=cast(Any, object()),
            catalog=GraphCatalog.compose((), ()),
        ),
    )
    assert set(command_spec.payload_type.model_json_schema()["properties"]) == {
        "original",
        "added",
    }
    assert observed == [("kept", 7)]


def test_new_owner_tuple_specs_compose_and_dispatch_without_central_edits() -> None:
    handled: list[int] = []

    def reduce_second(state: int, payload: _ExpandedEventPayload, metadata: EventMetadata) -> int:
        del metadata
        return state + payload.added

    def handle_second(
        command: _ExpandedCommand,
        projection: Any,
        events: tuple[Any, ...],
        context: CommandExecutionContext,
    ) -> list[object]:
        del projection, events, context
        handled.append(command.added)
        return []

    event_domain = (
        EventSpecification(
            "first_event",
            _ExpandedEventPayload,
            _reduce_expanded,
            ProjectionParticipation.MUTATES,
        ),
        EventSpecification(
            "second_event",
            _ExpandedEventPayload,
            reduce_second,
            ProjectionParticipation.MUTATES,
        ),
    )
    command_domain = (
        CommandSpecification("first_command", _ExpandedCommand, handle_second),
        CommandSpecification("second_command", _ExpandedCommand, handle_second),
    )
    catalog = GraphCatalog.compose(
        chain.from_iterable((event_domain,)), chain.from_iterable((command_domain,))
    )

    second_event = catalog.resolve_event("second_event")
    payload = second_event.validate_payload({"original": "x", "added": 3})
    metadata = EventMetadata(
        event_id="event-2",
        run_id="run-1",
        position=2,
        event_type="second_event",
        payload_schema_generation=2,
        actor=Actor(kind=ActorKind.SYSTEM),
        timestamp=datetime(2026, 7, 13, tzinfo=UTC),
    )
    assert second_event.reduce(4, second_event.create(metadata, payload)) == 7

    second_command = catalog.resolve_command("second_command")
    second_command.handle(
        second_command.validate({"original": "x", "added": 9}),
        {},
        (),
        CommandExecutionContext(
            run_id="run-1",
            current_position=0,
            clock=cast(Any, object()),
            id_generator=cast(Any, object()),
            actor=Actor(kind=ActorKind.SYSTEM),
            events=(),
            future_effects=cast(Any, object()),
            catalog=catalog,
        ),
    )
    assert handled == [9]
