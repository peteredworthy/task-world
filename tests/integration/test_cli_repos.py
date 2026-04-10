"""Integration tests for CLI repo commands."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from orchestrator.cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CLI runner."""
    return CliRunner()


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    """Create a repos directory with sample repositories."""
    repos = tmp_path / "repos"
    repos.mkdir()
    return repos


@pytest.fixture
def sample_repo(repos_dir: Path, _base_repo: Path) -> Path:
    """Create a sample git repository with feature branches."""
    repo = repos_dir / "sample-project"
    shutil.copytree(str(_base_repo), str(repo))

    # Create additional branches
    subprocess.run(
        ["git", "checkout", "-b", "feature/auth"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "feature/api"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "release-1.0"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


def test_repos_list_empty(runner: CliRunner, repos_dir: Path) -> None:
    """Test repos list with no repositories."""
    result = runner.invoke(cli, ["repos", "list", "--repos-dir", str(repos_dir)])
    assert result.exit_code == 0
    assert "No repositories found" in result.output


def test_repos_list_with_repo(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos list with a repository."""
    repos_dir = sample_repo.parent
    result = runner.invoke(cli, ["repos", "list", "--repos-dir", str(repos_dir)])
    assert result.exit_code == 0
    assert "sample-project" in result.output
    assert "Default branch:" in result.output


def test_repos_list_json(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos list with JSON output."""
    repos_dir = sample_repo.parent
    result = runner.invoke(cli, ["--json", "repos", "list", "--repos-dir", str(repos_dir)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "sample-project"
    assert "default_branch" in data[0]


def test_repos_show(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos show command."""
    repos_dir = sample_repo.parent
    result = runner.invoke(cli, ["repos", "show", "sample-project", "--repos-dir", str(repos_dir)])
    assert result.exit_code == 0
    assert "Repository: sample-project" in result.output
    assert "Path:" in result.output
    assert "Default branch:" in result.output
    assert "Local branches:" in result.output


def test_repos_show_json(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos show with JSON output."""
    repos_dir = sample_repo.parent
    result = runner.invoke(
        cli, ["--json", "repos", "show", "sample-project", "--repos-dir", str(repos_dir)]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "sample-project"
    assert "local_branches" in data
    assert "remote_branches" in data


def test_repos_show_not_found(runner: CliRunner, repos_dir: Path) -> None:
    """Test repos show with non-existent repository."""
    result = runner.invoke(cli, ["repos", "show", "nonexistent", "--repos-dir", str(repos_dir)])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_repos_branches(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos branches command."""
    repos_dir = sample_repo.parent
    result = runner.invoke(
        cli, ["repos", "branches", "sample-project", "--repos-dir", str(repos_dir)]
    )
    assert result.exit_code == 0
    # Should show all created branches
    assert "feature/auth" in result.output
    assert "feature/api" in result.output
    assert "release-1.0" in result.output
    assert "main" in result.output


def test_repos_branches_with_pattern(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos branches with glob pattern filter."""
    repos_dir = sample_repo.parent
    result = runner.invoke(
        cli,
        ["repos", "branches", "sample-project", "feature/*", "--repos-dir", str(repos_dir)],
    )
    assert result.exit_code == 0
    # Should only show feature branches
    assert "feature/auth" in result.output
    assert "feature/api" in result.output
    assert "release-1.0" not in result.output
    assert "matching 'feature/*'" in result.output


def test_repos_branches_pattern_no_match(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos branches with pattern that matches nothing."""
    repos_dir = sample_repo.parent
    result = runner.invoke(
        cli,
        ["repos", "branches", "sample-project", "bugfix/*", "--repos-dir", str(repos_dir)],
    )
    assert result.exit_code == 0
    assert "No branches matching" in result.output


def test_repos_branches_json(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos branches with JSON output."""
    repos_dir = sample_repo.parent
    result = runner.invoke(
        cli,
        ["--json", "repos", "branches", "sample-project", "--repos-dir", str(repos_dir)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "branches" in data
    assert "total" in data
    assert "truncated" in data
    branch_names = [b["name"] for b in data["branches"]]
    assert "main" in branch_names
    assert "feature/auth" in branch_names


def test_repos_branches_local_only(runner: CliRunner, sample_repo: Path) -> None:
    """Test repos branches with --local-only flag."""
    repos_dir = sample_repo.parent
    result = runner.invoke(
        cli,
        [
            "repos",
            "branches",
            "sample-project",
            "--local-only",
            "--repos-dir",
            str(repos_dir),
        ],
    )
    assert result.exit_code == 0
    # All branches should be local (no remote marker)
    assert "(remote)" not in result.output


def test_repos_branches_not_found(runner: CliRunner, repos_dir: Path) -> None:
    """Test repos branches with non-existent repository."""
    result = runner.invoke(cli, ["repos", "branches", "nonexistent", "--repos-dir", str(repos_dir)])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()
