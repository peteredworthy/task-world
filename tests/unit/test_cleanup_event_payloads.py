from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command as apply_typed_command,
    build_graph_command_dependencies,
    initial_projection,
    reduce_event,
)
from orchestrator.graph import build_graph_catalog
from orchestrator.graph.specifications import CommandExecutionContext, HydratedEvent
from orchestrator.graph.commands import callbacks
from orchestrator.graph import _commands
from orchestrator.graph.events import file_state as file_state_events
from orchestrator.graph.commands.file_state import RecordGatekeeperVerdictsCommand
from orchestrator.graph.events.file_state import (
    FileStateRejectedPayload,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdict,
    GatekeeperVerdictRecordedPayload,
)
from orchestrator.graph.models import StrictFileEntry, StrictFileStateRecord, StrictGitDiffSummary
from orchestrator.graph import StoredEventEnvelope


def apply_command(projection, events, command_type, payload, clock, id_gen):
    payload = dict(payload)
    run_id = payload.pop("run_id")
    catalog = build_graph_catalog()
    hydrated_events = tuple(events)
    output = apply_typed_command(
        catalog,
        projection,
        hydrated_events,
        command_type,
        payload,
        CommandExecutionContext(
            run_id=run_id,
            current_position=max(
                (event.metadata.position for event in hydrated_events), default=-1
            ),
            clock=clock,
            id_generator=id_gen,
            actor=Actor(kind=ActorKind.CONTROLLER),
            events=hydrated_events,
            future_effects=build_graph_command_dependencies(catalog=catalog).future_effects,
            catalog=catalog,
        ),
    )
    return [_stored_event(event) if isinstance(event, HydratedEvent) else event for event in output]


def _stored_event(event: HydratedEvent) -> EventEnvelope:
    metadata = event.metadata
    return (
        build_graph_catalog()
        .resolve_event(metadata.event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=metadata.event_id,
                run_id=metadata.run_id,
                position=metadata.position,
                event_type=metadata.event_type,
                payload_schema_generation=2,
                actor=metadata.actor,
                timestamp=metadata.timestamp,
                payload=event.payload.to_json(),
            )
        )
    )


def test_cleanup_requested_payload_rejects_unknown_and_malformed_fields() -> None:
    valid = {
        "cleanup_id": "cleanup-1",
        "file_state_record_id": "file-state-1",
        "snapshot_id": "snapshot-1",
        "paths": ("secrets.env",),
        "authority": "gatekeeper",
        "reason": "secret found",
        "execution_id": "exec-1",
        "producer_node_id": "gatekeeper-1",
    }

    with pytest.raises(ValidationError):
        CleanupRequestedPayload.model_validate({**valid, "policy": "legacy-top-level"})
    with pytest.raises(ValidationError):
        CleanupRequestedPayload.model_validate({**valid, "paths": ["secrets.env", 7]})


def test_file_state_strict_domain_does_not_delegate_or_dehydrate() -> None:
    event_source = inspect.getsource(file_state_events)
    handler_source = inspect.getsource(
        callbacks.handle_record_gatekeeper_verdicts
    ) + inspect.getsource(callbacks.handle_record_cleanup_applied)

    assert "reduce_legacy_event" not in event_source
    assert "_legacy_reduce" not in event_source
    assert "command.to_json" not in handler_source
    assert "apply_typed_record_" not in handler_source
    command_source = inspect.getsource(_commands)
    assert "apply_typed_record_gatekeeper_verdicts" not in command_source
    assert "apply_typed_record_cleanup_applied" not in command_source
    dispatch_source = Path("src/orchestrator/graph_runtime/dispatch.py").read_text()
    assert "GatekeeperVerdict.model_validate(verdict.to_payload())" not in dispatch_source


def test_file_state_accepted_reuses_strict_file_state_record_contract() -> None:
    assert file_state_events.FileStateAcceptedPayload is StrictFileStateRecord


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_gatekeeper_verdict_accepts_confidence_boundaries(confidence: float) -> None:
    verdict = GatekeeperVerdict(
        path="artifact.txt",
        classification="test_artifact",
        confidence=confidence,
        rationale="boundary",
        model_id="model-1",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.0,
        wall_time_ms=0,
    )
    assert verdict.confidence == confidence


@pytest.mark.parametrize(
    "field",
    [
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cost_usd",
        "wall_time_ms",
    ],
)
def test_gatekeeper_verdict_requires_every_metric(field: str) -> None:
    values = _verdict("artifact.txt", "test_artifact")
    values.update(cache_read_tokens=0, cache_write_tokens=0)
    values.pop(field)
    with pytest.raises(ValidationError):
        GatekeeperVerdict.model_validate(values)


@pytest.mark.parametrize("producer_node_id", [None, ""])
def test_file_state_record_requires_nonempty_producer_node_id(
    producer_node_id: str | None,
) -> None:
    values = _file_state_event("file-state-1", "snapshot-1", []).payload.to_json()
    if producer_node_id is None:
        values.pop("producer_node_id")
    else:
        values["producer_node_id"] = producer_node_id
    with pytest.raises(ValidationError):
        StrictFileStateRecord.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("input_tokens", -1),
        ("output_tokens", -1),
        ("cache_read_tokens", -1),
        ("cache_write_tokens", -1),
        ("cost_usd", -0.01),
        ("wall_time_ms", -1),
        ("confidence", "0.5"),
        ("input_tokens", 1.5),
        ("cost_usd", "0.01"),
        ("wall_time_ms", 1.5),
    ],
)
def test_gatekeeper_verdict_rejects_invalid_numeric_boundaries(field: str, value: object) -> None:
    valid = _verdict("artifact.txt", "test_artifact")
    valid.update(cache_read_tokens=0, cache_write_tokens=0)
    valid[field] = value
    with pytest.raises(ValidationError):
        GatekeeperVerdict.model_validate(valid)
    with pytest.raises(ValidationError):
        RecordGatekeeperVerdictsCommand.model_validate(
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "verdicts": [valid],
            }
        )


@pytest.mark.parametrize(
    ("model", "payload", "field", "value"),
    [
        (
            GatekeeperVerdictRecordedPayload,
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "verdicts": (),
                "resolved_count": 0,
            },
            "resolved_count",
            -1,
        ),
        (
            GatekeeperCostRecordedPayload,
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "consult_id": "consult-1",
                "model_id": "model-1",
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_usd": 0.0,
                "wall_time_ms": 0,
                "item_count": 0,
            },
            "item_count",
            -1,
        ),
        (
            CleanupAppliedPayload,
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "superseding_record_id": "file-state-2",
                "old_snapshot_id": "old",
                "new_snapshot_id": "new",
                "paths": (),
                "authority": "gatekeeper",
                "reason": None,
                "execution_id": "exec-1",
                "deleted_snapshot_ref": True,
                "resolved_count": 0,
            },
            "resolved_count",
            -1,
        ),
    ],
)
def test_event_payloads_reject_negative_aggregate_counts(model, payload, field, value) -> None:
    assert model.model_validate(payload)
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: value})


@pytest.mark.parametrize(
    "field",
    [
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cost_usd",
        "wall_time_ms",
        "item_count",
    ],
)
def test_gatekeeper_cost_rejects_each_negative_numeric_field(field: str) -> None:
    payload = {
        "file_state_record_id": "file-state-1",
        "execution_id": "exec-1",
        "consult_id": "consult-1",
        "model_id": "model-1",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "wall_time_ms": 0,
        "item_count": 0,
    }
    payload[field] = -0.01 if field == "cost_usd" else -1
    with pytest.raises(ValidationError):
        GatekeeperCostRecordedPayload.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (StrictGitDiffSummary, {"files_changed": -1, "additions": 0, "deletions": 0}),
        (StrictGitDiffSummary, {"files_changed": 0, "additions": -1, "deletions": 0}),
        (StrictGitDiffSummary, {"files_changed": 0, "additions": 0, "deletions": -1}),
        (StrictFileEntry, {"path": "artifact", "size_bytes": -1}),
        (StrictFileEntry, {"path": "artifact", "entropy": -0.01}),
        (StrictFileEntry, {"path": "artifact", "entropy": 8.01}),
        (
            FileStateRejectedPayload,
            {
                "node_id": "node-1",
                "run_id": "run-1",
                "execution_id": "exec-1",
                "lease_id": "lease-1",
                "lease_generation": -1,
                "classifications": [],
                "rejected_paths": [],
            },
        ),
    ],
)
def test_task8_similar_numeric_fields_reject_out_of_domain_values(model, payload) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            GatekeeperCostRecordedPayload,
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_usd": 0.0,
                "wall_time_ms": 0,
                "item_count": 0,
            },
        ),
        (
            CleanupRequestedPayload,
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "paths": (),
            },
        ),
        (
            RecordGatekeeperVerdictsCommand,
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "verdicts": [],
            },
        ),
    ],
)
def test_strict_task8_payloads_require_explicit_identity_fields(model, payload) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("field", ["execution_id", "consult_id", "model_id"])
def test_gatekeeper_command_rejects_empty_identity_fields(field: str) -> None:
    payload = {
        "file_state_record_id": "file-state-1",
        "execution_id": "exec-1",
        "consult_id": "consult-1",
        "model_id": "model-1",
        "verdicts": [],
    }
    payload[field] = ""
    with pytest.raises(ValidationError):
        RecordGatekeeperVerdictsCommand.model_validate(payload)


@pytest.mark.parametrize("field", ["authority", "execution_id"])
def test_cleanup_requested_rejects_empty_identity_fields(field: str) -> None:
    payload = {
        "cleanup_id": "cleanup-1",
        "file_state_record_id": "file-state-1",
        "paths": (),
        "authority": "gatekeeper",
        "execution_id": "exec-1",
    }
    payload[field] = ""
    with pytest.raises(ValidationError):
        CleanupRequestedPayload.model_validate(payload)


def test_cleanup_applied_payload_requires_resolved_count_and_rejects_unknown_fields() -> None:
    valid = {
        "cleanup_id": "cleanup-1",
        "file_state_record_id": "file-state-1",
        "superseding_record_id": "file-state-2",
        "old_snapshot_id": "snapshot-old",
        "new_snapshot_id": "snapshot-new",
        "paths": ("secrets.env",),
        "authority": "gatekeeper",
        "reason": "cleanup applied",
        "execution_id": "exec-1",
        "deleted_snapshot_ref": True,
        "resolved_count": 1,
    }

    payload = CleanupAppliedPayload.model_validate(valid)
    assert payload.resolved_count == 1
    with pytest.raises(ValidationError):
        CleanupAppliedPayload.model_validate(
            {key: value for key, value in valid.items() if key != "resolved_count"}
        )
    with pytest.raises(ValidationError):
        CleanupAppliedPayload.model_validate({**valid, "operator_note": "legacy note"})


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
            "consult_id": "consult-1",
            "model_id": "model-1",
            "verdicts": [_verdict("residue.txt", "secret")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    requested_event = next(event for event in emitted if event.event_type == "cleanup_requested")
    requested_payload = requested_event.payload.to_json()
    requested = CleanupRequestedPayload.model_validate_json(json.dumps(requested_payload))
    assert requested.cleanup_id == "file-state-1:gatekeeper-secret"

    requested_payload["cleanup_id"] = "cleanup-1"
    events = [
        *events,
        _event("cleanup_requested", requested_payload, position=requested_event.position),
    ]
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

    applied_payload = CleanupAppliedPayload.model_validate_json(
        json.dumps(applied[0].payload.to_json())
    )
    assert applied[0].event_type == "cleanup_applied"
    assert applied_payload.cleanup_id == "cleanup-1"
    assert applied_payload.superseding_record_id == "file-state-1-cleanup"
    assert applied_payload.deleted_snapshot_ref is True
    assert applied_payload.resolved_count == 1


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return (
        build_graph_catalog()
        .resolve_event(event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=f"{event_type}-{position}",
                run_id="run-1",
                position=position,
                event_type=event_type,
                payload_schema_generation=2,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=FakeClock().now(),
                payload=payload,
            )
        )
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
            "record_type": "file_state",
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
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
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
