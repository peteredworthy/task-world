"""Shared helpers for subprocess environment wiring.

The subprocess runners use this module to enforce a consistent PATH-first
``git-wrapper.sh`` and to export run-scoped git validation variables.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path


GIT_RUN_WORKTREE_ENV = "ORCHESTRATOR_RUN_WORKTREE"
GIT_RUN_BRANCH_ENV = "ORCHESTRATOR_RUN_BRANCH"
GIT_WRAPPER_NAME = "git-wrapper.sh"
_GIT_WRAPPER_RELATIVE = Path("scripts") / "worktree" / GIT_WRAPPER_NAME
_DEFAULT_GIT_AUTHOR_NAME = "Orchestrator Agent"
_DEFAULT_GIT_AUTHOR_EMAIL = "orchestrator@local"
_WRAPPER_CACHE_DIR = "orchestrator-git-wrapper-bin"


def _ensure_git_wrapper_shim() -> str:
    """Create a stable `git` shim that points to ``git-wrapper.sh``.

    The repository keeps the wrapper under a descriptive filename, so this helper
    creates/refreshes a ``git`` executable in a temp cache directory that shells
    can resolve directly from PATH.
    """
    wrapper_path = _find_git_wrapper()
    cache_dir = Path(tempfile.gettempdir()) / _WRAPPER_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    git_shim = cache_dir / "git"

    try:
        if git_shim.exists():
            try:
                if git_shim.is_symlink():
                    if git_shim.resolve() == wrapper_path.resolve():
                        return str(cache_dir)
                # If an unrelated symlink/file exists, replace it below.
                git_shim.unlink()
            except FileNotFoundError:
                pass
        try:
            os.symlink(wrapper_path, git_shim)
        except (OSError, NotImplementedError):
            # macOS and sandboxed environments may disallow symlinks in
            # some paths; fall back to copy, which is sufficient for shim use.
            shutil.copy2(wrapper_path, git_shim)
        os.chmod(git_shim, 0o755)
    except OSError:
        # If the shim cannot be created, return the wrapper directory directly.
        # The caller may still be able to run with absolute-path fallback.
        return str(wrapper_path.parent)

    return str(cache_dir)


def _find_git_wrapper() -> Path:
    """Locate the repo-level git wrapper script.

    Walk upwards from this file and return the first ancestor that contains
    ``scripts/worktree/git-wrapper.sh``. Resilient to worktrees and tests run
    from subdirectories.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / _GIT_WRAPPER_RELATIVE
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("git wrapper script not found")


def _prepend_to_path(env: dict[str, str], wrapper_dir: str) -> None:
    """Prepend ``wrapper_dir`` to PATH without duplicating entries."""
    path_value = env.get("PATH", "")
    path_sep = os.pathsep
    path_entries = [entry for entry in path_value.split(path_sep) if entry]
    if wrapper_dir in path_entries:
        path_entries = [entry for entry in path_entries if entry != wrapper_dir]
    env["PATH"] = path_sep.join([wrapper_dir, *path_entries])


def _isolate_git_config(env: dict[str, str]) -> None:
    """Keep agent git calls from reading host-level config files."""
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.setdefault("GIT_AUTHOR_NAME", _DEFAULT_GIT_AUTHOR_NAME)
    env.setdefault("GIT_AUTHOR_EMAIL", _DEFAULT_GIT_AUTHOR_EMAIL)
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])


def build_agent_subprocess_env(
    base_env: Mapping[str, str] | None = None,
    *,
    run_worktree: str | None = None,
    expected_run_branch: str | None = None,
) -> dict[str, str]:
    """Build an execution environment for agent subprocesses.

    Args:
        base_env: Base environment; defaults to ``os.environ``.
        run_worktree: Absolute path to the run worktree, if any.
        expected_run_branch: Expected git branch name for wrapper validation.

    Returns:
        A copy of ``base_env`` with git wrapper PATH precedence and run-scope
        environment variables for the v1 wrapper checks.
    """
    env = dict(base_env or os.environ)

    try:
        wrapper_dir = _ensure_git_wrapper_shim()
        _prepend_to_path(env, wrapper_dir)
    except FileNotFoundError:
        # If the wrapper disappears, continue with base environment; this keeps
        # tests that run outside a git checkout (or old installations) from
        # hard-failing. The runner still gets the expected PATH behavior when
        # the wrapper is present.
        pass

    _isolate_git_config(env)

    if run_worktree is not None:
        env[GIT_RUN_WORKTREE_ENV] = run_worktree

    if expected_run_branch is not None:
        env[GIT_RUN_BRANCH_ENV] = expected_run_branch

    return env
