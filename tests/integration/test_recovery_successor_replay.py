"""No-model replay checks for the successor probe result boundary."""

from __future__ import annotations

import asyncio
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
from typing import Any

import pytest

from examples.recovery import replay_successor_probe as replay
from orchestrator.artifacts import FilesystemArtifactStore, StoredArtifactRef
from orchestrator.runners import (
    CodexDynamicToolReceipt,
    build_dynamic_tool_call_response,
    route_tool_call,
)


pytestmark = pytest.mark.slow

_SPEC = importlib.util.spec_from_file_location(
    "successor_planner_probe_replay_test",
    Path("examples/recovery/successor_planner_probe.py"),
)
assert _SPEC and _SPEC.loader
probe = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = probe
_SPEC.loader.exec_module(probe)


@pytest.mark.asyncio
async def test_replay_successor_result_replays_controller_artifacts_without_model(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "protected"
    with tempfile.TemporaryDirectory(dir=tmp_path) as raw_workspace:
        evidence = await probe.run_probe(Path(raw_workspace), evidence_root)

    summary = await replay.replay_result(Path(evidence.result_path))

    assert summary.status == "passed"
    assert summary.source_result_status == "passed"
    assert summary.source_probe_passed is True
    assert summary.source_identity_verified is True
    assert summary.rejection_count == summary.replayed_rejection_count == 1
    assert summary.controller_correlated_count == 1
    assert summary.non_replayable_count == 0

    failed_source_path = tmp_path / "failed-source-result.json"
    failed_source = json.loads(Path(evidence.result_path).read_text(encoding="utf-8"))
    failed_source["status"] = "failed"
    failed_source_path.write_text(json.dumps(failed_source), encoding="utf-8")
    replayed_failed_source = await replay.replay_result(failed_source_path)
    assert replayed_failed_source.status == "passed"
    assert replayed_failed_source.source_result_status == "failed"
    assert replayed_failed_source.source_probe_passed is False


@pytest.mark.asyncio
async def test_replay_fails_closed_for_tampered_result_and_cli_is_safe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root = tmp_path / "protected"
    with tempfile.TemporaryDirectory(dir=tmp_path) as raw_workspace:
        evidence = await probe.run_probe(Path(raw_workspace), evidence_root)

    result_path = Path(evidence.result_path)
    tampered_path = tmp_path / "tampered-result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["dynamic_tool_receipts"][0]["request_sha256"] = "sha256:" + ("0" * 64)
    tampered_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(replay.ReplayProbeError):
        await replay.replay_result(tampered_path)

    assert await asyncio.to_thread(replay.main, [str(tampered_path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output == {"status": "error", "error_type": "ReplayProbeError"}

    context_tampered_path = tmp_path / "tampered-context-result.json"
    context_payload = json.loads(result_path.read_text(encoding="utf-8"))
    context_payload["spec_sha256"] = "sha256:" + ("0" * 64)
    context_tampered_path.write_text(json.dumps(context_payload), encoding="utf-8")
    with pytest.raises(replay.ReplayProbeError, match="protected context identity differs"):
        await replay.replay_result(context_tampered_path)

    prompt_tampered_path = tmp_path / "tampered-prompt-result.json"
    prompt_payload = json.loads(result_path.read_text(encoding="utf-8"))
    prompt_payload["successor_prompt_sha256"] = "0" * 64
    prompt_tampered_path.write_text(json.dumps(prompt_payload), encoding="utf-8")
    with pytest.raises(replay.ReplayProbeError, match="protected successor prompt differs"):
        await replay.replay_result(prompt_tampered_path)

    authority_tampered_path = tmp_path / "tampered-authority-result.json"
    authority_payload = json.loads(result_path.read_text(encoding="utf-8"))
    authority_payload["successor_authority"]["planning_horizon"] = 99
    authority_tampered_path.write_text(json.dumps(authority_payload), encoding="utf-8")
    with pytest.raises(replay.ReplayProbeError, match="protected successor authority differs"):
        await replay.replay_result(authority_tampered_path)

    empty_evidence_path = tmp_path / "empty-evidence-result.json"
    empty_evidence = json.loads(result_path.read_text(encoding="utf-8"))
    store = FilesystemArtifactStore(Path(empty_evidence["artifact_root"]))
    protected_ref = StoredArtifactRef.model_validate(empty_evidence["protected_context_ref"])
    protected_context = json.loads((await store.read(protected_ref)).decode("utf-8"))
    protected_context["dynamic_tool_receipt_refs"] = []
    replacement_ref = await store.put(
        json.dumps(protected_context, sort_keys=True, separators=(",", ":")).encode(),
        media_type="application/vnd.orchestrator.successor-probe-context+json",
        encoding="utf-8",
    )
    empty_evidence["protected_context_ref"] = replacement_ref.model_dump(mode="json")
    empty_evidence["dynamic_tool_receipts"] = []
    empty_evidence_path.write_text(json.dumps(empty_evidence), encoding="utf-8")
    with pytest.raises(replay.ReplayProbeError, match="dynamic tool receipts are missing"):
        await replay.replay_result(empty_evidence_path)


def _receipt(request: dict[str, Any], response: dict[str, Any]) -> CodexDynamicToolReceipt:
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
    response_json = json.dumps(response, sort_keys=True, separators=(",", ":"))
    return CodexDynamicToolReceipt(
        thread_id="thread-replay",
        turn_id="turn-replay",
        request_id=request["id"],
        request_sha256=f"sha256:{replay._sha256_bytes(request_json.encode())}",
        response_sha256=f"sha256:{replay._sha256_bytes(response_json.encode())}",
        request_size_bytes=len(request_json.encode()),
        response_size_bytes=len(response_json.encode()),
        request_response_complete=True,
        request=request_json,
        response=response_json,
    )


@pytest.mark.asyncio
async def test_replay_pre_controller_normalization_uses_fresh_error_response() -> None:
    arguments = {"operation_key": "missing-patch-id"}
    request = {
        "jsonrpc": "2.0",
        "id": 77,
        "method": "item/tool/call",
        "params": {"tool": "construct_reliable_plan_region", "arguments": arguments},
    }

    async def fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("normalization replay crossed the controller boundary")

    with pytest.raises(ValueError) as raised:
        await route_tool_call(
            "construct_reliable_plan_region",
            arguments,
            fail_if_called,
            fail_if_called,
            on_submit_graph_patch=fail_if_called,
            on_grade=fail_if_called,
            on_complete_recovery=fail_if_called,
        )
    response = build_dynamic_tool_call_response(77, success=False, output=str(raised.value))
    receipt = _receipt(request, response)

    replayed, correlated, non_replayable = await replay._replay_routing_failures(
        [receipt], set(), "successor-node"
    )
    assert (replayed, correlated, non_replayable) == (1, 0, 0)

    tampered_response = build_dynamic_tool_call_response(
        77, success=False, output="tampered expected response"
    )
    with pytest.raises(replay.ReplayProbeError, match="routing response mismatch"):
        await replay._replay_routing_failures(
            [_receipt(request, tampered_response)], set(), "successor-node"
        )


@pytest.mark.asyncio
async def test_replay_blocks_uncorrelated_successful_controller_rejection() -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 78,
        "method": "item/tool/call",
        "params": {
            "tool": "construct_reliable_plan_region",
            "arguments": {"patch_id": "missing-evidence", "base_graph_position": 12},
        },
    }
    response = build_dynamic_tool_call_response(
        78,
        success=True,
        output="graph patch missing-evidence rejected: graph_patch_rejected",
    )
    with pytest.raises(replay.ReplayProbeError, match="uncorrelated controller rejection"):
        await replay._replay_routing_failures(
            [_receipt(request, response)], set(), "successor-node"
        )
