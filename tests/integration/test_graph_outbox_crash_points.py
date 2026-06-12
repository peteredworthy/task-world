from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import (
    EventV2Model,
    GraphOutboxModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import (
    CompromisedFileStateError,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphController,
    GraphEventStore,
    OutboxAppendError,
    OutboxDispatcher,
    OutboxItem,
    StaleProjectionError,
    apply_cleanup_requested,
    capture_file_state_boundary,
    recover,
)
from orchestrator.graph_runtime.controller import rebuild_projection
from orchestrator.graph_runtime.outbox import append_outbox_rows


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


class FixedSequenceIds:
    def __init__(self, values: list[str]) -> None:
        self._values = list(values)

    def next_id(self, prefix: str = "") -> str:
        if not self._values:
            raise AssertionError(f"no id configured for prefix {prefix}")
        return self._values.pop(0)


class RecordingExecutor:
    def __init__(self, call_log: list[str], *, fail_on_calls: set[int] | None = None) -> None:
        self._call_log = call_log
        self._fail_on_calls = fail_on_calls or set()
        self._calls = 0

    async def dispatch(self, item: OutboxItem) -> None:
        self._calls += 1
        self._call_log.append(item.event_id)
        if self._calls in self._fail_on_calls:
            raise RuntimeError(f"dispatch failed at call {self._calls}")


class VisibilityAssertingExecutor:
    def __init__(self, db_path: Path, call_log: list[str]) -> None:
        self._db_path = db_path
        self._call_log = call_log

    async def dispatch(self, item: OutboxItem) -> None:
        own_engine = create_engine(self._db_path)
        try:
            own_session_factory = create_session_factory(own_engine)
            async with own_session_factory() as session:
                events = await GraphEventStore(session).read_run(item.run_id)
                outbox_row = await session.execute(
                    select(GraphOutboxModel).where(GraphOutboxModel.event_id == item.event_id)
                )
                event_rows = await session.execute(
                    select(EventV2Model).where(EventV2Model.aggregate_id == item.run_id)
                )
                visible_outbox_row = outbox_row.scalar_one_or_none()
                visible_event_rows = list(event_rows.scalars())

            assert any(event.event_id == item.event_id for event in events)
            assert visible_outbox_row is not None
            assert len(visible_event_rows) >= 1
            self._call_log.append(item.event_id)
        finally:
            await own_engine.dispose()


class SimulatedProcessCrash(BaseException):
    pass


class CrashOnceAfterSideEffectExecutor:
    def __init__(self, call_log: list[str]) -> None:
        self._call_log = call_log
        self._calls = 0

    async def dispatch(self, item: OutboxItem) -> None:
        self._calls += 1
        self._call_log.append(item.event_id)
        if self._calls == 1:
            raise SimulatedProcessCrash("process died before outbox completion")


class CrashBeforeCleanupExecutor:
    async def dispatch(self, item: OutboxItem) -> None:
        if item.kind == "snapshot_cleanup":
            raise RuntimeError("cleanup side effect did not start")


class UnusedAgentFactory:
    def create_runner(self, context: GraphDispatchContext) -> Any:
        raise AssertionError(f"unexpected agent dispatch for {context.node_id}")


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def file_db_with_path(
    tmp_path: Path,
) -> AsyncGenerator[tuple[Path, AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    db_path = tmp_path / "graph-visibility.db"
    engine = create_engine(db_path)
    await init_db(engine)
    yield db_path, engine, create_session_factory(engine)
    await engine.dispose()


def _event(event_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


async def _seed_runnable_worker(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[EventEnvelope]:
    events = [
        _event(
            f"{run_id}-run-active",
            run_id,
            "run_lifecycle_changed",
            {"from_state": "queued", "to_state": "active"},
        ),
        _event(
            f"{run_id}-worker-created",
            run_id,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
            },
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            return await GraphEventStore(session).append_events(run_id, 0, events)


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _outbox_statuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    async with session_factory() as session:
        result = await session.execute(
            select(GraphOutboxModel.status).order_by(GraphOutboxModel.outbox_id)
        )
        return [str(status) for status in result.scalars()]


async def _outbox_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[GraphOutboxModel]:
    async with session_factory() as session:
        result = await session.execute(
            select(GraphOutboxModel).order_by(GraphOutboxModel.outbox_id)
        )
        return list(result.scalars())


async def _outbox_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(select(func.count(GraphOutboxModel.outbox_id)))
        return int(result.scalar_one())


def _init_repo(path: Path) -> None:
    path.mkdir()
    _run_git(path, ["init"])
    _run_git(path, ["config", "user.email", "test@example.com"])
    _run_git(path, ["config", "user.name", "Test User"])
    (path / "README.md").write_text("base\n")
    _run_git(path, ["add", "README.md"])
    _run_git(path, ["commit", "-m", "base"])


def _run_git(path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _ref_exists(path: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=path,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def _tree_paths(path: Path, commit_sha: str) -> set[str]:
    output = _run_git(path, ["ls-tree", "-r", "--name-only", commit_sha])
    return set(output.splitlines()) if output else set()


def _secret_verdict(path: str) -> dict[str, object]:
    return {
        "path": path,
        "classification": "secret",
        "confidence": 0.99,
        "rationale": "secret fixture",
        "model_id": "test-gatekeeper",
        "input_tokens": 1,
        "output_tokens": 1,
        "cost_usd": 0.001,
        "wall_time_ms": 1,
    }


async def _seed_cleanup_request(
    session_factory: async_sessionmaker[AsyncSession],
    repo: Path,
    *,
    run_id: str,
    clock: FixedClock,
    ids: SequentialIds,
) -> tuple[GraphController, str, str]:
    (repo / "residue.txt").write_text("secret\n")
    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id=run_id,
        node_id="worker-1",
        execution_id="exec-1",
        base_snapshot_id="base-snapshot",
    )
    assert boundary.output_record is not None
    record_id = str(boundary.output_record["record_id"])
    old_snapshot_id = str(boundary.output_record["snapshot_id"])
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [_event("file-state-event", run_id, "file_state_accepted", boundary.output_record)],
            )

    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    result = await controller.handle_command(
        run_id,
        1,
        "record_gatekeeper_verdicts",
        {
            "file_state_record_id": record_id,
            "execution_id": "exec-1",
            "consult_id": "consult-1",
            "verdicts": [_secret_verdict("residue.txt")],
        },
    )
    assert [item.kind for item in result.outbox_items] == ["snapshot_cleanup"]
    return controller, record_id, old_snapshot_id


@pytest.mark.asyncio
async def test_crash_before_append_no_events_no_outbox_no_dispatch(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "crash-before-append"
    await _seed_runnable_worker(session_factory, run_id)
    call_log: list[str] = []
    clock = FixedClock()
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    controller = GraphController(session_factory, clock, SequentialIds(), dispatcher=dispatcher)

    with pytest.raises(StaleProjectionError):
        await controller.handle_command(
            run_id, 1, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
        )

    events = await _read_events(session_factory, run_id)
    assert [event.event_id for event in events] == [
        f"{run_id}-run-active",
        f"{run_id}-worker-created",
    ]
    assert await _outbox_count(session_factory) == 0
    assert call_log == []


@pytest.mark.asyncio
async def test_crash_after_append_before_outbox_starts_agent_restarts_dispatch(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "crash-after-append"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)

    result = await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )
    assert [item.status for item in result.outbox_items] == ["pending"]

    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    report = await recover(session_factory, dispatcher, run_id=run_id)
    await dispatcher.dispatch_pending()

    assert len(report.redispatched) == 1
    redispatched = report.redispatched[0]
    assert redispatched.run_id == run_id
    assert redispatched.kind == "agent_dispatch"
    assert redispatched.payload["run_id"] == run_id
    assert redispatched.payload["node_id"] == "worker-1"
    assert redispatched.payload["lease_id"] == result.outbox_items[0].payload["lease_id"]
    assert redispatched.payload["generation"] == 1
    assert redispatched.payload["classification"] == "agent_dispatch_pending"
    assert call_log == [result.outbox_items[0].event_id]
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_crash_after_agent_starts_before_start_ack_reports_awaiting_start_ack(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "crash-after-agent-start"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    controller = GraphController(
        session_factory,
        clock,
        SequentialIds(),
        dispatcher=dispatcher,
    )

    await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )
    assert len(call_log) == 1

    restarted_dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
    second_report = await recover(session_factory, restarted_dispatcher, run_id=run_id)

    assert len(call_log) == 1
    assert report.redispatched == []
    assert report.awaiting_start_ack == [
        {
            "run_id": run_id,
            "lease_id": "lease-3",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-4",
            "classification": "awaiting_start_ack",
        }
    ]
    assert report.awaiting_start_ack == second_report.awaiting_start_ack
    lease_id = str(report.awaiting_start_ack[0]["lease_id"])
    projection = rebuild_projection(await _read_events(session_factory, run_id))
    assert projection["leases"][lease_id]["state"] == "active"
    assert projection["node_states"]["worker-1"] == "leased"


@pytest.mark.asyncio
async def test_crash_point_4_agent_died_revokes_lease_and_allows_release(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "agent-dies-controller-command"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    controller = GraphController(
        session_factory,
        clock,
        SequentialIds(),
        dispatcher=dispatcher,
    )

    first = await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )
    lease_id = str(first.outbox_items[0].payload["lease_id"])
    execution_id = str(first.outbox_items[0].payload["execution_id"])
    started = await controller.handle_command(
        run_id,
        first.projection_position,
        "acknowledge_start",
        {
            "node_id": "worker-1",
            "lease_id": lease_id,
            "lease_generation": 1,
            "execution_id": execution_id,
        },
    )

    died = await controller.handle_command(
        run_id,
        started.projection_position,
        "agent_died",
        {"lease_id": lease_id, "execution_id": execution_id, "reason": "process_exited"},
    )
    projection_after_death = rebuild_projection(await _read_events(session_factory, run_id))
    relearnt = await controller.handle_command(
        run_id,
        died.projection_position,
        "schedule_tick",
        {"lease_seconds": 60, "base_snapshot_id": "S0"},
    )
    projection_after_relearn = rebuild_projection(await _read_events(session_factory, run_id))

    assert [event.event_type for event in died.events] == [
        "agent_died",
        "lease_revoked",
        "runtime_retry_scheduled",
        "node_state_changed",
    ]
    assert projection_after_death["leases"][lease_id]["state"] == "revoked"
    assert projection_after_death["node_states"]["worker-1"] == "ready"
    assert any(event.event_type == "runtime_retry_scheduled" for event in died.events)
    assert [event.event_type for event in relearnt.events] == [
        "node_ready",
        "lease_granted",
        "agent_dispatch_requested",
        "node_state_changed",
    ]
    new_lease_id = str(relearnt.outbox_items[0].payload["lease_id"])
    assert new_lease_id != lease_id
    assert projection_after_relearn["leases"][new_lease_id]["state"] == "active"
    assert call_log == [first.outbox_items[0].event_id, relearnt.outbox_items[0].event_id]
    assert await _outbox_statuses(session_factory) == ["completed", "completed"]


@pytest.mark.asyncio
async def test_duplicate_dispatch_pending_invokes_executor_once(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "duplicate-dispatch"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)
    await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )

    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    await dispatcher.dispatch_pending()
    await dispatcher.dispatch_pending()

    assert len(call_log) == 1
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_restart_mid_dispatching_row_is_retried_idempotently(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "restart-mid-dispatch"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)
    result = await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )

    call_log: list[str] = []
    crashing_dispatcher = OutboxDispatcher(
        session_factory,
        CrashOnceAfterSideEffectExecutor(call_log),
        clock,
    )

    with pytest.raises(SimulatedProcessCrash):
        await crashing_dispatcher.dispatch_pending()

    rows_after_crash = await _outbox_rows(session_factory)
    assert len(rows_after_crash) == 1
    assert rows_after_crash[0].event_id == result.outbox_items[0].event_id
    assert rows_after_crash[0].status == "dispatching"
    assert rows_after_crash[0].attempts == 1
    assert call_log == [result.outbox_items[0].event_id]

    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    report = await recover(session_factory, dispatcher, run_id=run_id)
    rows_after_recovery = await _outbox_rows(session_factory)

    assert len(report.redispatched) == 1
    assert call_log == [result.outbox_items[0].event_id, result.outbox_items[0].event_id]
    assert rows_after_recovery[0].status == "completed"
    assert rows_after_recovery[0].attempts == 2


@pytest.mark.asyncio
async def test_snapshot_cleanup_recovers_when_dispatch_fails_before_side_effect(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "cleanup-before-side-effect"
    _init_repo(repo)
    clock = FixedClock()
    controller, record_id, old_snapshot_id = await _seed_cleanup_request(
        session_factory,
        repo,
        run_id="cleanup-before-side-effect",
        clock=clock,
        ids=SequentialIds(),
    )
    old_ref = f"refs/orchestrator/snapshots/{old_snapshot_id}"
    assert _ref_exists(repo, old_ref) is True

    crashing_dispatcher = OutboxDispatcher(session_factory, CrashBeforeCleanupExecutor(), clock)
    await crashing_dispatcher.dispatch_pending(limit=1)
    rows_after_crash = await _outbox_rows(session_factory)
    assert len(rows_after_crash) == 1
    assert rows_after_crash[0].kind == "snapshot_cleanup"
    assert rows_after_crash[0].status == "pending"

    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        UnusedAgentFactory(),
        worktree_path=repo,
    )
    restarted_dispatcher = OutboxDispatcher(session_factory, executor, clock)
    report = await recover(
        session_factory,
        restarted_dispatcher,
        run_id="cleanup-before-side-effect",
    )
    await restarted_dispatcher.dispatch_pending()

    events = await _read_events(session_factory, "cleanup-before-side-effect")
    projection = rebuild_projection(events)
    original = projection["file_state_records"][record_id]
    superseding_id = str(original["superseded_by_record_id"])
    superseding = projection["file_state_records"][superseding_id]
    new_snapshot_id = str(superseding["snapshot_id"])
    new_ref = f"refs/orchestrator/snapshots/{new_snapshot_id}"

    assert [item.kind for item in report.pending_cleanups] == ["snapshot_cleanup"]
    assert [item.kind for item in report.redispatched] == ["snapshot_cleanup"]
    assert _ref_exists(repo, old_ref) is False
    assert _ref_exists(repo, new_ref) is True
    assert "residue.txt" not in _tree_paths(repo, str(superseding["git"]["commit_sha"]))
    assert any(event.event_type == "cleanup_applied" for event in events)
    assert original["superseded_pending"] is False
    assert superseding["supersedes_record_id"] == record_id
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_snapshot_cleanup_recovers_after_ref_delete_before_record(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "cleanup-after-ref-delete"
    _init_repo(repo)
    clock = FixedClock()
    controller, record_id, old_snapshot_id = await _seed_cleanup_request(
        session_factory,
        repo,
        run_id="cleanup-after-ref-delete",
        clock=clock,
        ids=SequentialIds(),
    )
    events_before = await _read_events(session_factory, "cleanup-after-ref-delete")
    cleanup_event = next(
        event for event in events_before if event.event_type == "cleanup_requested"
    )
    compromised_record = rebuild_projection(events_before)["file_state_records"][record_id]
    first_cleanup = apply_cleanup_requested(
        worktree_path=repo,
        cleanup_request=cleanup_event.payload,
        compromised_record=compromised_record,
    )
    old_ref = f"refs/orchestrator/snapshots/{old_snapshot_id}"
    first_new_ref = (
        f"refs/orchestrator/snapshots/{first_cleanup.superseding_file_state_record['snapshot_id']}"
    )
    assert first_cleanup.deleted_snapshot_ref is True
    assert _ref_exists(repo, old_ref) is False
    assert _ref_exists(repo, first_new_ref) is True

    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        UnusedAgentFactory(),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    await dispatcher.dispatch_pending()
    await dispatcher.dispatch_pending()

    events_after = await _read_events(session_factory, "cleanup-after-ref-delete")
    projection = rebuild_projection(events_after)
    original = projection["file_state_records"][record_id]
    superseding_records = [
        event
        for event in events_after
        if event.event_type == "file_state_accepted"
        and event.payload.get("supersedes_record_id") == record_id
    ]

    assert _ref_exists(repo, old_ref) is False
    assert len([event for event in events_after if event.event_type == "cleanup_applied"]) == 1
    assert len(superseding_records) == 1
    assert original["superseded_pending"] is False
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_compromised_file_state_binding_is_refused_before_cleanup_completes(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "compromised-binding"
    _init_repo(repo)
    run_id = "compromised-binding"
    file_state_payload = {
        "record_id": "file-state-1",
        "record_kind": "file_state",
        "producer_node_id": "worker-1",
        "snapshot_id": "snapshot-1",
        "base_snapshot_id": "base-1",
        "git": {
            "commit_sha": "commit-1",
            "tree_sha": "tree-1",
            "ref": "refs/orchestrator/snapshots/snapshot-1",
        },
        "classifications": [
            {"path": "residue.txt", "source": "untracked", "classification": "secret"}
        ],
        "residue": [{"path": "residue.txt", "source": "untracked", "classification": "secret"}],
    }
    events = [
        _event(
            "file-state-event",
            run_id,
            "file_state_accepted",
            file_state_payload,
        ),
        _event(
            "cleanup-event",
            run_id,
            "cleanup_requested",
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "snapshot_id": "snapshot-1",
                "paths": ["residue.txt"],
            },
        ),
        _event(
            "worker-event",
            run_id,
            "node_created",
            {"node_id": "consumer-1", "kind": "worker", "state": "ready"},
        ),
        _event(
            "bound-event",
            run_id,
            "input_bound",
            {
                "edge_id": "edge-1",
                "to_node_id": "consumer-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
                "bound_at_position": 0,
            },
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, events)

    clock = FixedClock()
    controller = GraphController(session_factory, clock=clock, id_gen=SequentialIds())
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        UnusedAgentFactory(),
        worktree_path=repo,
    )

    with pytest.raises(CompromisedFileStateError):
        await executor.dispatch(
            OutboxItem(
                outbox_id=1,
                event_id="dispatch-1",
                run_id=run_id,
                kind="agent_dispatch",
                payload={
                    "node_id": "consumer-1",
                    "lease_id": "lease-1",
                    "generation": 1,
                    "execution_id": "exec-1",
                    "base_snapshot_id": "base-1",
                },
                status="pending",
                attempts=0,
                created_at=clock.now(),
                updated_at=clock.now(),
                last_error=None,
            )
        )


@pytest.mark.asyncio
async def test_events_and_outbox_rows_commit_atomically_on_outbox_failure(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "atomic-outbox-failure"
    clock = FixedClock()
    dispatch_event = _event(
        "dispatch-event-collision",
        run_id,
        "agent_dispatch_requested",
        {"lease_id": "lease-1", "node_id": "worker-1"},
    )

    async with session_factory() as session:
        async with session.begin():
            session.add(
                GraphOutboxModel(
                    event_id=dispatch_event.event_id,
                    run_id=run_id,
                    kind="agent_dispatch",
                    payload={"event_id": dispatch_event.event_id},
                    status="pending",
                    attempts=0,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )

    with pytest.raises(OutboxAppendError):
        async with session_factory() as session:
            async with session.begin():
                stored = await GraphEventStore(session).append_events(run_id, 0, [dispatch_event])
                await append_outbox_rows(session, stored, clock)

    assert await _read_events(session_factory, run_id) == []
    assert await _outbox_count(session_factory) == 1


@pytest.mark.asyncio
async def test_controller_does_not_start_side_effect_before_commit(
    file_db_with_path: tuple[Path, AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    db_path, _, session_factory = file_db_with_path
    run_id = "no-side-effect-before-commit"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(
        session_factory,
        VisibilityAssertingExecutor(db_path, call_log),
        clock,
    )
    controller = GraphController(
        session_factory,
        clock,
        SequentialIds(),
        dispatcher=dispatcher,
    )

    result = await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )

    assert call_log == [result.outbox_items[0].event_id]
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_controller_rolls_back_events_when_dispatch_outbox_insert_fails(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "controller-atomic-outbox-failure"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    collision_event_id = "event-dispatch-collision"
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)

    async with session_factory() as session:
        async with session.begin():
            session.add(
                GraphOutboxModel(
                    event_id=collision_event_id,
                    run_id=run_id,
                    kind="agent_dispatch",
                    payload={"event_id": collision_event_id},
                    status="pending",
                    attempts=0,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )

    controller = GraphController(
        session_factory,
        clock,
        FixedSequenceIds(
            [
                "event-ready",
                "event-ready-state",
                "lease-1",
                "exec-1",
                "event-lease-granted",
                "event-leased-state",
                collision_event_id,
            ]
        ),
        dispatcher=dispatcher,
    )

    with pytest.raises(OutboxAppendError):
        await controller.handle_command(
            run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
        )

    events = await _read_events(session_factory, run_id)
    outbox_rows = await _outbox_rows(session_factory)
    assert [event.event_id for event in events] == [
        f"{run_id}-run-active",
        f"{run_id}-worker-created",
    ]
    assert len(outbox_rows) == 1
    assert outbox_rows[0].event_id == collision_event_id
    assert call_log == []


@pytest.mark.asyncio
async def test_agent_dispatch_requested_event_envelope_is_persisted_exactly(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "dispatch-envelope"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)

    result = await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )
    read_back = await _read_events(session_factory, run_id)
    lease_event = next(event for event in read_back if event.event_type == "lease_granted")
    dispatch_event = next(
        event for event in read_back if event.event_type == "agent_dispatch_requested"
    )

    assert dispatch_event.event_type == "agent_dispatch_requested"
    assert dispatch_event.run_id == run_id
    assert dispatch_event.position == lease_event.position + 1
    assert dispatch_event.actor.kind == "controller"
    assert dispatch_event.causation_id == "schedule_tick"
    assert dispatch_event.schema_version == 1
    assert dispatch_event.timestamp == clock.now()
    assert dispatch_event.payload == {
        "lease_granted_event_id": lease_event.event_id,
        "lease_id": lease_event.payload["lease_id"],
        "node_id": "worker-1",
        "generation": 1,
        "execution_id": lease_event.payload["execution_id"],
        "base_snapshot_id": "S0",
        "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
    }
    assert result.outbox_items[0].event_id == dispatch_event.event_id


@pytest.mark.asyncio
async def test_controller_round_trip_projection_matches_in_memory_projection(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "controller-round-trip"
    seed_events = await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)

    result = await controller.handle_command(
        run_id, 2, "schedule_tick", {"lease_seconds": 60, "base_snapshot_id": "S0"}
    )
    read_back = await _read_events(session_factory, run_id)

    assert read_back == seed_events + result.events
    assert rebuild_projection(read_back) == rebuild_projection(seed_events + result.events)
