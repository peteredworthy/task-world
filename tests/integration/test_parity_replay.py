"""Parity test: round-trip event replay.

Drives real workflow lifecycles through the service layer, captures all persisted
events, destroys (resets) run state to simulate a crash, then replays events back
onto the blank run and asserts the reconstructed state matches the original.

Covers:
  - Linear execution: start → build → verify → complete across two steps
  - Pause/resume cycle: run.pause_reason reconstructed after pause, cleared after resume
  - Step skip: skipped step reconstructed with skip_reason
  - Old event format handling: new fields (last_error, start_commit) defaulting to None
"""

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from orchestrator.config.enums import ChecklistStatus, RunStatus, TaskStatus
from orchestrator.config.models import (
    RequirementConfig,
    RoutineConfig,
    StepCondition,
    StepConfig,
    TaskConfig,
)
from orchestrator.db import Base
from orchestrator.db import EventStore
from orchestrator.db import replay_events
from orchestrator.db import RunRepository
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run
from orchestrator.workflow.service import WorkflowService

_TMP_DIR = Path(__file__).parent.parent.parent / "tmp"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """File-based SQLite so events persist across session boundaries."""
    _TMP_DIR.mkdir(exist_ok=True)
    db_path = _TMP_DIR / f"test_replay_{uuid.uuid4().hex}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from orchestrator.db import create_session_factory

    yield create_session_factory(engine)
    await engine.dispose()
    db_path.unlink(missing_ok=True)
    Path(str(db_path) + "-wal").unlink(missing_ok=True)
    Path(str(db_path) + "-shm").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------


def _make_linear_routine() -> RoutineConfig:
    """Two-step routine with one task each."""
    req = RequirementConfig(id="R1", desc="Done")
    return RoutineConfig(
        id="replay-linear",
        name="Replay Linear Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step One",
                tasks=[
                    TaskConfig(
                        id="T-01", title="Task One", task_context="Do it", requirements=[req]
                    )
                ],
            ),
            StepConfig(
                id="S-02",
                title="Step Two",
                tasks=[
                    TaskConfig(
                        id="T-02", title="Task Two", task_context="Do it too", requirements=[req]
                    )
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(routine: RoutineConfig, run_id: str, embed_routine: bool = False) -> Run:
    run = create_run_from_routine(
        routine,
        repo_name=f"replay-repo-{run_id}",
        source_branch="main",
    )
    if embed_routine:
        # Store the routine config so engine can evaluate step conditions
        run.routine_embedded = routine.model_dump(mode="json")
    return run


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


async def _complete_task(service: WorkflowService, run_id: str, task_id: str) -> None:
    """Drive a task through start → checklist done → submit → grade A → complete."""
    await service.start_task(run_id, task_id)
    await service.update_checklist_item(run_id, task_id, "R1", ChecklistStatus.DONE)
    await service.submit_for_verification(run_id, task_id)
    await service.set_grade(run_id, task_id, "R1", "A", "Looks good")
    await service.complete_verification(run_id, task_id)


# ---------------------------------------------------------------------------
# Test: linear lifecycle round-trip
# ---------------------------------------------------------------------------


async def test_replay_linear_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full two-step linear run: destroy state, replay events, compare reconstructed state."""
    routine = _make_linear_routine()
    run = _make_run(routine, "linear-001")
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id
    task2_id = run.steps[1].tasks[0].id

    # Phase 1: drive full lifecycle
    async with session_factory() as session:
        svc = WorkflowService(session)
        await svc.create_run(run)
        await svc.start_run(run_id)
        await _complete_task(svc, run_id, task1_id)
        await _complete_task(svc, run_id, task2_id)

    # Phase 2: capture original state + all events, then reset + replay
    async with session_factory() as session:
        repo = RunRepository(session)
        original = await repo.get(run_id)

        # Capture original state for comparison
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

        # Get all events
        events = await _get_events(session, run_id)
        assert len(events) > 0, "Events should have been persisted"

        # Destroy (reset) run state to simulate crash
        _reset_run_to_draft(original)
        assert original.status == RunStatus.DRAFT

        # Replay events onto the blank run
        replay_events(original, events)

        # Assert reconstructed state matches original
        assert original.status == original_status, (
            f"Reconstructed status {original.status} != original {original_status}"
        )
        assert original.current_step_index == original_step_index, (
            f"Reconstructed step_index {original.current_step_index} != original {original_step_index}"
        )
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

        # Timestamps reconstructed
        assert original.started_at is not None
        assert original.completed_at is not None


# ---------------------------------------------------------------------------
# Test: pause/resume lifecycle round-trip
# ---------------------------------------------------------------------------


async def test_replay_pause_resume_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pause/resume cycle: pause_reason reconstructed from events, cleared on resume."""
    routine = _make_pause_routine()
    run = _make_run(routine, "pause-001")
    run_id = run.id

    async with session_factory() as session:
        svc = WorkflowService(session)
        await svc.create_run(run)
        await svc.start_run(run_id)
        # Pause with a specific reason
        await svc.pause_run(run_id, reason="server_shutdown")
        # Resume
        await svc.resume_run(run_id)

    async with session_factory() as session:
        repo = RunRepository(session)
        original = await repo.get(run_id)

        # After resume, status is ACTIVE and pause_reason cleared
        assert original.status == RunStatus.ACTIVE
        assert original.pause_reason is None

        events = await _get_events(session, run_id)

        # Identify pause and resume events
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
        assert len(resume_events) >= 1, "Should have at least one resume (active) event"

        # Verify enriched pause event has pause_reason
        pause_payload = pause_events[0]["payload"]
        assert pause_payload.get("pause_reason") == "server_shutdown", (
            f"pause_reason should be in event payload, got: {pause_payload}"
        )

        # Reset and replay
        _reset_run_to_draft(original)
        replay_events(original, events)

        # After full replay (including resume), run should be ACTIVE with no pause_reason
        assert original.status == RunStatus.ACTIVE
        assert original.pause_reason is None

        # Verify that replaying only up to the pause gives paused state
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
            f"pause_reason should be reconstructed as 'server_shutdown', got: {original.pause_reason}"
        )


# ---------------------------------------------------------------------------
# Test: step skip round-trip
# ---------------------------------------------------------------------------


async def test_replay_step_skip_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Step skip: skipped step and skip_reason reconstructed from step_skipped events."""
    routine = _make_skip_routine()
    run = _make_run(routine, "skip-001", embed_routine=True)
    run_id = run.id
    task1_id = run.steps[0].tasks[0].id
    task3_id = run.steps[2].tasks[0].id

    async with session_factory() as session:
        svc = WorkflowService(session)
        await svc.create_run(run)
        await svc.start_run(run_id)
        # Complete step 1 (step 2 auto-skipped by condition=false)
        await _complete_task(svc, run_id, task1_id)
        # Complete step 3
        await _complete_task(svc, run_id, task3_id)

    async with session_factory() as session:
        repo = RunRepository(session)
        original = await repo.get(run_id)

        # Verify the original state
        assert original.status == RunStatus.COMPLETED
        assert original.steps[0].completed is True
        assert original.steps[1].skipped is True
        assert original.steps[1].skip_reason is not None
        assert original.steps[2].completed is True

        original_skip_reason = original.steps[1].skip_reason

        # Verify step_skipped event was emitted with skip_reason in payload
        events = await _get_events(session, run_id)
        skip_events = [e for e in events if e["type"] == "step_skipped"]
        assert len(skip_events) >= 1, "Should have at least one step_skipped event"
        skip_payload = skip_events[0]["payload"]
        # New events have skip_reason; backward-compat: may also have reason
        assert (
            skip_payload.get("skip_reason") is not None or skip_payload.get("reason") is not None
        ), f"step_skipped payload should have skip_reason or reason: {skip_payload}"

        # Reset and replay
        _reset_run_to_draft(original)
        replay_events(original, events)

        # Verify reconstructed state
        assert original.status == RunStatus.COMPLETED
        assert original.steps[0].completed is True
        assert original.steps[1].skipped is True
        assert original.steps[1].skip_reason == original_skip_reason, (
            f"skip_reason should be reconstructed: got {original.steps[1].skip_reason!r}, "
            f"expected {original_skip_reason!r}"
        )
        assert original.steps[2].completed is True


# ---------------------------------------------------------------------------
# Test: backward compatibility — old events without new fields
# ---------------------------------------------------------------------------


async def test_replay_handles_old_event_format(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Old events without last_error/start_commit/end_commit replay without errors."""
    from datetime import datetime, timezone

    from orchestrator.config.enums import RunStatus, TaskStatus
    from orchestrator.db import replay_events

    routine = _make_linear_routine()
    run = _make_run(routine, "compat-001")
    run_id = run.id

    async with session_factory() as session:
        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

    # Craft old-format events (no last_error, no start_commit, no end_commit)
    t1 = datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 15, 10, 32, 0, tzinfo=timezone.utc)
    t3 = datetime(2025, 1, 15, 10, 33, 0, tzinfo=timezone.utc)
    t4 = datetime(2025, 1, 15, 10, 34, 0, tzinfo=timezone.utc)

    old_events = [
        {
            "type": "run_status_changed",
            "timestamp": t1,
            "payload": {
                # Old format: no last_error, no pause_reason
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
                # Old format: pause with no last_error
                "old_status": "active",
                "new_status": "paused",
                "run_id": run_id,
                "event_type": "run_status_changed",
                "timestamp": t2.isoformat(),
                # No pause_reason, no last_error
            },
        },
        {
            "type": "task_status_changed",
            "timestamp": t3,
            "payload": {
                # Old format: no start_commit
                "task_id": run.steps[0].tasks[0].id,
                "old_status": "pending",
                "new_status": "building",
                "run_id": run_id,
                "event_type": "task_status_changed",
                "timestamp": t3.isoformat(),
                # No start_commit
            },
        },
        {
            "type": "step_skipped",
            "timestamp": t4,
            "payload": {
                # Old format: uses "reason" instead of "skip_reason"
                "step_index": 1,
                "step_id": run.steps[1].id,
                "condition": "false",
                "reason": "old reason format",  # legacy field name
                # No skip_reason
                "run_id": run_id,
                "event_type": "step_skipped",
                "timestamp": t4.isoformat(),
            },
        },
    ]

    # Replay old-format events — should not raise
    async with session_factory() as session:
        repo = RunRepository(session)
        fresh_run = await repo.get(run_id)

    replay_events(fresh_run, old_events)

    # Verify graceful defaults for missing new fields
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


# ---------------------------------------------------------------------------
# Test: child event types are defined and handled without errors
# ---------------------------------------------------------------------------


async def test_child_event_types_in_replay(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Child lifecycle event types exist and replay without errors (informational)."""
    from datetime import datetime, timezone
    from orchestrator.workflow.events import ChildSpawned, ChildCompleted, ChildFailed

    routine = _make_pause_routine()
    run = _make_run(routine, "child-001")
    run_id = run.id

    async with session_factory() as session:
        repo = RunRepository(session)
        await repo.save(run)
        await session.commit()

    t1 = datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc)

    # Verify event types can be instantiated
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

    # Replay child events — they are informational and should not change state
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
    assert fresh_run.status == RunStatus.DRAFT  # unchanged (informational events)
