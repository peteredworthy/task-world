"""Unit tests for seed-SHA resolution and staleness classification.

Covers the P0 fix for stale-base run creation: `intended_seed_sha` recorded at
run-creation time is compared against the branch head at worktree-seed time.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orchestrator.git.seed import SeedStaleness, classify_seed_staleness, resolve_branch_sha

from tests.unit.git_helpers import _commit_file, _git


@pytest.fixture
def git_repo(tmp_path: Path, _unit_base_repo: Path) -> Path:
    """Copy the session-scoped base repo for this test (fast: no git init)."""
    return Path(shutil.copytree(str(_unit_base_repo), str(tmp_path / "repo")))


class TestResolveBranchSha:
    def test_resolves_known_branch(self, git_repo: Path) -> None:
        expected = _git(["rev-parse", "main"], cwd=git_repo)
        assert resolve_branch_sha(git_repo, "main") == expected

    def test_unknown_branch_returns_none(self, git_repo: Path) -> None:
        assert resolve_branch_sha(git_repo, "does-not-exist") is None

    def test_missing_repo_returns_none(self, tmp_path: Path) -> None:
        assert resolve_branch_sha(tmp_path / "no-such-repo", "main") is None


class TestClassifySeedStaleness:
    def test_none_intended_is_match(self, git_repo: Path) -> None:
        head = _git(["rev-parse", "main"], cwd=git_repo)
        assert classify_seed_staleness(git_repo, None, head) == SeedStaleness.MATCH

    def test_same_sha_is_match(self, git_repo: Path) -> None:
        head = _git(["rev-parse", "main"], cwd=git_repo)
        assert classify_seed_staleness(git_repo, head, head) == SeedStaleness.MATCH

    def test_branch_advanced_since_creation(self, git_repo: Path) -> None:
        """intended is a strict ancestor of actual: branch moved forward."""
        intended = _git(["rev-parse", "main"], cwd=git_repo)
        actual = _commit_file(git_repo, "feature.py", "# feature", "Add feature")
        assert intended != actual
        assert classify_seed_staleness(git_repo, intended, actual) == SeedStaleness.ADVANCED

    def test_stale_clone_is_behind_intended(self, git_repo: Path) -> None:
        """actual is a strict ancestor of intended: the stale-base failure mode."""
        stale_actual = _git(["rev-parse", "main"], cwd=git_repo)
        intended = _commit_file(git_repo, "feature.py", "# feature", "Add feature")
        assert intended != stale_actual
        assert classify_seed_staleness(git_repo, intended, stale_actual) == SeedStaleness.STALE

    def test_unrelated_histories_are_indeterminate(self, git_repo: Path) -> None:
        intended = _commit_file(git_repo, "on-main.py", "# on main", "On main")
        _git(["checkout", "--orphan", "orphan-branch"], cwd=git_repo)
        _git(["reset", "--hard"], cwd=git_repo)
        actual = _commit_file(git_repo, "orphan.py", "# orphan", "Orphan commit")
        assert classify_seed_staleness(git_repo, intended, actual) == SeedStaleness.UNRELATED

    def test_unknown_shas_are_indeterminate_not_fatal(self, git_repo: Path) -> None:
        """Garbage SHAs (e.g. from a repo error) must never raise."""
        result = classify_seed_staleness(git_repo, "0" * 40, "1" * 40)
        assert result == SeedStaleness.UNRELATED
