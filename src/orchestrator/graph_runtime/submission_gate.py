"""Authoritative, bounded validation gates for mutating graph submissions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from orchestrator.graph import GraphProjection, classify_write_worker_semantics, edges_view
from orchestrator.graph_runtime.errors import (
    InvalidExecutionContractError,
    SubmissionQualityGateError,
)
from orchestrator.runners import parse_health_check_command

SUBMISSION_GATE_OUTPUT_BYTES = 16 * 1024
SUBMISSION_GATE_TIMEOUT_SECONDS = 180.0
PROJECT_SUBMISSION_GATE_TIMEOUT_SECONDS = 600.0
SUBMISSION_GATE_WORKSPACE_SETUP_TIMEOUT_SECONDS = 15.0
SUBMISSION_GATE_WORKSPACE_CLEANUP_TIMEOUT_SECONDS = 15.0
SUBMISSION_GATE_MAX_COMMANDS = 8
SUBMISSION_GATE_MAX_COMMAND_CHARS = 8_192
SUBMISSION_GATE_MAX_FAILED_TEST_IDS = 64
SUBMISSION_GATE_DIAGNOSTIC_CHARS = 2_048


class SubmissionGateCommand(BaseModel):
    """One trusted command declared by the work or repository contract."""

    model_config = {"frozen": True}

    command: str = Field(min_length=1, max_length=SUBMISSION_GATE_MAX_COMMAND_CHARS)
    source: Literal[
        "node_acceptance_commands",
        "dynamic_feature_acceptance",
        "project_test_command",
    ]
    timeout_seconds: float = Field(default=SUBMISSION_GATE_TIMEOUT_SECONDS, gt=0, le=3600)


class SubmissionGateApplicability(BaseModel):
    """Typed immutable effect policy for one executable node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effect_contract: Literal["read_only_semantic", "effectful_write"]
    access_mode: Literal["read_only", "write"]
    semantic_stage: str | None = None
    execute_commands: bool
    legacy_normalized: bool = False


class _ProjectSubmissionGateConfig(BaseModel):
    """Relevant checked-in project gate fields; unrelated config stays opaque."""

    model_config = ConfigDict(extra="ignore", strict=True)

    test_command: str | None = None
    test_command_timeout_seconds: float = Field(
        default=PROJECT_SUBMISSION_GATE_TIMEOUT_SECONDS,
        gt=0,
        le=3600,
    )


class SubmissionGateCommandResult(BaseModel):
    """Bounded validation provenance for one executed command."""

    model_config = {"frozen": True}

    run_id: str
    node_id: str
    execution_id: str
    command: str
    command_sha256: str
    source: str
    timeout_seconds: float = Field(default=SUBMISSION_GATE_TIMEOUT_SECONDS, gt=0, le=3600)
    status: Literal["passed", "failed", "timeout"]
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    stdout_tail: str
    stderr_tail: str
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int = Field(ge=0)
    stderr_bytes: int = Field(ge=0)
    stdout_truncated: bool
    stderr_truncated: bool
    failure_category: (
        Literal["candidate_check_failure", "validation_environment_blockage"] | None
    ) = None
    failed_test_ids: tuple[str, ...] = ()
    failed_test_evidence: tuple[str, ...] = ()
    failed_test_ids_truncated: bool = False
    failure_identity_status: Literal["established", "unknown"] = "unknown"


class GateRejectionEvidence(BaseModel):
    """Bounded runner-facing evidence for one rejected gate command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    category: Literal["candidate_check_failure", "validation_environment_blockage"]
    command: str
    command_source: str
    command_sha256: str
    exit_code: int | None
    timed_out: bool
    failed_test_ids: tuple[str, ...] = ()
    failed_test_ids_truncated: bool = False
    final_diagnostic: str
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int = Field(ge=0)
    stderr_bytes: int = Field(ge=0)
    stdout_truncated: bool
    stderr_truncated: bool
    evidence_truncated: bool
    failure_identity_status: Literal["established", "unknown"]
    semantic_failure_fingerprint: str | None = None
    durable_audit_reference: str | None = None


class SubmissionGateReport(BaseModel):
    """Complete bounded result for the pre-staging quality gate."""

    model_config = {"frozen": True}

    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int = Field(ge=1)
    base_snapshot_id: str
    base_tree_sha: str
    candidate_tree_sha: str | None = None
    status: Literal["passed", "baseline_exempted", "no_configured_commands"]
    results: tuple[SubmissionGateCommandResult, ...] = ()
    baseline_failure_fingerprints: tuple[str, ...] = ()


class SubmissionGateBaseline(BaseModel):
    """Pre-run gate result bound to the exact durable baseline tree."""

    model_config = {"frozen": True}

    schema_version: Literal[1] = 1
    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int = Field(ge=1)
    base_snapshot_id: str
    base_tree_sha: str
    status: Literal["passed", "failed", "no_configured_commands"]
    results: tuple[SubmissionGateCommandResult, ...] = ()
    failure_fingerprints: tuple[str, ...] = ()


class SubmissionGateBoundaryIdentity(BaseModel):
    """Exact staged boundary validated after commands finish and before append."""

    model_config = {"frozen": True}

    snapshot_id: str
    snapshot_ref: str
    commit_sha: str
    tree_sha: str
    boundary_hash: str


class SubmissionValidationWitness(BaseModel):
    """Stage-ready immutable witness tying gate results to exact graph authority."""

    model_config = {"frozen": True}

    schema_version: Literal[1] = 1
    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int = Field(ge=1)
    base_snapshot_id: str
    disposition: Literal["passed", "baseline_exempted", "no_configured_commands"]
    commands: tuple[SubmissionGateCommandResult, ...]
    validated_boundary: SubmissionGateBoundaryIdentity
    baseline: SubmissionGateBaseline | None = None


@dataclass(frozen=True)
class ReadOnlyExecutionWorkspace:
    """A disposable exact-snapshot checkout and its isolated process state."""

    root: Path
    checkout: Path
    environment: dict[str, str]


async def prepare_read_only_execution_workspace(
    *,
    source_worktree: str | Path,
    snapshot_commit_sha: str,
    snapshot_tree_sha: str,
) -> ReadOnlyExecutionWorkspace:
    """Prepare a disposable exact-baseline checkout for a semantic runner."""
    return await _prepare_workspace_cancellation_safe(
        source_worktree=Path(source_worktree),
        commit_sha=snapshot_commit_sha,
        expected_tree_sha=snapshot_tree_sha,
        host_environment=None,
    )


async def cleanup_read_only_execution_workspace(
    *,
    source_worktree: str | Path,
    workspace: ReadOnlyExecutionWorkspace,
) -> None:
    """Remove a semantic runner checkout and drain cleanup under cancellation."""
    await _cleanup_workspace_cancellation_safe(Path(source_worktree), workspace)


def resolve_submission_gate_applicability(
    node_payload: Mapping[str, Any],
    *,
    node_id: str | None = None,
    graph_projection: GraphProjection | None = None,
) -> SubmissionGateApplicability:
    """Resolve a worker's gate authority from its immutable effect contract.

    The only legacy normalization is the exact contract already present in the
    live journal: a read-only semantic discovery worker. Missing or ambiguous
    legacy effect declarations remain invalid.
    """
    raw_access_mode = node_payload.get("access_mode")
    raw_stage = node_payload.get("semantic_stage")
    raw_effect_contract = node_payload.get("effect_contract")
    if raw_effect_contract is None:
        if raw_access_mode == "read_only" and raw_stage == "discovery":
            return SubmissionGateApplicability(
                effect_contract="read_only_semantic",
                access_mode="read_only",
                semantic_stage="discovery",
                execute_commands=False,
                legacy_normalized=True,
            )
        # Direct gate-library callers predating graph node contracts do not
        # carry a node identity at all. Preserve that narrow library seam;
        # every durable node_created worker contains kind and therefore cannot
        # use it to bypass the fail-closed contract.
        if "kind" not in node_payload and raw_access_mode is None and raw_stage is None:
            return SubmissionGateApplicability(
                effect_contract="effectful_write",
                access_mode="write",
                execute_commands=True,
                legacy_normalized=True,
            )
        raise InvalidExecutionContractError(
            "submission quality gate contract is invalid: worker effect_contract is missing"
        )
    try:
        applicability = SubmissionGateApplicability(
            effect_contract=raw_effect_contract,
            access_mode=cast(Any, raw_access_mode),
            semantic_stage=raw_stage,
            execute_commands=raw_effect_contract == "effectful_write",
        )
    except ValidationError as exc:
        raise InvalidExecutionContractError(
            "submission quality gate contract is invalid: malformed worker effect contract"
        ) from exc
    if applicability.effect_contract == "read_only_semantic" and (
        applicability.access_mode != "read_only"
        or applicability.semantic_stage not in {None, "discovery"}
    ):
        raise InvalidExecutionContractError(
            "submission quality gate contract is invalid: read_only_semantic requires "
            "access_mode=read_only outside effectful semantic stages"
        )
    if applicability.effect_contract == "effectful_write" and (
        applicability.access_mode != "write" or applicability.semantic_stage == "discovery"
    ):
        raise InvalidExecutionContractError(
            "submission quality gate contract is invalid: effectful_write requires "
            "access_mode=write outside semantic discovery"
        )
    if (
        graph_projection is not None
        and isinstance(node_id, str)
        and classify_write_worker_semantics(
            node_id,
            node_payload,
            graph_projection,
            edges=(edge.model_dump(mode="json") for edge in edges_view(graph_projection).values()),
        )
        == "invalid_declared_batch_write"
    ):
        raise InvalidExecutionContractError(
            "submission quality gate contract is invalid: implementation against a "
            "declared batch plan must use effectful_batch semantics"
        )
    return applicability


def resolve_submission_gate_commands(
    *,
    node_payload: Mapping[str, Any],
    dynamic_feature: Mapping[str, Any] | None,
    worktree_path: str | Path,
) -> tuple[SubmissionGateCommand, ...]:
    """Resolve authoritative commands without treating agent prose as evidence.

    Explicit node commands and the dynamic-feature acceptance command are work
    contract facts.  A checked-in ``.task-world/config.yaml`` contributes its
    configured project test command.  Missing config does not invent a gate for
    repositories that have not declared one; malformed config fails closed.
    """
    applicability = resolve_submission_gate_applicability(node_payload)
    if not applicability.execute_commands:
        return ()
    candidates: list[SubmissionGateCommand] = []
    node_timeout = _source_timeout(
        node_payload.get("acceptance_command_timeout_seconds"),
        field_name="acceptance_command_timeout_seconds",
        default=SUBMISSION_GATE_TIMEOUT_SECONDS,
    )
    raw_commands = node_payload.get("acceptance_commands")
    if raw_commands is not None:
        if not isinstance(raw_commands, (list, tuple)):
            raise SubmissionQualityGateError(
                "submission quality gate contract is invalid: acceptance_commands "
                "must be a sequence"
            )
        for raw_command in cast(list[Any] | tuple[Any, ...], raw_commands):
            candidates.append(
                SubmissionGateCommand(
                    command=_required_command(raw_command, "acceptance_commands"),
                    source="node_acceptance_commands",
                    timeout_seconds=node_timeout,
                )
            )

    if dynamic_feature is not None:
        dynamic_timeout = _source_timeout(
            dynamic_feature.get("acceptance_command_timeout_seconds"),
            field_name="dynamic_feature.acceptance_command_timeout_seconds",
            default=SUBMISSION_GATE_TIMEOUT_SECONDS,
        )
        raw_dynamic_command = dynamic_feature.get("acceptance_command")
        if isinstance(raw_dynamic_command, str) and raw_dynamic_command.strip():
            candidates.append(
                SubmissionGateCommand(
                    command=_required_command(
                        raw_dynamic_command,
                        "dynamic_feature.acceptance_command",
                    ),
                    source="dynamic_feature_acceptance",
                    timeout_seconds=dynamic_timeout,
                )
            )
        elif raw_dynamic_command is not None and not isinstance(raw_dynamic_command, str):
            raise SubmissionQualityGateError(
                "submission quality gate contract is invalid: "
                "dynamic_feature.acceptance_command must be a string"
            )

    config_path = Path(worktree_path) / ".task-world" / "config.yaml"
    if config_path.exists():
        try:
            config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise SubmissionQualityGateError(
                f"submission quality gate could not read {config_path}: {exc}"
            ) from exc
        if not isinstance(config_data, dict):
            raise SubmissionQualityGateError(
                "submission quality gate contract is invalid: "
                ".task-world/config.yaml must contain a YAML object"
            )
        try:
            project_config = _ProjectSubmissionGateConfig.model_validate(config_data)
        except ValidationError as exc:
            raise SubmissionQualityGateError(
                "submission quality gate contract is invalid: project test command/timeout"
            ) from exc
        project_command = parse_health_check_command(project_config.model_dump())
        if project_command is not None and project_command.strip():
            candidates.append(
                SubmissionGateCommand(
                    command=_required_command(project_command, "test_command"),
                    source="project_test_command",
                    timeout_seconds=project_config.test_command_timeout_seconds,
                )
            )

    deduplicated: list[SubmissionGateCommand] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.command in seen:
            continue
        seen.add(candidate.command)
        deduplicated.append(candidate)
    if len(deduplicated) > SUBMISSION_GATE_MAX_COMMANDS:
        raise SubmissionQualityGateError(
            "submission quality gate contract exceeds "
            f"the {SUBMISSION_GATE_MAX_COMMANDS}-command limit"
        )
    return tuple(deduplicated)


async def enforce_submission_quality_gate(
    *,
    run_id: str,
    node_id: str,
    execution_id: str,
    lease_id: str,
    lease_generation: int,
    base_snapshot_id: str,
    base_tree_sha: str = "",
    node_payload: Mapping[str, Any],
    dynamic_feature: Mapping[str, Any] | None,
    worktree_path: str | Path,
    baseline: SubmissionGateBaseline | None = None,
    candidate_tree_sha: str | None = None,
    snapshot_commit_sha: str | None = None,
    resolved_commands: tuple[SubmissionGateCommand, ...] | None = None,
    host_environment: Mapping[str, str] | None = None,
) -> SubmissionGateReport:
    """Run declared gates before staging and raise actionable failure feedback."""
    commands = resolved_commands
    if commands is None:
        commands = resolve_submission_gate_commands(
            node_payload=node_payload,
            dynamic_feature=dynamic_feature,
            worktree_path=worktree_path,
        )
    results: list[SubmissionGateCommandResult] = []
    exempted = False
    declared_exemptions = _declared_baseline_failure_exemptions(node_payload)
    baseline_fingerprints: set[str] = (
        set(baseline.failure_fingerprints).intersection(declared_exemptions)
        if baseline is not None
        and baseline.run_id == run_id
        and baseline.node_id == node_id
        and baseline.execution_id == execution_id
        and baseline.lease_id == lease_id
        and baseline.lease_generation == lease_generation
        and baseline.base_snapshot_id == base_snapshot_id
        and baseline.base_tree_sha == base_tree_sha
        else set[str]()
    )
    baseline_failure_identities = (
        {identity for identity in baseline.failure_fingerprints if identity}
        if baseline is not None
        and baseline.run_id == run_id
        and baseline.node_id == node_id
        and baseline.execution_id == execution_id
        and baseline.lease_id == lease_id
        and baseline.lease_generation == lease_generation
        and baseline.base_snapshot_id == base_snapshot_id
        and baseline.base_tree_sha == base_tree_sha
        else set[str]()
    )
    if commands:
        expected_tree_sha = candidate_tree_sha
        if snapshot_commit_sha is None or expected_tree_sha is None:
            raise SubmissionQualityGateError(
                "submission quality gate requires an exact candidate snapshot commit and tree"
            )
        workspace = await _prepare_workspace_cancellation_safe(
            source_worktree=Path(worktree_path),
            commit_sha=snapshot_commit_sha,
            expected_tree_sha=expected_tree_sha,
            host_environment=host_environment,
        )
        try:
            for command in commands:
                result = await _run_command(
                    run_id=run_id,
                    node_id=node_id,
                    execution_id=execution_id,
                    gate=command,
                    worktree_path=workspace.checkout,
                    environment=workspace.environment,
                )
                if result.status != "passed":
                    fingerprint = submission_gate_failure_fingerprint(result)
                    if (
                        result.source == "project_test_command"
                        and fingerprint is not None
                        and fingerprint in baseline_failure_identities
                        and not any(
                            evidence.startswith("MISSING:")
                            for evidence in result.failed_test_evidence
                        )
                    ):
                        result = result.model_copy(
                            update={"failure_category": "validation_environment_blockage"}
                        )
                    results.append(result)
                    # A killed command is an incomplete observation. Partial
                    # output identity is scheduling-dependent and can never
                    # authorize a baseline exemption.
                    if (
                        result.status == "failed"
                        and fingerprint is not None
                        and fingerprint in baseline_fingerprints
                    ):
                        exempted = True
                        continue
                    raise SubmissionQualityGateError(_failure_message(result), report=result)
                results.append(result)
        finally:
            await _cleanup_workspace_cancellation_safe(Path(worktree_path), workspace)
    return SubmissionGateReport(
        run_id=run_id,
        node_id=node_id,
        execution_id=execution_id,
        lease_id=lease_id,
        lease_generation=lease_generation,
        base_snapshot_id=base_snapshot_id,
        base_tree_sha=base_tree_sha,
        candidate_tree_sha=candidate_tree_sha,
        status=(
            "baseline_exempted" if exempted else "passed" if results else "no_configured_commands"
        ),
        results=tuple(results),
        baseline_failure_fingerprints=tuple(sorted(baseline_fingerprints)),
    )


async def capture_submission_gate_baseline(
    *,
    run_id: str,
    node_id: str,
    execution_id: str,
    lease_id: str,
    lease_generation: int,
    base_snapshot_id: str,
    base_tree_sha: str,
    node_payload: Mapping[str, Any],
    dynamic_feature: Mapping[str, Any] | None,
    worktree_path: str | Path,
    snapshot_commit_sha: str | None = None,
    resolved_commands: tuple[SubmissionGateCommand, ...] | None = None,
    host_environment: Mapping[str, str] | None = None,
) -> SubmissionGateBaseline:
    """Execute authoritative commands before the runner mutates the worktree."""
    commands = resolved_commands
    if commands is None:
        commands = resolve_submission_gate_commands(
            node_payload=node_payload,
            dynamic_feature=dynamic_feature,
            worktree_path=worktree_path,
        )
    results: tuple[SubmissionGateCommandResult, ...] = ()
    if commands:
        if snapshot_commit_sha is None:
            raise SubmissionQualityGateError(
                "submission quality gate requires an exact baseline snapshot commit and tree"
            )
        workspace = await _prepare_workspace_cancellation_safe(
            source_worktree=Path(worktree_path),
            commit_sha=snapshot_commit_sha,
            expected_tree_sha=base_tree_sha,
            host_environment=host_environment,
        )
        try:
            results = tuple(
                [
                    await _run_command(
                        run_id=run_id,
                        node_id=node_id,
                        execution_id=execution_id,
                        gate=command,
                        worktree_path=workspace.checkout,
                        environment=workspace.environment,
                    )
                    for command in commands
                ]
            )
        finally:
            await _cleanup_workspace_cancellation_safe(Path(worktree_path), workspace)
    failures = tuple(
        fingerprint
        for result in results
        if result.status != "passed"
        if (fingerprint := submission_gate_failure_fingerprint(result)) is not None
    )
    return SubmissionGateBaseline(
        run_id=run_id,
        node_id=node_id,
        execution_id=execution_id,
        lease_id=lease_id,
        lease_generation=lease_generation,
        base_snapshot_id=base_snapshot_id,
        base_tree_sha=base_tree_sha,
        status=(
            "failed"
            if any(result.status != "passed" for result in results)
            else "passed"
            if results
            else "no_configured_commands"
        ),
        results=results,
        failure_fingerprints=failures,
    )


def submission_gate_failure_fingerprint(result: SubmissionGateCommandResult) -> str | None:
    """Return semantic failure identity, separate from output-integrity hashes.

    A timeout is incomplete evidence. Likewise, an arbitrary command failure
    without parsed test evidence has no safe unchanged-failure comparison.
    """
    if result.status != "failed" or result.failure_identity_status != "established":
        return None
    payload = {
        "command_sha256": result.command_sha256,
        "source": result.source,
        "failed_test_evidence": sorted(result.failed_test_evidence),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def gate_rejection_evidence(result: SubmissionGateCommandResult) -> GateRejectionEvidence:
    """Build compact structured feedback while retaining full audit integrity."""
    diagnostic, diagnostic_truncated = _final_diagnostic(result)
    return GateRejectionEvidence(
        category=result.failure_category or "candidate_check_failure",
        command=result.command[:512],
        command_source=result.source,
        command_sha256=result.command_sha256,
        exit_code=result.exit_code,
        timed_out=result.status == "timeout",
        failed_test_ids=result.failed_test_ids,
        failed_test_ids_truncated=result.failed_test_ids_truncated,
        final_diagnostic=diagnostic,
        stdout_sha256=result.stdout_sha256,
        stderr_sha256=result.stderr_sha256,
        stdout_bytes=result.stdout_bytes,
        stderr_bytes=result.stderr_bytes,
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
        evidence_truncated=(
            diagnostic_truncated
            or result.stdout_truncated
            or result.stderr_truncated
            or result.failed_test_ids_truncated
            or len(result.command) > 512
        ),
        failure_identity_status=result.failure_identity_status,
        semantic_failure_fingerprint=submission_gate_failure_fingerprint(result),
    )


def submission_gate_commands_from_baseline(
    baseline: SubmissionGateBaseline,
) -> tuple[SubmissionGateCommand, ...]:
    """Reconstitute the exact command contract captured before runner work."""
    return tuple(
        SubmissionGateCommand(
            command=result.command,
            source=cast(Any, result.source),
            timeout_seconds=result.timeout_seconds,
        )
        for result in baseline.results
    )


def bind_submission_gate_witness(
    report: SubmissionGateReport,
    *,
    snapshot_id: str,
    snapshot_ref: str,
    commit_sha: str,
    tree_sha: str,
    boundary_hash: str,
    baseline: SubmissionGateBaseline | None = None,
) -> SubmissionValidationWitness:
    """Bind completed command provenance to the exact boundary being staged."""
    return SubmissionValidationWitness(
        run_id=report.run_id,
        node_id=report.node_id,
        execution_id=report.execution_id,
        lease_id=report.lease_id,
        lease_generation=report.lease_generation,
        base_snapshot_id=report.base_snapshot_id,
        disposition=report.status,
        commands=report.results,
        validated_boundary=SubmissionGateBoundaryIdentity(
            snapshot_id=snapshot_id,
            snapshot_ref=snapshot_ref,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            boundary_hash=boundary_hash,
        ),
        baseline=baseline,
    )


def _source_timeout(value: object, *, field_name: str, default: float) -> float:
    raw_timeout = value
    if raw_timeout is None:
        return default
    if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float)):
        raise SubmissionQualityGateError(
            f"submission quality gate contract is invalid: {field_name} must be numeric"
        )
    timeout = float(raw_timeout)
    if timeout <= 0 or timeout > 3600:
        raise SubmissionQualityGateError(
            "submission quality gate contract is invalid: "
            f"{field_name} must be greater than 0 and at most 3600"
        )
    return timeout


def _required_command(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SubmissionQualityGateError(
            f"submission quality gate contract is invalid: {field_name} "
            "must contain non-empty command strings"
        )
    return value.strip()


def _declared_baseline_failure_exemptions(
    node_payload: Mapping[str, Any],
) -> set[str]:
    """Read explicit, durable contract exemptions; agent prose never qualifies."""
    raw = node_payload.get("accepted_baseline_failure_fingerprints")
    if raw is None:
        return set()
    if not isinstance(raw, (list, tuple)):
        raise SubmissionQualityGateError(
            "submission quality gate contract is invalid: "
            "accepted_baseline_failure_fingerprints must be a sequence"
        )
    values = cast(list[Any] | tuple[Any, ...], raw)
    if len(values) > SUBMISSION_GATE_MAX_COMMANDS:
        raise SubmissionQualityGateError(
            "submission quality gate contract is invalid: too many accepted "
            "baseline failure fingerprints"
        )
    exemptions: set[str] = set()
    for value in values:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise SubmissionQualityGateError(
                "submission quality gate contract is invalid: accepted baseline "
                "failure fingerprints must be lowercase SHA-256 hex strings"
            )
        exemptions.add(value)
    return exemptions


async def _run_command(
    *,
    run_id: str,
    node_id: str,
    execution_id: str,
    gate: SubmissionGateCommand,
    worktree_path: Path,
    environment: Mapping[str, str],
) -> SubmissionGateCommandResult:
    started = perf_counter()
    proc = await _start_gate_process_cancellation_safe(
        gate.command,
        worktree_path=worktree_path,
        environment=environment,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    stdout_task = asyncio.create_task(_bounded_stream_tail(proc.stdout))
    stderr_task = asyncio.create_task(_bounded_stream_tail(proc.stderr))
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=gate.timeout_seconds)
    except TimeoutError:
        timed_out = True
        await _terminate_gate_process(proc, stdout_task, stderr_task)
    except asyncio.CancelledError:
        await _terminate_gate_process(proc, stdout_task, stderr_task)
        raise
    stdout_bytes, stdout_total, stdout_hash, stdout_truncated = await stdout_task
    stderr_bytes, stderr_total, stderr_hash, stderr_truncated = await stderr_task
    status: Literal["passed", "failed", "timeout"] = (
        "timeout" if timed_out else "passed" if proc.returncode == 0 else "failed"
    )
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    failed_test_ids, failed_test_evidence, failed_test_ids_truncated = _parse_failed_test_evidence(
        f"{stdout_text}\n{stderr_text}"
    )
    return SubmissionGateCommandResult(
        run_id=run_id,
        node_id=node_id,
        execution_id=execution_id,
        command=gate.command,
        command_sha256=hashlib.sha256(gate.command.encode("utf-8")).hexdigest(),
        source=gate.source,
        timeout_seconds=gate.timeout_seconds,
        status=status,
        exit_code=None if timed_out else proc.returncode,
        duration_ms=max(0, int((perf_counter() - started) * 1000)),
        stdout_tail=stdout_text,
        stderr_tail=stderr_text,
        stdout_sha256=stdout_hash,
        stderr_sha256=stderr_hash,
        stdout_bytes=stdout_total,
        stderr_bytes=stderr_total,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        failure_category="candidate_check_failure" if status != "passed" else None,
        failed_test_ids=failed_test_ids,
        failed_test_evidence=failed_test_evidence,
        failed_test_ids_truncated=failed_test_ids_truncated,
        failure_identity_status=(
            "established"
            if status == "failed" and failed_test_evidence and not failed_test_ids_truncated
            else "unknown"
        ),
    )


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PYTEST_SUMMARY = re.compile(r"^(FAILED|ERROR)\s+([^\s]+?)(?:\s+-|$)", re.MULTILINE)
_PYTEST_MISSING = re.compile(r"^ERROR:\s+file or directory not found:\s+(\S+)", re.MULTILINE)


def _parse_failed_test_evidence(
    output: str,
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    clean = _ANSI_ESCAPE.sub("", output)
    evidence = {f"{outcome}:{test_id}" for outcome, test_id in _PYTEST_SUMMARY.findall(clean)}
    evidence.update(f"MISSING:{path}" for path in _PYTEST_MISSING.findall(clean))
    ordered = sorted(evidence)
    bounded = tuple(ordered[:SUBMISSION_GATE_MAX_FAILED_TEST_IDS])
    identifiers = tuple(item.split(":", 1)[1] for item in bounded)
    return identifiers, bounded, len(ordered) > len(bounded)


def _final_diagnostic(result: SubmissionGateCommandResult) -> tuple[str, bool]:
    combined = "\n".join(
        value.strip() for value in (result.stdout_tail, result.stderr_tail) if value.strip()
    )
    if len(combined) <= SUBMISSION_GATE_DIAGNOSTIC_CHARS:
        return combined, False
    return combined[-SUBMISSION_GATE_DIAGNOSTIC_CHARS:], True


async def _start_gate_process_cancellation_safe(
    command: str,
    *,
    worktree_path: Path,
    environment: Mapping[str, str],
) -> asyncio.subprocess.Process:
    process_environment = dict(environment)
    protected_environment = process_environment.pop(
        "ORCHESTRATOR_GATE_READ_ONLY_DEPENDENCY_ENVIRONMENT",
        None,
    )
    argv = ["/bin/sh", "-c", command]
    if protected_environment is not None and sys.platform == "darwin":
        profile = "\n".join(
            (
                "(version 1)",
                "(allow default)",
                f"(deny file-write* (subpath {json.dumps(protected_environment)}))",
            )
        )
        argv = ["/usr/bin/sandbox-exec", "-p", profile, *argv]
    start_task = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *argv,
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=process_environment,
        )
    )
    try:
        return await asyncio.shield(start_task)
    except asyncio.CancelledError:
        proc = await start_task
        assert proc.stdout is not None
        assert proc.stderr is not None
        await _terminate_gate_process(
            proc,
            asyncio.create_task(_bounded_stream_tail(proc.stdout)),
            asyncio.create_task(_bounded_stream_tail(proc.stderr)),
        )
        raise


async def _terminate_gate_process(
    proc: asyncio.subprocess.Process,
    stdout_task: asyncio.Task[tuple[bytes, int, str, bool]],
    stderr_task: asyncio.Task[tuple[bytes, int, str, bool]],
) -> None:
    """Terminate an exact gate process group and drain it before returning."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    wait_task = asyncio.create_task(proc.wait())
    try:
        await asyncio.shield(wait_task)
    except asyncio.CancelledError:
        await wait_task
    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


async def _prepare_workspace_cancellation_safe(
    *,
    source_worktree: Path,
    commit_sha: str,
    expected_tree_sha: str,
    host_environment: Mapping[str, str] | None,
) -> ReadOnlyExecutionWorkspace:
    task = asyncio.create_task(
        asyncio.to_thread(
            _prepare_submission_gate_workspace,
            source_worktree,
            commit_sha,
            expected_tree_sha,
            host_environment,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        workspace = await task
        await _cleanup_workspace_cancellation_safe(source_worktree, workspace)
        raise


async def _cleanup_workspace_cancellation_safe(
    source_worktree: Path,
    workspace: ReadOnlyExecutionWorkspace,
) -> None:
    task = asyncio.create_task(
        asyncio.to_thread(_cleanup_submission_gate_workspace, source_worktree, workspace)
    )
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def _prepare_submission_gate_workspace(
    source_worktree: Path,
    commit_sha: str,
    expected_tree_sha: str,
    host_environment: Mapping[str, str] | None,
) -> ReadOnlyExecutionWorkspace:
    deadline = perf_counter() + SUBMISSION_GATE_WORKSPACE_SETUP_TIMEOUT_SECONDS
    if not _is_git_oid(commit_sha) or not _is_git_oid(expected_tree_sha):
        raise SubmissionQualityGateError(
            "submission quality gate snapshot commit/tree identity is invalid"
        )
    actual_tree = _run_gate_git(
        source_worktree,
        ["rev-parse", "--verify", f"{commit_sha}^{{tree}}"],
        deadline=deadline,
    ).stdout.strip()
    if actual_tree != expected_tree_sha:
        raise SubmissionQualityGateError(
            "submission quality gate snapshot commit does not match the expected tree"
        )

    root = Path(tempfile.mkdtemp(prefix="orchestrator-submission-gate-"))
    checkout = root / "snapshot"
    runtime = root / "runtime"
    try:
        result = _run_gate_git(
            source_worktree,
            ["worktree", "add", "--detach", str(checkout), commit_sha],
            check=False,
            deadline=deadline,
        )
        if result.returncode != 0:
            raise SubmissionQualityGateError(
                "submission quality gate could not create its exact snapshot workspace: "
                f"{result.stderr.strip()}"
            )
        environment = _isolated_gate_environment(
            runtime,
            checkout=checkout,
            source_worktree=source_worktree,
            host_environment=host_environment,
        )
        if perf_counter() > deadline:
            raise SubmissionQualityGateError(
                "submission quality gate workspace setup exceeded its strict "
                f"{SUBMISSION_GATE_WORKSPACE_SETUP_TIMEOUT_SECONDS:g}-second limit"
            )
        return ReadOnlyExecutionWorkspace(
            root=root,
            checkout=checkout,
            environment=environment,
        )
    except BaseException:
        workspace = ReadOnlyExecutionWorkspace(root=root, checkout=checkout, environment={})
        _cleanup_submission_gate_workspace(source_worktree, workspace)
        raise


def _isolated_gate_environment(
    runtime: Path,
    *,
    checkout: Path,
    source_worktree: Path,
    host_environment: Mapping[str, str] | None,
) -> dict[str, str]:
    source = os.environ if host_environment is None else host_environment
    # Repository gates routinely depend on caller-supplied feature flags,
    # credentials, service endpoints, and envfile values.  Preserve those
    # inputs while taking ownership of every variable that can redirect the
    # shell, Python, Git, package managers, caches, journals, or writable
    # runtime state back into the leased runner worktree.
    environment = {
        key: value
        for key, value in source.items()
        if not _gate_environment_key_is_process_controlled(key)
    }
    reusable_environment = _reusable_active_gate_environment(checkout)
    virtual_environment = reusable_environment or runtime / "venv"
    directories = {
        "HOME": runtime / "home",
        "TMPDIR": runtime / "tmp",
        "TMP": runtime / "tmp",
        "TEMP": runtime / "tmp",
        "XDG_CACHE_HOME": runtime / "cache",
        "XDG_CONFIG_HOME": runtime / "config",
        "XDG_DATA_HOME": runtime / "data",
        "XDG_STATE_HOME": runtime / "state",
        "UV_CACHE_DIR": runtime / "cache" / "uv",
        "UV_PROJECT_ENVIRONMENT": virtual_environment,
        "VIRTUAL_ENV": virtual_environment,
        "PIP_CACHE_DIR": runtime / "cache" / "pip",
        "NPM_CONFIG_CACHE": runtime / "cache" / "npm",
        "PRE_COMMIT_HOME": runtime / "cache" / "pre-commit",
        "RUFF_CACHE_DIR": runtime / "cache" / "ruff",
        "PYTHONPYCACHEPREFIX": runtime / "cache" / "pycache",
    }
    for path in set(directories.values()) - {virtual_environment}:
        path.mkdir(parents=True, exist_ok=True)
    if reusable_environment is None:
        _create_lightweight_gate_virtual_environment(virtual_environment)
    environment.update({key: str(value) for key, value in directories.items()})
    environment.update(
        {
            "COVERAGE_FILE": str(runtime / "state" / ".coverage"),
            "PATH": _safe_gate_path(
                virtual_environment / "bin",
                source_worktree=source_worktree,
                checkout=checkout,
            ),
            "PYTHONPATH": os.pathsep.join((str(checkout / "src"), str(checkout))),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_ADDOPTS": "",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "NPM_CONFIG_USERCONFIG": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    )
    if reusable_environment is not None:
        environment.update(
            {
                "ORCHESTRATOR_GATE_READ_ONLY_DEPENDENCY_ENVIRONMENT": str(reusable_environment),
                "UV_NO_SYNC": "1",
            }
        )
    return environment


def _gate_environment_key_is_process_controlled(key: str) -> bool:
    upper = key.upper()
    if upper in {
        "BASH_ENV",
        "CDPATH",
        "ENV",
        "HOME",
        "PATH",
        "SHELL",
        "TMP",
        "TEMP",
        "TMPDIR",
        "VIRTUAL_ENV",
        "VIRTUAL_ENV_PROMPT",
        "ZDOTDIR",
    }:
        return True
    return (
        upper.startswith(
            (
                "COVERAGE_",
                "DYLD_",
                "GIT_",
                "LD_",
                "NPM_",
                "PIP_",
                "PRE_COMMIT_",
                "PYTEST_",
                "PYTHON",
                "RUFF_",
                "UV_",
                "XDG_",
            )
        )
        or upper == "ORCHESTRATOR_EVENT_JOURNAL_PATH"
    )


def _reusable_active_gate_environment(checkout: Path) -> Path | None:
    """Return the active env only for an exact matching locked project.

    The environment is exposed read-only by the process sandbox. A different
    project or lock falls back to a unique writable venv so UV can resolve its
    own dependencies without contaminating the active environment.
    """
    if sys.platform != "darwin":
        return None
    active = Path(sys.prefix).resolve()
    if active == Path(sys.base_prefix).resolve() or not (active / "pyvenv.cfg").is_file():
        return None
    active_project = active.parent
    for filename in ("pyproject.toml", "uv.lock"):
        checkout_contract = checkout / filename
        active_contract = active_project / filename
        try:
            if checkout_contract.read_bytes() != active_contract.read_bytes():
                return None
        except OSError:
            return None
    return active


def _create_lightweight_gate_virtual_environment(target: Path) -> None:
    """Create a minimal writable launcher environment for dependency fallback."""
    bin_dir = target / ("Scripts" if os.name == "nt" else "bin")
    version_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
    packages = target / (
        "Lib/site-packages" if os.name == "nt" else f"lib/{version_dir}/site-packages"
    )
    bin_dir.mkdir(parents=True, exist_ok=True)
    packages.mkdir(parents=True, exist_ok=True)
    (target / "pyvenv.cfg").write_text(
        f"home = {Path(sys.executable).resolve().parent}\n"
        "include-system-site-packages = false\n"
        f"version = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n",
        encoding="utf-8",
    )
    for name in ("python", "python3", f"python{sys.version_info.major}.{sys.version_info.minor}"):
        destination = bin_dir / name
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        destination.symlink_to(Path(sys.executable).resolve())


def _safe_gate_path(
    virtual_environment_bin: Path,
    *,
    source_worktree: Path,
    checkout: Path,
) -> str:
    """Return deterministic launch paths with no project-relative executable dirs."""
    candidates = [
        virtual_environment_bin,
        Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin"),
        Path("/opt/homebrew/bin"),
        Path("/opt/homebrew/sbin"),
        Path("/usr/local/bin"),
        Path("/usr/local/sbin"),
        Path("/usr/bin"),
        Path("/usr/sbin"),
        Path("/bin"),
        Path("/sbin"),
    ]
    forbidden = (source_worktree.resolve(), checkout.resolve())
    retained: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_dir() or any(resolved.is_relative_to(root) for root in forbidden):
            continue
        rendered = str(resolved)
        if rendered not in retained:
            retained.append(rendered)
    return os.pathsep.join(retained)


def _cleanup_submission_gate_workspace(
    source_worktree: Path,
    workspace: ReadOnlyExecutionWorkspace,
) -> None:
    removal_error = ""
    deadline = perf_counter() + SUBMISSION_GATE_WORKSPACE_CLEANUP_TIMEOUT_SECONDS
    if workspace.checkout.exists():
        result = _run_gate_git(
            source_worktree,
            ["worktree", "remove", "--force", str(workspace.checkout)],
            check=False,
            deadline=deadline,
        )
        if result.returncode != 0:
            # A gate can invoke `git worktree lock`; unlock only this exact
            # disposable checkout and retry the supported removal. Never prune
            # unrelated repository registrations.
            _run_gate_git(
                source_worktree,
                ["worktree", "unlock", str(workspace.checkout)],
                check=False,
                deadline=deadline,
            )
            retry = _run_gate_git(
                source_worktree,
                ["worktree", "remove", "--force", str(workspace.checkout)],
                check=False,
                deadline=deadline,
            )
            if retry.returncode != 0:
                removal_error = retry.stderr.strip() or result.stderr.strip()
    registered = _gate_worktree_is_registered(
        source_worktree,
        workspace.checkout,
        deadline=deadline,
    )
    if not registered:
        shutil.rmtree(workspace.root, ignore_errors=True)
    if workspace.root.exists() or removal_error or registered:
        detail = removal_error or f"could not remove {workspace.root}"
        if registered:
            detail = f"Git still registers disposable checkout {workspace.checkout}"
        raise SubmissionQualityGateError(
            f"submission quality gate workspace cleanup failed: {detail}"
        )


def _gate_worktree_is_registered(
    source_worktree: Path,
    checkout: Path,
    *,
    deadline: float,
) -> bool:
    result = _run_gate_git(
        source_worktree,
        ["worktree", "list", "--porcelain"],
        check=False,
        deadline=deadline,
    )
    if result.returncode != 0:
        raise SubmissionQualityGateError(
            f"submission quality gate could not verify workspace cleanup: {result.stderr.strip()}"
        )
    expected = checkout.resolve()
    return any(
        line.startswith("worktree ") and Path(line.removeprefix("worktree ")).resolve() == expected
        for line in result.stdout.splitlines()
    )


def _run_gate_git(
    source_worktree: Path,
    args: list[str],
    *,
    check: bool = True,
    deadline: float | None = None,
) -> subprocess.CompletedProcess[str]:
    timeout = 30.0 if deadline is None else deadline - perf_counter()
    if timeout <= 0:
        raise SubmissionQualityGateError(
            "submission quality gate snapshot workspace operation timed out"
        )
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=source_worktree,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={
                "PATH": _safe_host_executable_path(),
                "HOME": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise SubmissionQualityGateError(
            "submission quality gate snapshot workspace operation timed out"
        ) from exc
    if check and result.returncode != 0:
        raise SubmissionQualityGateError(
            f"submission quality gate snapshot Git operation failed: {result.stderr.strip()}"
        )
    return result


def _safe_host_executable_path() -> str:
    candidates = (
        Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin"),
        Path("/opt/homebrew/bin"),
        Path("/opt/homebrew/sbin"),
        Path("/usr/local/bin"),
        Path("/usr/local/sbin"),
        Path("/usr/bin"),
        Path("/usr/sbin"),
        Path("/bin"),
        Path("/sbin"),
    )
    retained: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        rendered = str(resolved)
        if resolved.is_dir() and rendered not in retained:
            retained.append(rendered)
    return os.pathsep.join(retained)


def _is_git_oid(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


async def _bounded_stream_tail(
    stream: asyncio.StreamReader,
) -> tuple[bytes, int, str, bool]:
    tail = bytearray()
    total = 0
    digest = hashlib.sha256()
    while chunk := await stream.read(8192):
        total += len(chunk)
        digest.update(chunk)
        tail.extend(chunk)
        if len(tail) > SUBMISSION_GATE_OUTPUT_BYTES:
            del tail[: len(tail) - SUBMISSION_GATE_OUTPUT_BYTES]
    return bytes(tail), total, digest.hexdigest(), total > SUBMISSION_GATE_OUTPUT_BYTES


def _failure_message(result: SubmissionGateCommandResult) -> str:
    outcome = (
        "timed out after the configured limit"
        if result.status == "timeout"
        else f"failed with exit code {result.exit_code}"
    )
    output = (result.stdout_tail + "\n" + result.stderr_tail).strip()
    suffix = f"\nBounded output tail:\n{output}" if output else ""
    return (
        f"submission quality gate {outcome}; source={result.source}; "
        f"command={result.command!r}. Correct the failure and submit again in this session."
        f"{suffix}"
    )


__all__ = [
    "SUBMISSION_GATE_MAX_COMMANDS",
    "SUBMISSION_GATE_OUTPUT_BYTES",
    "SUBMISSION_GATE_TIMEOUT_SECONDS",
    "PROJECT_SUBMISSION_GATE_TIMEOUT_SECONDS",
    "GateRejectionEvidence",
    "ReadOnlyExecutionWorkspace",
    "SubmissionGateApplicability",
    "SubmissionGateCommand",
    "SubmissionGateCommandResult",
    "SubmissionGateBoundaryIdentity",
    "SubmissionGateBaseline",
    "SubmissionGateReport",
    "SubmissionValidationWitness",
    "bind_submission_gate_witness",
    "capture_submission_gate_baseline",
    "cleanup_read_only_execution_workspace",
    "enforce_submission_quality_gate",
    "gate_rejection_evidence",
    "resolve_submission_gate_commands",
    "resolve_submission_gate_applicability",
    "prepare_read_only_execution_workspace",
    "submission_gate_commands_from_baseline",
    "submission_gate_failure_fingerprint",
]
