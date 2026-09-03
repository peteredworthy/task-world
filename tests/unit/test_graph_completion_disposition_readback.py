"""Truthful runner completion dispositions on compact public read paths."""

from datetime import UTC, datetime

from orchestrator.api import activity_payload_for_mode, graph_event_payload
from orchestrator.graph import Actor, ActorKind, EventEnvelope


def _event(event_type: str, disposition: str | None = None) -> EventEnvelope:
    payload: dict[str, object] = {"execution_id": "exec"}
    if disposition is not None:
        payload["disposition"] = disposition
    return EventEnvelope(
        event_id=f"event-{event_type}",
        run_id="run",
        position=1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def test_graph_event_and_activity_readback_expose_all_submit_dispositions() -> None:
    cases = (
        (_event("command_rejected"), "rejected"),
        (_event("runner_submission_staged", "durably_staged"), "durably_staged"),
        (
            _event("runner_execution_finalized", "finalized_accepted"),
            "finalized_accepted",
        ),
    )
    for event, disposition in cases:
        for mode in ("full", "summary"):
            assert graph_event_payload(event, payload_mode=mode)["disposition"] == disposition
            assert (
                activity_payload_for_mode(event.event_type, event.payload, mode)["disposition"]
                == disposition
            )
