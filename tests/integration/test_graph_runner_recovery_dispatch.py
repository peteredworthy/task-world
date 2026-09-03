"""Real durable runner-recovery dispatch coverage.

This harness deliberately builds the boundary history through the controller,
then drives its durable outbox item through the production executor against a
real Git worktree.  It keeps recovery's at-least-once and shared-worktree lock
properties in the same integration proof.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import threading
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.api import create_app
from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.git import (
    GitError,
    SelectiveRestoreResult,
    WorktreeError,
    restore_paths,
    snapshot,
)
from orchestrator.graph import (
    canonical_callback_payload_bytes,
    callback_payload_identity,
    node_states_view,
    EventEnvelope,
    GraphCommandContext,
    boundary_manifest_hash,
    cache_authority_binding,
    execution_attempts_view,
    recovery_proof_hash,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    OutboxItem,
    RecoveryCompletionRejectedError,
    RecoveryEventError,
    RecoveryRestoreError,
    StaticGraphAgentFactory,
    recover,
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


class FailOnceCompletionController(GraphController):
    """Real controller that simulates one process death before durable completion."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fail_completion_once = True

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ):
        if command_type == "complete_runner_recovery" and self._fail_completion_once:
            self._fail_completion_once = False
            raise OSError("simulated process death before recovery completion append")
        return await super().handle_command(
            run_id, expected_position, command_type, payload, context=context
        )


class RejectingCompletionController(GraphController):
    """Routes completion through the real controller with conflicting proof data."""

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ):
        if command_type == "complete_runner_recovery" and payload is not None:
            payload = {**payload, "proof_hash": f"sha256:{'0' * 64}"}
        return await super().handle_command(
            run_id, expected_position, command_type, payload, context=context
        )


class FailingGitRecoveryRestorer:
    def __call__(
        self,
        worktree_path: str | Path,
        snapshot_id: str,
        paths: list[str],
        *,
        expected_tree_sha: str | None = None,
    ) -> SelectiveRestoreResult:
        del worktree_path, snapshot_id, paths, expected_tree_sha
        raise GitError("concrete Git recovery failure")


class FailingWorktreeRecoveryRestorer:
    def __call__(
        self,
        worktree_path: str | Path,
        snapshot_id: str,
        paths: list[str],
        *,
        expected_tree_sha: str | None = None,
    ) -> SelectiveRestoreResult:
        del worktree_path, snapshot_id, paths, expected_tree_sha
        raise WorktreeError("concrete worktree recovery failure")


class DelayedRealRecoveryRestorer:
    """Pause one real Git restore so async-loop and lock behavior is observable."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()
        self.started_at: float | None = None

    def __call__(
        self,
        worktree_path: str | Path,
        snapshot_id: str,
        paths: list[str],
        *,
        expected_tree_sha: str | None = None,
    ) -> SelectiveRestoreResult:
        self.started_at = perf_counter()
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release the delayed real restore")
        try:
            return restore_paths(
                worktree_path,
                snapshot_id,
                paths,
                expected_tree_sha=expected_tree_sha,
            )
        finally:
            self.completed.set()


@dataclass(frozen=True)
class RecoveryFixture:
    controller: GraphController
    repo: Path
    item: OutboxItem
    baseline_snapshot_id: str
    baseline_tree_sha: str
    execution_id: str


@dataclass(frozen=True)
class WitnessedFixture:
    controller: GraphController
    executor: GraphDispatchExecutor
    dispatcher: OutboxDispatcher
    context: GraphDispatchContext
    repo: Path
    execution_id: str
    staged_ref: str


@pytest.fixture
async def recovery_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "runner-recovery.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_runner_recovery_outbox_restores_selectively_is_idempotent_and_holds_worktree_lock(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A boundary mismatch restores only its preimages under the shared lock."""
    _, session_factory = recovery_db
    repo = tmp_path / "repo"
    _init_repo(repo)
    baseline = snapshot(repo, "runner recovery baseline")
    controller, lease = await _active_worker_lease(session_factory, baseline.id)

    node_id = str(lease["node_id"])
    lease_id = str(lease["lease_id"])
    execution_id = str(lease["execution_id"])
    lease_generation = int(lease["generation"])
    baseline_entries = [_entry("README.md", "clean", _fingerprint("baseline\n"))]
    staged = snapshot(repo, "runner recovery staged boundary", snapshot_id="b" * 32)
    await _command(
        controller,
        "runner-recovery",
        "record_runner_baseline",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
            "baseline_snapshot_id": baseline.id,
            "baseline_snapshot_ref": baseline.ref,
            "baseline_commit_sha": baseline.commit_sha,
            "baseline_tree_sha": baseline.tree_sha,
            "entries": baseline_entries,
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, baseline_entries),
            "cache_roots": [],
        },
    )
    await _command(
        controller,
        "runner-recovery",
        "stage_runner_submission",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
            "base_snapshot_id": baseline.id,
            "observed_graph_position": await controller.current_position("runner-recovery"),
            "idempotency_key": "runner-recovery-submit",
            "payload": {},
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": staged.id,
            "staged_snapshot_ref": staged.ref,
            "staged_commit_sha": staged.commit_sha,
            "staged_tree_sha": staged.tree_sha,
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, baseline_entries),
            "boundary_entries": baseline_entries,
        },
    )
    (repo / "README.md").write_text("changed by execution\n")
    (repo / "execution-created.txt").write_text("must be removed\n")
    final = snapshot(repo, "runner recovery mismatched final boundary")
    final_entries = [
        _entry("README.md", "modified", _fingerprint("changed by execution\n")),
        _entry("execution-created.txt", "untracked", _fingerprint("must be removed\n")),
    ]
    mismatch = await _command(
        controller,
        "runner-recovery",
        "finalize_runner_execution",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
            "final_snapshot_id": final.id,
            "final_snapshot_ref": final.ref,
            "final_commit_sha": final.commit_sha,
            "final_tree_sha": final.tree_sha,
            "boundary_hash": boundary_manifest_hash(final.tree_sha, final_entries),
            "boundary_entries": final_entries,
        },
    )
    assert [event.event_type for event in mismatch.events] == [
        "runner_completion_witnessed",
        "runner_boundary_mismatch",
        "runner_recovery_requested",
    ]
    assert [item.kind for item in mismatch.outbox_items] == [
        "snapshot_publish",
        "runner_recovery",
    ]
    recovery_item = mismatch.outbox_items[1]
    assert recovery_item.kind == "runner_recovery"
    assert recovery_item.payload["classification"] == "runner_recovery_pending"
    await _complete_prior_agent_dispatches(session_factory, "runner-recovery")

    shared_lock = asyncio.Lock()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(AgentRunnerType.CLI_SUBPROCESS),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        worktree_execution_lock=shared_lock,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())
    published = await dispatcher.dispatch_pending(
        run_id="runner-recovery", allowed_kinds=frozenset({"snapshot_publish"})
    )
    assert [item.kind for item in published] == ["snapshot_publish", "snapshot_publish"]

    lock_held = asyncio.Event()
    release_lock = asyncio.Event()
    competing_observations: list[tuple[str, bool]] = []

    async def competing_worktree_user() -> None:
        async with shared_lock:
            lock_held.set()
            competing_observations.append(
                ((repo / "README.md").read_text(), (repo / "execution-created.txt").exists())
            )
            await release_lock.wait()
            competing_observations.append(
                ((repo / "README.md").read_text(), (repo / "execution-created.txt").exists())
            )

    competing_task = asyncio.create_task(competing_worktree_user())
    await lock_held.wait()
    dispatch_task = asyncio.create_task(dispatcher.dispatch_pending(run_id="runner-recovery"))
    await _wait_for_outbox_dispatching(session_factory, recovery_item.outbox_id)
    assert competing_observations == [
        ("changed by execution\n", True),
    ]
    assert not any(
        event.event_type == "runner_recovery_completed"
        for event in await _events(session_factory, "runner-recovery")
    )
    release_lock.set()
    await competing_task
    completed_items = await dispatch_task

    assert [item.kind for item in completed_items] == ["runner_recovery"]
    assert completed_items[0].outbox_id == recovery_item.outbox_id
    pending_cleanups = await dispatcher.pending_items(run_id="runner-recovery")
    # The staged candidate remains durable and inspectable after recovery, so
    # only baseline/final transient refs become eligible for cleanup.
    assert [item.kind for item in pending_cleanups] == [
        "snapshot_cleanup",
        "snapshot_cleanup",
    ]
    completed_cleanups = await dispatcher.dispatch_pending(run_id="runner-recovery")
    assert [item.kind for item in completed_cleanups] == [
        "snapshot_cleanup",
        "snapshot_cleanup",
    ]
    assert await dispatcher.pending_items(run_id="runner-recovery") == []
    assert _ref_exists(repo, staged.ref)
    assert competing_observations == [
        ("changed by execution\n", True),
        ("changed by execution\n", True),
    ]
    assert (repo / "README.md").read_text() == "baseline\n"
    assert not (repo / "execution-created.txt").exists()

    events = await _events(session_factory, "runner-recovery")
    completion_events = [
        event for event in events if event.event_type == "runner_recovery_completed"
    ]
    assert len(completion_events) == 1
    completion = completion_events[0]
    recovery_id = str(recovery_item.payload["recovery_id"])
    assert completion.payload == {
        "execution_id": execution_id,
        "recovery_id": recovery_id,
        "node_id": node_id,
        "lease_id": lease_id,
        "lease_generation": lease_generation,
        "baseline_snapshot_id": baseline.id,
        "baseline_tree_sha": baseline.tree_sha,
        "requested_paths": ["README.md", "execution-created.txt"],
        "restored_paths": ["README.md"],
        "removed_paths": ["execution-created.txt"],
        "recovery_scope": "selective",
        "disposition": "restored_boundary_mismatch",
        "proof_hash": recovery_proof_hash(
            execution_id=execution_id,
            recovery_id=recovery_id,
            node_id=node_id,
            lease_id=lease_id,
            lease_generation=lease_generation,
            baseline_snapshot_id=baseline.id,
            baseline_tree_sha=baseline.tree_sha,
            requested_paths=("README.md", "execution-created.txt"),
            restored_paths=("README.md",),
            removed_paths=("execution-created.txt",),
        ),
    }
    attempt = execution_attempts_view(await controller.read_projection("runner-recovery"))[
        execution_id
    ]
    assert attempt.state == "recovered"
    assert attempt.recovery_paths == ("README.md", "execution-created.txt")
    assert attempt.restored_paths == ("README.md",)
    assert attempt.removed_paths == ("execution-created.txt",)
    assert attempt.recovery_proof_hash == completion.payload["proof_hash"]

    lease_revoked = next(
        event
        for event in events
        if event.event_type == "lease_revoked" and event.payload.get("execution_id") == execution_id
    )
    retry_scheduled = next(
        event
        for event in events
        if event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
    )
    ready = next(
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == node_id
        and event.payload.get("new_state") == "ready"
        and event.payload.get("trigger") == "runner_recovery_completed_retry_scheduled"
    )
    assert completion.position < lease_revoked.position < retry_scheduled.position < ready.position
    assert (
        node_states_view(await controller.read_projection("runner-recovery")).get(node_id)
        == "ready"
    )

    filesystem_after_completion = (
        (repo / "README.md").read_bytes(),
        (repo / "execution-created.txt").exists(),
    )
    await executor.dispatch(completed_items[0])
    assert await _events(session_factory, "runner-recovery") == events
    assert ((repo / "README.md").read_bytes(), (repo / "execution-created.txt").exists()) == (
        filesystem_after_completion
    )


@pytest.mark.asyncio
async def test_slow_real_recovery_restore_keeps_product_health_responsive(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    """A real delayed Git restore must not starve the API's sole asyncio loop."""
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(session_factory, tmp_path, "recovery-health")
    restorer = DelayedRealRecoveryRestorer()
    executor = _executor(
        session_factory,
        fixture.controller,
        fixture.repo,
        tmp_path,
        runner_recovery_restorer=restorer,
    )
    app = create_app(db_path=":memory:", routine_dirs=[])

    async def health_after_restore_starts() -> tuple[int, float]:
        while not restorer.started.is_set():
            await asyncio.sleep(0.001)
        assert restorer.started_at is not None
        async with AsyncClient(
            transport=ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.get("/health")
        return response.status_code, perf_counter() - restorer.started_at

    health_task = asyncio.create_task(health_after_restore_starts())
    release_timer = threading.Timer(0.8, restorer.release.set)
    release_timer.start()
    dispatch_task = asyncio.create_task(executor.dispatch(fixture.item))
    try:
        status_code, elapsed = await asyncio.wait_for(health_task, timeout=2)
        assert status_code == 200
        assert elapsed < 0.3
    finally:
        restorer.release.set()
        release_timer.cancel()
    await asyncio.wait_for(dispatch_task, timeout=3)
    assert restorer.completed.is_set()
    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    assert not (fixture.repo / "execution-created.txt").exists()


@pytest.mark.asyncio
async def test_cancelled_recovery_waits_for_real_restore_before_releasing_worktree_lock(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    """Cancellation cannot overlap a later worktree mutation with the restore thread."""
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(session_factory, tmp_path, "recovery-cancel-lock")
    restorer = DelayedRealRecoveryRestorer()
    shared_lock = asyncio.Lock()
    executor = GraphDispatchExecutor(
        session_factory,
        fixture.controller,
        StaticGraphAgentFactory(AgentRunnerType.CLI_SUBPROCESS),
        worktree_path=fixture.repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "cancel-lock-artifacts"),
        worktree_execution_lock=shared_lock,
        runner_recovery_restorer=restorer,
    )

    dispatch_task = asyncio.create_task(executor.dispatch(fixture.item))
    await asyncio.wait_for(asyncio.to_thread(restorer.started.wait), timeout=2)
    dispatch_task.cancel()
    await asyncio.sleep(0.05)
    assert shared_lock.locked()
    assert not dispatch_task.done()

    competitor_entered = asyncio.Event()
    competitor_observations: list[bool] = []

    async def mutate_after_recovery() -> None:
        async with shared_lock:
            competitor_observations.append(restorer.completed.is_set())
            (fixture.repo / "after-recovery.txt").write_text("serialized mutation\n")
            competitor_entered.set()

    competitor = asyncio.create_task(mutate_after_recovery())
    await asyncio.sleep(0.05)
    assert not competitor_entered.is_set()
    assert competitor_observations == []

    restorer.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(dispatch_task, timeout=3)
    await asyncio.wait_for(competitor, timeout=2)

    assert competitor_observations == [True]
    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    assert not (fixture.repo / "execution-created.txt").exists()
    assert (fixture.repo / "after-recovery.txt").read_text() == "serialized mutation\n"


@pytest.mark.asyncio
async def test_runner_recovery_dispatching_outbox_is_redelivered_after_restart(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(session_factory, tmp_path, "recovery-restart")
    await _set_outbox_status(session_factory, fixture.item.outbox_id, "dispatching")
    executor = _executor(session_factory, fixture.controller, fixture.repo, tmp_path)

    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())
    report = await recover(session_factory, dispatcher, run_id="recovery-restart")

    assert [item.kind for item in report.redispatched] == ["runner_recovery"]
    pending_cleanups = await dispatcher.pending_items(run_id="recovery-restart")
    assert [item.kind for item in pending_cleanups] == [
        "snapshot_cleanup",
        "snapshot_cleanup",
    ]
    completed_cleanups = await dispatcher.dispatch_pending(run_id="recovery-restart")
    assert [item.kind for item in completed_cleanups] == [
        "snapshot_cleanup",
        "snapshot_cleanup",
    ]
    assert await dispatcher.pending_items(run_id="recovery-restart") == []
    assert report.redispatched[0].outbox_id == fixture.item.outbox_id
    assert await _outbox_status(session_factory, fixture.item.outbox_id) == "completed"
    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    assert not (fixture.repo / "execution-created.txt").exists()
    assert (
        _event_types(await _events(session_factory, "recovery-restart")).count(
            "runner_recovery_completed"
        )
        == 1
    )


@pytest.mark.asyncio
async def test_runner_recovery_retry_after_completion_append_failure_is_idempotent(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(
        session_factory,
        tmp_path,
        "recovery-completion-retry",
        controller_type=FailOnceCompletionController,
    )
    clock = FixedClock()
    dispatcher = OutboxDispatcher(
        session_factory,
        _executor(session_factory, fixture.controller, fixture.repo, tmp_path),
        clock,
        retry_jitter_seconds=0,
    )

    assert await dispatcher.dispatch_pending(run_id="recovery-completion-retry") == []
    assert (fixture.repo / "README.md").read_text() == "baseline\n"
    assert not (fixture.repo / "execution-created.txt").exists()
    assert not any(
        event.event_type == "runner_recovery_completed"
        for event in await _events(session_factory, "recovery-completion-retry")
    )
    assert await _outbox_status(session_factory, fixture.item.outbox_id) == "pending"

    clock.advance(2)
    await dispatcher.dispatch_pending(run_id="recovery-completion-retry")
    assert await _outbox_status(session_factory, fixture.item.outbox_id) == "completed"
    assert (
        _event_types(await _events(session_factory, "recovery-completion-retry")).count(
            "runner_recovery_completed"
        )
        == 1
    )


@pytest.mark.asyncio
async def test_runner_recovery_wrong_baseline_tree_is_retryable_worktree_error(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(
        session_factory,
        tmp_path,
        "recovery-wrong-tree",
        baseline_tree_sha="a" * 40,
    )
    executor = _executor(session_factory, fixture.controller, fixture.repo, tmp_path)

    with pytest.raises(RecoveryRestoreError) as caught:
        await executor.dispatch(fixture.item)
    assert isinstance(caught.value.__cause__, WorktreeError)
    assert not any(
        event.event_type == "runner_recovery_completed"
        for event in await _events(session_factory, "recovery-wrong-tree")
    )

    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock(), retry_jitter_seconds=0)
    assert await dispatcher.dispatch_pending(run_id="recovery-wrong-tree") == []
    assert await _outbox_status(session_factory, fixture.item.outbox_id) == "pending"


@pytest.mark.asyncio
async def test_runner_recovery_rejects_malformed_or_missing_canonical_request(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, session_factory = recovery_db
    repo = tmp_path / "malformed-recovery"
    _init_repo(repo)
    controller = GraphController(
        session_factory, FixedClock(), SequentialIds(), auto_dispatch=False
    )
    executor = _executor(session_factory, controller, repo, tmp_path)

    missing = _recovery_item(
        "missing-request", "recovery-missing", execution_id="execution-missing"
    )
    with pytest.raises(RecoveryEventError, match="unknown runner_recovery_requested"):
        await executor.dispatch(missing)

    fixture = await _recovery_fixture(session_factory, tmp_path, "malformed-request")
    malformed_payload = dict(fixture.item.payload)
    malformed_payload.pop("node_id")
    malformed = replace(fixture.item, payload=malformed_payload)
    with pytest.raises(RecoveryEventError, match="malformed requested event"):
        await _executor(session_factory, fixture.controller, fixture.repo, tmp_path).dispatch(
            malformed
        )


@pytest.mark.asyncio
async def test_runner_recovery_wraps_real_controller_completion_rejection(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(
        session_factory,
        tmp_path,
        "recovery-completion-rejected",
        controller_type=RejectingCompletionController,
    )

    with pytest.raises(RecoveryCompletionRejectedError, match="recovery proof conflicts"):
        await _executor(session_factory, fixture.controller, fixture.repo, tmp_path).dispatch(
            fixture.item
        )
    assert not any(
        event.event_type == "runner_recovery_completed"
        for event in await _events(session_factory, "recovery-completion-rejected")
    )
    assert any(
        event.event_type == "command_rejected"
        and event.payload.get("command_type") == "complete_runner_recovery"
        for event in await _events(session_factory, "recovery-completion-rejected")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("restorer", "cause_type"),
    [(FailingGitRecoveryRestorer(), GitError), (FailingWorktreeRecoveryRestorer(), WorktreeError)],
)
async def test_runner_recovery_wraps_concrete_restore_failures(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
    restorer: object,
    cause_type: type[GitError],
) -> None:
    _, session_factory = recovery_db
    fixture = await _recovery_fixture(session_factory, tmp_path, f"recovery-{cause_type.__name__}")

    with pytest.raises(RecoveryRestoreError) as caught:
        await _executor(
            session_factory,
            fixture.controller,
            fixture.repo,
            tmp_path,
            runner_recovery_restorer=restorer,
        ).dispatch(fixture.item)
    assert isinstance(caught.value.__cause__, cause_type)
    assert not any(
        event.event_type == "runner_recovery_completed"
        for event in await _events(session_factory, f"recovery-{cause_type.__name__}")
    )


@pytest.mark.asyncio
async def test_runner_recovery_restores_rename_copy_and_file_directory_transition_selectively(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, session_factory = recovery_db
    fixture = await _topology_recovery_fixture(session_factory, tmp_path)

    await OutboxDispatcher(
        session_factory,
        _executor(session_factory, fixture.controller, fixture.repo, tmp_path),
        FixedClock(),
    ).dispatch_pending(run_id="recovery-topology")

    assert (fixture.repo / "renamed-from.txt").read_text() == "rename source\n"
    assert not (fixture.repo / "renamed-to.txt").exists()
    assert (fixture.repo / "copied-source.txt").read_text() == "copy source\n"
    assert not (fixture.repo / "copied-target.txt").exists()
    assert (fixture.repo / "shape").is_file()
    assert (fixture.repo / "shape").read_text() == "a baseline file\n"
    assert (fixture.repo / "unrelated.txt").read_text() == "preserve this external change\n"


@pytest.mark.asyncio
async def test_concurrent_witnessed_finalize_and_recovery_has_one_durable_winner(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    """Production finalization and restart recovery race through one SQLite log."""
    _, session_factory = recovery_db
    fixture = await _witnessed_fixture(session_factory, tmp_path)

    results = await asyncio.gather(
        fixture.executor._finalize_runner_execution(fixture.context),
        fixture.executor._request_runner_recovery(
            fixture.context,
            "runner_died",
            error_detail="concurrent restart observed no process owner",
        ),
        return_exceptions=True,
    )

    events = await _events(session_factory, "recovery-finalize-race")
    finalized = [
        item
        for item in events
        if item.event_type == "runner_execution_finalized"
        and item.payload.get("execution_id") == fixture.execution_id
    ]
    requested = [
        item
        for item in events
        if item.event_type == "runner_recovery_requested"
        and item.payload.get("execution_id") == fixture.execution_id
    ]
    assert (len(finalized), len(requested)) in {(1, 0), (0, 1)}

    if requested:
        await fixture.dispatcher.dispatch_pending(
            run_id="recovery-finalize-race",
            allowed_kinds=frozenset({"runner_recovery"}),
        )
    final_events = await _events(session_factory, "recovery-finalize-race")
    accepted = [
        item
        for item in final_events
        if item.event_type == "callback_accepted"
        and item.payload.get("execution_id") == fixture.execution_id
    ]
    recovered = [
        item
        for item in final_events
        if item.event_type == "runner_recovery_completed"
        and item.payload.get("execution_id") == fixture.execution_id
    ]
    assert (len(finalized), len(accepted), len(recovered)) in {(1, 1, 0), (0, 0, 1)}
    attempt = execution_attempts_view(
        await fixture.controller.read_projection("recovery-finalize-race")
    )[fixture.execution_id]
    assert attempt.state in {"finalized", "recovered"}
    assert attempt.completion_disposition in {
        "finalized_accepted",
        "restored_boundary_mismatch",
    }
    assert sum(not isinstance(item, Exception) for item in results) >= 1
    assert _ref_exists(fixture.repo, fixture.staged_ref)


@pytest.mark.asyncio
async def test_restart_after_finalization_before_outbox_ack_does_not_refinalize(
    recovery_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    """A crash after the atomic append may redeliver effects, never acceptance."""
    _, session_factory = recovery_db
    fixture = await _witnessed_fixture(session_factory, tmp_path)
    await fixture.executor._finalize_runner_execution(fixture.context)
    before = await _events(session_factory, "recovery-finalize-race")
    assert _event_types(before).count("runner_execution_finalized") == 1
    assert _event_types(before).count("callback_accepted") == 1

    pending = await fixture.dispatcher.pending_items(run_id="recovery-finalize-race")
    assert pending
    await _set_outbox_status(session_factory, pending[0].outbox_id, "dispatching")
    restarted_executor = GraphDispatchExecutor(
        session_factory,
        fixture.controller,
        StaticGraphAgentFactory(AgentRunnerType.CLI_SUBPROCESS),
        worktree_path=fixture.repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "race-artifacts"),
    )
    restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, FixedClock())
    report = await recover(
        session_factory,
        restarted_dispatcher,
        run_id="recovery-finalize-race",
    )
    await restarted_executor.reconcile_execution_attempts("recovery-finalize-race")

    after = await _events(session_factory, "recovery-finalize-race")
    assert _event_types(after).count("runner_execution_finalized") == 1
    assert _event_types(after).count("callback_accepted") == 1
    assert not any(
        item.event_type in {"runner_recovery_requested", "runner_recovery_completed"}
        and item.payload.get("execution_id") == fixture.execution_id
        for item in after
    )
    assert any(item.outbox_id == pending[0].outbox_id for item in report.redispatched)


def _executor(
    session_factory: async_sessionmaker[AsyncSession],
    controller: GraphController,
    repo: Path,
    tmp_path: Path,
    *,
    runner_recovery_restorer: object | None = None,
) -> GraphDispatchExecutor:
    kwargs = (
        {}
        if runner_recovery_restorer is None
        else {"runner_recovery_restorer": runner_recovery_restorer}
    )
    return GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(AgentRunnerType.CLI_SUBPROCESS),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        **kwargs,
    )


async def _recovery_fixture(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    run_id: str,
    *,
    baseline_tree_sha: str | None = None,
    controller_type: type[GraphController] = GraphController,
) -> RecoveryFixture:
    repo = tmp_path / run_id
    _init_repo(repo)
    baseline = snapshot(repo, f"{run_id} baseline")
    recorded_tree_sha = baseline_tree_sha or baseline.tree_sha
    controller, lease = await _active_worker_lease(
        session_factory, baseline.id, run_id=run_id, controller_type=controller_type
    )
    node_id = str(lease["node_id"])
    lease_id = str(lease["lease_id"])
    execution_id = str(lease["execution_id"])
    lease_generation = int(lease["generation"])
    baseline_entries = [_entry("README.md", "clean", _fingerprint("baseline\n"))]
    staged = snapshot(repo, f"{run_id} staged", snapshot_id="b" * 31 + "c")
    await _command(
        controller,
        run_id,
        "record_runner_baseline",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
            "baseline_snapshot_id": baseline.id,
            "baseline_snapshot_ref": baseline.ref,
            "baseline_commit_sha": baseline.commit_sha,
            "baseline_tree_sha": recorded_tree_sha,
            "entries": baseline_entries,
            "boundary_hash": boundary_manifest_hash(recorded_tree_sha, baseline_entries),
            "cache_roots": [],
        },
    )
    await _command(
        controller,
        run_id,
        "stage_runner_submission",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
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
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, baseline_entries),
            "boundary_entries": baseline_entries,
        },
    )
    (repo / "README.md").write_text("changed by execution\n")
    (repo / "execution-created.txt").write_text("must be removed\n")
    final = snapshot(repo, f"{run_id} final")
    final_entries = [
        _entry("README.md", "modified", _fingerprint("changed by execution\n")),
        _entry("execution-created.txt", "untracked", _fingerprint("must be removed\n")),
    ]
    result = await _command(
        controller,
        run_id,
        "finalize_runner_execution",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
            "final_snapshot_id": final.id,
            "final_snapshot_ref": final.ref,
            "final_commit_sha": final.commit_sha,
            "final_tree_sha": final.tree_sha,
            "boundary_hash": boundary_manifest_hash(final.tree_sha, final_entries),
            "boundary_entries": final_entries,
        },
    )
    item = next(item for item in result.outbox_items if item.kind == "runner_recovery")
    await _complete_prior_agent_dispatches(session_factory, run_id)
    await OutboxDispatcher(
        session_factory,
        _executor(session_factory, controller, repo, tmp_path),
        FixedClock(),
    ).dispatch_pending(run_id=run_id, allowed_kinds=frozenset({"snapshot_publish"}))
    return RecoveryFixture(
        controller=controller,
        repo=repo,
        item=item,
        baseline_snapshot_id=baseline.id,
        baseline_tree_sha=recorded_tree_sha,
        execution_id=execution_id,
    )


async def _witnessed_fixture(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> WitnessedFixture:
    run_id = "recovery-finalize-race"
    repo = tmp_path / run_id
    _init_repo(repo)
    baseline = snapshot(repo, "race baseline")
    controller, lease = await _active_worker_lease(session_factory, baseline.id, run_id=run_id)
    node_id = str(lease["node_id"])
    lease_id = str(lease["lease_id"])
    execution_id = str(lease["execution_id"])
    generation = int(lease["generation"])
    entries = [_entry("README.md", "clean", _fingerprint("baseline\n"))]
    await _command(
        controller,
        run_id,
        "record_runner_baseline",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": generation,
            "baseline_snapshot_id": baseline.id,
            "baseline_snapshot_ref": baseline.ref,
            "baseline_commit_sha": baseline.commit_sha,
            "baseline_tree_sha": baseline.tree_sha,
            "entries": entries,
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, entries),
            "cache_roots": [],
        },
    )
    staged = snapshot(repo, "race staged", snapshot_id="e" * 32)
    callback_payload: dict[str, object] = {"output_records": []}
    artifact_store = FilesystemArtifactStore(tmp_path / "race-artifacts")
    payload_ref = await artifact_store.put(
        canonical_callback_payload_bytes(callback_payload),
        media_type="application/json",
        encoding="utf-8",
    )
    payload_hash, _ = callback_payload_identity(callback_payload)
    await _command(
        controller,
        run_id,
        "stage_runner_submission",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": generation,
            "base_snapshot_id": baseline.id,
            "observed_graph_position": await controller.current_position(run_id),
            "idempotency_key": "race-submit",
            "payload": callback_payload,
            "payload_ref": payload_ref.model_dump(mode="json"),
            "payload_hash": payload_hash,
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": staged.id,
            "staged_snapshot_ref": staged.ref,
            "staged_commit_sha": staged.commit_sha,
            "staged_tree_sha": staged.tree_sha,
            "boundary_hash": boundary_manifest_hash(staged.tree_sha, entries),
            "boundary_entries": entries,
        },
    )
    final = snapshot(repo, "race final", snapshot_id="f" * 32)
    attempt = execution_attempts_view(await controller.read_projection(run_id))[execution_id]
    await _command(
        controller,
        run_id,
        "witness_runner_completion",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": generation,
            "staged_payload_hash": attempt.payload_hash,
            "staged_payload_size_bytes": attempt.payload_size_bytes,
            "staged_snapshot_id": staged.id,
            "staged_snapshot_ref": staged.ref,
            "staged_commit_sha": staged.commit_sha,
            "staged_tree_sha": staged.tree_sha,
            "staged_boundary_hash": attempt.staged_boundary_hash,
            "runner_return_kind": "successful_return",
            "final_snapshot_id": final.id,
            "final_snapshot_ref": final.ref,
            "final_commit_sha": final.commit_sha,
            "final_tree_sha": final.tree_sha,
            "boundary_hash": boundary_manifest_hash(final.tree_sha, entries),
            "boundary_entries": entries,
        },
    )
    await _complete_prior_agent_dispatches(session_factory, run_id)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(AgentRunnerType.CLI_SUBPROCESS),
        worktree_path=repo,
        artifact_store=artifact_store,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())
    await dispatcher.dispatch_pending(run_id=run_id, allowed_kinds=frozenset({"snapshot_publish"}))
    context = await executor._reattached_execution_context(run_id, attempt)
    return WitnessedFixture(
        controller=controller,
        executor=executor,
        dispatcher=dispatcher,
        context=context,
        repo=repo,
        execution_id=execution_id,
        staged_ref=staged.ref,
    )


async def _topology_recovery_fixture(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> RecoveryFixture:
    run_id = "recovery-topology"
    repo = tmp_path / run_id
    _init_repo(repo)
    for name, contents in {
        "renamed-from.txt": "rename source\n",
        "copied-source.txt": "copy source\n",
        "shape": "a baseline file\n",
        "unrelated.txt": "baseline unrelated\n",
    }.items():
        (repo / name).write_text(contents)
    _commit_all(repo, "topology baseline")
    baseline = snapshot(repo, "topology baseline snapshot")
    controller, lease = await _active_worker_lease(session_factory, baseline.id, run_id=run_id)
    node_id = str(lease["node_id"])
    lease_id = str(lease["lease_id"])
    execution_id = str(lease["execution_id"])
    generation = int(lease["generation"])
    baseline_entries = [
        _entry("copied-source.txt", "clean", _fingerprint("copy source\n")),
        _entry("renamed-from.txt", "clean", _fingerprint("rename source\n")),
        _entry("shape", "clean", _fingerprint("a baseline file\n")),
    ]
    staged = snapshot(repo, "topology staged snapshot", snapshot_id="d" * 32)
    await _command(
        controller,
        run_id,
        "record_runner_baseline",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": generation,
            "baseline_snapshot_id": baseline.id,
            "baseline_snapshot_ref": baseline.ref,
            "baseline_commit_sha": baseline.commit_sha,
            "baseline_tree_sha": baseline.tree_sha,
            "entries": baseline_entries,
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, baseline_entries),
            "cache_roots": [],
        },
    )
    await _command(
        controller,
        run_id,
        "stage_runner_submission",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": generation,
            "base_snapshot_id": baseline.id,
            "observed_graph_position": await controller.current_position(run_id),
            "idempotency_key": "topology-submit",
            "payload": {},
            "is_mutating": False,
            "complete_node": False,
            "new_state": "completed",
            "staged_snapshot_id": staged.id,
            "staged_snapshot_ref": staged.ref,
            "staged_commit_sha": staged.commit_sha,
            "staged_tree_sha": staged.tree_sha,
            "boundary_hash": boundary_manifest_hash(baseline.tree_sha, baseline_entries),
            "boundary_entries": baseline_entries,
        },
    )
    (repo / "renamed-from.txt").rename(repo / "renamed-to.txt")
    (repo / "copied-target.txt").write_text("copy source\n")
    (repo / "shape").unlink()
    (repo / "shape").mkdir()
    (repo / "shape" / "child.txt").write_text("directory replacement\n")
    (repo / "unrelated.txt").write_text("preserve this external change\n")
    final = snapshot(repo, "topology final snapshot")
    final_entries = [
        _entry("copied-source.txt", "clean", _fingerprint("copy source\n")),
        _entry("copied-target.txt", "untracked", _fingerprint("copy source\n")),
        _entry("renamed-from.txt", "missing", _fingerprint("missing")),
        _entry("renamed-to.txt", "untracked", _fingerprint("rename source\n")),
        _entry("shape", "modified", _fingerprint("directory replacement"), file_type="directory"),
    ]
    result = await _command(
        controller,
        run_id,
        "finalize_runner_execution",
        {
            "execution_id": execution_id,
            "node_id": node_id,
            "lease_id": lease_id,
            "lease_generation": generation,
            "final_snapshot_id": final.id,
            "final_snapshot_ref": final.ref,
            "final_commit_sha": final.commit_sha,
            "final_tree_sha": final.tree_sha,
            "boundary_hash": boundary_manifest_hash(final.tree_sha, final_entries),
            "boundary_entries": final_entries,
        },
    )
    await _complete_prior_agent_dispatches(session_factory, run_id)
    item = next(item for item in result.outbox_items if item.kind == "runner_recovery")
    await OutboxDispatcher(
        session_factory,
        _executor(session_factory, controller, repo, tmp_path),
        FixedClock(),
    ).dispatch_pending(run_id=run_id, allowed_kinds=frozenset({"snapshot_publish"}))
    return RecoveryFixture(
        controller=controller,
        repo=repo,
        item=item,
        baseline_snapshot_id=baseline.id,
        baseline_tree_sha=baseline.tree_sha,
        execution_id=execution_id,
    )


async def _active_worker_lease(
    session_factory: async_sessionmaker[AsyncSession],
    baseline_snapshot_id: str,
    *,
    run_id: str = "runner-recovery",
    controller_type: type[GraphController] = GraphController,
) -> tuple[GraphController, dict[str, object]]:
    clock = FixedClock()
    ids = SequentialIds()
    await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    controller = controller_type(session_factory, clock, ids, auto_dispatch=False)
    accepted = await _command(controller, run_id, "accept_run")
    await _command(controller, run_id, "start", expected_position=accepted.projection_position)
    scheduled = await _command(
        controller,
        run_id,
        "schedule_tick",
        {"base_snapshot_id": baseline_snapshot_id, "max_grants": 1, "lease_seconds": 60},
    )
    lease = next(event.payload for event in scheduled.events if event.event_type == "lease_granted")
    return controller, lease


async def _command(
    controller: GraphController,
    run_id: str,
    command_type: str,
    payload: dict[str, object] | None = None,
    *,
    expected_position: int | None = None,
):
    if command_type in {
        "record_runner_baseline",
        "stage_runner_submission",
        "witness_runner_completion",
        "finalize_runner_execution",
        "request_runner_recovery",
    }:
        payload = dict(payload or {})
        authority_hash = cache_authority_binding(await controller.read_projection(run_id)).hash
        payload.setdefault("cache_authority_hash", authority_hash)
        if command_type == "record_runner_baseline":
            entries_key = "entries"
            tree_key = "baseline_tree_sha"
        elif command_type == "stage_runner_submission":
            entries_key = "boundary_entries"
            tree_key = "staged_tree_sha"
        elif command_type in {"witness_runner_completion", "finalize_runner_execution"}:
            entries_key = "boundary_entries"
            tree_key = "final_tree_sha"
        else:
            entries_key = "boundary_entries"
            tree_key = "final_tree_sha"
        if entries_key in payload and tree_key in payload:
            payload["boundary_hash"] = boundary_manifest_hash(
                str(payload[tree_key]),
                payload[entries_key],
                payload.get("cache_status_evidence", []),
                authority_hash,
            )
        if command_type == "finalize_runner_execution":
            attempt = execution_attempts_view(await controller.read_projection(run_id))[
                str(payload["execution_id"])
            ]
            witnessed = await _command(
                controller,
                run_id,
                "witness_runner_completion",
                {
                    **payload,
                    "staged_payload_hash": attempt.payload_hash,
                    "staged_payload_size_bytes": attempt.payload_size_bytes,
                    "staged_snapshot_id": attempt.staged_snapshot_id,
                    "staged_snapshot_ref": attempt.staged_snapshot_ref,
                    "staged_commit_sha": attempt.staged_commit_sha,
                    "staged_tree_sha": attempt.staged_tree_sha,
                    "staged_boundary_hash": attempt.staged_boundary_hash,
                    "runner_return_kind": "successful_return",
                },
                expected_position=expected_position,
            )
            if any(
                event.event_type in {"runner_boundary_mismatch", "command_rejected"}
                for event in witnessed.events
            ):
                return witnessed
            expected_position = witnessed.projection_position
        return await controller.handle_runtime_boundary_command(
            run_id,
            await controller.current_position(run_id)
            if expected_position is None
            else expected_position,
            command_type,
            payload,
            getattr(controller, "_runtime_boundary_capability"),
        )
    return await controller.handle_command(
        run_id,
        await controller.current_position(run_id)
        if expected_position is None
        else expected_position,
        command_type,
        payload,
    )


async def _events(session_factory: async_sessionmaker[AsyncSession], run_id: str):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _complete_prior_agent_dispatches(
    session_factory: async_sessionmaker[AsyncSession], run_id: str
) -> None:
    """Remove the lease setup's unrelated dispatch intent from this focused drive."""
    async with session_factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    select(GraphOutboxModel).where(
                        GraphOutboxModel.run_id == run_id,
                        GraphOutboxModel.kind == "agent_dispatch",
                    )
                )
            ).scalars()
            for row in rows:
                row.status = "completed"


async def _wait_for_outbox_dispatching(
    session_factory: async_sessionmaker[AsyncSession], outbox_id: int
) -> None:
    """Synchronize against the real dispatcher claim before releasing the lock."""
    for _ in range(20):
        async with session_factory() as session:
            row = await session.get(GraphOutboxModel, outbox_id)
            if row is not None and row.status == "dispatching":
                return
        await asyncio.sleep(0)
    raise AssertionError("runner recovery outbox item was not claimed for dispatch")


async def _set_outbox_status(
    session_factory: async_sessionmaker[AsyncSession], outbox_id: int, status: str
) -> None:
    async with session_factory() as session:
        async with session.begin():
            row = await session.get(GraphOutboxModel, outbox_id)
            assert row is not None
            row.status = status


async def _outbox_status(session_factory: async_sessionmaker[AsyncSession], outbox_id: int) -> str:
    async with session_factory() as session:
        row = await session.get(GraphOutboxModel, outbox_id)
        assert row is not None
        return str(row.status)


def _recovery_item(run_id: str, recovery_id: str, *, execution_id: str) -> OutboxItem:
    now = FixedClock().now()
    return OutboxItem(
        outbox_id=1,
        event_id=f"outbox-{recovery_id}",
        run_id=run_id,
        kind="runner_recovery",
        payload={"recovery_id": recovery_id, "execution_id": execution_id},
        status="pending",
        attempts=0,
        created_at=now,
        updated_at=now,
        next_attempt_at=None,
        last_error=None,
    )


def _event_types(events: list[EventEnvelope]) -> list[str]:
    return [event.event_type for event in events]


def _entry(
    path: str,
    status: str,
    fingerprint: str,
    *,
    file_type: str = "file",
) -> dict[str, str]:
    return {
        "path": path,
        "kind": "tracked" if path == "README.md" else "untracked",
        "status": status,
        "fingerprint": fingerprint,
        "file_type": file_type,
    }


def _fingerprint(contents: str) -> str:
    return f"sha256:{hashlib.sha256(contents.encode()).hexdigest()}"


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "runner-recovery",
            "name": "Runner Recovery",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Recover a runner boundary",
                            "task_context": "Exercise the durable recovery path.",
                            "requirements": [{"id": "req-1", "desc": "Recovery is proven."}],
                        }
                    ],
                }
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("baseline\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _ref_exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=repo,
            check=False,
            timeout=30,
        ).returncode
        == 0
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
