"""Integration tests for branch operations using real git repos."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from orchestrator.git import back_merge, get_branch_status, merge_back
from orchestrator.git.errors import BranchNotFoundError, MergeConflictError


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)


def _commit_file(path: Path, filename: str, content: str, message: str) -> str:
    """Create/modify a file and commit it. Returns the commit SHA."""
    (path / filename).write_text(content)
    _git(["add", filename], cwd=path)
    _git(["commit", "-m", message], cwd=path)
    return _git(["rev-parse", "HEAD"], cwd=path)


@pytest.fixture
def git_repo(tmp_path: Path, _unit_base_repo: Path) -> Path:
    """Copy the session-scoped base repo for this test.

    Using shutil.copytree instead of git init + config + commit saves ~100 ms
    per test (5-6 subprocess calls → 0) because copytree transfers .git/config
    verbatim, including user.email / user.name.  The base repo is already on
    main so no branch rename is needed.
    """
    return Path(shutil.copytree(str(_unit_base_repo), str(tmp_path / "repo")))


@pytest.fixture
def repo_with_run_branch(git_repo: Path) -> tuple[Path, str, str]:
    """Create a repo with a run branch diverged from main.

    Returns: (repo_path, run_branch, source_branch)
    """
    run_branch = "orchestrator/run-test"
    source_branch = "main"

    # Create run branch from main
    _git(["checkout", "-b", run_branch], cwd=git_repo)
    _git(["checkout", source_branch], cwd=git_repo)

    return git_repo, run_branch, source_branch


class TestGetBranchStatus:
    def test_no_divergence(self, repo_with_run_branch: tuple[Path, str, str]) -> None:
        repo, run_branch, source = repo_with_run_branch

        status = get_branch_status(repo, run_branch, source)

        assert status.behind_count == 0
        assert status.ahead_count == 0
        assert status.can_merge_cleanly is True
        assert status.has_conflicts is False

    def test_ahead_only(self, repo_with_run_branch: tuple[Path, str, str]) -> None:
        repo, run_branch, source = repo_with_run_branch

        # Make a commit on the run branch
        _git(["checkout", run_branch], cwd=repo)
        _commit_file(repo, "feature.py", "# feature", "Add feature")
        _git(["checkout", source], cwd=repo)

        status = get_branch_status(repo, run_branch, source)

        assert status.ahead_count == 1
        assert status.behind_count == 0
        assert status.can_merge_cleanly is True

    def test_behind_only(self, repo_with_run_branch: tuple[Path, str, str]) -> None:
        repo, run_branch, source = repo_with_run_branch

        # Make a commit on source
        _commit_file(repo, "hotfix.py", "# hotfix", "Add hotfix")

        status = get_branch_status(repo, run_branch, source)

        assert status.ahead_count == 0
        assert status.behind_count == 1
        assert status.can_merge_cleanly is True
        assert status.has_conflicts is False

    def test_diverged(self, repo_with_run_branch: tuple[Path, str, str]) -> None:
        repo, run_branch, source = repo_with_run_branch

        # Commit on run branch
        _git(["checkout", run_branch], cwd=repo)
        _commit_file(repo, "feature.py", "# feature", "Add feature")

        # Commit on source (different file = no conflict)
        _git(["checkout", source], cwd=repo)
        _commit_file(repo, "hotfix.py", "# hotfix", "Add hotfix")

        status = get_branch_status(repo, run_branch, source)

        assert status.ahead_count == 1
        assert status.behind_count == 1
        assert status.can_merge_cleanly is True
        assert status.has_conflicts is False

    def test_diverged_with_conflicts(self, repo_with_run_branch: tuple[Path, str, str]) -> None:
        repo, run_branch, source = repo_with_run_branch

        # Commit on run branch modifying README
        _git(["checkout", run_branch], cwd=repo)
        _commit_file(repo, "README.md", "# Run changes\n", "Modify README on run")

        # Commit on source modifying same file
        _git(["checkout", source], cwd=repo)
        _commit_file(repo, "README.md", "# Source changes\n", "Modify README on source")

        status = get_branch_status(repo, run_branch, source)

        assert status.ahead_count == 1
        assert status.behind_count == 1
        assert status.has_conflicts is True
        assert status.can_merge_cleanly is False

    def test_branch_not_found(self, git_repo: Path) -> None:
        with pytest.raises(BranchNotFoundError, match="nonexistent"):
            get_branch_status(git_repo, "nonexistent", "main")

    def test_source_not_found(self, git_repo: Path) -> None:
        with pytest.raises(BranchNotFoundError, match="nonexistent"):
            get_branch_status(git_repo, "main", "nonexistent")


class TestBackMerge:
    def test_clean_merge(self, git_repo: Path) -> None:
        """Back-merge source into run branch when no conflicts."""
        run_branch = "orchestrator/run-test"
        _git(["checkout", "-b", run_branch], cwd=git_repo)
        _commit_file(git_repo, "feature.py", "# feature", "Add feature")

        # Add a commit on main
        _git(["checkout", "main"], cwd=git_repo)
        _commit_file(git_repo, "hotfix.py", "# hotfix", "Add hotfix")

        # Switch to run branch and back-merge
        _git(["checkout", run_branch], cwd=git_repo)
        sha = back_merge(git_repo, "main")

        assert sha
        # Verify the hotfix file exists on run branch now
        assert (git_repo / "hotfix.py").exists()
        assert (git_repo / "feature.py").exists()

    def test_conflict_raises_error(self, git_repo: Path) -> None:
        """Back-merge raises MergeConflictError on conflict."""
        run_branch = "orchestrator/run-test"
        _git(["checkout", "-b", run_branch], cwd=git_repo)
        _commit_file(git_repo, "README.md", "# Run version\n", "Modify on run")

        # Modify same file on main
        _git(["checkout", "main"], cwd=git_repo)
        _commit_file(git_repo, "README.md", "# Main version\n", "Modify on main")

        # Switch to run branch and try back-merge
        _git(["checkout", run_branch], cwd=git_repo)
        with pytest.raises(MergeConflictError) as exc_info:
            back_merge(git_repo, "main")

        assert exc_info.value.source == "main"
        assert exc_info.value.target == run_branch
        assert "README.md" in exc_info.value.conflicting_files

    def test_branch_not_found(self, git_repo: Path) -> None:
        with pytest.raises(BranchNotFoundError, match="nonexistent"):
            back_merge(git_repo, "nonexistent")

    def test_no_op_when_already_up_to_date(self, git_repo: Path) -> None:
        """Back-merge is a no-op when run branch already has all source commits."""
        run_branch = "orchestrator/run-test"
        _git(["checkout", "-b", run_branch], cwd=git_repo)

        sha = back_merge(git_repo, "main")
        # Should succeed with current HEAD (already up to date)
        assert sha == _git(["rev-parse", "HEAD"], cwd=git_repo)


class TestMergeBack:
    def test_squash_strategy(self, git_repo: Path) -> None:
        """Merge-back with squash strategy creates a single commit."""
        run_branch = "orchestrator/run-test"

        # Create run branch with multiple commits
        _git(["checkout", "-b", run_branch], cwd=git_repo)
        _commit_file(git_repo, "file1.py", "# file 1", "Add file 1")
        _commit_file(git_repo, "file2.py", "# file 2", "Add file 2")

        sha = merge_back(git_repo, run_branch, "main", strategy="squash")

        assert sha
        # Should be on main now
        assert _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo) == "main"
        # Files should exist
        assert (git_repo / "file1.py").exists()
        assert (git_repo / "file2.py").exists()
        # Check that it was a squash (main should have initial commit + 1 squash commit)
        log = _git(["log", "--oneline"], cwd=git_repo)
        assert len(log.strip().split("\n")) == 2  # initial + squash

    def test_merge_strategy(self, git_repo: Path) -> None:
        """Merge-back with merge strategy preserves history."""
        run_branch = "orchestrator/run-test"

        # Create run branch with multiple commits
        _git(["checkout", "-b", run_branch], cwd=git_repo)
        _commit_file(git_repo, "file1.py", "# file 1", "Add file 1")
        _commit_file(git_repo, "file2.py", "# file 2", "Add file 2")

        sha = merge_back(git_repo, run_branch, "main", strategy="merge")

        assert sha
        assert _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo) == "main"
        assert (git_repo / "file1.py").exists()
        assert (git_repo / "file2.py").exists()
        # Merge commit preserves all history
        log = _git(["log", "--oneline"], cwd=git_repo)
        # initial + 2 feature commits + 1 merge commit = 4
        assert len(log.strip().split("\n")) == 4

    def test_conflict_raises_error(self, git_repo: Path) -> None:
        """Merge-back raises MergeConflictError on conflict."""
        run_branch = "orchestrator/run-test"

        # Diverge the branches with conflicting changes
        _git(["checkout", "-b", run_branch], cwd=git_repo)
        _commit_file(git_repo, "README.md", "# Run version\n", "Modify on run")

        _git(["checkout", "main"], cwd=git_repo)
        _commit_file(git_repo, "README.md", "# Main version\n", "Modify on main")

        with pytest.raises(MergeConflictError) as exc_info:
            merge_back(git_repo, run_branch, "main", strategy="squash")

        assert exc_info.value.source == run_branch
        assert exc_info.value.target == "main"

    def test_branch_not_found(self, git_repo: Path) -> None:
        with pytest.raises(BranchNotFoundError, match="nonexistent"):
            merge_back(git_repo, "nonexistent", "main")
