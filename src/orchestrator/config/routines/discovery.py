"""Discover routines from directories and git repositories."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import RoutineConfig
from orchestrator.config.routines.errors import RoutineError
from orchestrator.config.routines.loader import load_routine_from_path


@dataclass
class DiscoveredRoutine:
    """A routine discovered from a directory scan or git repository."""

    config: RoutineConfig
    source: RoutineSource
    path: Path | str  # Path object for local, string for git-based
    commit: str | None = None  # Git commit SHA (for PROJECT routines)
    scaffolding_path: str | None = None  # Path to scaffolding/ directory (for PROJECT routines)


@dataclass
class ProjectRoutine:
    """A routine discovered from a project repository.

    This is the extended routine info returned from discover_routines_in_repo().
    """

    config: RoutineConfig
    source: RoutineSource = field(default=RoutineSource.PROJECT)
    path: str = ""  # Relative path within repo (e.g., "routines/feature.yaml")
    commit: str = ""  # Commit SHA where routine was read
    scaffolding_path: str | None = None  # Path to scaffolding/ if exists
    has_scaffolding: bool = False


def discover_routines(
    directories: list[tuple[Path, RoutineSource]],
) -> list[DiscoveredRoutine]:
    """Scan directories for routine YAML files.

    Supports both flat format (routine.yaml) and directory format (dir/routine.yaml).

    Args:
        directories: List of (directory_path, source_type) tuples.

    Returns:
        List of DiscoveredRoutine for each valid routine found.
        Invalid files are silently skipped.
    """
    routines: list[DiscoveredRoutine] = []

    for directory, source in directories:
        if not directory.is_dir():
            continue

        # Scan for flat file routines (*.yaml, *.yml)
        for yaml_path in sorted(directory.glob("*.yaml")):
            try:
                config = load_routine_from_path(yaml_path)
                routines.append(DiscoveredRoutine(config=config, source=source, path=yaml_path))
            except RoutineError:
                continue

        for yml_path in sorted(directory.glob("*.yml")):
            try:
                config = load_routine_from_path(yml_path)
                routines.append(DiscoveredRoutine(config=config, source=source, path=yml_path))
            except RoutineError:
                continue

        # Scan for directory-based routines (*/routine.yaml or */routine.yml)
        for subdir in sorted(directory.iterdir()):
            if not subdir.is_dir():
                continue

            for routine_file in ["routine.yaml", "routine.yml"]:
                routine_path = subdir / routine_file
                if routine_path.exists():
                    try:
                        config = load_routine_from_path(routine_path)
                        # Check for scaffolding directory
                        scaffolding_path = subdir / "scaffolding"
                        scaffolding_str = (
                            str(scaffolding_path) if scaffolding_path.exists() else None
                        )
                        routines.append(
                            DiscoveredRoutine(
                                config=config,
                                source=source,
                                path=routine_path,
                                scaffolding_path=scaffolding_str,
                            )
                        )
                    except RoutineError:
                        continue
                    break  # Only load first matching routine file per directory

    # Deduplicate by (routine ID, source) — within each source, later entries win
    # (directory-based routines are scanned after flat files, so they take priority).
    # But routines with same ID from different sources are both kept.
    seen: dict[tuple[str, RoutineSource], int] = {}
    for i, r in enumerate(routines):
        seen[(r.config.id, r.source)] = i
    routines = [routines[i] for i in sorted(seen.values())]

    return routines


def discover_routines_in_repo(
    repo_path: Path,
    branch: str = "main",
) -> list[ProjectRoutine]:
    """Discover routines from {repo}/routines/ at specified branch.

    Uses git to read files without checkout.
    Returns routines with both embedded config and path+commit reference.

    Args:
        repo_path: Path to the git repository
        branch: Branch to read routines from

    Returns:
        List of ProjectRoutine for each valid routine found.
        Invalid files are silently skipped.
    """
    routines: list[ProjectRoutine] = []

    # Get commit SHA for branch
    try:
        commit = _git_rev_parse(repo_path, branch)
    except subprocess.CalledProcessError:
        return []

    # List files in routines/ directory at the branch
    try:
        files = _git_ls_tree(repo_path, branch, "routines/")
    except subprocess.CalledProcessError:
        return []

    # Track which directories have routine.yaml (for directory-based routines)
    routine_dirs: set[str] = set()
    routine_files: list[str] = []

    for file_path in files:
        # Check for directory-based routines (routines/*/routine.yaml)
        if file_path.endswith("/routine.yaml") or file_path.endswith("/routine.yml"):
            routine_files.append(file_path)
            # Extract directory path (e.g., "routines/feature-x/")
            dir_path = str(Path(file_path).parent) + "/"
            routine_dirs.add(dir_path)
        # Check for flat file routines (routines/*.yaml or routines/*.yml)
        elif file_path.startswith("routines/") and "/" not in file_path[len("routines/") :]:
            if file_path.endswith(".yaml") or file_path.endswith(".yml"):
                routine_files.append(file_path)

    # Process each routine file
    for file_path in routine_files:
        try:
            content = _git_show(repo_path, branch, file_path)
            config = _parse_routine_content(content, file_path)

            # Check for scaffolding directory (directory-based routines only)
            scaffolding_path = None
            has_scaffolding = False
            if file_path.endswith("/routine.yaml") or file_path.endswith("/routine.yml"):
                dir_path = str(Path(file_path).parent)
                scaffolding_dir = f"{dir_path}/scaffolding/"
                # Check if any files exist in the scaffolding directory
                has_scaffolding = any(f.startswith(scaffolding_dir) for f in files)
                if has_scaffolding:
                    scaffolding_path = scaffolding_dir

            routines.append(
                ProjectRoutine(
                    config=config,
                    path=file_path,
                    commit=commit,
                    scaffolding_path=scaffolding_path,
                    has_scaffolding=has_scaffolding,
                )
            )
        except (subprocess.CalledProcessError, yaml.YAMLError, ValidationError, RoutineError):
            # Skip invalid routines
            continue

    return sorted(routines, key=lambda r: r.config.id)


def get_routine_from_repo(
    repo_path: Path,
    branch: str,
    routine_id: str,
) -> ProjectRoutine | None:
    """Get a specific routine from a repository.

    Args:
        repo_path: Path to the git repository
        branch: Branch to read from
        routine_id: The routine ID to find

    Returns:
        ProjectRoutine if found, None otherwise
    """
    routines = discover_routines_in_repo(repo_path, branch)
    for routine in routines:
        if routine.config.id == routine_id:
            return routine
    return None


def _git_rev_parse(repo_path: Path, ref: str) -> str:
    """Get the commit SHA for a reference (branch, tag, commit)."""
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_ls_tree(repo_path: Path, ref: str, path_prefix: str) -> list[str]:
    """List files under a path at a specific ref.

    Returns list of file paths (relative to repo root).
    """
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", path_prefix],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.strip().split("\n") if line]


def _git_show(repo_path: Path, ref: str, file_path: str) -> str:
    """Read file content at a specific ref."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{file_path}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _parse_routine_content(content: str, file_path: str) -> RoutineConfig:
    """Parse routine content from a YAML string.

    Args:
        content: YAML content
        file_path: Path for error messages

    Returns:
        Validated RoutineConfig

    Raises:
        yaml.YAMLError: If YAML is invalid
        ValidationError: If content doesn't match schema
    """
    raw = yaml.safe_load(content)

    if raw is None:
        raise ValueError(f"Empty file: {file_path}")

    data: Any = raw

    # Handle both wrapped and unwrapped format
    if isinstance(data, dict) and "routine" in data:
        data = cast(Any, data["routine"])

    return RoutineConfig.model_validate(data)
