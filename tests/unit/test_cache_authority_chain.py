"""End-to-end cache-authority facts across compile, projection, and runtime."""

from __future__ import annotations

import copy
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    CacheAuthorityPolicy,
    EventEnvelope,
    FakeClock,
    GraphCommandContext,
    PatchCommandContext,
    SequentialIdGenerator,
    apply_command,
    build_projection,
    cache_authority_binding,
    cache_authority_hash,
    canonicalize_cache_authority,
    compile_routine,
    file_state_policy_from_authority,
    initial_projection,
    lease_by_id,
    leases_view,
    node_cache_authority_hash,
    node_states_view,
    ProjectionCheckpointIntegrityError,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_pattern_library,
    reduce_event,
    validate_projection_integrity,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxItem,
    OutboxDispatcher,
    policy_with_pattern_library,
    seed_run,
)
from orchestrator.runners import AgentRunner, ExecutionResult


def _routine(
    policy: dict[str, Any] | None = None, *, routine_id: str = "authority"
) -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": routine_id,
            "name": "Authority",
            "file_state_policy": policy,
            "steps": [{"id": "s", "title": "S", "tasks": [{"id": "t", "title": "T"}]}],
        }
    )


def _compiled(
    policy: dict[str, Any] | None = None,
    *,
    routine_id: str = "authority",
) -> list[EventEnvelope]:
    return compile_routine(
        _routine(policy, routine_id=routine_id),
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-authority",
    )


def _runtime_routine() -> RoutineConfig:
    return _routine(
        {
            "declarations": [
                {
                    "pattern": "custom-cache/**",
                    "classification": "tool_cache",
                    "source_kinds": ["ignored"],
                }
            ]
        },
        routine_id="runtime-authority",
    )


def _event(
    event_type: str,
    payload: dict[str, Any],
    *,
    position: int,
    run_id: str = "run-authority",
) -> EventEnvelope:
    canonical = dict(payload)
    if event_type == "run_lifecycle_changed":
        canonical.setdefault("command_type", "fixture_transition")
        canonical.setdefault("from_state", "queued")
        canonical.setdefault("trigger", "fixture_transition")
    return EventEnvelope(
        event_id=f"authority-event-{position}",
        run_id=run_id,
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical,
    )


def _snapshot_projection(*, strip_carriers: bool = False, **updates: object) -> tuple[Any, str]:
    events = _compiled()
    snapshot_event = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    snapshot_payload = copy.deepcopy(snapshot_event.payload)
    snapshot_value = snapshot_payload["value"]
    assert isinstance(snapshot_value, dict)
    snapshot_value.update(updates)
    events[events.index(snapshot_event)] = snapshot_event.model_copy(
        update={"payload": snapshot_payload}
    )
    if strip_carriers:
        for index, event in enumerate(events):
            if event.event_type not in {"node_created", "lease_granted"}:
                continue
            payload = copy.deepcopy(event.payload)
            payload.pop("cache_authority_hash", None)
            events[index] = event.model_copy(update={"payload": payload})
    return build_projection(events), str(snapshot_value["cache_authority_hash"])


@pytest.mark.parametrize(
    ("version", "preimage", "digest"),
    [
        (None, None, None),
        ("cache-authority-v1", None, None),
        (None, "present", None),
        (None, None, "present"),
        ("cache-authority-v1", "present", None),
        ("cache-authority-v1", None, "present"),
        (None, "present", "present"),
        ("cache-authority-v1", "present", "present"),
    ],
)
def test_authority_binding_handles_every_metadata_presence_state(
    version: str | None,
    preimage: str | None,
    digest: str | None,
) -> None:
    policy = CacheAuthorityPolicy()
    fields: dict[str, object] = {
        "cache_authority_version": version,
        "cache_authority_preimage": (
            canonicalize_cache_authority(policy) if preimage == "present" else preimage
        ),
        "cache_authority_hash": cache_authority_hash(policy) if digest == "present" else digest,
    }
    projection, _ = _snapshot_projection(
        strip_carriers=(version, preimage, digest) == (None, None, None),
        **fields,
    )
    if (version, preimage, digest) in {
        (None, None, None),
        ("cache-authority-v1", "present", "present"),
    }:
        assert cache_authority_binding(projection).policy == policy
    else:
        with pytest.raises(ValueError, match="cache authority"):
            cache_authority_binding(projection)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"cache_authority_preimage": "{"}, "invalid cache authority preimage"),
        ({"cache_authority_hash": "0" * 64}, "hash verification failed"),
        ({"cache_authority_hash": "not-a-digest"}, "hash verification failed"),
        ({"cache_authority_version": "cache-authority-v2"}, "unknown"),
    ],
)
def test_authority_binding_rejects_malformed_preimage_digest_and_version(
    updates: dict[str, object], message: str
) -> None:
    projection, _ = _snapshot_projection(**updates)
    with pytest.raises(ValueError, match=message):
        cache_authority_binding(projection)


def test_authority_binding_rejects_wrong_reserved_record() -> None:
    events = _compiled()
    snapshot = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    payload = copy.deepcopy(snapshot.payload)
    payload.update(
        {
            "record_type": "candidate",
            "record_kind": "output",
            "schema": "ImplementationCandidate",
            "producer_node_id": "worker-s-t",
            "port": "candidate",
            "candidate_id": "candidate-reserved",
            "value": {"summary": "wrong reserved record"},
        }
    )
    events[events.index(snapshot)] = snapshot.model_copy(update={"payload": payload})
    projection = build_projection(events)
    with pytest.raises(ValueError, match="routine-snapshot-record"):
        cache_authority_binding(projection)


def test_authority_binding_requires_snapshot_when_an_authority_node_exists() -> None:
    projection = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "state": "planned",
                    "cache_authority_hash": "0" * 64,
                },
                position=0,
            )
        ]
    )
    with pytest.raises(ValueError, match="canonical routine-snapshot-record"):
        cache_authority_binding(projection)


def test_authority_binding_and_integrity_require_snapshot_for_authority_lease() -> None:
    projection = build_projection(
        [
            _event(
                "node_created",
                {"node_id": "worker-1", "kind": "worker", "state": "planned"},
                position=0,
            ),
            _event(
                "lease_granted",
                {
                    "lease_id": "lease-1",
                    "node_id": "worker-1",
                    "generation": 1,
                    "execution_id": "execution-1",
                    "base_snapshot_id": "snapshot-1",
                    "resource_claims": [],
                    "cache_authority_hash": "0" * 64,
                },
                position=1,
            ),
        ]
    )
    with pytest.raises(ValueError, match="canonical routine-snapshot-record"):
        cache_authority_binding(projection)
    with pytest.raises(ProjectionCheckpointIntegrityError, match="routine-snapshot-record"):
        validate_projection_integrity(projection)


@pytest.mark.parametrize("carrier", ["node", "lease"])
def test_authority_binding_rejects_mixed_legacy_snapshot_carriers(carrier: str) -> None:
    events = _compiled()
    snapshot = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    snapshot_payload = copy.deepcopy(snapshot.payload)
    snapshot_value = snapshot_payload["value"]
    assert isinstance(snapshot_value, dict)
    for field in (
        "cache_authority_version",
        "cache_authority_preimage",
        "cache_authority_hash",
    ):
        snapshot_value.pop(field, None)
    events[events.index(snapshot)] = snapshot.model_copy(update={"payload": snapshot_payload})
    if carrier == "lease":
        for index, event in enumerate(events):
            if event.event_type != "node_created":
                continue
            payload = copy.deepcopy(event.payload)
            payload.pop("cache_authority_hash", None)
            events[index] = event.model_copy(update={"payload": payload})
        events.append(
            _event(
                "lease_granted",
                {
                    "lease_id": "lease-mixed",
                    "node_id": "worker-s-t",
                    "generation": 1,
                    "execution_id": "execution-mixed",
                    "base_snapshot_id": "snapshot-1",
                    "resource_claims": [],
                    "cache_authority_hash": cache_authority_hash(CacheAuthorityPolicy()),
                },
                position=len(events),
            )
        )
    projection = build_projection(events)
    with pytest.raises(ValueError, match="mixed"):
        cache_authority_binding(projection)
    with pytest.raises(ProjectionCheckpointIntegrityError, match="legacy cache authority"):
        validate_projection_integrity(projection)


@pytest.mark.parametrize(
    ("case", "updates"),
    [
        ("partial_snapshot", {"cache_authority_hash": None}),
        ("unknown_version", {"cache_authority_version": "cache-authority-v2"}),
    ],
)
def test_integrity_rejects_partial_or_unknown_snapshot_authority(
    case: str, updates: dict[str, object]
) -> None:
    del case
    projection, _ = _snapshot_projection(**updates)
    with pytest.raises(ProjectionCheckpointIntegrityError, match="cache authority"):
        validate_projection_integrity(projection)


def test_integrity_rejects_wrong_reserved_snapshot_record_type() -> None:
    events = _compiled()
    snapshot = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    payload = copy.deepcopy(snapshot.payload)
    payload.update(
        {
            "record_type": "candidate",
            "record_kind": "output",
            "schema": "ImplementationCandidate",
            "producer_node_id": "worker-s-t",
            "port": "candidate",
            "candidate_id": "candidate-reserved-integrity",
            "value": {"summary": "wrong reserved record"},
        }
    )
    events[events.index(snapshot)] = snapshot.model_copy(update={"payload": payload})
    projection = build_projection(events)
    with pytest.raises(ProjectionCheckpointIntegrityError, match="routine-snapshot-record"):
        validate_projection_integrity(projection)


@pytest.mark.parametrize("missing", [True, False])
def test_integrity_rejects_missing_or_mismatched_node_authority_hash(missing: bool) -> None:
    events = _compiled()
    node = next(
        event
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "worker-s-t"
    )
    payload = copy.deepcopy(node.payload)
    if missing:
        payload.pop("cache_authority_hash", None)
    else:
        payload["cache_authority_hash"] = "0" * 64
    events[events.index(node)] = node.model_copy(update={"payload": payload})
    with pytest.raises(ProjectionCheckpointIntegrityError, match="cache_authority_hash"):
        validate_projection_integrity(build_projection(events))


@pytest.mark.parametrize("missing", [True, False])
def test_integrity_rejects_missing_or_mismatched_lease_authority_hash(missing: bool) -> None:
    events, projection = _schedule_projection()
    lease_events = apply_command(
        projection,
        events,
        "schedule_tick",
        {"max_grants": 1},
        GraphCommandContext(run_id="run-authority", current_graph_position=0),
        FakeClock(),
        SequentialIdGenerator(),
    )
    lease = next(event for event in lease_events if event.event_type == "lease_granted")
    payload = copy.deepcopy(lease.payload)
    if missing:
        payload.pop("cache_authority_hash", None)
    else:
        payload["cache_authority_hash"] = "0" * 64
    lease_events[lease_events.index(lease)] = lease.model_copy(update={"payload": payload})
    with pytest.raises(ProjectionCheckpointIntegrityError, match="cache_authority_hash"):
        validate_projection_integrity(build_projection([*events, *lease_events]))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tool_cache_patterns", ("replacement/**",), "tool_cache_patterns are frozen"),
        ("secret_name_patterns", ("replacement",), "secret_name_patterns are frozen"),
        ("secret_entropy_threshold", 5.0, "secret_entropy_threshold is frozen"),
    ],
)
def test_v1_rejects_every_frozen_runtime_replacement(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CacheAuthorityPolicy.model_validate({field: value})


def test_runtime_materialization_is_authority_owned_and_learned_rules_are_isolated() -> None:
    policy = CacheAuthorityPolicy.model_validate(
        {
            "scan_budget": {"max_entries": 7, "max_bytes": 11},
            "declarations": [
                {
                    "pattern": "reports/**",
                    "classification": "test_artifact",
                    "source_kinds": ["untracked"],
                }
            ],
        }
    )
    runtime = file_state_policy_from_authority(policy)
    learned_events = [
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-learned",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "snapshot_id": "snapshot-learned",
                "base_snapshot_id": "snapshot-base",
                "git": {
                    "commit_sha": "commit-learned",
                    "tree_sha": "tree-learned",
                    "ref": "refs/orchestrator/snapshots/snapshot-learned",
                },
                "classifications": [
                    {
                        "path": "learned/result.xml",
                        "source": "untracked",
                        "classification": "unknown_untracked",
                        "needs_gatekeeper": True,
                    }
                ],
                "residue": [],
            },
            position=1,
        ),
        _event(
            "gatekeeper_verdict_recorded",
            {
                "file_state_record_id": "file-state-learned",
                "execution_id": "execution-learned",
                "producer_node_id": "worker-1",
                "verdicts": [
                    {
                        "path": "learned/result.xml",
                        "classification": "test_artifact",
                        "confidence": 0.9,
                        "rationale": "learned rule",
                        "model_id": "test-model",
                    }
                ],
                "resolved_count": 1,
            },
            position=2,
        ),
    ]
    learned = policy_with_pattern_library(learned_events, base_policy=runtime)
    assert learned.declarations != runtime.declarations
    assert all(item.pattern != "learned/result.xml" for item in policy.declarations)
    assert runtime.tool_cache_patterns == policy.tool_cache_patterns
    assert runtime.scan_budget.max_entries == 7
    assert runtime.scan_budget.max_bytes == 11
    assert canonicalize_cache_authority(policy) == canonicalize_cache_authority(
        CacheAuthorityPolicy.model_validate(policy.model_dump())
    )


@pytest.mark.parametrize("operation", ["generic", "gate", "revision", "appeal"])
def test_dynamic_nodes_inherit_authority_hash(operation: str) -> None:
    events = [_event("run_lifecycle_changed", {"to_state": "active"}, position=0), *_compiled()]
    projection = build_projection(events)
    digest = cache_authority_binding(projection).hash
    payloads: dict[str, dict[str, Any]] = {
        "generic": {
            "op": "create_node",
            "node": {
                "node_id": "worker-dynamic",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "dynamic",
                "candidate_id": "candidate-dynamic",
            },
        },
        "gate": {
            "op": "create_gate",
            "node": {"node_id": "gate-dynamic", "kind": "gate", "state": "planned"},
        },
        "revision": {
            "op": "create_revision_attempt",
            "task_region_id": "dynamic",
            "worker_node": {"node_id": "worker-revision", "kind": "worker", "role": "builder"},
            "verifier_node": {
                "node_id": "verifier-revision",
                "kind": "verifier",
                "role": "verifier",
            },
        },
        "appeal": {
            "op": "create_appeal",
            "node": {"node_id": "appeal-dynamic", "kind": "appeal", "state": "planned"},
            "appealed_node_id": "verifier-authority-s-t",
            "appeal_type": "invalid_test",
        },
    }
    emitted = apply_command(
        projection,
        events,
        "submit_patch",
        {
            "patch_id": f"patch-{operation}",
            "base_graph_position": 0,
            "ops": [payloads[operation]],
        },
        PatchCommandContext(
            run_id="run-authority",
            current_graph_position=0,
            proposed_by_node_id="planner-s",
            actor_role="controller",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    created = [event for event in emitted if event.event_type == "node_created"]
    assert created
    assert all(event.payload.get("cache_authority_hash") == digest for event in created)


@pytest.mark.parametrize("operation", ["generic", "gate", "revision", "appeal"])
def test_dynamic_nodes_reject_explicit_authority_mismatch(operation: str) -> None:
    events = [_event("run_lifecycle_changed", {"to_state": "active"}, position=0), *_compiled()]
    projection = build_projection(events)
    operations: dict[str, dict[str, Any]] = {
        "generic": {
            "op": "create_node",
            "node": {
                "node_id": "worker-mismatch",
                "kind": "worker",
                "role": "builder",
                "task_region_id": "dynamic",
                "candidate_id": "candidate-mismatch",
                "cache_authority_hash": "0" * 64,
            },
        },
        "gate": {
            "op": "create_gate",
            "node": {
                "node_id": "gate-mismatch",
                "kind": "gate",
                "cache_authority_hash": "0" * 64,
            },
        },
        "revision": {
            "op": "create_revision_attempt",
            "task_region_id": "dynamic-mismatch",
            "worker_node": {
                "node_id": "worker-revision-mismatch",
                "kind": "worker",
                "role": "builder",
                "cache_authority_hash": "0" * 64,
            },
        },
        "appeal": {
            "op": "create_appeal",
            "node": {
                "node_id": "appeal-mismatch",
                "kind": "appeal",
                "cache_authority_hash": "0" * 64,
            },
            "appealed_node_id": "verifier-authority-s-t",
        },
    }
    with pytest.raises(ValueError, match="differs from routine snapshot"):
        apply_command(
            projection,
            events,
            "submit_patch",
            {
                "patch_id": f"patch-mismatch-{operation}",
                "base_graph_position": 0,
                "ops": [operations[operation]],
            },
            PatchCommandContext(
                run_id="run-authority",
                current_graph_position=0,
                proposed_by_node_id="planner-s",
                actor_role="controller",
            ),
            FakeClock(),
            SequentialIdGenerator(),
        )


def _schedule_projection(
    *, missing_snapshot: bool = False, mismatch: bool = False
) -> tuple[list[EventEnvelope], Any]:
    events = [_event("run_lifecycle_changed", {"to_state": "active"}, position=0), *_compiled()]
    if missing_snapshot or mismatch:
        node = next(
            event
            for event in events
            if event.event_type == "node_created" and event.payload.get("node_id") == "worker-s-t"
        )
        payload = copy.deepcopy(node.payload)
        if missing_snapshot:
            payload.pop("cache_authority_hash", None)
        else:
            payload["cache_authority_hash"] = "0" * 64
        events[events.index(node)] = node.model_copy(update={"payload": payload})
    return events, build_projection(events)


def test_scheduler_defers_missing_or_mismatched_authority_before_lease() -> None:
    for kwargs, reason in (
        ({"missing_snapshot": True}, "cache_authority_mismatch"),
        ({"mismatch": True}, "cache_authority_mismatch"),
    ):
        events, projection = _schedule_projection(**kwargs)
        emitted = apply_command(
            projection,
            events,
            "schedule_tick",
            {"max_grants": 10, "base_snapshot_id": "snapshot-explicit"},
            GraphCommandContext(run_id="run-authority", current_graph_position=0),
            FakeClock(),
            SequentialIdGenerator(),
        )
        deferred = [event for event in emitted if event.event_type == "node_deferred"]
        assert any(event.payload.get("reason") == reason for event in deferred)
        assert not any(
            event.event_type == "lease_granted" and event.payload.get("node_id") == "worker-s-t"
            for event in emitted
        )


def test_scheduler_propagates_authority_hash_into_lease() -> None:
    events, projection = _schedule_projection()
    digest = cache_authority_binding(projection).hash
    emitted = apply_command(
        projection,
        events,
        "schedule_tick",
        {"max_grants": 10},
        GraphCommandContext(run_id="run-authority", current_graph_position=0),
        FakeClock(),
        SequentialIdGenerator(),
    )
    lease = next(event for event in emitted if event.event_type == "lease_granted")
    assert lease.payload["cache_authority_hash"] == digest


class _CountingRunnerFactory:
    def __init__(self) -> None:
        self.calls = 0

    def create_runner(self, context: GraphDispatchContext) -> object:
        del context
        self.calls += 1
        raise AssertionError("runner must not be created")


async def _persist_events(session_factory: Any, run_id: str, events: list[EventEnvelope]) -> None:
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


def _dispatch_item(*, digest: str | None, lease_id: str = "lease-1") -> OutboxItem:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return OutboxItem(
        outbox_id=1,
        event_id="dispatch-1",
        run_id="run-dispatch",
        kind="agent_dispatch",
        payload={
            "node_id": "worker-1",
            "lease_id": lease_id,
            "generation": 1,
            "execution_id": "execution-1",
            "base_snapshot_id": "snapshot-1",
            "cache_authority_hash": digest,
        },
        status="pending",
        attempts=0,
        created_at=now,
        updated_at=now,
        next_attempt_at=None,
        last_error=None,
    )


_INHERIT_AUTHORITY_DIGEST = object()


def _dispatch_events(
    *,
    digest: str | None,
    node_digest: str | None | object = _INHERIT_AUTHORITY_DIGEST,
    lease_digest: str | None | object = _INHERIT_AUTHORITY_DIGEST,
    include_lease: bool = True,
    legacy: bool = False,
) -> list[EventEnvelope]:
    if node_digest is _INHERIT_AUTHORITY_DIGEST:
        node_digest = digest
    if lease_digest is _INHERIT_AUTHORITY_DIGEST:
        lease_digest = digest
    snapshot = next(
        event
        for event in _compiled()
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    ).model_copy(update={"run_id": "run-dispatch"})
    if legacy:
        snapshot_payload = copy.deepcopy(snapshot.payload)
        snapshot_value = snapshot_payload["value"]
        assert isinstance(snapshot_value, dict)
        for field in (
            "cache_authority_version",
            "cache_authority_preimage",
            "cache_authority_hash",
        ):
            snapshot_value.pop(field, None)
        snapshot = snapshot.model_copy(update={"payload": snapshot_payload})
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, position=0, run_id="run-dispatch"),
        snapshot,
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "ready",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "cache_authority_hash": node_digest,
            },
            position=1,
            run_id="run-dispatch",
        ),
    ]
    if include_lease:
        events.append(
            _event(
                "lease_granted",
                {
                    "lease_id": "lease-1",
                    "node_id": "worker-1",
                    "generation": 1,
                    "execution_id": "execution-1",
                    "base_snapshot_id": "snapshot-1",
                    "expires_at": "2026-01-01T00:05:00+00:00",
                    "resource_claims": [],
                    "cache_authority_hash": lease_digest,
                },
                position=2,
                run_id="run-dispatch",
            )
        )
    events.append(
        _event(
            "agent_dispatch_requested",
            {
                "lease_granted_event_id": "authority-event-2",
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "execution-1",
                "base_snapshot_id": "snapshot-1",
                "resource_claims": [],
                "cache_authority_hash": digest,
            },
            position=3,
            run_id="run-dispatch",
        ),
    )
    return events


class _CountingFilesystemPath:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.accesses = 0

    def __str__(self) -> str:
        self.accesses += 1
        return str(self.path)

    def __fspath__(self) -> str:
        self.accesses += 1
        return str(self.path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("carrier", "dispatch_digest", "node_digest", "lease_digest", "include_lease"),
    [
        ("dispatch", None, "valid", "valid", True),
        ("dispatch", "0" * 64, "valid", "valid", True),
        ("node", "valid", None, "valid", True),
        ("node", "valid", "0" * 64, "valid", True),
        ("lease", "valid", "valid", None, True),
        ("lease", "valid", "valid", "0" * 64, True),
        ("lease_record", "valid", "valid", "valid", False),
    ],
)
async def test_dispatch_rejects_missing_or_mismatched_authority_before_runner(
    tmp_path: Path,
    carrier: str,
    dispatch_digest: str | None,
    node_digest: str | None,
    lease_digest: str | None,
    include_lease: bool,
) -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    digest = cache_authority_hash(CacheAuthorityPolicy())

    def resolve(value: str | None) -> str | None:
        return digest if value == "valid" else value

    await _persist_events(
        session_factory,
        "run-dispatch",
        _dispatch_events(
            digest=digest,
            node_digest=resolve(node_digest),
            lease_digest=resolve(lease_digest),
            include_lease=include_lease,
        ),
    )
    factory = _CountingRunnerFactory()
    filesystem_path = _CountingFilesystemPath(tmp_path)
    executor = GraphDispatchExecutor(
        session_factory,
        GraphController(session_factory, FakeClock(), SequentialIdGenerator(), auto_dispatch=False),
        factory,
        worktree_path=cast(Any, filesystem_path),
        artifact_store=FilesystemArtifactStore(tmp_path),
    )
    filesystem_path.accesses = 0
    with pytest.raises(ValueError, match="cache authority"):
        await executor.dispatch(_dispatch_item(digest=resolve(dispatch_digest)))
    assert factory.calls == 0
    assert filesystem_path.accesses == 0, carrier
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_dispatch_uses_frozen_legacy_authority(tmp_path: Path) -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    await _persist_events(
        session_factory,
        "run-dispatch",
        _dispatch_events(digest=None, legacy=True),
    )
    factory = _CountingRunnerFactory()
    executor = GraphDispatchExecutor(
        session_factory,
        GraphController(session_factory, FakeClock(), SequentialIdGenerator(), auto_dispatch=False),
        factory,
        worktree_path=tmp_path,
        artifact_store=FilesystemArtifactStore(tmp_path),
    )
    context = await executor._build_dispatch_context(_dispatch_item(digest=None))
    assert context.cache_authority_hash == cache_authority_hash(CacheAuthorityPolicy())
    assert factory.calls == 0
    await engine.dispose()


class _BoundaryRunner:
    def __init__(self, *, fail: bool) -> None:
        self._fail = fail

    @property
    def info(self) -> Any:
        return None

    async def execute(
        self,
        context: Any,
        _on_checklist_update: Any,
        on_submit: Any,
        **_callbacks: Any,
    ) -> ExecutionResult:
        learned_path = Path(context.working_dir) / "learned-cache" / "created.txt"
        learned_path.parent.mkdir(parents=True, exist_ok=True)
        learned_path.write_text("runtime learned cache\n", encoding="utf-8")
        if not self._fail:
            await on_submit()
        return ExecutionResult(success=not self._fail)

    async def cancel(self) -> None:
        return None


class _BoundaryRunnerFactory:
    def __init__(self, runner: _BoundaryRunner) -> None:
        self.runner = runner
        self.calls = 0

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        del context
        self.calls += 1
        return cast(AgentRunner, self.runner)


def _init_runtime_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "README.md").write_text("runtime authority\n", encoding="utf-8")
    (repo / ".gitignore").write_text("custom-cache/\nlearned-cache/\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "runtime-authority",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    cache_file = repo / "custom-cache" / "existing.txt"
    cache_file.parent.mkdir()
    cache_file.write_text("custom cache\n", encoding="utf-8")


def _learned_pattern_events(run_id: str) -> list[EventEnvelope]:
    path = "learned-cache/result.xml"
    entry = {
        "path": path,
        "source": "untracked",
        "classification": "unknown_untracked",
        "matched_rule": "unmatched_untracked",
        "needs_gatekeeper": True,
        "size_bytes": 12,
    }
    return [
        _event(
            "file_state_accepted",
            {
                "record_id": "learned-file-state",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-s-t",
                "snapshot_id": "snapshot-learned",
                "base_snapshot_id": "snapshot-base",
                "task_region_id": "s/t",
                "candidate_id": "candidate-s-t-1",
                "git": {
                    "commit_sha": "0" * 40,
                    "tree_sha": "1" * 40,
                    "ref": "refs/orchestrator/snapshots/snapshot-learned",
                },
                "classifications": [entry],
                "residue": [entry],
            },
            position=0,
            run_id=run_id,
        ),
        _event(
            "gatekeeper_verdict_recorded",
            {
                "file_state_record_id": "learned-file-state",
                "execution_id": "learned-execution",
                "producer_node_id": "worker-s-t",
                "verdicts": [
                    {
                        "path": path,
                        "classification": "test_artifact",
                        "confidence": 0.9,
                        "rationale": "learned test artifact",
                        "model_id": "test-model",
                    }
                ],
                "resolved_count": 1,
            },
            position=1,
            run_id=run_id,
        ),
    ]


async def _append_at_head(session_factory: Any, run_id: str, events: list[EventEnvelope]) -> None:
    async with session_factory() as session:
        store = GraphEventStore(session)
        position = await store.current_position(run_id)
        await store.append_events(run_id, position, events)
        await session.commit()


async def _read_events(session_factory: Any, run_id: str) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _run_runtime_boundary_case(tmp_path: Path, *, fail: bool) -> list[EventEnvelope]:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    run_id = "runtime-authority-failure" if fail else "runtime-authority-success"
    await seed_run(session_factory, _runtime_routine(), run_id=run_id, clock=clock, id_gen=ids)
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    accepted = await controller.handle_command(
        run_id, await controller.current_position(run_id), "accept_run"
    )
    await controller.handle_command(run_id, accepted.projection_position, "start")
    learned_events = _learned_pattern_events(run_id)
    assert project_pattern_library(learned_events)["patterns"]
    await _append_at_head(session_factory, run_id, learned_events)
    authority = cache_authority_binding(await controller.read_projection(run_id))
    assert [item.pattern for item in authority.policy.declarations] == ["custom-cache/**"]

    repo = tmp_path / ("runtime-failure" if fail else "runtime-success")
    _init_runtime_repo(repo)
    factory = _BoundaryRunnerFactory(_BoundaryRunner(fail=fail))
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        factory,
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"max_grants": 1, "lease_seconds": 60},
    )
    await dispatcher.dispatch_pending(run_id=run_id)
    await executor.wait_for_all()
    events = await _read_events(session_factory, run_id)
    await engine.dispose()
    return events


@pytest.mark.asyncio
async def test_executor_boundary_paths_use_snapshot_policy_not_learned_rules(
    tmp_path: Path,
) -> None:
    events = await _run_runtime_boundary_case(tmp_path, fail=False)
    baseline = next(event for event in events if event.event_type == "runner_baseline_recorded")
    staged = next(event for event in events if event.event_type == "runner_submission_staged")
    final = next(event for event in events if event.event_type == "runner_execution_finalized")
    learned_path = "learned-cache/created.txt"
    assert baseline.payload["cache_roots"] == [{"path": "custom-cache", "kind": "ignored"}]
    assert not any(entry["path"] == learned_path for entry in baseline.payload["entries"])
    assert not any(
        entry["path"].startswith("custom-cache/") for entry in baseline.payload["entries"]
    )
    assert final.payload["cache_roots"] == [{"path": "custom-cache", "kind": "ignored"}]
    assert any(entry["path"] == learned_path for entry in final.payload["boundary_entries"])
    assert not any(
        entry["path"].startswith("custom-cache/") for entry in final.payload["boundary_entries"]
    )
    assert any(entry["path"] == learned_path for entry in staged.payload["boundary_entries"])
    assert not any(
        entry["path"].startswith("custom-cache/") for entry in staged.payload["boundary_entries"]
    )


@pytest.mark.asyncio
async def test_executor_recovery_capture_uses_snapshot_policy_not_learned_rules(
    tmp_path: Path,
) -> None:
    events = await _run_runtime_boundary_case(tmp_path, fail=True)
    recovery = next(event for event in events if event.event_type == "runner_recovery_requested")
    assert recovery.payload["observed_cache_roots"] == [{"path": "custom-cache", "kind": "ignored"}]
    assert recovery.payload["authorized_cache_roots"] == [
        {"path": "custom-cache", "kind": "ignored"}
    ]
    assert recovery.payload["legacy_cache_root_paths"] == []
    assert any(
        entry["path"] == "learned-cache/created.txt"
        for entry in recovery.payload["final_boundary_entries"]
    )
    assert not any(
        entry["path"].startswith("custom-cache/")
        for entry in recovery.payload["final_boundary_entries"]
    )


def test_lease_projection_preserves_all_authority_and_ownership_fields() -> None:
    digest = cache_authority_hash(CacheAuthorityPolicy())
    projection = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "role": "builder",
                    "state": "planned",
                    "task_region_id": "task-1",
                    "cache_authority_hash": digest,
                    "authority": {
                        "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}]
                    },
                },
                position=0,
            ),
            _event(
                "lease_granted",
                {
                    "lease_id": "lease-1",
                    "node_id": "worker-1",
                    "generation": 2,
                    "execution_id": "execution-1",
                    "base_snapshot_id": "snapshot-1",
                    "task_region_id": "task-1",
                    "kind": "worker",
                    "session_id": "session-1",
                    "expires_at": "2026-01-01T00:05:00+00:00",
                    "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
                    "cache_authority_hash": digest,
                },
                position=1,
            ),
        ]
    )
    lease = lease_by_id(projection, "lease-1")
    assert lease is not None
    assert lease.generation == 2
    assert lease.execution_id == "execution-1"
    assert lease.base_snapshot_id == "snapshot-1"
    assert lease.task_region_id == "task-1"
    assert lease.kind == "worker"
    assert lease.session_id == "session-1"
    assert lease.cache_authority_hash == digest
    assert leases_view(projection)["lease-1"] == lease


def test_every_node_and_lease_pass_authority_integrity() -> None:
    events, projection = _schedule_projection()
    scheduled = apply_command(
        projection,
        events,
        "schedule_tick",
        {"max_grants": 10},
        GraphCommandContext(run_id="run-authority", current_graph_position=0),
        FakeClock(),
        SequentialIdGenerator(),
    )
    final = build_projection([*events, *scheduled])
    validate_projection_integrity(final)
    digest = cache_authority_binding(final).hash
    assert all(
        node_cache_authority_hash(final, node_id) == digest for node_id in node_states_view(final)
    )
    assert all(lease.cache_authority_hash == digest for lease in leases_view(final).values())


def test_authority_codec_live_replay_and_checkpoint_round_trip() -> None:
    events = _compiled()
    live = initial_projection()
    for event in events:
        live = reduce_event(live, event)
    replay = build_projection(events)
    assert live == replay
    checkpoint = projection_to_checkpoint(live)
    restored = projection_from_checkpoint(checkpoint)
    assert restored == live
    assert cache_authority_binding(restored) == cache_authority_binding(live)


def test_routine_content_hash_is_sensitive_to_policy_content() -> None:
    plain = _compiled()
    declared = _compiled(
        {
            "declarations": [
                {
                    "pattern": "reports/**",
                    "classification": "test_artifact",
                    "source_kinds": ["untracked"],
                }
            ]
        }
    )
    plain_snapshot = next(
        event.payload["value"]
        for event in plain
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    declared_snapshot = next(
        event.payload["value"]
        for event in declared
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    assert plain_snapshot["content_hash"] != declared_snapshot["content_hash"]
    assert plain_snapshot["cache_authority_hash"] != declared_snapshot["cache_authority_hash"]


def test_legacy_snapshot_still_schedules_without_authority_hash() -> None:
    events = _compiled()
    snapshot = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "routine-snapshot-record"
    )
    payload = copy.deepcopy(snapshot.payload)
    value = payload["value"]
    assert isinstance(value, dict)
    for field in ("cache_authority_version", "cache_authority_preimage", "cache_authority_hash"):
        value.pop(field, None)
    events[events.index(snapshot)] = snapshot.model_copy(update={"payload": payload})
    for index, event in enumerate(events):
        if event.event_type != "node_created":
            continue
        node_payload = copy.deepcopy(event.payload)
        node_payload.pop("cache_authority_hash", None)
        events[index] = event.model_copy(update={"payload": node_payload})
    projection = build_projection(
        [_event("run_lifecycle_changed", {"to_state": "active"}, position=0), *events]
    )
    emitted = apply_command(
        projection,
        [_event("run_lifecycle_changed", {"to_state": "active"}, position=0), *events],
        "schedule_tick",
        {"base_snapshot_id": "legacy-snapshot"},
        GraphCommandContext(run_id="run-authority", current_graph_position=0),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert any(event.event_type == "lease_granted" for event in emitted)
    lease = next(event for event in emitted if event.event_type == "lease_granted")
    assert lease.payload.get("cache_authority_hash") is None
    assert cache_authority_binding(projection).hash == cache_authority_hash(CacheAuthorityPolicy())
