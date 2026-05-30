"""Auto-commit timeout configuration."""

from __future__ import annotations

from orchestrator.git import (
    GIT_ADD_TIMEOUT_SECONDS,
    GIT_COMMIT_TIMEOUT_SECONDS,
    GIT_QUICK_TIMEOUT_SECONDS,
)


def test_commit_timeout_allows_hook_driven_test_suites() -> None:
    assert GIT_QUICK_TIMEOUT_SECONDS == 30
    assert GIT_ADD_TIMEOUT_SECONDS >= 5 * 60
    assert GIT_COMMIT_TIMEOUT_SECONDS >= 30 * 60
