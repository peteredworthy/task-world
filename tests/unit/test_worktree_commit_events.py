"""Event-sourced worktree auto-commit behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

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
from orchestrator.git import WorktreeCommitError
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
        id="worktree-commit-routine",
        name="Worktree Commit Routine",
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


async def _events(session, run_id: str) -> list[dict[str, Any]]:
    result = await session.execute(
        select(EventV2Model.event_type, EventV2Model.payload)
        .where(EventV2Model.aggregate_id == run_id)
        .order_by(EventV2Model.position)
    )
    return [
        {"event_type": event_type, "payload": json.loads(payload)}
        for event_type, payload in result.all()
    ]


async def _service_with_building_run(repo_path: Path):
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    session = session_factory()
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
    task.checklist[0].status = ChecklistStatus.DONE
    task.current_attempt = 1
    task.attempts.append(Attempt(attempt_num=1))
    run = await service.create_run(run)
    return engine, session, service, run.id, task.id


@pytest.mark.asyncio
async def test_submit_auto_commit_records_completed_before_verifying(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    initial_head = _init_repo(repo_path)
    engine, session, service, run_id, task_id = await _service_with_building_run(repo_path)
    try:
        (repo_path / "tracked.txt").write_text("builder change\n")

        result = await service.submit_for_verification(run_id, task_id)

        assert result.new_status == TaskStatus.VERIFYING
        head_after = _git(repo_path, "rev-parse", "HEAD")
        assert head_after != initial_head
        events = await _events(session, run_id)
        event_types = [event["event_type"] for event in events]
        commit_completed_index = event_types.index("run_worktree_commit_completed")
        task_changed_index = event_types.index("task_status_changed")
        assert commit_completed_index < task_changed_index
        completed = events[commit_completed_index]["payload"]
        assert completed["task_id"] == task_id
        assert completed["created_commit"] is True
        assert completed["message"] == f"Auto-commit builder changes for task {task_id}"
        assert completed["head_after"] == head_after
        task_event = events[task_changed_index]["payload"]
        assert task_event["new_status"] == "verifying"
        assert task_event["end_commit"] == head_after
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_submit_auto_commit_noop_records_completed_false(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    head = _init_repo(repo_path)
    engine, session, service, run_id, task_id = await _service_with_building_run(repo_path)
    try:
        result = await service.submit_for_verification(run_id, task_id)

        assert result.new_status == TaskStatus.VERIFYING
        events = await _events(session, run_id)
        completed = next(
            event["payload"]
            for event in events
            if event["event_type"] == "run_worktree_commit_completed"
        )
        assert completed["created_commit"] is False
        assert completed["head_before"] == head
        assert completed["head_after"] == head
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_submit_auto_commit_failure_blocks_verifying(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_repo(repo_path)
    engine, session, service, run_id, task_id = await _service_with_building_run(repo_path)
    try:
        (repo_path / "tracked.txt").write_text("builder change\n")
        (repo_path / ".git" / "index.lock").write_text("locked\n")

        with pytest.raises(WorktreeCommitError):
            await service.submit_for_verification(run_id, task_id)

        run = await service.get_run(run_id)
        task = run.steps[0].tasks[0]
        assert task.status == TaskStatus.BUILDING
        assert task.attempts[-1].end_commit is None
        events = await _events(session, run_id)
        event_types = [event["event_type"] for event in events]
        assert "run_worktree_commit_requested" in event_types
        assert "run_worktree_commit_failed" in event_types
        assert "task_status_changed" not in event_types
    finally:
        lock_path = repo_path / ".git" / "index.lock"
        if lock_path.exists():
            lock_path.unlink()
        await session.close()
        await engine.dispose()
