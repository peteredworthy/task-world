"""Tests for repos discovery module."""

import subprocess
from pathlib import Path

import pytest

from orchestrator.git.repos import (
    RepoNotFoundError,
    branch_count,
    get_repo,
    list_branches,
    list_repos,
    match_branches,
)


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    """Create a repos directory with test repositories."""
    repos = tmp_path / "repos"
    repos.mkdir()
    return repos


@pytest.fixture
def sample_repo(repos_dir: Path) -> Path:
    """Create a sample git repository."""
    repo_path = repos_dir / "sample-repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
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

    # Create initial commit
    (repo_path / "README.md").write_text("# Sample Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create feature branch
    subprocess.run(
        ["git", "checkout", "-b", "feature/auth"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Back to main
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


class TestListRepos:
    def test_empty_repos_dir(self, repos_dir: Path) -> None:
        result = list_repos(repos_dir)
        assert result == []

    def test_nonexistent_repos_dir(self, tmp_path: Path) -> None:
        result = list_repos(tmp_path / "nonexistent")
        assert result == []

    def test_with_git_repos(self, sample_repo: Path) -> None:
        repos_dir = sample_repo.parent
        result = list_repos(repos_dir)

        assert len(result) == 1
        assert result[0].name == "sample-repo"
        assert result[0].path == sample_repo
        assert result[0].default_branch in ["main", "master"]

    def test_ignores_non_git_directories(self, repos_dir: Path) -> None:
        # Create a non-git directory
        (repos_dir / "not-a-repo").mkdir()

        result = list_repos(repos_dir)
        assert result == []


class TestGetRepo:
    def test_existing_repo(self, sample_repo: Path) -> None:
        repos_dir = sample_repo.parent
        result = get_repo(repos_dir, "sample-repo")

        assert result.name == "sample-repo"
        assert result.path == sample_repo

    def test_nonexistent_repo(self, repos_dir: Path) -> None:
        with pytest.raises(RepoNotFoundError) as exc_info:
            get_repo(repos_dir, "nonexistent")

        assert exc_info.value.name == "nonexistent"


class TestListBranches:
    def test_list_local_branches(self, sample_repo: Path) -> None:
        result = list_branches(sample_repo, local_only=True)

        names = [b.name for b in result]
        assert "main" in names or "master" in names
        assert "feature/auth" in names

    def test_pattern_filter(self, sample_repo: Path) -> None:
        result = list_branches(sample_repo, pattern="feature/*", local_only=True)

        assert len(result) == 1
        assert result[0].name == "feature/auth"

    def test_pattern_no_match(self, sample_repo: Path) -> None:
        result = list_branches(sample_repo, pattern="release/*", local_only=True)
        assert result == []


class TestBranchCount:
    def test_count_all_branches(self, sample_repo: Path) -> None:
        count = branch_count(sample_repo, local_only=True)
        assert count >= 2  # main + feature/auth

    def test_count_with_pattern(self, sample_repo: Path) -> None:
        count = branch_count(sample_repo, pattern="feature/*", local_only=True)
        assert count == 1


class TestMatchBranches:
    def test_empty_pattern_returns_all(self) -> None:
        branches = ["main", "develop", "feature/auth"]
        result = match_branches(branches, "")
        assert result == branches

    def test_prefix_pattern(self) -> None:
        branches = ["main", "feature/auth", "feature/login", "bugfix/typo"]
        result = match_branches(branches, "feature/*")
        assert result == ["feature/auth", "feature/login"]

    def test_suffix_pattern(self) -> None:
        branches = ["feature/auth", "bugfix/auth", "main"]
        result = match_branches(branches, "*/auth")
        assert result == ["feature/auth", "bugfix/auth"]

    def test_no_match(self) -> None:
        branches = ["main", "develop"]
        result = match_branches(branches, "release*")
        assert result == []
