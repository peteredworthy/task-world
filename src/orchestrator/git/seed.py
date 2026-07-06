"""Seed-SHA resolution and staleness classification for run creation/worktree seeding.

When a graph run is created, we best-effort record the source branch's current
HEAD SHA as ``Run.intended_seed_sha``. Later, when the worktree is actually
seeded (potentially much later, e.g. after a queue delay or a paused run), we
compare that recorded SHA against the branch's *current* HEAD to detect the
"stale base" failure mode: the worktree gets seeded from a commit that is
*behind* what the run creator saw, silently discarding work the creator
expected to be included.

This module is intentionally dependency-free (subprocess only) so it can be
unit tested against throwaway temp git repos.
"""

from __future__ import annotations

import enum
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

GIT_SEED_TIMEOUT_SECONDS = 30


class SeedStaleness(str, enum.Enum):
    """Classification of an intended seed SHA against the actual branch head."""

    MATCH = "match"
    """intended_sha is None, or intended_sha == actual_sha."""

    ADVANCED = "advanced"
    """intended_sha is a strict ancestor of actual_sha: the branch moved forward
    since the run was created. Seeding from the newer head is fine."""

    STALE = "stale"
    """actual_sha is a strict ancestor of intended_sha: the branch/clone we are
    about to seed from is BEHIND what the run creator saw. This is the
    stale-base failure mode this module exists to catch."""

    UNRELATED = "unrelated"
    """SHAs are unrelated, or ancestry could not be determined (git errors,
    shallow history, missing objects, etc). Never block on this — it usually
    means infrastructure noise, not an actual problem."""


def resolve_branch_sha(repo_path: Path, branch: str) -> str | None:
    """Best-effort resolve the current HEAD SHA of ``branch`` in ``repo_path``.

    Returns ``None`` (never raises) if the repo doesn't exist, the branch is
    unknown, or git otherwise fails to resolve it.
    """
    if not repo_path.is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{branch}^{{commit}}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=GIT_SEED_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _is_ancestor(repo_path: Path, ancestor_sha: str, descendant_sha: str) -> bool | None:
    """Return True/False for ancestry, or None if it could not be determined."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=GIT_SEED_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    # returncode >= 128 (or other): one/both SHAs unknown to this repo, git
    # error, shallow clone missing history, etc. Indeterminate.
    return None


def classify_seed_staleness(
    repo_path: Path,
    intended_sha: str | None,
    actual_sha: str | None,
) -> SeedStaleness:
    """Classify ``intended_sha`` (recorded at run creation) against ``actual_sha``
    (the branch head at worktree-seed time), both resolved in ``repo_path``.

    Never raises: git failures / indeterminate ancestry classify as UNRELATED
    so callers can safely warn-and-proceed rather than brick a run on
    infrastructure noise.
    """
    if not intended_sha or not actual_sha or intended_sha == actual_sha:
        return SeedStaleness.MATCH

    advanced = _is_ancestor(repo_path, intended_sha, actual_sha)
    if advanced is True:
        return SeedStaleness.ADVANCED

    stale = _is_ancestor(repo_path, actual_sha, intended_sha)
    if stale is True:
        return SeedStaleness.STALE

    return SeedStaleness.UNRELATED
