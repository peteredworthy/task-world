"""Real production-gate regression for journal isolation and cleanup."""

from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from orchestrator.graph_runtime import enforce_submission_quality_gate


pytestmark = pytest.mark.slow


_JOURNAL_AND_CLEANUP_TESTS = (
    "tests/unit/test_signal_consumer.py::test_processed_marker_is_exported_to_jsonl",
    "tests/integration/test_jsonl_rotation_recovery.py::"
    "test_graph_events_reach_the_committed_jsonl_journal",
    "tests/integration/test_jsonl_rotation_recovery.py::"
    "test_graph_controller_rotates_at_its_injected_journal_limit",
    "tests/integration/test_output_batching.py::"
    "test_output_batching_session_factory_writes_jsonl_outbox",
    "tests/unit/test_graph_submission_gate.py::test_gate_unlocks_its_exact_checkout_before_cleanup",
    "tests/integration/test_server_supervisor_process.py::"
    "test_relaunch_reclaims_child_orphaned_by_supervisor_sigkill",
)


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_configured_project_gate_runs_journal_and_cleanup_regressions_nested(
    tmp_path: Path,
) -> None:
    """Exercise the named regressions as the checked-in project-command seam."""
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    shutil.copytree(
        source,
        repo,
        ignore=shutil.ignore_patterns(
            ".git",
            ".claude",
            ".venv",
            ".orchestrator",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "node_modules",
            "orchestrator.db",
            "orchestrator.db-*",
            "outputs",
            "repos",
            "tmp",
            "worktrees",
            "*.log",
        ),
    )
    # The outer test runner can itself be OS-sandboxed. Use its exact Python
    # dependency environment while keeping the test collection and application
    # imports bound to the disposable candidate checkout.
    command = f"{shlex.quote(sys.executable)} -m pytest -n 0 -q " + " ".join(
        _JOURNAL_AND_CLEANUP_TESTS
    )
    config = repo / ".task-world" / "config.yaml"
    config.parent.mkdir(exist_ok=True)
    config.write_text(f'test_command: "{command}"\n', encoding="utf-8")
    # Prevent the gate from nesting macOS sandbox-exec around a test process
    # that may already run inside the agent sandbox. Production dependencies
    # still come from the exact interpreter named by the configured command.
    with (repo / "uv.lock").open("a", encoding="utf-8") as lock_file:
        lock_file.write("\n# nested-gate-fixture\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Gate Test",
            "-c",
            "user.email=gate@example.test",
            "commit",
            "-qm",
            "nested gate fixture",
        ],
        cwd=repo,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    report = await enforce_submission_quality_gate(
        run_id="nested-journal-regressions",
        node_id="worker-nested-journal-regressions",
        execution_id="execution-nested-journal-regressions",
        lease_id="lease-nested-journal-regressions",
        lease_generation=1,
        base_snapshot_id="baseline-nested-journal-regressions",
        base_tree_sha=tree,
        node_payload={},
        dynamic_feature=None,
        worktree_path=repo,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
    )

    assert report.status == "passed"
    assert len(report.results) == 1
    assert report.results[0].source == "project_test_command"
    assert report.results[0].exit_code == 0
    assert report.results[0].failed_test_ids == ()
