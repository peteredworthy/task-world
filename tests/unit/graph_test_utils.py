from datetime import datetime, timezone
from typing import Any

from orchestrator.graph import Actor, ActorKind, EventEnvelope


def event(
    event_type: str,
    payload: dict[str, Any],
    *,
    position: int = 0,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        payload=payload,
    )
