"""Direct pure-command coverage for the runner execution boundary kernel."""

import pytest
from copy import deepcopy

from orchestrator.graph import (
    node_states_view,
    non_gap_planner_completion_contract_satisfied,
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
    execution_attempts_view,
    initial_projection,
    map_set,
    ProjectionReplayConflictError,
    recovery_proof_hash,
    reduce_event,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_final_invariant_blockers,
    reliable_plan_successor_horizon_materialized,
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
    node_overrides: dict[str, object] | None = None,
    explicit_legacy_authority: bool = False,
):
    projection = initial_projection()
    node_payload = {"node_id": "node", "kind": kind, "state": "running"}
    if role is not None:
        node_payload["role"] = role
    if attempt_number is not None:
        node_payload["attempt_number"] = attempt_number
    if max_attempts is not None:
        node_payload["max_attempts"] = max_attempts
    if node_overrides is not None:
        node_payload.update(node_overrides)
    if explicit_legacy_authority:
        node_payload.update(
            {
                "kind": "planner",
                "role": "planner",
                "inputs": [
                    {
                        "port": "routine_snapshot",
                        "direction": "input",
                        "schema": "RoutineSnapshot",
                        "required": True,
                    }
                ],
                "outputs": [
                    {
                        "port": "graph_patch",
                        "direction": "output",
                        "schema": "GraphPatch",
                        "record_layers": ["graph_record"],
                    }
                ],
            }
        )
        snapshot_value = {
            "routine_id": "legacy-routine",
            "name": "Legacy routine",
            "content_hash": "c" * 64,
            "step_count": 1,
            "task_count": 1,
            "agent_interaction_contract": None,
        }
        events = [
            _event(
                "node_created",
                {
                    "node_id": "routine-snapshot",
                    "kind": "artifact",
                    "role": "routine_snapshot",
                    "state": "completed",
                    "outputs": [
                        {
                            "port": "snapshot",
                            "direction": "output",
                            "schema": "RoutineSnapshot",
                            "record_layers": ["graph_record"],
                        }
                    ],
                },
                1,
            ),
            _event(
                "output_record_accepted",
                {
                    "record_type": "routine_snapshot",
                    "record_id": "legacy-routine-snapshot",
                    "record_kind": "graph_record",
                    "producer_node_id": "routine-snapshot",
                    "port": "snapshot",
                    "schema": "RoutineSnapshot",
                    "value": snapshot_value,
                },
                2,
            ),
            _event("node_created", node_payload, 3),
            _event(
                "edge_created",
                {
                    "edge_id": "legacy-routine-to-node",
                    "from_node_id": "routine-snapshot",
                    "from_port": "snapshot",
                    "to_node_id": "node",
                    "to_port": "routine_snapshot",
                    "required": True,
                    "purpose": "routine_snapshot",
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_type": "routine_snapshot",
                        "schema": "RoutineSnapshot",
                    },
                },
                4,
            ),
            _event(
                "input_bound",
                {
                    "edge_id": "legacy-routine-to-node",
                    "to_node_id": "node",
                    "to_port": "routine_snapshot",
                    "record_ids": ["legacy-routine-snapshot"],
                    "bound_at_position": 0,
                    "record_bound_positions": {"legacy-routine-snapshot": -1},
                },
                5,
            ),
        ]
        lease_position = 6
    else:
        events = [_event("node_created", node_payload, 1)]
        lease_position = 2
    events.append(
        _event(
            "lease_granted",
            {
                "lease_id": "lease",
                "node_id": "node",
                "generation": 1,
                "execution_id": "exec",
                "base_snapshot_id": "snap",
            },
            lease_position,
        )
    )
    for event in events:
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
        command
        in {
            "stage_runner_submission",
            "witness_runner_completion",
            "finalize_runner_execution",
        }
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
    if command == "finalize_runner_execution":
        attempt = execution_attempts_view(projection).get(str(payload.get("execution_id", "")))
        if attempt is not None and attempt.state == "submission_staged":
            witness_payload = {
                **payload,
                "staged_payload_hash": attempt.payload_hash,
                "staged_payload_size_bytes": attempt.payload_size_bytes,
                "staged_snapshot_id": attempt.staged_snapshot_id,
                "staged_snapshot_ref": attempt.staged_snapshot_ref,
                "staged_commit_sha": attempt.staged_commit_sha,
                "staged_tree_sha": attempt.staged_tree_sha,
                "staged_boundary_hash": attempt.staged_boundary_hash,
                "runner_return_kind": "successful_return",
            }
            witnessed = _apply_raw(projection, "witness_runner_completion", witness_payload)
            if any(event.event_type == "runner_boundary_mismatch" for event in witnessed):
                # Older assertions focus on the mismatch/recovery pair. The
                # new witness itself is covered explicitly below.
                return witnessed[1:]
            if not witnessed or witnessed[0].event_type != "runner_completion_witnessed":
                return witnessed
            projection = reduce_event(projection, witnessed[0])
    return _apply_raw(projection, command, payload)


def _apply_raw(projection, command: str, payload: dict[str, object]):
    return apply_command(
        projection,
        [],
        command,
        payload,
        GraphCommandContext(run_id="run", current_graph_position=2),
        FakeClock(),
        SequentialIdGenerator(),
    )


def _witness_payload(projection, **final_overrides: object) -> dict[str, object]:
    attempt = execution_attempts_view(projection)["exec"]
    payload: dict[str, object] = {
        "execution_id": "exec",
        "node_id": "node",
        "lease_id": "lease",
        "lease_generation": 1,
        "staged_payload_hash": attempt.payload_hash,
        "staged_payload_size_bytes": attempt.payload_size_bytes,
        "staged_snapshot_id": attempt.staged_snapshot_id,
        "staged_snapshot_ref": attempt.staged_snapshot_ref,
        "staged_commit_sha": attempt.staged_commit_sha,
        "staged_tree_sha": attempt.staged_tree_sha,
        "staged_boundary_hash": attempt.staged_boundary_hash,
        "runner_return_kind": "successful_return",
        "final_snapshot_id": "final",
        "final_snapshot_ref": "refs/orchestrator/snapshots/final",
        "final_commit_sha": OID,
        "final_tree_sha": OID,
        "boundary_entries": [
            entry.model_dump(mode="json") for entry in attempt.staged_boundary_entries
        ],
    }
    payload.update(final_overrides)
    return payload


def test_completion_witness_is_required_idempotent_and_replayable() -> None:
    staged = _staged_projection()
    final_payload = _witness_payload(staged)
    for key in tuple(final_payload):
        if key.startswith("staged_") or key == "runner_return_kind":
            final_payload.pop(key)
    final_payload["boundary_hash"] = boundary_manifest_hash(
        final_payload["final_tree_sha"], final_payload["boundary_entries"]
    )
    rejected = _apply_raw(staged, "finalize_runner_execution", final_payload)
    assert rejected[0].event_type == "command_rejected"
    assert "not durably witnessed" in str(rejected[0].payload["reason"])

    witness_payload = _witness_payload(staged)
    witnessed_events = _apply(staged, "witness_runner_completion", witness_payload)
    assert [event.event_type for event in witnessed_events] == ["runner_completion_witnessed"]
    witnessed = reduce_event(staged, witnessed_events[0])
    attempt = execution_attempts_view(witnessed)["exec"]
    assert attempt.state == "completion_witnessed"
    assert attempt.completion_disposition == "completion_witnessed"
    assert _apply(witnessed, "witness_runner_completion", witness_payload) == []

    finalized_events = _apply(witnessed, "finalize_runner_execution", final_payload)
    assert finalized_events[0].event_type == "runner_execution_finalized"
    finalized = witnessed
    for event in finalized_events:
        finalized = reduce_event(finalized, event)
    attempt = execution_attempts_view(finalized)["exec"]
    assert attempt.state == "finalized"
    assert attempt.completion_disposition == "finalized_accepted"


def test_post_submit_mutation_is_witnessed_then_restored_not_finalized() -> None:
    staged = _staged_projection()
    mutated_entry = _entry("src/a.py", status="modified", fingerprint="sha256:" + "c" * 64)
    witness_payload = _witness_payload(staged, boundary_entries=[mutated_entry])
    events = _apply(
        staged,
        "witness_runner_completion",
        witness_payload,
    )
    assert [event.event_type for event in events] == [
        "runner_completion_witnessed",
        "runner_boundary_mismatch",
        "runner_recovery_requested",
    ]
    after = staged
    for event in events:
        after = reduce_event(after, event)
    attempt = execution_attempts_view(after)["exec"]
    assert attempt.state == "recovery_requested"
    assert attempt.runner_return_kind == "successful_return"
    # Recovery is requested but not yet proven complete, so the last durable
    # completion fact remains the witness rather than claiming restoration.
    assert attempt.completion_disposition == "completion_witnessed"
    assert _apply(after, "witness_runner_completion", witness_payload) == []
    assert not any(event.event_type == "runner_execution_finalized" for event in events)


def _staged_projection(
    *,
    kind: str = "worker",
    role: str | None = None,
    attempt_number: int | None = None,
    max_attempts: int | None = None,
    node_overrides: dict[str, object] | None = None,
    explicit_legacy_authority: bool = False,
):
    projection = _projection(
        kind=kind,
        role=role,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        node_overrides=node_overrides,
        explicit_legacy_authority=explicit_legacy_authority,
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
        not {
            "cache_roots",
            "observed_cache_roots",
            "authorized_cache_roots",
            "legacy_cache_root_paths",
        }
        & event.payload.keys()
        for event in events
    )
    recovered = reduce_event(reduce_event(projection, events[0]), events[1])
    assert projection_from_checkpoint(projection_to_checkpoint(recovered)) == recovered


@pytest.mark.parametrize("phase", ["baseline", "stage", "final", "recovery"])
def test_cache_authority_phase_matrix_retains_each_root_in_its_durable_slot(phase: str) -> None:
    """The four legacy integration variants are pure reducer cases, not DB cases."""
    projection = _projection()
    baseline_roots = [_cache_root(".pytest_cache", "ignored")] if phase == "baseline" else []
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
            "cache_roots": baseline_roots,
            "cache_status_evidence": [
                _cache_root(".pytest_cache/entry", "ignored")
            ]
            if baseline_roots
            else [],
        },
    )
    projection = reduce_event(projection, baseline[0])
    staged_roots = [_cache_root(".pytest_cache", "ignored")] if phase == "stage" else []
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
            "cache_roots": staged_roots,
            "cache_status_evidence": (
                [_cache_root(".pytest_cache/entry", "ignored")] if staged_roots else []
            ),
        },
    )
    projection = reduce_event(projection, staged[0])
    if phase == "final":
        final_events = _apply(
            projection,
            "witness_runner_completion",
            _witness_payload(
                projection,
                cache_roots=[_cache_root(".pytest_cache", "ignored")],
                cache_status_evidence=[_cache_root(".pytest_cache/entry", "ignored")],
            ),
        )
        for event in final_events:
            projection = reduce_event(projection, event)
    elif phase == "recovery":
        entries = [_entry("changed.py", kind="untracked", status="created")]
        recovery_events = _apply(
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
                "boundary_hash": boundary_manifest_hash(
                    OID, entries, [_cache_root(".pytest_cache/entry", "ignored")]
                ),
                "boundary_entries": entries,
                    "observed_cache_roots": [_cache_root(".pytest_cache", "ignored")],
                    "cache_status_evidence": [_cache_root(".pytest_cache/entry", "ignored")],
            },
        )
        for event in recovery_events:
            projection = reduce_event(projection, event)

    attempt = execution_attempts_view(projection)["exec"]

    def root_set(field: str) -> set[tuple[str, str]]:
        return {(root.path, root.kind) for root in getattr(attempt, field)}

    assert root_set("baseline_cache_roots") == (
        {(".pytest_cache", "ignored")} if phase == "baseline" else set()
    )
    assert root_set("staged_cache_roots") == (
        {(".pytest_cache", "ignored")} if phase == "stage" else set()
    )
    assert root_set("final_cache_roots") == (
        {(".pytest_cache", "ignored")} if phase == "final" else set()
    )
    assert root_set("recovery_observed_cache_roots") == (
        {(".pytest_cache", "ignored")} if phase == "recovery" else (
            {(".pytest_cache", "ignored")} if phase == "final" else set()
        )
    )


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


def test_recovery_authority_collapses_identical_roots_retained_in_phase_history() -> None:
    projection = _staged_cache_transition("ignored", "ignored")
    attempt = projection.execution.attempts_by_execution_id["exec"].model_copy(
        update={
            "baseline_cache_roots": (
                _cache_root(".pytest_cache", "ignored"),
                _cache_root(".pytest_cache", "ignored"),
            )
        }
    )
    execution = projection.execution.model_copy(
        update={
            "attempts_by_execution_id": map_set(
                projection.execution.attempts_by_execution_id, "exec", attempt
            )
        }
    )
    checkpoint = projection_to_checkpoint(projection.model_copy(update={"execution": execution}))
    replayed = projection_from_checkpoint(checkpoint)

    events = _apply(
        replayed,
        "finalize_runner_execution",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "final_snapshot_id": "final",
            "final_tree_sha": OID,
            "boundary_entries": [_entry("changed.py", kind="untracked", status="created")],
            "cache_roots": [_cache_root(".pytest_cache", "ignored")],
            "cache_status_evidence": [_cache_root(".pytest_cache/entry", "ignored")],
        },
    )

    assert [event.event_type for event in events] == [
        "runner_boundary_mismatch",
        "runner_recovery_requested",
    ]
    assert all(
        not {
            "cache_roots",
            "observed_cache_roots",
            "authorized_cache_roots",
            "legacy_cache_root_paths",
        }
        & event.payload.keys()
        for event in events
    )


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
    assert node_states_view(projection).get("node") == "ready"
    assert execution_attempts_view(projection)["exec"].retry_scheduled is True


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
        "reason": "boundary_mismatch",
        "attempt_number": 3,
        "max_attempts": 3,
    }
    assert not any(event.event_type == "runtime_retry_scheduled" for event in completion_events)
    assert node_states_view(projection).get("node") == "failed"


def test_submission_repair_exhaustion_restores_then_fails_without_retry() -> None:
    projection = _staged_projection(attempt_number=1)
    detail = (
        "submission repair exhausted after 3 attempts; first_cause=missing output; "
        "last_cause=invalid value; operator_action=repair contract before explicit retry"
    )
    requested = _apply(
        projection,
        "request_runner_recovery",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "reason": "submission_repair_exhausted",
            "error_detail": detail,
            "final_tree_sha": OID,
            "boundary_hash": boundary_manifest_hash(OID, []),
            "boundary_entries": [],
        },
    )
    assert [event.event_type for event in requested] == ["runner_recovery_requested"]
    projection = reduce_event(projection, requested[0])
    request = requested[0].payload
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=request["recovery_id"],
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id=request["baseline_snapshot_id"],
        baseline_tree_sha=request["baseline_tree_sha"],
        requested_paths=tuple(request["paths"]),
        restored_paths=tuple(request["paths"]),
        removed_paths=(),
    )

    completed = _apply(
        projection,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": request["recovery_id"],
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": request["baseline_snapshot_id"],
            "baseline_tree_sha": request["baseline_tree_sha"],
            "requested_paths": request["paths"],
            "proof_hash": proof,
            "restored_paths": request["paths"],
            "removed_paths": [],
        },
    )

    assert not any(event.event_type == "runtime_retry_scheduled" for event in completed)
    failure = next(
        event
        for event in completed
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "failure_record"
    )
    assert failure.payload["value"]["error_class"] == "submission_repair_exhausted"
    assert failure.payload["value"]["reason"] == detail
    terminal = next(event for event in completed if event.event_type == "node_state_changed")
    assert terminal.payload["new_state"] == "failed"
    assert terminal.payload["trigger"] == "submission_repair_exhausted"


@pytest.mark.parametrize(
    ("attempt_number", "expected_state", "expected_trigger"),
    [
        (1, "ready", "runner_recovery_completed_retry_scheduled"),
        (2, "failed", "invalid_planner_execution_limit_exhausted"),
    ],
)
def test_invalid_planner_proposal_recovery_obeys_persisted_execution_limit(
    attempt_number: int,
    expected_state: str,
    expected_trigger: str,
) -> None:
    projection = _staged_projection(
        attempt_number=attempt_number,
        max_attempts=2,
        explicit_legacy_authority=True,
    )
    requested = _apply(
        projection,
        "request_runner_recovery",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "reason": "invalid_planner_proposal",
            "error_detail": "invalid_planner_proposal",
            "max_attempts": 2,
            "retry_after_recovery": True,
            "recovery_snapshot_id": "rejected-candidate",
            "recovery_snapshot_ref": "refs/orchestrator/snapshots/rejected-candidate",
            "recovery_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_hash": boundary_manifest_hash(OID, []),
            "boundary_entries": [],
        },
    )
    projection = reduce_event(projection, requested[0])
    request = requested[0].payload
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=request["recovery_id"],
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id=request["baseline_snapshot_id"],
        baseline_tree_sha=request["baseline_tree_sha"],
        requested_paths=tuple(request["paths"]),
        restored_paths=tuple(request["paths"]),
        removed_paths=(),
    )
    completed = _apply(
        projection,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": request["recovery_id"],
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": request["baseline_snapshot_id"],
            "baseline_tree_sha": request["baseline_tree_sha"],
            "requested_paths": request["paths"],
            "proof_hash": proof,
            "restored_paths": request["paths"],
            "removed_paths": [],
        },
    )

    terminal = next(event for event in completed if event.event_type == "node_state_changed")
    assert terminal.payload["new_state"] == expected_state
    assert terminal.payload["trigger"] == expected_trigger
    if expected_state == "ready":
        assert any(event.event_type == "runtime_retry_scheduled" for event in completed)
        assert not any(event.event_type == "output_record_accepted" for event in completed)
    else:
        assert not any(event.event_type == "runtime_retry_scheduled" for event in completed)
        failure = next(event for event in completed if event.event_type == "output_record_accepted")
        assert failure.payload["value"]["failure_class"] == "invalid_plan_failure"
        assert failure.payload["value"]["error_class"] == "invalid_planner_proposal"


def test_proposal_rejection_limit_restores_then_fails_without_retry() -> None:
    projection = _staged_projection(attempt_number=1, max_attempts=3)
    requested = _apply(
        projection,
        "request_runner_recovery",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "reason": "invalid_planner_proposal",
            "error_detail": "proposal_rejection_limit_exhausted",
            "max_attempts": 3,
            "retry_after_recovery": False,
            "final_tree_sha": OID,
            "boundary_hash": boundary_manifest_hash(OID, []),
            "boundary_entries": [],
        },
    )
    projection = reduce_event(projection, requested[0])
    request = requested[0].payload
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=request["recovery_id"],
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id=request["baseline_snapshot_id"],
        baseline_tree_sha=request["baseline_tree_sha"],
        requested_paths=tuple(request["paths"]),
        restored_paths=tuple(request["paths"]),
        removed_paths=(),
    )
    completed = _apply(
        projection,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": request["recovery_id"],
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": request["baseline_snapshot_id"],
            "baseline_tree_sha": request["baseline_tree_sha"],
            "requested_paths": request["paths"],
            "proof_hash": proof,
            "restored_paths": request["paths"],
            "removed_paths": [],
        },
    )
    assert not any(event.event_type == "runtime_retry_scheduled" for event in completed)
    failure = next(event for event in completed if event.event_type == "output_record_accepted")
    assert failure.payload["value"]["error_class"] == "invalid_planner_proposal"
    terminal = next(event for event in completed if event.event_type == "node_state_changed")
    assert terminal.payload["new_state"] == "failed"
    assert terminal.payload["trigger"] == "invalid_planner_proposal"


def test_validation_environment_blockage_releases_lease_without_retry() -> None:
    projection = _staged_projection(attempt_number=1)
    requested = _apply(
        projection,
        "request_runner_recovery",
        {
            "execution_id": "exec",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "reason": "validation_environment_blocked",
            "error_detail": "test tool cannot create its runtime directory",
            "recovery_snapshot_id": "rejected-exec",
            "recovery_snapshot_ref": "refs/orchestrator/snapshots/rejected-exec",
            "recovery_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_hash": boundary_manifest_hash(OID, []),
            "boundary_entries": [],
        },
    )
    projection = reduce_event(projection, requested[0])
    request = requested[0].payload
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=request["recovery_id"],
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id=request["baseline_snapshot_id"],
        baseline_tree_sha=request["baseline_tree_sha"],
        requested_paths=tuple(request["paths"]),
        restored_paths=tuple(request["paths"]),
        removed_paths=(),
    )

    completed = _apply(
        projection,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": request["recovery_id"],
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": request["baseline_snapshot_id"],
            "baseline_tree_sha": request["baseline_tree_sha"],
            "requested_paths": request["paths"],
            "proof_hash": proof,
            "restored_paths": request["paths"],
            "removed_paths": [],
        },
    )

    assert any(event.event_type == "lease_revoked" for event in completed)
    assert not any(event.event_type == "runtime_retry_scheduled" for event in completed)
    failure = next(event for event in completed if event.event_type == "output_record_accepted")
    assert failure.payload["value"] == {
        "failed_node_id": "node",
        "phase": "submission",
        "failure_class": "infrastructure_failure",
        "error_class": "validation_environment_blocked",
        "retryable": False,
        "lease_id": "lease",
        "execution_id": "exec",
        "lease_generation": 1,
        "reason": "test tool cannot create its runtime directory",
        "rejected_candidate_snapshot_id": "rejected-exec",
        "rejected_candidate_snapshot_ref": "refs/orchestrator/snapshots/rejected-exec",
    }
    terminal = next(event for event in completed if event.event_type == "node_state_changed")
    assert terminal.payload["new_state"] == "failed"
    assert terminal.payload["trigger"] == "validation_environment_blocked"
    assert not any(
        event.event_type == "cleanup_requested" and event.payload.get("snapshot_role") == "recovery"
        for event in completed
    )
    for event in completed:
        projection = reduce_event(projection, event)
    resolution = apply_command(
        projection,
        [],
        "resolve_validation_environment_blockage",
        {
            "expected_graph_position": 99,
            "node_id": "node",
            "execution_id": "exec",
            "recovery_id": request["recovery_id"],
            "snapshot_selection": "rejected_candidate",
        },
        GraphCommandContext(
            run_id="run",
            current_graph_position=99,
            actor=Actor(kind=ActorKind.HUMAN, id="operator", role="operator"),
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert [event.event_type for event in resolution] == [
        "validation_environment_blockage_resolution_requested"
    ]
    projection = reduce_event(projection, resolution[0])
    resolution_payload = resolution[0].payload
    completed_resolution = _apply_raw(
        projection,
        "complete_validation_environment_blockage_resolution",
        {
            key: resolution_payload[key]
            for key in (
                "resolution_id",
                "node_id",
                "execution_id",
                "recovery_id",
                "snapshot_selection",
                "snapshot_id",
                "snapshot_ref",
                "commit_sha",
                "tree_sha",
            )
        },
    )
    assert [event.event_type for event in completed_resolution] == [
        "validation_environment_blockage_resolved",
        "node_authority_changed",
        "node_state_changed",
    ]
    for event in completed_resolution:
        projection = reduce_event(projection, event)
    attempt = execution_attempts_view(projection)["exec"]
    assert attempt.continuation_resolution_status == "completed"
    assert node_states_view(projection)["node"] == "ready"


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


def test_runner_recovery_retries_final_horizon_planner_missing_finalization() -> None:
    projection = _staged_projection(
        kind="planner",
        role="planner",
        node_overrides={
            "semantic_stage": "successor_planning",
            "planning_horizon": 2,
            "reliable_plan_remaining_horizons": 1,
            "reliable_plan_skeleton_id": "skeleton-1",
        },
    )
    for event in (
        _event(
            "graph_patch_accepted",
            {"patch_id": "batch-2", "proposed_by_node_id": "node"},
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-batch-2",
                "kind": "worker",
                "state": "planned",
                "semantic_stage": "effectful_batch",
                "planning_horizon": 2,
                "reliable_plan_skeleton_id": "skeleton-1",
                "patch_id": "batch-2",
            },
            4,
        ),
    ):
        projection = reduce_event(projection, event)
    assert not non_gap_planner_completion_contract_satisfied(projection, "node")
    assert reliable_plan_successor_horizon_materialized(projection, "node")
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
    projection = reduce_event(projection, requested[0])
    recovery_id = requested[0].payload["recovery_id"]
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
            "proof_hash": recovery_proof_hash(
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
            ),
            "restored_paths": ["src/a.py"],
            "removed_paths": [],
        },
    )

    assert [event.event_type for event in completed[:4]] == [
        "runner_recovery_completed",
        "lease_revoked",
        "runtime_retry_scheduled",
        "node_state_changed",
    ]
    assert completed[3].payload["new_state"] == "ready"
    assert completed[3].payload["trigger"] == "runner_recovery_completed_retry_scheduled"

    complete_projection = projection
    for position, payload in enumerate(
        (
            {
                "node_id": "final-audit",
                "kind": "verifier",
                "semantic_stage": "final_audit",
                "patch_id": "finalization",
                "state": "planned",
            },
            {
                "node_id": "final-gate",
                "kind": "final_gate",
                "patch_id": "finalization",
                "state": "planned",
            },
        ),
        start=5,
    ):
        complete_projection = reduce_event(
            complete_projection, _event("node_created", payload, position)
        )
    complete_projection = reduce_event(
        complete_projection,
        _event(
            "graph_patch_accepted",
            {"patch_id": "finalization", "proposed_by_node_id": "node"},
            7,
        ),
    )
    # A batch and finalization accepted in separate patches do not satisfy the
    # atomic final-horizon contract, so recovery must still retry the planner.
    assert not non_gap_planner_completion_contract_satisfied(complete_projection, "node")


def test_successor_discovery_patch_does_not_materialize_effectful_horizon() -> None:
    projection = _staged_projection(
        kind="planner",
        role="planner",
        node_overrides={
            "semantic_stage": "successor_planning",
            "planning_horizon": 2,
            "reliable_plan_remaining_horizons": 1,
            "reliable_plan_skeleton_id": "skeleton-1",
        },
    )
    for event in (
        _event(
            "graph_patch_accepted",
            {"patch_id": "discovery", "proposed_by_node_id": "node"},
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-discovery",
                "kind": "worker",
                "semantic_stage": "discovery",
                "planning_horizon": 2,
                "reliable_plan_skeleton_id": "skeleton-1",
                "patch_id": "discovery",
                "state": "planned",
            },
            4,
        ),
    ):
        projection = reduce_event(projection, event)

    assert not reliable_plan_successor_horizon_materialized(projection, "node")
    assert not non_gap_planner_completion_contract_satisfied(projection, "node")


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
    ] == ["baseline", "final"]
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
    elif field == "error_detail":
        changed["error_detail"] = "different managed runner failure"
    else:
        raise AssertionError(field)
    return changed


@pytest.mark.parametrize(
    "field",
    [
        "refs",
        "commits",
        "trees",
        "manifests",
        "reason",
        "paths",
        "max_attempts",
        "error_detail",
    ],
)
def test_recovery_request_command_duplicate_conflicts_for_every_identity_field(field: str) -> None:
    projection, payload, _ = _pending_recovery_request()

    assert _apply(projection, "request_runner_recovery", payload) == []
    changed = _changed_recovery_request_payload(payload, field)
    rejected = _apply(projection, "request_runner_recovery", changed)
    assert [event.event_type for event in rejected] == ["command_rejected"]
    assert rejected[0].payload["reason"] == "recovery request conflicts"


@pytest.mark.parametrize(
    "field",
    [
        "refs",
        "commits",
        "trees",
        "manifests",
        "reason",
        "paths",
        "max_attempts",
        "error_detail",
    ],
)
def test_recovery_request_replay_conflicts_for_every_identity_field(field: str) -> None:
    projection, payload, requested = _pending_recovery_request()
    duplicate_payload = _changed_recovery_request_payload(
        dict(requested.payload), field, for_replay=True
    )
    duplicate = requested.model_copy(update={"payload": duplicate_payload})

    with pytest.raises(ProjectionReplayConflictError):
        reduce_event(projection, duplicate)


def test_recovery_error_detail_is_canonical_bounded_and_checkpointed() -> None:
    projection = _staged_projection(attempt_number=3, max_attempts=3)
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
            "error_detail": "\x00exact transport failure\n" + "x" * 5_000,
            "max_attempts": 3,
            "recovery_snapshot_id": "recovery",
            "recovery_snapshot_ref": "refs/orchestrator/snapshots/recovery",
            "recovery_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_hash": boundary_manifest_hash(OID, entries),
            "boundary_entries": entries,
        },
    )

    detail = requested[0].payload["error_detail"]
    assert isinstance(detail, str)
    assert detail.startswith("�exact transport failure\n")
    assert len(detail) == 4_096
    reconstructed = projection_from_checkpoint(
        projection_to_checkpoint(reduce_event(projection, requested[0]))
    )
    assert execution_attempts_view(reconstructed)["exec"].recovery_error_detail == detail
    request_payload = requested[0].payload
    requested_paths = tuple(request_payload["paths"])
    proof = recovery_proof_hash(
        execution_id="exec",
        recovery_id=request_payload["recovery_id"],
        node_id="node",
        lease_id="lease",
        lease_generation=1,
        baseline_snapshot_id=request_payload["baseline_snapshot_id"],
        baseline_tree_sha=request_payload["baseline_tree_sha"],
        requested_paths=requested_paths,
        restored_paths=requested_paths,
        removed_paths=(),
    )
    completed = _apply(
        reconstructed,
        "complete_runner_recovery",
        {
            "execution_id": "exec",
            "recovery_id": request_payload["recovery_id"],
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": request_payload["baseline_snapshot_id"],
            "baseline_tree_sha": request_payload["baseline_tree_sha"],
            "requested_paths": list(requested_paths),
            "proof_hash": proof,
            "restored_paths": list(requested_paths),
            "removed_paths": [],
        },
    )
    failure = next(
        event
        for event in completed
        if event.event_type == "node_state_changed" and event.payload.get("new_state") == "failed"
    )
    assert failure.payload["trigger"] == "max_attempts_exhausted"
    assert failure.payload["reason"] == detail


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
