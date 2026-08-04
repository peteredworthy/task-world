from __future__ import annotations

import os
import errno
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from orchestrator.git import (
    SnapshotPathLimitError,
    WorktreeError,
    delete_snapshot_ref,
    ensure_snapshot_ref,
    prepare_snapshot,
    publish_snapshot,
    restore,
    restore_paths,
    snapshot,
)
from orchestrator.git.snapshot import (
    SnapshotRef,
    match_snapshot_by_tree,
    parse_snapshot_refs,
)
from orchestrator.git.snapshot import _run_git as default_run_git

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


def test_restore_paths_restores_only_requested_paths_and_preserves_unrelated_dirt(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    (repo / "target.txt").write_text("baseline target\n", encoding="utf-8")
    (repo / "removed.txt").write_text("baseline removed\n", encoding="utf-8")
    snapshot_result = snapshot(repo, "selective baseline")
    (repo / "target.txt").write_text("runner target\n", encoding="utf-8")
    (repo / "removed.txt").unlink()
    (repo / "created.txt").write_text("runner creation\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("keep this dirt\n", encoding="utf-8")

    result = restore_paths(repo, snapshot_result.id, ["target.txt", "created.txt", "removed.txt"])

    assert result.requested_paths == ("created.txt", "removed.txt", "target.txt")
    assert result.restored_paths == ("removed.txt", "target.txt")
    assert result.removed_paths == ("created.txt",)
    assert (repo / "target.txt").read_text(encoding="utf-8") == "baseline target\n"
    assert (repo / "removed.txt").read_text(encoding="utf-8") == "baseline removed\n"
    assert not (repo / "created.txt").exists()
    assert (repo / "unrelated.txt").read_text(encoding="utf-8") == "keep this dirt\n"


def test_restore_paths_handles_ancestor_collapse_kind_transitions_and_symlinks(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    (repo / "tree").mkdir()
    (repo / "tree" / "file.txt").write_text("baseline child\n", encoding="utf-8")
    (repo / "link").symlink_to("tree/file.txt")
    script = repo / "script.sh"
    script.write_text("#!/bin/sh\necho baseline\n", encoding="utf-8")
    script.chmod(0o755)
    snapshot_result = snapshot(repo, "transition baseline")
    shutil.rmtree(repo / "tree")
    (repo / "tree").write_text("runner file replaces directory\n", encoding="utf-8")
    (repo / "link").unlink()
    (repo / "link").write_text("runner regular file\n", encoding="utf-8")
    script.chmod(0o644)

    result = restore_paths(
        repo,
        snapshot_result.id,
        ["tree", "tree/file.txt", "link", "script.sh"],
    )

    assert result.requested_paths == ("link", "script.sh", "tree", "tree/file.txt")
    assert result.restored_paths == ("link", "script.sh", "tree", "tree/file.txt")
    assert result.removed_paths == ()
    assert (repo / "tree" / "file.txt").read_text(encoding="utf-8") == "baseline child\n"
    assert (repo / "link").is_symlink()
    assert os.readlink(repo / "link") == "tree/file.txt"
    assert stat.S_IMODE(script.stat().st_mode) == 0o755


def test_restore_paths_is_idempotent_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "safe.txt").write_text("baseline\n", encoding="utf-8")
    snapshot_result = snapshot(repo, "retry baseline")
    (repo / "safe.txt").write_text("changed\n", encoding="utf-8")
    (repo / "created.txt").write_text("created\n", encoding="utf-8")

    first = restore_paths(repo, snapshot_result.id, ["safe.txt", "created.txt"])
    second = restore_paths(repo, snapshot_result.id, ["safe.txt", "created.txt"])

    assert first == second
    assert (repo / "safe.txt").read_text(encoding="utf-8") == "baseline\n"
    assert not (repo / "created.txt").exists()
    for unsafe in [
        "",
        ".",
        "../outside",
        "/absolute",
        ".git/config",
        ".GIT/config",
        "src/.git/config",
        "x//y",
    ]:
        with pytest.raises(WorktreeError, match="Invalid restore path"):
            restore_paths(repo, snapshot_result.id, [unsafe])


def test_restore_paths_treats_special_and_newline_names_as_literal_git_paths(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    special_paths = [":(glob)**", "bracket[abc].txt", "with space.txt", "line\nbreak.txt"]
    for name in special_paths:
        (repo / name).write_text(f"baseline {name}", encoding="utf-8")
    snapshot_result = snapshot(repo, "literal special names")
    for name in special_paths:
        (repo / name).write_text(f"changed {name}", encoding="utf-8")
    (repo / "unrelated.txt").write_text("unchanged dirt", encoding="utf-8")

    result = restore_paths(repo, snapshot_result.id, special_paths)

    assert result.restored_paths == tuple(sorted(special_paths))
    for name in special_paths:
        assert (repo / name).read_text(encoding="utf-8") == f"baseline {name}"
    assert (repo / "unrelated.txt").read_text(encoding="utf-8") == "unchanged dirt"


def test_restore_paths_retry_after_injected_partial_operation_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    snapshot_result = snapshot(repo, "partial-operation baseline")
    (repo / "baseline.txt").write_text("runner\n", encoding="utf-8")
    calls: list[str] = []

    def fail_after_remove(path: str) -> None:
        calls.append(path)
        raise WorktreeError("injected partial restore failure")

    with pytest.raises(WorktreeError, match="injected partial"):
        restore_paths(
            repo,
            snapshot_result.id,
            ["baseline.txt"],
            after_remove=fail_after_remove,
        )

    result = restore_paths(repo, snapshot_result.id, ["baseline.txt"])

    assert calls == ["baseline.txt"]
    assert result.restored_paths == ("baseline.txt",)
    assert (repo / "baseline.txt").read_text(encoding="utf-8") == "baseline\n"


def test_selective_restore_preserves_head_index_and_all_unrelated_dirt(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".gitignore").write_text(".ignored\n", encoding="utf-8")
    _run_git(repo, "add", ".gitignore")
    _run_git(repo, "commit", "-q", "-m", "ignore unrelated dirt")
    (repo / "target.txt").write_text("baseline\n", encoding="utf-8")
    (repo / "deleted.txt").write_text("baseline delete\n", encoding="utf-8")
    (repo / "link").symlink_to("target.txt")
    executable = repo / "run.sh"
    executable.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
    executable.chmod(0o755)
    baseline = snapshot(repo, "selective preservation baseline")

    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=repo, check=True)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    index_before = subprocess.run(
        ["git", "diff", "--cached", "--binary"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (repo / "README.md").write_text("unrelated tracked dirt\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked dirt\n", encoding="utf-8")
    ignored = repo / ".ignored"
    ignored.write_text("ignored dirt\n", encoding="utf-8")
    ignored_check = subprocess.run(
        ["git", "check-ignore", "--", ignored.name],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert ignored_check.stdout.strip() == ignored.name
    (repo / "target.txt").write_text("runner\n", encoding="utf-8")
    (repo / "deleted.txt").unlink()
    (repo / "created.txt").write_text("created\n", encoding="utf-8")
    (repo / "link").unlink()
    (repo / "link").write_text("wrong type\n", encoding="utf-8")
    executable.chmod(0o644)

    restore_paths(
        repo,
        baseline.id,
        ["target.txt", "deleted.txt", "created.txt", "link", "run.sh"],
    )

    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout
        == head_before
    )
    assert (
        subprocess.run(
            ["git", "diff", "--cached", "--binary"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == index_before
    )
    assert (repo / "README.md").read_text(encoding="utf-8") == "unrelated tracked dirt\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "untracked dirt\n"
    assert ignored.read_bytes() == b"ignored dirt\n"
    assert (repo / "target.txt").read_text(encoding="utf-8") == "baseline\n"
    assert (repo / "deleted.txt").read_text(encoding="utf-8") == "baseline delete\n"
    assert not (repo / "created.txt").exists()
    assert (repo / "link").is_symlink()
    assert stat.S_IMODE(executable.stat().st_mode) == 0o755


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


def test_managed_snapshot_cleanup_rejects_same_tree_with_changed_commit_and_is_exactly_idempotent(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    owned = snapshot(repo, "owned snapshot")
    changed_commit = _run_git(
        repo,
        "commit-tree",
        owned.tree_sha,
        "-p",
        _head(repo),
        "-m",
        "same tree, different commit",
    ).stdout.strip()
    _run_git(repo, "update-ref", owned.ref, changed_commit)

    with pytest.raises(WorktreeError, match="commit does not match"):
        delete_snapshot_ref(
            repo,
            owned.id,
            expected_ref=owned.ref,
            expected_tree_sha=owned.tree_sha,
            expected_commit_sha=owned.commit_sha,
        )
    assert _run_git(repo, "rev-parse", owned.ref).stdout.strip() == changed_commit

    assert (
        delete_snapshot_ref(
            repo,
            owned.id,
            expected_ref=owned.ref,
            expected_tree_sha=owned.tree_sha,
            expected_commit_sha=changed_commit,
        )
        is True
    )
    assert delete_snapshot_ref(repo, owned.id, expected_ref=owned.ref) is False
    assert delete_snapshot_ref(repo, "missing-snapshot") is False


def test_managed_snapshot_cleanup_rejects_a_changed_ref_name(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    owned = snapshot(repo, "owned snapshot")

    with pytest.raises(WorktreeError, match="ref does not match"):
        delete_snapshot_ref(
            repo,
            owned.id,
            expected_ref="refs/orchestrator/snapshots/not-owned",
            expected_tree_sha=owned.tree_sha,
            expected_commit_sha=owned.commit_sha,
        )


def test_ensure_snapshot_ref_recreates_only_the_persisted_owned_commit(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    owned = snapshot(repo, "owned snapshot")
    _run_git(repo, "update-ref", "-d", owned.ref)

    recovered = ensure_snapshot_ref(
        repo,
        owned.id,
        expected_ref=owned.ref,
        expected_commit_sha=owned.commit_sha,
        expected_tree_sha=owned.tree_sha,
    )

    assert recovered == owned
    assert _run_git(repo, "rev-parse", owned.ref).stdout.strip() == owned.commit_sha


def test_prepared_snapshot_crash_before_durable_ownership_leaves_only_dangling_object(
    tmp_path: Path,
) -> None:
    """Preparation must not create a semantic ref before its owner is durable."""
    repo = _make_repo(tmp_path)
    prepared = prepare_snapshot(repo, "unowned boundary", snapshot_id="a" * 32)

    assert _run_git(repo, "cat-file", "-e", f"{prepared.commit_sha}^{{commit}}")
    assert (
        _run_git(
            repo,
            "for-each-ref",
            "--format=%(refname)",
            "refs/orchestrator/snapshots",
        ).stdout.splitlines()
        == []
    )


def test_prepare_snapshot_untracked_limit_fails_before_commit_or_ref(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    for index in range(3):
        (repo / f"untracked-{index}").write_text("x", encoding="utf-8")

    with pytest.raises(SnapshotPathLimitError) as raised:
        prepare_snapshot(
            repo,
            "bounded",
            snapshot_id="c" * 32,
            max_untracked_items=2,
            max_untracked_bytes=1024,
        )

    assert (raised.value.metric, raised.value.limit, raised.value.observed) == ("items", 2, 3)
    assert _run_git(repo, "for-each-ref", "refs/orchestrator/snapshots").stdout == ""
    assert _run_git(repo, "status", "--porcelain").stdout.splitlines() == [
        "?? untracked-0",
        "?? untracked-1",
        "?? untracked-2",
    ]


def test_prepare_snapshot_untracked_limit_exact_item_and_byte_edges(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "aa").write_text("x", encoding="utf-8")
    (repo / "bb").write_text("x", encoding="utf-8")
    prepared = prepare_snapshot(
        repo,
        "edge",
        snapshot_id="d" * 32,
        max_untracked_items=2,
        max_untracked_bytes=4,
    )
    assert prepared.tree_sha
    (repo / "overlong").write_text("x", encoding="utf-8")
    with pytest.raises(SnapshotPathLimitError) as raised:
        prepare_snapshot(
            repo,
            "byte-overflow",
            snapshot_id="e" * 32,
            max_untracked_items=3,
            max_untracked_bytes=4,
        )
    assert raised.value.metric == "bytes"


def test_prepare_snapshot_round_trips_surrogateescaped_untracked_path(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    raw_path = os.fsencode(repo) + b"/invalid-\xff-name"
    try:
        descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o644)
    except OSError as exc:
        if exc.errno == errno.EILSEQ:
            pytest.skip("filesystem rejects invalid UTF-8 filenames")
        raise
    os.close(descriptor)

    prepared = prepare_snapshot(
        repo,
        "surrogate path",
        snapshot_id="f" * 32,
        max_untracked_items=1,
        max_untracked_bytes=len(b"invalid-\xff-name"),
    )

    assert prepared.tree_sha


def test_delayed_snapshot_publish_cas_conflict_preserves_replaced_ref(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    prepared = prepare_snapshot(repo, "owned boundary", snapshot_id="b" * 32)
    replacement = _run_git(
        repo, "commit-tree", prepared.tree_sha, "-m", "competing owner"
    ).stdout.strip()
    _run_git(repo, "update-ref", prepared.ref, replacement)

    with pytest.raises(WorktreeError, match="different commit"):
        publish_snapshot(repo, prepared)

    assert _run_git(repo, "rev-parse", prepared.ref).stdout.strip() == replacement


def test_ensure_snapshot_ref_rejects_changed_owned_ref(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    owned = snapshot(repo, "owned snapshot")
    changed_commit = _run_git(
        repo, "commit-tree", owned.tree_sha, "-p", _head(repo), "-m", "different commit"
    ).stdout.strip()
    _run_git(repo, "update-ref", owned.ref, changed_commit)

    with pytest.raises(WorktreeError, match="different commit"):
        ensure_snapshot_ref(
            repo,
            owned.id,
            expected_ref=owned.ref,
            expected_commit_sha=owned.commit_sha,
            expected_tree_sha=owned.tree_sha,
        )


def test_parse_snapshot_refs_reads_tree_from_the_listing() -> None:
    parsed = parse_snapshot_refs(
        "refs/orchestrator/snapshots/aa commit-aa tree-aa\n"
        "refs/orchestrator/snapshots/bb commit-bb tree-bb\n"
    )

    assert parsed == [
        SnapshotRef("refs/orchestrator/snapshots/aa", "commit-aa", "tree-aa"),
        SnapshotRef("refs/orchestrator/snapshots/bb", "commit-bb", "tree-bb"),
    ]


def test_parse_snapshot_refs_tolerates_missing_tree_and_blank_lines() -> None:
    # A ref that is not a commit reports no %(tree); it must survive parsing so
    # the caller can resolve it individually rather than be silently dropped.
    parsed = parse_snapshot_refs(
        "refs/orchestrator/snapshots/aa commit-aa\n\nrefs/orchestrator/snapshots/bb commit-bb t-bb\n"
    )

    assert parsed == [
        SnapshotRef("refs/orchestrator/snapshots/aa", "commit-aa", ""),
        SnapshotRef("refs/orchestrator/snapshots/bb", "commit-bb", "t-bb"),
    ]


def test_match_snapshot_by_tree_settles_from_the_listing_alone() -> None:
    refs = [
        SnapshotRef("refs/orchestrator/snapshots/aa", "commit-aa", "tree-aa"),
        SnapshotRef("refs/orchestrator/snapshots/bb", "commit-bb", "tree-bb"),
    ]

    match, unresolved = match_snapshot_by_tree(refs, "tree-bb")

    assert match == refs[1]
    # Nothing left to resolve: no per-ref git command is warranted.
    assert unresolved == []


def test_match_snapshot_by_tree_reports_only_refs_without_a_tree() -> None:
    refs = [
        SnapshotRef("refs/orchestrator/snapshots/aa", "commit-aa", ""),
        SnapshotRef("refs/orchestrator/snapshots/bb", "commit-bb", "tree-bb"),
    ]

    match, unresolved = match_snapshot_by_tree(refs, "tree-zz")

    assert match is None
    assert unresolved == [refs[0]]


def test_dedup_lookup_does_not_scale_with_snapshot_count(tmp_path: Path) -> None:
    """Each capture must cost a constant number of git commands.

    Resolving each existing snapshot's tree with its own `git show` made one
    capture cost O(snapshots) processes, so a run's captures cost O(snapshots^2)
    overall. The injected runner records real git calls without patching.
    """
    repo = _make_repo(tmp_path)
    invocations: list[list[str]] = []

    def recording_git(
        cwd: Path,
        args: list[str],
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        invocations.append(args)
        return default_run_git(cwd, args, env)

    per_capture: list[int] = []
    for index in range(4):
        (repo / "README.md").write_text(f"revision {index}\n", encoding="utf-8")
        invocations.clear()
        snapshot(repo, f"capture {index}", run_git=recording_git)
        per_capture.append(len(invocations))

    assert per_capture == [per_capture[0]] * 4, per_capture
    assert not [args for args in invocations if args[:2] == ["show", "-s"]]


def test_snapshot_uses_the_injected_runner_for_every_git_call(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    seen: list[list[str]] = []

    def recording_git(
        cwd: Path,
        args: list[str],
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return default_run_git(cwd, args, env)

    result = snapshot(repo, "injected", run_git=recording_git)

    assert result.tree_sha
    # No git call bypasses the seam, so a caller can observe or substitute all of them.
    assert [args[0] for args in seen] == [
        "add",
        "write-tree",
        "for-each-ref",
        "commit-tree",
        "update-ref",
    ]


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


@pytest.mark.slow
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
