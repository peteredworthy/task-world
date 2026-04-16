"""Git worktree management for run isolation."""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

    def __init__(
        self,
        repo_path: Path,
        worktree_dir: Path,
        server_port: int = 8000,
        worktree_base_port: int = 9000,
    ):
        """
        Initialize the worktree manager.

        Args:
            repo_path: Path to the main git repository
            worktree_dir: Directory for worktrees (centralized, from global config)
            server_port: Port the main server runs on (default 8000)
            worktree_base_port: Base port for worktree servers (default 9000)
        """
        self._repo = repo_path
        self._worktree_dir = worktree_dir
        self._server_port = server_port
        self._worktree_base_port = worktree_base_port

    _COUNTER_RE = re.compile(r"^r(\d+)$")

    def _next_counter(self) -> int:
        """Return the next available counter for short worktree directory names.

        Scans ``_worktree_dir`` for directories matching ``r<N>`` and returns
        max(N) + 1, or 1 if none exist.
        """
        max_n = 0
        if self._worktree_dir.is_dir():
            for entry in self._worktree_dir.iterdir():
                if entry.is_dir():
                    m = self._COUNTER_RE.match(entry.name)
                    if m:
                        max_n = max(max_n, int(m.group(1)))
        return max_n + 1

    def _write_manifest(
        self,
        worktree_path: Path,
        run_id: str,
        branch: str,
        worktree_number: int,
    ) -> None:
        """Write a `.worktree-manifest.json` into the worktree directory.

        The manifest declares identity, assigned port, and main server URL so
        that startup guards and agents can discover their configuration.
        """
        worktree_name = f"r{worktree_number}"
        assigned_port = self._worktree_base_port + worktree_number
        manifest = {
            "is_worktree": True,
            "worktree_number": worktree_number,
            "worktree_name": worktree_name,
            "main_repo_path": str(self._repo),
            "main_server_url": f"http://localhost:{self._server_port}",
            "assigned_port": assigned_port,
            "run_id": run_id,
            "branch": branch,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = worktree_path / ".worktree-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        # Ensure the manifest is git-ignored so it doesn't count as an
        # untracked file (which would block non-force worktree deletion).
        # Worktrees share the main repo's .git/info/exclude, not their own.
        _entry = ".worktree-manifest.json"
        exclude_file = self._repo / ".git" / "info" / "exclude"
        try:
            exclude_file.parent.mkdir(parents=True, exist_ok=True)
            existing = exclude_file.read_text() if exclude_file.exists() else ""
            if _entry not in existing:
                with exclude_file.open("a") as f:
                    f.write(f"{_entry}\n")
        except OSError:
            pass  # Best-effort; won't block worktree usage

        logger.info("Wrote worktree manifest: %s (port=%d)", manifest_path, assigned_port)

    def _write_sandbox_settings(self, worktree_path: Path) -> None:
        """Write a ``.claude/settings.local.json`` with absolute-path sandbox rules.

        All reads are denied by default (``denyRead: ["/"]``), then re-allowed
        only for the worktree, temp directories, and essential system paths.
        Because ``allowWrite`` is a strict allowlist, anything not in it is
        already write-denied.  ``denyWrite`` is used for any ``allowRead`` paths
        that should be readable but not writable.
        """
        wt_abs = str(worktree_path.resolve())
        repo_abs = str(self._repo.resolve())
        tmp_dir = os.environ.get("TMPDIR", "/tmp").rstrip("/")

        # Paths the agent can read for context but must not modify.
        read_only_paths = [
            f"{repo_abs}/src",
            f"{repo_abs}/scripts",
            f"{repo_abs}/ui",
            f"{repo_abs}/.git",
            # Knowledge graph — agents can query it even if the worktree copy
            # is missing or stale (e.g. when .worktree-setup was skipped).
            f"{repo_abs}/graphify-out",
        ]

        settings = {
            "permissions": {
                "allow": [
                    f"Read({wt_abs}/**)",
                    f"Edit({wt_abs}/**)",
                    f"Write({wt_abs}/**)",
                    f"Glob({wt_abs}/**)",
                    f"Grep({wt_abs}/**)",
                ],
                "deny": [],
            },
            "sandbox": {
                "enabled": True,
                "filesystem": {
                    "denyRead": ["/"],
                    "allowRead": [
                        wt_abs,
                        "/tmp",
                        tmp_dir,
                        "/usr",
                        "/System",
                        "/Library",
                        "/bin",
                        "/sbin",
                        "/private/var",
                        "/private/etc",
                        "/opt/homebrew",
                        "/dev",
                        *read_only_paths,
                    ],
                    "allowWrite": [
                        wt_abs,
                        "/tmp",
                        tmp_dir,
                    ],
                    "denyWrite": read_only_paths,
                },
                "network": {
                    "allowedDomains": [
                        "localhost",
                        "127.0.0.1",
                    ],
                },
            },
        }

        settings_dir = worktree_path / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.local.json"
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

        # Git-ignore settings.local.json so it doesn't pollute the worktree
        _entry = ".claude/settings.local.json"
        exclude_file = self._repo / ".git" / "info" / "exclude"
        try:
            existing = exclude_file.read_text() if exclude_file.exists() else ""
            if _entry not in existing:
                with exclude_file.open("a") as f:
                    f.write(f"{_entry}\n")
        except OSError:
            pass

        logger.info("Wrote sandbox settings: %s", settings_path)

    @staticmethod
    def _worktree_number_from_path(worktree_path: Path) -> int:
        """Extract the worktree number from a path like ``worktrees/r27``."""
        m = re.match(r"^r(\d+)$", worktree_path.name)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _create_worktree_venv(worktree_path: Path) -> None:
        """Create an independent virtual environment in a worktree.

        Runs ``uv sync`` which creates the ``.venv``, installs all dependencies,
        and sets up the editable install pointing at the *worktree's* ``src/``.
        With uv's global cache (hardlinks), this adds negligible disk overhead.
        """
        logger.info("Creating independent venv in %s", worktree_path)
        try:
            subprocess.run(
                ["uv", "sync", "--frozen"],
                cwd=worktree_path,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            logger.warning("uv not found; falling back to venv symlink")
            main_venv = worktree_path.parent.parent / ".venv"
            if main_venv.exists() and not (worktree_path / ".venv").exists():
                (worktree_path / ".venv").symlink_to(main_venv.resolve())
        except subprocess.TimeoutExpired:
            logger.warning("uv sync timed out after 120s in %s", worktree_path)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "uv sync failed in %s (exit %d): %s",
                worktree_path,
                e.returncode,
                e.stderr.strip() if e.stderr else "(no output)",
            )

    def _run_worktree_setup(self, worktree_path: Path) -> None:
        """Run the project's worktree setup script if it exists.

        Looks for ``.worktree-setup`` in the main repo root and executes it
        with ``<worktree-path> <main-repo-path>`` as arguments.  Failures are
        logged but do **not** prevent the worktree from being used.
        """
        setup_script = self._repo / ".worktree-setup"
        if not setup_script.exists():
            return

        cmd = [str(setup_script), str(worktree_path), str(self._repo)]
        logger.info("Running worktree setup: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                cwd=self._repo,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Worktree setup script timed out after 120s")
        except subprocess.CalledProcessError as e:
            logger.warning(
                "Worktree setup script failed (exit %d): %s",
                e.returncode,
                e.stderr.strip() if e.stderr else "(no output)",
            )
        except OSError as e:
            logger.warning("Could not run worktree setup script: %s", e)

    def create(self, run_id: str, base_branch: str = "main") -> WorktreeInfo:
        """
        Create a new worktree for a run.

        Uses a short counter-based directory name (``r1``, ``r2``, …) to keep
        paths short. The branch name ``orchestrator/run-{run_id}`` is kept
        unchanged for identification.

        Args:
            run_id: Unique identifier for the run
            base_branch: Branch to create the worktree from

        Returns:
            WorktreeInfo with path, branch, and commit

        Raises:
            WorktreeExistsError: If worktree already exists
            GitCommandError: If git command fails
        """
        branch_name = f"orchestrator/run-{run_id}"

        # Check if a worktree for this run already exists (by branch)
        for wt in self.list():
            if wt.branch == branch_name:
                raise WorktreeExistsError(run_id, str(wt.path))

        # Ensure worktree directory exists
        self._worktree_dir.mkdir(parents=True, exist_ok=True)

        # Use short counter-based directory name
        worktree_path = self._worktree_dir / f"r{self._next_counter()}"

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

        # Create an independent venv for the worktree.  A symlink to the main
        # venv is NOT safe: `uv run` detects the project-root mismatch and
        # re-syncs, overwriting the editable-install .pth to point at the
        # worktree's src/.  That redirects the main server's imports into the
        # worktree — breaking isolation completely.
        self._create_worktree_venv(worktree_path)

        # Write manifest before setup script so it can read it
        wt_number = self._worktree_number_from_path(worktree_path)
        self._write_manifest(worktree_path, run_id, branch_name, wt_number)

        # Write sandbox settings with absolute paths so agents cannot escape
        # the worktree (the project-level ./ path resolves ambiguously in
        # worktrees due to git topology).
        self._write_sandbox_settings(worktree_path)

        self._run_worktree_setup(worktree_path)

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

    def checkout(self, run_id: str, commit: str, worktree_path: str | Path) -> None:
        """Checkout a commit in a worktree, keeping HEAD on the run's branch.

        Uses ``git checkout -B <branch> <commit>`` so the branch pointer moves
        to the target commit without detaching HEAD.  This prevents the agent
        from accidentally committing to ``main`` or another shared branch.

        Args:
            run_id: Run identifier (used to derive the branch name).
            commit: The commit SHA to check out.
            worktree_path: Filesystem path of the worktree.

        Raises:
            GitCommandError: If the checkout fails.
        """
        branch_name = f"orchestrator/run-{run_id}"
        cmd = ["git", "checkout", "-B", branch_name, commit]
        try:
            subprocess.run(
                cmd,
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

    def ensure_branch(self, run_id: str, worktree_path: str | Path) -> None:
        """Ensure a worktree's HEAD is on its run branch, not detached.

        If HEAD is already on the correct branch this is a no-op.

        Args:
            run_id: Run identifier (used to derive the branch name).
            worktree_path: Filesystem path of the worktree.

        Raises:
            GitCommandError: If the checkout fails.
        """
        branch_name = f"orchestrator/run-{run_id}"
        # Check if already on the right branch
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip() == branch_name:
                return
        except subprocess.CalledProcessError:
            pass  # Detached HEAD — need to re-attach

        cmd = ["git", "checkout", branch_name]
        try:
            subprocess.run(
                cmd,
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

    def ensure_exists(
        self,
        run_id: str,
        base_branch: str = "main",
        worktree_path: str | None = None,
    ) -> WorktreeInfo:
        """Ensure a worktree exists for a run, recreating it if the directory is missing.

        Unlike ``create()``, this method handles the case where the worktree
        directory was deleted (e.g., by cleanup) but the git branch may still
        exist from the original creation. It:

        1. Returns immediately if the directory already exists (checks provided
           ``worktree_path`` first, then searches by branch name).
        2. Prunes stale git worktree entries (where the directory is gone).
        3. If the branch ``orchestrator/run-{run_id}`` already exists, creates
           the worktree pointing to that branch (preserving git history).
        4. If the branch doesn't exist, creates a fresh worktree and branch
           from ``base_branch`` (same as ``create()``).

        Args:
            run_id: Unique identifier for the run
            base_branch: Branch to use if a fresh worktree must be created
            worktree_path: Known path for this worktree (from the run record).
                If provided and exists, used directly. Otherwise searches by
                branch name or allocates a new counter-based path.

        Returns:
            WorktreeInfo with path, branch, and commit

        Raises:
            GitCommandError: If git command fails
        """
        branch_name = f"orchestrator/run-{run_id}"

        # Try the provided path first
        if worktree_path:
            wt_path = Path(worktree_path)
            if wt_path.exists():
                git_marker = wt_path / ".git"
                if not git_marker.exists():
                    # Directory exists but .git is missing — broken worktree
                    logger.warning(f"Worktree directory {wt_path} exists but has no .git file")
                else:
                    try:
                        result = subprocess.run(
                            ["git", "rev-parse", "HEAD"],
                            cwd=wt_path,
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        return WorktreeInfo(
                            path=wt_path.resolve(),
                            branch=branch_name,
                            commit=result.stdout.strip(),
                        )
                    except subprocess.CalledProcessError:
                        pass  # Fall through to recreate

        # Search existing worktrees by branch name
        for wt in self.list():
            if wt.branch == branch_name and wt.path.exists() and (wt.path / ".git").exists():
                return wt

        # Also check legacy path format for backward compat
        legacy_path = self._worktree_dir / f"run-{run_id}"
        if legacy_path.exists():
            legacy_git_marker = legacy_path / ".git"
            if not legacy_git_marker.exists():
                logger.warning(
                    f"Legacy worktree directory {legacy_path} exists but has no .git file"
                )
            else:
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=legacy_path,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    return WorktreeInfo(
                        path=legacy_path.resolve(),
                        branch=branch_name,
                        commit=result.stdout.strip(),
                    )
                except subprocess.CalledProcessError:
                    pass

        # Prune stale worktree entries so git doesn't block re-adding
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self._repo,
            capture_output=True,
        )

        self._worktree_dir.mkdir(parents=True, exist_ok=True)

        # Allocate a new short path
        new_path = self._worktree_dir / f"r{self._next_counter()}"

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
            cmd = ["git", "worktree", "add", str(new_path), branch_name]
        else:
            cmd = ["git", "worktree", "add", "-b", branch_name, str(new_path), base_branch]

        try:
            subprocess.run(cmd, cwd=self._repo, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e

        # Create an independent venv (see create() for rationale)
        if not (new_path / ".venv").exists():
            self._create_worktree_venv(new_path)

        # Write manifest before setup script so it can read it
        wt_number = self._worktree_number_from_path(new_path)
        self._write_manifest(new_path, run_id, branch_name, wt_number)
        self._write_sandbox_settings(new_path)

        self._run_worktree_setup(new_path)

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=new_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return WorktreeInfo(
            path=new_path.resolve(),
            branch=branch_name,
            commit=result.stdout.strip(),
        )

    def delete_path(self, worktree_path: str | Path, force: bool = False) -> None:
        """Remove a worktree by its filesystem path.

        Args:
            worktree_path: Absolute path to the worktree directory
            force: Force removal even with uncommitted changes

        Raises:
            WorktreeNotFoundError: If worktree doesn't exist
            GitCommandError: If git command fails
        """
        wt_path = Path(worktree_path)
        if not wt_path.exists():
            raise WorktreeNotFoundError("(path)", str(wt_path))

        cmd: list[str] = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(wt_path))

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

    def delete(self, run_id: str, force: bool = False) -> None:
        """
        Remove worktree for a run.

        Finds the worktree by branch name (``orchestrator/run-{run_id}``),
        falling back to the legacy ``run-{run_id}`` directory path.

        Args:
            run_id: Unique identifier for the run
            force: Force removal even with uncommitted changes

        Raises:
            WorktreeNotFoundError: If worktree doesn't exist
            GitCommandError: If git command fails
        """
        branch_name = f"orchestrator/run-{run_id}"

        # Search by branch name first (works with both old and new naming)
        for wt in self.list():
            if wt.branch == branch_name:
                self.delete_path(wt.path, force=force)
                return

        # Fallback: legacy path format
        legacy_path = self._worktree_dir / f"run-{run_id}"
        if legacy_path.exists():
            self.delete_path(legacy_path, force=force)
            return

        raise WorktreeNotFoundError(run_id, str(legacy_path))

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
                        self.delete_path(wt.path, force=True)
                        removed += 1
                    except WorktreeNotFoundError:
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

        # Guard against accidentally deleting all worktrees when run set is empty
        # (e.g., empty/in-memory DB during test or misconfigured restart)
        worktrees = self.list()
        orchestrator_worktrees = [
            wt for wt in worktrees if wt.branch.startswith("orchestrator/run-")
        ]
        if not all_run_ids and orchestrator_worktrees:
            logger.warning(
                "cleanup_expired called with empty run set but %d worktree(s) exist; "
                "refusing to remove (possible misconfiguration)",
                len(orchestrator_worktrees),
            )
            return 0

        cutoff = now - retention
        removed = 0

        for wt in worktrees:
            if not wt.branch.startswith("orchestrator/run-"):
                continue

            run_id = wt.branch.replace("orchestrator/run-", "")

            # Orphaned: run doesn't exist in DB at all
            if run_id not in all_run_ids:
                logger.info(f"Removing orphaned worktree for unknown run {run_id}")
                try:
                    self.delete_path(wt.path, force=True)
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
                    self.delete_path(wt.path, force=True)
                    removed += 1
                except WorktreeNotFoundError:
                    pass

        return removed
