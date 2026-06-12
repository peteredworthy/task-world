"""Auto-commit retries once when commit hooks reformat staged files."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from orchestrator.git.errors import WorktreeCommitError
from orchestrator.git.utils import commit_uncommitted_changes_or_raise

GIT = "/usr/bin/git"


def _init_repo(path: Path) -> None:
    subprocess.run([GIT, "init", "-q"], cwd=path, check=True)
    subprocess.run([GIT, "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run([GIT, "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("seed\n")
    subprocess.run([GIT, "add", "-A"], cwd=path, check=True)
    subprocess.run([GIT, "commit", "-q", "-m", "seed"], cwd=path, check=True)


def _install_pre_commit_hook(path: Path, script: str) -> None:
    hook = path / ".git" / "hooks" / "pre-commit"
    hook.write_text(script)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


def test_retries_once_when_hook_reformats_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    # Mimic ruff-format: first run rewrites the staged file and fails with the
    # canonical "files were modified by this hook" message; second run passes.
    _install_pre_commit_hook(
        repo,
        "#!/bin/sh\n"
        "if [ ! -f .hook_ran ]; then\n"
        "  touch .hook_ran\n"
        '  printf "formatted\\n" > code.py\n'
        '  echo "- files were modified by this hook"\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
    )
    (repo / "code.py").write_text("unformatted")

    result = commit_uncommitted_changes_or_raise(repo, "auto-commit test")

    assert result.created_commit is True
    assert (repo / "code.py").read_text() == "formatted\n"
    status = subprocess.run(
        [GIT, "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    )
    untracked = [line for line in status.stdout.splitlines() if not line.endswith(".hook_ran")]
    assert untracked == []


def test_persistent_hook_failure_still_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _install_pre_commit_hook(
        repo,
        '#!/bin/sh\necho "- files were modified by this hook"\nexit 1\n',
    )
    (repo / "code.py").write_text("unformatted")

    with pytest.raises(WorktreeCommitError):
        commit_uncommitted_changes_or_raise(repo, "auto-commit test")


def test_non_hook_failure_does_not_retry(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _install_pre_commit_hook(
        repo,
        '#!/bin/sh\necho "lint error: bad code"\nexit 1\n',
    )
    (repo / "code.py").write_text("bad")

    with pytest.raises(WorktreeCommitError) as excinfo:
        commit_uncommitted_changes_or_raise(repo, "auto-commit test")
    assert "lint error" in str(excinfo.value)


def test_hook_env_does_not_leak_parent_git_dir(tmp_path: Path) -> None:
    # Sanity: GIT_DIR/GIT_WORK_TREE from any parent process must not redirect
    # the test repo's commit; assert commit landed in the tmp repo.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "file.txt").write_text("x\n")
    result = commit_uncommitted_changes_or_raise(repo, "plain commit")
    assert result.created_commit is True
    head = subprocess.run(
        [GIT, "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert head.stdout.strip() == "plain commit"
    assert os.environ.get("GIT_DIR") is None
