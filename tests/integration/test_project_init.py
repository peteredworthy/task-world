"""Integration tests for project initialization."""

import subprocess
from pathlib import Path

import pytest

from orchestrator.git.project_init import init_project


def test_init_project_creates_git_repo(tmp_path: Path) -> None:
    """init_project creates a directory with git initialized and an initial commit."""
    project_path = tmp_path / "new-project"

    result = init_project(project_path, use_uv=False)

    assert result.path == project_path
    assert result.git_initialized is True
    assert result.uv_initialized is False
    assert project_path.exists()
    assert (project_path / ".git").exists()

    # Verify there's at least one commit
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=project_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Initial project setup" in log.stdout

    # Verify main branch
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch.stdout.strip() == "main"


def test_init_project_with_uv(tmp_path: Path) -> None:
    """init_project with use_uv=True runs uv init if uv is available."""
    project_path = tmp_path / "uv-project"

    result = init_project(project_path, use_uv=True)

    assert result.path == project_path
    assert result.git_initialized is True
    # uv_initialized depends on whether uv is installed
    # In our test environment uv is installed
    assert result.uv_initialized is True
    assert (project_path / "pyproject.toml").exists()


def test_init_project_raises_if_exists(tmp_path: Path) -> None:
    """init_project raises FileExistsError if path already exists."""
    project_path = tmp_path / "existing"
    project_path.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        init_project(project_path)


def test_init_project_creates_readme(tmp_path: Path) -> None:
    """init_project creates a README.md if none exists."""
    project_path = tmp_path / "readme-project"

    init_project(project_path, use_uv=False)

    assert (project_path / "README.md").exists()
    assert "# New Project" in (project_path / "README.md").read_text()
