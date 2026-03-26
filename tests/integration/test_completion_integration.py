"""Integration tests for completion actions through WorkflowService.

Tests completion handler is called when runs reach terminal states.
"""

import subprocess
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.config.global_config import GlobalConfig, PathsConfig
from orchestrator.config.models import (
    RequirementConfig,
    RetryConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.git.worktree import WorktreeManager
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Attempt
from orchestrator.workflow.service import WorkflowService


@pytest.fixture
def git_repo() -> Generator[tuple[Path, Path], None, None]:
    """Create a temporary git repository and worktrees directory.

    Yields:
        Tuple of (repo_path, worktrees_dir)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        repo_path = base / "repo"
        worktrees_dir = base / "worktrees"
        repo_path.mkdir()
        worktrees_dir.mkdir()

        # Initialize git repo
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create and commit an initial file
        initial_file = repo_path / "README.md"
        initial_file.write_text("# Test Project\n")
        subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        yield repo_path, worktrees_dir


@pytest.fixture
def simple_routine() -> RoutineConfig:
    """Create a simple routine config for testing."""
    return RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=[
            StepConfig(
                id="step-1",
                title="Test Step",
                tasks=[
                    TaskConfig(
                        id="task-1",
                        title="Test Task",
                        task_context="Complete the test task",
                        retry=RetryConfig(max_attempts=3),
                        requirements=[
                            RequirementConfig(
                                id="req-1",
                                desc="Complete the task",
                                priority=Priority.EXPECTED,
                            )
                        ],
                    )
                ],
            )
        ],
    )


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create an in-memory database session."""
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)

    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_worktree_deleted_on_successful_completion(
    db_session: AsyncSession, git_repo: tuple[Path, Path], simple_routine: RoutineConfig
) -> None:
    """Test that worktree is deleted when run completes successfully with delete flag."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree
    run_id = "test-run-1"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Create a run with worktree configured (use "repo" to match directory name)
    run = create_run_from_routine(simple_routine, "repo", source_branch="main")
    run.id = run_id
    run.worktree_path = str(wt_info.path)
    run.delete_worktree_on_completion = True
    run.status = RunStatus.ACTIVE

    # Grade all requirements as passing (to trigger completion)
    task = run.steps[0].tasks[0]
    task.status = TaskStatus.VERIFYING
    for item in task.checklist:
        item.grade = "A"
        item.status = ChecklistStatus.DONE

    # Create global config with paths
    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repo_path.parent),
            worktrees_dir=str(worktrees_dir),
        )
    )

    # Create workflow service with global config
    service = WorkflowService(db_session, global_config=global_config)
    await service.create_run(run)

    # Complete verification (should complete the run and delete worktree)
    result = await service.complete_verification(run.id, task.id)

    assert result.success
    assert result.new_status == TaskStatus.COMPLETED

    # Verify run completed
    updated_run = await service.get_run(run.id)
    assert updated_run.status == RunStatus.COMPLETED

    # Verify worktree was deleted
    assert not wt_info.path.exists()


@pytest.mark.asyncio
async def test_worktree_kept_when_flag_false(
    db_session: AsyncSession, git_repo: tuple[Path, Path], simple_routine: RoutineConfig
) -> None:
    """Test that worktree is kept when delete_worktree_on_completion is False."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree
    run_id = "test-run-2"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Create a run with delete flag set to False (use "repo" to match directory name)
    run = create_run_from_routine(simple_routine, "repo", source_branch="main")
    run.id = run_id
    run.worktree_path = str(wt_info.path)
    run.delete_worktree_on_completion = False  # Keep worktree
    run.status = RunStatus.ACTIVE

    # Grade all requirements as passing
    task = run.steps[0].tasks[0]
    task.status = TaskStatus.VERIFYING
    for item in task.checklist:
        item.grade = "A"
        item.status = ChecklistStatus.DONE

    # Create global config with paths
    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repo_path.parent),
            worktrees_dir=str(worktrees_dir),
        )
    )

    # Create workflow service with global config
    service = WorkflowService(db_session, global_config=global_config)
    await service.create_run(run)

    # Complete verification
    result = await service.complete_verification(run.id, task.id)

    assert result.success
    assert result.new_status == TaskStatus.COMPLETED

    # Verify run completed
    updated_run = await service.get_run(run.id)
    assert updated_run.status == RunStatus.COMPLETED

    # Verify worktree still exists
    assert wt_info.path.exists()

    # Cleanup
    manager.delete(run_id, force=True)


@pytest.mark.asyncio
async def test_worktree_deleted_on_cancelled_run(
    db_session: AsyncSession, git_repo: tuple[Path, Path], simple_routine: RoutineConfig
) -> None:
    """Test that worktree is deleted when run is cancelled with delete flag."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree
    run_id = "test-run-3"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Create a run with worktree configured (use "repo" to match directory name)
    run = create_run_from_routine(simple_routine, "repo", source_branch="main")
    run.id = run_id
    run.worktree_path = str(wt_info.path)
    run.delete_worktree_on_completion = True
    run.status = RunStatus.ACTIVE

    # Create global config with paths
    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repo_path.parent),
            worktrees_dir=str(worktrees_dir),
        )
    )

    # Create workflow service with global config
    service = WorkflowService(db_session, global_config=global_config)
    await service.create_run(run)

    # Cancel the run
    cancelled_run = await service.cancel_run(run.id, reason="Test cancellation")

    # Verify run failed
    assert cancelled_run.status == RunStatus.FAILED

    # Verify worktree was deleted
    assert not wt_info.path.exists()


@pytest.mark.asyncio
async def test_worktree_deleted_on_failed_run(
    db_session: AsyncSession, git_repo: tuple[Path, Path]
) -> None:
    """Test that worktree is deleted when run fails with delete flag."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree
    run_id = "test-run-4"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Create a routine with a task that will fail (max_attempts reached)
    routine = RoutineConfig(
        id="test-routine-fail",
        name="Test Routine (Fail)",
        steps=[
            StepConfig(
                id="step-1",
                title="Test Step",
                tasks=[
                    TaskConfig(
                        id="task-1",
                        title="Test Task",
                        task_context="Complete the test task",
                        retry=RetryConfig(max_attempts=1),
                        requirements=[
                            RequirementConfig(
                                id="req-1",
                                desc="Must pass",
                                priority=Priority.CRITICAL,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    # Create a run with worktree configured (use "repo" to match directory name)
    run = create_run_from_routine(routine, "repo", source_branch="main")
    run.id = run_id
    run.worktree_path = str(wt_info.path)
    run.delete_worktree_on_completion = True
    run.status = RunStatus.ACTIVE

    # Start and fail the task
    task = run.steps[0].tasks[0]
    task.status = TaskStatus.VERIFYING
    task.checklist[0].grade = "F"
    task.checklist[0].status = ChecklistStatus.DONE
    task.current_attempt = 1  # Max attempts reached
    task.attempts = [Attempt(attempt_num=1)]  # Add attempt for grade evaluation

    # Create global config with paths
    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repo_path.parent),
            worktrees_dir=str(worktrees_dir),
        )
    )

    # Create workflow service with global config
    service = WorkflowService(db_session, global_config=global_config)
    await service.create_run(run)

    # Complete verification (should fail the task and run)
    result = await service.complete_verification(run.id, task.id)

    # Task should fail
    assert result.success
    assert result.new_status == TaskStatus.FAILED

    # Run should also fail
    updated_run = await service.get_run(run.id)
    assert updated_run.status == RunStatus.FAILED

    # Verify worktree was deleted
    assert not wt_info.path.exists()


@pytest.mark.asyncio
async def test_no_error_when_worktree_manager_not_configured(
    db_session: AsyncSession, git_repo: tuple[Path, Path], simple_routine: RoutineConfig
) -> None:
    """Test that completion works when WorktreeManager is not configured."""
    # Create a run (no worktree created)
    run = create_run_from_routine(simple_routine, "repo", source_branch="main")
    run.worktree_path = "/some/path"  # Set path but no manager
    run.delete_worktree_on_completion = True
    run.status = RunStatus.ACTIVE

    # Grade all requirements as passing
    task = run.steps[0].tasks[0]
    task.status = TaskStatus.VERIFYING
    for item in task.checklist:
        item.grade = "A"
        item.status = ChecklistStatus.DONE

    # Create workflow service WITHOUT global config (no worktree manager available)
    service = WorkflowService(db_session, global_config=None)
    await service.create_run(run)

    # Complete verification (should complete without error)
    result = await service.complete_verification(run.id, task.id)

    assert result.success
    assert result.new_status == TaskStatus.COMPLETED

    # Verify run completed
    updated_run = await service.get_run(run.id)
    assert updated_run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_no_error_when_worktree_path_not_set(
    db_session: AsyncSession, git_repo: tuple[Path, Path], simple_routine: RoutineConfig
) -> None:
    """Test that completion works when worktree_path is None."""
    repo_path, worktrees_dir = git_repo

    # Create a run without worktree_path
    run = create_run_from_routine(simple_routine, "repo", source_branch="main")
    run.worktree_path = None  # No worktree configured
    run.delete_worktree_on_completion = True
    run.status = RunStatus.ACTIVE

    # Grade all requirements as passing
    task = run.steps[0].tasks[0]
    task.status = TaskStatus.VERIFYING
    for item in task.checklist:
        item.grade = "A"
        item.status = ChecklistStatus.DONE

    # Create global config with paths
    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repo_path.parent),
            worktrees_dir=str(worktrees_dir),
        )
    )

    # Create workflow service with global config
    service = WorkflowService(db_session, global_config=global_config)
    await service.create_run(run)

    # Complete verification (should complete without error)
    result = await service.complete_verification(run.id, task.id)

    assert result.success
    assert result.new_status == TaskStatus.COMPLETED

    # Verify run completed
    updated_run = await service.get_run(run.id)
    assert updated_run.status == RunStatus.COMPLETED
