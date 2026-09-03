"""Permanent contracts for deterministic full, incremental, and checkpointed replay."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    GraphCommandContext,
    EventEnvelope,
    FakeClock,
    ExternalFileEntry,
    FileEntry,
    FileStateRecord,
    build_projection,
    apply_command,
    boundary_manifest_hash,
    execution_attempts_view,
    initial_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    recovery_proof_hash,
    SequentialIdGenerator,
)
from orchestrator.graph_runtime import (
    CrashBarrierObservation,
    CrashBarrierRecoveryProof,
    CrashBarrierSlotState,
    schema_two_slot_lineage_authorized,
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


def test_recovered_retry_lineage_survives_every_checkpoint_split() -> None:
    """Schema-2 lineage remains authoritative after any checkpoint boundary."""
    clock = FakeClock()
    tree_sha = "a" * 40
    boundary_hash = boundary_manifest_hash(tree_sha, [])
    proof_hash = recovery_proof_hash(
        execution_id="execution-1",
        recovery_id="recovery-1",
        node_id="effectful-1",
        lease_id="lease-1",
        lease_generation=1,
        baseline_snapshot_id="baseline-1",
        baseline_tree_sha=tree_sha,
        requested_paths=(),
        restored_paths=(),
        removed_paths=(),
    )

    def event(position: int, event_type: str, payload: dict[str, object]) -> EventEnvelope:
        return EventEnvelope(
            event_id=f"lineage-{position}",
            run_id="lineage-run",
            position=position,
            event_type=event_type,
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=clock.now(),
            payload=payload,
        )

    stream = (
        event(
            0,
            "node_created",
            {
                "node_id": "effectful-1",
                "kind": "worker",
                "state": "running",
                "attempt_number": 1,
                "max_attempts": 3,
            },
        ),
        event(
            1,
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "effectful-1",
                "generation": 1,
                "execution_id": "execution-1",
                "base_snapshot_id": "base-1",
            },
        ),
        event(
            2,
            "runner_baseline_recorded",
            {
                "execution_id": "execution-1",
                "node_id": "effectful-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "lease_base_snapshot_id": "base-1",
                "baseline_snapshot_id": "baseline-1",
                "baseline_tree_sha": tree_sha,
                "entries": [],
                "boundary_hash": boundary_hash,
            },
        ),
        event(
            3,
            "runner_submission_staged",
            {
                "execution_id": "execution-1",
                "node_id": "effectful-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "idempotency_key": "staged-1",
                "payload": {},
                "payload_hash": "sha256:" + "b" * 64,
                "staged_snapshot_id": "staged-1",
                "staged_tree_sha": tree_sha,
                "boundary_hash": boundary_hash,
                "boundary_entries": [],
                "base_snapshot_id": "base-1",
                "observed_graph_position": 1,
                "is_mutating": True,
                "complete_node": True,
                "new_state": "completed",
            },
        ),
        event(
            4,
            "runner_recovery_requested",
            {
                "execution_id": "execution-1",
                "recovery_id": "recovery-1",
                "node_id": "effectful-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "reason": "runner_died",
                "max_attempts": 3,
                "retry_after_recovery": True,
                "baseline_snapshot_id": "baseline-1",
                "baseline_tree_sha": tree_sha,
                "final_tree_sha": tree_sha,
                "final_boundary_hash": boundary_hash,
                "final_boundary_entries": [],
                "paths": [],
            },
        ),
        event(
            5,
            "runner_recovery_completed",
            {
                "execution_id": "execution-1",
                "recovery_id": "recovery-1",
                "node_id": "effectful-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "baseline_snapshot_id": "baseline-1",
                "baseline_tree_sha": tree_sha,
                "requested_paths": [],
                "proof_hash": proof_hash,
                "restored_paths": [],
                "removed_paths": [],
                "disposition": "restored_unwitnessed",
            },
        ),
        event(
            6,
            "runtime_retry_scheduled",
            {
                "node_id": "effectful-1",
                "lease_id": "lease-1",
                "generation": 1,
                "policy": "immediate",
                "reason": "runner_died",
            },
        ),
    )
    first_slot = CrashBarrierSlotState(
        slot=1,
        point="after_staging_pre_witness",
        status="consumed_after_process_loss",
        node_id="effectful-1",
        execution_id="execution-1",
        lease_id="lease-1",
        lease_generation=1,
        owner_pid=1234,
        owner_create_time=1.0,
        release_token="f" * 48,
        reached_at=clock.now(),
    )

    for split in range(len(stream) + 1):
        prefix = build_projection(list(stream[:split]))
        restored = projection_from_checkpoint(deepcopy(projection_to_checkpoint(prefix)))
        replayed = _fold(restored, stream[split:])
        attempt = execution_attempts_view(replayed)["execution-1"]
        assert attempt.state == "recovered", split
        assert attempt.completion_disposition == "restored_unwitnessed", split
        assert attempt.retry_scheduled is True, split
        proof = CrashBarrierRecoveryProof(
            node_id=attempt.node_id,
            execution_id=attempt.execution_id,
            lease_generation=attempt.lease_generation,
            state="recovered",
            completion_disposition=attempt.completion_disposition,
            retry_authorized=attempt.retry_scheduled,
        )
        valid = CrashBarrierObservation(
            run_id="lineage-run",
            node_id="effectful-1",
            execution_id="execution-2",
            lease_id="lease-2",
            lease_generation=2,
            node_kind="worker",
            node_role="builder",
            semantic_stage="effectful_batch",
            point="after_witness_pre_finalization",
            attempt_state="completion_witnessed",
            recovered_attempts=(proof,),
        )
        assert schema_two_slot_lineage_authorized(first_slot, valid) is True, split
        assert (
            schema_two_slot_lineage_authorized(
                first_slot, valid.model_copy(update={"lease_generation": 1})
            )
            is False
        ), split
        assert (
            schema_two_slot_lineage_authorized(
                first_slot, valid.model_copy(update={"execution_id": "execution-1"})
            )
            is False
        ), split


def test_copied_legacy_incident_staged_stream_replays_and_recovers_fail_closed() -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "graph" / "legacy-staged-incident.json"
    raw_events = json.loads(fixture_path.read_text(encoding="utf-8"))
    stream = tuple(EventEnvelope.model_validate(item) for item in raw_events)
    full = build_projection(list(stream))
    execution_id = "exec-ab62d27ce1284035a451143db5a27692"
    full_attempt = execution_attempts_view(full)[execution_id]
    assert full_attempt.state == "submission_staged"
    assert full_attempt.completion_disposition == "durably_staged"
    assert full_attempt.runner_return_kind is None

    for split in range(len(stream) + 1):
        prefix = build_projection(list(stream[:split]))
        assert _fold(prefix, stream[split:]) == full
        restored = projection_from_checkpoint(deepcopy(projection_to_checkpoint(prefix)))
        assert _fold(restored, stream[split:]) == full

    recovery = apply_command(
        full,
        list(stream),
        "request_runner_recovery",
        {
            "execution_id": execution_id,
            "node_id": "worker-reliable-plan-rp-01",
            "lease_id": "lease-8fd4e1385a904de5acd2c3d062269f2f",
            "lease_generation": 1,
            "reason": "runner_died",
            "error_detail": "legacy staged attempt has no durable completion witness",
            "max_attempts": 1,
            "final_tree_sha": "95b9aa9671492c11c80eecb7fca46d8456dcfab4",
            "boundary_hash": (
                "sha256:48b68511f3ee8a1b22e40d2c76caee586c985b6563c795ca1617c6c76418609d"
            ),
            "boundary_entries": [],
        },
        GraphCommandContext(
            run_id="917a81b5-117c-403b-b344-640696e8d750",
            current_graph_position=146,
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert [item.event_type for item in recovery] == ["runner_recovery_requested"]
    requested = reduce_event(full, recovery[0])
    attempt = execution_attempts_view(requested)[execution_id]
    proof = recovery_proof_hash(
        execution_id=execution_id,
        recovery_id=str(attempt.recovery_id),
        node_id=attempt.node_id,
        lease_id=attempt.lease_id,
        lease_generation=attempt.lease_generation,
        baseline_snapshot_id=str(attempt.baseline_snapshot_id),
        baseline_tree_sha=str(attempt.baseline_tree_sha),
        requested_paths=(),
        restored_paths=(),
        removed_paths=(),
    )
    completed = apply_command(
        requested,
        [*stream, recovery[0]],
        "complete_runner_recovery",
        {
            "execution_id": execution_id,
            "recovery_id": attempt.recovery_id,
            "node_id": attempt.node_id,
            "lease_id": attempt.lease_id,
            "lease_generation": attempt.lease_generation,
            "baseline_snapshot_id": attempt.baseline_snapshot_id,
            "baseline_tree_sha": attempt.baseline_tree_sha,
            "requested_paths": [],
            "restored_paths": [],
            "removed_paths": [],
            "proof_hash": proof,
        },
        GraphCommandContext(
            run_id="917a81b5-117c-403b-b344-640696e8d750",
            current_graph_position=147,
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert completed[0].event_type == "runner_recovery_completed"
    assert completed[0].payload["disposition"] == "restored_unwitnessed"
    assert not any(
        item.event_type in {"runner_execution_finalized", "callback_accepted"}
        for item in (*recovery, *completed)
    )


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
