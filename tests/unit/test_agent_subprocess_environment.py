from __future__ import annotations

import os

from orchestrator.runners.environment import build_agent_subprocess_env


def test_build_agent_subprocess_env_isolates_host_git_config() -> None:
    env = build_agent_subprocess_env(
        base_env={"PATH": os.defpath},
        run_worktree="/tmp/run-worktree",
        expected_run_branch="orchestrator/run-test",
    )

    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_AUTHOR_NAME"] == "Orchestrator Agent"
    assert env["GIT_AUTHOR_EMAIL"] == "orchestrator@local"
    assert env["GIT_COMMITTER_NAME"] == "Orchestrator Agent"
    assert env["GIT_COMMITTER_EMAIL"] == "orchestrator@local"
    assert env["ORCHESTRATOR_RUN_WORKTREE"] == "/tmp/run-worktree"
    assert env["ORCHESTRATOR_RUN_BRANCH"] == "orchestrator/run-test"
