"""Git worktree management for run isolation."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import GitCommandError, WorktreeExistsError, WorktreeNotFoundError


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""

    path: Path
    branch: str
    commit: str


class WorktreeManager:
    """Manages git worktrees for run isolation."""

    def __init__(self, repo_path: Path, worktree_dir: Path | None = None):
        """
        Initialize the worktree manager.

        Args:
            repo_path: Path to the main git repository
            worktree_dir: Directory for worktrees (default: repo/.worktrees)
        """
        self._repo = repo_path
        self._worktree_dir = worktree_dir or repo_path / ".worktrees"

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
