"""Durable cache-authority recovery facts across every graph read path."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import RoutineConfig
from orchestrator.config.enums import AgentRunnerType
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    CacheStatusEvidence,
    EventEnvelope,
    FakeClock,
    GraphProjection,
    ProjectionReplayConflictError,
    RunnerCacheRoot,
    SequentialIdGenerator,
    boundary_manifest_hash,
    build_projection,
    cache_authority_binding,
    execution_attempts_view,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    thaw_json,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphEventStore,
    build_graph_runtime,
    seed_run,
)


pytestmark = pytest.mark.slow

OID = "a" * 40
FINGERPRINT = "sha256:" + "b" * 64
CHANGED_FINGERPRINT = "sha256:" + "c" * 64
BASELINE_SNAPSHOT = "1" * 32
STAGED_SNAPSHOT = "2" * 32
FINAL_SNAPSHOT = "3" * 32
RECOVERY_SNAPSHOT = "4" * 32
MANAGED_BOUNDARY_COMMANDS = {
    "record_runner_baseline",
    "stage_runner_submission",
    "witness_runner_completion",
    "finalize_runner_execution",
    "request_runner_recovery",
}


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "cache-authority-durability",
            "name": "Cache authority durability",
            "file_state_policy": {
                "declarations": [
                    {
                        "pattern": "a-cache/**",
                        "classification": "tool_cache",
                        "source_kinds": ["ignored"],
                    },
                    {
                        "pattern": "z-cache/**",
                        "classification": "tool_cache",
                        "source_kinds": ["ignored"],
                    },
                ]
            },
            "steps": [{"id": "step", "title": "Step", "tasks": [{"id": "task", "title": "Task"}]}],
        }
    )


def _entry(path: str = "README.md", *, changed: bool = False) -> dict[str, str]:
    return {
        "path": path,
        "kind": "tracked" if path == "README.md" else "untracked",
        "status": "modified" if changed else "clean",
        "fingerprint": CHANGED_FINGERPRINT if changed else FINGERPRINT,
        "file_type": "file",
    }


def _root(path: str) -> dict[str, str]:
    return RunnerCacheRoot(path=path, kind="ignored").model_dump(mode="json")


def _evidence(path: str) -> dict[str, str]:
    return CacheStatusEvidence(path=f"{path}/entry", kind="ignored").model_dump(mode="json")


def _ref(snapshot_id: str) -> str:
    return f"refs/orchestrator/snapshots/{snapshot_id}"


@dataclass
class Harness:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    controller: GraphController
    executor: Any
    run_id: str
    node_id: str
    lease_id: str
    execution_id: str
    lease_generation: int
    authority_hash: str


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncGenerator[Harness, None]:
    engine = create_engine(tmp_path / "cache-authority.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    run_id = "cache-authority-durability-run"
    controller, executor = build_graph_runtime(
        session_factory,
        clock,
        id_gen,
        worktree_path=tmp_path / "worktree",
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        runner_type=AgentRunnerType.CLI_SUBPROCESS,
    )
    seeded = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=id_gen)
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {"base_snapshot_id": BASELINE_SNAPSHOT, "max_grants": 1, "lease_seconds": 60},
    )
    lease_event = next(event for event in scheduled.events if event.event_type == "lease_granted")
    lease = lease_event.payload
    projection = await controller.read_projection(run_id)
    yield Harness(
        engine=engine,
        session_factory=session_factory,
        controller=controller,
        executor=executor,
        run_id=run_id,
        node_id=str(lease["node_id"]),
        lease_id=str(lease["lease_id"]),
        execution_id=str(lease["execution_id"]),
        lease_generation=int(lease["generation"]),
        authority_hash=cache_authority_binding(projection).hash,
    )
    await engine.dispose()


async def _events(harness: Harness) -> list[EventEnvelope]:
    async with harness.session_factory() as session:
        return await GraphEventStore(session).read_run(harness.run_id)


def _boundary_hash(
    harness: Harness,
    entries: list[dict[str, str]],
    evidence: list[dict[str, str]],
) -> str:
    return boundary_manifest_hash(
        OID,
        entries,
        evidence,
        harness.authority_hash,
    )


async def _trusted_boundary_command(
    harness: Harness,
    command_type: str,
    payload: dict[str, object],
) -> Any:
    # RuntimeBoundaryCapability is intentionally not public.  The public
    # build_graph_runtime factory wires the executor's opaque capability to its
    # controller; this is the same command path used by managed dispatch.
    return await harness.executor._handle_command_retry_stale(  # pyright: ignore[reportPrivateUsage]
        harness.run_id,
        await harness.controller.current_position(harness.run_id),
        command_type,
        payload,
    )


def _identity(harness: Harness) -> dict[str, object]:
    return {
        "execution_id": harness.execution_id,
        "node_id": harness.node_id,
        "lease_id": harness.lease_id,
        "lease_generation": harness.lease_generation,
    }


def _baseline_payload(
    harness: Harness,
    roots: list[str],
    evidence: list[dict[str, str]],
) -> dict[str, object]:
    entries = [_entry()]
    return {
        **_identity(harness),
        "lease_base_snapshot_id": BASELINE_SNAPSHOT,
        "baseline_snapshot_id": BASELINE_SNAPSHOT,
        "baseline_snapshot_ref": _ref(BASELINE_SNAPSHOT),
        "baseline_commit_sha": OID,
        "baseline_tree_sha": OID,
        "entries": entries,
        "boundary_hash": _boundary_hash(harness, entries, evidence),
        "cache_authority_hash": harness.authority_hash,
        "cache_roots": [_root(root) for root in roots],
        "cache_status_evidence": evidence,
    }


def _stage_payload(
    harness: Harness,
    roots: list[str],
    evidence: list[dict[str, str]],
) -> dict[str, object]:
    entries = [_entry()]
    return {
        **_identity(harness),
        "base_snapshot_id": BASELINE_SNAPSHOT,
        "observed_graph_position": 0,
        "idempotency_key": "cache-authority-submit",
        "payload": {},
        "is_mutating": False,
        "complete_node": False,
        "new_state": "completed",
        "staged_snapshot_id": STAGED_SNAPSHOT,
        "staged_snapshot_ref": _ref(STAGED_SNAPSHOT),
        "staged_commit_sha": OID,
        "staged_tree_sha": OID,
        "boundary_hash": _boundary_hash(harness, entries, evidence),
        "boundary_entries": entries,
        "cache_authority_hash": harness.authority_hash,
        "cache_roots": [_root(root) for root in roots],
        "cache_status_evidence": evidence,
    }


def _final_payload(
    harness: Harness,
    roots: list[str],
    evidence: list[dict[str, str]],
) -> dict[str, object]:
    entries = [_entry(changed=True)]
    return {
        **_identity(harness),
        "final_snapshot_id": FINAL_SNAPSHOT,
        "final_snapshot_ref": _ref(FINAL_SNAPSHOT),
        "final_commit_sha": OID,
        "final_tree_sha": OID,
        "boundary_hash": _boundary_hash(harness, entries, evidence),
        "boundary_entries": entries,
        "cache_authority_hash": harness.authority_hash,
        "cache_roots": [_root(root) for root in roots],
        "cache_status_evidence": evidence,
    }


async def _witness_then_finalize(harness: Harness, final: dict[str, object]) -> Any:
    attempt = execution_attempts_view(await harness.controller.read_projection(harness.run_id))[
        harness.execution_id
    ]
    witnessed = await _trusted_boundary_command(
        harness,
        "witness_runner_completion",
        {
            **final,
            "staged_payload_hash": attempt.payload_hash,
            "staged_payload_size_bytes": attempt.payload_size_bytes,
            "staged_snapshot_id": attempt.staged_snapshot_id,
            "staged_snapshot_ref": attempt.staged_snapshot_ref,
            "staged_commit_sha": attempt.staged_commit_sha,
            "staged_tree_sha": attempt.staged_tree_sha,
            "staged_boundary_hash": attempt.staged_boundary_hash,
            "runner_return_kind": "successful_return",
        },
    )
    if any(
        event.event_type in {"runner_boundary_mismatch", "command_rejected"}
        for event in witnessed.events
    ):
        return witnessed
    return await _trusted_boundary_command(harness, "finalize_runner_execution", final)


async def _run_case(harness: Harness, case: str) -> tuple[list[EventEnvelope], GraphProjection]:
    phase_roots = {
        "baseline": (["z-cache"], [], [], []),
        "stage": ([], ["z-cache"], [], []),
        "final": ([], [], ["z-cache"], []),
        "recovery": ([], [], [], ["a-cache"]),
    }[case]
    baseline_roots, stage_roots, final_roots, recovery_roots = phase_roots
    baseline_evidence = [_evidence(root) for root in baseline_roots]
    stage_evidence = [_evidence(root) for root in stage_roots]
    final_evidence = [_evidence(root) for root in final_roots]
    recovery_evidence = [_evidence(root) for root in recovery_roots]

    await _trusted_boundary_command(
        harness,
        "record_runner_baseline",
        _baseline_payload(harness, baseline_roots, baseline_evidence),
    )
    stage = _stage_payload(harness, stage_roots, stage_evidence)
    stage["observed_graph_position"] = await harness.controller.current_position(harness.run_id)
    await _trusted_boundary_command(harness, "stage_runner_submission", stage)

    if case == "recovery":
        entries = [_entry(changed=True)]
        recovery_payload: dict[str, object] = {
            **_identity(harness),
            "reason": "runner_died",
            "max_attempts": 3,
            "recovery_snapshot_id": RECOVERY_SNAPSHOT,
            "recovery_snapshot_ref": _ref(RECOVERY_SNAPSHOT),
            "recovery_commit_sha": OID,
            "final_tree_sha": OID,
            "boundary_hash": _boundary_hash(harness, entries, recovery_evidence),
            "boundary_entries": entries,
            "cache_authority_hash": harness.authority_hash,
            "observed_cache_roots": [_root(root) for root in recovery_roots],
            "cache_status_evidence": recovery_evidence,
        }
        await _trusted_boundary_command(harness, "request_runner_recovery", recovery_payload)
    else:
        final = _final_payload(harness, final_roots, final_evidence)
        mismatch = await _witness_then_finalize(harness, final)
        assert [event.event_type for event in mismatch.events] == [
            "runner_completion_witnessed",
            "runner_boundary_mismatch",
            "runner_recovery_requested",
        ]

    events = await _events(harness)
    return events, await harness.controller.read_projection(harness.run_id)


def _typed_root_set(values: object) -> set[tuple[str, str]]:
    return {
        (root.path, root.kind)
        for root in values  # type: ignore[union-attr]
        if isinstance(root, RunnerCacheRoot)
    }


async def _exercise_boundary_authority_schema(harness: Harness, case: str) -> None:
    events, projection = await _run_case(harness, case)
    request = next(event for event in events if event.event_type == "runner_recovery_requested")
    mismatch = next(
        (event for event in events if event.event_type == "runner_boundary_mismatch"), None
    )
    boundary_event = mismatch or request
    for event in (boundary_event, request):
        assert (
            not {
                "observed_cache_roots",
                "authorized_cache_roots",
                "legacy_cache_root_paths",
                "cache_roots",
            }
            & event.payload.keys()
        )
        assert "cache_status_evidence" in event.payload
        assert event.payload["cache_authority_hash"] == harness.authority_hash

    attempt = execution_attempts_view(projection)[harness.execution_id]
    expected_phase_roots = {
        "baseline": {("z-cache", "ignored")} if case == "baseline" else set(),
        "stage": {("z-cache", "ignored")} if case == "stage" else set(),
        # Completion witnessing durably records final-phase evidence before
        # finalization detects the cross-phase boundary mismatch.
        "final": {("z-cache", "ignored")} if case == "final" else set(),
        "recovery": set(),
    }
    expected_recovery_roots = (
        {("a-cache", "ignored")}
        if case == "recovery"
        else ({("z-cache", "ignored")} if case == "final" else set())
    )
    assert _typed_root_set(attempt.baseline_cache_roots) == expected_phase_roots["baseline"]
    assert _typed_root_set(attempt.staged_cache_roots) == expected_phase_roots["stage"]
    assert _typed_root_set(attempt.final_cache_roots) == expected_phase_roots["final"]
    assert _typed_root_set(attempt.recovery_observed_cache_roots) == expected_recovery_roots
    assert _typed_root_set(attempt.recovery_authorized_cache_roots) == (
        expected_phase_roots["baseline"]
        | expected_phase_roots["stage"]
        | expected_phase_roots["final"]
        | expected_recovery_roots
    )
    assert attempt.legacy_cache_root_paths == ()


async def _exercise_projection_mode_sql_replay(harness: Harness, case: str) -> None:
    events, _ = await _run_case(harness, case)
    async with harness.session_factory() as session:
        store = GraphEventStore(session)
        full = await store.read_run(harness.run_id)
        projection_events = await store.read_run_projection(harness.run_id)
    assert [event.event_type for event in projection_events] == [event.event_type for event in full]
    projected = build_projection(projection_events)
    rebuilt = build_projection(full)
    projected_attempt = execution_attempts_view(projected)[harness.execution_id].model_dump(
        mode="json"
    )
    rebuilt_attempt = execution_attempts_view(rebuilt)[harness.execution_id].model_dump(mode="json")
    differences = {
        key: (projected_attempt.get(key), rebuilt_attempt.get(key))
        for key in projected_attempt.keys() | rebuilt_attempt.keys()
        if projected_attempt.get(key) != rebuilt_attempt.get(key)
    }
    assert not differences, differences
    assert cache_authority_binding(projected) == cache_authority_binding(rebuilt)
    assert events == full


async def _exercise_checkpoint_round_trip(harness: Harness, case: str) -> None:
    events, full_projection = await _run_case(harness, case)
    checkpoint = projection_to_checkpoint(full_projection)
    assert projection_from_checkpoint(checkpoint) == full_projection

    async with harness.session_factory() as session:
        store = GraphEventStore(session)
        projection_events = await store.read_run_projection(harness.run_id)
        before_tail = build_projection(projection_events[:-1])
        await store.persist_projection_snapshot(
            harness.run_id,
            before_tail,
            events[-2].position if len(events) > 1 else 0,
        )
        await session.commit()
        loaded, tail, position = await store.load_projection_with_tail(harness.run_id)
    assert [event.event_id for event in tail] == [events[-1].event_id]
    assert position == events[-1].position
    assert loaded == full_projection

    attempt = execution_attempts_view(projection_from_checkpoint(checkpoint))[harness.execution_id]
    all_roots = {
        (root.path, root.kind)
        for roots in (
            attempt.baseline_cache_roots,
            attempt.staged_cache_roots,
            attempt.final_cache_roots,
            attempt.recovery_observed_cache_roots,
        )
        for root in roots
        if isinstance(root, RunnerCacheRoot)
    }
    assert _typed_root_set(attempt.recovery_authorized_cache_roots) == all_roots
    expected_evidence = {
        "baseline": ({"z-cache/entry"}, set(), set(), set()),
        "stage": (set(), {"z-cache/entry"}, set(), set()),
        "final": (set(), set(), {"z-cache/entry"}, {"z-cache/entry"}),
        "recovery": (set(), set(), set(), {"a-cache/entry"}),
    }[case]
    assert tuple(item.path for item in attempt.baseline_cache_status_evidence) == tuple(
        sorted(expected_evidence[0])
    )
    assert tuple(item.path for item in attempt.staged_cache_status_evidence) == tuple(
        sorted(expected_evidence[1])
    )
    assert tuple(item.path for item in attempt.final_cache_status_evidence) == tuple(
        sorted(expected_evidence[2])
    )
    assert tuple(item.path for item in attempt.recovery_cache_status_evidence) == tuple(
        sorted(expected_evidence[3])
    )


@pytest.mark.asyncio
async def test_boundary_authority_schema_persists_root_and_evidence(harness: Harness) -> None:
    await _exercise_boundary_authority_schema(harness, "baseline")


@pytest.mark.asyncio
async def test_projection_mode_sql_replay_matches_authority_history(harness: Harness) -> None:
    await _exercise_projection_mode_sql_replay(harness, "baseline")


@pytest.mark.asyncio
async def test_checkpoint_round_trip_and_tail_replay_retain_root_evidence(
    harness: Harness,
) -> None:
    await _exercise_checkpoint_round_trip(harness, "baseline")


@pytest.mark.asyncio
async def test_z_root_then_a_root_is_canonicalized_in_authorized_recovery_order(
    harness: Harness,
) -> None:
    await _trusted_boundary_command(
        harness,
        "record_runner_baseline",
        _baseline_payload(harness, ["z-cache"], [_evidence("z-cache")]),
    )
    stage = _stage_payload(harness, ["a-cache"], [_evidence("a-cache")])
    stage["observed_graph_position"] = await harness.controller.current_position(harness.run_id)
    await _trusted_boundary_command(harness, "stage_runner_submission", stage)
    final = _final_payload(harness, [], [])
    result = await _witness_then_finalize(harness, final)
    assert [event.event_type for event in result.events] == [
        "runner_completion_witnessed",
        "runner_boundary_mismatch",
        "runner_recovery_requested",
    ]
    for event in result.events:
        assert (
            not {
                "cache_roots",
                "observed_cache_roots",
                "authorized_cache_roots",
                "legacy_cache_root_paths",
            }
            & event.payload.keys()
        )
    attempt = execution_attempts_view(await harness.controller.read_projection(harness.run_id))[
        harness.execution_id
    ]
    assert _typed_root_set(attempt.recovery_authorized_cache_roots) == {
        ("a-cache", "ignored"),
        ("z-cache", "ignored"),
    }


@pytest.mark.asyncio
async def test_unauthorized_later_kind_cannot_replace_accepted_root_authority(
    harness: Harness,
) -> None:
    await _trusted_boundary_command(
        harness,
        "record_runner_baseline",
        _baseline_payload(harness, ["z-cache"], [_evidence("z-cache")]),
    )
    stage = _stage_payload(harness, [], [])
    stage["observed_graph_position"] = await harness.controller.current_position(harness.run_id)
    await _trusted_boundary_command(harness, "stage_runner_submission", stage)
    final = _final_payload(harness, [], [])
    final["cache_roots"] = [{"path": "z-cache", "kind": "untracked"}]
    final["cache_status_evidence"] = [{"path": "z-cache/entry", "kind": "untracked"}]
    final["boundary_hash"] = boundary_manifest_hash(
        OID,
        final["boundary_entries"],
        final["cache_status_evidence"],
        harness.authority_hash,
    )

    result = await _witness_then_finalize(harness, final)

    assert [event.event_type for event in result.events] == ["command_rejected"]
    assert "not authorized for untracked" in result.events[0].payload["reason"]
    assert not any(
        event.event_type == "runner_recovery_requested" for event in await _events(harness)
    )


@pytest.mark.asyncio
async def test_recovery_duplicate_changed_observed_authorized_legacy_and_evidence_conflict(
    harness: Harness,
) -> None:
    events, projection = await _run_case(harness, "recovery")
    request = next(event for event in events if event.event_type == "runner_recovery_requested")
    original_evidence = [_evidence("a-cache")]
    changes: dict[str, dict[str, object]] = {
        "observed": {
            "observed_cache_roots": [_root("z-cache")],
            "authorized_cache_roots": [_root("z-cache")],
            "cache_status_evidence": [_evidence("z-cache")],
            "final_boundary_hash": _boundary_hash(
                harness, [_entry(changed=True)], [_evidence("z-cache")]
            ),
        },
        "authorized": {"authorized_cache_roots": []},
        "legacy": {"legacy_cache_root_paths": ["legacy-cache"]},
        "evidence": {
            "cache_status_evidence": [_evidence("a-cache/other")],
            "final_boundary_hash": _boundary_hash(
                harness, [_entry(changed=True)], [_evidence("a-cache/other")]
            ),
        },
    }
    assert original_evidence == request.payload["cache_status_evidence"]
    for field, update in changes.items():
        duplicate = request.model_copy(
            update={
                "event_id": f"changed-{field}",
                "position": request.position + 1,
                "payload": {**request.payload, **update},
            }
        )
        with pytest.raises(ProjectionReplayConflictError, match="root authority|duplicate|cache"):
            reduce_event(projection, duplicate)


@pytest.mark.asyncio
async def test_boundary_mismatch_changed_authorized_and_legacy_conflict(
    harness: Harness,
) -> None:
    events, projection = await _run_case(harness, "final")
    mismatch = next(event for event in events if event.event_type == "runner_boundary_mismatch")
    staged_projection = build_projection(events[: events.index(mismatch)])
    for field, value in (
        ("authorized_cache_roots", []),
        ("legacy_cache_root_paths", ["legacy-cache"]),
    ):
        duplicate = mismatch.model_copy(
            update={
                "event_id": f"mismatch-{field}",
                "position": mismatch.position + 1,
                "payload": {**mismatch.payload, field: value},
            }
        )
        with pytest.raises(ProjectionReplayConflictError, match="root authority"):
            reduce_event(staged_projection, duplicate)


@pytest.mark.asyncio
async def test_generic_controller_rejects_all_managed_boundary_commands_without_appending(
    harness: Harness,
) -> None:
    before = await harness.controller.current_position(harness.run_id)
    before_events = await _events(harness)
    for command_type in sorted(MANAGED_BOUNDARY_COMMANDS):
        with pytest.raises(ValueError, match="runtime capability"):
            await harness.controller.handle_command(harness.run_id, before, command_type, {})
        assert await harness.controller.current_position(harness.run_id) == before
    assert await _events(harness) == before_events


@pytest.mark.asyncio
async def test_foreign_runtime_boundary_capability_is_rejected(
    harness: Harness, tmp_path: Path
) -> None:
    other_controller, _ = build_graph_runtime(
        harness.session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        worktree_path=tmp_path / "other-worktree",
        artifact_store=FilesystemArtifactStore(tmp_path / "other-artifacts"),
        runner_type=AgentRunnerType.CLI_SUBPROCESS,
    )
    foreign_capability = other_controller._runtime_boundary_capability  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError, match="invalid runtime boundary capability"):
        await harness.controller.handle_runtime_boundary_command(
            harness.run_id,
            await harness.controller.current_position(harness.run_id),
            "record_runner_baseline",
            {},
            foreign_capability,
        )


@pytest.mark.asyncio
async def test_build_graph_runtime_shares_opaque_capability_for_trusted_boundary_write(
    harness: Harness,
) -> None:
    result = await _trusted_boundary_command(
        harness,
        "record_runner_baseline",
        _baseline_payload(harness, [], []),
    )
    assert [event.event_type for event in result.events] == ["runner_baseline_recorded"]
    assert await harness.controller.current_position(harness.run_id) == result.projection_position


def test_graph_api_enumeration_has_no_arbitrary_managed_boundary_ingress() -> None:
    app = create_app(db_path=":memory:", routine_dirs=[])
    graph_routes = [
        route for route in app.routes if isinstance(route, APIRoute) and "/graph" in route.path
    ]
    paths = sorted(route.path for route in graph_routes)
    assert set(paths) == {
        "/api/runs/{run_id}/graph",
        "/api/runs/{run_id}/graph/crash-barrier",
        "/api/runs/{run_id}/graph/decisions",
        "/api/runs/{run_id}/graph/events",
        "/api/runs/{run_id}/graph/file-state",
        "/api/runs/{run_id}/graph/final-blockers",
        "/api/runs/{run_id}/graph/health",
        "/api/runs/{run_id}/graph/nodes/{node_id}",
        "/api/runs/{run_id}/graph/patch",
        "/api/runs/{run_id}/graph/patches",
        "/api/runs/{run_id}/graph/regions",
        "/api/runs/{run_id}/graph/runtime-health",
        "/api/runs/{run_id}/graph/runtime-health/resolve-validation-environment-blockage",
        "/api/runs/{run_id}/graph/scheduler",
        "/api/runs/{run_id}/graph/topology",
    }
    post_paths = {
        route.path
        for route in graph_routes
        if route.methods is not None and "POST" in route.methods
    }
    assert post_paths == {
        "/api/runs/{run_id}/graph/decisions",
        "/api/runs/{run_id}/graph/patch",
        "/api/runs/{run_id}/graph/runtime-health/resolve-validation-environment-blockage",
    }
    forbidden_names = {
        "command_type",
        "capability",
        "runtime_boundary_capability",
    }
    for route in graph_routes:
        body_models = [parameter.type_ for parameter in route.dependant.body_params]
        for model in body_models:
            if isinstance(model, type) and issubclass(model, BaseModel):
                assert not forbidden_names.intersection(model.model_fields)


def _historical_event(event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"historical-{event_type}",
        run_id="historical",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def _historical_prefix() -> list[EventEnvelope]:
    return [
        _historical_event(
            "node_created",
            {"node_id": "node", "kind": "worker", "state": "running"},
        ),
        _historical_event(
            "lease_granted",
            {
                "lease_id": "lease",
                "node_id": "node",
                "generation": 1,
                "execution_id": "execution",
                "base_snapshot_id": BASELINE_SNAPSHOT,
            },
        ),
    ]


def _historical_baseline(root: object) -> EventEnvelope:
    entries: list[dict[str, str]] = []
    return _historical_event(
        "runner_baseline_recorded",
        {
            "execution_id": "execution",
            "node_id": "node",
            "lease_id": "lease",
            "lease_generation": 1,
            "baseline_snapshot_id": BASELINE_SNAPSHOT,
            "baseline_tree_sha": OID,
            "entries": entries,
            "boundary_hash": boundary_manifest_hash(OID, entries),
            "cache_roots": [root],
        },
    )


def _historical_stage(root: object) -> EventEnvelope:
    entries: list[dict[str, str]] = []
    payload = {
        "execution_id": "execution",
        "node_id": "node",
        "lease_id": "lease",
        "lease_generation": 1,
        "idempotency_key": "historical-submit",
        "payload": {},
        "payload_hash": "sha256:" + hashlib.sha256(b"{}").hexdigest(),
        "staged_snapshot_id": STAGED_SNAPSHOT,
        "staged_tree_sha": OID,
        "boundary_hash": boundary_manifest_hash(OID, entries),
        "boundary_entries": entries,
        "base_snapshot_id": BASELINE_SNAPSHOT,
        "observed_graph_position": 3,
        "is_mutating": False,
        "complete_node": False,
        "new_state": "completed",
        "cache_roots": [root],
    }
    return _historical_event("runner_submission_staged", payload)


async def _append_history(
    session_factory: async_sessionmaker[AsyncSession], events: list[EventEnvelope]
) -> list[EventEnvelope]:
    async with session_factory() as session:
        async with session.begin():
            return await GraphEventStore(session).append_events("historical", 0, events)


@pytest.mark.asyncio
async def test_historical_string_root_replay_survives_projection_mode_sql_read() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    root = ".pytest_cache"
    events = [*_historical_prefix(), _historical_baseline(root), _historical_stage(root)]
    entries: list[dict[str, str]] = []
    events.append(
        _historical_event(
            "runner_execution_finalized",
            {
                "execution_id": "execution",
                "node_id": "node",
                "lease_id": "lease",
                "lease_generation": 1,
                "final_snapshot_id": FINAL_SNAPSHOT,
                "final_tree_sha": OID,
                "boundary_hash": boundary_manifest_hash(OID, entries),
                "boundary_entries": entries,
                "cache_roots": [root],
            },
        )
    )
    stored = await _append_history(session_factory, events)
    async with session_factory() as session:
        store = GraphEventStore(session)
        full = await store.read_run("historical")
        projected = await store.read_run_projection("historical")
    assert build_projection(projected) == build_projection(full)
    attempt = execution_attempts_view(build_projection(stored))["execution"]
    assert attempt.cache_roots == (root,)
    assert thaw_json(attempt.payload) == {}
    assert attempt.payload_ref is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_earlier_typed_aggregate_replay_without_observed_root_schema() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    root = _root(".pytest_cache")
    prefix = [*_historical_prefix(), _historical_baseline(root), _historical_stage(root)]
    entries: list[dict[str, str]] = []
    prefix.append(
        _historical_event(
            "runner_recovery_requested",
            {
                "execution_id": "execution",
                "recovery_id": "recovery:execution:runner_died",
                "node_id": "node",
                "lease_id": "lease",
                "lease_generation": 1,
                "reason": "runner_died",
                "max_attempts": 3,
                "baseline_snapshot_id": BASELINE_SNAPSHOT,
                "baseline_tree_sha": OID,
                "final_tree_sha": OID,
                "final_boundary_hash": boundary_manifest_hash(OID, entries),
                "final_boundary_entries": entries,
                "cache_roots": [root],
                "paths": [".pytest_cache"],
            },
        )
    )
    stored = await _append_history(session_factory, prefix)
    async with session_factory() as session:
        projected = await GraphEventStore(session).read_run_projection("historical")
    attempt = execution_attempts_view(build_projection(projected))["execution"]
    assert _typed_root_set(attempt.recovery_observed_cache_roots) == {(".pytest_cache", "ignored")}
    assert attempt.recovery_authorized_cache_roots == (
        RunnerCacheRoot(path=".pytest_cache", kind="ignored"),
    )
    assert attempt.legacy_cache_root_paths == ()
    assert build_projection(projected) == build_projection(stored)
    await engine.dispose()


@pytest.mark.asyncio
async def test_noncanonical_recovery_roots_are_canonical_across_durable_replays(
    harness: Harness,
) -> None:
    await _trusted_boundary_command(
        harness,
        "record_runner_baseline",
        _baseline_payload(harness, [], []),
    )
    stage = _stage_payload(harness, [], [])
    stage["observed_graph_position"] = await harness.controller.current_position(harness.run_id)
    await _trusted_boundary_command(harness, "stage_runner_submission", stage)

    entries = [_entry()]
    evidence = [_evidence("z-cache"), _evidence("a-cache")]
    recovery_event = _historical_event(
        "runner_recovery_requested",
        {
            **_identity(harness),
            "recovery_id": f"recovery:{harness.execution_id}:runner_died",
            "reason": "runner_died",
            "max_attempts": 3,
            "baseline_snapshot_id": BASELINE_SNAPSHOT,
            "baseline_tree_sha": OID,
            "final_tree_sha": OID,
            "final_boundary_hash": _boundary_hash(harness, entries, evidence),
            "final_boundary_entries": entries,
            "cache_authority_hash": harness.authority_hash,
            "observed_cache_roots": [_root("z-cache"), _root("a-cache")],
            "authorized_cache_roots": [_root("z-cache"), _root("a-cache")],
            "cache_status_evidence": evidence,
            "paths": ["a-cache", "z-cache"],
        },
    )
    before_recovery = await _events(harness)
    async with harness.session_factory() as session:
        async with session.begin():
            stored_recovery = await GraphEventStore(session).append_events(
                harness.run_id,
                await harness.controller.current_position(harness.run_id),
                [recovery_event],
            )

    stored = [*before_recovery, *stored_recovery]
    async with harness.session_factory() as session:
        store = GraphEventStore(session)
        full = await store.read_run(harness.run_id)
        projected = await store.read_run_projection(harness.run_id)

    expected = (
        RunnerCacheRoot(path="a-cache", kind="ignored"),
        RunnerCacheRoot(path="z-cache", kind="ignored"),
    )
    for replay in (stored, full, projected):
        attempt = execution_attempts_view(build_projection(replay))[harness.execution_id]
        assert attempt.recovery_observed_cache_roots == expected
        assert attempt.recovery_authorized_cache_roots == expected

    checkpoint = projection_to_checkpoint(build_projection(full))
    checkpoint_attempt = execution_attempts_view(projection_from_checkpoint(checkpoint))[
        harness.execution_id
    ]
    assert checkpoint_attempt.recovery_observed_cache_roots == expected
    assert checkpoint_attempt.recovery_authorized_cache_roots == expected
