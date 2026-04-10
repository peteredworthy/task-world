"""Consolidated recovery tests.

Covers:
- DB persistence across service restart (new WorkflowService from same persisted DB)
- No duplicate attempts after restart
- Run can continue from correct step after restart
- Event replay restores full run state (linear, pause/resume, step skip)
- Old event format backward compatibility
- Child event types replay without errors
- Grade snapshots survive event replay across revision cycles
- Revision cycle recovery via events
- Recovery with YAML routine fixture
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from orchestrator.config import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
    load_routine_from_path,
)
from orchestrator.config.models import (
    RequirementConfig,
    RoutineConfig,
    StepCondition,
    StepConfig,
    TaskConfig,
)
from orchestrator.db import Base, EventStore, RunRepository, create_engine, create_session_factory, init_db, replay_events
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"
_TMP_DIR = Path(__file__).parent.parent.parent / "tmp"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """File-based SQLite so events and DB state persist across session boundaries."""
    _TMP_DIR.mkdir(exist_ok=True)
    db_path = _TMP_DIR / f"test_recovery_{uuid.uuid4().hex}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from orchestrator.db import create_session_factory as _csf

    yield _csf(engine)
    await engine.dispose()
    db_path.unlink(missing_ok=True)
    Path(str(db_path) + "-wal").unlink(missing_ok=True)
    Path(str(db_path) + "-shm").unlink(missing_ok=True)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite for pure event-replay tests that don't need cross-session persistence."""
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# Routine builders
# ---------------------------------------------------------------------------


def _make_two_step_routine(routine_id: str = "recovery-two-step") -> RoutineConfig:
    req = RequirementConfig(id="R1", desc="Complete the work")
    return RoutineConfig(
        id=routine_id,
        name="Recovery Two-Step Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step One",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task One",
                        task_context="First task",
                        requirements=[req],
                    ),
                ],
            ),
            StepConfig(
                id="S-02",
                title="Step Two",
                tasks=[
                    TaskConfig(
                        id="T-02",
                        title="Task Two",
                        task_context="Second task",
                        requirements=[req],
                    ),
                ],
            ),
        ],
    )


def _make_skip_routine() -> RoutineConfig:
    """Three-step routine where step 2 has condition=false."""
    req = RequirementConfig(id="R1", desc="Done")
    return RoutineConfig(
        id="replay-skip",
        name="Replay Skip Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step One",
                tasks=[
                    TaskConfig(
                        id="T-01", title="Task One", task_context="Always runs", requirements=[req]
                    )
                ],
            ),
            StepConfig(
                id="S-02",
                title="Step Two (Skipped)",
                tasks=[
                    TaskConfig(
                        id="T-02", title="Task Two", task_context="Skipped", requirements=[req]
                    )
                ],
                condition=StepCondition(when="false"),
            ),
            StepConfig(
                id="S-03",
                title="Step Three",
                tasks=[
                    TaskConfig(
                        id="T-03",
                        title="Task Three",
                        task_context="Runs after skip",
                        requirements=[req],
                    )
                ],
            ),
        ],
    )


def _make_pause_routine() -> RoutineConfig:
    """Single-step routine for pause/resume testing."""
    req = RequirementConfig(id="R1", desc="Done")
    return RoutineConfig(
        id="replay-pause",
        name="Replay Pause Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Only Step",
                tasks=[
                    TaskConfig(
                        id="T-01", title="Only Task", task_context="Do it", requirements=[req]
                    )
                ],
            ),
        ],
    )


def _make_single_task_run() -> Run:
    """Simple in-memory run with one task, used for event-replay tests."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Complete the task",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_from_routine(
    routine: RoutineConfig, run_id: str, embed_routine: bool = False
) -> Run:
    run = create_run_from_routine(
        routine,
        repo_name=f"replay-repo-{run_id}",
        source_branch="main",
    )
    if embed_routine:
        run.routine_embedded = routine.model_dump(mode="json")
    return run


def _make_persistence_run(
    routine: RoutineConfig, run_id: str = "run-recovery"
) -> Any:
    return create_run_from_routine(
        routine,
        repo_name="parity-recovery-repo",
        source_branch="main",
        id_generator=iter([run_id, "step-1", "task-1", "step-2", "task-2"]).__next__,
    )


async def _complete_task(service: WorkflowService, run_id: str, task_id: str) -> None:
    """Drive a task through start → checklist done → submit → grade A → complete."""
    await service.start_task(run_id, task_id)
    await service.update_checklist_item(run_id, task_id, "R1", ChecklistStatus.DONE)
    await service.submit_for_verification(run_id, task_id)
    await service.set_grade(run_id, task_id, "R1", "A", "Looks good")
    await service.complete_verification(run_id, task_id)


async def _get_events(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    """Retrieve all persisted events for a run."""
    store = EventStore(session, journal=None)
    return await store.get_events_for_run(run_id)


def _reset_run_to_draft(run: Run) -> None:
    """Reset a run and all its tasks back to initial DRAFT state (simulate crash)."""
    run.status = RunStatus.DRAFT
    run.started_at = None
    run.completed_at = None
    run.pause_reason = None
    run.last_error = None
    run.current_step_index = 0
    for step in run.steps:
        step.completed = False
        step.skipped = False
        step.skip_reason = None
        for task in step.tasks:
            task.status = TaskStatus.PENDING
            task.current_attempt = 0
            task.attempts = []


# ===========================================================================
# DB PERSISTENCE ACROSS SERVICE RESTART
# (from test_parity_recovery.py)
# ===========================================================================


async def test_db_persistence_completed_task_survives_restart(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Completed task remains completed after service is re-instantiated from DB."""
    routine = _make_two_step_routine()
    run = _make_persistence_run(routine)
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id

    # Phase 1: complete task 1 with service instance 1
    async with session_factory() as session1:
        svc1 = WorkflowService(session1)
        await svc1.create_run(run)
        await svc1.apply_start_run(run_id)
        await _complete_task(svc1, run_id, task1_id)

    # Phase 2: new service from same DB — simulate restart
    async with session_factory() as session2:
        svc2 = WorkflowService(session2)
        loaded = await svc2._repo.get(run_id)

        task1 = loaded.steps[0].tasks[0]
        assert task1.status == TaskStatus.COMPLETED, (
            "Task 1 should remain completed after service restart"
        )
        assert len(task1.attempts) == 1, "No duplicate attempt should be created after restart"
        assert task1.attempts[0].outcome == "passed"
        assert loaded.steps[0].completed is True
        assert loaded.current_step_index == 1
        assert loaded.status == RunStatus.ACTIVE


async def test_db_persistence_no_duplicate_attempts_on_reload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reloading from DB does not create duplicate attempts for completed tasks."""
    routine = _make_two_step_routine()
    run = _make_persistence_run(routine, run_id="run-recovery-no-dup")
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id

    async with session_factory() as session1:
        svc1 = WorkflowService(session1)
        await svc1.create_run(run)
        await svc1.apply_start_run(run_id)
        await _complete_task(svc1, run_id, task1_id)

    async with session_factory() as session2:
        svc2 = WorkflowService(session2)
        loaded = await svc2._repo.get(run_id)
        task1 = loaded.steps[0].tasks[0]
        assert task1.status == TaskStatus.COMPLETED
        assert len(task1.attempts) == 1, "Reloading from DB must not create duplicate attempts"


async def test_db_persistence_can_continue_from_correct_step(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """After restart, the second task can be started and completed normally."""
    routine = _make_two_step_routine()
    run = _make_persistence_run(routine, run_id="run-recovery-continue")
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id
    task2_id = run.steps[1].tasks[0].id

    # Phase 1: complete task 1
    async with session_factory() as session1:
        svc1 = WorkflowService(session1)
        await svc1.create_run(run)
        await svc1.apply_start_run(run_id)
        await _complete_task(svc1, run_id, task1_id)

    # Phase 2: restart — continue with task 2
    async with session_factory() as session2:
        svc2 = WorkflowService(session2)
        loaded = await svc2._repo.get(run_id)

        assert loaded.steps[0].tasks[0].status == TaskStatus.COMPLETED
        assert loaded.steps[1].tasks[0].status == TaskStatus.PENDING

        await _complete_task(svc2, run_id, task2_id)

        finished = await svc2._repo.get(run_id)
        assert finished.status == RunStatus.COMPLETED
        assert finished.steps[1].tasks[0].status == TaskStatus.COMPLETED
        assert len(finished.steps[1].tasks[0].attempts) == 1, (
            "Task 2 should have exactly one attempt"
        )


# ===========================================================================
# EVENT REPLAY — LINEAR LIFECYCLE
# (merged from test_parity_replay and test_event_recovery)
# ===========================================================================


async def test_replay_linear_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full two-step linear run: destroy state, replay events, compare reconstructed state."""
    routine = _make_two_step_routine(routine_id="replay-linear")
    run = _make_run_from_routine(routine, "linear-001")
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id
    task2_id = run.steps[1].tasks[0].id

    # Phase 1: drive full lifecycle
    async with session_factory() as session:
        svc = WorkflowService(session)
        await svc.create_run(run)
        await svc.apply_start_run(run_id)
        await _complete_task(svc, run_id, task1_id)
        await _complete_task(svc, run_id, task2_id)

    # Phase 2: capture state, reset, replay, compare
    async with session_factory() as session:
        repo = RunRepository(session)
        original = await repo.get(run_id)

        original_status = original.status
        original_step_index = original.current_step_index
        original_step0_completed = original.steps[0].completed
        original_step1_completed = original.steps[1].completed
        t1_status = original.steps[0].tasks[0].status
        t1_attempt_count = len(original.steps[0].tasks[0].attempts)
        t1_outcome = (
            original.steps[0].tasks[0].attempts[0].outcome
            if original.steps[0].tasks[0].attempts
            else None
        )
        t2_status = original.steps[1].tasks[0].status
        t2_attempt_count = len(original.steps[1].tasks[0].attempts)

        events = await _get_events(session, run_id)
        assert len(events) > 0, "Events should have been persisted"

        _reset_run_to_draft(original)
        replay_events(original, events)

        assert original.status == original_status
        assert original.current_step_index == original_step_index
        assert original.steps[0].completed == original_step0_completed
        assert original.steps[1].completed == original_step1_completed

        task1 = original.steps[0].tasks[0]
        assert task1.status == t1_status
        assert len(task1.attempts) == t1_attempt_count
        assert task1.current_attempt == t1_attempt_count
        if task1.attempts:
            assert task1.attempts[0].outcome == t1_outcome

        task2 = original.steps[1].tasks[0]
        assert task2.status == t2_status
        assert len(task2.attempts) == t2_attempt_count

        assert original.started_at is not None
        assert original.completed_at is not None


async def test_replay_basic_state_recovery(session: AsyncSession) -> None:
    """Basic replay: start + begin task, crash, replay, verify state reconstructed."""
    service = WorkflowService(session)
    run = _make_single_task_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    current = await service.get_run("run-1")
    assert current.status == RunStatus.ACTIVE
    assert current.steps[0].tasks[0].status == TaskStatus.BUILDING

    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    assert len(events) >= 2

    fresh_run = _make_single_task_run()
    recovered = replay_events(fresh_run, events)

    assert recovered.status == RunStatus.ACTIVE
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.BUILDING
    assert recovered.steps[0].tasks[0].current_attempt == 1


# ===========================================================================
# EVENT REPLAY — PAUSE / RESUME
# (from test_parity_replay)
# ===========================================================================


async def test_replay_pause_resume_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pause/resume cycle: pause_reason reconstructed from events, cleared on resume."""
    routine = _make_pause_routine()
    run = _make_run_from_routine(routine, "pause-001")
    run_id = run.id

    async with session_factory() as session:
        svc = WorkflowService(session)
        await svc.create_run(run)
        await svc.apply_start_run(run_id)
        await svc.apply_pause_run(run_id, reason="server_shutdown")
        await svc.apply_resume_run(run_id)

    async with session_factory() as session:
        repo = RunRepository(session)
        original = await repo.get(run_id)

        assert original.status == RunStatus.ACTIVE
        assert original.pause_reason is None

        events = await _get_events(session, run_id)

        pause_events = [
            e
            for e in events
            if e["type"] == "run_status_changed" and e["payload"].get("new_status") == "paused"
        ]
        resume_events = [
            e
            for e in events
            if e["type"] == "run_status_changed" and e["payload"].get("new_status") == "active"
        ]
        assert len(pause_events) >= 1, "Should have at least one pause event"
        assert len(resume_events) >= 1, "Should have at least one resume event"

        pause_payload = pause_events[0]["payload"]
        assert pause_payload.get("pause_reason") == "server_shutdown", (
            f"pause_reason should be in event payload, got: {pause_payload}"
        )

        # Full replay: ends with ACTIVE (resume happened)
        _reset_run_to_draft(original)
        replay_events(original, events)
        assert original.status == RunStatus.ACTIVE
        assert original.pause_reason is None

        # Partial replay up to pause: should yield PAUSED with correct reason
        events_up_to_pause_idx = None
        for i, e in enumerate(events):
            if e["type"] == "run_status_changed" and e["payload"].get("new_status") == "paused":
                events_up_to_pause_idx = i + 1
                break

        assert events_up_to_pause_idx is not None
        _reset_run_to_draft(original)
        replay_events(original, events[:events_up_to_pause_idx])
        assert original.status == RunStatus.PAUSED
        assert original.pause_reason == "server_shutdown", (
            f"pause_reason should be 'server_shutdown', got: {original.pause_reason}"
        )


# ===========================================================================
# EVENT REPLAY — STEP SKIP
# (from test_parity_replay)
# ===========================================================================


async def test_replay_step_skip_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Step skip: skipped step and skip_reason reconstructed from step_skipped events."""
    routine = _make_skip_routine()
    run = _make_run_from_routine(routine, "skip-001", embed_routine=True)
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id
    task3_id = run.steps[2].tasks[0].id

    async with session_factory() as session:
        svc = WorkflowService(session)
        await svc.create_run(run)
        await svc.apply_start_run(run_id)
        await _complete_task(svc, run_id, task1_id)
        await _complete_task(svc, run_id, task3_id)

    async with session_factory() as session:
        repo = RunRepository(session)
        original = await repo.get(run_id)

        assert original.status == RunStatus.COMPLETED
        assert original.steps[0].completed is True
        assert original.steps[1].skipped is True
        assert original.steps[1].skip_reason is not None
        assert original.steps[2].completed is True

        original_skip_reason = original.steps[1].skip_reason

        events = await _get_events(session, run_id)
        skip_events = [e for e in events if e["type"] == "step_skipped"]
        assert len(skip_events) >= 1, "Should have at least one step_skipped event"
        skip_payload = skip_events[0]["payload"]
        assert (
            skip_payload.get("skip_reason") is not None or skip_payload.get("reason") is not None
        ), f"step_skipped payload should have skip_reason or reason: {skip_payload}"

        _reset_run_to_draft(original)
        replay_events(original, events)

        assert original.status == RunStatus.COMPLETED
        assert original.steps[0].completed is True
        assert original.steps[1].skipped is True
        assert original.steps[1].skip_reason == original_skip_reason, (
            f"skip_reason should be reconstructed: got {original.steps[1].skip_reason!r}, "
            f"expected {original_skip_reason!r}"
        )
        assert original.steps[2].completed is True


# ===========================================================================
# EVENT REPLAY — OLD EVENT FORMAT BACKWARD COMPATIBILITY
# (from test_parity_replay)
# ===========================================================================


async def test_replay_handles_old_event_format(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Old events without last_error/start_commit/end_commit replay without errors."""
    routine = _make_two_step_routine(routine_id="replay-linear-compat")
    run = _make_run_from_routine(routine, "compat-001")
    run_id = run.id

    async with session_factory() as session:
        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

    t1 = datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 15, 10, 32, 0, tzinfo=timezone.utc)
    t3 = datetime(2025, 1, 15, 10, 33, 0, tzinfo=timezone.utc)
    t4 = datetime(2025, 1, 15, 10, 34, 0, tzinfo=timezone.utc)

    old_events = [
        {
            "type": "run_status_changed",
            "timestamp": t1,
            "payload": {
                "old_status": "draft",
                "new_status": "active",
                "run_id": run_id,
                "event_type": "run_status_changed",
                "timestamp": t1.isoformat(),
            },
        },
        {
            "type": "run_status_changed",
            "timestamp": t2,
            "payload": {
                "old_status": "active",
                "new_status": "paused",
                "run_id": run_id,
                "event_type": "run_status_changed",
                "timestamp": t2.isoformat(),
                # No pause_reason, no last_error (old format)
            },
        },
        {
            "type": "task_status_changed",
            "timestamp": t3,
            "payload": {
                "task_id": run.steps[0].tasks[0].id,
                "old_status": "pending",
                "new_status": "building",
                "run_id": run_id,
                "event_type": "task_status_changed",
                "timestamp": t3.isoformat(),
                # No start_commit (old format)
            },
        },
        {
            "type": "step_skipped",
            "timestamp": t4,
            "payload": {
                "step_index": 1,
                "step_id": run.steps[1].id,
                "condition": "false",
                "reason": "old reason format",  # legacy field name
                "run_id": run_id,
                "event_type": "step_skipped",
                "timestamp": t4.isoformat(),
            },
        },
    ]

    async with session_factory() as session:
        repo = RunRepository(session)
        fresh_run = await repo.get(run_id)

    replay_events(fresh_run, old_events)

    assert fresh_run.status == RunStatus.PAUSED
    assert fresh_run.pause_reason is None  # old event had no pause_reason
    assert fresh_run.last_error is None  # old event had no last_error

    task1 = fresh_run.steps[0].tasks[0]
    assert task1.status == TaskStatus.BUILDING
    assert len(task1.attempts) == 1
    assert task1.attempts[0].start_commit is None  # old event had no start_commit

    # step_skipped with legacy "reason" field should reconstruct skip_reason
    assert fresh_run.steps[1].skipped is True
    assert fresh_run.steps[1].skip_reason == "old reason format"


# ===========================================================================
# EVENT REPLAY — CHILD EVENT TYPES
# (from test_parity_replay)
# ===========================================================================


async def test_child_event_types_in_replay(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Child lifecycle event types exist and replay without errors (informational)."""
    from orchestrator.workflow import ChildSpawned, ChildCompleted, ChildFailed

    routine = _make_pause_routine()
    run = _make_run_from_routine(routine, "child-001")
    run_id = run.id

    async with session_factory() as session:
        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

    t1 = datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc)

    spawned = ChildSpawned(
        timestamp=t1,
        run_id=run_id,
        event_type="child_spawned",
        parent_task_id="parent-1",
        child_task_id="child-1",
        fan_out_index=0,
        fan_out_input="item_0",
    )
    assert spawned.event_type == "child_spawned"
    assert spawned.parent_task_id == "parent-1"

    completed = ChildCompleted(
        timestamp=t1,
        run_id=run_id,
        event_type="child_completed",
        parent_task_id="parent-1",
        child_task_id="child-1",
        fan_out_index=0,
        fan_out_output="result_0",
    )
    assert completed.event_type == "child_completed"

    failed = ChildFailed(
        timestamp=t1,
        run_id=run_id,
        event_type="child_failed",
        parent_task_id="parent-1",
        child_task_id="child-1",
        fan_out_index=0,
        error="some error",
    )
    assert failed.event_type == "child_failed"

    async with session_factory() as session:
        repo = RunRepository(session)
        fresh_run = await repo.get(run_id)

    child_events = [
        {
            "type": "child_spawned",
            "timestamp": t1,
            "payload": {
                "parent_task_id": "parent-1",
                "child_task_id": "child-1",
                "fan_out_index": 0,
            },
        },
        {
            "type": "child_completed",
            "timestamp": t1,
            "payload": {
                "parent_task_id": "parent-1",
                "child_task_id": "child-1",
                "fan_out_index": 0,
            },
        },
        {
            "type": "child_failed",
            "timestamp": t1,
            "payload": {
                "parent_task_id": "parent-1",
                "child_task_id": "child-1",
                "fan_out_index": 0,
                "error": "some error",
            },
        },
    ]

    # Should not raise; informational events leave run in DRAFT state
    replay_events(fresh_run, child_events)
    assert fresh_run.status == RunStatus.DRAFT


# ===========================================================================
# EVENT REPLAY — REVISION CYCLE RECOVERY
# (from test_event_recovery)
# ===========================================================================


async def test_replay_revision_cycle_recovery(session: AsyncSession) -> None:
    """Revision cycle: fail -> retry -> pass, then recover via events."""
    service = WorkflowService(session)
    run = _make_single_task_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs work")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.BUILDING  # revision

    # Fix and pass
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED

    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    fresh = _make_single_task_run()
    recovered = replay_events(fresh, events)

    assert recovered.status == RunStatus.COMPLETED
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.COMPLETED
    # Two building transitions: initial + revision
    assert recovered.steps[0].tasks[0].current_attempt == 2


# ===========================================================================
# EVENT REPLAY — GRADE SNAPSHOTS SURVIVE REPLAY
# (from test_event_recovery — unique scenario)
# ===========================================================================


async def test_replay_grade_snapshots_survive(session: AsyncSession) -> None:
    """Grade snapshots survive event replay recovery across revision cycles."""
    service = WorkflowService(session)
    run = _make_single_task_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")

    # Attempt 1: build, verify with bad grade -> revision
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs work")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.BUILDING

    # Attempt 2: fix grade, pass
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A", "Great")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED

    # Verify live state has snapshots
    live = await service.get_run("run-1")
    live_task = live.steps[0].tasks[0]
    assert len(live_task.attempts) == 2
    assert live_task.attempts[0].grade_snapshot[0].grade == "D"
    assert live_task.attempts[0].grade_snapshot[0].grade_reason == "Needs work"
    assert live_task.attempts[1].grade_snapshot[0].grade == "A"
    assert live_task.attempts[1].grade_snapshot[0].grade_reason == "Great"

    # Replay events on fresh run
    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    fresh = _make_single_task_run()
    recovered = replay_events(fresh, events)

    recovered_task = recovered.steps[0].tasks[0]
    assert len(recovered_task.attempts) == 2
    assert recovered_task.attempts[0].grade_snapshot[0].grade == "D"
    assert recovered_task.attempts[0].grade_snapshot[0].grade_reason == "Needs work"
    assert recovered_task.attempts[1].grade_snapshot[0].grade == "A"
    assert recovered_task.attempts[1].grade_snapshot[0].grade_reason == "Great"


# ===========================================================================
# EVENT REPLAY — RECOVERY WITH YAML ROUTINE FIXTURE
# (from test_event_recovery — unique scenario)
# ===========================================================================


async def test_replay_with_routine_fixture(session: AsyncSession) -> None:
    """Recovery works with runs created from actual YAML routines."""
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
    run = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
    )

    service = WorkflowService(session)
    await service.create_run(run)
    await service.apply_start_run(run.id)

    task_id = run.steps[0].tasks[0].id
    await service.start_task(run.id, task_id)

    store = EventStore(session)
    events = await store.get_events_for_run(run.id)

    # Create a fresh run from the same routine
    fresh = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
    )
    # Transplant the same IDs so event replay can find the right entities
    fresh.id = run.id
    fresh.steps[0].id = run.steps[0].id
    fresh.steps[0].tasks[0].id = task_id

    recovered = replay_events(fresh, events)
    assert recovered.status == RunStatus.ACTIVE
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.BUILDING
    assert recovered.steps[0].tasks[0].current_attempt == 1
