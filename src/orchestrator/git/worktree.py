"""Git worktree management for run isolation."""

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from orchestrator.git.errors import GitCommandError, WorktreeExistsError, WorktreeNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""

    path: Path
    branch: str
    commit: str


class WorktreeManager:
    """Manages git worktrees for run isolation."""

    def __init__(self, repo_path: Path, worktree_dir: Path):
        """
        Initialize the worktree manager.

        Args:
            repo_path: Path to the main git repository
            worktree_dir: Directory for worktrees (centralized, from global config)
        """
        self._repo = repo_path
        self._worktree_dir = worktree_dir

    def create(self, run_id: str, base_branch: str = "main") -> WorktreeInfo:
        """
        Create a new worktree for a run.

        Args:
            run_id: Unique identifier for the run
            base_branch: Branch to create the worktree from

        Returns:
            WorktreeInfo with path, branch, and commit

        Raises:
            WorktreeExistsError: If worktree already exists
            GitCommandError: If git command fails
        """
        worktree_path = self._worktree_dir / f"run-{run_id}"
        branch_name = f"orchestrator/run-{run_id}"

        # Check if worktree already exists
        if worktree_path.exists():
            raise WorktreeExistsError(run_id, str(worktree_path))

        # Ensure worktree directory exists
        self._worktree_dir.mkdir(parents=True, exist_ok=True)

        # Create worktree with new branch
        cmd = [
            "git",
            "worktree",
            "add",
            "-b",
            branch_name,
            str(worktree_path),
            base_branch,
        ]
        try:
            subprocess.run(
                cmd,
                cwd=self._repo,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

        # Symlink .venv from main repo to avoid duplicating the virtual environment
        main_venv = self._repo / ".venv"
        if main_venv.exists():
            (worktree_path / ".venv").symlink_to(main_venv.resolve())

        # Get commit SHA
        cmd = ["git", "rev-parse", "HEAD"]
        try:
            result = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

        return WorktreeInfo(
            path=worktree_path.resolve(),
            branch=branch_name,
            commit=result.stdout.strip(),
        )

    def ensure_exists(self, run_id: str, base_branch: str = "main") -> WorktreeInfo:
        """Ensure a worktree exists for a run, recreating it if the directory is missing.

        Unlike ``create()``, this method handles the case where the worktree
        directory was deleted (e.g., by cleanup) but the git branch may still
        exist from the original creation. It:

        1. Returns immediately if the directory already exists.
        2. Prunes stale git worktree entries (where the directory is gone).
        3. If the branch ``orchestrator/run-{run_id}`` already exists, creates
           the worktree pointing to that branch (preserving git history).
        4. If the branch doesn't exist, creates a fresh worktree and branch
           from ``base_branch`` (same as ``create()``).

        Args:
            run_id: Unique identifier for the run
            base_branch: Branch to use if a fresh worktree must be created

        Returns:
            WorktreeInfo with path, branch, and commit

        Raises:
            GitCommandError: If git command fails
        """
        worktree_path = self._worktree_dir / f"run-{run_id}"
        branch_name = f"orchestrator/run-{run_id}"

        if worktree_path.exists():
            # Already present - get the current commit and return
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return WorktreeInfo(
                    path=worktree_path.resolve(),
                    branch=branch_name,
                    commit=result.stdout.strip(),
                )
            except subprocess.CalledProcessError:
                pass  # Fall through to recreate

        # Prune stale worktree entries so git doesn't block re-adding
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self._repo,
            capture_output=True,
        )

        self._worktree_dir.mkdir(parents=True, exist_ok=True)

        # Check if the branch already exists
        branch_exists = (
            subprocess.run(
                ["git", "rev-parse", "--verify", branch_name],
                cwd=self._repo,
                capture_output=True,
            ).returncode
            == 0
        )

        if branch_exists:
            # Reuse the existing branch (preserves any committed work)
            cmd = ["git", "worktree", "add", str(worktree_path), branch_name]
        else:
            # Fresh worktree from base_branch
            cmd = ["git", "worktree", "add", "-b", branch_name, str(worktree_path), base_branch]

        try:
            subprocess.run(cmd, cwd=self._repo, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

        # Symlink .venv from main repo to avoid duplicating the virtual environment
        main_venv = self._repo / ".venv"
        if main_venv.exists() and not (worktree_path / ".venv").exists():
            (worktree_path / ".venv").symlink_to(main_venv.resolve())

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return WorktreeInfo(
            path=worktree_path.resolve(),
            branch=branch_name,
            commit=result.stdout.strip(),
        )

    def delete(self, run_id: str, force: bool = False) -> None:
        """
        Remove worktree for a run.

        Args:
            run_id: Unique identifier for the run
            force: Force removal even with uncommitted changes

        Raises:
            WorktreeNotFoundError: If worktree doesn't exist
            GitCommandError: If git command fails
        """
        worktree_path = self._worktree_dir / f"run-{run_id}"

        # Check if worktree exists
        if not worktree_path.exists():
            raise WorktreeNotFoundError(run_id, str(worktree_path))

        cmd: list[str] = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(worktree_path))

        try:
            subprocess.run(
                cmd,
                cwd=self._repo,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

    def list(self) -> list[WorktreeInfo]:
        """
        List all orchestrator worktrees.

        Returns:
            List of WorktreeInfo for all orchestrator-managed worktrees

        Raises:
            GitCommandError: If git command fails
        """
        cmd = ["git", "worktree", "list", "--porcelain"]
        try:
            result = subprocess.run(
                cmd,
                cwd=self._repo,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

        worktrees: list[WorktreeInfo] = []
        current: dict[str, str | Path] = {}

        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                current["path"] = Path(line.split(" ", 1)[1]).resolve()
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["commit"] = line.split(" ", 1)[1]
            elif line == "" and current:
                # Filter to orchestrator worktrees
                branch = current.get("branch", "")
                if isinstance(branch, str) and branch.startswith("refs/heads/orchestrator/"):
                    # Remove refs/heads/ prefix for cleaner branch name
                    path_val = current["path"]
                    commit_val = current["commit"]
                    if isinstance(path_val, Path) and isinstance(commit_val, str):
                        clean_branch = branch.replace("refs/heads/", "")
                        worktrees.append(
                            WorktreeInfo(path=path_val, branch=clean_branch, commit=commit_val)
                        )
                current = {}

        return worktrees

    def cleanup_stale(self, active_run_ids: set[str]) -> int:
        """
        Remove worktrees for runs that no longer exist.

        Args:
            active_run_ids: Set of currently active run IDs

        Returns:
            Number of worktrees removed

        Raises:
            GitCommandError: If git command fails
        """
        removed = 0
        for wt in self.list():
            # Extract run ID from branch name (orchestrator/run-{run_id})
            if wt.branch.startswith("orchestrator/run-"):
                run_id = wt.branch.replace("orchestrator/run-", "")
                if run_id not in active_run_ids:
                    try:
                        self.delete(run_id, force=True)
                        removed += 1
                    except WorktreeNotFoundError:
                        # Worktree was already removed, skip
                        pass

        return removed

    def cleanup_expired(
        self,
        all_run_ids: set[str],
        run_completed_at: dict[str, datetime],
        retention: timedelta,
        now: datetime | None = None,
    ) -> int:
        """Remove worktrees for runs that no longer exist or have expired.

        A worktree is removed if:
        - Its run ID is not found in all_run_ids (orphaned), or
        - Its run has a completed_at timestamp older than the retention period.

        Args:
            all_run_ids: Set of all known run IDs in the database.
            run_completed_at: Mapping of run_id → completed_at for terminal runs.
            retention: How long to keep worktrees after run completion.
            now: Current time (injectable for testing). Defaults to UTC now.

        Returns:
            Number of worktrees removed.
        """
        if now is None:
            from datetime import timezone

            now = datetime.now(timezone.utc)

        cutoff = now - retention
        removed = 0

        for wt in self.list():
            if not wt.branch.startswith("orchestrator/run-"):
                continue

            run_id = wt.branch.replace("orchestrator/run-", "")

            # Orphaned: run doesn't exist in DB at all
            if run_id not in all_run_ids:
                logger.info(f"Removing orphaned worktree for unknown run {run_id}")
                try:
                    self.delete(run_id, force=True)
                    removed += 1
                except WorktreeNotFoundError:
                    pass
                continue

            # Expired: run is terminal and older than retention period
            completed = run_completed_at.get(run_id)
            if completed is not None and completed < cutoff:
                logger.info(
                    f"Removing expired worktree for run {run_id} "
                    f"(completed {completed.isoformat()})"
                )
                try:
                    self.delete(run_id, force=True)
                    removed += 1
                except WorktreeNotFoundError:
                    pass

        return removed
