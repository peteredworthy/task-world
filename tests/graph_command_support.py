"""Real typed graph-command dispatch support shared by test harnesses."""

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    CommandExecutionContext,
    EventEnvelope,
    FakeClock,
    HydratedEvent,
    SequentialIdGenerator,
    apply_command,
    build_graph_catalog,
    initial_projection,
    reduce_event,
)
from orchestrator.graph import StoredEventEnvelope


def dispatch_graph_command(
    events: list[EventEnvelope | HydratedEvent],
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> list[HydratedEvent]:
    """Explicit test adapter for catalog dispatch over hydrated fixture history."""
    raw_payload = dict(payload or {})
    first_run_id = (
        events[0].metadata.run_id
        if events and isinstance(events[0], HydratedEvent)
        else events[0].run_id
        if events
        else "run-1"
    )
    run_id = str(raw_payload.pop("run_id", first_run_id))
    actor_role = raw_payload.get("actor_role")
    if command_type != "submit_patch":
        raw_payload.pop("actor_role", None)
    clock = FakeClock()
    id_generator = SequentialIdGenerator()
    catalog = build_graph_catalog()
    hydrated_events = [_hydrate_fixture_event(event) for event in events]
    projection = initial_projection()
    for event in hydrated_events:
        projection = reduce_event(catalog, projection, event)
    context = CommandExecutionContext(
        run_id=run_id,
        current_position=max(
            (event.position for event in hydrated_events),
            default=-1,
        ),
        clock=clock,
        id_generator=id_generator,
        actor=Actor(
            kind=ActorKind.CONTROLLER,
            role=actor_role if isinstance(actor_role, str) else None,
        ),
        events=tuple(hydrated_events),
        catalog=catalog,
    )
    return apply_command(
        catalog,
        projection,
        hydrated_events,
        command_type,
        raw_payload,
        context,
    )


def with_metadata_position(event: HydratedEvent, position: int) -> HydratedEvent:
    """Return a typed fixture event at a new persisted stream position."""
    return event.model_copy(
        update={"metadata": event.metadata.model_copy(update={"position": position})}
    )


def _hydrate_fixture_event(event: EventEnvelope | HydratedEvent) -> HydratedEvent:
    if isinstance(event, HydratedEvent):
        return event
    return (
        build_graph_catalog()
        .resolve_event(event.event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=event.event_id,
                run_id=event.run_id,
                position=event.position,
                event_type=event.event_type,
                # Command fixtures are hydrated through the strict catalog;
                # the legacy envelope's default schema_version is not a
                # persisted payload-generation value.
                payload_schema_generation=2,
                actor=event.actor,
                timestamp=event.timestamp,
                payload=event.payload,
            )
        )
    )


__all__ = ["dispatch_graph_command", "with_metadata_position"]
