from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    reduce_event,
)


def test_cleanup_requested_payload_normalizes_legacy_free_form_keys_to_extra() -> None:
    payload = CleanupRequestedPayload.model_validate(
        {
            "cleanup_id": "cleanup-1",
            "file_state_record_id": "file-state-1",
            "snapshot_id": "snapshot-1",
            "paths": ["secrets.env", 7],
            "authority": {"kind": "gatekeeper", "policy": "delete-secret"},
            "reason": "secret found",
            "execution_id": "exec-1",
            "producer_node_id": "gatekeeper-1",
            "policy": "legacy-top-level",
        }
    )

    assert payload.cleanup_id == "cleanup-1"
    assert payload.paths == ["secrets.env"]
    assert payload.authority is None
    assert payload.extra == {
        "authority": {"kind": "gatekeeper", "policy": "delete-secret"},
        "policy": "legacy-top-level",
    }


def test_cleanup_applied_payload_normalizes_legacy_free_form_keys_to_extra() -> None:
    payload = CleanupAppliedPayload.model_validate(
        {
            "cleanup_id": "cleanup-1",
            "file_state_record_id": "file-state-1",
            "superseding_record_id": "file-state-2",
            "old_snapshot_id": "snapshot-old",
            "new_snapshot_id": "snapshot-new",
            "paths": ["secrets.env", None],
            "authority": {"kind": "gatekeeper"},
            "reason": "cleanup applied",
            "execution_id": "exec-1",
            "deleted_snapshot_ref": True,
            "operator_note": "legacy note",
        }
    )

    assert payload.paths == ["secrets.env"]
    assert payload.authority is None
    assert payload.deleted_snapshot_ref is True
    assert payload.extra == {
        "authority": {"kind": "gatekeeper"},
        "operator_note": "legacy note",
    }


def test_cleanup_reducers_tolerate_legacy_payloads_through_typed_models() -> None:
    projection = reduce_event(
        initial_projection(),
        _file_state_event("file-state-1", "snapshot-1", ["secrets.env"]),
    )

    projection = reduce_event(
        projection,
        _event(
            "cleanup_requested",
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "snapshot_id": "snapshot-1",
                "paths": ["secrets.env", 123],
                "authority": {"kind": "gatekeeper"},
                "reason": "secret found",
                "legacy_note": "kept under extra",
            },
            position=2,
        ),
    )

    requested = projection["cleanup_requested_events"]["cleanup-1"]
    assert requested.paths == ["secrets.env"]
    assert requested.authority is None
    assert requested.extra == {
        "authority": {"kind": "gatekeeper"},
        "legacy_note": "kept under extra",
    }

    projection = reduce_event(
        projection,
        _event(
            "cleanup_applied",
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "superseding_record_id": "file-state-2",
                "deleted_snapshot_ref": True,
                "authority": {"kind": "gatekeeper"},
                "legacy_note": "kept under extra",
            },
            position=3,
        ),
    )

    record = projection["file_state_records"]["file-state-1"]
    assert projection["cleanup_applied_ids"] == {"cleanup-1": True}
    assert record.superseded_by_record_id == "file-state-2"
    assert record.compromised_snapshot_deleted is True


def test_cleanup_producers_emit_payloads_validated_by_typed_models() -> None:
    events = [_file_state_event("file-state-1", "snapshot-file-state-1", ["residue.txt"])]

    emitted = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [_verdict("residue.txt", "secret")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    requested_event = next(event for event in emitted if event.event_type == "cleanup_requested")
    requested = CleanupRequestedPayload.model_validate(requested_event.payload)
    assert requested.cleanup_id == "file-state-1:gatekeeper-secret"
    assert requested.extra == {}

    requested_event.payload["cleanup_id"] = "cleanup-1"
    events = [*events, requested_event]
    applied = apply_command(
        _project(events),
        events,
        "record_cleanup_applied",
        {
            "run_id": "run-1",
            "cleanup_id": "cleanup-1",
            "superseding_file_state_record": _superseding_record(),
            "deleted_snapshot_ref": True,
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    applied_payload = CleanupAppliedPayload.model_validate(applied[0].payload)
    assert applied[0].event_type == "cleanup_applied"
    assert applied_payload.cleanup_id == "cleanup-1"
    assert applied_payload.superseding_record_id == "file-state-1-cleanup"
    assert applied_payload.deleted_snapshot_ref is True
    assert applied_payload.extra == {}


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def _file_state_event(
    record_id: str,
    snapshot_id: str,
    residue_paths: list[str],
) -> EventEnvelope:
    return _event(
        "file_state_accepted",
        {
            "record_id": record_id,
            "record_kind": "file_state",
            "producer_node_id": "worker-1",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": snapshot_id,
            "base_snapshot_id": "base-1",
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
            "verdict": "captured",
            "residue": [
                {
                    "path": path,
                    "source": "untracked",
                    "classification": "unknown_untracked",
                    "matched_rule": "unmatched_untracked",
                    "needs_gatekeeper": True,
                    "size_bytes": 42,
                }
                for path in residue_paths
            ],
        },
        position=1,
    )


def _verdict(path: str, classification: str) -> dict[str, Any]:
    return {
        "path": path,
        "classification": classification,
        "confidence": 0.9,
        "rationale": "metadata shape matches",
        "model_id": "claude-test",
        "input_tokens": 11,
        "output_tokens": 3,
        "cost_usd": 0.001,
        "wall_time_ms": 12,
    }


def _superseding_record() -> dict[str, Any]:
    return {
        "record_id": "file-state-1-cleanup",
        "record_kind": "file_state",
        "producer_node_id": "worker-1",
        "snapshot_id": "snapshot-clean",
        "base_snapshot_id": "base-1",
        "supersedes_record_id": "file-state-1",
        "cleanup_id": "cleanup-1",
        "git": {
            "commit_sha": "commit-clean",
            "tree_sha": "tree-clean",
            "ref": "refs/orchestrator/snapshots/snapshot-clean",
        },
        "classifications": [],
        "residue": [],
    }
