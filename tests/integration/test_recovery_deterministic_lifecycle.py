"""Deterministic closure for the failed Stage 3 lifecycle smoke."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "deterministic_lifecycle",
    Path("examples/recovery/deterministic_lifecycle.py"),
)
assert _SPEC and _SPEC.loader
lifecycle = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = lifecycle
_SPEC.loader.exec_module(lifecycle)


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_one_file_dynamic_lifecycle_reaches_clean_terminal_completion(
    tmp_path: Path,
) -> None:
    evidence = await lifecycle.run_lifecycle(tmp_path)

    assert evidence.status == "passed"
    assert evidence.graph_state == "completed"
    assert evidence.workflow_status == "completed"
    assert evidence.changed_paths == ["stage3-smoke.txt"]
    assert evidence.exact_candidate is True
    assert (tmp_path / "run-worktree" / "stage3-smoke.txt").read_bytes() == (b"stage3-smoke-ok\n")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=tmp_path / "run-worktree",
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
    assert not (tmp_path / "run-worktree" / ".gitignore").exists()
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", ".orchestrator/runtime/scaffolding.json"],
            cwd=tmp_path / "run-worktree",
        ).returncode
        == 0
    )

    assert len(evidence.dispatch_node_ids) == 7
    assert evidence.dispatch_node_ids[0] == "planner-s-01"
    assert evidence.dispatch_node_ids[3].startswith("planner-successor-")
    assert evidence.dispatch_node_ids[-1].startswith("verifier-final-audit-")
    assert len(evidence.verifier_instance_ids) == 3
    assert len(set(evidence.verifier_instance_ids)) == 3
    assert evidence.event_type_counts["graph_patch_accepted"] == 2
    for event_type in (
        "runner_submission_staged",
        "runner_completion_witnessed",
        "runner_execution_finalized",
    ):
        assert evidence.event_type_counts[event_type] == 7
    assert set(evidence.check_statuses.values()) == {"passed"}
    assert len(evidence.check_statuses) == 2
    assert evidence.completion_status == "passed"
    assert set(evidence.task_states.values()) == {"accepted"}
    assert evidence.remaining_node_states == {}
    assert evidence.finalized_execution_count == 7
    assert evidence.active_lease_count == 0
    assert evidence.owned_process_count == 0
    assert evidence.pending_outbox_count == 0
