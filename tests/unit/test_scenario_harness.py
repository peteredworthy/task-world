"""Unit tests for graph scenario harness slice 1.2."""

import pytest

from orchestrator.graph.clock import FakeClock, SequentialIdGenerator
from orchestrator.graph.models import Actor, ActorKind, EventEnvelope
from orchestrator.graph.scenario import run_scenario
from orchestrator.graph.store import DuplicateEventError, InMemoryEventStore


def make_event(run_id: str, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-event",
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def test_scenario_with_all_expected_events_passes() -> None:
    result = run_scenario(
        {
            "name": "node_completed",
            "given_events": [
                {"node_created": {"node_id": "build-A-1", "kind": "worker"}},
                {
                    "node_state_changed": {
                        "node_id": "build-A-1",
                        "new_state": "completed",
                    }
                },
            ],
            "when_command": {"raise_appeal": {"node_id": "build-A-1"}},
            "then_events": [
                {"node_created": {"kind": "worker"}},
                {
                    "node_state_changed": {
                        "node_id": "build-A-1",
                        "new_state": "completed",
                    }
                },
                {"command_recorded": {"command_type": "raise_appeal"}},
            ],
            "then_projection": {"build-A-1": "completed"},
        },
        InMemoryEventStore(),
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert result.passed is True
    assert result.failures == []
    assert [event.position for event in result.events_produced] == [0, 1, 2]
    assert result.projection_snapshot == {"build-A-1": "completed"}


def test_scenario_detects_missing_then_event() -> None:
    result = run_scenario(
        {
            "name": "missing_event",
            "given_events": [{"node_created": {"node_id": "build-A-1"}}],
            "then_events": ["appeal_opened"],
        },
        InMemoryEventStore(),
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert result.passed is False
    assert result.failures == ["Missing expected event: appeal_opened"]


def test_scenario_detects_wrong_payload_in_then_event() -> None:
    result = run_scenario(
        {
            "name": "payload_mismatch",
            "given_events": [{"node_created": {"node_id": "build-A-1"}}],
            "then_events": [{"node_created": {"node_id": "build-A-2"}}],
        },
        InMemoryEventStore(),
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert result.passed is False
    assert result.failures == [
        "Payload mismatch for event node_created: expected fields {'node_id': 'build-A-2'}"
    ]


def test_fake_clock_advances() -> None:
    clock = FakeClock()

    assert clock.now().isoformat() == "2026-01-01T00:00:00+00:00"

    clock.advance(90.5)

    assert clock.now().isoformat() == "2026-01-01T00:01:30.500000+00:00"


def test_sequential_id_generator() -> None:
    id_gen = SequentialIdGenerator()

    assert id_gen.next_id("event") == "event-1"
    assert id_gen.next_id("node") == "node-2"
    assert id_gen.next_id() == "-3"


def test_in_memory_store_append_and_read() -> None:
    store = InMemoryEventStore()

    first = store.append(make_event("run-1", "node_created", {"node_id": "A"}))
    second = store.append(make_event("run-1", "node_state_changed", {"node_id": "A"}))
    other_run = store.append(make_event("run-2", "node_created", {"node_id": "B"}))

    assert first.position == 0
    assert second.position == 1
    assert other_run.position == 0
    assert store.snapshot_position("run-1") == 1
    assert store.snapshot_position("missing") == -1
    assert store.read_from("run-1") == [first, second]
    assert store.read_from("run-1", from_position=1) == [second]


def test_duplicate_event_raises() -> None:
    store = InMemoryEventStore()
    store.append(make_event("run-1", "node_created", {"node_id": "A"}))
    duplicate = make_event("run-1", "node_state_changed", {"node_id": "A"})
    duplicate = duplicate.model_copy(update={"position": 0})

    with pytest.raises(DuplicateEventError):
        store.append(duplicate)
