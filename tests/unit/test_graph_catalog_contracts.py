"""Catalog-wide contracts for the strict graph kernel."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, cast, get_type_hints

import pytest
from pydantic import ValidationError, model_validator

from orchestrator.graph import (
    Actor,
    ActorKind,
    DuplicateGraphSpecificationError,
    EventMetadata,
    GraphCatalog,
    HydratedEvent,
    UnknownGraphCommandError,
    build_graph_catalog,
    initial_projection,
    reduce_event,
)
from orchestrator.graph.models import EventEnvelope
from orchestrator.graph.commands import COMMAND_SPECIFICATION_GROUPS, apply_command
from orchestrator.graph.events import EVENT_SPECIFICATION_GROUPS
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    ProjectionParticipation,
    StoredEventEnvelope,
)
from orchestrator.graph._commands import _project_with_events, _source_repair_events
from orchestrator.graph.events.topology import NodeReadyPayload
from tests.unit.graph_catalog_samples import COMMAND_SAMPLES, EVENT_SAMPLES


def test_catalog_composes_the_complete_unique_strict_surface() -> None:
    catalog = build_graph_catalog()

    assert len(catalog.events) == 44
    assert len(catalog.commands) == 23
    assert len({spec.name for spec in catalog.events}) == 44
    assert len({spec.name for spec in catalog.commands}) == 23
    assert all(spec.reducer is not None for spec in catalog.events)
    assert build_graph_catalog() == catalog


def test_catalog_rejects_duplicate_event_and_command_specifications() -> None:
    catalog = build_graph_catalog()

    with pytest.raises(DuplicateGraphSpecificationError, match=catalog.events[0].name):
        GraphCatalog.compose((catalog.events[0], catalog.events[0]), ())
    with pytest.raises(DuplicateGraphSpecificationError, match=catalog.commands[0].name):
        GraphCatalog.compose((), (catalog.commands[0], catalog.commands[0]))


def test_typed_dispatch_rejects_an_unknown_current_command_before_execution() -> None:
    catalog = GraphCatalog.compose((), ())

    with pytest.raises(UnknownGraphCommandError, match="unknown graph command: absent"):
        apply_command(catalog, initial_projection(), [], "absent", {}, None)


def test_production_catalog_rejects_an_unknown_current_command_before_execution() -> None:
    with pytest.raises(UnknownGraphCommandError, match="unknown graph command: absent"):
        apply_command(build_graph_catalog(), initial_projection(), [], "absent", {}, None)


def test_catalog_dispatch_validates_a_known_command_once_before_its_handler() -> None:
    counter = _ValidationCounter()

    class CountingCommand(StrictPayload):
        value: str
        validation_counter: ClassVar[_ValidationCounter] = counter

        @model_validator(mode="after")
        def count_validation(self) -> "CountingCommand":
            self.validation_counter.calls += 1
            return self

    def handle(
        command: CountingCommand,
        projection: Any,
        events: tuple[Any, ...],
        context: CommandExecutionContext,
    ) -> list[object]:
        del command, projection, events, context
        return []

    catalog = GraphCatalog.compose((), (CommandSpecification("count", CountingCommand, handle),))
    context = CommandExecutionContext(
        run_id="run-1",
        current_position=0,
        clock=cast(Any, _FixedClock()),
        id_generator=cast(Any, _FixedIdGenerator()),
        actor=Actor(kind=ActorKind.SYSTEM),
        events=(),
        future_effects=cast(Any, object()),
        catalog=catalog,
    )

    assert (
        apply_command(catalog, initial_projection(), [], "count", {"value": "once"}, context) == []
    )
    assert counter.calls == 1


def test_command_specification_rejects_raw_event_results() -> None:
    class RawResultCommand(StrictPayload):
        pass

    def handle(
        command: RawResultCommand,
        projection: Any,
        events: tuple[Any, ...],
        context: CommandExecutionContext,
    ) -> list[EventEnvelope]:
        del command, projection, events, context
        return [
            EventEnvelope(
                event_id="event-raw",
                run_id="run-1",
                position=1,
                event_type="run_lifecycle_changed",
                schema_version=2,
                actor=Actor(kind=ActorKind.SYSTEM),
                timestamp=datetime(2026, 7, 12, tzinfo=UTC),
                payload={"to_state": "active"},
            )
        ]

    catalog = GraphCatalog.compose(
        (), (CommandSpecification("raw-result", RawResultCommand, handle),)
    )
    context = CommandExecutionContext(
        run_id="run-1",
        current_position=0,
        clock=cast(Any, _FixedClock()),
        id_generator=cast(Any, _FixedIdGenerator()),
        actor=Actor(kind=ActorKind.SYSTEM),
        events=(),
        future_effects=cast(Any, object()),
        catalog=catalog,
    )

    with pytest.raises(TypeError, match="HydratedEvent"):
        apply_command(catalog, initial_projection(), [], "raw-result", {}, context)


def test_reduce_event_accepts_only_hydrated_events() -> None:
    raw_event = EventEnvelope(
        event_id="event-raw",
        run_id="run-1",
        position=1,
        event_type="run_lifecycle_changed",
        schema_version=2,
        actor=Actor(kind=ActorKind.SYSTEM),
        timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        payload={"to_state": "active"},
    )

    assert get_type_hints(reduce_event)["event"].__name__ == "HydratedEvent"
    with pytest.raises(TypeError, match="HydratedEvent"):
        reduce_event(build_graph_catalog(), initial_projection(), cast(Any, raw_event))


def test_source_repair_projection_matches_catalog_reduction_for_current_event() -> None:
    catalog = build_graph_catalog()
    specification = catalog.resolve_event("node_state_changed")
    event = specification.create(
        EventMetadata(
            event_id="event-1",
            run_id="run-1",
            position=1,
            event_type="node_state_changed",
            payload_schema_generation=2,
            actor=Actor(kind=ActorKind.SYSTEM),
            timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        ),
        specification.validate_payload({"node_id": "node-1", "new_state": "running"}),
    )

    expected = specification.reduce(initial_projection(), event)

    assert _project_with_events(initial_projection(), [event], catalog) == expected


def test_source_repair_rejects_a_generation_one_current_envelope() -> None:
    catalog = build_graph_catalog()
    specification = catalog.resolve_event("node_state_changed")
    event = specification.create(
        EventMetadata(
            event_id="event-1",
            run_id="run-1",
            position=1,
            event_type="node_state_changed",
            payload_schema_generation=1,
            actor=Actor(kind=ActorKind.SYSTEM),
            timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        ),
        specification.validate_payload({"node_id": "node-1", "new_state": "running"}),
    )

    with pytest.raises(ValueError, match="generation 2"):
        _project_with_events(initial_projection(), [event], catalog)


def test_source_repair_fails_closed_for_corrupt_accepted_record_event() -> None:
    corrupt = HydratedEvent(
        metadata=EventMetadata(
            event_id="event-1",
            run_id="run-1",
            position=1,
            event_type="output_record_accepted",
            payload_schema_generation=2,
            actor=Actor(kind=ActorKind.SYSTEM),
            timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        ),
        payload=NodeReadyPayload(node_id="node-1"),
    )

    with pytest.raises(
        TypeError, match="output_record_accepted event has an unexpected payload type"
    ):
        _source_repair_events(
            initial_projection(),
            [corrupt],
            [corrupt],
            lambda _event_type, _payload: corrupt,
            build_graph_catalog(),
            object(),
        )


def test_catalog_rejects_generation_one_stored_events_without_legacy_hydration() -> None:
    catalog = build_graph_catalog()
    stored = StoredEventEnvelope(
        event_id="event-1",
        run_id="run-1",
        position=1,
        event_type="node_state_changed",
        payload_schema_generation=1,
        actor=Actor(kind=ActorKind.SYSTEM),
        timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        payload={"node_id": "node-1", "new_state": "running"},
    )

    with pytest.raises(ValueError, match="generation 2"):
        catalog.hydrate_event(stored)


def test_command_context_requires_an_explicit_catalog() -> None:
    with pytest.raises(TypeError, match="catalog"):
        CommandExecutionContext(
            run_id="run-1",
            current_position=0,
            clock=cast(Any, _FixedClock()),
            id_generator=cast(Any, _FixedIdGenerator()),
            actor=Actor(kind=ActorKind.SYSTEM),
            events=(),
            future_effects=cast(Any, object()),
        )


def test_catalog_command_surface_is_derived_from_owner_domain_tuples() -> None:
    owner_specs = tuple(spec for group in COMMAND_SPECIFICATION_GROUPS for spec in group)

    assert tuple(spec.name for spec in build_graph_catalog().commands) == tuple(
        spec.name for spec in owner_specs
    )


def test_catalog_event_surface_is_derived_from_owner_domain_tuples() -> None:
    owner_specs = tuple(spec for group in EVENT_SPECIFICATION_GROUPS for spec in group)

    assert tuple(spec.name for spec in build_graph_catalog().events) == tuple(
        spec.name for spec in owner_specs
    )


def test_every_catalog_spec_has_an_explicit_current_producer_sample() -> None:
    catalog = build_graph_catalog()

    assert set(EVENT_SAMPLES) == {spec.name for spec in catalog.events}
    assert set(COMMAND_SAMPLES) == {spec.name for spec in catalog.commands}


@pytest.mark.parametrize("spec", build_graph_catalog().events, ids=lambda spec: spec.name)
def test_every_event_contract_validates_serializes_and_hydrates_once(spec: object) -> None:
    event_spec = spec
    sample = EVENT_SAMPLES[event_spec.name]
    payload = event_spec.validate_payload(sample)
    metadata = EventMetadata(
        event_id="event-1",
        run_id="run-1",
        position=1,
        event_type=event_spec.name,
        payload_schema_generation=2,
        actor=Actor(kind=ActorKind.SYSTEM),
        timestamp=datetime(2026, 7, 12, tzinfo=UTC),
    )

    stored = event_spec.serialize(event_spec.create(metadata, payload))

    assert event_spec.hydrate(stored).payload == payload
    assert event_spec.payload_type.model_json_schema()["type"] == "object"
    assert event_spec.reducer is not None

    with pytest.raises(ValidationError):
        event_spec.validate_payload({**sample, "unexpected_catalog_key": True})
    _assert_required_field_rejects_missing_and_wrong_type(event_spec, sample)
    if event_spec.projection_participation is ProjectionParticipation.NEUTRAL:
        assert event_spec.reducer is not None


@pytest.mark.parametrize("spec", build_graph_catalog().commands, ids=lambda spec: spec.name)
def test_every_command_contract_validates_and_generates_json_schema(spec: object) -> None:
    command_spec = spec
    sample = COMMAND_SAMPLES[command_spec.name]

    assert type(command_spec.validate(sample)) is command_spec.payload_type
    assert command_spec.payload_type.model_json_schema()

    with pytest.raises(ValidationError):
        command_spec.validate({**sample, "unexpected_catalog_key": True})
    _assert_required_field_rejects_missing_and_wrong_type(command_spec, sample)


def _assert_required_field_rejects_missing_and_wrong_type(
    spec: object, sample: dict[str, object]
) -> None:
    required_name = next(
        (name for name, field in spec.payload_type.model_fields.items() if field.is_required()),
        None,
    )
    if required_name is None:
        # Empty/default-only commands and audit records have no producer-required
        # field to remove; their extra-key contract above remains meaningful.
        assert not any(field.is_required() for field in spec.payload_type.model_fields.values())
        return

    # RootModel command schemas expose their discriminated union as ``root``;
    # their producer contract is represented by the discriminator fields.
    contract_field = required_name if required_name in sample else next(iter(sample))
    missing = dict(sample)
    del missing[contract_field]
    with pytest.raises(ValidationError):
        spec.validate_payload(missing) if hasattr(spec, "validate_payload") else spec.validate(
            missing
        )

    mistyped = {**sample, contract_field: object()}
    with pytest.raises(ValidationError):
        spec.validate_payload(mistyped) if hasattr(spec, "validate_payload") else spec.validate(
            mistyped
        )


class _ValidationCounter:
    def __init__(self) -> None:
        self.calls = 0


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 12, tzinfo=UTC)


class _FixedIdGenerator:
    def next_id(self, prefix: str = "") -> str:
        return f"{prefix}-1"
