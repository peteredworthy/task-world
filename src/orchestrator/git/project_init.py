"""Project initialization: create a new project directory with git (and optionally uv)."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import GitCommandError


@dataclass
class InitializedProject:
    """Result of initializing a new project."""

    path: Path
    git_initialized: bool
    uv_initialized: bool


def init_project(project_path: Path, use_uv: bool = True) -> InitializedProject:
    """Initialize a new project directory with git and optionally uv.

    Creates the directory, runs `git init`, configures git user,
    runs `uv init` (optional), and creates an initial commit.

    Args:
        project_path: Path where the project should be created.
        use_uv: Whether to run `uv init` for Python project setup.

    Returns:
        InitializedProject with details about what was created.

    Raises:
        FileExistsError: If the path already exists.
        GitCommandError: If git commands fail.
    """
    if project_path.exists():
        raise FileExistsError(f"Project path already exists: {project_path}")

    project_path.mkdir(parents=True)

    # git init
    try:
        subprocess.run(
            ["git", "init"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitCommandError("git init", e.returncode, e.stderr) from e

    # Configure git user
    for config_cmd in [
        ["git", "config", "user.email", "orchestrator@local"],
        ["git", "config", "user.name", "Orchestrator"],
    ]:
        try:
            subprocess.run(
                config_cmd,
                cwd=project_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(config_cmd), e.returncode, e.stderr) from e

    # uv init (optional)
    uv_initialized = False
    if use_uv:
        try:
            subprocess.run(
                ["uv", "init"],
                cwd=project_path,
                check=True,
                capture_output=True,
                text=True,
            )
            uv_initialized = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            # uv not available or failed - continue without it
            pass

    # Ensure there's at least one file to commit
    readme = project_path / "README.md"
    if not readme.exists():
        readme.write_text("# New Project\n")

    # Stage all and create initial commit
    try:
        subprocess.run(
            ["git", "add", "."],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial project setup"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "branch", "-M", "main"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitCommandError(" ".join(e.cmd), e.returncode, e.stderr) from e

    return InitializedProject(
        path=project_path,
        git_initialized=True,
        uv_initialized=uv_initialized,
    )
