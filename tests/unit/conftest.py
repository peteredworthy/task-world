"""Unit-test boundary enforcement.

Unit tests must not boot a full HTTP app, open real WebSocket connections, or
import heavy infrastructure that belongs only in integration tests.  This
conftest registers a collection hook that fails loudly when a unit-test module
violates these boundaries.

Forbidden imports in tests/unit/:
  - orchestrator.api.app.create_app  (starts a full ASGI app)
  - starlette.testclient.TestClient  (HTTP + WebSocket test client)
  - sqlalchemy.pool.StaticPool        (in-memory shared-pool pattern used only
                                       in integration fixtures)

Integration tests (tests/integration/) may use all of the above freely.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Forbidden import patterns for unit test files
# ---------------------------------------------------------------------------

_FORBIDDEN: list[tuple[str, str]] = [
    # (module_path_fragment, human-readable description)
    ("starlette.testclient", "starlette.testclient.TestClient"),
    ("fastapi.testclient", "fastapi.testclient.TestClient"),
    ("sqlalchemy.pool.StaticPool", "sqlalchemy.pool.StaticPool"),
]

_FORBIDDEN_NAMES = {"create_app"}


def _check_unit_test_file(path: Path) -> list[str]:
    """Return a list of violation messages for *path*, empty if clean.

    All unit-test files are checked — there are no exceptions.
    """
    try:
        source = path.read_text(encoding="utf-8")
        # Allow explicit opt-out for a file with a special marker comment
        if "# unit-test-boundary: ignore" in source:
            return []
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for fragment, label in _FORBIDDEN:
                if module.startswith(fragment.split(".")[0]) and fragment in module:
                    violations.append(f"  - imports '{label}' (forbidden in unit tests)")
            # Check 'from X import create_app'
            names = [alias.name for alias in node.names]
            if any(n in _FORBIDDEN_NAMES for n in names):
                imported = [n for n in names if n in _FORBIDDEN_NAMES]
                violations.append(
                    f"  - imports {imported} (create_app boots a full ASGI app; "
                    f"forbidden in unit tests)"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for fragment, label in _FORBIDDEN:
                    if alias.name.startswith(fragment.split(".")[0]) and fragment in alias.name:
                        violations.append(f"  - imports '{label}' (forbidden in unit tests)")

    return violations


def pytest_collect_file(parent: pytest.Collector, file_path: Path) -> None:
    """Fail collection for unit-test files that violate import boundaries."""
    # Only enforce inside tests/unit/ (not tests/unit/conftest.py itself)
    try:
        file_path.relative_to(Path(__file__).parent)
    except ValueError:
        return

    if file_path.name == "conftest.py":
        return  # conftest files are exempt

    if not file_path.name.startswith("test_"):
        return

    violations = _check_unit_test_file(file_path)
    if violations:
        raise pytest.UsageError(
            f"\nUnit-test boundary violation in {file_path}:\n"
            + "\n".join(violations)
            + "\n\nMove this test to tests/integration/ or remove the forbidden imports.\n"
            "See AGENTS.md § Testing for the unit/integration boundary rules."
        )
