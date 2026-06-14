"""Worktree-isolation contamination detection (git/contamination.py).

Uses a real temporary git repo + linked worktree — no mocks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.git import dirty_paths, find_leaked_paths, resolve_main_worktree


def test_find_leaked_paths_is_new_dirty_only() -> None:
    before = {"a.txt", "b.txt"}
    after = {"a.txt", "b.txt", "leaked.py"}
    assert find_leaked_paths(before, after) == {"leaked.py"}
    # already-dirty paths are not attributed to the run
    assert find_leaked_paths(before, before) == set()
    assert find_leaked_paths({"x"}, {"x", "y", "z"}) == {"y", "z"}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def test_dirty_paths_and_resolve_main_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")

    # A clean main worktree has no dirty paths.
    assert dirty_paths(repo) == set()

    # Create a linked worktree (the run worktree).
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", str(wt), "-b", "run")

    # From the linked worktree, the main worktree resolves back to the repo.
    resolved = resolve_main_worktree(wt)
    assert resolved is not None
    assert resolved.resolve() == repo.resolve()

    # A write into the MAIN worktree (simulated leak) is detected.
    (repo / "leaked.py").write_text("oops\n")
    assert "leaked.py" in dirty_paths(repo)

    # The end-to-end guard: leak shows up as a new dirty path.
    before = set()  # repo was clean before the run
    after = dirty_paths(repo)
    assert find_leaked_paths(before, after) == {"leaked.py"}


def test_helpers_never_raise_on_non_git_path(tmp_path: Path) -> None:
    missing = tmp_path / "not-a-repo"
    assert resolve_main_worktree(missing) is None
    assert dirty_paths(missing) == set()
