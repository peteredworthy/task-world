from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from orchestrator.git import restore, snapshot

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
