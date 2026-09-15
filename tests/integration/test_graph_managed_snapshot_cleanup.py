"""Durable, real-Git coverage for managed runner snapshot cleanup.

These tests intentionally use the production controller, SQLite outbox, dispatcher,
and dispatch executor.  In particular, the crash cases reproduce the durable
boundary by doing the completed Git operation before a fresh dispatcher redelivers
the same outbox intent; they do not replace production collaborators.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, RoutineConfig
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.git import WorktreeError, delete_snapshot_ref, snapshot
from orchestrator.graph import (
    boundary_manifest_hash,
    cache_authority_binding,
    execution_attempts_view,
    project_final_invariant_blockers,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    OutboxItem,
    StaticGraphAgentFactory,
    recover,
    reconcile_runtime,
    seed_run,
)

pytestmark = pytest.mark.slow


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


@dataclass(frozen=True)
class ManagedFixture:
    run_id: str
    repo: Path
    controller: GraphController
    clock: FixedClock
    baseline: object
    staged: object
    final: object
    execution_id: str
    recovery_item: OutboxItem | None


@pytest.fixture
async def managed_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "managed-cleanup.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_finalization_creates_and_dispatches_exact_managed_cleanup_rows(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "final-cleanup", mismatch=False)

    cleanups = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    assert [row.payload["snapshot_role"] for row in cleanups] == ["baseline", "staged", "final"]
    assert all(row.status == "pending" for row in cleanups)

    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    completed = await dispatcher.dispatch_pending(run_id=fixture.run_id)

    assert len(completed) == 3, [
        (row.status, row.last_error)
        for row in await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    ]
    assert all(
        not _ref_exists(fixture.repo, item.ref)
        for item in (fixture.baseline, fixture.staged, fixture.final)
    )
    assert (await _event_types(sessions, fixture.run_id)).count("cleanup_applied") == 3
    assert not [
        blocker
        for blocker in project_final_invariant_blockers(
            await _events(sessions, fixture.run_id),
            projection=await fixture.controller.read_projection(fixture.run_id),
        )
        if blocker["kind"] == "pending_managed_snapshot_cleanup"
    ]


@pytest.mark.asyncio
async def test_mismatch_restores_before_cleanup_and_includes_recovery_ref(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "mismatch-cleanup", mismatch=True)
    assert fixture.recovery_item is not None
    assert _ref_exists(fixture.repo, fixture.baseline.ref)

    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    assert _ref_exists(fixture.repo, fixture.baseline.ref) is True

    cleanup_rows = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    assert [row.payload["snapshot_role"] for row in cleanup_rows] == [
        "baseline",
        "final",
    ]
    assert _ref_exists(fixture.repo, fixture.staged.ref)
    await dispatcher.dispatch_pending(run_id=fixture.run_id)
    assert all(not _ref_exists(fixture.repo, row.payload["snapshot_ref"]) for row in cleanup_rows)


@pytest.mark.asyncio
async def test_terminal_startup_reconciles_owned_recovery_without_agent_retry(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "terminal-cleanup", mismatch=True)
    assert fixture.recovery_item is not None
    await _command(fixture.controller, fixture.run_id, "cancel")

    report = await recover(
        sessions, _dispatcher(sessions, fixture, tmp_path), run_id=fixture.run_id
    )

    assert {item.kind for item in report.redispatched} == {"runner_recovery"}
    await _dispatcher(sessions, fixture, tmp_path).dispatch_pending(
        run_id=fixture.run_id,
        allowed_kinds=frozenset({"snapshot_cleanup"}),
    )
    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    assert not any(
        _ref_exists(fixture.repo, ref)
        for ref in _managed_refs(await _rows(sessions, fixture.run_id, "snapshot_cleanup"))
    )
    agent_rows = await _rows(sessions, fixture.run_id, "agent_dispatch")
    assert all(row.status == "completed" for row in agent_rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["baseline", "submission"])
async def test_terminal_cancellation_before_recovery_request_converges_in_one_startup_reconcile(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
    phase: str,
) -> None:
    """A terminal owner restores and drains its refs without reviving an agent."""
    _, sessions = managed_db
    fixture = await _managed_fixture(
        sessions,
        tmp_path,
        f"terminal-before-recovery-{phase}",
        mismatch=False,
        stop_after_baseline=phase == "baseline",
        stop_after_stage=phase == "submission",
    )
    if phase == "baseline":
        assert (
            delete_snapshot_ref(
                fixture.repo,
                str(fixture.baseline.id),
                expected_ref=str(fixture.baseline.ref),
                expected_tree_sha=str(fixture.baseline.tree_sha),
                expected_commit_sha=str(fixture.baseline.commit_sha),
            )
            is True
        )
    (fixture.repo / "README.md").write_text("cancelled execution residue\n")
    canary_ref = f"refs/orchestrator/snapshots/cancellation-owner-canary-{phase}"
    _git(fixture.repo, ["update-ref", canary_ref, fixture.baseline.commit_sha])
    await _command(fixture.controller, fixture.run_id, "cancel")
    await _command(fixture.controller, fixture.run_id, "cancel")
    dispatcher = _dispatcher(sessions, fixture, tmp_path)

    report = await recover(sessions, dispatcher, run_id=fixture.run_id)
    assert report.owned_attempts == [
        {"run_id": fixture.run_id, "execution_id": fixture.execution_id}
    ]
    await reconcile_runtime(
        fixture.controller, _executor(sessions, fixture, tmp_path), report, dispatcher
    )
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id,
        allowed_kinds=frozenset({"snapshot_cleanup"}),
    )
    events = await _events(sessions, fixture.run_id)
    event_types = [event.event_type for event in events]
    assert "runner_recovery_completed" in event_types, [
        event.payload for event in events if event.event_type == "command_rejected"
    ]

    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    cleanup_rows = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    assert cleanup_rows and all(row.status == "completed" for row in cleanup_rows)
    assert not any(_ref_exists(fixture.repo, ref) for ref in _managed_refs(cleanup_rows))
    assert _ref_exists(fixture.repo, canary_ref)
    assert all(
        row.status != "pending" for row in await _rows(sessions, fixture.run_id, "agent_dispatch")
    )


@pytest.mark.asyncio
async def test_duplicate_delivery_and_crash_after_delete_are_idempotent(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "duplicate-cleanup", mismatch=False)
    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    rows = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    first = rows[0]
    assert (
        delete_snapshot_ref(
            fixture.repo,
            str(first.payload["snapshot_id"]),
            expected_ref=str(first.payload["snapshot_ref"]),
            expected_tree_sha=str(first.payload["tree_sha"]),
            expected_commit_sha=str(first.payload["commit_sha"]),
        )
        is True
    )

    await dispatcher.dispatch_pending(run_id=fixture.run_id, limit=1)
    await dispatcher.dispatch_pending(run_id=fixture.run_id, limit=1)
    assert (await _event_types(sessions, fixture.run_id)).count("cleanup_applied") == 2

    # A completed row redelivered after an acknowledgement crash has no side effect.
    await _set_status(sessions, first.outbox_id, "pending")
    await dispatcher.dispatch_pending(run_id=fixture.run_id, limit=1)
    assert (await _event_types(sessions, fixture.run_id)).count("cleanup_applied") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["wrong-tree", "wrong-commit", "same-tree-other-commit"])
async def test_changed_owned_ref_fails_safely_and_remains_retryable(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path, mutation: str
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, f"safe-{mutation}", mismatch=False)
    row = (await _rows(sessions, fixture.run_id, "snapshot_cleanup"))[0]
    _replace_ref(fixture.repo, str(row.payload["snapshot_ref"]), mutation)
    dispatcher = _dispatcher(sessions, fixture, tmp_path)

    assert await dispatcher.dispatch_pending(run_id=fixture.run_id, limit=1) == []
    retried = await _row(sessions, row.outbox_id)
    assert retried.status == "pending"
    assert retried.last_error is not None
    assert _ref_exists(fixture.repo, str(row.payload["snapshot_ref"]))
    _git(
        fixture.repo,
        ["update-ref", str(row.payload["snapshot_ref"]), fixture.baseline.commit_sha],
    )
    fixture.clock.advance(2)
    await dispatcher.dispatch_pending(run_id=fixture.run_id)
    assert not any(
        _ref_exists(fixture.repo, ref)
        for ref in _managed_refs(await _rows(sessions, fixture.run_id, "snapshot_cleanup"))
    )


@pytest.mark.asyncio
async def test_wrong_named_ref_is_rejected_without_deleting_owned_ref(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "wrong-name", mismatch=False)
    row = (await _rows(sessions, fixture.run_id, "snapshot_cleanup"))[0]
    executor = _executor(sessions, fixture, tmp_path)
    payload = {**row.payload, "snapshot_ref": "refs/orchestrator/snapshots/not-the-owned-id"}
    item = _item(row)

    with pytest.raises(WorktreeError, match="ref does not match"):
        await executor._dispatch_managed_snapshot_cleanup(item, payload)
    assert _ref_exists(fixture.repo, str(row.payload["snapshot_ref"]))


@pytest.mark.asyncio
async def test_distinct_refs_to_same_commit_are_deleted_independently(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "same-commit", mismatch=False)
    assert fixture.staged.commit_sha == fixture.final.commit_sha
    await _dispatcher(sessions, fixture, tmp_path).dispatch_pending(run_id=fixture.run_id)
    assert not _ref_exists(fixture.repo, fixture.staged.ref)
    assert not _ref_exists(fixture.repo, fixture.final.ref)


@pytest.mark.asyncio
async def test_startup_requeues_failed_cleanup_once_but_never_agent_dispatch(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "requeue-cleanup", mismatch=False)
    cleanup, *_ = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    agent, *_ = await _rows(sessions, fixture.run_id, "agent_dispatch")
    await _set_failed(sessions, cleanup.outbox_id, "retained cleanup error")
    await _set_failed(sessions, agent.outbox_id, "agent must not restart")
    dispatcher = _dispatcher(sessions, fixture, tmp_path)

    await dispatcher.requeue_failed_snapshot_cleanups_for_startup(run_id=fixture.run_id)
    await dispatcher.requeue_failed_snapshot_cleanups_for_startup(run_id=fixture.run_id)
    cleanup_after, agent_after = (
        await _row(sessions, cleanup.outbox_id),
        await _row(sessions, agent.outbox_id),
    )
    assert (
        cleanup_after.status == "pending" and cleanup_after.last_error == "retained cleanup error"
    )
    assert agent_after.status == "failed" and agent_after.last_error == "agent must not restart"
    assert (await _event_types(sessions, fixture.run_id)).count("outbox_requeued") == 1


@pytest.mark.asyncio
async def test_terminal_failed_cleanup_requeues_per_startup_epoch_and_preserves_audit(
    managed_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = managed_db
    fixture = await _managed_fixture(sessions, tmp_path, "terminal-cleanup-epochs", mismatch=False)
    cleanup, *_ = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    agent, *_ = await _rows(sessions, fixture.run_id, "agent_dispatch")
    _replace_ref(fixture.repo, str(cleanup.payload["snapshot_ref"]), "wrong-commit")
    await _set_failed(sessions, cleanup.outbox_id, "first delivery epoch")
    await _set_failed(sessions, agent.outbox_id, "agent must not restart")
    await _command(fixture.controller, fixture.run_id, "cancel")
    await _command(fixture.controller, fixture.run_id, "cancel")
    dispatcher = OutboxDispatcher(
        sessions,
        _executor(sessions, fixture, tmp_path),
        fixture.clock,
        max_attempts=1,
        retry_jitter_seconds=0,
    )

    first = await recover(sessions, dispatcher, run_id=fixture.run_id)
    after_first = await _row(sessions, cleanup.outbox_id)
    assert [item.outbox_id for item in first.redispatched] != [cleanup.outbox_id]
    assert after_first.status == "failed"
    assert after_first.last_error is not None and "commit does not match" in after_first.last_error
    assert (await _row(sessions, agent.outbox_id)).status == "failed"

    _git(
        fixture.repo,
        ["update-ref", str(cleanup.payload["snapshot_ref"]), str(cleanup.payload["commit_sha"])],
    )
    second = await recover(sessions, dispatcher, run_id=fixture.run_id)
    after_second = await _row(sessions, cleanup.outbox_id)
    audits = [
        event
        for event in await _events(sessions, fixture.run_id)
        if event.event_type == "outbox_requeued" and event.payload["outbox_id"] == cleanup.outbox_id
    ]

    assert any(item.outbox_id == cleanup.outbox_id for item in second.redispatched)
    assert after_second.status == "completed"
    assert len(audits) == 2
    assert audits[0].payload["previous_last_error"] == "first delivery epoch"
    assert audits[1].payload["previous_last_error"] == after_first.last_error
    assert (await _row(sessions, agent.outbox_id)).status == "failed"


async def _managed_fixture(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    run_id: str,
    *,
    mismatch: bool,
    stop_after_baseline: bool = False,
    stop_after_stage: bool = False,
) -> ManagedFixture:
    repo = tmp_path / run_id
    _init_repo(repo)
    clock, ids = FixedClock(), SequentialIds()
    await seed_run(sessions, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    await _command(controller, run_id, "accept_run")
    await _command(controller, run_id, "start")
    baseline = snapshot(repo, "baseline", snapshot_id="a" * 32)
    lease = next(
        event.payload
        for event in (
            await _command(
                controller,
                run_id,
                "schedule_tick",
                {"base_snapshot_id": baseline.id, "max_grants": 1, "lease_seconds": 60},
            )
        ).events
        if event.event_type == "lease_granted"
    )
    identity = {
        "execution_id": lease["execution_id"],
        "node_id": lease["node_id"],
        "lease_id": lease["lease_id"],
        "lease_generation": lease["generation"],
    }
    baseline_entries = [_entry("README.md", "clean", "baseline\n")]
    await _command(
        controller,
        run_id,
        "record_runner_baseline",
        {
            **identity,
            "baseline_snapshot_id": baseline.id,
            "baseline_snapshot_ref": baseline.ref,
            "baseline_commit_sha": baseline.commit_sha,
            "baseline_tree_sha": baseline.tree_sha,
            "entries": baseline_entries,
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, baseline_entries),
            "cache_roots": [],
        },
    )
    if stop_after_baseline:
        await _complete_agent_rows(sessions, run_id)
        fixture = ManagedFixture(
            run_id,
            repo,
            controller,
            clock,
            baseline,
            baseline,
            baseline,
            str(identity["execution_id"]),
            None,
        )
        await _finish_snapshot_publications(sessions, fixture, tmp_path)
        return fixture
    (repo / "README.md").write_text("staged\n")
    staged = snapshot(repo, "staged", snapshot_id="b" * 32)
    staged_entries = [_entry("README.md", "modified", "staged\n")]
    await _command(
        controller,
        run_id,
        "stage_runner_submission",
        {
            **identity,
            "base_snapshot_id": baseline.id,
            "observed_graph_position": await controller.current_position(run_id),
            "idempotency_key": f"{run_id}-submit",
            "payload": {},
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": staged.id,
            "staged_snapshot_ref": staged.ref,
            "staged_commit_sha": staged.commit_sha,
            "staged_tree_sha": staged.tree_sha,
            "boundary_hash": boundary_manifest_hash(staged.tree_sha, staged_entries),
            "boundary_entries": staged_entries,
        },
    )
    if stop_after_stage:
        await _complete_agent_rows(sessions, run_id)
        fixture = ManagedFixture(
            run_id,
            repo,
            controller,
            clock,
            baseline,
            staged,
            staged,
            str(identity["execution_id"]),
            None,
        )
        await _finish_snapshot_publications(sessions, fixture, tmp_path)
        return fixture
    if mismatch:
        (repo / "README.md").write_text("final\n")
        (repo / "created.txt").write_text("created\n")
    final = snapshot(repo, "final", snapshot_id="c" * 32)
    final_entries = (
        [
            _entry("README.md", "modified", "final\n"),
            _entry("created.txt", "untracked", "created\n"),
        ]
        if mismatch
        else staged_entries
    )
    final_payload = {
        **identity,
        "final_snapshot_id": final.id,
        "final_snapshot_ref": final.ref,
        "final_commit_sha": final.commit_sha,
        "final_tree_sha": final.tree_sha,
        "boundary_hash": boundary_manifest_hash(final.tree_sha, final_entries),
        "boundary_entries": final_entries,
    }
    witnessed = await _witness(controller, run_id, final_payload)
    finalized = (
        witnessed
        if mismatch
        else await _command(
            controller,
            run_id,
            "finalize_runner_execution",
            final_payload,
        )
    )
    await _complete_agent_rows(sessions, run_id)
    recovery = next(
        (item for item in finalized.outbox_items if item.kind == "runner_recovery"), None
    )
    fixture = ManagedFixture(
        run_id,
        repo,
        controller,
        clock,
        baseline,
        staged,
        final,
        str(identity["execution_id"]),
        recovery,
    )
    await _finish_snapshot_publications(sessions, fixture, tmp_path)
    return fixture


async def _finish_snapshot_publications(
    sessions: async_sessionmaker[AsyncSession],
    fixture: ManagedFixture,
    tmp_path: Path,
) -> None:
    await _dispatcher(sessions, fixture, tmp_path).dispatch_pending(
        run_id=fixture.run_id,
        allowed_kinds=frozenset({"snapshot_publish"}),
    )


def _executor(
    sessions: async_sessionmaker[AsyncSession], fixture: ManagedFixture, tmp_path: Path
) -> GraphDispatchExecutor:
    return GraphDispatchExecutor(
        sessions,
        fixture.controller,
        StaticGraphAgentFactory(AgentRunnerType.CLI_SUBPROCESS),
        worktree_path=fixture.repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )


def _dispatcher(
    sessions: async_sessionmaker[AsyncSession], fixture: ManagedFixture, tmp_path: Path
) -> OutboxDispatcher:
    return OutboxDispatcher(
        sessions, _executor(sessions, fixture, tmp_path), fixture.clock, retry_jitter_seconds=0
    )


async def _command(
    controller: GraphController, run_id: str, command: str, payload: dict[str, object] | None = None
):
    if command in {
        "record_runner_baseline",
        "stage_runner_submission",
        "witness_runner_completion",
        "finalize_runner_execution",
        "request_runner_recovery",
    }:
        payload = dict(payload or {})
        authority_hash = cache_authority_binding(await controller.read_projection(run_id)).hash
        payload.setdefault("cache_authority_hash", authority_hash)
        entries_key = "entries" if command == "record_runner_baseline" else "boundary_entries"
        tree_key = {
            "record_runner_baseline": "baseline_tree_sha",
            "stage_runner_submission": "staged_tree_sha",
            "witness_runner_completion": "final_tree_sha",
            "finalize_runner_execution": "final_tree_sha",
        }.get(command)
        if tree_key is not None and entries_key in payload and tree_key in payload:
            payload["boundary_hash"] = boundary_manifest_hash(
                str(payload[tree_key]),
                payload[entries_key],
                payload.get("cache_status_evidence", []),
                authority_hash,
            )
        return await controller.handle_runtime_boundary_command(
            run_id,
            await controller.current_position(run_id),
            command,
            payload,
            getattr(controller, "_runtime_boundary_capability"),
        )
    return await controller.handle_command(
        run_id, await controller.current_position(run_id), command, payload
    )


async def _witness(
    controller: GraphController,
    run_id: str,
    final_payload: dict[str, object],
):
    attempt = execution_attempts_view(await controller.read_projection(run_id))[
        str(final_payload["execution_id"])
    ]
    return await _command(
        controller,
        run_id,
        "witness_runner_completion",
        {
            **final_payload,
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


async def _rows(
    sessions: async_sessionmaker[AsyncSession], run_id: str, kind: str
) -> list[GraphOutboxModel]:
    async with sessions() as session:
        return list(
            (
                await session.execute(
                    select(GraphOutboxModel)
                    .where(GraphOutboxModel.run_id == run_id, GraphOutboxModel.kind == kind)
                    .order_by(GraphOutboxModel.outbox_id)
                )
            ).scalars()
        )


async def _row(sessions: async_sessionmaker[AsyncSession], outbox_id: int) -> GraphOutboxModel:
    async with sessions() as session:
        row = await session.get(GraphOutboxModel, outbox_id)
        assert row is not None
        return row


async def _event_types(sessions: async_sessionmaker[AsyncSession], run_id: str) -> list[str]:
    return [event.event_type for event in await _events(sessions, run_id)]


async def _events(sessions: async_sessionmaker[AsyncSession], run_id: str):
    async with sessions() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _complete_agent_rows(sessions: async_sessionmaker[AsyncSession], run_id: str) -> None:
    async with sessions() as session:
        async with session.begin():
            for row in (
                await session.execute(
                    select(GraphOutboxModel).where(
                        GraphOutboxModel.run_id == run_id, GraphOutboxModel.kind == "agent_dispatch"
                    )
                )
            ).scalars():
                row.status = "completed"


async def _set_status(
    sessions: async_sessionmaker[AsyncSession], outbox_id: int, status: str
) -> None:
    async with sessions() as session:
        async with session.begin():
            row = await session.get(GraphOutboxModel, outbox_id)
            assert row is not None
            row.status = status


async def _set_failed(
    sessions: async_sessionmaker[AsyncSession], outbox_id: int, error: str
) -> None:
    async with sessions() as session:
        async with session.begin():
            row = await session.get(GraphOutboxModel, outbox_id)
            assert row is not None
            row.status, row.last_error, row.attempts = "failed", error, 3


def _item(row: GraphOutboxModel) -> OutboxItem:
    return OutboxItem(
        row.outbox_id,
        row.event_id,
        row.run_id,
        row.kind,
        row.payload,
        row.status,
        row.attempts,
        row.created_at,
        row.updated_at,
        row.next_attempt_at,
        row.last_error,
    )


def _entry(path: str, status: str, contents: str) -> dict[str, str]:
    return {
        "path": path,
        "kind": "tracked",
        "status": status,
        "fingerprint": f"sha256:{hashlib.sha256(contents.encode()).hexdigest()}",
        "file_type": "file",
    }


def _managed_refs(rows: list[GraphOutboxModel]) -> list[str]:
    return [str(row.payload["snapshot_ref"]) for row in rows]


def _replace_ref(repo: Path, ref: str, mutation: str) -> None:
    (repo / "replacement.txt").write_text(mutation + "\n")
    _git(repo, ["add", "replacement.txt"])
    _git(
        repo,
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", mutation],
    )
    replacement = _git(repo, ["rev-parse", "HEAD"])
    if mutation == "same-tree-other-commit":
        original_tree = _git(repo, ["rev-parse", f"{ref}^{{tree}}"])
        replacement = _git(repo, ["commit-tree", original_tree, "-m", "same tree other commit"])
    _git(repo, ["update-ref", ref, replacement])


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "README.md").write_text("baseline\n")
    _git(repo, ["init"])
    _git(repo, ["add", "README.md"])
    _git(
        repo,
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
    )


def _git(repo: Path, args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _ref_exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref], cwd=repo, check=False, timeout=30
        ).returncode
        == 0
    )


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "managed-cleanup",
            "name": "Managed cleanup",
            "steps": [
                {
                    "id": "step",
                    "title": "Step",
                    "tasks": [
                        {
                            "id": "task",
                            "title": "Task",
                            "task_context": "Exercise managed snapshots.",
                            "requirements": [{"id": "req", "desc": "Clean refs."}],
                        }
                    ],
                }
            ],
        }
    )
