from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from orchestrator.git import delete_snapshot_ref, restore, snapshot

GIT = "/usr/bin/git"


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"}
    }
    env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    return subprocess.run(
        [GIT, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-q", "-m", "initial")
    return repo


def _head(repo: Path) -> str:
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _cached_diff(repo: Path) -> str:
    return _run_git(repo, "diff", "--cached").stdout


def _porcelain(repo: Path) -> str:
    return _run_git(repo, "status", "--porcelain").stdout


def test_round_trip_tracked(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text("snapshot content\n", encoding="utf-8")

    result = snapshot(repo, "tracked snapshot")
    readme.write_text("changed after snapshot\n", encoding="utf-8")

    restore(repo, result.id)

    assert readme.read_text(encoding="utf-8") == "snapshot content\n"


def test_round_trip_untracked(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    note = repo / "notes" / "todo.txt"
    note.parent.mkdir()
    note.write_text("capture me\n", encoding="utf-8")

    result = snapshot(repo, "untracked snapshot")
    note.unlink()

    restore(repo, result.id)

    assert note.read_text(encoding="utf-8") == "capture me\n"


def test_porcelain_state_untouched(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("modified\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    before = _porcelain(repo)

    snapshot(repo, "status invariant")

    assert _porcelain(repo) == before


def test_head_untouched(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("modified\n", encoding="utf-8")
    before = _head(repo)

    snapshot(repo, "head invariant")

    assert _head(repo) == before


def test_index_untouched(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    _run_git(repo, "add", "staged.txt")
    before = _cached_diff(repo)

    snapshot(repo, "index invariant")

    assert _cached_diff(repo) == before


def test_identical_tree_dedup(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("same tree\n", encoding="utf-8")

    first = snapshot(repo, "first")
    second = snapshot(repo, "second")

    assert second.tree_sha == first.tree_sha
    assert second.commit_sha == first.commit_sha
    assert second.id == first.id
    refs = _run_git(
        repo,
        "for-each-ref",
        "--format=%(refname)",
        "refs/orchestrator/snapshots",
    ).stdout.splitlines()
    assert refs == [first.ref]


def test_restore_does_not_touch_head_or_index(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("snapshot version\n", encoding="utf-8")
    result = snapshot(repo, "restore invariant")
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    _run_git(repo, "add", "staged.txt")
    head_before = _head(repo)
    cached_before = _cached_diff(repo)
    (repo / "README.md").write_text("after snapshot\n", encoding="utf-8")

    restore(repo, result.id)

    assert _head(repo) == head_before
    assert _cached_diff(repo) == cached_before
    assert (repo / "README.md").read_text(encoding="utf-8") == "snapshot version\n"


def test_hooks_never_fire(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    sentinel = repo / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntouch hook-ran\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    (repo / "README.md").write_text("modified\n", encoding="utf-8")

    result = snapshot(repo, "hook invariant")

    assert result.ref.startswith("refs/orchestrator/snapshots/")
    assert not sentinel.exists()


def test_force_include_paths_are_literal_for_leading_dash_and_pathspec_magic(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".gitignore").write_text("--secret\n:(glob)*\n", encoding="utf-8")
    _run_git(repo, "add", ".gitignore")
    _run_git(repo, "commit", "-q", "-m", "ignore special names")
    (repo / "--secret").write_text("leading dash\n", encoding="utf-8")
    (repo / ":(glob)*").write_text("pathspec magic\n", encoding="utf-8")

    result = snapshot(
        repo,
        "literal force include",
        force_include_paths=["--secret", ":(glob)*"],
    )

    tree = _run_git(repo, "ls-tree", "-r", "--name-only", result.commit_sha).stdout.splitlines()
    assert "--secret" in tree
    assert ":(glob)*" in tree


def test_exclude_paths_are_literal_for_pathspec_magic(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ":(glob)*").write_text("remove only me\n", encoding="utf-8")
    (repo / "keep.txt").write_text("keep me\n", encoding="utf-8")

    result = snapshot(repo, "literal exclude", exclude_paths=[":(glob)*"])

    tree = _run_git(repo, "ls-tree", "-r", "--name-only", result.commit_sha).stdout.splitlines()
    assert ":(glob)*" not in tree
    assert "keep.txt" in tree


def test_delete_snapshot_ref_removes_ref_without_touching_worktree(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("snapshot version\n", encoding="utf-8")
    result = snapshot(repo, "delete ref")
    before = (repo / "README.md").read_text(encoding="utf-8")

    assert delete_snapshot_ref(repo, result.id) is True
    assert delete_snapshot_ref(repo, result.id) is False

    refs = _run_git(
        repo,
        "for-each-ref",
        "--format=%(refname)",
        "refs/orchestrator/snapshots",
    ).stdout.splitlines()
    assert result.ref not in refs
    assert (repo / "README.md").read_text(encoding="utf-8") == before


def test_pathspec_batches_splits_by_count() -> None:
    from orchestrator.git.snapshot import _MAX_PATHSPECS_PER_BATCH, _pathspec_batches

    specs = [f":(literal)f{i}" for i in range(_MAX_PATHSPECS_PER_BATCH * 2 + 5)]
    batches = _pathspec_batches(specs)
    assert len(batches) == 3
    assert sum(len(b) for b in batches) == len(specs)
    assert all(len(b) <= _MAX_PATHSPECS_PER_BATCH for b in batches)
    # Order preserved across the flattened batches.
    assert [s for b in batches for s in b] == specs


def test_pathspec_batches_splits_by_bytes() -> None:
    from orchestrator.git.snapshot import _MAX_PATHSPEC_BYTES_PER_BATCH, _pathspec_batches

    big = "x" * (_MAX_PATHSPEC_BYTES_PER_BATCH // 4)
    specs = [f":(literal){big}{i}" for i in range(10)]
    batches = _pathspec_batches(specs)
    assert len(batches) > 1
    for batch in batches:
        total = sum(len(s.encode()) + 1 for s in batch)
        # Each batch (beyond a single oversized spec) stays within budget.
        assert total <= _MAX_PATHSPEC_BYTES_PER_BATCH or len(batch) == 1


def test_pathspec_batches_empty() -> None:
    from orchestrator.git.snapshot import _pathspec_batches

    assert _pathspec_batches([]) == []


def test_snapshot_force_includes_many_paths_without_arg_overflow(tmp_path: Path) -> None:
    """A worktree with thousands of force-included ignored files must snapshot
    without overflowing git's argv (regression for the ARG_MAX/E2BIG boundary bug).
    """
    repo = _make_repo(tmp_path)
    # Ignore a cache dir and fill it with many files, mirroring an in-worktree .venv.
    (repo / ".gitignore").write_text("cache/\n", encoding="utf-8")
    _run_git(repo, "add", ".gitignore")
    _run_git(repo, "commit", "-q", "-m", "ignore cache")
    cache = repo / "cache"
    cache.mkdir()
    n = 5000
    force_paths = []
    for i in range(n):
        rel = f"cache/f{i}.txt"
        (repo / rel).write_text(str(i), encoding="utf-8")
        force_paths.append(rel)

    # Must not raise OSError/E2BIG and must capture the ignored files.
    result = snapshot(repo, "many force-included paths", force_include_paths=force_paths)
    listing = _run_git(repo, "ls-tree", "-r", "--name-only", result.commit_sha).stdout
    assert "cache/f0.txt" in listing
    assert f"cache/f{n - 1}.txt" in listing
