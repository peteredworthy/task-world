"""Focused proof for the isolated reliable-plan successor harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import FakeClock, SequentialIdGenerator, StoredArtifactRef
from orchestrator.graph_runtime import (
    replay_reliable_plan_rejection,
    resolve_orchestrator_source_root,
)


pytestmark = pytest.mark.slow


_SPEC = importlib.util.spec_from_file_location(
    "successor_planner_probe",
    Path("examples/recovery/successor_planner_probe.py"),
)
assert _SPEC and _SPEC.loader
probe = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = probe
_SPEC.loader.exec_module(probe)


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_deterministic_successor_uses_codex_route_and_retains_replay(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "protected"
    with tempfile.TemporaryDirectory(dir=tmp_path) as raw_workspace:
        workspace = Path(raw_workspace)
        evidence = await probe.run_probe(workspace, evidence_root)
    assert not workspace.exists()

    assert evidence.status == "passed"
    assert evidence.model == "gpt-5.6-luna"
    assert evidence.reasoning_effort == "medium"
    assert evidence.phase_node_ids[:3] == [
        "planner-s-01",
        "worker-discovery-stage3-discovery-65899afc882cd542",
        "verifier-plan-stage3-discovery-65899afc882cd542",
    ]
    assert evidence.successor_node_id == evidence.phase_node_ids[3]
    assert evidence.successor_node_id != evidence.phase_node_ids[0]
    assert evidence.execution_count == 1
    assert evidence.rejected_patch_ids == ["successor-probe-rejected-1"]
    assert evidence.accepted_patch_ids == ["successor-probe-accepted"]
    assert evidence.replayed_rejection_count == 1
    assert evidence.downstream_dispatch_count == 0
    assert evidence.downstream_active_lease_count == 0
    assert evidence.pending_outbox_count == 0
    assert evidence.owned_process_count_after == 0
    assert evidence.fixture_unchanged is True
    assert all(evidence.strict_predicates.values())
    assert evidence.phase_event_counts["graph_patch_accepted"] == 1
    assert evidence.phase_event_counts["command_rejected"] == 1
    assert evidence.phase_event_counts["runner_execution_finalized"] == 1
    assert len(evidence.dynamic_tool_receipts) == 3
    assert all(item["request_response_complete"] for item in evidence.dynamic_tool_receipts)

    context_ref = StoredArtifactRef.model_validate(evidence.protected_context_ref)
    protected = await FilesystemArtifactStore(Path(evidence.artifact_root)).read(context_ref)
    context = json.loads(protected)
    assert context["successor_node_id"] == evidence.successor_node_id
    assert "current_declared_batch" in context["successor_prompt"]
    assert {tool["name"] for tool in context["dynamic_tools"]} >= {
        "construct_reliable_plan_region",
        "submit",
    }
    rejection_ref = StoredArtifactRef.model_validate(evidence.rejection_evidence[0]["artifact_ref"])
    replay_engine = create_engine(tmp_path / "post-cleanup-replay.db")
    await init_db(replay_engine)
    try:
        replay = await replay_reliable_plan_rejection(
            artifact_store=FilesystemArtifactStore(Path(evidence.artifact_root)),
            evidence_ref=rejection_ref,
            isolated_session_factory=create_session_factory(replay_engine),
            clock=FakeClock(),
            id_gen=SequentialIdGenerator(),
            worktree_path=resolve_orchestrator_source_root(),
        )
    finally:
        await replay_engine.dispose()
    assert replay.reproduced is True


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_successor_submission_is_required(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    evidence = await probe.run_probe(
        workspace,
        tmp_path / "protected",
        scenario="no_submit",
    )

    assert evidence.status == "failed"
    assert evidence.execution_count == 1
    assert evidence.strict_predicates["plain_submission_finalized"] is False
    assert evidence.strict_predicates["no_runtime_recovery_or_retry"] is False
    assert evidence.downstream_dispatch_count == 0
    assert evidence.owned_process_count_after == 0


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_successor_proposal_cap_stops_acceptance_and_retry(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    evidence = await probe.run_probe(
        workspace,
        tmp_path / "protected",
        scenario="cap",
    )

    assert evidence.status == "failed"
    assert evidence.rejected_patch_ids == [
        "successor-probe-rejected-1",
        "successor-probe-rejected-2",
    ]
    assert evidence.accepted_patch_ids == []
    assert evidence.execution_count == 1
    assert evidence.recorded_execution_attempt_count == 1
    assert evidence.replayed_rejection_count == 2
    assert evidence.downstream_dispatch_count == 0
    assert evidence.owned_process_count_after == 0


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_successor_timeout_drains_exact_owner_without_retry(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    evidence = await probe.run_probe(
        workspace,
        tmp_path / "protected",
        scenario="timeout",
        timeout_seconds=0.01,
    )

    assert evidence.status == "incomplete"
    assert evidence.timed_out is True
    assert evidence.incomplete_reason == "model wall timeout expired"
    assert evidence.execution_count == 1
    assert evidence.downstream_dispatch_count == 0
    assert evidence.owned_process_count_after == 0
    assert evidence.cleanup_unbounded_for_ownership is True


def test_paid_cli_requires_explicit_opt_in(tmp_path: Path) -> None:
    evidence_root = tmp_path / "must-not-exist"
    with pytest.raises(SystemExit, match="2"):
        probe.main(["paid", "--evidence-root", str(evidence_root)])
    assert not evidence_root.exists()


@pytest.mark.asyncio
async def test_rejects_evidence_inside_disposable_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError, match="outside"):
        await probe.run_probe(workspace, workspace / "evidence")


def test_cli_rejects_timeout_above_cap(capsys: pytest.CaptureFixture[str]) -> None:
    result = probe.main(["deterministic", "--timeout-seconds", "181"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error_type"] == "ValueError"
    assert payload["error"] == "successor probe failed; inspect protected evidence if available"


def test_default_cli_serializes_unexpected_error_without_private_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(*_args: object, **_kwargs: object) -> probe.SuccessorProbeEvidence:
        raise RuntimeError("private-token-must-not-escape")

    result = probe.main([], run_probe_fn=fail)

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "successor probe failed; inspect protected evidence if available"
    assert "private-token" not in json.dumps(payload)
