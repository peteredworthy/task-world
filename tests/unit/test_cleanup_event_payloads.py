import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    FakeClock,
    SequentialIdGenerator,
    build_projection,
)
from tests.unit.graph_test_utils import apply_command, command_context
from tests.unit.graph_test_utils import event


def test_cleanup_payload_serializes_canonical_shape() -> None:
    raw = {
        "cleanup_id": "cleanup-1",
        "snapshot_id": "snapshot-1",
        "paths": ["tmp/output.txt"],
        "authority": "controller",
    }
    assert (
        CleanupRequestedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"cleanup_id": "cleanup-1", "future_field": True},
        {"cleanup_id": "cleanup-1", "paths": [3]},
    ],
)
def test_cleanup_payload_rejects_unknown_and_wrong_typed_fields(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CleanupRequestedPayload.model_validate(raw)


def test_cleanup_applied_boolean_is_strict() -> None:
    with pytest.raises(ValidationError):
        CleanupAppliedPayload.model_validate({"cleanup_id": "cleanup-1", "deleted_snapshot_ref": 1})


def test_cleanup_command_producers_match_typed_payload_json() -> None:
    file_state = event(
        "file_state_accepted",
        {
            "record_id": "file-state-1",
            "record_kind": "file_state",
            "record_type": "file_state",
            "producer_node_id": "worker-1",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": "snapshot-1",
            "base_snapshot_id": "base-1",
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
            "verdict": "captured",
            "residue": [
                {
                    "path": "residue.txt",
                    "source": "untracked",
                    "classification": "unknown_untracked",
                    "matched_rule": "unmatched_untracked",
                    "needs_gatekeeper": True,
                    "size_bytes": 42,
                }
            ],
        },
        position=1,
    )
    events = [file_state]
    requested_events = apply_command(
        build_projection(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [
                {
                    "path": "residue.txt",
                    "classification": "secret",
                    "confidence": 0.9,
                    "rationale": "metadata shape matches",
                    "model_id": "gatekeeper-test",
                    "gen_ai_usage_input_tokens": 11,
                    "gen_ai_usage_output_tokens": 3,
                    "cost_usd": 0.001,
                    "wall_time_ms": 12,
                }
            ],
        },
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )
    requested_event = next(
        item for item in requested_events if item.event_type == "cleanup_requested"
    )
    assert requested_event.payload == CleanupRequestedPayload.model_validate(
        requested_event.payload
    ).model_dump(mode="json")

    requested_event.payload["cleanup_id"] = "cleanup-1"
    events.append(requested_event)
    applied_events = apply_command(
        build_projection(events),
        events,
        "record_cleanup_applied",
        {
            "cleanup_id": "cleanup-1",
            "superseding_file_state_record": {
                "record_id": "file-state-1-cleanup",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": "snapshot-clean",
                "base_snapshot_id": "base-1",
                "supersedes_record_id": "file-state-1",
                "cleanup_id": "cleanup-1",
                "cleanup_excluded_paths": ["residue.txt"],
                "classifications": [],
                "residue": [],
            },
            "deleted_snapshot_ref": True,
        },
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )
    applied = next(item.payload for item in applied_events if item.event_type == "cleanup_applied")
    assert applied == CleanupAppliedPayload.model_validate(applied).model_dump(mode="json")
