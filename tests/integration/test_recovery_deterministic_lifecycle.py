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
    assert evidence.qualification_contract_identity.interaction_contract == "decision-v1"
    assert evidence.graph_state == "completed"
    assert evidence.workflow_status == "completed"
    assert evidence.phase_counts.model_phases == len(evidence.dispatch_node_ids)
    assert evidence.phase_counts.finalized_executions == evidence.finalized_execution_count
    assert sum(evidence.phase_counts.by_node_kind.values()) == evidence.phase_counts.model_phases
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

    assert evidence.phase_counts.model_phases > 0
    assert evidence.dispatch_node_ids[0] == "planner-s-01"
    assert any(node_id.startswith("planner-successor-") for node_id in evidence.dispatch_node_ids)
    assert evidence.dispatch_node_ids[-1].startswith("verifier-final-audit-")
    assert len(evidence.verifier_instance_ids) == evidence.phase_counts.by_node_kind["verifier"]
    assert len(set(evidence.verifier_instance_ids)) == len(evidence.verifier_instance_ids)
    assert evidence.event_type_counts["graph_patch_accepted"] >= 2
    for event_type in (
        "runner_submission_staged",
        "runner_completion_witnessed",
        "runner_execution_finalized",
    ):
        assert evidence.event_type_counts[event_type] == evidence.finalized_execution_count
    assert set(evidence.check_statuses.values()) == {"passed"}
    assert len(evidence.check_statuses) == 2
    assert evidence.completion_status == "passed"
    assert set(evidence.task_states.values()) == {"accepted"}
    assert evidence.remaining_node_states == {}
    assert evidence.finalized_execution_count > 0
    assert evidence.active_lease_count == 0
    assert evidence.owned_process_count == 0
    assert evidence.pending_outbox_count == 0

    readback = evidence.public_readback
    assert readback.accepted is True
    assert readback.graph_state == "completed"
    assert readback.workflow_status == "completed"
    assert readback.candidate_paths == ["stage3-smoke.txt"]
    assert readback.candidate_mode == "100644"
    assert readback.clean_checkout is True
    assert readback.check_statuses == evidence.check_statuses
    assert readback.suspended_lease_count == 0
    assert readback.unfinished_node_ids == []
    assert "stage3-smoke.txt" in readback.explanation
    assert "passed" in readback.explanation
    assert lifecycle.LifecycleEvidence.model_validate_json(evidence.model_dump_json()) == evidence


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_legacy_lifecycle_remains_a_separate_compatibility_entry(tmp_path: Path) -> None:
    evidence = await lifecycle.run_legacy_lifecycle(tmp_path)

    assert evidence.status == "passed"
    assert evidence.qualification_contract_identity.interaction_contract == "legacy"
    assert evidence.graph_state == "completed"
    assert evidence.exact_candidate is True
