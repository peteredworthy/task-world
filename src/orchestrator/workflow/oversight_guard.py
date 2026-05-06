"""Guards for oversight-only task submissions."""

from collections.abc import Sequence
from pathlib import Path
import subprocess

from orchestrator.workflow.engine.errors import WorkflowError

_ALLOWED_OVERSIGHT_EXACT_PATHS = frozenset({".mcp.json"})
_ALLOWED_OVERSIGHT_PREFIXES = ("docs/super-parent/",)


class OversightModeViolationError(WorkflowError):
    """Raised when an oversight task attempts implementation file changes."""

    def __init__(self, paths: Sequence[str]) -> None:
        self.paths = list(paths)
        super().__init__(
            "Oversight task attempted disallowed file changes: " + ", ".join(self.paths)
        )


def find_oversight_change_violations(status_lines: Sequence[str]) -> list[str]:
    """Return git-status paths not allowed for oversight-only tasks."""
    violations: set[str] = set()
    for line in status_lines:
        for path in _paths_from_porcelain_line(line):
            if not _is_allowed_oversight_path(path):
                violations.add(path)
    return sorted(violations)


def ensure_oversight_worktree_changes_allowed(
    worktree_path: Path, base_commit: str | None = None
) -> None:
    """Raise if an oversight task has implementation changes.

    Checks both dirty worktree changes and changes already committed since the
    current task attempt started. The latter matters because CLI agents may
    commit their own work before calling submit.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    )
    violations = set(find_oversight_change_violations(status.stdout.splitlines()))
    if base_commit:
        diff = subprocess.run(
            ["git", "diff", "--name-status", "--find-renames", f"{base_commit}..HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True,
        )
        violations.update(find_oversight_committed_change_violations(diff.stdout.splitlines()))

    if violations:
        raise OversightModeViolationError(sorted(violations))


def find_oversight_committed_change_violations(status_lines: Sequence[str]) -> list[str]:
    """Return committed paths not allowed for oversight-only tasks."""
    violations: set[str] = set()
    for line in status_lines:
        for path in _paths_from_name_status_line(line):
            if not _is_allowed_oversight_path(path):
                violations.add(path)
    return sorted(violations)


def _paths_from_porcelain_line(line: str) -> list[str]:
    if len(line) < 4:
        return []
    path_text = line[3:].strip()
    if " -> " in path_text:
        return [_unquote_path(path) for path in path_text.split(" -> ", maxsplit=1)]
    return [_unquote_path(path_text)]


def _paths_from_name_status_line(line: str) -> list[str]:
    parts = line.split("\t")
    if len(parts) < 2:
        return []
    return [_unquote_path(path) for path in parts[1:] if path]


def _unquote_path(path: str) -> str:
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        return path[1:-1]
    return path


def _is_allowed_oversight_path(path: str) -> bool:
    return path in _ALLOWED_OVERSIGHT_EXACT_PATHS or path.startswith(_ALLOWED_OVERSIGHT_PREFIXES)
