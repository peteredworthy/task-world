"""Unit tests for completion actions.

Tests use real git repositories in temporary directories.
NO mocks.
"""

import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from orchestrator.config.enums import RunStatus
from orchestrator.git.worktree import WorktreeManager
from orchestrator.state.models import Run
from orchestrator.workflow.completion import handle_run_completion


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

        # Create and commit an initial file (git worktree requires commits)
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


def test_worktree_deleted_when_configured(git_repo: tuple[Path, Path]) -> None:
    """Test that worktree is deleted when delete_worktree_on_completion is True."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree for a run
    run_id = "test-run-1"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Create a run with delete_worktree_on_completion=True
    run = Run(
        id=run_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=str(wt_info.path),
        delete_worktree_on_completion=True,
    )

    # Handle completion
    handle_run_completion(run, manager)

    # Verify worktree was deleted
    assert not wt_info.path.exists()


def test_worktree_kept_when_configured(git_repo: tuple[Path, Path]) -> None:
    """Test that worktree is kept when delete_worktree_on_completion is False."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree for a run
    run_id = "test-run-2"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Create a run with delete_worktree_on_completion=False
    run = Run(
        id=run_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=str(wt_info.path),
        delete_worktree_on_completion=False,
    )

    # Handle completion
    handle_run_completion(run, manager)

    # Verify worktree still exists
    assert wt_info.path.exists()

    # Cleanup
    manager.delete(run_id, force=True)


def test_no_error_when_no_worktree_exists(git_repo: tuple[Path, Path]) -> None:
    """Test that handle_run_completion doesn't error when no worktree exists."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a run without creating an actual worktree
    run_id = "test-run-3"
    run = Run(
        id=run_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=None,  # No worktree path
        delete_worktree_on_completion=True,
    )

    # Should not raise any error
    handle_run_completion(run, manager)


def test_no_error_when_worktree_already_deleted(git_repo: tuple[Path, Path]) -> None:
    """Test that handle_run_completion doesn't error when worktree was already deleted."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree then delete it manually
    run_id = "test-run-4"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()
    manager.delete(run_id, force=True)
    assert not wt_info.path.exists()

    # Create a run that references the deleted worktree
    run = Run(
        id=run_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=str(wt_info.path),
        delete_worktree_on_completion=True,
    )

    # Should not raise any error
    handle_run_completion(run, manager)


def test_worktree_cleanup_with_uncommitted_changes(git_repo: tuple[Path, Path]) -> None:
    """Test that worktree cleanup works even with uncommitted changes (force=True)."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a worktree for a run
    run_id = "test-run-5"
    wt_info = manager.create(run_id)
    assert wt_info.path.exists()

    # Make uncommitted changes in the worktree
    test_file = wt_info.path / "test.txt"
    test_file.write_text("uncommitted changes")

    # Create a run with delete_worktree_on_completion=True
    run = Run(
        id=run_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=str(wt_info.path),
        delete_worktree_on_completion=True,
    )

    # Handle completion (should use force=True to remove despite changes)
    handle_run_completion(run, manager)

    # Verify worktree was deleted
    assert not wt_info.path.exists()


def test_completion_respects_delete_flag(git_repo: tuple[Path, Path]) -> None:
    """Test that completion only deletes when explicitly configured."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create two worktrees
    run1_id = "test-run-6"
    run2_id = "test-run-7"

    wt1_info = manager.create(run1_id)
    wt2_info = manager.create(run2_id)

    assert wt1_info.path.exists()
    assert wt2_info.path.exists()

    # Run 1: delete_worktree_on_completion=True
    run1 = Run(
        id=run1_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=str(wt1_info.path),
        delete_worktree_on_completion=True,
    )

    # Run 2: delete_worktree_on_completion=False
    run2 = Run(
        id=run2_id,
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=str(wt2_info.path),
        delete_worktree_on_completion=False,
    )

    # Handle completion for both runs
    handle_run_completion(run1, manager)
    handle_run_completion(run2, manager)

    # Verify: run1's worktree deleted, run2's worktree kept
    assert not wt1_info.path.exists()
    assert wt2_info.path.exists()

    # Cleanup
    manager.delete(run2_id, force=True)


def test_completion_without_worktree_path(git_repo: tuple[Path, Path]) -> None:
    """Test that completion works when worktree_path is None."""
    repo_path, worktrees_dir = git_repo
    manager = WorktreeManager(repo_path, worktrees_dir)

    # Create a run without worktree_path set
    run = Run(
        id="test-run-8",
        repo_name="test-repo",
        status=RunStatus.COMPLETED,
        worktree_path=None,
        delete_worktree_on_completion=True,
    )

    # Should complete without error (early return)
    handle_run_completion(run, manager)
