"""Copy routine-adjacent files (scripts, scaffolding, etc.) to worktree.

This module provides the primary mechanism for making routine files available
inside a worktree.  All files adjacent to the routine YAML (except the YAML
itself) are copied to ``.orchestrator/routine-files/`` in the worktree so that
both the orchestrator server (for script tasks and auto-verify) and the agent
environment can reference them at a predictable path.
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.runners.scaffolding.copier import ensure_gitignore

logger = logging.getLogger(__name__)

_ROUTINE_YAML_NAMES = {"routine.yaml", "routine.yml"}
# Also skip files that look like standalone routine YAMLs (flat format)
_SKIP_SUFFIXES = {".yaml", ".yml"}


@dataclass
class RoutineFilesResult:
    """Result of a routine-files copy operation."""

    files_copied: int
    target_path: str
    gitignore_updated: bool


def copy_routine_files_local(
    source_dir: Path,
    worktree_path: Path,
    target_dir: str = ".orchestrator/routine-files",
) -> RoutineFilesResult:
    """Copy routine-adjacent files from a local directory to a worktree.

    Walks ``source_dir``, skipping the routine YAML itself, and copies all
    other files preserving directory structure into ``worktree_path / target_dir``.

    Args:
        source_dir: Absolute path to the routine directory on disk.
        worktree_path: Path to the worktree.
        target_dir: Relative target directory within the worktree.

    Returns:
        RoutineFilesResult with copy details.
    """
    target = worktree_path / target_dir
    files_copied = 0

    if not source_dir.is_dir():
        logger.warning(f"Routine source dir not found: {source_dir}")
        gitignore_updated = ensure_gitignore(worktree_path, ".orchestrator/")
        return RoutineFilesResult(
            files_copied=0,
            target_path=str(target),
            gitignore_updated=gitignore_updated,
        )

    for src_file in sorted(source_dir.rglob("*")):
        if not src_file.is_file():
            continue

        rel = src_file.relative_to(source_dir)

        # Skip the routine YAML at the root level
        if rel.name in _ROUTINE_YAML_NAMES and len(rel.parts) == 1:
            continue

        # Skip README files at the root level
        if rel.name.upper().startswith("README") and len(rel.parts) == 1:
            continue

        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        files_copied += 1

    if files_copied > 100:
        logger.warning(
            f"Copied {files_copied} routine files from {source_dir} — "
            f"consider trimming the routine directory"
        )

    gitignore_updated = ensure_gitignore(worktree_path, ".orchestrator/")
    return RoutineFilesResult(
        files_copied=files_copied,
        target_path=str(target),
        gitignore_updated=gitignore_updated,
    )


def copy_routine_files_git(
    repo_path: Path,
    routine_path: str,
    routine_commit: str,
    worktree_path: Path,
    target_dir: str = ".orchestrator/routine-files",
) -> RoutineFilesResult:
    """Copy routine-adjacent files from a git repository to a worktree.

    Uses ``git ls-tree`` and ``git show`` to extract all files in the routine
    directory (except the routine YAML) at a specific commit.

    Args:
        repo_path: Path to the git repository containing the routine.
        routine_path: Path to routine YAML within the repo
            (e.g., ``"routines/feature-x/routine.yaml"``).
        routine_commit: Git commit SHA to read files at.
        worktree_path: Path to the worktree.
        target_dir: Relative target directory within the worktree.

    Returns:
        RoutineFilesResult with copy details.
    """
    target = worktree_path / target_dir
    target.mkdir(parents=True, exist_ok=True)

    routine_dir = str(Path(routine_path).parent)
    dir_prefix = f"{routine_dir}/"

    # List all files in the routine directory
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", routine_commit, "--", dir_prefix],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to list routine files via git: {e.stderr}")
        gitignore_updated = ensure_gitignore(worktree_path, ".orchestrator/")
        return RoutineFilesResult(
            files_copied=0,
            target_path=str(target),
            gitignore_updated=gitignore_updated,
        )

    files_copied = 0
    routine_yaml_name = Path(routine_path).name

    for file_path in result.stdout.strip().split("\n"):
        if not file_path:
            continue

        rel_path = file_path[len(dir_prefix) :]
        if not rel_path:
            continue

        # Skip the routine YAML itself
        if rel_path == routine_yaml_name:
            continue

        # Skip README at root of routine dir
        if "/" not in rel_path and rel_path.upper().startswith("README"):
            continue

        # Extract file content
        try:
            content_result = subprocess.run(
                ["git", "show", f"{routine_commit}:{file_path}"],
                cwd=repo_path,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to read {file_path} from git: {e.stderr}")
            continue

        dst = target / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content_result.stdout)
        files_copied += 1

    gitignore_updated = ensure_gitignore(worktree_path, ".orchestrator/")
    return RoutineFilesResult(
        files_copied=files_copied,
        target_path=str(target),
        gitignore_updated=gitignore_updated,
    )
