"""Tests for oversight-mode worktree change guards."""

from pathlib import Path
import subprocess

import pytest

from orchestrator.workflow import (
    OversightModeViolationError,
    ensure_oversight_worktree_changes_allowed,
    find_oversight_change_violations,
    find_oversight_committed_change_violations,
)


def test_oversight_guard_allows_super_parent_docs_and_mcp_config() -> None:
    violations = find_oversight_change_violations(
        [
            " M .mcp.json",
            " M docs/super-parent/current-understanding.md",
            "?? docs/super-parent/evidence/child.json",
        ]
    )

    assert violations == []


def test_oversight_guard_rejects_source_test_and_dependency_changes() -> None:
    violations = find_oversight_change_violations(
        [
            " M src/orchestrator/workflow/oversight.py",
            " M tests/unit/test_super_parent_oversight.py",
            " M ui/src/App.tsx",
            " M pyproject.toml",
            " M uv.lock",
        ]
    )

    assert violations == [
        "pyproject.toml",
        "src/orchestrator/workflow/oversight.py",
        "tests/unit/test_super_parent_oversight.py",
        "ui/src/App.tsx",
        "uv.lock",
    ]


def test_oversight_guard_checks_both_paths_for_renames() -> None:
    violations = find_oversight_change_violations(
        ["R  docs/super-parent/old.md -> src/orchestrator/new.py"]
    )

    assert violations == ["src/orchestrator/new.py"]


def test_oversight_guard_rejects_committed_source_changes() -> None:
    violations = find_oversight_committed_change_violations(
        [
            "M\tsrc/orchestrator/workflow/service.py",
            "A\tdocs/super-parent/current-understanding.md",
            "R100\tdocs/super-parent/old.md\ttests/unit/test_new.py",
        ]
    )

    assert violations == [
        "src/orchestrator/workflow/service.py",
        "tests/unit/test_new.py",
    ]


def test_oversight_guard_checks_attempt_commit_range(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Initial")
    base_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / "src").mkdir()
    (repo / "src" / "changed.py").write_text("print('not oversight')\n")
    _git(repo, "add", "src/changed.py")
    _git(repo, "commit", "-m", "Change source during oversight")

    with pytest.raises(OversightModeViolationError, match="src/changed.py"):
        ensure_oversight_worktree_changes_allowed(repo, base_commit=base_commit)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
