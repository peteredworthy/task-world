"""Tests for oversight-mode worktree change guards."""

from orchestrator.workflow import find_oversight_change_violations


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
