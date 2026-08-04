"""Direct pure-command coverage for the runner execution boundary kernel."""

import pytest
from copy import deepcopy

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    GraphCommandContext,
    MAX_BOUNDARY_MANIFEST_ITEMS,
    SequentialIdGenerator,
    apply_command,
    boundary_manifest_hash,
    derive_recovery_paths,
    initial_projection,
    node_state,
    ProjectionReplayConflictError,
    recovery_proof_hash,
    reduce_event,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_final_invariant_blockers,
)
from orchestrator.graph import BoundaryValidationError
from orchestrator.graph_runtime.outbox import outbox_payload_for_event


OID = "a" * 40
HASH = "sha256:" + "b" * 64


def _entry(
    path: str,
    *,
    kind: str = "tracked",
    status: str = "clean",
    fingerprint: str = HASH,
    file_type: str = "file",
) -> dict[str, str]:
    return {
        "path": path,
        "kind": kind,
        "status": status,
        "fingerprint": fingerprint,
        "file_type": file_type,
    }


def _event(kind: str, payload: dict[str, object], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"seed-{position}",
        run_id="run",
        position=position,
        event_type=kind,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def _projection(
    *,
    kind: str = "worker",
    role: str | None = None,
    attempt_number: int | None = None,
    max_attempts: int | None = None,
):
    projection = initial_projection()
    node_payload = {"node_id": "node", "kind": kind, "state": "running"}
    if role is not None:
        node_payload["role"] = role
    if attempt_number is not None:
        node_payload["attempt_number"] = attempt_number
    if max_attempts is not None:
        node_payload["max_attempts"] = max_attempts
    for event in (
        _event("node_created", node_payload, 1),
        _event(
            "lease_granted",
            {
                "lease_id": "lease",
                "node_id": "node",
                "generation": 1,
                "execution_id": "exec",
                "base_snapshot_id": "snap",
            },
            2,
        ),
    ):
        projection = reduce_event(projection, event)
    return projection


def _apply(projection, command: str, payload: dict[str, object]):
    payload = dict(payload)
    # Historical fixture literals below are normalized at the command boundary;
    # every actual command payload is the unified RunnerBoundaryEntry shape.
    entry_key = "entries" if command == "record_runner_baseline" else "boundary_entries"
    if entry_key in payload:
        payload[entry_key] = [
            _entry(
                str(entry["path"]),
                kind=str(entry["kind"]),
                status=str(entry.get("status", entry.get("original_status", "clean"))),
                fingerprint=str(entry["fingerprint"]),
                file_type=str(entry.get("file_type", "file")),
            )
            for entry in payload[entry_key]
        ]
    if command == "record_runner_baseline":
        snapshot_id = str(payload["baseline_snapshot_id"])
        payload.setdefault("baseline_snapshot_ref", f"refs/orchestrator/snapshots/{snapshot_id}")
        payload.setdefault("baseline_commit_sha", OID)
        try:
            payload["boundary_hash"] = boundary_manifest_hash(
                payload["baseline_tree_sha"],
                payload["entries"],
                payload.get("cache_status_evidence", []),
            )
        except BoundaryValidationError:
            payload["boundary_hash"] = HASH
    elif (
        command in {"stage_runner_submission", "finalize_runner_execution"}
        and "boundary_entries" in payload
    ):
        tree_key = "staged_tree_sha" if command == "stage_runner_submission" else "final_tree_sha"
        payload["boundary_hash"] = boundary_manifest_hash(
            payload[tree_key],
            payload["boundary_entries"],
            payload.get("cache_status_evidence", []),
        )
        prefix = "staged" if command == "stage_runner_submission" else "final"
        snapshot_id = str(payload[f"{prefix}_snapshot_id"])
        payload.setdefault("%s_snapshot_ref" % prefix, f"refs/orchestrator/snapshots/{snapshot_id}")
        payload.setdefault("%s_commit_sha" % prefix, OID)
    return apply_command(
        projection,
        [],
        command,
        payload,
        GraphCommandContext(run_id="run", current_graph_position=2),
        FakeClock(),
        SequentialIdGenerator(),
    )


def _staged_projection(
    *,
    kind: str = "worker",
    role: str | None = None,
    attempt_number: int | None = None,
    max_attempts: int | None = None,
):
    projection = _projection(
        kind=kind,
        role=role,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
    )
    baseline = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_snapshot_ref": "refs/orchestrator/snapshots/snap",
            "baseline_commit_sha": OID,
            "baseline_tree_sha": OID,
            "entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                }
            ],
            "cache_roots": [],
        },
    )
    projection = reduce_event(projection, baseline[0])
    stage = _apply(
        projection,
        "stage_runner_submission",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "base_snapshot_id": "snap",
            "observed_graph_position": 2,
            "idempotency_key": "key",
            "payload": {},
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": "staged",
            "staged_snapshot_ref": "refs/orchestrator/snapshots/staged",
            "staged_commit_sha": OID,
            "staged_tree_sha": OID,
            "boundary_hash": HASH,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                }
            ],
        },
    )
    return reduce_event(projection, stage[0])


def _cache_root(path: str, kind: str) -> dict[str, str]:
    return {"path": path, "kind": kind}


def _staged_cache_transition(baseline_kind: str, staged_kind: str):
    projection = _projection()
    root_path = ".pytest_cache"
    baseline = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "entries": [],
            "cache_roots": [_cache_root(root_path, baseline_kind)],
            "cache_status_evidence": [_cache_root(f"{root_path}/entry", baseline_kind)],
        },
    )
    projection = reduce_event(projection, baseline[0])
    staged = _apply(
        projection,
        "stage_runner_submission",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "base_snapshot_id": "snap",
            "observed_graph_position": 2,
            "idempotency_key": "key",
            "payload": {},
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": "staged",
            "staged_tree_sha": OID,
            "boundary_entries": [],
            "cache_roots": [_cache_root(root_path, staged_kind)],
            "cache_status_evidence": [_cache_root(f"{root_path}/entry", staged_kind)],
        },
    )
    return reduce_event(projection, staged[0])


@pytest.mark.parametrize(
    ("baseline_kind", "staged_kind", "final_kind"),
    [
        ("ignored", "untracked", "untracked"),
        ("untracked", "ignored", "ignored"),
        ("ignored", "untracked", "ignored"),
    ],
)
def test_recovery_authority_uses_latest_phase_kind_for_the_same_root(
    baseline_kind: str, staged_kind: str, final_kind: str
) -> None:
    projection = _staged_cache_transition(baseline_kind, staged_kind)
    final_entries = [_entry("changed.py", kind="untracked", status="created")]
    events = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_entries": final_entries,
            "cache_roots": [_cache_root(".pytest_cache", final_kind)],
            "cache_status_evidence": [_cache_root(".pytest_cache/entry", final_kind)],
        },
    )

    assert [event.event_type for event in events] == [
        "runner_boundary_mismatch",
        "runner_recovery_requested",
    ]
    assert all(
        event.payload["authorized_cache_roots"] == [_cache_root(".pytest_cache", final_kind)]
        for event in events
    )
    recovered = reduce_event(reduce_event(projection, events[0]), events[1])
    assert projection_from_checkpoint(projection_to_checkpoint(recovered)) == recovered


def test_recovery_authority_still_rejects_conflicts_within_one_phase() -> None:
    projection = _staged_cache_transition("ignored", "untracked")
    events = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_entries": [_entry("changed.py", kind="untracked", status="created")],
            "cache_roots": [
                _cache_root(".pytest_cache", "ignored"),
                _cache_root(".pytest_cache", "untracked"),
            ],
            "cache_status_evidence": [],
        },
    )

    assert [event.event_type for event in events] == ["command_rejected"]


def test_finalization_requests_exact_cleanup_for_every_owned_snapshot_ref() -> None:
    projection = _projection()
    baseline = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "lease_base_snapshot_id": "snap",
            "baseline_snapshot_id": "baseline",
            "baseline_snapshot_ref": "refs/orchestrator/snapshots/baseline",
            "baseline_commit_sha": OID,
            "baseline_tree_sha": OID,
            "entries": [],
            "cache_roots": [],
        },
    )
    projection = reduce_event(projection, baseline[0])
    staged = _apply(
        projection,
        "stage_runner_submission",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "base_snapshot_id": "snap",
            "observed_graph_position": 2,
            "idempotency_key": "key",
            "payload": {},
            "staged_snapshot_id": "staged",
            "staged_snapshot_ref": "refs/orchestrator/snapshots/staged",
            "staged_commit_sha": OID,
            "staged_tree_sha": OID,
            "boundary_entries": [],
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
        },
    )
    assert staged[0].event_type == "runner_submission_staged", staged[0].payload
    projection = reduce_event(projection, staged[0])
    events = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_snapshot_ref": "refs/orchestrator/snapshots/final",
            "final_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_entries": [],
        },
    )
    assert events[0].event_type == "runner_execution_finalized"
    cleanups = [event.payload for event in events if event.event_type == "cleanup_requested"]
    assert [(item["snapshot_role"], item["snapshot_ref"]) for item in cleanups] == [
        ("baseline", "refs/orchestrator/snapshots/baseline"),
        ("staged", "refs/orchestrator/snapshots/staged"),
        ("final", "refs/orchestrator/snapshots/final"),
    ]
    assert all(item["tree_sha"] == OID and item["lease_id"] == "lease" for item in cleanups)


def _recovery_projection(*, attempt_number: int | None = None, max_attempts: int | None = None):
    projection = _staged_projection(attempt_number=attempt_number, max_attempts=max_attempts)
    finalize = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_snapshot_ref": "refs/orchestrator/snapshots/final",
            "final_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_hash": "sha256:" + "c" * 64,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "modified",
                    "fingerprint": "sha256:" + "c" * 64,
                }
            ],
        },
    )
    assert not any(item.event_type == "cleanup_requested" for item in finalize)
    for event in finalize:
        projection = reduce_event(projection, event)
    request = finalize[1]
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=request.payload["recovery_id"],
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id="snap",
        baseline_tree_sha=OID,
        requested_paths=("src/a.py",),
        restored_paths=("src/a.py",),
        removed_paths=(),
    )
    completion_payload = {
        "execution_id": "exec",
        "recovery_id": request.payload["recovery_id"],
        "node_id": "node",
        "lease_id": "lease",
        "lease_generation": 1,
        "baseline_snapshot_id": "snap",
        "baseline_tree_sha": OID,
        "requested_paths": ["src/a.py"],
        "proof_hash": proof,
        "restored_paths": ["src/a.py"],
        "removed_paths": [],
    }
    completion_events = _apply(projection, "complete_runner_recovery", completion_payload)
    for event in completion_events:
        projection = reduce_event(projection, event)
    return projection, completion_payload, completion_events


def test_boundary_mismatch_recovery_retries_when_attempts_remain() -> None:
    projection, _, completion_events = _recovery_projection(attempt_number=1, max_attempts=3)

    assert [event.event_type for event in completion_events[:4]] == [
        "runner_recovery_completed",
        "lease_revoked",
        "runtime_retry_scheduled",
        "node_state_changed",
    ]
    assert completion_events[2].payload["reason"] == "boundary_mismatch"
    assert completion_events[3].payload == {
        "node_id": "node",
        "new_state": "ready",
        "trigger": "runner_recovery_completed_retry_scheduled",
        "attempt_number": 2,
    }
    assert node_state(projection, "node") == "ready"


def test_boundary_mismatch_recovery_fails_when_attempts_are_exhausted() -> None:
    projection, _, completion_events = _recovery_projection(attempt_number=3, max_attempts=3)

    assert [event.event_type for event in completion_events[:3]] == [
        "runner_recovery_completed",
        "lease_revoked",
        "node_state_changed",
    ]
    assert completion_events[2].payload == {
        "node_id": "node",
        "new_state": "failed",
        "trigger": "max_attempts_exhausted",
        "reason": "max_attempts_exhausted",
        "attempt_number": 3,
        "max_attempts": 3,
    }
    assert not any(event.event_type == "runtime_retry_scheduled" for event in completion_events)
    assert node_state(projection, "node") == "failed"


def test_runner_boundary_commands_stage_without_publication_then_request_proven_recovery() -> None:
    projection = _projection()
    baseline = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                }
            ],
            "cache_roots": [],
        },
    )
    assert [item.event_type for item in baseline] == ["runner_baseline_recorded"]
    projection = reduce_event(projection, baseline[0])
    stage = _apply(
        projection,
        "stage_runner_submission",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "base_snapshot_id": "snap",
            "observed_graph_position": 2,
            "idempotency_key": "key",
            "payload": {},
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": "staged",
            "staged_tree_sha": OID,
            "boundary_hash": HASH,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                }
            ],
        },
    )
    assert [item.event_type for item in stage] == ["runner_submission_staged"]
    projection = reduce_event(projection, stage[0])
    mismatch = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_hash": "sha256:" + "c" * 64,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "modified",
                    "fingerprint": "sha256:" + "c" * 64,
                }
            ],
        },
    )
    assert [item.event_type for item in mismatch] == [
        "runner_boundary_mismatch",
        "runner_recovery_requested",
    ]
    for item in mismatch:
        projection = reduce_event(projection, item)
    recovery_id = mismatch[1].payload["recovery_id"]
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=recovery_id,
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id="snap",
        baseline_tree_sha=OID,
        requested_paths=("src/a.py",),
        restored_paths=("src/a.py",),
        removed_paths=(),
    )
    completed = _apply(
        projection,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": recovery_id,
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "requested_paths": ["src/a.py"],
            "proof_hash": proof,
            "restored_paths": ["src/a.py"],
            "removed_paths": [],
        },
    )
    assert [item.event_type for item in completed] == [
        "runner_recovery_completed",
        "lease_revoked",
        "runtime_retry_scheduled",
        "node_state_changed",
        "cleanup_requested",
        "cleanup_requested",
        "cleanup_requested",
    ]


def test_runner_recovery_completes_non_gap_planner_with_accepted_patch() -> None:
    projection = _staged_projection(kind="planner", role="planner")
    projection = reduce_event(
        projection,
        _event(
            "graph_patch_accepted",
            {"patch_id": "patch-1", "proposed_by_node_id": "node"},
            3,
        ),
    )
    entries = [_entry("src/a.py", status="modified", fingerprint="sha256:" + "c" * 64)]
    requested = _apply(
        projection,
        "request_runner_recovery",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "reason": "runner_died",
            "max_attempts": 3,
            "recovery_snapshot_id": "recovery",
            "recovery_snapshot_ref": "refs/orchestrator/snapshots/recovery",
            "recovery_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_hash": boundary_manifest_hash(OID, entries),
            "boundary_entries": entries,
        },
    )
    assert [event.event_type for event in requested] == ["runner_recovery_requested"]
    projection = reduce_event(projection, requested[0])
    recovery_id = requested[0].payload["recovery_id"]
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=recovery_id,
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id="snap",
        baseline_tree_sha=OID,
        requested_paths=("src/a.py",),
        restored_paths=("src/a.py",),
        removed_paths=(),
    )

    completed = _apply(
        projection,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": recovery_id,
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "requested_paths": ["src/a.py"],
            "proof_hash": proof,
            "restored_paths": ["src/a.py"],
            "removed_paths": [],
        },
    )

    assert [event.event_type for event in completed[:3]] == [
        "runner_recovery_completed",
        "lease_revoked",
        "node_state_changed",
    ]
    assert completed[2].payload == {
        "node_id": "node",
        "new_state": "completed",
        "trigger": "accepted_graph_patch_before_agent_death",
    }
    assert not any(event.event_type == "runtime_retry_scheduled" for event in completed)


def test_runner_recovery_request_is_a_durable_selective_restore_outbox_effect() -> None:
    projection = _staged_projection()
    mismatch = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_hash": "sha256:" + "c" * 64,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "modified",
                    "fingerprint": "sha256:" + "c" * 64,
                }
            ],
        },
    )

    mapped = outbox_payload_for_event(mismatch[1])

    assert mapped is not None
    kind, payload = mapped
    assert kind == "runner_recovery"
    assert payload["classification"] == "runner_recovery_pending"
    assert payload["baseline_snapshot_id"] == "snap"
    assert payload["paths"] == ["src/a.py"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorized_cache_roots", [{"path": ".pytest_cache", "kind": "ignored"}]),
        ("legacy_cache_root_paths", ["legacy-cache"]),
    ],
)
def test_boundary_mismatch_replay_binds_root_authority_to_the_staged_attempt(
    field: str, value: object
) -> None:
    """An audit mismatch cannot independently widen recovery root authority."""
    projection = _staged_projection()
    mismatch = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_entries": [
                _entry("src/a.py", status="modified", fingerprint="sha256:" + "c" * 64)
            ],
        },
    )[0]

    # The newly emitted fact has an explicit observed-root carrier and is
    # accepted.  Changing either aggregate carrier must fail before its paired
    # recovery request can be trusted.
    assert reduce_event(projection, mismatch) is projection
    altered_payload = dict(mismatch.payload)
    altered_payload[field] = value
    altered = mismatch.model_copy(update={"payload": altered_payload})
    with pytest.raises(ProjectionReplayConflictError, match="root authority conflicts"):
        reduce_event(projection, altered)


def test_boundary_command_rejects_hash_only_stage_and_baseline_snapshot_mismatch() -> None:
    projection = _projection()
    bad_baseline = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "other",
            "baseline_tree_sha": OID,
            "entries": [],
            "cache_roots": [],
        },
    )
    assert [item.event_type for item in bad_baseline] == ["command_rejected"]
    baseline = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "entries": [],
            "cache_roots": [],
        },
    )
    projection = reduce_event(projection, baseline[0])
    hash_only = _apply(
        projection,
        "stage_runner_submission",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "base_snapshot_id": "snap",
            "observed_graph_position": 2,
            "idempotency_key": "key",
            "payload_hash": HASH,
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": "staged",
            "staged_tree_sha": OID,
            "boundary_hash": HASH,
        },
    )
    assert [item.event_type for item in hash_only] == ["command_rejected"]


def test_baseline_entries_are_canonicalized_and_ambiguous_ancestors_rejected() -> None:
    projection = _projection()
    unordered_duplicate = _apply(
        projection,
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "entries": [
                {
                    "path": "z.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                },
                {
                    "path": "a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                },
                {
                    "path": "z.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                },
            ],
            "cache_roots": [],
        },
    )
    assert [event.event_type for event in unordered_duplicate] == ["command_rejected"]

    ambiguous = _apply(
        _projection(),
        "record_runner_baseline",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": "snap",
            "baseline_tree_sha": OID,
            "entries": [
                {"path": "src", "kind": "tracked", "original_status": "clean", "fingerprint": HASH},
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                },
            ],
            "cache_roots": [],
        },
    )
    assert [event.event_type for event in ambiguous] == ["command_rejected"]


def test_exact_duplicate_recovery_completion_is_idempotent_and_changed_fields_conflict() -> None:
    recovered, completion, completion_events = _recovery_projection()
    assert [
        item.payload["snapshot_role"]
        for item in completion_events
        if item.event_type == "cleanup_requested"
    ] == ["baseline", "staged", "final"]
    assert _apply(recovered, "complete_runner_recovery", completion) == []
    changed_accounting = {**completion, "restored_paths": [], "removed_paths": ["src/a.py"]}
    assert [
        event.event_type
        for event in _apply(recovered, "complete_runner_recovery", changed_accounting)
    ] == ["command_rejected"]
    changed_proof = {**completion, "proof_hash": "sha256:" + "d" * 64}
    assert [
        event.event_type for event in _apply(recovered, "complete_runner_recovery", changed_proof)
    ] == ["command_rejected"]


def test_exact_duplicate_finalization_event_replays_idempotently() -> None:
    projection = _staged_projection()
    finalization = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_hash": HASH,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                }
            ],
        },
    )
    after = reduce_event(projection, finalization[0])
    assert reduce_event(after, finalization[0]) is after


def test_complete_manifest_recovery_derivation_covers_transitions_and_cache_roots() -> None:
    """Commands and replay share complete entry identity, not a baseline-only path list."""
    baseline = [
        _entry("delete.py"),
        _entry("keep.py"),
        _entry("link", file_type="symlink"),
        _entry("old-name.py"),
    ]
    staged = [
        _entry("add.py", kind="untracked", status="created"),
        _entry("copy.py", status="copied_to"),
        _entry("keep.py"),
        _entry("link", file_type="file", status="modified"),
        _entry("new-name.py", status="renamed_to"),
    ]
    final = [
        _entry("add.py", kind="untracked", status="created"),
        _entry("copy.py", status="copied_to"),
        _entry("keep.py"),
        _entry("link", file_type="file", status="modified"),
        _entry("new-name.py", status="renamed_to"),
    ]

    assert derive_recovery_paths(
        baseline, staged, final, [{"path": ".cache", "kind": "ignored"}]
    ) == (
        ".cache",
        "add.py",
        "copy.py",
        "delete.py",
        "link",
        "new-name.py",
        "old-name.py",
    )
    assert boundary_manifest_hash(OID, staged) == boundary_manifest_hash(OID, list(staged))
    assert boundary_manifest_hash(OID, staged) != boundary_manifest_hash(OID, final[:-1])


def test_boundary_hash_binds_the_prepared_accepted_snapshot_tree() -> None:
    """A non-cache post-submit mutation cannot reuse an earlier manifest."""
    entries = [_entry("src/accepted.py", status="modified")]

    assert boundary_manifest_hash("a" * 40, entries) != boundary_manifest_hash("b" * 40, entries)
    assert boundary_manifest_hash("a" * 40, entries) != boundary_manifest_hash(
        "b" * 40, [_entry("src/accepted.py", status="modified", fingerprint="sha256:" + "c" * 64)]
    )


def test_manifest_rejects_duplicate_hash_conflicts_and_item_bounds() -> None:
    duplicate = [_entry("same.py"), _entry("same.py", fingerprint="sha256:" + "c" * 64)]
    with pytest.raises(BoundaryValidationError, match="sorted and unique"):
        boundary_manifest_hash(OID, duplicate)
    with pytest.raises(BoundaryValidationError, match="item limit"):
        boundary_manifest_hash(
            OID, [_entry(f"file-{index}") for index in range(MAX_BOUNDARY_MANIFEST_ITEMS + 1)]
        )


@pytest.mark.parametrize("field", ["node_id", "lease_id", "lease_generation"])
def test_finalization_duplicate_with_changed_identity_is_replay_conflict(field: str) -> None:
    projection = _staged_projection()
    finalization = _apply(
        projection,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_hash": HASH,
            "boundary_entries": [
                {
                    "path": "src/a.py",
                    "kind": "tracked",
                    "original_status": "clean",
                    "fingerprint": HASH,
                }
            ],
        },
    )
    after = reduce_event(projection, finalization[0])
    changed = dict(finalization[0].payload)
    changed[field] = "other" if field != "lease_generation" else 2
    duplicate = finalization[0].model_copy(update={"payload": changed})
    with pytest.raises(ProjectionReplayConflictError):
        reduce_event(after, duplicate)


def _pending_recovery_request() -> tuple[object, dict[str, object], object]:
    projection = _staged_projection()
    entries = [_entry("src/a.py", status="modified", fingerprint="sha256:" + "c" * 64)]
    payload: dict[str, object] = {
        "execution_id": "exec",
        "node_id": "node",
        "lease_id": "lease",
        "lease_generation": 1,
        "reason": "runner_died",
        "max_attempts": 3,
        "recovery_snapshot_id": "recovery",
        "recovery_snapshot_ref": "refs/orchestrator/snapshots/recovery",
        "recovery_commit_sha": OID,
        "final_tree_sha": OID,
        "boundary_hash": boundary_manifest_hash(OID, entries),
        "boundary_entries": entries,
    }
    requested = _apply(projection, "request_runner_recovery", payload)
    assert [event.event_type for event in requested] == ["runner_recovery_requested"]
    return reduce_event(projection, requested[0]), payload, requested[0]


def _changed_recovery_request_payload(
    payload: dict[str, object], field: str, *, for_replay: bool = False
) -> dict[str, object]:
    changed = deepcopy(payload)
    if field == "refs":
        changed["recovery_snapshot_id"] = "other-recovery"
        changed["recovery_snapshot_ref"] = "refs/orchestrator/snapshots/other-recovery"
    elif field == "commits":
        changed["recovery_commit_sha"] = "b" * 40
    elif field == "trees":
        changed["final_tree_sha"] = "b" * 40
        entries_key = (
            "final_boundary_entries" if "final_boundary_entries" in changed else "boundary_entries"
        )
        hash_key = "final_boundary_hash" if "final_boundary_hash" in changed else "boundary_hash"
        changed[hash_key] = boundary_manifest_hash(changed["final_tree_sha"], changed[entries_key])
    elif field == "manifests":
        changed_entries = [
            _entry("src/a.py", status="modified", fingerprint="sha256:" + "c" * 64),
            _entry("new.py", status="created", kind="untracked"),
        ]
        entries_key = (
            "final_boundary_entries" if "final_boundary_entries" in changed else "boundary_entries"
        )
        hash_key = "final_boundary_hash" if "final_boundary_hash" in changed else "boundary_hash"
        changed[entries_key] = changed_entries
        changed[hash_key] = boundary_manifest_hash(changed["final_tree_sha"], changed_entries)
    elif field == "reason":
        changed["reason"] = "cancelled"
    elif field == "paths":
        if for_replay:
            changed["paths"] = ["not-the-derived-path"]
        else:
            changed_entries = [
                _entry("src/a.py", status="modified", fingerprint="sha256:" + "c" * 64),
                _entry("new.py", status="created", kind="untracked"),
            ]
            changed["boundary_entries"] = changed_entries
            changed["boundary_hash"] = boundary_manifest_hash(
                changed["final_tree_sha"], changed_entries
            )
    elif field == "max_attempts":
        changed["max_attempts"] = 4
    else:
        raise AssertionError(field)
    return changed


@pytest.mark.parametrize(
    "field", ["refs", "commits", "trees", "manifests", "reason", "paths", "max_attempts"]
)
def test_recovery_request_command_duplicate_conflicts_for_every_identity_field(field: str) -> None:
    projection, payload, _ = _pending_recovery_request()

    assert _apply(projection, "request_runner_recovery", payload) == []
    changed = _changed_recovery_request_payload(payload, field)
    rejected = _apply(projection, "request_runner_recovery", changed)
    assert [event.event_type for event in rejected] == ["command_rejected"]
    assert rejected[0].payload["reason"] == "recovery request conflicts"


@pytest.mark.parametrize(
    "field", ["refs", "commits", "trees", "manifests", "reason", "paths", "max_attempts"]
)
def test_recovery_request_replay_conflicts_for_every_identity_field(field: str) -> None:
    projection, payload, requested = _pending_recovery_request()
    duplicate_payload = _changed_recovery_request_payload(
        dict(requested.payload), field, for_replay=True
    )
    duplicate = requested.model_copy(update={"payload": duplicate_payload})

    with pytest.raises(ProjectionReplayConflictError):
        reduce_event(projection, duplicate)


def test_managed_cleanup_is_a_codec_safe_final_invariant_blocker_until_exact_application() -> None:
    request = _event(
        "cleanup_requested",
        {
            "cleanup_id": "runner-snapshot:exec:final",
            "snapshot_id": "final",
            "snapshot_ref": "refs/orchestrator/snapshots/final",
            "tree_sha": OID,
            "commit_sha": OID,
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "snapshot_role": "final",
            "execution_id": "exec",
            "reason": "managed_runner_boundary_no_longer_needed",
        },
        1,
    )
    projection = reduce_event(initial_projection(), request)
    blockers = project_final_invariant_blockers([request], projection=projection)
    assert [item["kind"] for item in blockers] == ["pending_managed_snapshot_cleanup"]

    restored = projection_from_checkpoint(deepcopy(projection_to_checkpoint(projection)))
    assert project_final_invariant_blockers([request], projection=restored) == blockers

    wrong = request.model_copy(
        update={
            "event_id": "wrong-application",
            "position": 2,
            "event_type": "cleanup_applied",
            "payload": {
                "cleanup_id": "runner-snapshot:exec:final",
                "old_snapshot_id": "other",
                "snapshot_ref": "refs/orchestrator/snapshots/other",
                "tree_sha": OID,
                "commit_sha": OID,
                "node_id": "node",
                "lease_id": "lease",
                "lease_generation": 1,
                "snapshot_role": "final",
                "execution_id": "exec",
            },
        }
    )
    with pytest.raises(ProjectionReplayConflictError):
        reduce_event(restored, wrong)
    still_blocked = restored
    assert project_final_invariant_blockers([request], projection=still_blocked)

    applied = request.model_copy(
        update={
            "event_id": "exact-application",
            "position": 3,
            "event_type": "cleanup_applied",
            "payload": {
                "cleanup_id": "runner-snapshot:exec:final",
                "old_snapshot_id": "final",
                "snapshot_ref": "refs/orchestrator/snapshots/final",
                "tree_sha": OID,
                "commit_sha": OID,
                "node_id": "node",
                "lease_id": "lease",
                "lease_generation": 1,
                "snapshot_role": "final",
                "execution_id": "exec",
            },
        }
    )
    cleared = reduce_event(still_blocked, applied)
    assert not project_final_invariant_blockers([request, applied], projection=cleared)
