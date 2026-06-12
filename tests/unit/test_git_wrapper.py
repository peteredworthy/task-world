from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GIT_WRAPPER = REPO_ROOT / "scripts" / "worktree" / "git-wrapper.sh"
GIT = "/usr/bin/git"


def _run(
    args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run([GIT, "init"], repo)
    (repo / "sample.txt").write_text("hello\n", encoding="utf-8")
    _run([GIT, "add", "sample.txt"], repo)
    result = _run(
        [
            GIT,
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        repo,
    )
    assert result.returncode == 0, result.stderr
    return repo


def _wrapper_env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["ORCHESTRATOR_RUN_WORKTREE"] = str(repo)
    env.pop("ORCHESTRATOR_RUN_BRANCH", None)
    return env


def test_git_wrapper_allows_common_read_only_flags(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = _wrapper_env(repo)

    commands = [
        ["rev-parse", "--show-cdup"],
        ["diff", "--exit-code", "--", "sample.txt"],
        ["log", "-5", "--oneline"],
        ["ls-files", "--error-unmatch", "--", "sample.txt"],
    ]

    for command in commands:
        result = _run([str(GIT_WRAPPER), *command], repo, env)
        assert result.returncode == 0, f"{command}: {result.stderr}"


def test_git_wrapper_blocks_dangerous_read_only_flags(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = _wrapper_env(repo)

    commands = [
        ["diff", "--output", "patch.txt"],
        ["diff", "--ext-diff"],
        ["rev-parse", "--git-dir"],
        ["rev-parse", "--path-format", "absolute", "--show-toplevel"],
        ["ls-files", "--exclude-from", "../outside"],
    ]

    for command in commands:
        result = _run([str(GIT_WRAPPER), *command], repo, env)
        assert result.returncode != 0, command
        assert "blocked option" in result.stderr
        assert "this wrapper protects orchestrator run worktrees" in result.stderr
        assert "Do not bypass the wrapper" in result.stderr
