from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    project_gatekeeper_report,
    project_pattern_library,
    project_residue_report,
    reduce_event,
)


def test_record_gatekeeper_verdicts_accepts_and_resolves_residue() -> None:
    events = [_file_state_event("file-state-1", "reports/result.xml")]
    projection = _project(events)

    emitted = apply_command(
        projection,
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [_verdict("reports/result.xml", "test_artifact")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert [event.event_type for event in emitted] == [
        "gatekeeper_verdict_recorded",
        "gatekeeper_cost_recorded",
    ]
    report = project_residue_report([*events, *emitted])
    assert report["reports/result.xml"][0]["classification"] == "test_artifact"
    assert report["reports/result.xml"][0]["matched_rule"] == "gatekeeper:claude-test"
    assert report["reports/result.xml"][0]["needs_gatekeeper"] is False


def test_record_gatekeeper_verdicts_rejects_unknown_record_id() -> None:
    emitted = apply_command(
        initial_projection(),
        [],
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "missing",
            "execution_id": "exec-1",
            "verdicts": [_verdict("tmp.out", "build_output")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "unknown file_state record: missing"


def test_record_gatekeeper_verdicts_rejects_path_not_in_residue() -> None:
    events = [_file_state_event("file-state-1", "tmp.out")]

    emitted = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [_verdict("other.out", "build_output")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "path is not unresolved residue: other.out"


def test_record_gatekeeper_verdicts_rejects_invalid_taxonomy_value() -> None:
    events = [_file_state_event("file-state-1", "tmp.out")]

    emitted = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [_verdict("tmp.out", "unknown_untracked")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert "invalid classification for tmp.out" in str(emitted[0].payload["reason"])


def test_record_gatekeeper_verdicts_rejects_duplicate_already_resolved_path() -> None:
    events = [_file_state_event("file-state-1", "tmp.out")]
    first = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [_verdict("tmp.out", "build_output")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    emitted = apply_command(
        _project([*events, *first]),
        [*events, *first],
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [_verdict("tmp.out", "build_output")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "path is not unresolved residue: tmp.out"


def test_project_pattern_library_derives_and_merges_globs() -> None:
    events = [
        _file_state_event("file-state-1", "reports/a.xml", position=1),
        _gatekeeper_event("file-state-1", [_verdict("reports/a.xml", "test_artifact")], 2),
        _file_state_event("file-state-2", "reports/b.xml", position=3),
        _gatekeeper_event("file-state-2", [_verdict("reports/b.xml", "test_artifact")], 4),
        _file_state_event("file-state-3", "root.py", position=5),
        _gatekeeper_event("file-state-3", [_verdict("root.py", "test_artifact")], 6),
    ]

    library = project_pattern_library(events)

    assert library["patterns"]["reports/*.xml"]["classification"] == "test_artifact"
    assert library["patterns"]["reports/*.xml"]["occurrences"] == 2
    assert library["patterns"]["reports/*.xml"]["paths"] == [
        "reports/a.xml",
        "reports/b.xml",
    ]
    assert library["paths"]["reports/a.xml"]["classification"] == "test_artifact"
    assert library["patterns"]["root.py"]["classification"] == "test_artifact"
    assert "*.py" not in library["patterns"]


def test_record_gatekeeper_verdicts_requires_execution_id() -> None:
    events = [_file_state_event("file-state-1", "tmp.out")]

    emitted = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "verdicts": [_verdict("tmp.out", "build_output")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "missing execution_id"


def test_record_gatekeeper_verdicts_rejects_duplicate_path_in_same_payload() -> None:
    events = [_file_state_event("file-state-1", "tmp.out")]

    emitted = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "verdicts": [
                _verdict("tmp.out", "build_output"),
                _verdict("tmp.out", "build_output"),
            ],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "duplicate verdict path: tmp.out"


def test_record_gatekeeper_verdicts_secret_requests_cleanup_and_marks_projection() -> None:
    events = [_file_state_event("file-state-1", "residue.txt")]

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

    assert [event.event_type for event in emitted] == [
        "gatekeeper_verdict_recorded",
        "cleanup_requested",
        "gatekeeper_cost_recorded",
    ]
    cleanup = emitted[1]
    assert cleanup.payload["snapshot_id"] == "snapshot-file-state-1"
    assert cleanup.payload["paths"] == ["residue.txt"]
    assert cleanup.payload["authority"] == "gatekeeper"

    projection = _project([*events, *emitted])
    record = projection["file_state_records"]["file-state-1"]
    assert record["compromised"] is True
    assert record["superseded_pending"] is True
    assert record["compromised_paths"] == ["residue.txt"]


def test_record_cleanup_applied_rejects_unknown_cleanup() -> None:
    events = [_file_state_event("file-state-1", "residue.txt")]

    emitted = apply_command(
        _project(events),
        events,
        "record_cleanup_applied",
        {
            "run_id": "run-1",
            "cleanup_id": "missing-cleanup",
            "superseding_file_state_record": _superseding_record(),
            "deleted_snapshot_ref": True,
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "unknown cleanup_requested: missing-cleanup"


def test_record_cleanup_applied_rejects_duplicate_cleanup() -> None:
    events = _cleanup_requested_events()
    first = apply_command(
        _project(events),
        events,
        "record_cleanup_applied",
        {
            "run_id": "run-1",
            "cleanup_id": "cleanup-1",
            "superseding_file_state_record": _superseding_record(cleanup_id="cleanup-1"),
            "deleted_snapshot_ref": True,
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    second = apply_command(
        _project([*events, *first]),
        [*events, *first],
        "record_cleanup_applied",
        {
            "run_id": "run-1",
            "cleanup_id": "cleanup-1",
            "superseding_file_state_record": _superseding_record(cleanup_id="cleanup-1"),
            "deleted_snapshot_ref": False,
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert second[0].event_type == "command_rejected"
    assert second[0].payload["reason"] == "cleanup already applied: cleanup-1"


def test_record_cleanup_applied_rejects_same_snapshot_supersede() -> None:
    events = _cleanup_requested_events()
    record = _superseding_record(cleanup_id="cleanup-1")
    record["snapshot_id"] = "snapshot-file-state-1"

    emitted = apply_command(
        _project(events),
        events,
        "record_cleanup_applied",
        {
            "run_id": "run-1",
            "cleanup_id": "cleanup-1",
            "superseding_file_state_record": record,
            "deleted_snapshot_ref": True,
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert emitted[0].payload["reason"] == "superseding record must use a different snapshot_id"


def test_record_cleanup_applied_rejects_superseding_record_with_secret_path() -> None:
    events = _cleanup_requested_events()
    record = _superseding_record(cleanup_id="cleanup-1")
    record["classifications"] = [
        {
            "path": "residue.txt",
            "source": "untracked",
            "classification": "secret",
        }
    ]

    emitted = apply_command(
        _project(events),
        events,
        "record_cleanup_applied",
        {
            "run_id": "run-1",
            "cleanup_id": "cleanup-1",
            "superseding_file_state_record": record,
            "deleted_snapshot_ref": True,
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert emitted[0].event_type == "command_rejected"
    assert (
        emitted[0].payload["reason"]
        == "superseding record still contains cleanup secret path: residue.txt"
    )


def test_project_gatekeeper_report_hit_rate_and_growth() -> None:
    events = [
        _file_state_event("file-state-1", "reports/a.xml", position=1),
        _gatekeeper_event("file-state-1", [_verdict("reports/a.xml", "test_artifact")], 2),
        _cost_event("file-state-1", position=3),
        _file_state_event(
            "file-state-2",
            "reports/b.xml",
            position=4,
            classification="test_artifact",
            matched_rule="pattern_library:reports/*.xml",
            needs_gatekeeper=False,
        ),
    ]

    report = project_gatekeeper_report(events)["run-1"]

    assert report["deterministic_classifications"] == 1
    assert report["gatekeeper_consults"] == 1
    assert report["gatekeeper_resolved"] == 1
    assert report["hit_rate"] == 0.5
    assert report["pattern_library_size"] == 1
    assert [entry["size"] for entry in report["pattern_library_size_over_time"]] == [0, 1, 1]
    assert report["input_tokens"] == 11
    assert report["output_tokens"] == 3
    assert report["cost_usd"] == 0.001
    assert report["models"]["claude-test"]["consults"] == 1
    assert report["models"]["claude-test"]["input_tokens"] == 11
    assert report["models"]["claude-test"]["executions"] == ["exec-1"]


def _project(events: list[EventEnvelope]):
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _file_state_event(
    record_id: str,
    path: str,
    *,
    position: int = 1,
    classification: str = "unknown_untracked",
    matched_rule: str = "unmatched_untracked",
    needs_gatekeeper: bool = True,
) -> EventEnvelope:
    entry = {
        "path": path,
        "source": "untracked",
        "classification": classification,
        "matched_rule": matched_rule,
        "needs_gatekeeper": needs_gatekeeper,
        "size_bytes": 42,
    }
    return _event(
        "file_state_accepted",
        {
            "record_id": record_id,
            "record_kind": "file_state",
            "producer_node_id": "worker-1",
            "snapshot_id": f"snapshot-{record_id}",
            "base_snapshot_id": "base-1",
            "git": {
                "commit_sha": f"commit-{record_id}",
                "tree_sha": f"tree-{record_id}",
                "ref": f"refs/orchestrator/snapshots/snapshot-{record_id}",
            },
            "classifications": [entry],
            "residue": [entry],
        },
        position=position,
    )


def _gatekeeper_event(
    record_id: str,
    verdicts: list[dict[str, Any]],
    position: int,
) -> EventEnvelope:
    return _event(
        "gatekeeper_verdict_recorded",
        {
            "file_state_record_id": record_id,
            "execution_id": "exec-1",
            "producer_node_id": "worker-1",
            "verdicts": verdicts,
            "resolved_count": len(verdicts),
        },
        position=position,
    )


def _cost_event(record_id: str, *, position: int) -> EventEnvelope:
    return _event(
        "gatekeeper_cost_recorded",
        {
            "file_state_record_id": record_id,
            "execution_id": "exec-1",
            "consult_id": "consult-1",
            "model_id": "claude-test",
            "input_tokens": 11,
            "output_tokens": 3,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_usd": 0.001,
            "wall_time_ms": 12,
            "item_count": 1,
        },
        position=position,
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


def _cleanup_requested_events() -> list[EventEnvelope]:
    events = [_file_state_event("file-state-1", "residue.txt")]
    emitted = apply_command(
        _project(events),
        events,
        "record_gatekeeper_verdicts",
        {
            "run_id": "run-1",
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "consult_id": "consult-1",
            "verdicts": [_verdict("residue.txt", "secret")],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    cleanup = next(event for event in emitted if event.event_type == "cleanup_requested")
    cleanup.payload["cleanup_id"] = "cleanup-1"
    return [*events, cleanup]


def _superseding_record(*, cleanup_id: str = "missing-cleanup") -> dict[str, Any]:
    return {
        "record_id": "file-state-1-cleanup",
        "record_kind": "file_state",
        "producer_node_id": "worker-1",
        "snapshot_id": "snapshot-clean",
        "base_snapshot_id": "base-1",
        "supersedes_record_id": "file-state-1",
        "cleanup_id": cleanup_id,
        "git": {
            "commit_sha": "commit-clean",
            "tree_sha": "tree-clean",
            "ref": "refs/orchestrator/snapshots/snapshot-clean",
        },
        "classifications": [],
        "residue": [],
    }


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
