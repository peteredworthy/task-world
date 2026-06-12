"""Shared git subprocess helpers for unit tests.

All helpers strip GIT_* environment variables before running git commands
to prevent test operations from leaking into the main project's .git config
(GIT_DIR is set in the environment when tests run under pre-commit hooks).
"""

import os
import subprocess
import shutil
from pathlib import Path

_GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
_GIT_ENV["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
_PATH_ENTRIES = [
    path
    for path in _GIT_ENV.get("PATH", "").split(os.pathsep)
    if path and "orchestrator-git-wrapper-bin" not in path
]
for required in ("/usr/bin", "/usr/local/bin", "/bin"):
    if required not in _PATH_ENTRIES:
        _PATH_ENTRIES.append(required)
_GIT_ENV["PATH"] = os.pathsep.join(_PATH_ENTRIES)
_GIT_BIN = shutil.which("git", path=_GIT_ENV["PATH"]) or "/usr/bin/git"


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        [_GIT_BIN] + args, cwd=cwd, check=True, capture_output=True, text=True, env=_GIT_ENV
    )
    return result.stdout.strip()


def _commit_file(path: Path, filename: str, content: str, message: str) -> str:
    """Write a file, stage it, commit it, and return the commit SHA."""
    (path / filename).write_text(content)
    _git(["add", filename], cwd=path)
    _git(["commit", "-m", message], cwd=path)
    return _git(["rev-parse", "HEAD"], cwd=path)


def _init_repo(path: Path) -> None:
    """Initialize a bare-minimum git repo with one commit on main."""
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)
    _git(["branch", "-M", "main"], cwd=path)
