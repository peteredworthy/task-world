"""Integration tests for WorktreeManager.

Real ``git worktree add`` (via ``manager.create``) dominates each test's
cost, so related assertions that walk one manager through several states
(list, cleanup) share created worktrees instead of paying for fresh ones
per assertion.
"""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.git.errors import GitCommandError, WorktreeExistsError, WorktreeNotFoundError
from orchestrator.git.worktree import WorktreeManager, get_agent_cache_write_paths

from tests.integration.git_helpers import _git

pytestmark = pytest.mark.slow


@pytest.fixture
def git_repo(tmp_path: Path, _base_repo: Path) -> tuple[Path, Path]:
    """Copy the session-scoped base repo for a test-isolated repository.

    Returns:
        Tuple of (repo_path, worktrees_dir)
    """
    repo = tmp_path / "repo"
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    shutil.copytree(str(_base_repo), str(repo))
    return repo, worktrees


def test_create_worktree(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree for a run."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    # Create worktree
    wt = manager.create("test-run-1")

    # Verify worktree uses short counter-based path (r1, r2, ...)
    assert wt.path == (worktrees / "r1").resolve()
    assert wt.path.is_absolute()
    assert wt.branch == "orchestrator/run-test-run-1"
    assert len(wt.commit) == 40  # SHA is 40 chars

    # Verify worktree exists on filesystem
    assert wt.path.exists()
    assert (wt.path / ".git").exists()
    assert (wt.path / "README.md").exists()

    # Verify branch was created
    branch_list = _git(["branch", "--list", wt.branch], cwd=repo)
    assert wt.branch in branch_list


def test_create_worktree_writes_git_metadata_writable_roots(git_repo: tuple[Path, Path]) -> None:
    """Sandbox settings include git metadata and cache roots needed for commits."""
    repo, worktrees = git_repo
    manager = WorktreeManager(repo, worktrees)

    wt = manager.create("git-metadata-roots")

    settings_path = wt.path / ".claude" / "settings.local.json"
    settings = json.loads(settings_path.read_text())
    fs_settings = settings["sandbox"]["filesystem"]
    allow_write = set(fs_settings["allowWrite"])
    allow_read = set(fs_settings["allowRead"])
    allowed_domains = settings["sandbox"]["network"]["allowedDomains"]

    assert settings["autoMemoryEnabled"] is False

    gitdir_file = wt.path / ".git"
    gitdir_raw = gitdir_file.read_text().strip().removeprefix("gitdir: ")
    gitdir = Path(gitdir_raw)
    if not gitdir.is_absolute():
        gitdir = (wt.path / gitdir).resolve()
    else:
        gitdir = gitdir.resolve()
    commondir = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()

    assert str(gitdir) in allow_write
    assert str(commondir) in allow_write
    assert str(gitdir) in allow_read
    assert str(commondir) in allow_read
    for cache_path in get_agent_cache_write_paths():
        assert str(cache_path) in allow_write
        assert str(cache_path) in allow_read
    assert allowed_domains == ["*"]


def test_create_worktree_custom_base_branch(git_repo: tuple[Path, Path]) -> None:
    """Test creating a worktree from a custom base branch."""
    repo, worktrees = git_repo

    # Create a feature branch
    _git(["checkout", "-b", "feature"], cwd=repo)
    (repo / "feature.txt").write_text("feature file\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "Add feature"], cwd=repo)

    # Get feature commit SHA
    feature_commit = _git(["rev-parse", "HEAD"], cwd=repo)

    # Switch back to main
    _git(["checkout", "main"], cwd=repo)

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
    _git(["add", "."], cwd=wt.path)
    _git(["commit", "-m", "Worktree changes"], cwd=wt.path)

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


def test_list_worktrees_lifecycle(git_repo: tuple[Path, Path]) -> None:
    """list() is empty initially, tracks each created worktree with a unique
    branch, and filters out non-orchestrator worktrees."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    assert manager.list() == []

    wt1 = manager.create("test-run-9")
    listed = manager.list()
    assert len(listed) == 1
    assert listed[0].path == wt1.path
    assert listed[0].branch == wt1.branch
    assert listed[0].commit == wt1.commit

    wt2 = manager.create("test-run-10")
    wt3 = manager.create("test-run-11")
    listed = manager.list()
    assert len(listed) == 3
    assert {wt.path for wt in listed} == {wt1.path, wt2.path, wt3.path}
    # Branches are unique per worktree and registered in the repo
    assert len({wt1.branch, wt2.branch, wt3.branch}) == 3
    branch_list = _git(["branch", "--list", "orchestrator/*"], cwd=repo)
    assert "orchestrator/run-test-run-9" in branch_list
    assert "orchestrator/run-test-run-10" in branch_list
    assert "orchestrator/run-test-run-11" in branch_list

    # Create non-orchestrator worktree manually — list() must not return it
    manual_path = worktrees_dir / "manual"
    _git(
        ["worktree", "add", "-b", "manual-branch", str(manual_path), "main"],
        cwd=repo,
    )
    listed = manager.list()
    assert len(listed) == 3
    assert manual_path not in {wt.path for wt in listed}


def test_cleanup_stale_lifecycle(git_repo: tuple[Path, Path]) -> None:
    """cleanup_stale is a no-op with no worktrees or when all runs are
    active, and removes exactly the worktrees of inactive runs otherwise."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # No worktrees → nothing to remove
    assert manager.cleanup_stale({"some-run"}) == 0

    wt1 = manager.create("active-run-1")
    wt2 = manager.create("stale-run-1")
    wt3 = manager.create("stale-run-2")

    # All runs active → nothing removed
    assert manager.cleanup_stale({"active-run-1", "stale-run-1", "stale-run-2"}) == 0
    assert wt1.path.exists()
    assert wt2.path.exists()
    assert wt3.path.exists()

    # Only run-1 active → both stale worktrees removed
    assert manager.cleanup_stale({"active-run-1"}) == 2
    assert wt1.path.exists()
    assert not wt2.path.exists()
    assert not wt3.path.exists()


def test_cleanup_stale_no_active_runs_forces_uncommitted(git_repo: tuple[Path, Path]) -> None:
    """With no active runs, cleanup_stale removes every worktree, including
    one with uncommitted changes (force removal)."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    wt1 = manager.create("stale-run-3")
    wt2 = manager.create("stale-run-4")
    (wt2.path / "uncommitted.txt").write_text("uncommitted\n")

    removed = manager.cleanup_stale(set())

    assert removed == 2
    assert not wt1.path.exists()
    assert not wt2.path.exists()


# --- cleanup_expired tests ---


def test_cleanup_expired_orphaned_expired_and_retained(git_repo: tuple[Path, Path]) -> None:
    """cleanup_expired removes worktrees that are orphaned (run not in DB) or
    completed beyond retention, and keeps recently-completed and active
    runs."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    wt_orphan = manager.create("orphan-run")
    wt_expired = manager.create("expired-run")
    wt_recent = manager.create("recent-run")
    wt_active = manager.create("active-run")

    now = datetime(2025, 3, 1, tzinfo=timezone.utc)
    all_run_ids = {"expired-run", "recent-run", "active-run"}  # orphan-run not in DB
    run_completed_at = {
        "expired-run": datetime(2025, 1, 1, tzinfo=timezone.utc),  # 59 days ago
        "recent-run": datetime(2025, 2, 28, tzinfo=timezone.utc),  # 1 day ago
        # active-run has no completed_at (still running)
    }

    removed = manager.cleanup_expired(
        all_run_ids, run_completed_at, retention=timedelta(days=14), now=now
    )

    assert removed == 2
    assert not wt_orphan.path.exists()
    assert not wt_expired.path.exists()
    assert wt_recent.path.exists()
    assert wt_active.path.exists()


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


# --- broken worktree detection tests ---


def test_ensure_exists_broken_worktree_no_git_file(git_repo: tuple[Path, Path]) -> None:
    """Test ensure_exists recreates a worktree whose directory exists but has no .git file."""
    repo, worktrees_dir = git_repo
    manager = WorktreeManager(repo, worktrees_dir)

    # Create a real worktree first
    wt = manager.create("broken-run-1")
    original_path = wt.path

    # Simulate a broken worktree: remove .git file but keep the directory
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


# -- Worktree setup script tests --


def test_worktree_setup_script_runs_with_args(git_repo: tuple[Path, Path]) -> None:
    """scripts/worktree/setup.sh runs after worktree creation and receives
    the worktree path and main repo path as arguments."""
    repo, worktrees = git_repo

    setup_script = repo / "scripts" / "worktree" / "setup.sh"
    setup_script.parent.mkdir(parents=True, exist_ok=True)
    setup_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "setup-ran" > "$1/.setup-marker"\n'
        'echo "$1" > "$1/.arg1"\n'
        'echo "$2" > "$1/.arg2"\n'
    )
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("setup-test")

    marker = wt.path / ".setup-marker"
    assert marker.exists(), "Setup script should have created .setup-marker"
    assert marker.read_text().strip() == "setup-ran"
    # arg1 is the worktree path (may not be resolved yet), arg2 the main repo
    arg1 = (wt.path / ".arg1").read_text().strip()
    arg2 = (wt.path / ".arg2").read_text().strip()
    assert Path(arg1).resolve() == wt.path
    assert Path(arg2).resolve() == repo.resolve()


def test_worktree_setup_script_failure_does_not_block(git_repo: tuple[Path, Path]) -> None:
    """Test that a failing setup script doesn't prevent worktree creation."""
    repo, worktrees = git_repo

    setup_script = repo / "scripts" / "worktree" / "setup.sh"
    setup_script.parent.mkdir(parents=True, exist_ok=True)
    setup_script.write_text("#!/usr/bin/env bash\nexit 1\n")
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.create("fail-test")

    # Worktree should still be created and usable
    assert wt.path.exists()
    assert (wt.path / ".git").exists()


def test_worktree_setup_runs_on_ensure_exists(git_repo: tuple[Path, Path]) -> None:
    """Test that setup.sh runs when ensure_exists recreates a worktree."""
    repo, worktrees = git_repo

    setup_script = repo / "scripts" / "worktree" / "setup.sh"
    setup_script.parent.mkdir(parents=True, exist_ok=True)
    setup_script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\necho "setup-ran" > "$1/.setup-marker"\n'
    )
    setup_script.chmod(0o755)

    manager = WorktreeManager(repo, worktrees)
    wt = manager.ensure_exists("ensure-test")

    marker = wt.path / ".setup-marker"
    assert marker.exists(), "Setup script should have run via ensure_exists"
