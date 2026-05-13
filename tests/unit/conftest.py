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
import os
import subprocess
import time
from pathlib import Path

import pytest

_collection_start: float = 0.0
_files_checked = 0
_files_parsed = 0


def pytest_sessionstart(session: pytest.Session) -> None:
    global _collection_start
    _collection_start = time.perf_counter()


def pytest_collection_finish(session: pytest.Session) -> None:
    elapsed = time.perf_counter() - _collection_start
    print(
        f"\n[boundary-check] {elapsed:.3f}s"
        f" | files_checked={_files_checked} ast_parsed={_files_parsed}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Shared git-repo template fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _unit_base_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a minimal git repo ONCE per worker session.

    Unit tests that need a fresh git repo should use ``shutil.copytree``
    to copy this template instead of running ``git init`` + config + commit
    for every test.  Copytree copies the entire ``.git/config`` (including
    user.email / user.name), so no extra config calls are needed.
    Savings: ~100 ms per test on macOS (5-6 subprocess calls → 0).
    """
    base = tmp_path_factory.mktemp("unit_base_repo")
    repo = base / "repo"
    repo.mkdir()

    def _git(*args: str) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
        subprocess.run(list(args), cwd=repo, check=True, capture_output=True, env=env)

    _git("git", "init")
    _git("git", "config", "user.email", "test@test.com")
    _git("git", "config", "user.name", "Test")
    (repo / "README.md").write_text("# Test\n")
    _git("git", "add", ".")
    _git("git", "commit", "-m", "Initial commit")
    _git("git", "branch", "-M", "main")
    return repo


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


_FAST_KEYWORDS = frozenset(["testclient", "StaticPool", "create_app"])


def _check_unit_test_file(path: Path) -> list[str]:
    """Return a list of violation messages for *path*, empty if clean.

    All unit-test files are checked — there are no exceptions.
    """
    global _files_checked, _files_parsed
    _files_checked += 1
    try:
        source = path.read_text(encoding="utf-8")
        # Fast path: skip AST parse if no forbidden keyword appears in source.
        if not any(kw in source for kw in _FAST_KEYWORDS):
            return []
        _files_parsed += 1
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

    if file_path.suffix != ".py":
        return

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
