"""Copy scaffolding files from git repository to worktree."""

import subprocess
from pathlib import Path

from orchestrator.runners.scaffolding.errors import ScaffoldingCopyError
from orchestrator.runners.scaffolding.models import ScaffoldingResult


def copy_scaffolding(
    repo_path: Path,
    routine_path: str,
    routine_commit: str,
    worktree_path: Path,
    target_dir: str = ".orchestrator/scaffolding",
) -> ScaffoldingResult:
    """Extract scaffolding from routine at specific commit and copy to worktree.

    Args:
        repo_path: Path to the git repository containing the routine
        routine_path: Path to routine within repo (e.g., "routines/feature-x/routine.yaml")
        routine_commit: Git commit SHA where the routine was read
        worktree_path: Path to the worktree where scaffolding will be copied
        target_dir: Target directory within worktree (relative path)

    Returns:
        ScaffoldingResult with details of the copy operation

    Raises:
        ScaffoldingCopyError: If copying fails
    """
    target = worktree_path / target_dir
    target.mkdir(parents=True, exist_ok=True)

    # Get scaffolding directory path from routine path
    routine_dir = str(Path(routine_path).parent)
    scaffolding_prefix = f"{routine_dir}/scaffolding/"

    # List files in scaffolding directory
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", routine_commit, "--", scaffolding_prefix],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise ScaffoldingCopyError(
            scaffolding_prefix, str(target), f"Failed to list scaffolding files: {e.stderr}"
        ) from e

    files_copied = 0
    for file_path in result.stdout.strip().split("\n"):
        if not file_path:
            continue

        # Extract relative path within scaffolding
        rel_path = file_path[len(scaffolding_prefix) :]
        if not rel_path:
            continue

        # Get file content from git
        try:
            content_result = subprocess.run(
                ["git", "show", f"{routine_commit}:{file_path}"],
                cwd=repo_path,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise ScaffoldingCopyError(
                file_path, str(target / rel_path), f"Failed to read file: {e.stderr}"
            ) from e

        # Write to target
        target_file = target / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(content_result.stdout)
        files_copied += 1

    # Ensure .orchestrator/ is in .gitignore
    gitignore_updated = ensure_gitignore(worktree_path, ".orchestrator/")

    return ScaffoldingResult(
        files_copied=files_copied,
        target_path=str(target),
        gitignore_updated=gitignore_updated,
    )


def ensure_gitignore(worktree_path: Path, entry: str) -> bool:
    """Ensure generated scaffolding is ignored without changing project files.

    Args:
        worktree_path: Path to the worktree
        entry: Entry to add to .gitignore

    Returns:
        True if an exclude file was modified, False if entry already existed
    """
    # Real run checkouts are Git worktrees.  Resolve the repository-local exclude
    # path through Git so linked-worktree layouts are handled correctly.  This
    # keeps orchestrator-owned scaffolding out of candidate diffs without adding
    # an unrequested source file to repositories that do not track .gitignore.
    exclude_result = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if exclude_result.returncode == 0:
        exclude = Path(exclude_result.stdout.strip())
        if not exclude.is_absolute():
            exclude = worktree_path / exclude
        exclude.parent.mkdir(parents=True, exist_ok=True)
        repository_entry = "/.orchestrator/" if entry.rstrip("/") == ".orchestrator" else entry
        return _ensure_ignore_entry(exclude, repository_entry)

    if (worktree_path / ".git").exists():
        reason = exclude_result.stderr.strip() or "Git could not resolve info/exclude"
        raise ScaffoldingCopyError(entry, str(worktree_path), reason)

    # Preserve compatibility for callers preparing a directory before it is
    # attached as a Git worktree.  Runtime-created linked worktrees always take
    # the repository-local exclude path above.
    return _ensure_ignore_entry(worktree_path / ".gitignore", entry)


def _ensure_ignore_entry(ignore_file: Path, entry: str) -> bool:
    """Append one ignore entry to ``ignore_file`` if it is absent."""

    if ignore_file.exists():
        content = ignore_file.read_text()
        # Check if entry already exists (accounting for newlines)
        entries = set(line.strip() for line in content.split("\n"))
        variants = {entry, entry.rstrip("/")}
        if entry.startswith("/"):
            variants.update({entry.lstrip("/"), entry.lstrip("/").rstrip("/")})
        if variants.intersection(entries):
            return False
        # Append entry
        with ignore_file.open("a") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(f"{entry}\n")
        return True
    ignore_file.write_text(f"{entry}\n")
    return True
