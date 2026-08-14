from __future__ import annotations

import subprocess
import os
from pathlib import Path
from typing import Any, cast

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    FileStateDeclaration,
    FileStatePath,
    FileStatePathKind,
    FileStatePolicy,
    FileStateScanBudget,
    WorktreeStatus,
    classify_file_state,
    declared_tool_cache_roots,
    default_file_state_policy,
    project_residue_report,
)
from orchestrator.graph_runtime import (
    CompromisedFileStateError,
    CacheScanBudgetExceededError,
    capture_file_state_boundary,
    capture_worktree_file_state_baseline,
    collect_worktree_status,
)
from orchestrator.graph_runtime.dispatch import _capture_runner_boundary
from orchestrator.git import publish_snapshot, restore_baseline_worktree, restore_paths


def _path(
    path: str,
    kind: str,
    *,
    entropy: float | None = None,
    content_hash: str | None = None,
    repo_escape: bool = False,
    symlink_escape: bool = False,
) -> FileStatePath:
    return FileStatePath(
        path=path,
        kind=cast(FileStatePathKind, kind),
        status="M" if kind == "tracked" else None,
        size_bytes=128,
        entropy=entropy,
        content_hash=content_hash,
        repo_escape=repo_escape,
        symlink_escape=symlink_escape,
    )


def _classifications(status: WorktreeStatus, policy: FileStatePolicy | None = None) -> list[str]:
    result = classify_file_state(status, policy or FileStatePolicy())
    return [entry.classification for entry in result.paths]


def test_tracked_changes_are_captured_as_tracked_change() -> None:
    result = classify_file_state(
        WorktreeStatus(tracked_modified=(_path("src/app.py", "tracked"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "tracked_change"
    assert result.paths[0].matched_rule == "git_status"


def test_learned_patterns_apply_only_to_untracked_or_ignored_sources() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration(
                "*.py",
                "tool_cache",
                rule="pattern_library:*.py",
                source_kinds=("untracked", "ignored"),
            ),
        )
    )

    result = classify_file_state(
        WorktreeStatus(
            tracked_modified=(_path("foo.py", "tracked"),),
            untracked=(_path("bar.py", "untracked"),),
        ),
        policy,
    )

    by_path = {entry.path: entry for entry in result.paths}
    assert by_path["foo.py"].classification == "tracked_change"
    assert by_path["foo.py"].matched_rule == "git_status"
    assert by_path["bar.py"].classification == "tool_cache"
    assert by_path["bar.py"].matched_rule == "pattern_library:*.py"


def test_untracked_residue_is_captured_and_needs_gatekeeper() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("notes/tmp.txt", "untracked"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "unknown_untracked"
    assert result.paths[0].needs_gatekeeper is True


def test_known_ignored_tool_cache_row() -> None:
    assert _classifications(
        WorktreeStatus(ignored=(_path("__pycache__/app.cpython-312.pyc", "ignored"),))
    ) == ["tool_cache"]


def test_declared_build_output_row() -> None:
    policy = FileStatePolicy(
        declarations=(FileStateDeclaration("dist/**", "build_output", rule="routine:build-output"),)
    )

    result = classify_file_state(
        WorktreeStatus(ignored=(_path("dist/app.js", "ignored"),)),
        policy,
    )

    assert result.paths[0].classification == "build_output"
    assert result.paths[0].matched_rule == "routine:build-output"


def test_declared_test_artifact_row() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration("reports/**", "test_artifact", rule="verifier:test-report"),
        )
    )

    assert _classifications(
        WorktreeStatus(ignored=(_path("reports/junit.xml", "ignored"),)),
        policy,
    ) == ["test_artifact"]


def test_external_artifact_row_rejects_repo_escape() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("../outside.bin", "untracked", repo_escape=True),)),
        FileStatePolicy(),
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].classification == "external_artifact"
    assert result.rejected_paths[0].reason == "repo_escape"


def test_declared_external_artifact_row_carries_manifest() -> None:
    policy = FileStatePolicy(
        declarations=(
            FileStateDeclaration(
                "../artifacts/report.bin",
                "external_artifact",
                rule="routine:external-report",
                origin="worker_output",
                retention="retain_30_days",
            ),
        )
    )

    result = classify_file_state(
        WorktreeStatus(
            untracked=(
                _path(
                    "../artifacts/report.bin",
                    "untracked",
                    content_hash="sha256:abc123",
                    repo_escape=True,
                ),
            )
        ),
        policy,
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].reason == "repo_escape"


def test_unknown_ignored_row_is_captured_with_gatekeeper_flag() -> None:
    result = classify_file_state(
        WorktreeStatus(ignored=(_path("scratch/local.bin", "ignored"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "unknown_ignored"
    assert result.paths[0].needs_gatekeeper is True


def test_secret_like_name_and_high_entropy_rejects() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("fake_key.pem", "untracked", entropy=7.2),)),
        FileStatePolicy(),
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].classification == "secret"
    assert result.rejected_paths[0].reason == "secret"


def test_symlink_escape_rejects() -> None:
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("linked", "untracked", symlink_escape=True),)),
        FileStatePolicy(),
    )

    assert result.verdict == "rejected"
    assert result.rejected_paths[0].reason == "repo_escape"


def test_classification_is_deterministic_and_stably_ordered() -> None:
    status = WorktreeStatus(
        tracked_modified=(_path("b.py", "tracked"),),
        untracked=(_path("a.tmp", "untracked"),),
        ignored=(_path(".pytest_cache/v/cache", "ignored"),),
    )

    first = classify_file_state(status, FileStatePolicy())
    second = classify_file_state(status, FileStatePolicy())

    assert first == second
    assert [entry.path for entry in first.paths] == [
        ".pytest_cache/v/cache",
        "a.tmp",
        "b.py",
    ]


def test_project_residue_report_from_accepted_file_state_events() -> None:
    events = [
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "residue": [
                    {
                        "path": "tmp.out",
                        "source": "untracked",
                        "classification": "unknown_untracked",
                        "matched_rule": "unmatched_untracked",
                        "needs_gatekeeper": True,
                    }
                ],
            },
        )
    ]

    assert project_residue_report(events) == {
        "tmp.out": [
            {
                "path": "tmp.out",
                "classification": "unknown_untracked",
                "matched_rule": "unmatched_untracked",
                "needs_gatekeeper": True,
                "run_id": "run-1",
                "node_id": "worker-1",
                "record_id": "file-state-1",
                "source": "untracked",
            }
        ]
    }


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_type,
        run_id="run-1",
        position=1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def test_tool_cache_does_not_hide_secret_or_escape_metadata() -> None:
    """A cache-like parent never suppresses a security-relevant classification."""
    status = WorktreeStatus(
        ignored=(
            _path(".venv/lib/python3.12/site-packages/authlib/oauth2/credentials.py", "ignored"),
            _path(".venv/lib/python3.12/site-packages/certifi/cacert.pem", "ignored", entropy=7.5),
            _path(".venv/bin/python", "ignored", repo_escape=True, symlink_escape=True),
            _path(".claude/settings.local.json", "ignored"),
            _path(".worktree-manifest.json", "ignored"),
        )
    )
    result = classify_file_state(status, FileStatePolicy())

    assert result.verdict == "rejected"
    assert {entry.path for entry in result.rejected_paths} == {
        ".venv/lib/python3.12/site-packages/authlib/oauth2/credentials.py",
        ".venv/lib/python3.12/site-packages/certifi/cacert.pem",
        ".venv/bin/python",
    }
    by_path = {entry.path: entry for entry in result.paths}
    assert (
        by_path[".venv/lib/python3.12/site-packages/certifi/cacert.pem"].classification == "secret"
    )
    assert by_path[".venv/bin/python"].classification == "external_artifact"
    assert by_path[".claude/settings.local.json"].classification == "tool_cache"
    assert by_path[".worktree-manifest.json"].classification == "tool_cache"


def test_worker_introduced_secret_outside_tool_cache_still_rejected() -> None:
    """The tool-cache precedence must NOT weaken detection of a genuine
    worker-introduced secret that lands outside a tool-cache dir."""
    result = classify_file_state(
        WorktreeStatus(untracked=(_path("config/id_rsa", "untracked", entropy=7.1),)),
        FileStatePolicy(),
    )
    assert result.verdict == "rejected"
    assert result.rejected_paths[0].classification == "secret"


def test_hypothesis_cache_is_tool_cache_residue() -> None:
    result = classify_file_state(
        WorktreeStatus(ignored=(_path(".hypothesis/constants/abc", "ignored"),)),
        FileStatePolicy(),
    )

    assert result.verdict == "captured"
    assert result.paths[0].classification == "tool_cache"


def test_file_state_baseline_excludes_unchanged_residue_but_keeps_execution_delta(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".hypothesis/\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    cache_file = repo / ".hypothesis" / "constants" / "abc"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache", encoding="utf-8")

    baseline = capture_worktree_file_state_baseline(repo)
    (repo / "tests").mkdir()
    helper = repo / "tests" / "feature_cases.py"
    helper.write_text("case\n", encoding="utf-8")

    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="run-1",
        node_id="worker-1",
        execution_id="execution-1",
        base_snapshot_id="base-1",
        baseline=baseline,
    )

    assert [entry.path for entry in boundary.classification.paths] == ["tests/feature_cases.py"]
    assert boundary.classification.residue[0].path == "tests/feature_cases.py"


def test_file_state_baseline_reports_changed_and_removed_preexisting_dirt(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    old_untracked = repo / "old helper.py"
    old_untracked.write_text("old\n", encoding="utf-8")
    ignored = repo / "scratch" / "old.log"
    ignored.parent.mkdir()
    ignored.write_text("ignored\n", encoding="utf-8")
    baseline = capture_worktree_file_state_baseline(repo)

    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    old_untracked.rename(repo / "new helper.py")
    ignored.unlink()

    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="run-1",
        node_id="worker-1",
        execution_id="execution-1",
        base_snapshot_id="base-1",
        baseline=baseline,
    )
    by_path = {entry.path: entry for entry in boundary.classification.paths}

    assert by_path["README.md"].status == "restored"
    assert by_path["old helper.py"].status == "deleted"
    assert by_path["new helper.py"].source == "untracked"
    assert by_path["scratch/old.log"].status == "deleted"


def test_collect_worktree_status_parses_rename_with_spaces(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    original = repo / "before name.txt"
    original.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", original.name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add source"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "mv", original.name, "after name.txt"], cwd=repo, check=True)

    status = collect_worktree_status(repo)

    assert {(entry.path, entry.status) for entry in status.tracked_modified} == {
        ("after name.txt", "R."),
        ("before name.txt", "renamed_from"),
    }


def test_policy_roots_snapshot_discards_preexisting_and_created_caches(tmp_path: Path) -> None:
    """Baseline snapshots omit disposable cache roots; recovery removes them."""
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text(
        ".hypothesis/\nnode_modules/\n.pytest_cache/\n.venv/\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "cache ignores"], cwd=repo, check=True, capture_output=True
    )
    hypothesis = repo / ".hypothesis" / "constants" / "example"
    modules = repo / "packages" / "node_modules" / "tool" / "bin"
    hypothesis.parent.mkdir(parents=True)
    modules.parent.mkdir(parents=True)
    hypothesis.write_text("before", encoding="utf-8")
    modules.write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    os.chmod(modules, 0o755)
    large_cache = repo / ".venv" / "lib" / "cache.bin"
    large_cache.parent.mkdir(parents=True)
    large_cache.write_bytes(b"x" * (2 * 1024 * 1024))

    policy = FileStatePolicy(scan_budget=FileStateScanBudget(max_entries=10, max_bytes=1))
    baseline = _capture_runner_boundary(repo, policy, "baseline", snapshot_id="cache-baseline")
    publish_snapshot(repo, baseline.snapshot)
    names = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", baseline.snapshot.commit_sha],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert not any(
        name.startswith((".hypothesis/", ".venv/", "packages/node_modules/")) for name in names
    )
    assert baseline.cache_roots == [".hypothesis", ".venv", "packages/node_modules"]
    hypothesis.write_text("changed", encoding="utf-8")
    modules.unlink()
    created = repo / ".pytest_cache" / "v" / "new"
    created.parent.mkdir(parents=True)
    created.write_text("new", encoding="utf-8")
    after = _capture_runner_boundary(repo, policy, "recovery", snapshot_id="cache-after")
    roots = sorted(set((*baseline.cache_roots, *after.cache_roots)))
    restored = restore_paths(
        repo, baseline.snapshot.id, roots, expected_tree_sha=baseline.snapshot.tree_sha
    )

    assert restored.restored_paths == ()
    assert restored.removed_paths == (
        ".hypothesis",
        ".pytest_cache",
        ".venv",
        "packages/node_modules",
    )
    assert not hypothesis.exists()
    assert not modules.exists()
    assert not created.exists()


def test_rejected_preexisting_secret_does_not_prepare_or_publish_baseline_snapshot(
    tmp_path: Path,
) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".env").write_bytes(bytes(range(256)))

    with pytest.raises(CompromisedFileStateError, match="rejected"):
        _capture_runner_boundary(repo, FileStatePolicy(), "baseline", snapshot_id="secret-baseline")

    refs = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/orchestrator/snapshots"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert refs == ""


def test_unignored_cache_root_is_excluded_from_baseline_and_full_restore(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ignore venv"], cwd=repo, check=True, capture_output=True
    )
    approved = repo / "approved-untracked.txt"
    approved.write_text("preserve\n", encoding="utf-8")
    cache_blob = repo / "node_modules" / "dependency" / "large.bin"
    cache_blob.parent.mkdir(parents=True)
    cache_blob.write_bytes(b"x" * (2 * 1024 * 1024))
    ignored_blob = repo / ".venv" / "cache.bin"
    ignored_blob.parent.mkdir()
    ignored_blob.write_bytes(b"y" * 1024)
    policy = FileStatePolicy(scan_budget=FileStateScanBudget(max_entries=10, max_bytes=1))

    baseline = _capture_runner_boundary(repo, policy, "baseline", snapshot_id="unignored-cache")
    publish_snapshot(repo, baseline.snapshot)
    names = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", baseline.snapshot.commit_sha],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "approved-untracked.txt" in names
    assert not any(name.startswith(("node_modules/", ".venv/")) for name in names)
    cache_oid = subprocess.run(
        ["git", "hash-object", str(cache_blob)],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    cache_object = subprocess.run(
        ["git", "cat-file", "-e", f"{cache_oid}^{{blob}}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert cache_object.returncode != 0

    approved.unlink()
    cache_blob.write_bytes(b"changed")
    restore_baseline_worktree(
        repo, baseline.snapshot.id, expected_tree_sha=baseline.snapshot.tree_sha
    )
    assert approved.read_text(encoding="utf-8") == "preserve\n"
    assert not (repo / "node_modules").exists()


def test_mixed_cache_root_preserves_tracked_source_and_drops_cache_residue(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    tracked = repo / "node_modules" / "tracked-source.py"
    deleted = repo / "node_modules" / "tracked-deleted.py"
    tracked.parent.mkdir()
    tracked.write_text("original\n", encoding="utf-8")
    deleted.write_text("delete me\n", encoding="utf-8")
    subprocess.run(["git", "add", "node_modules"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "tracked mixed root"], cwd=repo, check=True, capture_output=True
    )
    tracked.write_text("baseline modification\n", encoding="utf-8")
    deleted.unlink()
    residue = repo / "node_modules" / "dependency" / "large.bin"
    residue.parent.mkdir()
    residue.write_bytes(b"x" * (2 * 1024 * 1024))
    policy = FileStatePolicy(scan_budget=FileStateScanBudget(max_entries=10, max_bytes=1))

    baseline = _capture_runner_boundary(repo, policy, "baseline", snapshot_id="mixed-cache")
    publish_snapshot(repo, baseline.snapshot)
    names = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", baseline.snapshot.commit_sha],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "node_modules/tracked-source.py" in names
    assert "node_modules/tracked-deleted.py" not in names
    assert not any(name.startswith("node_modules/dependency/") for name in names)

    tracked.write_text("runner mutation\n", encoding="utf-8")
    deleted.write_text("runner recreated\n", encoding="utf-8")
    restore_baseline_worktree(
        repo, baseline.snapshot.id, expected_tree_sha=baseline.snapshot.tree_sha
    )
    assert tracked.read_text(encoding="utf-8") == "baseline modification\n"
    assert not deleted.exists()
    assert not residue.exists()


def test_cache_policy_roots_do_not_hide_sources_or_security_descendants(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "node cache"], cwd=repo, check=True, capture_output=True)
    visible = repo / "cache_notes" / "source.py"
    visible.parent.mkdir()
    visible.write_text("source", encoding="utf-8")
    secret = repo / "node_modules" / "dependency" / "id_rsa"
    secret.parent.mkdir(parents=True)
    secret.write_bytes(bytes(range(256)))
    link = repo / "node_modules" / "dependency" / "outside"
    link.symlink_to(tmp_path / "outside")

    status = collect_worktree_status(repo)
    assert declared_tool_cache_roots(status, default_file_state_policy()) == ("node_modules",)
    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="run-1",
        node_id="worker-1",
        execution_id="execution-1",
        base_snapshot_id="base-1",
    )
    by_path = {entry.path: entry for entry in boundary.classification.paths}

    assert by_path["cache_notes/source.py"].classification == "unknown_untracked"
    assert by_path["node_modules/dependency/id_rsa"].classification == "secret"
    assert by_path["node_modules/dependency/outside"].reason == "repo_escape"
    assert boundary.classification.verdict == "rejected"


def test_large_ignored_cache_is_one_root_plus_security_evidence(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ignore large cache"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    cache = repo / "node_modules" / "dependency"
    cache.mkdir(parents=True)
    for index in range(1_500):
        (cache / f"ordinary-{index}.js").write_text("module.exports = 1\n", encoding="utf-8")
    (cache / "id_rsa").write_bytes(bytes(range(256)))
    (cache / "outside").symlink_to(tmp_path / "outside")

    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="run-large-cache",
        node_id="worker-1",
        execution_id="execution-1",
        base_snapshot_id="base-1",
    )
    by_path = {entry.path: entry for entry in boundary.classification.paths}

    assert set(by_path) == {
        "node_modules",
        "node_modules/dependency/id_rsa",
        "node_modules/dependency/outside",
    }
    assert by_path["node_modules"].classification == "tool_cache"
    assert by_path["node_modules/dependency/id_rsa"].classification == "secret"
    assert by_path["node_modules/dependency/outside"].reason == "repo_escape"


def test_worktree_venv_is_opaque_cache_root(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ignore worktree venv"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    packages = repo / ".venv" / "lib" / "python3.12" / "site-packages"
    packages.mkdir(parents=True)
    (packages / "credentials.py").write_text("class Credentials: pass\n", encoding="utf-8")
    (packages / "cacert.pem").write_text("test certificate bundle\n", encoding="utf-8")
    executable = repo / ".venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(tmp_path / "managed-python")

    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="run-venv",
        node_id="planner-1",
        execution_id="execution-1",
        base_snapshot_id="base-1",
    )

    assert boundary.classification.verdict == "captured"
    assert [entry.path for entry in boundary.classification.paths] == [".venv"]
    assert boundary.classification.paths[0].classification == "tool_cache"


def test_cache_security_scan_entry_budget_is_stable_and_charges_symlinks(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ignore cache"], cwd=repo, check=True, capture_output=True
    )
    cache = repo / "node_modules" / "dependency"
    cache.mkdir(parents=True)
    (cache / "a-link").symlink_to(tmp_path / "outside")
    (cache / "id_rsa").write_text("secret", encoding="utf-8")

    policy = FileStatePolicy(scan_budget=FileStateScanBudget(max_entries=2, max_bytes=100))
    failures: list[CacheScanBudgetExceededError] = []
    for _ in range(2):
        with pytest.raises(CacheScanBudgetExceededError) as raised:
            collect_worktree_status(repo, policy)
        failures.append(raised.value)

    assert [(error.metric, error.limit, error.observed, error.path) for error in failures] == [
        ("entries", 2, 3, (cache / "id_rsa").as_posix()),
        ("entries", 2, 3, (cache / "id_rsa").as_posix()),
    ]


def test_cache_security_scan_byte_budget_stops_before_secret_content_read(tmp_path: Path) -> None:
    repo = _init_file_state_repo(tmp_path)
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ignore cache"], cwd=repo, check=True, capture_output=True
    )
    secret = repo / "node_modules" / "id_rsa"
    secret.parent.mkdir()
    secret.write_bytes(b"12345")

    policy = FileStatePolicy(scan_budget=FileStateScanBudget(max_entries=10, max_bytes=4))
    with pytest.raises(CacheScanBudgetExceededError) as raised:
        collect_worktree_status(repo, policy)

    error = raised.value
    assert (error.metric, error.limit, error.observed, error.path) == (
        "bytes",
        4,
        5,
        secret.as_posix(),
    )


@pytest.mark.parametrize("field", ["max_entries", "max_bytes"])
def test_runtime_scan_budget_rejects_compiler_invalid_zero(field: str) -> None:
    with pytest.raises(ValueError, match="at least one"):
        FileStateScanBudget(**{field: 0})


def _init_file_state_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".hypothesis/\nscratch/\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo
