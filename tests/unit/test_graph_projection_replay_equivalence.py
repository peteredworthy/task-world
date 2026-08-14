"""Permanent contracts for deterministic full, incremental, and checkpointed replay."""

from copy import deepcopy
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    ExternalFileEntry,
    FileEntry,
    FileStateRecord,
    build_projection,
    initial_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
)
from tests.unit.graph_projection_behavior_cases import behavior_cases, fold_events, replay_streams


STREAMS = replay_streams()


@pytest.mark.parametrize("case", behavior_cases(), ids=lambda case: case.event_type)
def test_matrix_streams_match_full_incremental_and_checkpoint_tail_replay_at_every_split(
    case,
) -> None:
    stream = case.stream
    full = fold_events(stream)
    full_query = case.query(full)
    for split in range(len(stream) + 1):
        prefix = fold_events(stream[:split])
        incremental = fold_events(stream[split:], prefix)
        assert incremental == full, (case.event_type, split)
        assert case.query(incremental) == full_query, (case.event_type, split, "incremental")

        checkpoint = projection_to_checkpoint(prefix)
        restored = projection_from_checkpoint(deepcopy(checkpoint))
        checkpoint_tail = fold_events(stream[split:], restored)
        assert checkpoint_tail == full, (case.event_type, split)
        assert case.query(checkpoint_tail) == full_query, (case.event_type, split, "checkpoint")


def test_gatekeeper_verdict_replay_after_checkpoint_preserves_projected_file_entry_type() -> None:
    stream = dict(STREAMS)["gatekeeper_verdict_recorded"]
    prefix = fold_events(stream[:3])
    full = fold_events(stream)

    restored = projection_from_checkpoint(deepcopy(projection_to_checkpoint(prefix)))

    assert fold_events(stream[3:], restored) == full


def test_canonical_gatekeeper_stream_preserves_ordinary_and_external_entry_subtypes() -> None:
    stream = dict(STREAMS)["gatekeeper_verdict_recorded"]
    direct = fold_events(stream)
    direct_record = direct.records.by_id["file-state-1"]
    assert isinstance(direct_record, FileStateRecord)
    assert type(direct_record.untracked[0]) is FileEntry
    assert type(direct_record.external[0]) is ExternalFileEntry

    restored = projection_from_checkpoint(
        deepcopy(projection_to_checkpoint(fold_events(stream[:3])))
    )
    replayed = fold_events(stream[3:], restored)
    replayed_record = replayed.records.by_id["file-state-1"]
    assert isinstance(replayed_record, FileStateRecord)
    assert type(replayed_record.untracked[0]) is FileEntry
    assert type(replayed_record.external[0]) is ExternalFileEntry


def _fold(projection: Any, events: tuple[EventEnvelope, ...] | list[EventEnvelope]) -> Any:
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def test_retired_node_stale_callback_stream_matches_at_every_replay_split() -> None:
    events = (
        EventEnvelope(
            event_id="created",
            run_id="retired-run",
            position=0,
            event_type="node_created",
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=FakeClock().now(),
            payload={"node_id": "retired-worker", "kind": "worker", "state": "planned"},
        ),
        EventEnvelope(
            event_id="retired",
            run_id="retired-run",
            position=1,
            event_type="node_state_changed",
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=FakeClock().now(),
            payload={"node_id": "retired-worker", "new_state": "retired"},
        ),
        EventEnvelope(
            event_id="stale-callback",
            run_id="retired-run",
            position=2,
            event_type="callback_rejected_stale",
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=FakeClock().now(),
            payload={
                "node_id": "retired-worker",
                "lease_id": "lease-retired",
                "lease_generation": 1,
                "execution_id": "execution-retired",
                "idempotency_key": "retired-callback",
                "payload": None,
                "reason": "node_retired",
            },
        ),
    )
    full = build_projection(list(events))

    for split in range(len(events) + 1):
        prefix = build_projection(list(events[:split]))
        assert _fold(prefix, events[split:]) == full
        restored = projection_from_checkpoint(deepcopy(projection_to_checkpoint(prefix)))
        assert _fold(restored, events[split:]) == full


def test_invalid_checkpoint_fails_strictly_without_sibling_salvage() -> None:
    raw = projection_to_checkpoint(initial_projection())
    raw["lifecycle"] = {"unknown": True}

    with pytest.raises(ValidationError):
        projection_from_checkpoint(raw)


@st.composite
def valid_bounded_event_sequences(draw: st.DrawFn) -> list[EventEnvelope]:
    ready_flags = draw(st.lists(st.booleans(), min_size=0, max_size=5))
    events: list[EventEnvelope] = []
    position = 0
    if draw(st.booleans()):
        events.append(
            EventEnvelope(
                event_id=f"generated-{position}",
                run_id="generated-run",
                position=position,
                event_type="run_lifecycle_changed",
                schema_version=1,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=FakeClock().now(),
                payload={
                    "command_type": "start",
                    "from_state": "queued",
                    "to_state": "active",
                    "trigger": "hypothesis",
                },
            )
        )
        position += 1
    for index, becomes_ready in enumerate(ready_flags):
        node_id = f"generated-node-{index}"
        events.append(
            EventEnvelope(
                event_id=f"generated-{position}",
                run_id="generated-run",
                position=position,
                event_type="node_created",
                schema_version=1,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=FakeClock().now(),
                payload={"node_id": node_id, "kind": "worker", "state": "planned"},
            )
        )
        position += 1
        if becomes_ready:
            events.append(
                EventEnvelope(
                    event_id=f"generated-{position}",
                    run_id="generated-run",
                    position=position,
                    event_type="node_state_changed",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=FakeClock().now(),
                    payload={
                        "node_id": node_id,
                        "new_state": "ready",
                        "trigger": "hypothesis",
                    },
                )
            )
            position += 1
    return events


@given(valid_bounded_event_sequences())
@settings(max_examples=20, deadline=None)
def test_generated_valid_event_sequences_have_equivalent_replay_paths(
    events: list[EventEnvelope],
) -> None:
    stream = tuple(events)
    full = build_projection(list(stream))
    for split in range(len(stream) + 1):
        prefix = build_projection(list(stream[:split]))
        assert _fold(prefix, stream[split:]) == full

        checkpoint = projection_to_checkpoint(prefix)
        restored = projection_from_checkpoint(deepcopy(checkpoint))
        assert _fold(restored, stream[split:]) == full
