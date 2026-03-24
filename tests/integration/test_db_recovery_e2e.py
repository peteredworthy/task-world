"""E2E integration tests for database backup, restore, and journal replay recovery."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.config.enums import (
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db import create_backup, restore_backup
from orchestrator.db import Base
from orchestrator.db import JsonlEventJournal
from orchestrator.db import EventStore
from orchestrator.db import replay_journal_to_repository
from orchestrator.db import replay_events
from orchestrator.db import CheckpointRepository, RunRepository
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.workflow.events import (
    GradeDetail,
    GradesEvaluated,
    RunStatusChanged,
    StepCompleted,
    TaskStatusChanged,
    WorkflowEvent,
)


def _make_run(
    run_id: str = "run-1",
    task_ids: tuple[str, ...] = ("task-1", "task-2"),
) -> Run:
    """Create a Run with one step containing two tasks."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    tasks = [
        TaskState(
            id=tid,
            config_id=f"T-{i + 1:02d}",
            status=TaskStatus.PENDING,
            checklist=[
                ChecklistItem(
                    req_id=f"R{i + 1}",
                    desc=f"Requirement for task {i + 1}",
                    priority=Priority.CRITICAL,
                )
            ],
            max_attempts=3,
        )
        for i, tid in enumerate(task_ids)
    ]
    return Run(
        id=run_id,
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=tasks,
            )
        ],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[async_sessionmaker[AsyncSession], Path], None]:
    """Create a file-based SQLite DB for backup/restore tests."""
    db_path = tmp_path / "orchestrator.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory, db_path
    await engine.dispose()


async def _emit_events_and_update_run(
    session: AsyncSession,
    journal: JsonlEventJournal,
    repo: RunRepository,
    run: Run,
    events: list[WorkflowEvent],
) -> Run:
    """Emit events to DB+journal AND apply them to the run state, then save.

    This mirrors what the real app does: WorkflowService updates the domain
    model AND persists events in the same transaction.
    """
    store = EventStore(session, journal=journal)
    for event in events:
        await store.append(event)

    # Build replay-compatible event dicts and apply to run
    event_dicts = [
        {
            "type": e.event_type,
            "timestamp": e.timestamp,
            "payload": _event_to_payload(e),
        }
        for e in events
    ]
    replay_events(run, event_dicts)
    await repo.save(run)
    return run


def _event_to_payload(event: WorkflowEvent) -> dict:
    """Convert a WorkflowEvent to the payload dict format used by replay_events."""
    import dataclasses
    import json
    from orchestrator.time_utils import format_utc_datetime

    data = dataclasses.asdict(event)

    def _json_default(obj: object) -> str:
        if isinstance(obj, datetime):
            return format_utc_datetime(obj)
        if hasattr(obj, "value"):
            return obj.value  # type: ignore[return-value]
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    return json.loads(json.dumps(data, default=_json_default))


async def test_full_recovery_backup_and_replay(
    file_db: tuple[async_sessionmaker[AsyncSession], Path],
    tmp_path: Path,
) -> None:
    """Full recovery cycle: create state, backup, add more events, destroy DB, restore, replay."""
    session_factory, db_path = file_db
    journal_path = tmp_path / "journal" / "history.jsonl"
    backup_dir = tmp_path / "backups"

    t1 = datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 15, 10, 32, 0, tzinfo=timezone.utc)
    t3 = datetime(2025, 1, 15, 10, 33, 0, tzinfo=timezone.utc)
    t4 = datetime(2025, 1, 15, 10, 34, 0, tzinfo=timezone.utc)
    t5 = datetime(2025, 1, 15, 10, 35, 0, tzinfo=timezone.utc)
    t6 = datetime(2025, 1, 15, 10, 36, 0, tzinfo=timezone.utc)
    t7 = datetime(2025, 1, 15, 10, 37, 0, tzinfo=timezone.utc)

    # Phase 1: Create run and apply initial events (run ACTIVE, task-1 through full lifecycle)
    async with session_factory() as session:
        repo = RunRepository(session)
        journal = JsonlEventJournal(journal_path)
        run = _make_run()
        await repo.save(run)

        run = await _emit_events_and_update_run(
            session,
            journal,
            repo,
            run,
            [
                RunStatusChanged(
                    timestamp=t1,
                    run_id="run-1",
                    event_type="run_status_changed",
                    old_status=RunStatus.DRAFT,
                    new_status=RunStatus.ACTIVE,
                ),
                TaskStatusChanged(
                    timestamp=t2,
                    run_id="run-1",
                    event_type="task_status_changed",
                    task_id="task-1",
                    old_status=TaskStatus.PENDING,
                    new_status=TaskStatus.BUILDING,
                ),
                TaskStatusChanged(
                    timestamp=t3,
                    run_id="run-1",
                    event_type="task_status_changed",
                    task_id="task-1",
                    old_status=TaskStatus.BUILDING,
                    new_status=TaskStatus.VERIFYING,
                ),
                GradesEvaluated(
                    timestamp=t4,
                    run_id="run-1",
                    event_type="grades_evaluated",
                    task_id="task-1",
                    passed=True,
                    grade_details=[GradeDetail(req_id="R1", grade="A", grade_reason="Excellent")],
                ),
                TaskStatusChanged(
                    timestamp=t5,
                    run_id="run-1",
                    event_type="task_status_changed",
                    task_id="task-1",
                    old_status=TaskStatus.VERIFYING,
                    new_status=TaskStatus.COMPLETED,
                ),
            ],
        )
        await session.commit()

    # Phase 2: Take backup (captures state with task-1 completed, task-2 pending)
    backup_meta = await create_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        journal_path=journal_path,
    )
    assert backup_meta.journal_sequence_marker >= 4  # at least 5 events (0-4)

    # Phase 3: Emit more events after backup (task-2 transitions)
    async with session_factory() as session:
        repo = RunRepository(session)
        journal = JsonlEventJournal(journal_path)
        run = await repo.get("run-1")

        run = await _emit_events_and_update_run(
            session,
            journal,
            repo,
            run,
            [
                TaskStatusChanged(
                    timestamp=t6,
                    run_id="run-1",
                    event_type="task_status_changed",
                    task_id="task-2",
                    old_status=TaskStatus.PENDING,
                    new_status=TaskStatus.BUILDING,
                ),
                TaskStatusChanged(
                    timestamp=t7,
                    run_id="run-1",
                    event_type="task_status_changed",
                    task_id="task-2",
                    old_status=TaskStatus.BUILDING,
                    new_status=TaskStatus.VERIFYING,
                ),
            ],
        )
        await session.commit()

    # Phase 4: Destroy DB
    db_path.unlink()
    assert not db_path.exists()

    # Phase 5: Restore from backup
    meta_path = backup_dir / f"orchestrator-{backup_meta.backup_id}.backup-meta.json"
    await restore_backup(meta_path, db_path)
    assert db_path.exists()

    # Phase 6: Re-create engine for restored DB and replay journal
    restored_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    restored_sf = async_sessionmaker(restored_engine, expire_on_commit=False)

    try:
        # Verify restored DB has pre-backup state
        async with restored_sf() as session:
            repo = RunRepository(session)
            restored_run = await repo.get("run-1")
            assert restored_run.status == RunStatus.ACTIVE
            assert restored_run.steps[0].tasks[0].status == TaskStatus.COMPLETED
            assert restored_run.steps[0].tasks[1].status == TaskStatus.PENDING

        # Set checkpoint at backup marker so replay only applies post-backup events
        async with restored_sf() as session:
            cp_repo = CheckpointRepository(session)
            await cp_repo.upsert_checkpoint(
                journal_path=str(journal_path),
                last_applied_sequence=backup_meta.journal_sequence_marker,
                last_applied_timestamp=t5,
            )
            await session.commit()

        # Replay journal from checkpoint
        async with restored_sf() as session:
            repo = RunRepository(session)
            cp_repo = CheckpointRepository(session)
            summary = await replay_journal_to_repository(
                repo,
                journal_path=journal_path,
                run_ids={"run-1"},
                batch_size=10,
                from_checkpoint=True,
                checkpoint_repo=cp_repo,
            )

        # Verify replay applied only post-backup events
        assert summary.replayed_events == 2  # task-2 BUILDING + VERIFYING
        assert summary.updated_runs == 1
        assert summary.missing_runs == 0
        assert summary.resumed_from_sequence == backup_meta.journal_sequence_marker

        # Verify final state
        async with restored_sf() as session:
            repo = RunRepository(session)
            final_run = await repo.get("run-1")

            assert final_run.status == RunStatus.ACTIVE

            task_1 = final_run.steps[0].tasks[0]
            assert task_1.status == TaskStatus.COMPLETED
            assert task_1.current_attempt == 1
            assert len(task_1.attempts) == 1
            assert task_1.attempts[0].grade_snapshot[0].grade == "A"
            assert task_1.attempts[0].grade_snapshot[0].grade_reason == "Excellent"

            task_2 = final_run.steps[0].tasks[1]
            assert task_2.status == TaskStatus.VERIFYING
            assert task_2.current_attempt == 1
            assert len(task_2.attempts) == 1
    finally:
        await restored_engine.dispose()


async def test_duplicate_replay_produces_no_changes(
    file_db: tuple[async_sessionmaker[AsyncSession], Path],
    tmp_path: Path,
) -> None:
    """Replaying journal twice with checkpoint produces no changes on second pass."""
    session_factory, db_path = file_db
    journal_path = tmp_path / "journal" / "history.jsonl"

    t1 = datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 15, 10, 32, 0, tzinfo=timezone.utc)
    t3 = datetime(2025, 1, 15, 10, 33, 0, tzinfo=timezone.utc)

    # Create run and emit events
    async with session_factory() as session:
        repo = RunRepository(session)
        journal = JsonlEventJournal(journal_path)
        run = _make_run()
        await repo.save(run)
        await session.commit()

    async with session_factory() as session:
        journal = JsonlEventJournal(journal_path)
        store = EventStore(session, journal=journal)
        await store.append(
            RunStatusChanged(
                timestamp=t1,
                run_id="run-1",
                event_type="run_status_changed",
                old_status=RunStatus.DRAFT,
                new_status=RunStatus.ACTIVE,
            )
        )
        await store.append(
            TaskStatusChanged(
                timestamp=t2,
                run_id="run-1",
                event_type="task_status_changed",
                task_id="task-1",
                old_status=TaskStatus.PENDING,
                new_status=TaskStatus.BUILDING,
            )
        )
        await store.append(
            TaskStatusChanged(
                timestamp=t3,
                run_id="run-1",
                event_type="task_status_changed",
                task_id="task-1",
                old_status=TaskStatus.BUILDING,
                new_status=TaskStatus.VERIFYING,
            )
        )
        await session.commit()

    # Corrupt state to simulate restoring from stale backup
    async with session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get("run-1")
        stale_run.status = RunStatus.DRAFT
        stale_run.started_at = None
        stale_run.steps[0].tasks[0].status = TaskStatus.PENDING
        stale_run.steps[0].tasks[0].current_attempt = 0
        stale_run.steps[0].tasks[0].attempts = []
        await repo.save(stale_run)
        await session.commit()

    # First replay
    async with session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        first_summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={"run-1"},
            batch_size=100,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    assert first_summary.replayed_events == 3
    assert first_summary.updated_runs == 1
    first_checkpoint = first_summary.checkpoint_sequence
    assert first_checkpoint is not None

    # Record state after first replay
    async with session_factory() as session:
        repo = RunRepository(session)
        run_after_first = await repo.get("run-1")
        status_after = run_after_first.status
        task_status_after = run_after_first.steps[0].tasks[0].status
        attempt_count_after = len(run_after_first.steps[0].tasks[0].attempts)

    # Second replay -- checkpoint should skip everything
    async with session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        second_summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={"run-1"},
            batch_size=100,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    assert second_summary.resumed_from_sequence == first_checkpoint
    assert second_summary.replayed_events == 0
    assert second_summary.updated_runs == 0

    # Verify state is identical
    async with session_factory() as session:
        repo = RunRepository(session)
        run_after_second = await repo.get("run-1")
        assert run_after_second.status == status_after
        assert run_after_second.steps[0].tasks[0].status == task_status_after
        assert len(run_after_second.steps[0].tasks[0].attempts) == attempt_count_after


async def test_interrupted_replay_resumes_from_checkpoint(
    file_db: tuple[async_sessionmaker[AsyncSession], Path],
    tmp_path: Path,
) -> None:
    """Batch replay with checkpoint resumes correctly after adding more events."""
    session_factory, db_path = file_db
    journal_path = tmp_path / "journal" / "history.jsonl"

    # Create run
    async with session_factory() as session:
        repo = RunRepository(session)
        run = _make_run()
        await repo.save(run)
        await session.commit()

    # Emit 10 events (sequence 0-9)
    ts = [datetime(2025, 1, 15, 10, 30 + i, 0, tzinfo=timezone.utc) for i in range(1, 11)]
    phase1_events: list[WorkflowEvent] = [
        RunStatusChanged(
            timestamp=ts[0],
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        ),
        TaskStatusChanged(
            timestamp=ts[1],
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
        TaskStatusChanged(
            timestamp=ts[2],
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-1",
            old_status=TaskStatus.BUILDING,
            new_status=TaskStatus.VERIFYING,
        ),
        GradesEvaluated(
            timestamp=ts[3],
            run_id="run-1",
            event_type="grades_evaluated",
            task_id="task-1",
            passed=True,
            grade_details=[GradeDetail(req_id="R1", grade="A", grade_reason="Good")],
        ),
        TaskStatusChanged(
            timestamp=ts[4],
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-1",
            old_status=TaskStatus.VERIFYING,
            new_status=TaskStatus.COMPLETED,
        ),
        TaskStatusChanged(
            timestamp=ts[5],
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-2",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
        TaskStatusChanged(
            timestamp=ts[6],
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-2",
            old_status=TaskStatus.BUILDING,
            new_status=TaskStatus.VERIFYING,
        ),
        GradesEvaluated(
            timestamp=ts[7],
            run_id="run-1",
            event_type="grades_evaluated",
            task_id="task-2",
            passed=True,
            grade_details=[GradeDetail(req_id="R2", grade="B", grade_reason="OK")],
        ),
        TaskStatusChanged(
            timestamp=ts[8],
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-2",
            old_status=TaskStatus.VERIFYING,
            new_status=TaskStatus.COMPLETED,
        ),
        StepCompleted(
            timestamp=ts[9],
            run_id="run-1",
            event_type="step_completed",
            step_index=0,
            step_id="step-1",
        ),
    ]

    async with session_factory() as session:
        journal = JsonlEventJournal(journal_path)
        store = EventStore(session, journal=journal)
        for event in phase1_events:
            await store.append(event)
        await session.commit()

    # Corrupt state to simulate stale backup
    async with session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get("run-1")
        stale_run.status = RunStatus.DRAFT
        stale_run.started_at = None
        for task in stale_run.steps[0].tasks:
            task.status = TaskStatus.PENDING
            task.current_attempt = 0
            task.attempts = []
        stale_run.steps[0].completed = False
        await repo.save(stale_run)
        await session.commit()

    # Replay with batch_size=3 (batches: [0-2], [3-5], [6-8], [9])
    async with session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        summary1 = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={"run-1"},
            batch_size=3,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    assert summary1.replayed_events == 10
    assert summary1.updated_runs == 1
    assert summary1.checkpoint_sequence == 9  # last event sequence
    assert summary1.resumed_from_sequence is None  # first replay, no prior checkpoint

    # Verify checkpoint was persisted at sequence 9
    async with session_factory() as session:
        cp_repo = CheckpointRepository(session)
        checkpoint = await cp_repo.get_checkpoint(str(journal_path))
        assert checkpoint is not None
        assert checkpoint.last_applied_sequence == 9

    # Verify state after first replay
    async with session_factory() as session:
        repo = RunRepository(session)
        run_mid = await repo.get("run-1")
        assert run_mid.status == RunStatus.ACTIVE
        assert run_mid.steps[0].completed is True
        assert run_mid.steps[0].tasks[0].status == TaskStatus.COMPLETED
        assert run_mid.steps[0].tasks[1].status == TaskStatus.COMPLETED

    # Add 5 more events (sequence 10-14)
    ts2 = [datetime(2025, 1, 15, 10, 41 + i, 0, tzinfo=timezone.utc) for i in range(5)]
    phase2_events: list[WorkflowEvent] = [
        RunStatusChanged(
            timestamp=ts2[0],
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.ACTIVE,
            new_status=RunStatus.COMPLETED,
        ),
        # Extra run_status_changed events (idempotent -- no state change)
        RunStatusChanged(
            timestamp=ts2[1],
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.COMPLETED,
            new_status=RunStatus.COMPLETED,
        ),
        RunStatusChanged(
            timestamp=ts2[2],
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.COMPLETED,
            new_status=RunStatus.COMPLETED,
        ),
        RunStatusChanged(
            timestamp=ts2[3],
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.COMPLETED,
            new_status=RunStatus.COMPLETED,
        ),
        RunStatusChanged(
            timestamp=ts2[4],
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.COMPLETED,
            new_status=RunStatus.COMPLETED,
        ),
    ]

    async with session_factory() as session:
        journal = JsonlEventJournal(journal_path)
        store = EventStore(session, journal=journal)
        for event in phase2_events:
            await store.append(event)
        await session.commit()

    # Replay from checkpoint -- should only process events 10-14
    async with session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        summary2 = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={"run-1"},
            batch_size=3,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    assert summary2.resumed_from_sequence == 9
    assert summary2.replayed_events == 5  # events 10-14
    assert summary2.checkpoint_sequence == 14

    # Verify final checkpoint
    async with session_factory() as session:
        cp_repo = CheckpointRepository(session)
        final_cp = await cp_repo.get_checkpoint(str(journal_path))
        assert final_cp is not None
        assert final_cp.last_applied_sequence == 14

    # Verify final state
    async with session_factory() as session:
        repo = RunRepository(session)
        final_run = await repo.get("run-1")
        assert final_run.status == RunStatus.COMPLETED
        assert final_run.steps[0].completed is True
        assert final_run.steps[0].tasks[0].status == TaskStatus.COMPLETED
        assert final_run.steps[0].tasks[1].status == TaskStatus.COMPLETED
