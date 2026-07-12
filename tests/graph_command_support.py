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
    build_graph_command_dependencies,
    initial_projection,
    reduce_event,
)


def dispatch_graph_command(
    events: list[EventEnvelope | HydratedEvent],
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> list[EventEnvelope]:
    """Dispatch through the real catalog and return store-compatible envelopes."""
    raw_payload = dict(payload or {})
    first_run_id = (
        events[0].metadata.run_id
        if events and isinstance(events[0], HydratedEvent)
        else events[0].run_id
        if events
        else "run-1"
    )
    run_id = str(raw_payload.pop("run_id", first_run_id))
    actor_role = raw_payload.pop("actor_role", None)
    clock = FakeClock()
    id_generator = SequentialIdGenerator()
    projection = initial_projection()
    for event in events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    context = CommandExecutionContext(
        run_id=run_id,
        current_position=max(
            (
                event.metadata.position if isinstance(event, HydratedEvent) else event.position
                for event in events
            ),
            default=-1,
        ),
        clock=clock,
        id_generator=id_generator,
        actor=Actor(
            kind=ActorKind.CONTROLLER,
            role=actor_role if isinstance(actor_role, str) else None,
        ),
        events=(),
        future_effects=build_graph_command_dependencies().future_effects,
    )
    return [
        _legacy_envelope(event)
        for event in apply_command(
            projection,
            events,
            command_type,
            raw_payload,
            clock,
            id_generator,
            catalog=build_graph_catalog(),
            context=context,
        )
    ]


def _legacy_envelope(event: EventEnvelope | HydratedEvent) -> EventEnvelope:
    if isinstance(event, EventEnvelope):
        return event
    return EventEnvelope(
        event_id=event.metadata.event_id,
        run_id=event.metadata.run_id,
        position=event.metadata.position,
        event_type=event.metadata.event_type,
        schema_version=event.metadata.payload_schema_generation,
        actor=event.metadata.actor,
        timestamp=event.metadata.timestamp,
        payload=event.payload.model_dump(mode="json"),
    )


__all__ = ["dispatch_graph_command"]
