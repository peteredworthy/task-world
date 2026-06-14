"""Detect run-worktree changes leaking into the repo's main worktree.

A run executes in a linked git worktree (``worktrees/rNN``). If an agent escapes
that worktree — or a tool resolves "the repo root" to the shared ``.git``'s main
worktree — it can write into the developer's live checkout. That contamination
has historically only surfaced days later via unexpected failing tests. These
helpers let the run driver snapshot the main worktree's dirty set before/after a
run and flag any new paths immediately.

This lives in ``git/`` (not ``graph/``), so subprocess use is allowed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_main_worktree(run_worktree: Path | str) -> Path | None:
    """Return the repo's primary (main) worktree for a linked run worktree.

    Derived from the shared ``.git`` common dir's parent. Returns ``None`` when it
    cannot be determined (not a git worktree, git missing, etc.).
    """
    run_worktree = Path(run_worktree)
    try:
        proc = subprocess.run(
            ["git", "-C", str(run_worktree), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = (run_worktree / common).resolve()
    return common.parent if common.name == ".git" else None


def dirty_paths(worktree: Path | str) -> set[str]:
    """Return the set of dirty (modified/added/untracked) paths in a worktree.

    Empty set on any error so a guard never breaks the run it observes.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    # Porcelain v1 lines are ``XY <path>``; the path starts at column 3.
    return {line[3:].strip() for line in proc.stdout.splitlines() if line.strip()}


def find_leaked_paths(before: set[str], after: set[str]) -> set[str]:
    """Paths that became dirty in the main worktree during a run (contamination).

    Pure set difference so it is trivially testable: anything dirty after the run
    that was not dirty before is attributable to the run.
    """
    return after - before
