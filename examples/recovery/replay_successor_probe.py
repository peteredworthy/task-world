"""Replay a completed successor probe without starting a model or live service."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from orchestrator.artifacts import FilesystemArtifactStore, StoredArtifactRef
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import FakeClock, ReliablePlanContractIdentity, SequentialIdGenerator
from orchestrator.graph_runtime import (
    RejectionEvidenceArtifact,
    capture_source_identity,
    replay_reliable_plan_rejection,
    resolve_orchestrator_source_root,
)
from orchestrator.runners import (
    CodexDynamicToolReceipt,
    build_dynamic_tool_call_response,
    route_tool_call,
)


class ReplayProbeError(RuntimeError):
    """Safe replay failure; callers must not print underlying evidence."""


class ReplaySummary(BaseModel):
    """Safe counts and hashes emitted by the replay CLI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    status: Literal["passed", "blocked", "error"]
    source_result_status: Literal["passed", "failed", "incomplete", "error"]
    source_probe_passed: bool
    result_sha256: str
    source_identity_verified: bool
    cas_artifact_count: int
    rejection_count: int
    replayed_rejection_count: int
    dynamic_receipt_count: int
    routing_replay_count: int
    controller_correlated_count: int
    non_replayable_count: int


class ReplayInput(BaseModel):
    """The successor result fields required for an offline replay."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["passed", "failed", "incomplete", "error"]
    qualification_contract_identity: ReliablePlanContractIdentity | None = None
    orchestrator_source_identity: dict[str, Any]
    harness_sha256: str
    lifecycle_helper_sha256: str
    routine_sha256: str
    fixture_commit: str
    fixture_tree: str
    spec_sha256: str
    oracle_sha256: str
    artifact_root: str
    successor_node_id: str
    successor_prompt_sha256: str
    successor_authority: dict[str, Any]
    rejection_evidence: list[dict[str, Any]]
    dynamic_tool_receipts: list[dict[str, Any]]
    protected_context_ref: dict[str, Any]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _ref(value: object) -> StoredArtifactRef:
    if not isinstance(value, dict):
        raise ReplayProbeError("artifact reference is not an object")
    try:
        return StoredArtifactRef.model_validate(value)
    except ValidationError as exc:
        raise ReplayProbeError("artifact reference is invalid") from exc


async def _require_hashes(result: ReplayInput, source_root: Path) -> None:
    """Reject any result whose source identity differs from this checkout."""
    expected_identity = result.orchestrator_source_identity
    if not expected_identity.get("complete"):
        raise ReplayProbeError("recorded source identity is incomplete")
    observed = await capture_source_identity(source_root)
    if observed.model_dump(mode="json") != expected_identity:
        raise ReplayProbeError("current source identity differs")
    paths = {
        "harness_sha256": Path(__file__).with_name("successor_planner_probe.py"),
        "lifecycle_helper_sha256": source_root / "examples/recovery/deterministic_lifecycle.py",
        "routine_sha256": source_root / "routines/dynamic-graph-feature/routine.yaml",
    }
    for field, path in paths.items():
        if not path.is_file() or _sha256_file(path) != getattr(result, field):
            raise ReplayProbeError("recorded source hash differs")


async def _load_artifact(store: FilesystemArtifactStore, value: object) -> bytes:
    try:
        return await store.read(_ref(value))
    except Exception as exc:
        raise ReplayProbeError("artifact CAS validation failed") from exc


async def _replay_rejections(
    store: FilesystemArtifactStore,
    result: ReplayInput,
    source_root: Path,
) -> tuple[int, set[tuple[str, str, str]]]:
    replayed = 0
    controller_pairs: set[tuple[str, str, str]] = set()
    with tempfile.TemporaryDirectory(prefix="successor-replay-") as raw_dir:
        root = Path(raw_dir)
        for index, evidence in enumerate(result.rejection_evidence):
            if evidence.get("replayable") is not True:
                raise ReplayProbeError("rejection evidence is non-replayable")
            if evidence.get("classification") != "exact_replay":
                raise ReplayProbeError("rejection evidence is not exact")
            ref = evidence.get("artifact_ref")
            artifact_bytes = await _load_artifact(store, ref)
            try:
                artifact = RejectionEvidenceArtifact.model_validate_json(artifact_bytes)
            except ValidationError as exc:
                raise ReplayProbeError("rejection evidence artifact is invalid") from exc
            if artifact.request is None or artifact.response is None:
                raise ReplayProbeError("rejection evidence artifact is incomplete")
            patch_id = artifact.request.get("patch_id")
            base_position = artifact.request.get("base_graph_position")
            if (
                not isinstance(patch_id, str)
                or not isinstance(base_position, int)
                or artifact.proposed_by_node_id != result.successor_node_id
            ):
                raise ReplayProbeError("rejection evidence has no patch identity")
            controller_request = _canonical_json(artifact.request).decode("utf-8")
            controller_pairs.add(
                (controller_request, artifact.response, artifact.proposed_by_node_id)
            )
            engine = create_engine(root / f"rejection-{index}.db")
            await init_db(engine)
            try:
                await replay_reliable_plan_rejection(
                    artifact_store=store,
                    evidence_ref=_ref(ref),
                    isolated_session_factory=create_session_factory(engine),
                    clock=FakeClock(),
                    id_gen=SequentialIdGenerator(),
                    worktree_path=source_root,
                )
            except Exception as exc:
                raise ReplayProbeError("controller rejection replay failed") from exc
            finally:
                await engine.dispose()
            replayed += 1
    return replayed, controller_pairs


def _receipt_payload(receipt: CodexDynamicToolReceipt) -> tuple[dict[str, Any], dict[str, Any]]:
    if not receipt.request_response_complete or receipt.request is None or receipt.response is None:
        raise ReplayProbeError("dynamic tool receipt is incomplete")
    request_bytes = receipt.request.encode("utf-8")
    response_bytes = receipt.response.encode("utf-8")
    if (
        receipt.request_size_bytes != len(request_bytes)
        or receipt.response_size_bytes != len(response_bytes)
        or receipt.request_sha256 != f"sha256:{_sha256_bytes(request_bytes)}"
        or receipt.response_sha256 != f"sha256:{_sha256_bytes(response_bytes)}"
    ):
        raise ReplayProbeError("dynamic tool receipt integrity failed")
    try:
        request_raw: object = json.loads(receipt.request)
        response_raw: object = json.loads(receipt.response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReplayProbeError("dynamic tool receipt JSON is invalid") from exc
    if not isinstance(request_raw, dict) or not isinstance(response_raw, dict):
        raise ReplayProbeError("dynamic tool receipt envelope is invalid")
    request = cast(dict[str, Any], request_raw)
    response = cast(dict[str, Any], response_raw)
    if (
        not isinstance(request.get("id"), int)
        or isinstance(request.get("id"), bool)
        or not isinstance(response.get("id"), int)
        or isinstance(response.get("id"), bool)
        or request.get("id") != receipt.request_id
        or response.get("id") != receipt.request_id
    ):
        raise ReplayProbeError("dynamic tool request and response ids differ")
    return request, response


async def _replay_routing_failures(
    receipts: list[CodexDynamicToolReceipt],
    controller_pairs: set[tuple[str, str, str]],
    successor_node_id: str,
) -> tuple[int, int, int]:
    routing_replayed = 0
    controller_correlated = 0
    non_replayable = 0
    for receipt in receipts:
        request, response = _receipt_payload(receipt)
        params_raw: object = request.get("params")
        result_payload_raw: object = response.get("result")
        params = cast(dict[str, Any], params_raw) if isinstance(params_raw, dict) else None
        result_payload = (
            cast(dict[str, Any], result_payload_raw)
            if isinstance(result_payload_raw, dict)
            else None
        )
        if not isinstance(params, dict) or not isinstance(result_payload, dict):
            raise ReplayProbeError("dynamic tool receipt envelope is invalid")
        tool_name: object = params.get("tool")
        arguments_raw: object = params.get("arguments")
        success = result_payload.get("success")
        if (
            request.get("method") != "item/tool/call"
            or not isinstance(tool_name, str)
            or not isinstance(arguments_raw, dict)
            or not isinstance(success, bool)
        ):
            raise ReplayProbeError("dynamic tool arguments are not replayable")
        arguments = cast(dict[str, Any], arguments_raw)
        patch_id = arguments.get("patch_id")
        response_items_raw: object = result_payload.get("contentItems")
        response_items = (
            cast(list[Any], response_items_raw) if isinstance(response_items_raw, list) else []
        )
        response_text = (
            cast(dict[str, Any], response_items[0]).get("text")
            if response_items and isinstance(response_items[0], dict)
            else None
        )
        normalized_request: str | None = None
        if tool_name == "construct_reliable_plan_region":
            if isinstance(patch_id, str) and isinstance(arguments.get("base_graph_position"), int):
                macro_args = {
                    key: value
                    for key, value in arguments.items()
                    if key not in {"patch_id", "base_graph_position", "rationale_record_id"}
                }
                normalized = {
                    "patch_id": patch_id,
                    "base_graph_position": arguments["base_graph_position"],
                    "macro_invocations": [{"macro": tool_name, "args": macro_args}],
                }
                rationale_record_id = arguments.get("rationale_record_id")
                if isinstance(rationale_record_id, str):
                    normalized["rationale_record_id"] = rationale_record_id
                normalized_request = _canonical_json(normalized).decode("utf-8")
        if (
            normalized_request is not None
            and isinstance(response_text, str)
            and (normalized_request, response_text, successor_node_id) in controller_pairs
        ):
            # Controller rejection responses can carry JSON-RPC success=True;
            # the matching durable rejection artifact is the authority here.
            controller_correlated += 1
            continue
        if success is True:
            if tool_name == "construct_reliable_plan_region" and normalized_request is None:
                raise ReplayProbeError("dynamic tool request is not normalizable")
            if (
                tool_name == "construct_reliable_plan_region"
                and isinstance(response_text, str)
                and (
                    "graph_patch_rejected" in response_text
                    or ("graph patch " in response_text and " rejected:" in response_text)
                )
            ):
                raise ReplayProbeError("uncorrelated controller rejection")
            continue
        if tool_name != "construct_reliable_plan_region":
            # A submit failure depends on the original mutable graph context.
            # Never replay it as a standalone routing failure.
            non_replayable += 1
            continue
        request_id = request.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            raise ReplayProbeError("dynamic tool request id is not replayable")

        async def fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
            raise ReplayProbeError("routing replay crossed the controller boundary")

        try:
            await route_tool_call(
                tool_name,
                arguments,
                fail_if_called,
                fail_if_called,
                on_submit_graph_patch=fail_if_called,
                on_grade=fail_if_called,
                on_complete_recovery=fail_if_called,
                agent_label="replay_successor_probe",
            )
        except ValueError as exc:
            prepared = build_dynamic_tool_call_response(
                request_id,
                success=False,
                output=str(exc),
            )
            if _canonical_json(prepared) != _canonical_json(response):
                raise ReplayProbeError("routing response mismatch")
        else:
            raise ReplayProbeError("routing failure did not reproduce")
        routing_replayed += 1
    return routing_replayed, controller_correlated, non_replayable


async def replay_result(result_path: Path) -> ReplaySummary:
    """Validate and replay one result JSON in disposable state."""
    result_bytes = result_path.read_bytes()
    try:
        result = ReplayInput.model_validate_json(result_bytes)
    except ValidationError as exc:
        raise ReplayProbeError("probe result schema is invalid") from exc
    if result.status == "error":
        raise ReplayProbeError("probe result is an error result")
    source_root = resolve_orchestrator_source_root()
    await _require_hashes(result, source_root)
    artifact_root = Path(result.artifact_root).resolve(strict=True)
    if not artifact_root.is_dir():
        raise ReplayProbeError("artifact root is not a directory")
    store = FilesystemArtifactStore(artifact_root)

    protected = await _load_artifact(store, result.protected_context_ref)
    try:
        protected_context = json.loads(protected)
    except json.JSONDecodeError as exc:
        raise ReplayProbeError("protected context is invalid") from exc
    if not isinstance(protected_context, dict):
        raise ReplayProbeError("protected context is invalid")
    protected_mapping = cast(dict[str, Any], protected_context)
    protected_fields = {
        "source_identity": result.orchestrator_source_identity,
        "harness_sha256": result.harness_sha256,
        "lifecycle_helper_sha256": result.lifecycle_helper_sha256,
        "routine_sha256": result.routine_sha256,
        "fixture_commit": result.fixture_commit,
        "fixture_tree": result.fixture_tree,
        "spec_sha256": result.spec_sha256,
        "oracle_sha256": result.oracle_sha256,
        "successor_node_id": result.successor_node_id,
    }
    if result.qualification_contract_identity is not None:
        protected_fields["qualification_contract_identity"] = (
            result.qualification_contract_identity.model_dump(mode="json")
        )
    if any(protected_mapping.get(key) != value for key, value in protected_fields.items()):
        raise ReplayProbeError("protected context identity differs")
    protected_prompt = protected_mapping.get("successor_prompt")
    if (
        not isinstance(protected_prompt, str)
        or _sha256_bytes(protected_prompt.encode("utf-8")) != result.successor_prompt_sha256
    ):
        raise ReplayProbeError("protected successor prompt differs")
    protected_payload = protected_mapping.get("successor_node_payload")
    authority_keys = (
        "semantic_stage",
        "planning_horizon",
        "reliable_plan_remaining_horizons",
        "reliable_plan_skeleton_id",
        "reliable_plan_assignment_role",
        "reliable_plan_selected_runner_type",
    )
    if not isinstance(protected_payload, dict):
        raise ReplayProbeError("protected successor authority differs")
    protected_payload_mapping = cast(dict[str, Any], protected_payload)
    if {
        key: protected_payload_mapping.get(key) for key in authority_keys
    } != result.successor_authority:
        raise ReplayProbeError("protected successor authority differs")
    protected_refs: object = protected_mapping.get("dynamic_tool_receipt_refs")
    if protected_refs != [item.get("artifact_ref") for item in result.dynamic_tool_receipts]:
        raise ReplayProbeError("dynamic receipt references do not match context")
    if not result.dynamic_tool_receipts:
        raise ReplayProbeError("dynamic tool receipts are missing")

    receipts: list[CodexDynamicToolReceipt] = []
    for item in result.dynamic_tool_receipts:
        content = await _load_artifact(store, item.get("artifact_ref"))
        try:
            receipt = CodexDynamicToolReceipt.model_validate_json(content)
        except ValidationError as exc:
            raise ReplayProbeError("dynamic receipt artifact is invalid") from exc
        safe = receipt.model_dump(mode="json", exclude={"request", "response"})
        if safe != {key: value for key, value in item.items() if key != "artifact_ref"}:
            raise ReplayProbeError("dynamic receipt metadata mismatch")
        receipts.append(receipt)

    replayed, controller_pairs = await _replay_rejections(store, result, source_root)
    routing, correlated, non_replayable = await _replay_routing_failures(
        receipts, controller_pairs, result.successor_node_id
    )
    status: Literal["passed", "blocked"] = (
        "passed"
        if (
            replayed == len(result.rejection_evidence)
            and correlated == len(result.rejection_evidence)
            and non_replayable == 0
        )
        else "blocked"
    )
    return ReplaySummary(
        status=status,
        source_result_status=result.status,
        source_probe_passed=result.status == "passed",
        result_sha256=_sha256_bytes(result_bytes),
        source_identity_verified=True,
        cas_artifact_count=1 + len(result.rejection_evidence) + len(receipts),
        rejection_count=len(result.rejection_evidence),
        replayed_rejection_count=replayed,
        dynamic_receipt_count=len(receipts),
        routing_replay_count=routing,
        controller_correlated_count=correlated,
        non_replayable_count=non_replayable,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json", type=Path)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(replay_result(args.result_json))
    except Exception as exc:
        # The CLI is intentionally safe to use in public logs: no exception
        # text can contain request/response payloads.
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        return 2
    print(summary.model_dump_json())
    return 0 if summary.status == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
