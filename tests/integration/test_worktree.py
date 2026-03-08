"""Integration tests for WorktreeManager."""

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.git.errors import GitCommandError, WorktreeExistsError, WorktreeNotFoundError
from orchestrator.git.worktree import WorktreeManager


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a temporary git repository and worktrees directory for testing.

    Returns:
        Tuple of (repo_path, worktrees_dir)
    """
    repo = tmp_path / "repo"
    worktrees = tmp_path / "worktrees"
    repo.mkdir()
    worktrees.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo, worktrees


def test_create_worktree(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree for a run."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    # Create worktree
    wt = manager.create("test-run-1")

    # Verify worktree uses short counter-based path (r1, r2, ...)
    assert wt.path == (worktrees / "r1").resolve()
    assert wt.branch == "orchestrator/run-test-run-1"
    assert len(wt.commit) == 40  # SHA is 40 chars

    # Verify worktree exists on filesystem
    assert wt.path.exists()
    assert (wt.path / ".git").exists()
    assert (wt.path / "README.md").exists()

    # Verify branch was created
    result = subprocess.run(
        ["git", "branch", "--list", wt.branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert wt.branch in result.stdout


def test_create_worktree_custom_base_branch(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree from a custom base branch."""
    repo, worktrees = git_repo

    # Create a feature branch
    subprocess.run(
        ["git", "checkout", "-b", "feature"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "feature.txt").write_text("feature file\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Add feature"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Get feature commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    feature_commit = result.stdout.strip()

    # Switch back to main
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create worktree from feature branch
    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("test-run-2", base_branch="feature")

    # Verify worktree has feature commit
    assert wt.commit == feature_commit
    assert (wt.path / "feature.txt").exists()


def test_create_worktree_custom_directory(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree in a custom directory."""
    repo, _ = git_repo
    custom_dir = repo.parent / "custom-worktrees"
    manager = WorktreeManager(repo, worktree_dir=custom_dir)

    wt = manager.create("test-run-3")

    # Custom directory also uses counter-based naming
    assert wt.path == (custom_dir / "r1").resolve()
    assert wt.path.exists()


def test_create_worktree_already_exists(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree that already exists raises an error."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    # Create first worktree
    manager.create("test-run-4")

    # Try to create again
    with pytest.raises(WorktreeExistsError) as exc_info:
        manager.create("test-run-4")

    assert exc_info.value.run_id == "test-run-4"
    assert "test-run-4" in str(exc_info.value)


def test_create_worktree_invalid_base_branch(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree from non-existent branch raises an error."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    with pytest.raises(GitCommandError) as exc_info:
        manager.create("test-run-5", base_branch="nonexistent")

    assert exc_info.value.returncode != 0
    assert (
        "nonexistent" in exc_info.value.stderr.lower() or "invalid" in exc_info.value.stderr.lower()
    )


def test_worktree_isolation(git_repo: tuple[Path, Path]) -> None:
    """Test that worktree changes don't affect main repo."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    # Create worktree
    wt = manager.create("test-run-6")

    # Make changes in worktree
    (wt.path / "worktree-file.txt").write_text("worktree content\n")
    subprocess.run(["git", "add", "."], cwd=wt.path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Worktree changes"],
        cwd=wt.path,
        check=True,
        capture_output=True,
    )

    # Verify main repo is unchanged
    assert not (repo / "worktree-file.txt").exists()

    # Verify changes are in worktree
    assert (wt.path / "worktree-file.txt").exists()


def test_delete_worktree(git_repo: tuple[Path, Path]) -> None:
    """Test deleting a worktree."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    # Create and then delete
    wt = manager.create("test-run-7")
    assert wt.path.exists()

    manager.delete("test-run-7")
    assert not wt.path.exists()


def test_delete_worktree_with_uncommitted_changes(git_repo: tuple[Path, Path]) -> None:
    """Test deleting a worktree with uncommitted changes requires force."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    # Create worktree and make uncommitted changes
    wt = manager.create("test-run-8")
    (wt.path / "uncommitted.txt").write_text("uncommitted\n")

    # Try to delete without force - should fail
    with pytest.raises(GitCommandError):
        manager.delete("test-run-8", force=False)

    # Verify worktree still exists
    assert wt.path.exists()

    # Delete with force should work
    manager.delete("test-run-8", force=True)
    assert not wt.path.exists()


def test_delete_worktree_not_found(git_repo: tuple[Path, Path]) -> None:
    """Test deleting a non-existent worktree raises an error."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    with pytest.raises(WorktreeNotFoundError) as exc_info:
        manager.delete("nonexistent-run")

    assert exc_info.value.run_id == "nonexistent-run"
    assert "nonexistent-run" in str(exc_info.value)


def test_list_worktrees_empty(git_repo: tuple[Path, Path]) -> None:
    """Test listing worktrees when none exist."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    worktrees = manager.list()

    assert worktrees == []


def test_list_worktrees_single(git_repo: tuple[Path, Path]) -> None:
    """Test listing a single worktree."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktree
    wt = manager.create("test-run-9")

    # List worktrees
    worktrees = manager.list()

    assert len(worktrees) == 1
    assert worktrees[0].path == wt.path
    assert worktrees[0].branch == wt.branch
    assert worktrees[0].commit == wt.commit


def test_list_worktrees_multiple(git_repo: tuple[Path, Path]) -> None:
    """Test listing multiple worktrees."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create multiple worktrees
    wt1 = manager.create("test-run-10")
    wt2 = manager.create("test-run-11")
    wt3 = manager.create("test-run-12")

    # List worktrees
    worktrees = manager.list()

    assert len(worktrees) == 3

    # Verify all worktrees are present
    paths = {wt.path for wt in worktrees}
    assert wt1.path in paths
    assert wt2.path in paths
    assert wt3.path in paths


def test_list_worktrees_filters_non_orchestrator(git_repo: tuple[Path, Path]) -> None:
    """Test that list() only returns orchestrator-managed worktrees."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create orchestrator worktree
    wt_orchestrator = manager.create("test-run-13")

    # Create non-orchestrator worktree manually
    manual_path = worktrees_dir / "manual"
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "manual-branch",
            str(manual_path),
            "main",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # List worktrees
    worktrees = manager.list()

    # Should only return orchestrator worktree
    assert len(worktrees) == 1
    assert worktrees[0].path == wt_orchestrator.path


def test_cleanup_stale_removes_inactive(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_stale removes worktrees for inactive runs."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktrees
    wt1 = manager.create("active-run-1")
    wt2 = manager.create("stale-run-1")
    wt3 = manager.create("stale-run-2")

    # Only mark run-1 as active
    active_runs = {"active-run-1"}

    # Cleanup stale
    removed = manager.cleanup_stale(active_runs)

    # Should remove 2 stale worktrees
    assert removed == 2

    # Verify active worktree remains
    assert wt1.path.exists()

    # Verify stale worktrees are removed
    assert not wt2.path.exists()
    assert not wt3.path.exists()


def test_cleanup_stale_no_active_runs(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_stale removes all worktrees when no runs are active."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktrees
    wt1 = manager.create("stale-run-3")
    wt2 = manager.create("stale-run-4")

    # No active runs
    active_runs: set[str] = set()

    # Cleanup stale
    removed = manager.cleanup_stale(active_runs)

    # Should remove all worktrees
    assert removed == 2
    assert not wt1.path.exists()
    assert not wt2.path.exists()


def test_cleanup_stale_all_active(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_stale removes nothing when all runs are active."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktrees
    wt1 = manager.create("active-run-2")
    wt2 = manager.create("active-run-3")

    # All runs active
    active_runs = {"active-run-2", "active-run-3"}

    # Cleanup stale
    removed = manager.cleanup_stale(active_runs)

    # Should remove nothing
    assert removed == 0
    assert wt1.path.exists()
    assert wt2.path.exists()


def test_cleanup_stale_empty_list(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_stale with no worktrees returns zero."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # No worktrees
    active_runs = {"some-run"}

    # Cleanup stale
    removed = manager.cleanup_stale(active_runs)

    assert removed == 0


def test_cleanup_stale_with_uncommitted_changes(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_stale can remove worktrees with uncommitted changes."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktree with uncommitted changes
    wt = manager.create("stale-run-5")
    (wt.path / "uncommitted.txt").write_text("uncommitted\n")

    # Cleanup (should force remove)
    removed = manager.cleanup_stale(set())

    # Should successfully remove
    assert removed == 1
    assert not wt.path.exists()


def test_worktree_manager_with_relative_path(git_repo: tuple[Path, Path]) -> None:
    """Test WorktreeManager works with repository path."""
    repo, worktrees_dir = git_repo
    # Create manager with absolute paths
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktree
    wt = manager.create("test-run-14")

    # Verify worktree created successfully
    assert wt.path.exists()
    assert wt.path.is_absolute()


def test_concurrent_worktrees_different_branches(git_repo: tuple[Path, Path]) -> None:
    """Test multiple worktrees can coexist with different branches."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create multiple worktrees
    wt1 = manager.create("concurrent-1")
    wt2 = manager.create("concurrent-2")
    wt3 = manager.create("concurrent-3")

    # Verify all exist
    assert wt1.path.exists()
    assert wt2.path.exists()
    assert wt3.path.exists()

    # Verify unique branches
    assert wt1.branch != wt2.branch
    assert wt2.branch != wt3.branch
    assert wt1.branch != wt3.branch

    # Verify all branches exist
    result = subprocess.run(
        ["git", "branch", "--list", "orchestrator/*"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert "orchestrator/run-concurrent-1" in result.stdout
    assert "orchestrator/run-concurrent-2" in result.stdout
    assert "orchestrator/run-concurrent-3" in result.stdout


# --- cleanup_expired tests ---


def test_cleanup_expired_removes_orphaned(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_expired removes worktrees whose run ID is not in the DB."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    wt_known = manager.create("known-run")
    wt_orphan = manager.create("orphan-run")

    all_run_ids = {"known-run"}
    run_completed_at: dict[str, datetime] = {}

    removed = manager.cleanup_expired(all_run_ids, run_completed_at, retention=timedelta(days=14))

    assert removed == 1
    assert wt_known.path.exists()
    assert not wt_orphan.path.exists()


def test_cleanup_expired_removes_old_completed(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_expired removes worktrees for runs completed beyond retention."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    wt_old = manager.create("old-run")
    wt_recent = manager.create("recent-run")
    wt_active = manager.create("active-run")

    now = datetime(2025, 3, 1, tzinfo=timezone.utc)
    all_run_ids = {"old-run", "recent-run", "active-run"}
    run_completed_at = {
        "old-run": datetime(2025, 2, 1, tzinfo=timezone.utc),  # 28 days ago
        "recent-run": datetime(2025, 2, 20, tzinfo=timezone.utc),  # 9 days ago
        # active-run has no completed_at (still running)
    }

    removed = manager.cleanup_expired(
        all_run_ids, run_completed_at, retention=timedelta(days=14), now=now
    )

    assert removed == 1
    assert not wt_old.path.exists()
    assert wt_recent.path.exists()
    assert wt_active.path.exists()


def test_cleanup_expired_keeps_within_retention(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_expired keeps completed worktrees within retention window."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    wt = manager.create("completed-run")

    now = datetime(2025, 3, 1, tzinfo=timezone.utc)
    all_run_ids = {"completed-run"}
    run_completed_at = {
        "completed-run": datetime(2025, 2, 28, tzinfo=timezone.utc),  # 1 day ago
    }

    removed = manager.cleanup_expired(
        all_run_ids, run_completed_at, retention=timedelta(days=14), now=now
    )

    assert removed == 0
    assert wt.path.exists()


def test_cleanup_expired_mixed_orphaned_and_expired(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_expired handles both orphaned and expired worktrees together."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    wt_orphan = manager.create("orphan-run")
    wt_expired = manager.create("expired-run")
    wt_keep = manager.create("keep-run")

    now = datetime(2025, 3, 1, tzinfo=timezone.utc)
    all_run_ids = {"expired-run", "keep-run"}  # orphan-run not in DB
    run_completed_at = {
        "expired-run": datetime(2025, 1, 1, tzinfo=timezone.utc),  # 59 days ago
        # keep-run has no completed_at (still active)
    }

    removed = manager.cleanup_expired(
        all_run_ids, run_completed_at, retention=timedelta(days=14), now=now
    )

    assert removed == 2
    assert not wt_orphan.path.exists()
    assert not wt_expired.path.exists()
    assert wt_keep.path.exists()


# --- broken worktree detection tests ---


def test_ensure_exists_broken_worktree_no_git_file(git_repo: tuple[Path, Path]) -> None:
    """Test ensure_exists recreates a worktree whose directory exists but has no .git file."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create a real worktree first
    wt = manager.create("broken-run-1")
    original_path = wt.path

    # Simulate a broken worktree: remove .git file but keep the directory
    import shutil

    shutil.rmtree(original_path)
    original_path.mkdir()
    (original_path / ".pytest_cache").mkdir()  # leftover artifact

    # Verify .git is gone
    assert original_path.exists()
    assert not (original_path / ".git").exists()

    # ensure_exists should detect the broken state and recreate
    restored = manager.ensure_exists("broken-run-1", worktree_path=str(original_path))

    # Should get a valid worktree back (possibly at a new path since the old
    # directory still exists without .git — the recreation allocates a new counter path)
    assert restored.path.exists()
    assert (restored.path / ".git").exists()
    assert restored.branch == "orchestrator/run-broken-run-1"
    assert len(restored.commit) == 40


def test_ensure_exists_broken_legacy_path_no_git_file(git_repo: tuple[Path, Path]) -> None:
    """Test ensure_exists recreates a legacy-path worktree with no .git file."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    run_id = "legacy-broken-1"

    # Create a legacy-style directory (run-{id}) without a .git file
    legacy_path = worktrees_dir / f"run-{run_id}"
    legacy_path.mkdir(parents=True)
    (legacy_path / "stale-file.txt").write_text("stale")

    assert legacy_path.exists()
    assert not (legacy_path / ".git").exists()

    # ensure_exists should not be tricked by the legacy directory
    restored = manager.ensure_exists(run_id)

    assert restored.path.exists()
    assert (restored.path / ".git").exists()
    assert restored.branch == f"orchestrator/run-{run_id}"
    assert len(restored.commit) == 40


def test_cleanup_expired_refuses_empty_run_set(git_repo: tuple[Path, Path]) -> None:
    """Test cleanup_expired refuses to delete worktrees when all_run_ids is empty."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create worktrees that would be "orphaned" if run set is trusted
    wt1 = manager.create("run-a")
    wt2 = manager.create("run-b")

    # Pass empty run set — should refuse to remove anything
    removed = manager.cleanup_expired(
        all_run_ids=set(),
        run_completed_at={},
        retention=timedelta(days=14),
    )

    assert removed == 0
    assert wt1.path.exists()
    assert wt2.path.exists()


# -- Worktree setup script tests --


def test_worktree_setup_script_runs_on_create(git_repo: tuple[Path, Path]) -> None:
    """Test that .worktree-setup is executed after worktree creation."""
    repo, worktrees = git_repo

    # Create a setup script that writes a marker file
    setup_script = repo / ".worktree-setup"
    setup_script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\necho "setup-ran" > "$1/.setup-marker"\n'
    )
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("setup-test")

    marker = wt.path / ".setup-marker"
    assert marker.exists(), "Setup script should have created .setup-marker"
    assert marker.read_text().strip() == "setup-ran"


def test_worktree_setup_script_receives_both_args(git_repo: tuple[Path, Path]) -> None:
    """Test that .worktree-setup receives worktree path and main repo path."""
    repo, worktrees = git_repo

    setup_script = repo / ".worktree-setup"
    setup_script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\necho "$1" > "$1/.arg1"\necho "$2" > "$1/.arg2"\n'
    )
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("args-test")

    arg1 = (wt.path / ".arg1").read_text().strip()
    arg2 = (wt.path / ".arg2").read_text().strip()
    # arg1 is the worktree path (may not be resolved yet)
    assert Path(arg1).resolve() == wt.path
    assert Path(arg2).resolve() == repo.resolve()


def test_worktree_setup_script_failure_does_not_block(git_repo: tuple[Path, Path]) -> None:
    """Test that a failing setup script doesn't prevent worktree creation."""
    repo, worktrees = git_repo

    setup_script = repo / ".worktree-setup"
    setup_script.write_text("#!/usr/bin/env bash\nexit 1\n")
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("fail-test")

    # Worktree should still be created and usable
    assert wt.path.exists()
    assert (wt.path / ".git").exists()


def test_worktree_no_setup_script(git_repo: tuple[Path, Path]) -> None:
    """Test that missing .worktree-setup is handled gracefully."""
    repo, worktrees = git_repo

    # No setup script — should work fine (baseline behavior)
    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("no-setup-test")
    assert wt.path.exists()


def test_worktree_setup_runs_on_ensure_exists(git_repo: tuple[Path, Path]) -> None:
    """Test that .worktree-setup runs when ensure_exists recreates a worktree."""
    repo, worktrees = git_repo

    setup_script = repo / ".worktree-setup"
    setup_script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\necho "setup-ran" > "$1/.setup-marker"\n'
    )
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.ensure_exists("ensure-test")

    marker = wt.path / ".setup-marker"
    assert marker.exists(), "Setup script should have run via ensure_exists"
