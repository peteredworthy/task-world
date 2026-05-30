"""Event-sourced worktree reset behavior."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from orchestrator.config import (
    ChecklistStatus,
    RequirementConfig,
    RoutineConfig,
    RunStatus,
    StepConfig,
    TaskConfig,
    TaskStatus,
)
from orchestrator.db import (
    EventV2Model,
    RunRepository,
    create_engine,
    create_session_factory,
    create_wired_event_store_v2,
    init_db,
)
from orchestrator.git import WorktreeCommitError, WorktreeResetError, reset_worktree_changes
from orchestrator.runners import AgentRunnerExecutor
from orchestrator.state import Attempt, create_run_from_routine
from orchestrator.workflow import LocalAutoVerifyRunner, PersistentEventEmitter, WorkflowService


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "tracked.txt").write_text("initial\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    return _git(repo, "rev-parse", "HEAD")


def _routine() -> RoutineConfig:
    return RoutineConfig(
        id="worktree-reset-routine",
        name="Worktree Reset Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do the work",
                        requirements=[RequirementConfig(id="R1", desc="Complete the work")],
                    )
                ],
            )
        ],
    )


async def _event_types(session, run_id: str) -> list[str]:
    result = await session.execute(
        select(EventV2Model.event_type)
        .where(EventV2Model.aggregate_id == run_id)
        .order_by(EventV2Model.position)
    )
    return list(result.scalars())


async def _events(session, run_id: str) -> list[tuple[str, dict]]:
    result = await session.execute(
        select(EventV2Model.event_type, EventV2Model.payload)
        .where(EventV2Model.aggregate_id == run_id)
        .order_by(EventV2Model.position)
    )
    return [(event_type, json.loads(payload)) for event_type, payload in result.all()]


@pytest.mark.asyncio
async def test_reset_worktree_changes_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    (repo / "tracked.txt").write_text("dirty\n")
    (repo / "untracked.txt").write_text("temporary\n")

    reset_worktree_changes(repo)
    reset_worktree_changes(repo)

    assert (repo / "tracked.txt").read_text() == "initial\n"
    assert not (repo / "untracked.txt").exists()
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.asyncio
async def test_prepare_worktree_reset_records_events_and_resets_before_resume(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_repo(repo_path)
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-reset-repo",
            source_branch="main",
        )
        run.status = RunStatus.PAUSED
        run.pause_reason = "executor_not_started"
        run.worktree_path = str(repo_path)
        run = await service.create_run(run)

        (repo_path / "tracked.txt").write_text("dirty\n")
        (repo_path / "untracked.txt").write_text("temporary\n")

        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            service_factory=lambda _session: service,
            spawn_agents=False,
        )
        prepared = await executor.prepare_worktree(
            run.id,
            service=service,
            reset_worktree=True,
        )
        assert prepared is True
        resumed = await service.apply_resume_run(run.id, resume_strategy="reset_worktree")

        assert resumed.status == RunStatus.ACTIVE
        assert (repo_path / "tracked.txt").read_text() == "initial\n"
        assert not (repo_path / "untracked.txt").exists()
        assert _git(repo_path, "status", "--porcelain") == ""
        events = await _event_types(session, run.id)
        assert "run_worktree_reset_requested" in events
        assert "run_worktree_reset_completed" in events
        assert events.index("run_worktree_reset_completed") < events.index("run_status_changed")

    await engine.dispose()


@pytest.mark.asyncio
async def test_prepare_worktree_reset_records_failure(
    tmp_path: Path,
) -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-reset-failure-repo",
            source_branch="main",
        )
        run.status = RunStatus.PAUSED
        run.pause_reason = "executor_not_started"
        run.worktree_path = str(tmp_path / "missing")
        run = await service.create_run(run)

        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            service_factory=lambda _session: service,
            spawn_agents=False,
        )
        prepared = await executor.prepare_worktree(
            run.id,
            service=service,
            reset_worktree=True,
        )

        persisted = await repo.get(run.id)
        assert prepared is False
        assert persisted.status == RunStatus.PAUSED
        events = await _event_types(session, run.id)
        assert "run_worktree_reset_requested" in events
        assert "run_worktree_reset_failed" in events
        result = await session.execute(
            select(EventV2Model.event_type, EventV2Model.payload).where(
                EventV2Model.aggregate_id == run.id
            )
        )
        active_status_events = [
            payload
            for event_type, payload in result.all()
            if event_type == "run_status_changed"
            and json.loads(payload).get("new_status") == "active"
        ]
        assert active_status_events == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_resume_revert_records_reset_before_task_reverted(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    initial_commit = _init_repo(repo_path)
    (repo_path / "tracked.txt").write_text("later\n")
    _git(repo_path, "add", "tracked.txt")
    _git(repo_path, "commit", "-m", "later")

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-resume-revert-repo",
            source_branch="main",
        )
        run.status = RunStatus.PAUSED
        run.worktree_path = str(repo_path)
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.current_attempt = 1
        task.attempts.append(
            Attempt(
                attempt_num=1,
                started_at=datetime.now(timezone.utc),
                start_commit=initial_commit,
            )
        )
        run = await service.create_run(run)
        task_id = run.steps[0].tasks[0].id

        resumed = await service.apply_resume_run(run.id, resume_strategy="revert")

        assert resumed.status == RunStatus.ACTIVE
        assert _git(repo_path, "rev-parse", "HEAD") == initial_commit
        assert (repo_path / "tracked.txt").read_text() == "initial\n"
        persisted_task = (await repo.get(run.id)).steps[0].tasks[0]
        assert persisted_task.id == task_id
        assert persisted_task.status == TaskStatus.BUILDING
        events = await _event_types(session, run.id)
        assert events.index("run_worktree_reset_requested") < events.index(
            "run_worktree_reset_completed"
        )
        assert events.index("run_worktree_reset_completed") < events.index("task_reverted")
        assert events.index("task_reverted") < events.index("run_status_changed")

    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_submission_records_commit_events_before_task_transition(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_repo(repo_path)
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-commit-repo",
            source_branch="main",
        )
        run.status = RunStatus.ACTIVE
        run.worktree_path = str(repo_path)
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.current_attempt = 1
        task.checklist[0].status = ChecklistStatus.DONE
        task.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
        run = await service.create_run(run)
        task_id = run.steps[0].tasks[0].id

        (repo_path / "tracked.txt").write_text("builder work\n")

        result = await service.apply_submission(run.id, task_id)

        assert result.new_status == TaskStatus.VERIFYING
        persisted = await repo.get(run.id)
        persisted_task = persisted.steps[0].tasks[0]
        assert persisted_task.status == TaskStatus.VERIFYING
        assert persisted_task.attempts[-1].end_commit == _git(repo_path, "rev-parse", "HEAD")

        events = await _events(session, run.id)
        event_types = [event_type for event_type, _payload in events]
        completed_payload = next(
            payload
            for event_type, payload in events
            if event_type == "run_worktree_commit_completed"
        )
        assert completed_payload["created_commit"] is True
        assert completed_payload["commit_sha"] == persisted_task.attempts[-1].end_commit
        assert event_types.index("run_worktree_commit_requested") < event_types.index(
            "run_worktree_commit_completed"
        )
        assert event_types.index("run_worktree_commit_completed") < event_types.index(
            "task_status_changed"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_submission_records_noop_commit_event_when_clean(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    initial_commit = _init_repo(repo_path)
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-commit-noop-repo",
            source_branch="main",
        )
        run.status = RunStatus.ACTIVE
        run.worktree_path = str(repo_path)
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.current_attempt = 1
        task.checklist[0].status = ChecklistStatus.DONE
        task.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
        run = await service.create_run(run)
        task_id = run.steps[0].tasks[0].id

        await service.apply_submission(run.id, task_id)

        events = await _events(session, run.id)
        completed_payload = next(
            payload
            for event_type, payload in events
            if event_type == "run_worktree_commit_completed"
        )
        assert completed_payload["created_commit"] is False
        assert completed_payload["head_before"] == initial_commit
        assert completed_payload["head_after"] == initial_commit
        assert completed_payload["commit_sha"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_submission_commit_failure_leaves_task_building(
    tmp_path: Path,
) -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-commit-failure-repo",
            source_branch="main",
        )
        run = await service.create_run(run)
        run = await service.set_worktree_path(run.id, str(tmp_path / "missing-worktree"))
        await service.apply_start_run(run.id)
        await service.start_task(run.id, run.steps[0].tasks[0].id)
        await service.update_checklist_item(
            run.id,
            run.steps[0].tasks[0].id,
            "R1",
            ChecklistStatus.DONE,
        )
        task_id = run.steps[0].tasks[0].id

        with pytest.raises(WorktreeCommitError):
            await service.apply_submission(run.id, task_id)

        persisted = await repo.get(run.id)
        persisted_task = persisted.steps[0].tasks[0]
        assert persisted_task.status == TaskStatus.BUILDING
        assert persisted_task.attempts[-1].end_commit is None
        events = await _event_types(session, run.id)
        assert "run_worktree_commit_requested" in events
        assert "run_worktree_commit_failed" in events
        verifying_events = [
            payload
            for event_type, payload in await _events(session, run.id)
            if event_type == "task_status_changed"
            and payload.get("new_status") == TaskStatus.VERIFYING.value
        ]
        assert verifying_events == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_recover_run_reset_branch_records_events_before_recovery_state(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    initial_commit = _init_repo(repo_path)
    (repo_path / "tracked.txt").write_text("later\n")
    _git(repo_path, "add", "tracked.txt")
    _git(repo_path, "commit", "-m", "later")

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-recover-repo",
            source_branch="main",
        )
        run.status = RunStatus.FAILED
        run.worktree_path = str(repo_path)
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.FAILED
        task.current_attempt = 1
        task.attempts.append(
            Attempt(
                attempt_num=1,
                started_at=datetime.now(timezone.utc),
                start_commit=initial_commit,
            )
        )
        run = await service.create_run(run)

        result = await service.recover_run(run.id, target_task_id=task.id, reset_branch=True)

        assert result.status == "paused"
        assert _git(repo_path, "rev-parse", "HEAD") == initial_commit
        assert (repo_path / "tracked.txt").read_text() == "initial\n"
        events = await _event_types(session, run.id)
        assert events.index("run_worktree_reset_requested") < events.index(
            "run_worktree_reset_completed"
        )
        assert events.index("run_worktree_reset_completed") < events.index("run_status_changed")

    await engine.dispose()


@pytest.mark.asyncio
async def test_recover_run_reset_branch_failure_leaves_recovery_state_unchanged(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    initial_commit = _init_repo(repo_path)
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=_routine(),
            repo_name="worktree-recover-failure-repo",
            source_branch="main",
        )
        run.status = RunStatus.FAILED
        run.worktree_path = str(tmp_path / "missing-worktree")
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.FAILED
        task.current_attempt = 1
        task.attempts.append(
            Attempt(
                attempt_num=1,
                started_at=datetime.now(timezone.utc),
                start_commit=initial_commit,
            )
        )
        run = await service.create_run(run)
        task_id = run.steps[0].tasks[0].id

        with pytest.raises(WorktreeResetError):
            await service.recover_run(run.id, target_task_id=task_id, reset_branch=True)

        persisted = await repo.get(run.id)
        persisted_task = persisted.steps[0].tasks[0]
        assert persisted.status == RunStatus.FAILED
        assert persisted_task.status == TaskStatus.FAILED
        assert persisted_task.current_attempt == 1
        assert len(persisted_task.attempts) == 1

        events = await _event_types(session, run.id)
        assert "run_worktree_reset_requested" in events
        assert "run_worktree_reset_failed" in events
        assert "task_reverted" not in events
        assert "run_status_changed" not in events

    await engine.dispose()
