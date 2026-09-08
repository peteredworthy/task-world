"""Outbox-to-agent bridge for graph runtime dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
import logging
import psutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol, cast

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from pydantic import ValidationError

from orchestrator.artifacts import ArtifactIntegrityError, ArtifactNotFoundError, ArtifactStore
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus, RunStatus
from orchestrator.db import RunRepository, is_retriable_sqlite_write_conflict
from orchestrator.git import (
    GitError,
    SelectiveRestoreResult,
    PreparedSnapshot,
    WorktreeError,
    SnapshotPathLimitError,
    delete_snapshot_ref,
    ensure_snapshot_ref,
    verify_snapshot_ref,
    restore_baseline_worktree,
    restore_paths,
    prepare_snapshot,
    publish_snapshot,
    snapshot_path_metadata,
)
from orchestrator.graph import (
    authoritative_batch_verification_report_ids,
    cleanup_applied_ids_view,
    cleanup_requested_events_view,
    file_state_records_view,
    execution_attempts_view,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_payload_view,
    non_gap_planner_completion_contract_satisfied,
    node_roles_view,
    requirements_for_node_view,
    routine_snapshot_dynamic_feature_view,
    project_node_max_attempts,
    output_record_payloads_view,
    CheckResultRecord,
    CandidateRecord,
    EventEnvelope,
    FileStatePolicy,
    GraphCommandContext,
    GraphProjection,
    RunnerRecoveryRequestedPayload,
    RunnerBoundaryEntry,
    PatchCommandContext,
    PatchEnvelope,
    SubmitPatchCommand,
    RequirementRecord,
    ReliablePlanAssignmentCarrier,
    ReliablePlanModelAssignment,
    SemanticArtifactRecord,
    VerificationReportRecord,
    StoredArtifactRef,
    initial_projection,
    resolve_check_command_definition,
    recovery_proof_hash,
    boundary_manifest_hash,
    cache_authority_binding,
    cache_authority_is_new_format,
    file_state_policy_from_authority,
    derive_cache_roots,
    first_authorized_cache_root,
    cache_authority_hash,
    callback_payload_identity,
    canonical_callback_payload_bytes,
    classify_file_state,
    CleanupRequestedPayload,
    run_state,
    thaw_json,
    safe_validation_diagnostics,
    safe_validation_path,
    semantic_schema_declarations_view,
    validate_semantic_artifact_content,
    effective_node_max_attempts,
)
from orchestrator.graph_runtime import prompts as _prompts
from orchestrator.graph_runtime.controller import (
    GraphController,
    RuntimeBoundaryCapability,
    rebuild_projection,
)
from orchestrator.graph_runtime.crash_barrier import (
    CrashBarrier,
    CrashBarrierObservation,
    CrashBarrierPoint,
    CrashBarrierRecoveryProof,
    DisabledCrashBarrier,
)
from orchestrator.graph_runtime.errors import (
    CacheScanBudgetExceededError,
    CompromisedFileStateError,
    InvalidExecutionContractError,
    RecoveryCompletionRejectedError,
    RecoveryEventError,
    ProcessQuiescenceError,
    RunnerProcessMissingError,
    RecoveryRestoreError,
    StaleProjectionError,
    SubmissionQualityGateError,
)
from orchestrator.graph_runtime.file_state import (
    WorktreeFileStateBaseline,
    apply_cleanup_requested,
    capture_worktree_file_state_baseline,
    capture_file_state_boundary,
    collect_worktree_status,
    file_state_output_record,
)
from orchestrator.graph_runtime.gatekeeper import (
    ResidueClassifier,
    metadata_from_file_state_record,
    policy_with_pattern_library,
)
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem, SideEffectExecutor
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.graph_runtime.submission_gate import (
    SubmissionGateBaseline,
    SubmissionGateCommandResult,
    SubmissionGateReport,
    bind_submission_gate_witness,
    capture_submission_gate_baseline,
    cleanup_read_only_execution_workspace,
    enforce_submission_quality_gate,
    gate_rejection_evidence,
    prepare_read_only_execution_workspace,
    resolve_submission_gate_applicability,
    resolve_submission_gate_commands,
    submission_gate_commands_from_baseline,
    submission_gate_failure_fingerprint,
)
from orchestrator.runners import (
    AgentConfigError,
    AgentRunner,
    RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    ReliablePlanToolPreflightError,
    build_dynamic_tool_specs,
    create_agent_runner,
    is_reliable_plan_planner,
    resolve_dispatch_tools,
    SubmissionContract,
    SubmissionAcknowledgement,
    SubmissionOutputContract,
    SubmissionRejectionCategory,
    SubmissionRejectionEvidence,
    SubmissionRejectedError,
    SubmissionRepairExhaustedError,
)
from orchestrator.runners.types import ExecutionContext, ExecutionResult

MAX_GRAPH_PROMPT_CHARS = _prompts.MAX_GRAPH_PROMPT_CHARS
logger = logging.getLogger(__name__)

# Managed local-model executions may run for many minutes without a callback.
# This value is shared with the graph driver so the runner's asynchronous start
# heartbeat can never shorten the lease granted by the scheduling policy.
MANAGED_LEASE_TTL_SECONDS = 3600
MAX_GRAPH_JSON_SECTION_CHARS = _prompts.MAX_GRAPH_JSON_SECTION_CHARS
# Compatibility name retained for diagnostics/tests; all executable nodes now
# share this finite default through ``effective_node_max_attempts``.
DEFAULT_GAP_PLANNER_RUNTIME_DEATH_MAX_ATTEMPTS = 3
MAX_GRAPH_PROMPT_FIELD_CHARS = _prompts.MAX_GRAPH_PROMPT_FIELD_CHARS
MAX_CHECK_OUTPUT_CHARS = 20_000


def _requires_submission_quality_gate(context: GraphDispatchContext) -> bool:
    """Return whether this node owns mechanical snapshot acceptance."""
    return context.node_kind == "worker"


def _recovery_reason_for_finalization_error(
    error: Exception,
) -> Literal[
    "runner_died",
    "staged_artifact_missing",
    "staged_artifact_corrupt",
]:
    """Classify a staged-candidate failure without calling it a boundary mismatch."""
    if isinstance(error, ArtifactNotFoundError):
        return "staged_artifact_missing"
    if isinstance(error, ArtifactIntegrityError):
        return "staged_artifact_corrupt"
    return "runner_died"


async def _controller_ready_semantic_artifact_records(
    records: list[dict[str, object]],
    projection: GraphProjection,
    store: ArtifactStore,
) -> list[dict[str, object]]:
    """Resolve references before the callback envelope is content-addressed."""
    declarations = semantic_schema_declarations_view(projection)
    output: list[dict[str, object]] = []
    for raw_record in records:
        record = dict(raw_record)
        raw_value = record.get("value")
        if record.get("record_type") != "semantic_artifact" or not isinstance(raw_value, dict):
            output.append(record)
            continue
        value = dict(cast(dict[str, Any], raw_value))
        raw_ref = value.get("artifact_ref")
        if not isinstance(raw_ref, dict):
            output.append(record)
            continue
        ref = StoredArtifactRef.model_validate(raw_ref)
        content = await store.read(ref)
        decoded = json.loads(content.decode(ref.encoding or "utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("referenced semantic artifact JSON must contain an object")
        schema_id = value.get("schema_id")
        schema_version = value.get("schema_version")
        declaration = (
            declarations.get((schema_id, schema_version))
            if isinstance(schema_id, str)
            and isinstance(schema_version, int)
            and not isinstance(schema_version, bool)
            else None
        )
        if declaration is None:
            raise ValueError("referenced semantic artifact schema is undeclared")
        value["artifact_validation"] = {
            "declaration_record_id": declaration.record_id,
            "content_hash": ref.content_hash,
            "validated_json": decoded,
        }
        record["value"] = value
        output.append(record)
    return output


CHECK_OUTPUT_EXTERNALIZE_BYTES = 16_384
CHECK_OUTPUT_TAIL_CHARS = 4_000
DEFAULT_CHECK_TIMEOUT_SECONDS = 300
MAX_STALE_COMMAND_RETRIES = 5
SNAPSHOT_REF_PATTERN = re.compile(r"^refs/orchestrator/snapshots/(?!.*\.\.)[A-Za-z0-9._-]+$")


def _full_raw_patch_validation_diagnostics(
    payload: dict[str, Any],
    proposed_by_node_id: str,
) -> dict[str, Any] | None:
    """Return every safe raw-PatchOp error for the dynamic-tool response.

    Durable events retain the bounded form.  The Codex dynamic tool has a
    200-operation contract, so a normal tool invocation receives the complete
    safe accounting in-band; direct oversized commands are rejected at the
    command envelope before this preflight is reached.
    """

    raw_tool_input: object = getattr(payload, "tool_input", payload)
    tool_input = (
        cast(dict[str, Any], raw_tool_input) if isinstance(raw_tool_input, dict) else payload
    )
    nested = bool(getattr(payload, "nested", False))
    envelope_raw: object = tool_input.get("patch") if nested else tool_input

    if nested and not isinstance(envelope_raw, dict):
        diagnostics: list[dict[str, str]] = [
            {
                "path": "patch",
                "code": "model_type",
                "message": "Input must be an object",
            }
        ]
        diagnostics.extend(
            {
                "path": safe_validation_path((key,)),
                "code": "extra_forbidden",
                "message": "Extra field is not allowed",
            }
            for key in tool_input
            if key != "patch"
        )
        return _complete_validation_diagnostics(diagnostics)

    if not isinstance(envelope_raw, dict):
        return None
    envelope = cast(dict[str, Any], envelope_raw)
    prefix = "patch." if nested else ""
    raw_ops = envelope.get("ops")
    raw_ops_list = cast(list[object], raw_ops) if isinstance(raw_ops, list) else None
    if raw_ops_list is not None and len(raw_ops_list) > 200:
        return {
            "error_count": 1,
            "errors": [
                {
                    "path": f"{prefix}ops",
                    "code": "too_long",
                    "message": "At most 200 operations are allowed",
                }
            ],
            "omitted_error_count": 0,
        }
    diagnostics = []
    try:
        SubmitPatchCommand.model_validate(envelope)
    except ValidationError as exc:
        diagnostics.extend(_prefixed_validation_errors(exc, prefix))
    command_error_paths = {item["path"] for item in diagnostics}
    try:
        PatchEnvelope.model_validate(
            {
                "patch_id": envelope.get("patch_id"),
                "proposed_by_node_id": proposed_by_node_id,
                "base_graph_position": envelope.get("base_graph_position"),
                "ops": envelope.get("ops"),
                "rationale_record_id": envelope.get("rationale_record_id"),
            }
        )
    except ValidationError as exc:
        diagnostics.extend(
            item
            for item in _prefixed_validation_errors(exc, prefix)
            if item["path"] not in command_error_paths
        )
    if nested:
        diagnostics.extend(
            {
                "path": safe_validation_path((key,)),
                "code": "extra_forbidden",
                "message": "Extra field is not allowed",
            }
            for key in tool_input
            if key != "patch"
        )
    return _complete_validation_diagnostics(diagnostics)


def _prefixed_validation_errors(exc: ValidationError, prefix: str) -> list[dict[str, str]]:
    return [
        {**item, "path": f"{prefix}{item['path']}"}
        for item in safe_validation_diagnostics(exc, max_errors=None)["errors"]
    ]


def _complete_validation_diagnostics(
    diagnostics: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not diagnostics:
        return None
    unique = {(item["path"], item["code"], item["message"]): item for item in diagnostics}
    errors = [unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1], item[2]))]
    return {
        "error_count": len(errors),
        "errors": errors,
        "omitted_error_count": 0,
    }


_prompt_for_node = _prompts.prompt_for_node
_prompt_summary_for_node = _prompts.prompt_summary_for_node
_planner_evidence = _prompts.planner_evidence
_planner_packet = _prompts.planner_packet
_can_submit_graph_patch = _prompts.can_submit_graph_patch
_requires_graph_patch_before_submit = _prompts.requires_graph_patch_before_submit
_graph_patch_feedback_accepted = _prompts.graph_patch_feedback_accepted
_node_role = _prompts.node_role
_available_tools_for_context = _prompts.available_tools_for_context
_patch_payload_has_ops = _prompts.patch_payload_has_ops
_patch_payload_creates_successor_planner = _prompts.patch_payload_creates_successor_planner
_patch_payload_creates_finalization = _prompts.patch_payload_creates_finalization
_output_records_for_submit = _prompts.output_records_for_submit
_candidate_id_for_check = _prompts.candidate_id_for_check
_evaluated_record_citations = _prompts.evaluated_record_citations
_add_evaluated_record_citations = _prompts.add_evaluated_record_citations


def _declared_output_contract_error(
    context: GraphDispatchContext,
    records: list[dict[str, object]],
) -> str | None:
    """Preflight controller-owned and typed agent-authored output records."""
    contract = _submission_contract(context)
    if context.node_kind not in {"appeal", "oversight", "recovery"} and (
        contract is None or not contract.requires_arguments
    ):
        return None
    raw_outputs = context.node_payload.get("outputs")
    if not isinstance(raw_outputs, list):
        return None
    declared: dict[str, set[str]] = {}
    required_ports: set[str] = set()
    for raw_output in cast(list[object], raw_outputs):
        if not isinstance(raw_output, dict):
            continue
        output = cast(dict[str, object], raw_output)
        port = output.get("port")
        if not isinstance(port, str):
            continue
        schemas: set[str] = set()
        schema = output.get("schema")
        if isinstance(schema, str):
            schemas.add(schema)
        raw_schemas = output.get("schemas")
        if isinstance(raw_schemas, list):
            schemas.update(
                item for item in cast(list[object], raw_schemas) if isinstance(item, str)
            )
        declared[port] = schemas
        if output.get("required") is not False:
            required_ports.add(port)

    emitted_ports: set[str] = set()
    for index, record in enumerate(records):
        port = record.get("port")
        schema = record.get("schema")
        if not isinstance(port, str) or port not in declared:
            return (
                f"output contract preflight failed for node {context.node_id}: record {index} "
                f"uses unknown port {port}; declared ports={sorted(declared)}"
            )
        expected_schemas = declared[port]
        if expected_schemas and schema not in expected_schemas:
            return (
                f"output contract preflight failed for node {context.node_id}: record {index} "
                f"uses schema {schema} on {port}; expected schemas={sorted(expected_schemas)}"
            )
        emitted_ports.add(port)
    missing = sorted(required_ports - emitted_ports)
    if missing:
        return (
            f"output contract preflight failed for node {context.node_id}: "
            f"missing required ports={missing}"
        )
    return None


def _submission_contract(context: GraphDispatchContext) -> SubmissionContract | None:
    """Derive the runner-owned contract from accepted graph declarations."""
    raw_outputs = context.node_payload.get("outputs")
    if not isinstance(raw_outputs, list):
        return None
    declarations = semantic_schema_declarations_view(context.graph_projection)
    outputs: list[SubmissionOutputContract] = []
    for raw_output in cast(list[object], raw_outputs):
        if not isinstance(raw_output, dict):
            continue
        output = cast(dict[str, object], raw_output)
        port = output.get("port")
        schema = output.get("schema")
        if not isinstance(port, str) or not isinstance(schema, str):
            continue
        schema_id = context.node_payload.get("semantic_schema_id")
        schema_version = context.node_payload.get("semantic_schema_version")
        declaration = None
        if (
            schema == "SemanticArtifact"
            and isinstance(schema_id, str)
            and isinstance(schema_version, int)
            and not isinstance(schema_version, bool)
        ):
            declaration = declarations.get((schema_id, schema_version))
            if declaration is None:
                raise ValueError(
                    f"node {context.node_id} output {port} references undeclared semantic "
                    f"schema {schema_id}@{schema_version}"
                )
        outputs.append(
            SubmissionOutputContract(
                port=port,
                schema_name=schema,
                required=output.get("required") is not False,
                record_type=("semantic_artifact" if schema == "SemanticArtifact" else None),
                semantic_schema_id=(schema_id if declaration is not None else None),
                semantic_schema_version=(schema_version if declaration is not None else None),
                semantic_role=(
                    declaration.value.semantic_role if declaration is not None else None
                ),
                content_json_schema=(
                    cast(dict[str, Any], thaw_json(declaration.value.json_schema))
                    if declaration is not None
                    else None
                ),
            )
        )
    return SubmissionContract(outputs=tuple(outputs)) if outputs else None


def _semantic_output_records_from_submit_args(
    context: GraphDispatchContext,
    args: dict[str, Any],
) -> list[dict[str, object]]:
    """Compose controller-owned records with model-authored semantic content."""
    contract = _submission_contract(context)
    if contract is None or not contract.requires_arguments:
        if args:
            raise ValueError(f"node {context.node_id} submit does not accept output arguments")
        return _output_records_for_submit(context, [])
    unexpected = sorted(set(args) - {"outputs"})
    if unexpected:
        raise ValueError(
            f"node {context.node_id} submit has unknown fields={unexpected}; expected outputs"
        )
    raw_outputs = args.get("outputs")
    if not isinstance(raw_outputs, dict):
        raise ValueError(f"node {context.node_id} submit missing required object field outputs")
    authored = cast(dict[str, Any], raw_outputs)
    declared_ports = {output.port for output in contract.outputs if output.content_json_schema}
    unknown_ports = sorted(set(authored) - declared_ports)
    if unknown_ports:
        raise ValueError(
            f"node {context.node_id} submit has unknown output ports={unknown_ports}; "
            f"declared ports={sorted(declared_ports)}"
        )
    generated_records = [
        cast(dict[str, object], record) for record in _output_records_for_submit(context, [])
    ]
    generated_ports: set[str] = set()
    for record in generated_records:
        generated_port = record.get("port")
        if isinstance(generated_port, str):
            generated_ports.add(generated_port)
    ownership_collisions = sorted(generated_ports & declared_ports)
    if ownership_collisions:
        raise ValueError(
            f"node {context.node_id} output port {ownership_collisions[0]} has an ownership "
            "collision; the port is both controller-generated and agent-authored"
        )
    authored_records: list[dict[str, object]] = []
    for output in contract.outputs:
        if output.content_json_schema is None:
            continue
        if output.port not in authored:
            if output.required:
                raise ValueError(
                    f"node {context.node_id} submit missing required output port {output.port}; "
                    f"expected schema={output.schema_name}, semantic identity="
                    f"{output.semantic_schema_id}@{output.semantic_schema_version}"
                )
            continue
        content = authored[output.port]
        if not isinstance(content, dict):
            raise ValueError(
                f"node {context.node_id} output port {output.port} expected "
                f"schema={output.schema_name}, semantic identity={output.semantic_schema_id}@"
                f"{output.semantic_schema_version}; content must be an object"
            )
        typed_content = cast(dict[str, Any], content)
        reserved_identity_fields = {
            "record_id",
            "record_kind",
            "record_type",
            "schema",
            "schema_version",
            "producer_node_id",
            "port",
            "semantic_schema_id",
            "semantic_schema_version",
            "semantic_role",
        }
        spoofed_fields = sorted(set(typed_content) & reserved_identity_fields)
        if spoofed_fields:
            raise ValueError(
                f"node {context.node_id} output port {output.port} expected "
                f"schema={output.schema_name}, semantic identity={output.semantic_schema_id}@"
                f"{output.semantic_schema_version}; trusted identity fields are not authorable: "
                f"{spoofed_fields}"
            )
        record = SemanticArtifactRecord.model_validate(
            {
                "record_id": f"semantic-artifact-{context.execution_id}-{output.port}",
                "record_kind": "graph_record",
                "record_type": output.record_type,
                "schema_version": output.semantic_schema_version,
                "producer_node_id": context.node_id,
                "port": output.port,
                "schema": output.schema_name,
                "value": {
                    "semantic_role": output.semantic_role,
                    "schema_id": output.semantic_schema_id,
                    "schema_version": output.semantic_schema_version,
                    "content": dict(typed_content),
                    "provenance": {
                        "source": "agent_submit",
                        "execution_id": context.execution_id,
                    },
                    "source_record_ids": [],
                    "requirement_ids": [
                        item
                        for item in cast(
                            list[Any], context.node_payload.get("bound_requirement_ids", [])
                        )
                        if isinstance(item, str)
                    ],
                    "task_region_id": str(
                        context.node_payload.get("task_region_id") or context.node_id
                    ),
                    "validation_status": "validated",
                    "authority_status": "accepted",
                },
            }
        )
        content_error = validate_semantic_artifact_content(
            record, semantic_schema_declarations_view(context.graph_projection)
        )
        if content_error is not None:
            raise ValueError(
                f"node {context.node_id} output port {output.port} expected "
                f"schema={output.schema_name}, semantic identity={output.semantic_schema_id}@"
                f"{output.semantic_schema_version}; content validation failed: {content_error}"
            )
        authored_records.append(
            cast(dict[str, object], record.model_dump(mode="json", by_alias=True))
        )

    controller_ports = {
        output.port for output in contract.outputs if output.content_json_schema is None
    }
    controller_records: list[dict[str, object]] = []
    for record in generated_records:
        port = record.get("port")
        if not isinstance(port, str):
            continue
        if port not in controller_ports:
            continue
        controller_records.append(record)
    return [*controller_records, *authored_records]


def _empty_event_list() -> list[EventEnvelope]:
    return []


@dataclass(frozen=True)
class GraphDispatchContext:
    """Graph facts mapped into an existing runner execution context.

    Mapping decisions:
    - ``node_payload`` is the compiled executable node payload. It provides
      task title/context, role, candidate identity, tools, and verifier rubric.
    - ``requirements`` are reconstructed from requirement nodes bound to the
      executable node by compiler-created input bindings.
    - ``worktree_path`` is injected by runtime construction because filesystem
      location is run setup state, not a pure graph fact in slice 2.3.
    - Lease identity stays outside ``ExecutionContext`` and is copied into the
      graph callback envelope when the runner submits.
    """

    run_id: str
    node_id: str
    node_kind: str
    node_payload: dict[str, Any]
    requirements: list[str]
    worktree_path: str
    lease_id: str
    lease_generation: int
    execution_id: str
    base_snapshot_id: str
    dispatch_event_id: str
    cache_authority_hash: str = ""
    graph_projection: GraphProjection = field(default_factory=initial_projection)
    graph_events: list[EventEnvelope] = field(default_factory=_empty_event_list)
    graph_position: int = 0
    node_role: str = ""

    def __post_init__(self) -> None:
        """Keep direct legacy contexts truthful while production supplies the head."""
        if self.graph_position == 0 and self.graph_events:
            object.__setattr__(
                self,
                "graph_position",
                max(event.position for event in self.graph_events),
            )


def _crash_barrier_observation(
    context: GraphDispatchContext,
    *,
    point: CrashBarrierPoint,
    attempt_state: Literal["submission_staged", "completion_witnessed"],
) -> CrashBarrierObservation:
    """Project only canonical facts needed by the operator crash drill."""
    recovered_attempts = sorted(
        (
            attempt
            for attempt in execution_attempts_view(context.graph_projection).values()
            if attempt.node_id == context.node_id
            and attempt.lease_generation < context.lease_generation
            and attempt.state == "recovered"
            and attempt.completion_disposition == "restored_unwitnessed"
            and attempt.retry_scheduled
        ),
        key=lambda attempt: attempt.lease_generation,
        reverse=True,
    )[:20]
    recovered_proofs = [
        CrashBarrierRecoveryProof(
            node_id=attempt.node_id,
            execution_id=attempt.execution_id,
            lease_generation=attempt.lease_generation,
            state="recovered",
            completion_disposition="restored_unwitnessed",
            retry_authorized=True,
        )
        for attempt in recovered_attempts
    ]
    semantic_stage = context.node_payload.get("semantic_stage")
    return CrashBarrierObservation(
        run_id=context.run_id,
        node_id=context.node_id,
        execution_id=context.execution_id,
        lease_id=context.lease_id,
        lease_generation=context.lease_generation,
        node_kind=context.node_kind,
        node_role=context.node_role or "unknown",
        semantic_stage=semantic_stage if isinstance(semantic_stage, str) else "unknown",
        point=point,
        attempt_state=attempt_state,
        recovered_attempts=tuple(recovered_proofs),
    )


async def assemble_graph_dispatch_context(
    session_factory: async_sessionmaker[AsyncSession],
    item: OutboxItem,
    *,
    worktree_path: str,
) -> GraphDispatchContext:
    """Assemble the production dispatch context from durable graph facts."""

    payload = item.payload
    node_id = str(payload["node_id"])
    async with session_factory() as session:
        store = GraphEventStore(session)
        projection, events, graph_position = await store.load_projection_with_tail(item.run_id)

    _guard_no_pending_compromised_file_state_bindings(projection, node_id)
    node_payload = _node_payload(events, node_id, projection=projection)
    binding = cache_authority_binding(projection)
    lease = leases_view(projection).get(str(payload["lease_id"]))
    dispatch_hash = payload.get("cache_authority_hash")
    node_hash = node_payload.get("cache_authority_hash")
    lease_hash = lease.cache_authority_hash if lease is not None else None
    if cache_authority_is_new_format(projection) and (
        not isinstance(dispatch_hash, str)
        or not isinstance(node_hash, str)
        or not isinstance(lease_hash, str)
    ):
        raise ValueError(
            "new-format dispatch requires cache authority hashes on dispatch, lease, and node"
        )
    if any(
        value is not None and value != binding.hash
        for value in (dispatch_hash, lease_hash, node_hash)
    ):
        raise ValueError(
            "cache authority mismatch between dispatch, lease, node, and routine snapshot"
        )
    node_kind = str(node_payload.get("kind", "worker"))
    base_snapshot_id = payload.get("base_snapshot_id")
    if not isinstance(base_snapshot_id, str) or not base_snapshot_id:
        raise ValueError("agent dispatch payload missing base_snapshot_id")
    return GraphDispatchContext(
        run_id=item.run_id,
        node_id=node_id,
        node_kind=node_kind,
        node_role=_node_role(node_kind, node_payload),
        node_payload=node_payload,
        requirements=_requirements_for_node(projection, node_id, events),
        worktree_path=worktree_path,
        lease_id=str(payload["lease_id"]),
        lease_generation=_payload_int(payload, "generation"),
        execution_id=str(payload["execution_id"]),
        base_snapshot_id=base_snapshot_id,
        dispatch_event_id=item.event_id,
        cache_authority_hash=binding.hash,
        graph_projection=projection,
        graph_events=list(events),
        graph_position=graph_position,
    )


@dataclass(frozen=True)
class CheckExecutionWorktree:
    path: str
    snapshot_id: str | None = None
    snapshot_ref: str | None = None
    temporary_path: str | None = None


@dataclass(frozen=True)
class DependencyProvisionResult:
    package_dir: str
    strategy: str
    status: Literal["provisioned", "skipped", "failed"]
    detail: str


@dataclass(frozen=True)
class RunnerBoundaryCapture:
    """One durable snapshot plus the typed manifest for its filesystem boundary."""

    snapshot: PreparedSnapshot
    entries: list[dict[str, str]]
    boundary_hash: str
    cache_roots: list[dict[str, str] | str]
    cache_status_evidence: list[dict[str, str]]


class GraphAgentFactory(Protocol):
    def preflight(
        self,
        context: GraphDispatchContext,
        execution_context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None: ...

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner: ...


class GraphToolCatalogProvider(Protocol):
    """Validates the selected runner's concrete reliable-plan definitions."""

    def preflight(
        self,
        context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None: ...


class GraphRunnerBuilder(Protocol):
    """Injectable selected-runner construction boundary."""

    def __call__(
        self,
        agent_runner_type: AgentRunnerType,
        agent_runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> AgentRunner: ...


class SelectedRunnerGraphToolCatalog:
    """Production catalog backed by the concrete selected-runner adapters."""

    def __init__(
        self,
        runner_type: AgentRunnerType,
        runner_config: Mapping[str, Any],
    ) -> None:
        self._runner_type = runner_type
        self._runner_config = dict(runner_config)

    def preflight(
        self,
        context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None:
        if self._runner_type == AgentRunnerType.CODEX_SERVER:
            # This is the same concrete definition builder passed to
            # ``thread/start.dynamicTools`` by CodexServerAgent.execute().
            build_dynamic_tool_specs(context=context)
            return

        if self._runner_type == AgentRunnerType.CLI_SUBPROCESS:
            command = str(self._runner_config.get("command", "claude"))
            if Path(command).name != "claude":
                self._reject_delivery(
                    "CLI subprocess command "
                    f"{command!r} cannot attach the per-execution graph MCP server; "
                    "select codex_server or the Claude CLI for reliable-plan execution"
                )
            if not graph_mcp_available:
                self._reject_delivery(
                    "the per-execution graph MCP registry is unavailable for the Claude CLI"
                )

            # Build the actual FastMCP server used by the scheduled execution.
            # Its registration path constructs and validates the concrete JSON
            # schemas, so a missing or malformed registration is rejected here.
            from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server

            async def receive_patch(_payload: dict[str, Any]) -> str:
                return "preflight-only"

            build_graph_mcp_server(
                receive_patch,
                None,
                allowed_tools=context.available_tools,
                required_tools=context.required_tools,
            )
            return

        self._reject_delivery(
            f"runner {self._runner_type.value!r} has no reliable-plan graph tool adapter"
        )

    @staticmethod
    def _reject_delivery(reason: str) -> None:
        raise ReliablePlanToolPreflightError(
            invalid_tools={name: reason for name in RELIABLE_PLAN_REQUIRED_TOOL_NAMES}
        )


class GraphProcessRegistry(Protocol):
    def is_running(self, execution_id: str) -> bool: ...

    async def try_reattach(
        self,
        execution_id: str,
        callback: Callable[[list[dict[str, object]]], Awaitable[None]],
        worktree_execution_lock: asyncio.Lock,
    ) -> bool: ...


@dataclass
class _ExecutionCancellation:
    runner_loss: bool = False
    retry_after_recovery: bool = False
    runner_cancel: Callable[[], Awaitable[None]] | None = None


@dataclass(frozen=True)
class _RunnerProcessIdentity:
    """Exact child identity captured at the runner metadata boundary."""

    pid: int
    create_time: float
    command_sha256: str


def _read_runner_process_identity(pid: int) -> _RunnerProcessIdentity | None:
    """Return a reusable-PID-safe identity for a live non-zombie process."""
    try:
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        command = "\0".join(process.cmdline())
        return _RunnerProcessIdentity(
            pid=pid,
            create_time=process.create_time(),
            command_sha256=hashlib.sha256(command.encode()).hexdigest(),
        )
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
        return None


def _runner_process_identity_is_alive(identity: _RunnerProcessIdentity) -> bool:
    observed = _read_runner_process_identity(identity.pid)
    return observed == identity


class RunnerOwnedProcessRegistry:
    """Owns only tasks created by this executor process.

    Current AgentRunner implementations expose neither a stable execution id nor
    an API to pause mutations and replace their callback closure.  Therefore a
    task from a prior runtime can never safely be reattached: reporting it live
    would let it mutate the shared worktree outside the new executor lock.  The
    registry is nevertheless the production ownership boundary: it records
    locally-created tasks and explicitly refuses cross-runtime reattachment so
    reconciliation enters durable recovery instead of making an unsafe claim.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, tuple[str, asyncio.Task[None] | None, _ExecutionCancellation]] = {}

    def reserve(
        self,
        run_id: str,
        execution_id: str,
        cancellation: "_ExecutionCancellation",
    ) -> None:
        existing = self._tasks.get(execution_id)
        if existing is not None:
            raise ProcessQuiescenceError(
                f"execution {execution_id} already has a live process owner"
            )
        self._tasks[execution_id] = (run_id, None, cancellation)

    def register(
        self,
        execution_id: str,
        task: asyncio.Task[None],
        cancellation: "_ExecutionCancellation",
    ) -> None:
        reserved = self._tasks.get(execution_id)
        if reserved is None or reserved[1:] != (None, cancellation):
            raise ProcessQuiescenceError(
                f"execution {execution_id} lost its reserved process owner"
            )
        self._tasks[execution_id] = (reserved[0], task, cancellation)

    def release_reservation(
        self, execution_id: str, cancellation: "_ExecutionCancellation"
    ) -> None:
        reserved = self._tasks.get(execution_id)
        if reserved is not None and reserved[1:] == (None, cancellation):
            self._tasks.pop(execution_id, None)

    def unregister(self, execution_id: str, task: asyncio.Task[None]) -> None:
        existing = self._tasks.get(execution_id)
        if existing is not None and existing[1] is task and task.done():
            self._tasks.pop(execution_id, None)

    def is_running(self, execution_id: str) -> bool:
        owner = self._tasks.get(execution_id)
        return owner is not None and (owner[1] is None or not owner[1].done())

    def has_run_owners(self, run_id: str) -> bool:
        """Return whether any reserved or running execution remains owned by a run."""
        return self.run_owner_count(run_id) > 0

    def run_owner_count(self, run_id: str) -> int:
        """Return the bounded number of exact execution owners for one run."""
        return sum(owner[0] == run_id for owner in self._tasks.values())

    def prepare_run_quiescence(
        self,
        run_id: str,
        runner_loss: bool,
        retry_after_recovery: bool,
    ) -> None:
        """Bind the lifecycle cause before outer-driver cancellation can observe it."""
        for owner_run_id, _task, cancellation in self._tasks.values():
            if owner_run_id == run_id:
                cancellation.runner_loss = runner_loss
                cancellation.retry_after_recovery = retry_after_recovery

    async def quiesce_run(
        self,
        run_id: str,
        runner_loss: bool = True,
        retry_after_recovery: bool = False,
    ) -> None:
        """Cancel each exact runner owned for ``run_id`` before driver transfer."""
        self.prepare_run_quiescence(run_id, runner_loss, retry_after_recovery)
        execution_ids = [
            execution_id for execution_id, owner in self._tasks.items() if owner[0] == run_id
        ]
        for execution_id in execution_ids:
            await self._quiesce_execution(
                execution_id,
                runner_loss=runner_loss,
                retry_after_recovery=retry_after_recovery,
            )

    async def try_reattach(
        self,
        execution_id: str,
        callback: Callable[[list[dict[str, object]]], Awaitable[None]],
        worktree_execution_lock: asyncio.Lock,
    ) -> bool:
        del callback, worktree_execution_lock
        await self._quiesce_execution(
            execution_id,
            runner_loss=True,
            retry_after_recovery=False,
        )
        return False

    async def _quiesce_execution(
        self,
        execution_id: str,
        *,
        runner_loss: bool,
        retry_after_recovery: bool,
    ) -> None:
        owner = self._tasks.get(execution_id)
        if owner is None:
            return
        _, task, cancellation = owner
        if task is None:
            raise ProcessQuiescenceError(f"execution {execution_id} has no task for quiescence")
        if task.done():
            if self._tasks.get(execution_id) == owner:
                self._tasks.pop(execution_id, None)
            return
        if task is asyncio.current_task():
            raise ProcessQuiescenceError(
                f"execution {execution_id} cannot quiesce from its own task"
            )
        cancellation.runner_loss = runner_loss
        cancellation.retry_after_recovery = retry_after_recovery
        if cancellation.runner_cancel is not None:
            await cancellation.runner_cancel()
        task.cancel()
        # Do not time out this wait. A runner that catches cancellation remains
        # a worktree owner, so recovery must stay blocked rather than restore
        # concurrently with its mutations.
        waiter = asyncio.ensure_future(asyncio.gather(task, return_exceptions=True))
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            await asyncio.shield(waiter)
            raise
        finally:
            if task.done() and self._tasks.get(execution_id) == owner:
                self._tasks.pop(execution_id, None)


class RunnerRecoveryRestorer(Protocol):
    """Restores one durable recovery request into its shared worktree."""

    def __call__(
        self,
        worktree_path: str | Path,
        snapshot_id: str,
        paths: list[str],
        *,
        expected_tree_sha: str | None = None,
    ) -> SelectiveRestoreResult: ...


class StaticGraphAgentFactory:
    """Production-oriented adapter around the existing runner registry."""

    def __init__(
        self,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        *,
        graph_tool_catalog: GraphToolCatalogProvider | None = None,
        runner_builder: GraphRunnerBuilder = create_agent_runner,
    ) -> None:
        self._runner_type = runner_type
        self._runner_config = dict(runner_config or {})
        self._graph_tool_catalog = graph_tool_catalog or SelectedRunnerGraphToolCatalog(
            runner_type,
            self._runner_config,
        )
        self._runner_builder = runner_builder

    def preflight(
        self,
        context: GraphDispatchContext,
        execution_context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None:
        self._graph_tool_catalog.preflight(
            execution_context,
            graph_mcp_available=graph_mcp_available,
        )
        self._validated_reliable_plan_assignment(context)

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        phase = "verifying" if context.node_kind == "verifier" else "building"
        runner_config = dict(self._runner_config)
        assignment = self._validated_reliable_plan_assignment(context)
        if assignment is not None:
            runner_config["model"] = assignment.model
        return self._runner_builder(
            self._runner_type,
            runner_config,
            run_id=context.run_id,
            phase=phase,
        )

    def _validated_reliable_plan_assignment(
        self, context: GraphDispatchContext
    ) -> ReliablePlanModelAssignment | None:
        payload = context.node_payload
        root_payload = node_payload_view(context.graph_projection, "root") or {}
        raw_authoritative_carrier = root_payload.get("reliable_plan_assignment_carrier")
        reliable_plan_membership = isinstance(
            root_payload.get("reliable_plan_skeleton_id"), str
        ) or any(
            isinstance(
                (node_payload_view(context.graph_projection, node_id) or {}).get(
                    "reliable_plan_skeleton_id"
                ),
                str,
            )
            for node_id in node_kinds_view(context.graph_projection)
        )
        if not reliable_plan_membership:
            return None
        if not isinstance(raw_authoritative_carrier, dict):
            raise InvalidExecutionContractError(
                "reliable-plan graph is missing root sealed assignment carrier; "
                "historical runs remain readable but cannot execute"
            )
        try:
            authoritative_carrier = ReliablePlanAssignmentCarrier.model_validate(
                raw_authoritative_carrier
            )
        except ValueError as exc:
            raise InvalidExecutionContractError(
                "reliable-plan root sealed assignment carrier is invalid"
            ) from exc
        raw_carrier = payload.get("reliable_plan_assignment_carrier")
        if not isinstance(raw_carrier, dict):
            raise InvalidExecutionContractError(
                "reliable-plan execution is missing sealed assignment carrier; "
                "recreate the run with a qualified assignment arm"
            )
        try:
            carrier = ReliablePlanAssignmentCarrier.model_validate(raw_carrier)
        except ValueError as exc:
            raise InvalidExecutionContractError(
                "reliable-plan node sealed assignment carrier is invalid"
            ) from exc
        if carrier != authoritative_carrier:
            raise InvalidExecutionContractError(
                "reliable-plan node assignment carrier does not match root authority"
            )
        if carrier.selected_runner_type != self._runner_type.value:
            raise InvalidExecutionContractError(
                "reliable-plan selected runner mismatch: "
                f"node requires {carrier.selected_runner_type}, dispatch selected "
                f"{self._runner_type.value}"
            )
        raw_role = payload.get("reliable_plan_assignment_role")
        if not isinstance(raw_role, str) or raw_role not in {
            "planner",
            "discovery_worker",
            "implementation_worker",
            "correction_worker",
            "verifier",
            "successor_planner",
        }:
            raise InvalidExecutionContractError("reliable-plan node has invalid assignment role")
        expected_role = self._reliable_plan_role_for_payload(payload)
        if raw_role != expected_role:
            raise InvalidExecutionContractError(
                "reliable-plan node assignment role does not match controller-derived role"
            )
        assignment = carrier.assignment_for(cast(Any, raw_role))
        if payload.get("reliable_plan_selected_runner_type") != carrier.selected_runner_type:
            raise InvalidExecutionContractError(
                "reliable-plan node selected-runner stamp does not match carrier"
            )
        if payload.get("runner_model_override") != assignment.model:
            raise InvalidExecutionContractError(
                "reliable-plan node model stamp does not match carrier"
            )
        if payload.get("profile") != assignment.profile.value:
            raise InvalidExecutionContractError(
                "reliable-plan node profile stamp does not match carrier"
            )
        return assignment

    @staticmethod
    def _reliable_plan_role_for_payload(payload: dict[str, Any]) -> str:
        kind = payload.get("kind")
        stage = payload.get("semantic_stage")
        role = payload.get("role")
        if kind == "verifier":
            return "verifier"
        if kind == "planner":
            if stage == "successor_planning" or role == "gap_planner":
                return "successor_planner"
            return "planner"
        if kind == "worker":
            if stage == "discovery":
                return "discovery_worker"
            if stage == "corrective_work" or role in {
                "correction_worker",
                "corrective_worker",
            }:
                return "correction_worker"
            if stage == "effectful_batch" or payload.get("access_mode") == "write":
                return "implementation_worker"
        raise InvalidExecutionContractError(
            "reliable-plan model-backed node has ambiguous assignment role"
        )


def _runtime_death_max_attempts(context: GraphDispatchContext) -> int | None:
    return effective_node_max_attempts(
        context.node_kind,
        context.node_payload.get("max_attempts"),
    )


def _authority_file_state_policy(context: GraphDispatchContext) -> FileStatePolicy:
    """Runtime boundary authority comes exclusively from the verified snapshot."""
    binding = cache_authority_binding(context.graph_projection)
    if context.cache_authority_hash and binding.hash != context.cache_authority_hash:
        raise ValueError("dispatch cache authority binding changed before worktree access")
    return policy_with_pattern_library(
        [],
        file_state_policy_from_authority(binding.policy),
        projection=context.graph_projection,
    )


def _authority_cache_policy(context: GraphDispatchContext) -> Any:
    binding = cache_authority_binding(context.graph_projection)
    if context.cache_authority_hash and binding.hash != context.cache_authority_hash:
        raise ValueError("dispatch cache authority binding changed before worktree access")
    return binding.policy


class GraphDispatchExecutor(SideEffectExecutor):
    """Start graph-leased agent executions from durable outbox items."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        controller: GraphController,
        agent_factory: GraphAgentFactory,
        *,
        worktree_path: str | Path,
        artifact_store: ArtifactStore,
        running_executions: dict[str, asyncio.Task[None]] | None = None,
        process_registry: GraphProcessRegistry | None = None,
        residue_classifier: ResidueClassifier | None = None,
        max_gatekeeper_items_per_boundary: int = 20,
        on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
        on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] = perf_counter,
        graph_mcp_registry: "GraphMcpExecutionRegistry | None" = None,
        base_url: str = "http://localhost:8000",
        file_state_baselines: dict[str, WorktreeFileStateBaseline] | None = None,
        worktree_execution_lock: asyncio.Lock | None = None,
        runner_recovery_restorer: RunnerRecoveryRestorer = restore_paths,
        runtime_boundary_capability: RuntimeBoundaryCapability | None = None,
        utcnow: Callable[[], datetime] | None = None,
        crash_barrier: CrashBarrier | None = None,
        agent_dispatch_admission: Callable[[str], Awaitable[bool]] | None = None,
        runner_health_interval: float = 30.0,
        runner_metadata_start_deadline: float = 30.0,
    ) -> None:
        self._session_factory = session_factory
        self._controller = controller
        self._runtime_boundary_capability = (
            runtime_boundary_capability
            if runtime_boundary_capability is not None
            else getattr(controller, "_runtime_boundary_capability", RuntimeBoundaryCapability())
        )
        self._agent_factory = agent_factory
        self._worktree_path = str(worktree_path)
        self._artifact_store = artifact_store
        self._running = running_executions if running_executions is not None else {}
        self._process_registry = process_registry
        self._residue_classifier = residue_classifier
        self._max_gatekeeper_items_per_boundary = max_gatekeeper_items_per_boundary
        self._on_agent_output = on_agent_output
        self._on_agent_usage = on_agent_usage
        self._monotonic = monotonic
        self._graph_mcp_registry = graph_mcp_registry
        self._base_url = base_url.rstrip("/")
        self._file_state_baselines = (
            file_state_baselines if file_state_baselines is not None else {}
        )
        self._worktree_execution_lock = (
            worktree_execution_lock if worktree_execution_lock is not None else asyncio.Lock()
        )
        self._runner_recovery_restorer = runner_recovery_restorer
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._crash_barrier = crash_barrier or DisabledCrashBarrier()
        self._agent_dispatch_admission = agent_dispatch_admission
        if runner_health_interval <= 0:
            raise ValueError("runner_health_interval must be positive")
        self._runner_health_interval = runner_health_interval
        if runner_metadata_start_deadline <= 0:
            raise ValueError("runner_metadata_start_deadline must be positive")
        self._runner_metadata_start_deadline = runner_metadata_start_deadline
        self._verified_runner_identities: dict[str, _RunnerProcessIdentity] = {}

    async def _run_worktree_boundary(
        self,
        operation: Callable[..., Any],
        /,
        *args: object,
        lock_held: bool = False,
        offload: bool = True,
        **kwargs: object,
    ) -> Any:
        """Run one worktree/CAS boundary off-loop and cancellation-safely.

        ``asyncio.to_thread`` alone is not cancellation safe: cancelling its
        waiter does not stop the underlying thread, so an enclosing
        ``asyncio.Lock`` context could release while Git or filesystem mutation
        is still in flight.  This helper shields the thread and, if cancellation
        wins, waits for that exact operation to finish before propagating
        cancellation.  Therefore the per-worktree lock remains held for the
        complete physical boundary.

        ``lock_held`` is used by the serialized runner/callback path, including
        MCP callbacks that execute in a different asyncio task while the runner
        task owns the shared lock.  Direct recovery/finalization test seams leave
        it false and acquire the same lock here.
        """

        async def run_and_drain_cancellation() -> Any:
            worker = (
                asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
                if offload
                else asyncio.ensure_future(cast(Awaitable[Any], operation(*args, **kwargs)))
            )
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        # A second cancellation request must not release the
                        # worktree lock while the first thread is still active.
                        continue
                    except BaseException:
                        break
                if worker.done() and not worker.cancelled():
                    # Retrieve a losing thread exception so it is not reported
                    # as an unhandled task; cancellation remains authoritative.
                    try:
                        worker.result()
                    except BaseException:
                        pass
                raise

        if lock_held:
            return await run_and_drain_cancellation()
        async with self._worktree_execution_lock:
            return await run_and_drain_cancellation()

    async def dispatch(self, item: OutboxItem) -> None:
        if item.kind == "snapshot_publish":
            async with self._worktree_execution_lock:
                await self._dispatch_snapshot_publish(item, worktree_lock_held=True)
            return
        if item.kind == "snapshot_cleanup":
            async with self._worktree_execution_lock:
                await self._dispatch_snapshot_cleanup(item, worktree_lock_held=True)
            return
        if item.kind == "runner_recovery":
            async with self._worktree_execution_lock:
                await self._dispatch_runner_recovery(item, worktree_lock_held=True)
            return
        if item.kind == "validation_environment_resolution":
            async with self._worktree_execution_lock:
                await self._dispatch_validation_environment_resolution(item)
            return
        if item.kind != "agent_dispatch":
            return

        context = await self._build_dispatch_context(item)
        if not await self._agent_dispatch_is_allowed(context.run_id):
            return
        try:
            if is_reliable_plan_planner(
                node_kind=context.node_kind,
                node_payload=context.node_payload,
            ):
                execution_context = self._execution_context(context)
                preflight = getattr(self._agent_factory, "preflight", None)
                if not callable(preflight):
                    raise ReliablePlanToolPreflightError(
                        invalid_tools={
                            name: (
                                "selected graph agent factory does not expose a concrete "
                                "tool-catalog preflight"
                            )
                            for name in RELIABLE_PLAN_REQUIRED_TOOL_NAMES
                        }
                    )
                preflight(
                    context,
                    execution_context,
                    graph_mcp_available=self._graph_mcp_registry is not None,
                )
        except (AgentConfigError, InvalidExecutionContractError) as exc:
            await self._invalid_execution_contract(context, str(exc))
            return
        existing = self._running.get(context.execution_id)
        if existing is not None and not existing.done():
            return

        registry = (
            self._process_registry
            if isinstance(self._process_registry, RunnerOwnedProcessRegistry)
            else None
        )
        cancellation = _ExecutionCancellation()
        if not await self._agent_dispatch_is_allowed(context.run_id):
            return
        if registry is not None:
            registry.reserve(context.run_id, context.execution_id, cancellation)
        try:
            if not await self._agent_dispatch_is_allowed(context.run_id):
                if registry is not None:
                    registry.release_reservation(context.execution_id, cancellation)
                return
            if context.node_kind == "check":
                task = asyncio.create_task(self._run_check_serialized(context))
            elif context.node_kind == "join":
                task = asyncio.create_task(self._run_join(context))
            elif context.node_kind == "final_gate":
                task = asyncio.create_task(self._run_final_gate(context))
            else:
                runner = self._agent_factory.create_runner(context)
                cancellation.runner_cancel = runner.cancel
                task = asyncio.create_task(
                    self._run_agent_serialized(context, runner, cancellation)
                )
        except (AgentConfigError, InvalidExecutionContractError) as exc:
            if registry is not None:
                registry.release_reservation(context.execution_id, cancellation)
            await self._invalid_execution_contract(context, str(exc))
            return
        except BaseException:
            if registry is not None:
                registry.release_reservation(context.execution_id, cancellation)
            raise
        task.add_done_callback(_consume_task_exception)
        if registry is not None:
            registry.register(context.execution_id, task, cancellation)

            def unregister(completed: asyncio.Task[None]) -> None:
                registry.unregister(context.execution_id, completed)

            task.add_done_callback(unregister)
        self._running[context.execution_id] = task

    async def _agent_dispatch_is_allowed(self, run_id: str) -> bool:
        if self._agent_dispatch_admission is None:
            return True
        return await self._agent_dispatch_admission(run_id)

    async def _run_is_stopping_for_pause(self, run_id: str) -> bool:
        """Read the durable stop intent when cancellation beats signal handling."""
        async with self._session_factory() as session:
            run = await RunRepository(session).get(run_id)
        return run.status == RunStatus.STOPPING and run.pause_reason == "graph_pause_requested"

    def is_running(self, execution_id: str) -> bool:
        task = self._running.get(execution_id)
        if task is not None and not task.done():
            return True
        return self._process_registry is not None and self._process_registry.is_running(
            execution_id
        )

    def can_heartbeat(self, execution_id: str) -> bool:
        """Return true only while the exact observed child identity still exists."""
        identity = self._verified_runner_identities.get(execution_id)
        return identity is not None and _runner_process_identity_is_alive(identity)

    async def wait_for_all(
        self,
        *,
        timeout_seconds: float | None = None,
        active_execution_ids: set[str] | None = None,
    ) -> None:
        self._prune_done()
        if active_execution_ids is None:
            tasks = list(self._running.values())
        else:
            tasks = [
                task
                for execution_id, task in self._running.items()
                if execution_id in active_execution_ids
            ]
        if tasks:
            # A graph-driver owner may be cancelled so liveness can transfer to
            # a replacement driver.  The runner tasks remain owned by the
            # injected process registry and must be quiesced there, where the
            # exact runner.cancel boundary is available; cancellation of this
            # waiter must not bypass that boundary.
            protected = [asyncio.shield(task) for task in tasks]
            if timeout_seconds is None:
                await asyncio.gather(*protected)
            else:
                await asyncio.wait(protected, timeout=max(0.0, timeout_seconds))
        self._prune_done()

    async def reconcile_execution_attempts(self, run_id: str) -> set[str]:
        """Recover restart state from canonical attempts, not process-local tasks.

        Returns execution ids covered by the managed protocol.  Callers retain
        the old ``agent_died`` fallback only for histories written before a
        baseline fact existed.
        """
        async with self._session_factory() as session:
            projection, tail, graph_position = await GraphEventStore(
                session
            ).load_projection_with_tail(run_id)
        terminal = run_state(projection) in {"cancelled", "completed", "failed"}
        handled: set[str] = set()
        attempts = tuple(execution_attempts_view(projection).values())
        # A pending outbox row may have been redispatched on this executor by
        # ``recover()`` immediately before reconciliation.  Agent execution owns
        # ``_worktree_execution_lock`` for its full mutation boundary, so trying
        # to acquire that lock before recognizing our own task deadlocks lease
        # maintenance behind the slow runner.  Classify current-runtime owners
        # first; pre-restart owners exist only in the injected process registry
        # and still take the locked quiescence/recovery path below.
        for attempt in attempts:
            if attempt.state in {"finalized", "recovered", "recovery_requested"}:
                handled.add(attempt.execution_id)
                continue
            local_task = self._running.get(attempt.execution_id)
            if local_task is not None and not local_task.done():
                handled.add(attempt.execution_id)
        attempts_requiring_recovery = tuple(
            attempt for attempt in attempts if attempt.execution_id not in handled
        )
        if not attempts_requiring_recovery:
            return handled
        async with self._worktree_execution_lock:
            for attempt in attempts_requiring_recovery:
                if attempt.state == "completion_witnessed":
                    context = await self._reattached_execution_context(run_id, attempt)
                    try:
                        await self._finalize_runner_execution(context, worktree_lock_held=True)
                    except (
                        ArtifactIntegrityError,
                        ArtifactNotFoundError,
                        GitError,
                        WorktreeError,
                        ValueError,
                    ) as exc:
                        await self._request_runner_recovery(
                            context,
                            _recovery_reason_for_finalization_error(exc),
                            error_detail=f"witnessed finalization validation failed: {exc}",
                            worktree_lock_held=True,
                        )
                    handled.add(attempt.execution_id)
                    continue
                if self.is_running(attempt.execution_id):
                    context = await self._reattached_execution_context(run_id, attempt)

                    async def complete_submission(
                        output_records: list[dict[str, object]],
                    ) -> None:
                        await self._complete_reattached_submission(context, output_records)

                    if (
                        self._process_registry is not None
                        and await self._process_registry.try_reattach(
                            attempt.execution_id,
                            complete_submission,
                            self._worktree_execution_lock,
                        )
                    ):
                        handled.add(attempt.execution_id)
                        continue
                lease = leases_view(projection).get(attempt.lease_id)
                node_kind = node_kinds_view(projection).get(attempt.node_id, "worker")
                node_role = node_roles_view(projection).get(attempt.node_id, "")
                max_attempts = project_node_max_attempts(projection).get(attempt.node_id)
                context = GraphDispatchContext(
                    run_id=run_id,
                    node_id=attempt.node_id,
                    node_kind=node_kind,
                    node_role=node_role,
                    node_payload=(
                        {"max_attempts": max_attempts} if max_attempts is not None else {}
                    ),
                    requirements=[],
                    worktree_path=self._worktree_path,
                    lease_id=attempt.lease_id,
                    lease_generation=attempt.lease_generation,
                    execution_id=attempt.execution_id,
                    base_snapshot_id=(lease.base_snapshot_id if lease is not None else None)
                    or "recovered",
                    dispatch_event_id=f"reconcile:{attempt.execution_id}",
                    cache_authority_hash=cache_authority_binding(projection).hash,
                    graph_projection=projection,
                    graph_events=list(tail),
                    graph_position=graph_position,
                )
                # Staging proves only that on_submit ran.  It does not prove
                # that runner.execute returned successfully, so an orphaned
                # staged attempt must not publish its records on restart.
                # A successfully reattached process finalizes through its
                # completion callback above; every non-reattached attempt
                # instead restores first, after which the kernel atomically
                # determines retry disposition.
                await self._request_runner_recovery(
                    context,
                    "cancelled" if terminal else "runner_died",
                    worktree_lock_held=True,
                )
                handled.add(attempt.execution_id)
        return handled

    async def request_run_quiescence_recovery(
        self,
        run_id: str,
        reason: str,
        retry_after_recovery: bool,
    ) -> None:
        """Move every active execution into durable manual lifecycle recovery."""
        projection = await self._controller.read_projection(run_id)
        attempts = execution_attempts_view(projection)
        active_leases = tuple(
            lease for lease in leases_view(projection).values() if lease.state == "active"
        )
        attempted_execution_ids: set[str] = set()
        for lease in active_leases:
            execution_id = lease.execution_id
            if not isinstance(execution_id, str):
                continue
            attempt = attempts.get(execution_id)
            if attempt is None:
                continue
            attempted_execution_ids.add(execution_id)
            if attempt.state == "recovery_requested":
                continue
            if attempt.state not in {
                "baseline_captured",
                "submission_staged",
                "completion_witnessed",
            }:
                continue
            context = await self._reattached_execution_context(run_id, attempt)
            await self._request_runner_recovery(
                context,
                "cancelled",
                error_detail=f"manual lifecycle quiescence: {reason}"[:1_000],
                retry_after_recovery=retry_after_recovery,
            )

        projection = await self._controller.read_projection(run_id)
        for lease in tuple(leases_view(projection).values()):
            if lease.state != "active" or lease.execution_id in attempted_execution_ids:
                continue
            payload: dict[str, object] = {
                "lease_id": lease.lease_id,
                "reason": "manual_lifecycle_quiescence",
            }
            if isinstance(lease.execution_id, str):
                payload["execution_id"] = lease.execution_id
            await self._handle_command_retry_stale(
                run_id,
                await self._current_position(run_id),
                "agent_died",
                payload,
            )

    async def _reattached_execution_context(
        self, run_id: str, attempt: Any
    ) -> GraphDispatchContext:
        """Rebuild the durable identity needed to complete a surviving runner."""
        async with self._session_factory() as session:
            projection, events, graph_position = await GraphEventStore(
                session
            ).load_projection_with_tail(run_id)
        node_payload = _node_payload(events, attempt.node_id, projection=projection)
        lease = leases_view(projection).get(attempt.lease_id)
        return GraphDispatchContext(
            run_id=run_id,
            node_id=attempt.node_id,
            node_kind=str(node_payload.get("kind", "worker")),
            node_role=_node_role(str(node_payload.get("kind", "worker")), node_payload),
            node_payload=node_payload,
            requirements=_requirements_for_node(projection, attempt.node_id, events),
            worktree_path=self._worktree_path,
            lease_id=attempt.lease_id,
            lease_generation=attempt.lease_generation,
            execution_id=attempt.execution_id,
            base_snapshot_id=(lease.base_snapshot_id if lease is not None else None)
            or attempt.lease_base_snapshot_id
            or "recovered",
            dispatch_event_id=f"reconcile:{attempt.execution_id}",
            cache_authority_hash=cache_authority_binding(projection).hash,
            graph_projection=projection,
            graph_events=list(events),
            graph_position=graph_position,
        )

    async def _complete_reattached_submission(
        self,
        context: GraphDispatchContext,
        output_records: list[dict[str, object]],
    ) -> None:
        """Stage and finalize a live process callback after runtime restart.

        The old process cannot retain the original in-memory callback closure.
        Rebinding it here deliberately routes its completion through the same
        capability-gated boundary protocol as a newly dispatched runner.
        """
        async with self._worktree_execution_lock:
            attempt = execution_attempts_view(
                await self._controller.read_projection(context.run_id)
            ).get(context.execution_id)
            if attempt is None or (
                attempt.node_id != context.node_id
                or attempt.lease_id != context.lease_id
                or attempt.lease_generation != context.lease_generation
            ):
                raise ValueError("reattached runner identity no longer owns the execution")
            if attempt.state == "finalized":
                return
            if attempt.state == "completion_witnessed":
                await self._finalize_runner_execution(context, worktree_lock_held=True)
                return
            if attempt.state == "submission_staged":
                if await self._witness_runner_completion(context, worktree_lock_held=True):
                    await self._finalize_runner_execution(context, worktree_lock_held=True)
                return
            if attempt.state != "baseline_captured":
                raise ValueError("reattached runner execution is not ready for submission")
            await self._submit_callback(
                context,
                [],
                output_records=output_records,
                worktree_lock_held=True,
            )
            if await self._witness_runner_completion(context, worktree_lock_held=True):
                await self._finalize_runner_execution(context, worktree_lock_held=True)

    def cancel_all(self) -> None:
        for task in self._running.values():
            task.cancel()

    def _prune_done(self) -> None:
        for execution_id, task in list(self._running.items()):
            if task.done():
                self._running.pop(execution_id, None)

    async def _run_agent_serialized(
        self,
        context: GraphDispatchContext,
        runner: AgentRunner,
        cancellation: _ExecutionCancellation | None = None,
    ) -> None:
        """Serialize a shared-worktree execution from baseline through submit.

        File-state attribution cannot safely distinguish concurrent processes in
        one worktree. The injected lock makes ownership deterministic without
        process-global coordination: each worker sees a stable baseline and its
        post-submit capture before the next worker starts.
        """
        async with self._worktree_execution_lock:
            policy = _authority_file_state_policy(context)
            cache_policy = _authority_cache_policy(context)
            try:
                self._file_state_baselines[
                    context.execution_id
                ] = await self._run_worktree_boundary(
                    capture_worktree_file_state_baseline,
                    context.worktree_path,
                    policy,
                    lock_held=True,
                )
                baseline = await self._run_worktree_boundary(
                    _capture_runner_boundary,
                    context.worktree_path,
                    policy,
                    cache_policy,
                    "baseline",
                    snapshot_id=_managed_snapshot_id("baseline", context.execution_id),
                    lock_held=True,
                )
            except (
                CacheScanBudgetExceededError,
                CompromisedFileStateError,
                SnapshotPathLimitError,
            ) as exc:
                # No baseline ref is owned until the boundary event is durable,
                # so standard lease failure is the only safe path here.
                self._file_state_baselines.pop(context.execution_id, None)
                await self._agent_died(context, str(exc))
                return
            read_only_workspace = None
            if callable(self._session_factory):
                await self._record_runner_baseline(context, baseline)
                await self._run_worktree_boundary(
                    publish_snapshot,
                    context.worktree_path,
                    baseline.snapshot,
                    lock_held=True,
                )
                if _requires_submission_quality_gate(context):
                    try:
                        await self._ensure_submission_gate_baseline(context, baseline)
                        applicability = resolve_submission_gate_applicability(
                            context.node_payload,
                            node_id=context.node_id,
                            graph_projection=context.graph_projection,
                        )
                        if not applicability.execute_commands:
                            read_only_workspace = await prepare_read_only_execution_workspace(
                                source_worktree=context.worktree_path,
                                snapshot_commit_sha=baseline.snapshot.commit_sha,
                                snapshot_tree_sha=baseline.snapshot.tree_sha,
                            )
                    except InvalidExecutionContractError as exc:
                        await self._invalid_execution_contract(context, str(exc))
                        return
                    except SubmissionQualityGateError as exc:
                        await self._agent_died(context, str(exc))
                        return
            try:
                await self._run_agent(
                    context,
                    runner,
                    cancellation,
                    runner_worktree_path=(
                        str(read_only_workspace.checkout)
                        if read_only_workspace is not None
                        else None
                    ),
                )
            finally:
                try:
                    if read_only_workspace is not None:
                        await cleanup_read_only_execution_workspace(
                            source_worktree=context.worktree_path,
                            workspace=read_only_workspace,
                        )
                finally:
                    self._file_state_baselines.pop(context.execution_id, None)

    async def _run_check_serialized(self, context: GraphDispatchContext) -> None:
        """Serialize check snapshot/worktree setup with worker mutations."""
        async with self._worktree_execution_lock:
            await self._run_check(context)

    async def _run_agent(
        self,
        context: GraphDispatchContext,
        runner: AgentRunner,
        cancellation: _ExecutionCancellation | None = None,
        *,
        runner_worktree_path: str | None = None,
    ) -> None:
        # Direct callers retain the synchronous, non-managed callback contract.
        # Production dispatch always installs the baseline before entering here.
        managed = callable(
            getattr(self, "_session_factory", None)
        ) and context.execution_id in getattr(self, "_file_state_baselines", {})
        try:
            await self._acknowledge_start(context)
            await self._record_start_heartbeat(context)
            grades: list[tuple[str, str, str | None]] = []
            graph_patch_submitted = False
            graph_patch_accepted = False
            graph_successor_accepted = False
            graph_finalization_accepted = False
            submitted_callback = False
            submission_acknowledgement: SubmissionAcknowledgement | None = None
            first_submission_rejection_category: SubmissionRejectionCategory | None = None
            first_submission_rejection_detail: str | None = None
            submission_rejection_categories: set[SubmissionRejectionCategory] = set()
            latest_submission_rejection: SubmissionAcknowledgement | None = None

            async def on_checklist_update(
                _req_id: str,
                _status: ChecklistStatus,
                _note: str | None,
            ) -> None:
                return None

            async def on_submit(
                submit_args: dict[str, Any] | None = None,
            ) -> SubmissionAcknowledgement:
                nonlocal submitted_callback, submission_acknowledgement
                nonlocal first_submission_rejection_category, latest_submission_rejection
                nonlocal first_submission_rejection_detail
                if submitted_callback:
                    # Managed callbacks must re-read canonical attempt state so
                    # reconnect delivery can observe later finalization or
                    # recovery. Direct/non-managed callers have no canonical
                    # attempt and retain their cached idempotent acknowledgement.
                    canonical_acknowledgement = (
                        await self._read_submission_acknowledgement(context) if managed else None
                    )
                    submission_acknowledgement = canonical_acknowledgement or (
                        submission_acknowledgement
                        or SubmissionAcknowledgement(
                            disposition="durably_staged",
                            message=(
                                "submission is durably staged and pending successful runner "
                                "return; it is not yet accepted or completed"
                            ),
                            execution_id=context.execution_id,
                        )
                    )
                    return submission_acknowledgement
                if _requires_graph_patch_before_submit(context) and not graph_patch_submitted:
                    msg = (
                        "planner nodes must call submit_graph_patch before submit; "
                        "submit an accepted graph patch first"
                    )
                    raise ValueError(msg)
                if _requires_graph_patch_before_submit(context) and not graph_patch_accepted:
                    msg = (
                        "planner nodes must have an accepted submit_graph_patch before submit; "
                        "use patch rejection feedback to submit a corrected patch"
                    )
                    raise ValueError(msg)
                remaining_horizons = context.node_payload.get("reliable_plan_remaining_horizons")
                if (
                    isinstance(context.node_payload.get("reliable_plan_skeleton_id"), str)
                    and context.node_kind == "planner"
                    and context.node_role != "gap_planner"
                ):
                    completion_satisfied = (
                        non_gap_planner_completion_contract_satisfied(
                            await self._controller.read_projection(context.run_id),
                            context.node_id,
                        )
                        if managed
                        else graph_patch_accepted
                        and (
                            context.node_payload.get("semantic_stage") != "successor_planning"
                            or (
                                graph_successor_accepted
                                if isinstance(remaining_horizons, int) and remaining_horizons > 1
                                else graph_finalization_accepted
                            )
                        )
                    )
                    if not completion_satisfied:
                        if (
                            context.node_payload.get("semantic_stage") == "successor_planning"
                            and isinstance(remaining_horizons, int)
                            and remaining_horizons > 1
                        ):
                            raise ValueError(
                                "nonfinal reliable-plan horizon must create an accepted "
                                "successor planner, pass-gated by this batch verifier, "
                                "before submit"
                            )
                        if context.node_payload.get("semantic_stage") == "successor_planning":
                            raise ValueError(
                                "final reliable-plan horizon must atomically create the batch, "
                                "dynamic acceptance check, final audit, and final gate before submit"
                            )
                        raise ValueError(
                            "initial reliable-plan planner must atomically create discovery, "
                            "plan verification, and the first successor planner before submit"
                        )
                try:
                    contract = _submission_contract(context)
                    output_records = (
                        _semantic_output_records_from_submit_args(
                            context,
                            submit_args if submit_args is not None else {"outputs": {}},
                        )
                        if contract is not None and contract.requires_arguments
                        else None
                    )
                    if output_records is None:
                        acknowledgement = await self._submit_callback(context, grades)
                    else:
                        acknowledgement = await self._submit_callback(
                            context,
                            grades,
                            output_records=output_records,
                        )
                except ValueError as exc:
                    detail = str(exc)
                    if detail.startswith("submit callback rejected:"):
                        detail = detail.removeprefix("submit callback rejected:").strip()
                    rejection_category: SubmissionRejectionCategory = "submission_format_rejected"
                    rejection_evidence = SubmissionRejectionEvidence(
                        category=rejection_category,
                        final_diagnostic=detail[-2_048:] or "submission rejected",
                        evidence_truncated=len(detail) > 2_048,
                    )
                    if isinstance(exc, SubmissionQualityGateError) and isinstance(
                        exc.report, SubmissionGateCommandResult
                    ):
                        gate_evidence = gate_rejection_evidence(exc.report)
                        rejection_category = (
                            "validation_environment_blocked"
                            if gate_evidence.category == "validation_environment_blockage"
                            else "candidate_check_failed"
                        )
                        rejection_evidence = SubmissionRejectionEvidence(
                            category=rejection_category,
                            command=gate_evidence.command,
                            command_source=gate_evidence.command_source,
                            command_sha256=gate_evidence.command_sha256,
                            exit_code=gate_evidence.exit_code,
                            timed_out=gate_evidence.timed_out,
                            failed_test_ids=gate_evidence.failed_test_ids,
                            failed_test_ids_truncated=gate_evidence.failed_test_ids_truncated,
                            final_diagnostic=(gate_evidence.final_diagnostic or detail[-2_048:]),
                            stdout_sha256=gate_evidence.stdout_sha256,
                            stderr_sha256=gate_evidence.stderr_sha256,
                            stdout_bytes=gate_evidence.stdout_bytes,
                            stderr_bytes=gate_evidence.stderr_bytes,
                            stdout_truncated=gate_evidence.stdout_truncated,
                            stderr_truncated=gate_evidence.stderr_truncated,
                            evidence_truncated=gate_evidence.evidence_truncated,
                            failure_identity_status=gate_evidence.failure_identity_status,
                            semantic_failure_fingerprint=(
                                gate_evidence.semantic_failure_fingerprint
                            ),
                            durable_audit_reference=getattr(exc, "durable_audit_reference", None),
                        )
                    acknowledgement = SubmissionAcknowledgement(
                        disposition="rejected",
                        message=(f"{rejection_category}: {rejection_evidence.final_diagnostic}")[
                            -4_096:
                        ],
                        execution_id=context.execution_id,
                        rejection_category=rejection_category,
                        rejection_evidence=rejection_evidence,
                    )
                    if first_submission_rejection_category is None:
                        first_submission_rejection_category = rejection_category
                        first_submission_rejection_detail = rejection_evidence.final_diagnostic
                    submission_rejection_categories.add(rejection_category)
                    latest_submission_rejection = acknowledgement
                    raise SubmissionRejectedError(acknowledgement) from None
                submitted_callback = True
                submission_acknowledgement = acknowledgement or SubmissionAcknowledgement(
                    disposition="durably_staged",
                    message=(
                        "submission is durably staged and pending successful runner return; "
                        "it is not yet accepted or completed"
                    ),
                    execution_id=context.execution_id,
                )
                return submission_acknowledgement

            async def on_submit_graph_patch(patch_payload: dict[str, Any]) -> str:
                nonlocal graph_patch_submitted, graph_patch_accepted, graph_successor_accepted
                nonlocal graph_finalization_accepted
                graph_patch_submitted = True
                feedback = await self._submit_graph_patch_callback(context, patch_payload)
                if _graph_patch_feedback_accepted(feedback):
                    graph_patch_accepted = True
                    if _patch_payload_creates_successor_planner(patch_payload):
                        graph_successor_accepted = True
                    if _patch_payload_creates_finalization(patch_payload):
                        graph_finalization_accepted = True
                    patch_has_ops = _patch_payload_has_ops(patch_payload)
                    if context.node_role == "gap_planner":
                        context.node_payload["_accepted_gap_planner_patch_had_ops"] = patch_has_ops
                    if patch_has_ops:
                        context.node_payload["_accepted_graph_patch_had_ops"] = True
                return feedback

            async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
                grades.append((req_id, grade, grade_reason))

            async def on_output(lines: list[str]) -> None:
                if self._on_agent_output is not None:
                    await self._on_agent_output(context, lines)

            graph_mcp_token: str | None = None
            graph_mcp_url: str | None = None
            can_submit_patch = _can_submit_graph_patch(context)
            is_verifier = context.node_kind == "verifier"
            execution_context = self._execution_context(
                context,
                graph_patch_callback=(on_submit_graph_patch if can_submit_patch else None),
                working_dir=runner_worktree_path,
            )
            needs_typed_submit = (
                execution_context.submission_contract is not None
                and execution_context.submission_contract.requires_arguments
            )
            if self._graph_mcp_registry is not None and (
                can_submit_patch or is_verifier or needs_typed_submit
            ):
                import secrets

                from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server

                graph_mcp_server = build_graph_mcp_server(
                    on_submit_graph_patch,
                    on_grade if is_verifier else None,
                    allowed_tools=execution_context.available_tools,
                    required_tools=execution_context.required_tools,
                    on_submit=on_submit,
                    submission_contract=execution_context.submission_contract,
                )
                graph_mcp_token = secrets.token_urlsafe(24)
                self._graph_mcp_registry.register(
                    graph_mcp_token, graph_mcp_server.sse_app(mount_path="/")
                )
                graph_mcp_url = f"{self._base_url}/mcp-graph/{graph_mcp_token}/sse"
                execution_context.graph_mcp_url = graph_mcp_url

            try:
                started = self._monotonic()
                if managed:
                    result = await self._execute_runner_with_health(
                        context,
                        runner,
                        execution_context,
                        on_checklist_update,
                        on_submit,
                        on_output=on_output,
                        on_grade=on_grade if is_verifier else None,
                    )
                else:
                    # ``_run_agent`` remains a supported direct execution seam
                    # for callers that intentionally do not install the durable
                    # graph baseline/session boundary. Runtime observations are
                    # canonical workflow events, so attempting to emit them
                    # without that persistence boundary would both change the
                    # direct runner contract and create unverifiable health
                    # claims. Production outbox dispatch always enters through
                    # ``_run_agent_serialized`` with both prerequisites present.
                    result = await runner.execute(
                        execution_context,
                        on_checklist_update,
                        on_submit,
                        on_output=on_output,
                        on_grade=on_grade if is_verifier else None,
                    )
            finally:
                if graph_mcp_token is not None:
                    self._graph_mcp_registry.unregister(graph_mcp_token)  # type: ignore[union-attr]
            result.metrics.duration_ms = int((self._monotonic() - started) * 1000)
            from orchestrator.runners import extract_metrics_and_usage

            metrics, usage_by_model = extract_metrics_and_usage(result)
            if usage_by_model:
                await self._controller.record_node_usage(
                    context,
                    usage_by_model,
                    num_actions=metrics.num_actions,
                )
            if self._on_agent_usage is not None:
                try:
                    await self._on_agent_usage(context, result)
                except Exception:
                    logger.exception("graph usage observer failed")
            if not managed:
                if not submitted_callback:
                    await self._agent_died(context, "agent exited without submit")
            elif not submitted_callback and latest_submission_rejection is not None:
                rejection_reason = next(
                    category
                    for category in (
                        "validation_environment_blocked",
                        "candidate_check_failed",
                        "submission_format_rejected",
                    )
                    if category in submission_rejection_categories
                )
                diagnostic = (
                    latest_submission_rejection.rejection_evidence.final_diagnostic
                    if latest_submission_rejection.rejection_evidence is not None
                    else latest_submission_rejection.message
                )
                await self._request_runner_recovery(
                    context,
                    rejection_reason,
                    error_detail=diagnostic,
                    first_error_detail=(
                        f"{first_submission_rejection_category}: "
                        f"{first_submission_rejection_detail}"
                        if first_submission_rejection_category is not None
                        and first_submission_rejection_detail is not None
                        else None
                    ),
                    worktree_lock_held=True,
                )
            elif not result.success:
                await self._request_runner_recovery(
                    context,
                    "runner_died",
                    error_detail=result.error or "runner returned an unsuccessful result",
                    worktree_lock_held=True,
                )
            elif not submitted_callback:
                await self._request_runner_recovery(
                    context,
                    "runner_died",
                    error_detail="agent exited without a successful submit",
                    worktree_lock_held=True,
                )
            else:
                witnessed = await self._witness_runner_completion(context, worktree_lock_held=True)
                if witnessed:
                    await self._crash_barrier.wait_if_armed(
                        run_id=context.run_id,
                        execution_id=context.execution_id,
                        point="after_witness_pre_finalization",
                        observation=_crash_barrier_observation(
                            context,
                            point="after_witness_pre_finalization",
                            attempt_state="completion_witnessed",
                        ),
                    )
                    await self._finalize_runner_execution(context, worktree_lock_held=True)
        except asyncio.CancelledError:
            # Cancellation must never leave a mutable shared worktree attributed
            # to a live lease.  Shield the durable cleanup intent, then preserve
            # cancellation for the driver.
            if managed:
                reason: Literal["runner_died", "cancelled"] = (
                    "runner_died"
                    if cancellation is not None and cancellation.runner_loss
                    else "cancelled"
                )
                retry_after_recovery = (
                    cancellation.retry_after_recovery if cancellation is not None else False
                ) or await self._run_is_stopping_for_pause(context.run_id)
                await asyncio.shield(
                    self._request_runner_recovery(
                        context,
                        reason,
                        retry_after_recovery=retry_after_recovery,
                        worktree_lock_held=True,
                    )
                )
            raise
        except SubmissionRepairExhaustedError as exc:
            if managed:
                try:
                    await self._record_managed_runner_error(context, exc)
                except Exception:
                    logger.exception(
                        "submission repair exhaustion diagnostic could not be persisted "
                        "for execution %s",
                        context.execution_id,
                    )
                await self._request_runner_recovery(
                    context,
                    "submission_repair_exhausted",
                    error_detail=str(exc),
                    worktree_lock_held=True,
                )
            else:
                await self._invalid_execution_contract(context, str(exc))
        except InvalidExecutionContractError as exc:
            # Prompt assembly is the final production preflight for semantic
            # stage contracts.  A deterministic declaration defect is not a
            # runner failure: runner.execute has not been called, and the
            # lease must close through the typed invalid-contract outcome.
            await self._invalid_execution_contract(context, str(exc))
        except Exception as exc:
            if managed:
                # Record the runner exception before recovery mutates the
                # graph attempt.  Recovery events intentionally describe the
                # cleanup protocol, not the original transport failure; this
                # standard AgentErrorEvent is the API/journal-visible forensic
                # record and retains Codex's already-sanitized diagnostic.
                try:
                    await self._record_managed_runner_error(context, exc)
                except Exception:
                    logger.exception(
                        "managed graph runner failure diagnostic could not be persisted "
                        "for execution %s",
                        context.execution_id,
                    )
                logger.info("managed graph runner failed before finalization: %s", exc)
                if not isinstance(exc, CompromisedFileStateError):
                    await self._request_runner_recovery(
                        context,
                        _recovery_reason_for_finalization_error(exc),
                        error_detail=str(exc),
                        worktree_lock_held=True,
                    )
            else:
                await self._agent_died(context, str(exc))

    async def _record_managed_runner_error(
        self,
        context: GraphDispatchContext,
        exc: Exception,
    ) -> None:
        """Persist the original managed-runner failure before recovery starts."""
        from orchestrator.db import commit_with_event_outbox, create_wired_event_store_v2
        from orchestrator.workflow import AgentErrorEvent

        task_id = context.node_payload.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            task_id = context.node_id
        attempt_value = context.node_payload.get("attempt_number")
        attempt_num = attempt_value if isinstance(attempt_value, int) else 1
        event = AgentErrorEvent(
            run_id=context.run_id,
            task_id=task_id,
            attempt_num=attempt_num,
            error_type=type(exc).__name__,
            error_message=str(exc),
            node_id=context.node_id,
            execution_id=context.execution_id,
        )
        async with self._session_factory() as session:
            store = create_wired_event_store_v2(session)
            await store.append(event)
            await commit_with_event_outbox(session)

    async def _run_check(self, context: GraphDispatchContext) -> None:
        try:
            await self._acknowledge_start(context)
            async with self._artifact_store.publication():
                record = await _execute_check_command(
                    context,
                    self._artifact_store,
                    worktree_boundary=self._run_worktree_boundary,
                )
                await self._submit_check_result(context, record)
        except Exception as exc:
            await self._agent_died(context, str(exc))

    async def _run_final_gate(self, context: GraphDispatchContext) -> None:
        try:
            await self._acknowledge_start(context)
            observed_position = await self._current_position(context.run_id)
            await self._handle_command_retry_stale(
                context.run_id,
                observed_position,
                "evaluate_final_gate",
                {
                    "node_id": context.node_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                },
            )
        except Exception as exc:
            await self._agent_died(context, str(exc))

    async def _run_join(self, context: GraphDispatchContext) -> None:
        try:
            await self._acknowledge_start(context)
            observed_position = await self._current_position(context.run_id)
            await self._handle_command_retry_stale(
                context.run_id,
                observed_position,
                "evaluate_join",
                {
                    "node_id": context.node_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                },
            )
        except Exception as exc:
            await self._agent_died(context, str(exc))

    async def _build_dispatch_context(self, item: OutboxItem) -> GraphDispatchContext:
        return await assemble_graph_dispatch_context(
            self._session_factory,
            item,
            worktree_path=self._worktree_path,
        )

    def _execution_context(
        self,
        context: GraphDispatchContext,
        graph_patch_callback: Callable[[dict[str, Any]], Awaitable[str]] | None = None,
        graph_mcp_url: str | None = None,
        working_dir: str | None = None,
    ) -> ExecutionContext:
        node = context.node_payload
        prompt = _prompt_for_node(context)
        available_tools = resolve_dispatch_tools(
            node_kind=context.node_kind,
            node_role=context.node_role,
            available_tools=_available_tools_for_context(context),
        )
        reliable_plan = is_reliable_plan_planner(
            node_kind=context.node_kind, node_payload=context.node_payload
        )
        return ExecutionContext(
            run_id=context.run_id,
            task_id=str(node.get("task_id") or node.get("task_region_id") or context.node_id),
            working_dir=working_dir or context.worktree_path,
            prompt=prompt,
            requirements=context.requirements,
            step_id=cast(str | None, node.get("step_id")),
            node_id=context.node_id,
            node_kind=context.node_kind,
            node_role=context.node_role,
            graph_patch_callback=graph_patch_callback,
            graph_mcp_url=graph_mcp_url,
            available_tools=(
                list(available_tools)
                if context.node_kind == "verifier" or available_tools
                else None
            ),
            required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES if reliable_plan else (),
            mcp_servers=cast(Any, node.get("mcp_servers")),
            work_mode=_work_mode(node.get("work_mode")),
            submission_contract=_submission_contract(context),
        )

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "acknowledge_start",
            {
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "execution_id": context.execution_id,
                "prompt_summary": _prompt_summary_for_node(context),
            },
        )

    async def _record_start_heartbeat(self, context: GraphDispatchContext) -> None:
        result = await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "record_heartbeat",
            {
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "generation": context.lease_generation,
                "ttl_seconds": MANAGED_LEASE_TTL_SECONDS,
            },
        )
        rejection = next(
            (
                event
                for event in result.events
                if event.event_type == "command_rejected"
                and event.payload.get("command_type") == "record_heartbeat"
            ),
            None,
        )
        if rejection is not None:
            reason = rejection.payload.get("reason") or "record_heartbeat rejected"
            raise ValueError(str(reason))

    async def _execute_runner_with_health(
        self,
        context: GraphDispatchContext,
        runner: AgentRunner,
        execution_context: ExecutionContext,
        on_checklist_update: Callable[[str, ChecklistStatus, str | None], Awaitable[None]],
        on_submit: Callable[..., Awaitable[SubmissionAcknowledgement]],
        *,
        on_output: Callable[[list[str]], Awaitable[None]],
        on_grade: Callable[[str, str, str | None], Awaitable[None]] | None,
    ) -> ExecutionResult:
        """Execute under the runner's explicit runtime-observation contract."""
        try:
            runner_info = runner.info
            runner_type = runner_info.agent_runner_type.value
            capability = runner_info.runtime_observation
        except (AttributeError, TypeError, ValueError):
            runner_type = type(runner).__name__[:128]
            capability = None

        parameters = inspect.signature(runner.execute).parameters
        if capability is None or capability.mode != "host_process":
            mode = capability.mode if capability is not None else "unsupported"
            reason = (
                capability.reason
                if capability is not None
                else "runner did not provide a valid runtime-observation capability"
            )
            await self._record_runner_runtime_observation(
                context,
                runner_type=runner_type,
                identity=None,
                state=("non_process_owning" if mode == "non_process_owning" else "unsupported"),
                reason=reason,
            )
            return await runner.execute(
                execution_context,
                on_checklist_update,
                on_submit,
                on_output=on_output,
                on_grade=on_grade,
            )

        if "on_agent_metadata" not in parameters:
            reason = (
                "runner declared host-process observation but its execute boundary "
                "cannot receive process metadata"
            )
            await self._record_runner_runtime_observation(
                context,
                runner_type=runner_type,
                identity=None,
                state="unreported",
                reason=reason,
                root_error=reason,
            )
            raise RunnerProcessMissingError(reason)

        identity: _RunnerProcessIdentity | None = None
        metadata_received = asyncio.Event()
        metadata_error: RunnerProcessMissingError | None = None

        await self._record_runner_runtime_observation(
            context,
            runner_type=runner_type,
            identity=None,
            state="not_yet_reported",
            reason=(
                "runner declared host-process observation; awaiting exact PID metadata "
                f"for at most {self._runner_metadata_start_deadline:g} seconds"
            ),
        )

        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            nonlocal identity, metadata_error
            raw_pid = metadata.get("pid")
            if not isinstance(raw_pid, int) or isinstance(raw_pid, bool) or raw_pid <= 0:
                reason = (
                    "runner reported invalid PID metadata: pid must be a positive integer; "
                    f"received {raw_pid!r}"
                )
                metadata_error = RunnerProcessMissingError(reason)
                await self._record_runner_runtime_observation(
                    context,
                    runner_type=runner_type,
                    identity=None,
                    state="invalid_metadata",
                    reason=reason,
                    root_error=reason,
                )
                metadata_received.set()
                return
            identity = _read_runner_process_identity(raw_pid)
            reason = (
                "exact PID, process create time, and command hash captured"
                if identity is not None
                else f"runner reported PID {raw_pid}, but no live process identity existed"
            )
            if identity is None:
                metadata_error = RunnerProcessMissingError(reason)
            else:
                self._verified_runner_identities[context.execution_id] = identity
            metadata_received.set()
            await self._record_runner_runtime_observation(
                context,
                runner_type=runner_type,
                identity=identity,
                state="exact_identity_available" if identity is not None else "missing",
                reason=reason,
                root_error=None if identity is not None else reason,
            )

        runner_task = asyncio.create_task(
            runner.execute(
                execution_context,
                on_checklist_update,
                on_submit,
                on_output=on_output,
                on_grade=on_grade,
                on_agent_metadata=on_agent_metadata,
            )
        )

        async def monitor() -> None:
            try:
                await asyncio.wait_for(
                    metadata_received.wait(), timeout=self._runner_metadata_start_deadline
                )
            except asyncio.TimeoutError:
                reason = (
                    "runner did not report promised host-process metadata within "
                    f"{self._runner_metadata_start_deadline:g} seconds"
                )
                await self._record_runner_runtime_observation(
                    context,
                    runner_type=runner_type,
                    identity=None,
                    state="unreported",
                    reason=reason,
                    root_error=reason,
                )
                raise RunnerProcessMissingError(reason) from None
            if metadata_error is not None:
                raise metadata_error
            while not runner_task.done():
                current = identity
                if current is None:
                    raise RunnerProcessMissingError(
                        f"runner process identity missing for execution {context.execution_id}"
                    )
                await asyncio.sleep(self._runner_health_interval)
                if runner_task.done():
                    return
                if not _runner_process_identity_is_alive(current):
                    self._verified_runner_identities.pop(context.execution_id, None)
                    detail = (
                        "runner process identity disappeared or changed "
                        f"(pid={current.pid}, execution={context.execution_id})"
                    )
                    await self._record_runner_runtime_observation(
                        context,
                        runner_type=runner_type,
                        identity=current,
                        state="missing",
                        reason=detail,
                        root_error=detail,
                    )
                    raise RunnerProcessMissingError(detail)
                await self._record_start_heartbeat(context)
                await self._record_runner_runtime_observation(
                    context,
                    runner_type=runner_type,
                    identity=current,
                    state="exact_identity_available",
                    reason="exact runner process identity reverified; lease heartbeat renewed",
                )

        monitor_task = asyncio.create_task(monitor())
        try:
            done, _ = await asyncio.wait(
                {runner_task, monitor_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if monitor_task in done:
                monitor_error = monitor_task.exception()
                if monitor_error is not None:
                    runner_task.cancel()
                    await asyncio.gather(runner_task, return_exceptions=True)
                    raise monitor_error
            result = await runner_task
            if not metadata_received.is_set():
                reason = "runner completed before reporting its promised host-process metadata"
                await self._record_runner_runtime_observation(
                    context,
                    runner_type=runner_type,
                    identity=None,
                    state="never_started",
                    reason=reason,
                    root_error=reason,
                )
                raise RunnerProcessMissingError(reason)
            if metadata_error is not None:
                raise metadata_error
            if identity is not None:
                await self._record_runner_runtime_observation(
                    context,
                    runner_type=runner_type,
                    identity=identity,
                    state="exited",
                    reason="runner returned after an exact process identity was observed",
                )
            return result
        finally:
            self._verified_runner_identities.pop(context.execution_id, None)
            if not monitor_task.done():
                monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)

    async def _record_runner_runtime_observation(
        self,
        context: GraphDispatchContext,
        *,
        runner_type: str,
        identity: _RunnerProcessIdentity | None,
        state: Literal[
            "not_yet_reported",
            "exact_identity_available",
            "invalid_metadata",
            "unreported",
            "unsupported",
            "non_process_owning",
            "never_started",
            "missing",
            "exited",
        ],
        reason: str,
        root_error: str | None = None,
    ) -> None:
        from orchestrator.db import commit_with_event_outbox, create_wired_event_store_v2
        from orchestrator.workflow import GraphRunnerRuntimeObserved

        event = GraphRunnerRuntimeObserved(
            timestamp=self._utcnow(),
            run_id=context.run_id,
            node_id=context.node_id,
            execution_id=context.execution_id,
            lease_id=context.lease_id,
            lease_generation=context.lease_generation,
            runner_type=runner_type[:128],
            state=state,
            pid=identity.pid if identity is not None else None,
            process_create_time=(identity.create_time if identity is not None else None),
            command_sha256=(identity.command_sha256 if identity is not None else None),
            reason=reason[:1_000],
            root_error=root_error[:1_000] if root_error else None,
        )
        async with self._session_factory() as session:
            await create_wired_event_store_v2(session).append(event)
            await commit_with_event_outbox(session)

    async def _submit_callback(
        self,
        context: GraphDispatchContext,
        grades: list[tuple[str, str, str | None]],
        *,
        output_records: list[dict[str, object]] | None = None,
        worktree_lock_held: bool | None = None,
    ) -> SubmissionAcknowledgement:
        if worktree_lock_held is None:
            # Runner tool callbacks can arrive on an MCP request task while the
            # serialized runner task owns the lock.  The durable in-memory
            # baseline is the executor-local proof that this callback belongs
            # to that already-locked mutation boundary.
            worktree_lock_held = context.execution_id in self._file_state_baselines
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                return await self._submit_callback(
                    context,
                    grades,
                    output_records=output_records,
                    worktree_lock_held=True,
                )
        # A duplicate callback may be delivered after a lost tool response or
        # after the runner transport reconnects. Resolve an already-conclusive
        # attempt before capturing any new boundary. This makes all three
        # acknowledgements reachable through the production callback while the
        # first successful in-turn callback remains strictly staged.
        existing_acknowledgement = await self._read_submission_acknowledgement(context)
        if existing_acknowledgement is not None:
            return existing_acknowledgement
        submitted_records = (
            list(output_records)
            if output_records is not None
            else _output_records_for_submit(context, grades)
        )
        output_contract_error = _declared_output_contract_error(context, submitted_records)
        if output_contract_error is not None:
            raise ValueError(output_contract_error)
        observed_position = await self._current_position(context.run_id)
        submitted_records = await self._run_worktree_boundary(
            _controller_ready_semantic_artifact_records,
            submitted_records,
            context.graph_projection,
            self._artifact_store,
            lock_held=True,
            offload=False,
        )
        boundary = await self._run_worktree_boundary(
            capture_file_state_boundary,
            worktree_path=context.worktree_path,
            run_id=context.run_id,
            node_id=context.node_id,
            execution_id=context.execution_id,
            base_snapshot_id=context.base_snapshot_id,
            policy=_authority_file_state_policy(context),
            baseline=self._file_state_baselines.get(context.execution_id),
            lock_held=True,
        )
        if boundary.rejection_record is not None:
            payload: dict[str, object] = {
                "output_records": [],
                "file_state_rejected": boundary.rejection_record,
            }
            result = await self._handle_command_retry_stale(
                context.run_id,
                observed_position,
                "stage_runner_submission",
                {
                    "node_id": context.node_id,
                    "execution_id": context.execution_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                    "base_snapshot_id": context.base_snapshot_id,
                    "observed_graph_position": observed_position,
                    "idempotency_key": (
                        f"{context.dispatch_event_id}:{context.execution_id}:file-state-rejected"
                    ),
                    "payload_hash": _payload_hash(payload),
                    "payload": payload,
                    # A rejected file-state boundary has no accepted snapshot
                    # to stage.  Supply a valid, empty protocol envelope so
                    # the managed command can durably emit the rejection
                    # before recovery restores the worktree.
                    "staged_snapshot_id": context.base_snapshot_id,
                    "staged_snapshot_ref": (
                        f"refs/orchestrator/snapshots/{context.base_snapshot_id}"
                    ),
                    "staged_commit_sha": "0" * 40,
                    "staged_tree_sha": "0" * 40,
                    "boundary_hash": boundary_manifest_hash(
                        "0" * 40, [], [], context.cache_authority_hash
                    ),
                    "boundary_entries": [],
                    "cache_authority_hash": context.cache_authority_hash,
                    "cache_roots": [],
                    "cache_status_evidence": [],
                    "complete_node": False,
                },
            )
            if any(event.event_type == "file_state_rejected" for event in result.events):
                await self._request_runner_recovery(
                    context,
                    "runner_died",
                    publish_snapshot_ref=False,
                    worktree_lock_held=True,
                )
                raise CompromisedFileStateError(
                    "runner file-state boundary rejected; managed recovery requested"
                )
            raise ValueError("submit callback rejected: file-state boundary rejected")
        payload = {
            "output_records": submitted_records,
        }
        staged = await self._run_worktree_boundary(
            _capture_runner_boundary,
            context.worktree_path,
            _authority_file_state_policy(context),
            _authority_cache_policy(context),
            "submission",
            snapshot_id=_managed_snapshot_id("staged", context.execution_id),
            force_include_paths=list(boundary.force_include_paths),
            lock_held=True,
        )
        submission_gate_report: SubmissionGateReport | None = None
        submission_gate_baseline: SubmissionGateBaseline | None = None
        if _requires_submission_quality_gate(context):
            submission_gate_baseline = await self._load_submission_gate_baseline(context)
            resolved_commands = submission_gate_commands_from_baseline(submission_gate_baseline)
            try:
                submission_gate_report = await enforce_submission_quality_gate(
                    run_id=context.run_id,
                    node_id=context.node_id,
                    execution_id=context.execution_id,
                    lease_id=context.lease_id,
                    lease_generation=context.lease_generation,
                    base_snapshot_id=context.base_snapshot_id,
                    base_tree_sha=submission_gate_baseline.base_tree_sha,
                    node_payload=context.node_payload,
                    dynamic_feature=routine_snapshot_dynamic_feature_view(context.graph_projection),
                    worktree_path=context.worktree_path,
                    baseline=submission_gate_baseline,
                    candidate_tree_sha=staged.snapshot.tree_sha,
                    snapshot_commit_sha=staged.snapshot.commit_sha,
                    resolved_commands=resolved_commands,
                )
            except SubmissionQualityGateError as exc:
                durable_audit_reference = await self._persist_submission_gate_failure(
                    context,
                    baseline=submission_gate_baseline,
                    candidate_tree_sha=staged.snapshot.tree_sha,
                    error=exc,
                )
                setattr(exc, "durable_audit_reference", durable_audit_reference)
                raise
            await self._persist_submission_gate_audit(
                context,
                phase="submission",
                base_tree_sha=submission_gate_baseline.base_tree_sha,
                candidate_tree_sha=staged.snapshot.tree_sha,
                status=submission_gate_report.status,
                failure_fingerprint=None,
                report=submission_gate_report.model_dump(mode="json"),
            )
        submitted_records.append(
            file_state_output_record(
                boundary,
                staged.snapshot,
                node_id=context.node_id,
                execution_id=context.execution_id,
                base_snapshot_id=context.base_snapshot_id,
            )
        )
        payload_bytes = canonical_callback_payload_bytes(payload)
        payload_hash, payload_size_bytes = callback_payload_identity(payload)

        async def publish_callback_artifact_and_stage() -> Any:
            # Keep the cross-process CAS lock through the canonical graph append.
            # The outer worktree boundary helper shields this complete async
            # transaction, including its internally offloaded filesystem work.
            async with self._artifact_store.publication():
                payload_ref = await self._artifact_store.put(
                    payload_bytes,
                    media_type="application/json",
                    encoding="utf-8",
                )
                payload_data: dict[str, object] = {
                    "node_id": context.node_id,
                    "execution_id": context.execution_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                    "base_snapshot_id": context.base_snapshot_id,
                    "observed_graph_position": observed_position,
                    "idempotency_key": (
                        f"{context.dispatch_event_id}:{context.execution_id}:submit"
                    ),
                    "payload_hash": payload_hash,
                    "payload": payload,
                    "payload_ref": payload_ref.model_dump(mode="json"),
                    "staged_snapshot_id": staged.snapshot.id,
                    "staged_snapshot_ref": staged.snapshot.ref,
                    "staged_commit_sha": staged.snapshot.commit_sha,
                    "staged_tree_sha": staged.snapshot.tree_sha,
                    "boundary_hash": staged.boundary_hash,
                    "boundary_entries": staged.entries,
                    "cache_authority_hash": context.cache_authority_hash,
                    "cache_roots": staged.cache_roots,
                    "cache_status_evidence": staged.cache_status_evidence,
                }
                if submission_gate_report is not None:
                    payload_data["validation_witness"] = bind_submission_gate_witness(
                        submission_gate_report,
                        snapshot_id=staged.snapshot.id,
                        snapshot_ref=staged.snapshot.ref,
                        commit_sha=staged.snapshot.commit_sha,
                        tree_sha=staged.snapshot.tree_sha,
                        boundary_hash=staged.boundary_hash,
                        baseline=submission_gate_baseline,
                    ).model_dump(mode="json")
                if payload_ref.size_bytes != payload_size_bytes:
                    raise ValueError("artifact store returned a noncanonical callback size")
                return await self._handle_command_retry_stale(
                    context.run_id,
                    observed_position,
                    "stage_runner_submission",
                    payload_data,
                )

        result = await self._run_worktree_boundary(
            publish_callback_artifact_and_stage,
            lock_held=True,
            offload=False,
        )
        conflict_reason = _callback_conflict_reason(result.events)
        if conflict_reason is not None:
            raise ValueError(f"submit callback rejected: {conflict_reason}")
        await self._run_worktree_boundary(
            publish_snapshot,
            context.worktree_path,
            staged.snapshot,
            lock_held=True,
        )
        await self._crash_barrier.wait_if_armed(
            run_id=context.run_id,
            execution_id=context.execution_id,
            point="after_staging_pre_witness",
            observation=_crash_barrier_observation(
                context,
                point="after_staging_pre_witness",
                attempt_state="submission_staged",
            ),
        )
        # Stage is deliberately non-terminal.  Gatekeeper classification and
        # downstream binding may only observe accepted records after finalization.
        return SubmissionAcknowledgement(
            disposition="durably_staged",
            message=(
                "submission is durably staged and pending successful runner return; "
                "it is not yet accepted or completed"
            ),
            execution_id=context.execution_id,
            graph_position=result.projection_position,
        )

    async def _read_submission_acknowledgement(
        self,
        context: GraphDispatchContext,
    ) -> SubmissionAcknowledgement | None:
        """Map canonical attempt state to the three runner-facing dispositions."""
        projection = await self._controller.read_projection(context.run_id)
        attempt = execution_attempts_view(projection).get(context.execution_id)
        if attempt is None or attempt.state == "baseline_captured":
            return None
        graph_position = await self._current_position(context.run_id)
        if attempt.state == "finalized" and attempt.completion_disposition == "finalized_accepted":
            return SubmissionAcknowledgement(
                disposition="finalized_accepted",
                message="submission is durably finalized and accepted",
                execution_id=context.execution_id,
                graph_position=graph_position,
            )
        if attempt.state in {"submission_staged", "completion_witnessed"}:
            return SubmissionAcknowledgement(
                disposition="durably_staged",
                message=(
                    "submission is durably staged and pending finalization; "
                    "it is not yet accepted or completed"
                ),
                execution_id=context.execution_id,
                graph_position=graph_position,
            )
        reason = attempt.recovery_reason or attempt.completion_disposition or attempt.state
        return SubmissionAcknowledgement(
            disposition="rejected",
            message=(f"submission was not accepted; durable recovery disposition: {reason}")[
                :4_096
            ],
            execution_id=context.execution_id,
            graph_position=graph_position,
        )

    async def _ensure_submission_gate_baseline(
        self,
        context: GraphDispatchContext,
        boundary: RunnerBoundaryCapture,
    ) -> SubmissionGateBaseline:
        """Capture a pre-agent baseline once and make it canonical before execution."""
        existing = await self._find_submission_gate_baseline(context)
        if existing is not None:
            if existing.base_tree_sha != boundary.snapshot.tree_sha:
                raise SubmissionQualityGateError(
                    "submission quality gate baseline does not match the durable "
                    "runner baseline tree"
                )
            return existing
        resolved_commands = await self._run_worktree_boundary(
            resolve_submission_gate_commands,
            node_payload=context.node_payload,
            dynamic_feature=routine_snapshot_dynamic_feature_view(context.graph_projection),
            worktree_path=context.worktree_path,
            lock_held=True,
        )
        baseline = await capture_submission_gate_baseline(
            run_id=context.run_id,
            node_id=context.node_id,
            execution_id=context.execution_id,
            lease_id=context.lease_id,
            lease_generation=context.lease_generation,
            base_snapshot_id=context.base_snapshot_id,
            base_tree_sha=boundary.snapshot.tree_sha,
            node_payload=context.node_payload,
            dynamic_feature=routine_snapshot_dynamic_feature_view(context.graph_projection),
            worktree_path=context.worktree_path,
            snapshot_commit_sha=boundary.snapshot.commit_sha,
            resolved_commands=resolved_commands,
        )
        aggregate_fingerprint = (
            hashlib.sha256(
                json.dumps(
                    sorted(baseline.failure_fingerprints),
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if baseline.failure_fingerprints
            else None
        )
        await self._persist_submission_gate_audit(
            context,
            phase="baseline",
            base_tree_sha=baseline.base_tree_sha,
            candidate_tree_sha=None,
            status=baseline.status,
            failure_fingerprint=aggregate_fingerprint,
            report=baseline.model_dump(mode="json"),
        )
        return baseline

    async def _find_submission_gate_baseline(
        self, context: GraphDispatchContext
    ) -> SubmissionGateBaseline | None:
        from orchestrator.db import GraphSubmissionGateAuditRepository

        async with self._session_factory() as session:
            audit = await GraphSubmissionGateAuditRepository(session).latest_baseline(
                context.run_id, context.execution_id
            )
        if audit is None:
            return None
        try:
            baseline = SubmissionGateBaseline.model_validate(audit.report)
        except ValidationError as exc:
            raise SubmissionQualityGateError(
                "durable submission quality gate baseline is malformed"
            ) from exc
        expected = (
            context.run_id,
            context.node_id,
            context.execution_id,
            context.lease_id,
            context.lease_generation,
            context.base_snapshot_id,
        )
        observed = (
            baseline.run_id,
            baseline.node_id,
            baseline.execution_id,
            baseline.lease_id,
            baseline.lease_generation,
            baseline.base_snapshot_id,
        )
        if observed != expected:
            raise SubmissionQualityGateError(
                "durable submission quality gate baseline authority does not match "
                "the active execution"
            )
        return baseline

    async def _load_submission_gate_baseline(
        self, context: GraphDispatchContext
    ) -> SubmissionGateBaseline:
        baseline = await self._find_submission_gate_baseline(context)
        if baseline is None:
            raise SubmissionQualityGateError(
                "submission quality gate has no durable pre-change baseline for "
                "the active execution"
            )
        return baseline

    async def _persist_submission_gate_failure(
        self,
        context: GraphDispatchContext,
        *,
        baseline: SubmissionGateBaseline,
        candidate_tree_sha: str,
        error: SubmissionQualityGateError,
    ) -> str:
        failed_result = (
            error.report if isinstance(error.report, SubmissionGateCommandResult) else None
        )
        report: dict[str, Any] = {
            "schema_version": 1,
            "message": str(error)[:4_096],
            "results": (
                [failed_result.model_dump(mode="json")] if failed_result is not None else []
            ),
        }
        return await self._persist_submission_gate_audit(
            context,
            phase="submission",
            base_tree_sha=baseline.base_tree_sha,
            candidate_tree_sha=candidate_tree_sha,
            status="failed",
            failure_fingerprint=(
                submission_gate_failure_fingerprint(failed_result)
                if failed_result is not None
                else None
            ),
            report=report,
        )

    async def _persist_submission_gate_audit(
        self,
        context: GraphDispatchContext,
        *,
        phase: str,
        base_tree_sha: str,
        candidate_tree_sha: str | None,
        status: str,
        failure_fingerprint: str | None,
        report: dict[str, Any],
    ) -> str:
        """Atomically append canonical provenance and its disposable read model."""
        from orchestrator.db import (
            GraphSubmissionGateAuditRepository,
            commit_with_event_outbox,
            create_wired_event_store_v2,
        )
        from orchestrator.workflow import GraphSubmissionGateAudited

        timestamp = self._utcnow()
        event = GraphSubmissionGateAudited(
            timestamp=timestamp,
            run_id=context.run_id,
            node_id=context.node_id,
            execution_id=context.execution_id,
            phase=phase,
            base_snapshot_id=context.base_snapshot_id,
            base_tree_sha=base_tree_sha,
            candidate_tree_sha=candidate_tree_sha,
            status=status,
            failure_fingerprint=failure_fingerprint,
            report=report,
        )
        async with self._session_factory() as session:
            (stored,) = await create_wired_event_store_v2(session).append(event)
            await GraphSubmissionGateAuditRepository(session).append(
                canonical_position=stored.position,
                run_id=event.run_id,
                node_id=event.node_id,
                execution_id=event.execution_id,
                phase=event.phase,
                base_snapshot_id=event.base_snapshot_id,
                base_tree_sha=event.base_tree_sha,
                candidate_tree_sha=event.candidate_tree_sha,
                status=event.status,
                failure_fingerprint=event.failure_fingerprint,
                report=event.report,
                created_at=event.timestamp,
            )
            await commit_with_event_outbox(session)
        return f"graph-event:{context.run_id}:{stored.position}"

    async def _record_runner_baseline(
        self, context: GraphDispatchContext, baseline: RunnerBoundaryCapture
    ) -> None:
        result = await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "record_runner_baseline",
            {
                "execution_id": context.execution_id,
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "lease_base_snapshot_id": context.base_snapshot_id,
                "baseline_snapshot_id": baseline.snapshot.id,
                "baseline_snapshot_ref": baseline.snapshot.ref,
                "baseline_commit_sha": baseline.snapshot.commit_sha,
                "baseline_tree_sha": baseline.snapshot.tree_sha,
                "entries": baseline.entries,
                "boundary_hash": baseline.boundary_hash,
                "cache_authority_hash": context.cache_authority_hash,
                "cache_roots": baseline.cache_roots,
                "cache_status_evidence": baseline.cache_status_evidence,
            },
        )
        reason = _callback_conflict_reason(result.events)
        if reason is not None:
            raise ValueError(f"runner baseline rejected: {reason}")

    async def _witness_runner_completion(
        self,
        context: GraphDispatchContext,
        *,
        worktree_lock_held: bool = False,
    ) -> bool:
        """Capture and persist runner success before any callback is accepted."""
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                return await self._witness_runner_completion(context, worktree_lock_held=True)
        projection = await self._controller.read_projection(context.run_id)
        attempt = execution_attempts_view(projection).get(context.execution_id)
        if attempt is None or attempt.state != "submission_staged":
            raise ValueError("runner execution has no staged callback to witness")
        file_state = await self._run_worktree_boundary(
            capture_file_state_boundary,
            worktree_path=context.worktree_path,
            run_id=context.run_id,
            node_id=context.node_id,
            execution_id=context.execution_id,
            base_snapshot_id=context.base_snapshot_id,
            policy=_authority_file_state_policy(context),
            baseline=self._file_state_baselines.get(context.execution_id),
            lock_held=True,
        )
        capture = await self._run_worktree_boundary(
            _capture_runner_boundary,
            context.worktree_path,
            _authority_file_state_policy(context),
            _authority_cache_policy(context),
            "final",
            snapshot_id=_managed_snapshot_id("final", context.execution_id),
            force_include_paths=list(file_state.force_include_paths),
            lock_held=True,
        )
        result = await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "witness_runner_completion",
            {
                "execution_id": context.execution_id,
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "staged_payload_hash": attempt.payload_hash,
                "staged_payload_size_bytes": attempt.payload_size_bytes,
                "staged_snapshot_id": attempt.staged_snapshot_id,
                "staged_snapshot_ref": attempt.staged_snapshot_ref,
                "staged_commit_sha": attempt.staged_commit_sha,
                "staged_tree_sha": attempt.staged_tree_sha,
                "staged_boundary_hash": attempt.staged_boundary_hash,
                "runner_return_kind": "successful_return",
                "final_snapshot_id": capture.snapshot.id,
                "final_snapshot_ref": capture.snapshot.ref,
                "final_commit_sha": capture.snapshot.commit_sha,
                "final_tree_sha": capture.snapshot.tree_sha,
                "boundary_hash": capture.boundary_hash,
                "boundary_entries": capture.entries,
                "cache_authority_hash": context.cache_authority_hash,
                "cache_roots": capture.cache_roots,
                "cache_status_evidence": capture.cache_status_evidence,
            },
        )
        reason = _callback_conflict_reason(result.events)
        if reason is not None:
            raise ValueError(f"runner completion witness rejected: {reason}")
        await self._run_worktree_boundary(
            publish_snapshot,
            context.worktree_path,
            capture.snapshot,
            lock_held=True,
        )
        return any(
            event.event_type == "runner_completion_witnessed" for event in result.events
        ) and not any(
            event.event_type in {"runner_boundary_mismatch", "runner_recovery_requested"}
            for event in result.events
        )

    async def _finalize_runner_execution(
        self,
        context: GraphDispatchContext,
        *,
        worktree_lock_held: bool = False,
    ) -> None:
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                await self._finalize_runner_execution(context, worktree_lock_held=True)
            return
        callback_payload = await self._resolve_staged_callback_payload(
            context.run_id,
            context.execution_id,
            worktree_lock_held=True,
        )
        projection = await self._controller.read_projection(context.run_id)
        attempt = execution_attempts_view(projection).get(context.execution_id)
        if attempt is None or attempt.state != "completion_witnessed":
            raise ValueError("runner completion and final boundary are not durably witnessed")
        exact_identity = (
            attempt.final_snapshot_id,
            attempt.final_snapshot_ref,
            attempt.final_commit_sha,
            attempt.final_tree_sha,
            attempt.final_boundary_hash,
        )
        if not all(isinstance(value, str) and value for value in exact_identity):
            raise ValueError("durable completion witness has incomplete snapshot identity")
        await self._run_worktree_boundary(
            verify_snapshot_ref,
            context.worktree_path,
            cast(str, attempt.staged_snapshot_id),
            expected_ref=cast(str, attempt.staged_snapshot_ref),
            expected_commit_sha=cast(str, attempt.staged_commit_sha),
            expected_tree_sha=cast(str, attempt.staged_tree_sha),
            lock_held=True,
        )
        await self._run_worktree_boundary(
            verify_snapshot_ref,
            context.worktree_path,
            cast(str, attempt.final_snapshot_id),
            expected_ref=cast(str, attempt.final_snapshot_ref),
            expected_commit_sha=cast(str, attempt.final_commit_sha),
            expected_tree_sha=cast(str, attempt.final_tree_sha),
            lock_held=True,
        )
        result = await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "finalize_runner_execution",
            {
                "execution_id": context.execution_id,
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "final_snapshot_id": attempt.final_snapshot_id,
                "final_snapshot_ref": attempt.final_snapshot_ref,
                "final_commit_sha": attempt.final_commit_sha,
                "final_tree_sha": attempt.final_tree_sha,
                "boundary_hash": attempt.final_boundary_hash,
                "boundary_entries": [
                    entry.model_dump(mode="json") for entry in attempt.final_boundary_entries
                ],
                "cache_authority_hash": context.cache_authority_hash,
                "cache_roots": [
                    root.model_dump(mode="json")
                    for root in attempt.final_cache_roots
                    if not isinstance(root, str)
                ],
                "cache_status_evidence": [
                    item.model_dump(mode="json") for item in attempt.final_cache_status_evidence
                ],
                "callback_payload": callback_payload,
            },
        )
        reason = _callback_conflict_reason(result.events)
        if reason is not None:
            raise ValueError(f"runner finalization rejected: {reason}")
        await self._record_gatekeeper_verdicts(context, result.projection_position, result.events)

    async def _resolve_staged_callback_payload(
        self,
        run_id: str,
        execution_id: str,
        *,
        worktree_lock_held: bool = False,
    ) -> dict[str, Any]:
        """Resolve and integrity-check the callback body needed for finalization."""
        projection = await self._controller.read_projection(run_id)
        attempt = execution_attempts_view(projection).get(execution_id)
        if attempt is None or attempt.state not in {"submission_staged", "completion_witnessed"}:
            raise ValueError("runner execution has no staged callback")
        if attempt.payload_ref is None:
            legacy = thaw_json(attempt.payload)
            if not isinstance(legacy, dict):
                raise ValueError("legacy staged callback payload is unavailable")
            return cast(dict[str, Any], legacy)
        ref = StoredArtifactRef.model_validate(attempt.payload_ref.model_dump(mode="json"))
        content = await self._run_worktree_boundary(
            self._artifact_store.read,
            ref,
            lock_held=worktree_lock_held,
            offload=False,
        )
        try:
            decoded = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("staged callback artifact is not canonical JSON") from exc
        if not isinstance(decoded, dict):
            raise ArtifactIntegrityError("staged callback artifact must contain an object")
        payload = cast(dict[str, Any], decoded)
        payload_hash, payload_size = callback_payload_identity(payload)
        if payload_hash != attempt.payload_hash or payload_size != attempt.payload_size_bytes:
            raise ArtifactIntegrityError("staged callback artifact does not match durable identity")
        return payload

    async def _request_runner_recovery(
        self,
        context: GraphDispatchContext,
        reason: Literal[
            "runner_died",
            "cancelled",
            "staged_artifact_missing",
            "staged_artifact_corrupt",
            "submission_repair_exhausted",
            "submission_format_rejected",
            "candidate_check_failed",
            "validation_environment_blocked",
        ],
        *,
        publish_snapshot_ref: bool = True,
        error_detail: str | None = None,
        first_error_detail: str | None = None,
        retry_after_recovery: bool = False,
        worktree_lock_held: bool = False,
    ) -> None:
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                await self._request_runner_recovery(
                    context,
                    reason,
                    publish_snapshot_ref=publish_snapshot_ref,
                    error_detail=error_detail,
                    first_error_detail=first_error_detail,
                    retry_after_recovery=retry_after_recovery,
                    worktree_lock_held=True,
                )
            return
        try:
            capture = await self._run_worktree_boundary(
                _capture_runner_boundary,
                context.worktree_path,
                _authority_file_state_policy(context),
                _authority_cache_policy(context),
                "recovery",
                snapshot_id=_managed_snapshot_id("recovery", context.execution_id),
                lock_held=True,
            )
        except (CacheScanBudgetExceededError, CompromisedFileStateError, SnapshotPathLimitError):
            await self._request_budget_exhaustion_recovery(
                context,
                reason,
                error_detail=error_detail,
                first_error_detail=first_error_detail,
                retry_after_recovery=retry_after_recovery,
            )
            return
        result = await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "request_runner_recovery",
            {
                "execution_id": context.execution_id,
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "reason": reason,
                "error_detail": error_detail,
                "first_error_detail": first_error_detail,
                "recovery_snapshot_id": capture.snapshot.id,
                "recovery_snapshot_ref": capture.snapshot.ref,
                "recovery_commit_sha": capture.snapshot.commit_sha,
                "max_attempts": _runtime_death_max_attempts(context) or 0,
                "retry_after_recovery": retry_after_recovery,
                "final_tree_sha": capture.snapshot.tree_sha,
                "boundary_hash": capture.boundary_hash,
                "boundary_entries": capture.entries,
                "cache_authority_hash": context.cache_authority_hash,
                "observed_cache_roots": capture.cache_roots,
                "cache_status_evidence": capture.cache_status_evidence,
            },
        )
        if _callback_conflict_reason(result.events) is None and publish_snapshot_ref:
            await self._run_worktree_boundary(
                publish_snapshot,
                context.worktree_path,
                capture.snapshot,
                lock_held=True,
            )

    async def _request_budget_exhaustion_recovery(
        self,
        context: GraphDispatchContext,
        reason: Literal[
            "runner_died",
            "cancelled",
            "staged_artifact_missing",
            "staged_artifact_corrupt",
            "submission_repair_exhausted",
            "submission_format_rejected",
            "candidate_check_failed",
            "validation_environment_blocked",
        ],
        *,
        error_detail: str | None = None,
        first_error_detail: str | None = None,
        retry_after_recovery: bool = False,
    ) -> None:
        """Request restoration from the durable baseline without a partial scan.

        Cache exhaustion deliberately produces no current-boundary manifest or
        recovery snapshot. The kernel derives restore paths from the already
        durable baseline and (if present) staged boundary, then its normal
        recovery effect releases the lease only after restoration.
        """
        projection = await self._controller.read_projection(context.run_id)
        attempt = execution_attempts_view(projection).get(context.execution_id)
        if (
            attempt is None
            or attempt.baseline_tree_sha is None
            or attempt.baseline_boundary_hash is None
        ):
            raise RecoveryEventError("cache budget recovery has no durable baseline")
        await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "request_runner_recovery",
            {
                "execution_id": context.execution_id,
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "reason": reason,
                "error_detail": error_detail,
                "first_error_detail": first_error_detail,
                "max_attempts": _runtime_death_max_attempts(context) or 0,
                "retry_after_recovery": retry_after_recovery,
                "final_tree_sha": attempt.baseline_tree_sha,
                "boundary_hash": boundary_manifest_hash(
                    attempt.baseline_tree_sha,
                    [],
                    [],
                    context.cache_authority_hash,
                ),
                "boundary_entries": [],
                "cache_authority_hash": context.cache_authority_hash,
                "observed_cache_roots": [],
                "cache_status_evidence": [],
                "recovery_scope": "full_baseline",
            },
        )

    async def _dispatch_validation_environment_resolution(self, item: OutboxItem) -> None:
        """Restore the operator-selected snapshot before making the node ready."""
        payload = item.payload
        required = (
            "resolution_id",
            "node_id",
            "execution_id",
            "recovery_id",
            "snapshot_selection",
            "snapshot_id",
            "snapshot_ref",
            "commit_sha",
            "tree_sha",
        )
        if not all(isinstance(payload.get(key), str) and payload.get(key) for key in required):
            raise RecoveryRestoreError("validation environment resolution identity is malformed")
        snapshot_id = str(payload["snapshot_id"])
        snapshot_ref = str(payload["snapshot_ref"])
        commit_sha = str(payload["commit_sha"])
        tree_sha = str(payload["tree_sha"])
        await self._run_worktree_boundary(
            ensure_snapshot_ref,
            self._worktree_path,
            snapshot_id,
            expected_ref=snapshot_ref,
            expected_commit_sha=commit_sha,
            expected_tree_sha=tree_sha,
            lock_held=True,
        )
        await self._run_worktree_boundary(
            restore_baseline_worktree,
            self._worktree_path,
            snapshot_id,
            expected_tree_sha=tree_sha,
            lock_held=True,
        )
        await self._handle_command_retry_stale(
            item.run_id,
            await self._current_position(item.run_id),
            "complete_validation_environment_blockage_resolution",
            {key: payload[key] for key in required},
        )

    async def _dispatch_snapshot_publish(
        self, item: OutboxItem, *, worktree_lock_held: bool = False
    ) -> None:
        """Publish only the exact snapshot identity durably owned by an event."""
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                await self._dispatch_snapshot_publish(item, worktree_lock_held=True)
            return
        payload = item.payload
        required = ("snapshot_id", "snapshot_ref", "commit_sha", "tree_sha")
        values = {key: payload.get(key) for key in required}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise WorktreeError("snapshot publication has invalid durable identity")
        await self._run_worktree_boundary(
            publish_snapshot,
            self._worktree_path,
            PreparedSnapshot(
                id=str(values["snapshot_id"]),
                ref=str(values["snapshot_ref"]),
                commit_sha=str(values["commit_sha"]),
                tree_sha=str(values["tree_sha"]),
            ),
            lock_held=True,
        )

    async def _submit_check_result(
        self,
        context: GraphDispatchContext,
        record: dict[str, Any],
    ) -> None:
        observed_position = await self._current_position(context.run_id)
        payload = {
            "output_records": [record],
        }
        await self._handle_command_retry_stale(
            context.run_id,
            observed_position,
            "submit_callback",
            {
                "node_id": context.node_id,
                "execution_id": context.execution_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "base_snapshot_id": context.base_snapshot_id,
                "observed_graph_position": observed_position,
                "idempotency_key": f"{context.dispatch_event_id}:{context.execution_id}:check",
                "payload_hash": _payload_hash(payload),
                "payload": payload,
            },
        )

    async def _submit_graph_patch_callback(
        self,
        context: GraphDispatchContext,
        patch_payload: dict[str, Any],
    ) -> str:
        if not _can_submit_graph_patch(context):
            msg = f"node {context.node_id} is not authorized to submit graph patches"
            raise ValueError(msg)
        observed_position = await self._current_position(context.run_id)
        payload: dict[str, object] = dict(patch_payload)
        full_validation_diagnostics = _full_raw_patch_validation_diagnostics(
            patch_payload,
            context.node_id,
        )
        result = await self._handle_command_retry_stale(
            context.run_id,
            observed_position,
            "submit_patch",
            payload,
            proposed_by_node_id=context.node_id,
            actor_role=context.node_role,
        )
        accepted = [event for event in result.events if event.event_type == "graph_patch_accepted"]
        reconciled_patch_id = getattr(result, "reconciled_patch_id", None)
        if reconciled_patch_id is not None:
            reconciled_successors = getattr(
                result,
                "reconciled_successor_planner_node_ids",
                (),
            )
            return (
                f"graph patch {reconciled_patch_id} accepted (reconciled durable result); "
                "successor planner nodes: "
                f"{json.dumps(list(reconciled_successors), sort_keys=True)}"
            )
        if accepted:
            patch_id = accepted[0].payload.get("patch_id", payload.get("patch_id", "unknown"))
            raw_successors = accepted[0].payload.get("successor_planner_node_ids")
            successors = (
                [item for item in cast(list[object], raw_successors) if isinstance(item, str)]
                if isinstance(raw_successors, list)
                else []
            )
            return (
                f"graph patch {patch_id} accepted; "
                f"successor planner nodes: {json.dumps(successors, sort_keys=True)}"
            )

        rejection = next(
            (
                event
                for event in result.events
                if event.event_type in {"graph_patch_rejected", "command_rejected"}
            ),
            None,
        )
        if rejection is not None:
            reason = rejection.payload.get("reason") or "unknown rejection"
            patch_id = rejection.payload.get("patch_id", payload.get("patch_id", "unknown"))
            event_diagnostics = rejection.payload.get("diagnostics")
            diagnostics_payload: dict[str, Any] | None = (
                cast(dict[str, Any], event_diagnostics)
                if isinstance(event_diagnostics, dict)
                else full_validation_diagnostics
            )
            if diagnostics_payload is not None:
                diagnostics = json.dumps(
                    diagnostics_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                return (
                    f"graph patch {patch_id} rejected: {reason}; "
                    f"graph_patch_rejected; validation_diagnostics={diagnostics}"
                )
            return f"graph patch {patch_id} rejected: {reason}"

        return "graph patch command completed without accepted or rejected patch event"

    async def _agent_died(self, context: GraphDispatchContext, reason: str) -> None:
        payload: dict[str, object] = {
            "lease_id": context.lease_id,
            "execution_id": context.execution_id,
            "reason": reason or "runtime_process_died",
        }
        max_attempts = _runtime_death_max_attempts(context)
        if max_attempts is not None:
            payload["max_attempts"] = max_attempts
        await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "agent_died",
            payload,
        )

    async def _invalid_execution_contract(self, context: GraphDispatchContext, reason: str) -> None:
        """Conclude deterministic node-contract defects without retry recovery."""
        await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "agent_died",
            {
                "lease_id": context.lease_id,
                "execution_id": context.execution_id,
                "reason": reason,
                "failure_class": "invalid_plan_failure",
                "error_class": "invalid_execution_contract",
            },
        )

    async def _handle_command_retry_stale(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object],
        *,
        proposed_by_node_id: str | None = None,
        actor_role: str | None = None,
    ) -> Any:
        """Issue a graph command, retrying stale-projection races and transient DB locks.

        Two independent, retriable failure modes can surface from
        ``GraphController.handle_command``: a losing optimistic-concurrency
        race (``StaleProjectionError``, re-read position and resend), and a
        transient SQLite write-lock contention error (``OperationalError``
        with "database is locked"/"database is busy", back off briefly and
        resend the same payload — mirrors ``OutboxDispatcher._retry_locked``).
        Both share this method's retry budget.
        """
        current_position = expected_position
        retry_payload = dict(payload)
        delay_seconds = 0.1
        for attempt in range(MAX_STALE_COMMAND_RETRIES + 1):
            try:
                command_context = (
                    PatchCommandContext(
                        run_id=run_id,
                        current_graph_position=current_position,
                        proposed_by_node_id=proposed_by_node_id,
                        actor_role=actor_role,
                    )
                    if proposed_by_node_id is not None and actor_role is not None
                    else GraphCommandContext(
                        run_id=run_id,
                        current_graph_position=current_position,
                    )
                )
                if command_type in {
                    "record_runner_baseline",
                    "stage_runner_submission",
                    "witness_runner_completion",
                    "finalize_runner_execution",
                    "request_runner_recovery",
                }:
                    return await self._controller.handle_runtime_boundary_command(
                        run_id,
                        current_position,
                        command_type,
                        retry_payload,
                        self._runtime_boundary_capability,
                        context=command_context,
                    )
                return await self._controller.handle_command(
                    run_id, current_position, command_type, retry_payload, context=command_context
                )
            except OperationalError as exc:
                if (
                    not is_retriable_sqlite_write_conflict(exc)
                    or attempt >= MAX_STALE_COMMAND_RETRIES
                ):
                    raise
                await asyncio.sleep(delay_seconds * (attempt + 1))
            except StaleProjectionError:
                if attempt >= MAX_STALE_COMMAND_RETRIES:
                    raise
                current_position = await self._current_position(run_id)
                if "observed_graph_position" in retry_payload:
                    retry_payload["observed_graph_position"] = current_position
        raise StaleProjectionError(f"stale graph projection for run {run_id}: retry loop exhausted")

    async def _current_position(self, run_id: str) -> int:
        async with self._session_factory() as session:
            return await GraphEventStore(session).current_position(run_id)

    async def _record_gatekeeper_verdicts(
        self,
        context: GraphDispatchContext,
        projection_position: int,
        accepted_events: list[EventEnvelope],
    ) -> None:
        if self._residue_classifier is None:
            return
        current_position = projection_position
        for event in accepted_events:
            if event.event_type != "file_state_accepted":
                continue
            metadata = metadata_from_file_state_record(
                event.payload,
                max_items=self._max_gatekeeper_items_per_boundary,
            )
            if not metadata:
                continue
            verdicts = self._residue_classifier.classify(metadata)
            if not verdicts:
                continue
            result = await self._handle_command_retry_stale(
                context.run_id,
                current_position,
                "record_gatekeeper_verdicts",
                {
                    "file_state_record_id": event.payload.get("record_id"),
                    "execution_id": context.execution_id,
                    "consult_id": f"{context.execution_id}:{event.payload.get('record_id')}",
                    "verdicts": [verdict.to_payload() for verdict in verdicts],
                },
            )
            current_position = result.projection_position

    async def _dispatch_snapshot_cleanup(
        self, item: OutboxItem, *, worktree_lock_held: bool = False
    ) -> None:
        """Apply a cleanup side effect and record its durable result.

        ``snapshot_cleanup`` outbox rows are at-least-once. A retry may observe
        that ``cleanup_applied`` was already committed after an earlier
        filesystem cleanup; in that case the side effect intent is complete.
        """
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                await self._dispatch_snapshot_cleanup(item, worktree_lock_held=True)
            return
        try:
            durable_cleanup = CleanupRequestedPayload.model_validate(
                {
                    field_name: item.payload.get(field_name)
                    for field_name in CleanupRequestedPayload.model_fields
                    if field_name in item.payload
                }
            )
        except ValueError as exc:
            raise ValueError(f"malformed snapshot cleanup outbox intent: {exc}") from exc
        durable_payload = durable_cleanup.model_dump(mode="json")
        cleanup_id = durable_cleanup.cleanup_id
        projection = await self._controller.read_projection(item.run_id)
        if cleanup_applied_ids_view(projection).get(cleanup_id) is True:
            return
        cleanup_request = cleanup_requested_events_view(projection).get(cleanup_id)
        if cleanup_request is None:
            msg = f"unknown cleanup_requested: {cleanup_id}"
            raise ValueError(msg)
        projected_payload = cleanup_request.model_dump(mode="json")
        compared_fields = (
            "cleanup_id",
            "file_state_record_id",
            "snapshot_id",
            "execution_id",
            "producer_node_id",
            "snapshot_ref",
            "tree_sha",
            "commit_sha",
            "node_id",
            "lease_id",
            "lease_generation",
            "snapshot_role",
        )
        for field_name in compared_fields:
            if durable_payload.get(field_name) != projected_payload.get(field_name):
                raise ValueError(
                    f"snapshot cleanup outbox intent conflicts with projection: {field_name}"
                )
        cleanup_payload = durable_payload
        if cleanup_payload.get("snapshot_role") is not None:
            await self._dispatch_managed_snapshot_cleanup(
                item, cleanup_payload, worktree_lock_held=True
            )
            return
        record_id = cleanup_payload.get("file_state_record_id")
        if not isinstance(record_id, str):
            msg = f"cleanup_requested missing file_state_record_id: {cleanup_id}"
            raise ValueError(msg)
        compromised_record = file_state_records_view(projection).get(record_id)
        if compromised_record is None:
            msg = f"unknown cleanup file_state record: {record_id}"
            raise ValueError(msg)

        cleanup = await self._run_worktree_boundary(
            apply_cleanup_requested,
            worktree_path=self._worktree_path,
            cleanup_request=cleanup_payload,
            compromised_record=compromised_record.model_dump(mode="json"),
            lock_held=True,
        )
        result = await self._handle_command_retry_stale(
            item.run_id,
            await self._current_position(item.run_id),
            "record_cleanup_applied",
            {
                "cleanup_id": cleanup.cleanup_id,
                "superseding_file_state_record": cleanup.superseding_file_state_record,
                "deleted_snapshot_ref": cleanup.deleted_snapshot_ref,
            },
        )
        if _rejected_cleanup_already_applied(result.events, cleanup_id):
            return
        rejected = next(
            (
                event
                for event in result.events
                if event.event_type == "command_rejected"
                and event.payload.get("command_type") == "record_cleanup_applied"
            ),
            None,
        )
        if rejected is not None:
            msg = str(rejected.payload.get("reason") or "record_cleanup_applied rejected")
            raise ValueError(msg)

    async def _dispatch_managed_snapshot_cleanup(
        self,
        item: OutboxItem,
        payload: dict[str, object],
        *,
        worktree_lock_held: bool = False,
    ) -> None:
        """Delete only the ref named and tree-bound by a managed cleanup fact."""
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                await self._dispatch_managed_snapshot_cleanup(
                    item, payload, worktree_lock_held=True
                )
            return
        required = (
            "cleanup_id",
            "snapshot_id",
            "snapshot_ref",
            "tree_sha",
            "commit_sha",
            "node_id",
            "lease_id",
            "snapshot_role",
        )
        values = {key: payload.get(key) for key in required}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError("managed snapshot cleanup has incomplete ownership identity")
        generation = payload.get("lease_generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ValueError("managed snapshot cleanup has invalid lease generation")
        deleted = await self._run_worktree_boundary(
            delete_snapshot_ref,
            self._worktree_path,
            str(values["snapshot_id"]),
            expected_ref=str(values["snapshot_ref"]),
            expected_tree_sha=str(values["tree_sha"]),
            expected_commit_sha=str(values["commit_sha"]),
            lock_held=True,
        )
        result = await self._handle_command_retry_stale(
            item.run_id,
            await self._current_position(item.run_id),
            "record_managed_snapshot_cleanup_applied",
            {
                **values,
                "lease_generation": generation,
                "deleted_snapshot_ref": deleted,
            },
        )
        rejected = next(
            (
                event
                for event in result.events
                if event.event_type == "command_rejected"
                and event.payload.get("command_type") == "record_managed_snapshot_cleanup_applied"
            ),
            None,
        )
        if rejected is not None:
            raise ValueError(str(rejected.payload.get("reason") or "managed cleanup rejected"))

    async def _dispatch_runner_recovery(
        self, item: OutboxItem, *, worktree_lock_held: bool = False
    ) -> None:
        """Restore the requested durable baseline paths and record proof.

        The outbox is at-least-once: a crash after filesystem restoration but
        before the completion event simply performs the same selective restore
        again. No runner scheduling, lease transition, or retry lifecycle is
        performed here; that remains the next dispatch tranche.
        """
        if not worktree_lock_held:
            async with self._worktree_execution_lock:
                await self._dispatch_runner_recovery(item, worktree_lock_held=True)
            return
        recovery_id = item.payload.get("recovery_id")
        if not isinstance(recovery_id, str):
            raise RecoveryEventError("runner_recovery missing recovery_id")
        projection = await self._controller.read_projection(item.run_id)
        attempt_identities = execution_attempts_view(projection)
        request_execution_id = item.payload.get("execution_id")
        if not isinstance(request_execution_id, str):
            raise RecoveryEventError(f"runner recovery {recovery_id} has invalid execution_id")
        attempt = attempt_identities.get(request_execution_id)
        if attempt is None or attempt.recovery_id != recovery_id:
            raise RecoveryEventError(f"unknown runner_recovery_requested: {recovery_id}")
        if attempt.state in {"recovered", "finalized"}:
            return
        if attempt.state != "recovery_requested":
            raise RecoveryEventError(f"runner recovery {recovery_id} is not pending")
        try:
            payload_fields = RunnerRecoveryRequestedPayload.model_fields
            payload = RunnerRecoveryRequestedPayload.model_validate(
                {field: item.payload[field] for field in payload_fields if field in item.payload}
            ).model_dump(mode="json")
        except ValueError as exc:
            raise RecoveryEventError(
                f"runner recovery {recovery_id} has malformed requested event"
            ) from exc
        required_strings = (
            "execution_id",
            "node_id",
            "lease_id",
            "baseline_snapshot_id",
            "baseline_tree_sha",
        )
        values = {key: payload.get(key) for key in required_strings}
        if not all(isinstance(value, str) for value in values.values()):
            raise RecoveryEventError(f"runner recovery {recovery_id} has invalid identity")
        lease_generation = payload.get("lease_generation")
        paths = payload.get("paths")
        if not isinstance(lease_generation, int) or isinstance(lease_generation, bool):
            raise RecoveryEventError(f"runner recovery {recovery_id} has invalid lease generation")
        if not isinstance(paths, list):
            raise RecoveryEventError(f"runner recovery {recovery_id} has invalid paths")
        recovery_paths: list[str] = []
        raw_paths = cast(list[object], paths)
        for candidate_path in raw_paths:
            if not isinstance(candidate_path, str):
                raise RecoveryEventError(f"runner recovery {recovery_id} has invalid paths")
            recovery_paths.append(candidate_path)
        recovery_scope = payload.get("recovery_scope", "selective")
        if recovery_scope not in {"selective", "full_baseline"}:
            raise RecoveryEventError(f"runner recovery {recovery_id} has invalid scope")
        try:
            baseline_ref = attempt.baseline_snapshot_ref
            baseline_commit = attempt.baseline_commit_sha
            if not isinstance(baseline_ref, str) or not isinstance(baseline_commit, str):
                raise RecoveryEventError(f"runner recovery {recovery_id} has no owned baseline ref")
            await self._run_worktree_boundary(
                ensure_snapshot_ref,
                self._worktree_path,
                str(values["baseline_snapshot_id"]),
                expected_ref=baseline_ref,
                expected_commit_sha=baseline_commit,
                expected_tree_sha=str(values["baseline_tree_sha"]),
                lock_held=True,
            )
            if recovery_scope == "full_baseline":
                restoration = await self._run_worktree_boundary(
                    restore_baseline_worktree,
                    self._worktree_path,
                    str(values["baseline_snapshot_id"]),
                    expected_tree_sha=str(values["baseline_tree_sha"]),
                    lock_held=True,
                )
            elif recovery_paths:
                restoration = await self._run_worktree_boundary(
                    self._runner_recovery_restorer,
                    self._worktree_path,
                    str(values["baseline_snapshot_id"]),
                    recovery_paths,
                    expected_tree_sha=str(values["baseline_tree_sha"]),
                    lock_held=True,
                )
            else:
                restoration = SelectiveRestoreResult((), (), ())
        except (GitError, WorktreeError) as exc:
            raise RecoveryRestoreError(f"runner recovery {recovery_id} restore failed") from exc
        proof = recovery_proof_hash(
            execution_id=str(values["execution_id"]),
            recovery_id=recovery_id,
            node_id=str(values["node_id"]),
            lease_id=str(values["lease_id"]),
            lease_generation=lease_generation,
            baseline_snapshot_id=str(values["baseline_snapshot_id"]),
            baseline_tree_sha=str(values["baseline_tree_sha"]),
            requested_paths=restoration.requested_paths,
            restored_paths=restoration.restored_paths,
            removed_paths=restoration.removed_paths,
            recovery_scope=str(recovery_scope),
        )
        result = await self._handle_command_retry_stale(
            item.run_id,
            await self._current_position(item.run_id),
            "complete_runner_recovery",
            {
                "execution_id": values["execution_id"],
                "recovery_id": recovery_id,
                "node_id": values["node_id"],
                "lease_id": values["lease_id"],
                "lease_generation": lease_generation,
                "baseline_snapshot_id": values["baseline_snapshot_id"],
                "baseline_tree_sha": values["baseline_tree_sha"],
                "requested_paths": list(restoration.requested_paths),
                "proof_hash": proof,
                "restored_paths": list(restoration.restored_paths),
                "removed_paths": list(restoration.removed_paths),
                "recovery_scope": recovery_scope,
            },
        )
        rejected = next(
            (
                event
                for event in result.events
                if event.event_type == "command_rejected"
                and event.payload.get("command_type") == "complete_runner_recovery"
            ),
            None,
        )
        if rejected is not None:
            reason = rejected.payload.get("reason") or "complete_runner_recovery rejected"
            raise RecoveryCompletionRejectedError(str(reason))


async def reconcile_runtime(
    controller: GraphController,
    dispatcher: GraphDispatchExecutor,
    report: object,
    outbox_dispatcher: OutboxDispatcher | None = None,
) -> None:
    """Reconcile recovered active leases with in-process runtime liveness."""

    # The report may contain multiple runs; reconcile each one once.  This
    # awkward-looking extraction keeps the legacy report protocol unchanged.
    run_ids = {
        str(lease["run_id"])
        for lease in [
            *cast(Any, getattr(report, "awaiting_start_ack", [])),
            *cast(Any, getattr(report, "awaiting_callback", [])),
        ]
        if isinstance(lease.get("run_id"), str)
    }
    run_ids.update(
        str(attempt["run_id"])
        for attempt in cast(Any, getattr(report, "owned_attempts", []))
        if isinstance(attempt.get("run_id"), str)
    )
    managed_by_run = {
        run_id: await dispatcher.reconcile_execution_attempts(run_id) for run_id in run_ids
    }
    for lease in [
        *cast(Any, getattr(report, "awaiting_start_ack", [])),
        *cast(Any, getattr(report, "awaiting_callback", [])),
    ]:
        execution_id = str(lease.get("execution_id", ""))
        if execution_id in managed_by_run.get(str(lease["run_id"]), set()):
            continue
        if execution_id and dispatcher.is_running(execution_id):
            continue
        run_id = str(lease["run_id"])
        lease_id = str(lease["lease_id"])
        delay_seconds = 0.1
        for attempt in range(MAX_STALE_COMMAND_RETRIES):
            if not await _recovered_lease_still_active(
                controller,
                run_id,
                lease_id,
                execution_id,
            ):
                break
            try:
                await controller.handle_command(
                    run_id,
                    (position := await controller.current_position(run_id)),
                    "agent_died",
                    {
                        "lease_id": lease_id,
                        "execution_id": execution_id,
                        "reason": "runtime_process_missing_after_restart",
                    },
                    context=GraphCommandContext(
                        run_id=run_id,
                        current_graph_position=position,
                    ),
                )
                break
            except StaleProjectionError:
                if attempt == MAX_STALE_COMMAND_RETRIES - 1:
                    raise
                continue
            except OperationalError as exc:
                if (
                    not is_retriable_sqlite_write_conflict(exc)
                    or attempt == MAX_STALE_COMMAND_RETRIES - 1
                ):
                    raise
                await asyncio.sleep(delay_seconds * (attempt + 1))
                continue
    if outbox_dispatcher is not None:
        for run_id in run_ids:
            projection = await controller.read_projection(run_id)
            allowed_kinds = (
                frozenset({"snapshot_cleanup", "runner_recovery"})
                if run_state(projection) in {"cancelled", "completed", "failed"}
                else frozenset({"runner_recovery"})
            )
            await outbox_dispatcher.dispatch_pending(run_id=run_id, allowed_kinds=allowed_kinds)


async def _recovered_lease_still_active(
    controller: GraphController,
    run_id: str,
    lease_id: str,
    execution_id: str,
) -> bool:
    projection = await controller.read_projection(run_id)
    lease = leases_view(projection).get(lease_id)
    if lease is None or lease.state != "active":
        return False
    lease_execution_id = lease.execution_id
    return not isinstance(lease_execution_id, str) or lease_execution_id == execution_id


def build_graph_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Any,
    id_gen: Any,
    *,
    worktree_path: str | Path,
    artifact_store: ArtifactStore,
    runner_type: AgentRunnerType,
    runner_config: dict[str, Any] | None = None,
    journal_max_bytes: int = 64 * 1024 * 1024,
    on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
    on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
    graph_mcp_registry: "GraphMcpExecutionRegistry | None" = None,
    base_url: str = "http://localhost:8000",
    process_registry: GraphProcessRegistry | None = None,
    crash_barrier: CrashBarrier | None = None,
) -> tuple[GraphController, GraphDispatchExecutor]:
    """Assemble graph controller and dispatch executor without API imports."""

    async def agent_dispatch_admission(run_id: str) -> bool:
        async with session_factory() as session:
            run = await RunRepository(session).get(run_id)
        return run.status == RunStatus.ACTIVE

    capability = RuntimeBoundaryCapability()
    controller = GraphController(
        session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
        journal_max_bytes=journal_max_bytes,
        runtime_boundary_capability=capability,
        artifact_store=artifact_store,
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(runner_type, runner_config),
        worktree_path=worktree_path,
        artifact_store=artifact_store,
        on_agent_output=on_agent_output,
        on_agent_usage=on_agent_usage,
        graph_mcp_registry=graph_mcp_registry,
        base_url=base_url,
        process_registry=process_registry or RunnerOwnedProcessRegistry(),
        runtime_boundary_capability=capability,
        crash_barrier=crash_barrier,
        agent_dispatch_admission=agent_dispatch_admission,
    )
    return controller, executor


def _node_payload(
    events: list[EventEnvelope], node_id: str, *, projection: GraphProjection | None = None
) -> dict[str, Any]:
    payload = node_payload_view(projection, node_id) if projection is not None else None
    result = payload if payload is not None else {"node_id": node_id}
    for event in events:
        if event.event_type != "node_created":
            continue
        if event.payload.get("node_id") == node_id:
            for key, value in event.payload.items():
                result.setdefault(key, value)
            break
    return result


def _requirements_for_node(
    projection: GraphProjection | list[EventEnvelope],
    node_id: str,
    events: list[EventEnvelope] | None = None,
) -> list[str]:
    if isinstance(projection, list):
        events = projection
        projection = rebuild_projection(events)
    _guard_no_pending_compromised_file_state_bindings(projection, node_id)
    requirements = requirements_for_node_view(projection, node_id)
    if requirements:
        return requirements

    if events:
        bound_record_ids = {
            record_id
            for port, binding in input_bindings_view(projection).get(node_id, {}).items()
            if port.startswith("requirement_")
            for record_id in binding.record_ids
        }
        for event in events:
            if event.event_type != "node_created":
                continue
            requirement_node_id = event.payload.get("node_id")
            if requirement_node_id not in bound_record_ids:
                continue
            requirement_record = event.payload.get("requirement_record")
            if isinstance(requirement_record, dict):
                try:
                    record = RequirementRecord.model_validate(requirement_record)
                except ValueError:
                    continue
                requirements.append(f"{record.value.id}: {record.value.text}")
                continue
            requirement = event.payload.get("requirement")
            if isinstance(requirement, dict):
                req = cast(dict[str, Any], requirement)
                requirements.append(f"{req.get('id', requirement_node_id)}: {req.get('desc', '')}")
        if requirements:
            return requirements

    dynamic_feature = routine_snapshot_dynamic_feature_view(projection)
    if dynamic_feature is None and events:
        dynamic_feature = _dynamic_feature_from_events(events)
    if dynamic_feature is not None:
        requirement = _dynamic_feature_acceptance_requirement(dynamic_feature)
        if requirement is not None:
            return [requirement]
    return requirements


def _dynamic_feature_from_events(events: list[EventEnvelope]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.event_type != "node_created":
            continue
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, dict):
            typed_snapshot = cast(dict[str, Any], snapshot)
            snapshot_feature = typed_snapshot.get("dynamic_feature")
            if isinstance(snapshot_feature, dict):
                return cast(dict[str, Any], snapshot_feature)
        payload_feature = event.payload.get("dynamic_feature")
        if isinstance(payload_feature, dict):
            return cast(dict[str, Any], payload_feature)
    return None


def _dynamic_feature_acceptance_requirement(
    dynamic_feature: dict[str, Any],
) -> str | None:
    content = dynamic_feature.get("feature_spec_content")
    command = dynamic_feature.get("acceptance_command")
    parts: list[str] = []
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    if isinstance(command, str) and command.strip():
        parts.append(f"Acceptance command: {command.strip()}")
    if not parts:
        return None
    return f"dynamic_feature_acceptance: {' '.join(parts)}"


_CALLBACK_REJECTION_EVENT_TYPES = {"callback_rejected_conflict", "callback_rejected_stale"}


def _callback_conflict_reason(events: list[EventEnvelope]) -> str | None:
    # A ``callback_duplicate_returned`` event only means "we've seen this
    # idempotency key before" — the prior result it replays may itself have
    # been a rejection (historic event logs can contain duplicate-of-rejection
    # events even though current validation no longer produces them). Treating
    # a duplicate-of-rejection as success would silently swallow the original
    # conflict/staleness, so its prior_result must be inspected rather than
    # assumed to be an acceptance.
    for event in events:
        if (
            event.event_type in _CALLBACK_REJECTION_EVENT_TYPES
            or event.event_type == "command_rejected"
        ):
            reason = event.payload.get("reason")
            return (
                str(reason) if isinstance(reason, str) and reason else "unknown callback conflict"
            )
        if event.event_type == "callback_duplicate_returned":
            duplicate_reason = _duplicate_of_rejection_reason(event.payload)
            if duplicate_reason is not None:
                return duplicate_reason
    return None


def _duplicate_of_rejection_reason(payload: dict[str, Any]) -> str | None:
    prior_result = payload.get("prior_result")
    if not isinstance(prior_result, dict):
        return None
    prior = cast(dict[str, Any], prior_result)
    prior_outcome = prior.get("outcome")
    if prior_outcome not in _CALLBACK_REJECTION_EVENT_TYPES:
        return None
    prior_payload = prior.get("payload")
    reason = (
        cast(dict[str, Any], prior_payload).get("reason")
        if isinstance(prior_payload, dict)
        else None
    )
    return str(reason) if isinstance(reason, str) and reason else f"duplicate of {prior_outcome}"


def _capture_runner_boundary(
    worktree_path: str | Path,
    policy: Any,
    cache_policy: Any,
    label: str | None = None,
    *,
    snapshot_id: str | None = None,
    force_include_paths: list[str] | None = None,
) -> RunnerBoundaryCapture:
    """Capture a restorable tree and canonical manifest while the repository lock is held.

    The manifest intentionally describes the dirty/status boundary, while the
    snapshot contains the complete tree needed to restore a modified or deleted
    path.  This permits selective restore without claiming unrelated clean paths
    as execution output.
    """
    # Preserve the former internal helper shape for direct unit callers. The
    # managed runtime always passes the immutable projected cache policy.
    legacy_root_transport = label is None
    if legacy_root_transport:
        label = cast(str, cache_policy)
        from orchestrator.graph import LEGACY_CACHE_AUTHORITY_V1

        cache_policy = LEGACY_CACHE_AUTHORITY_V1
    root = Path(worktree_path)
    # Prepare the normalized output tree before observing boundary paths. The
    # entries below are read from this immutable Git tree, closing the live
    # worktree TOCTOU between manifest construction and publication.
    if snapshot_id is None:
        raise ValueError("managed runner boundary requires a deterministic snapshot id")
    initial_status = collect_worktree_status(root, policy)
    initial_cache_roots = list(derive_cache_roots(initial_status, cache_policy))
    initial_classification = classify_file_state(initial_status, policy)
    if initial_classification.verdict == "rejected":
        raise CompromisedFileStateError("boundary file-state contains rejected paths")
    # A baseline is authority state, not a cache archive. Git's `add -f` on a
    # directory recursively expands it, so force only individually approved
    # non-cache ignored files the classifier has already examined.
    approved_ignored_paths = sorted(
        entry.path
        for entry in initial_classification.paths
        if entry.source == "ignored"
        and not entry.rejected
        and entry.classification != "tool_cache"
        and (root / entry.path).is_file()
        and not (root / entry.path).is_symlink()
    )
    captured = prepare_snapshot(
        root,
        f"graph runner {label} boundary",
        snapshot_id=snapshot_id,
        force_include_paths=(approved_ignored_paths if label == "baseline" else [])
        + (force_include_paths or []),
        # Cache-root handling is deliberately narrower than full exclusion:
        # preserve tracked source under a mixed root while dropping untracked
        # and ignored cache residue without recursively enumerating it.
        exclude_untracked_cache_paths=[cache_root.path for cache_root in initial_cache_roots],
    )
    status = collect_worktree_status(root, policy)
    cache_roots = list(derive_cache_roots(status, cache_policy))
    entries_by_path: dict[str, RunnerBoundaryEntry] = {}
    for item in (*status.tracked_modified, *status.untracked, *status.ignored):
        if any(
            item.path == cache_root.path or item.path.startswith(f"{cache_root.path}/")
            for cache_root in cache_roots
        ):
            continue
        metadata = snapshot_path_metadata(root, captured, item.path)
        if metadata is None:
            file_type = "missing"
            material = b"missing"
            fingerprint = f"sha256:{hashlib.sha256(material).hexdigest()}"
        else:
            file_type = cast(Literal["file", "directory", "symlink", "missing"], metadata.file_type)
            fingerprint = metadata.fingerprint
        entries_by_path[item.path] = RunnerBoundaryEntry(
            path=item.path,
            kind=item.kind,
            status=item.status or "modified",
            fingerprint=fingerprint,
            file_type=file_type,
        )
    entries = [entries_by_path[path] for path in sorted(entries_by_path)]
    return RunnerBoundaryCapture(
        snapshot=captured,
        entries=[entry.model_dump(mode="json") for entry in entries],
        boundary_hash=boundary_manifest_hash(
            captured.tree_sha,
            entries,
            _cache_root_status_witnesses(status, cache_policy),
            None if legacy_root_transport else cache_authority_hash(cache_policy),
        ),
        cache_roots=(
            [root.path for root in cache_roots]
            if legacy_root_transport
            else [root.model_dump(mode="json") for root in cache_roots]
        ),
        cache_status_evidence=_cache_root_status_witnesses(status, cache_policy),
    )


def _managed_snapshot_id(label: str, execution_id: str) -> str:
    """Return a deterministic Git-safe snapshot identifier for one boundary."""
    return hashlib.sha256(f"runner-{label}-{execution_id}".encode()).hexdigest()


def _cache_root_status_witnesses(status: Any, cache_policy: Any) -> list[dict[str, str]]:
    """Persist one deterministic observed status path for each derived root."""
    witnesses: dict[tuple[str, str], dict[str, str]] = {}
    for item in (*status.untracked, *status.ignored):
        root = first_authorized_cache_root(item, cache_policy)
        if root is not None:
            witnesses.setdefault((root.path, root.kind), {"path": item.path, "kind": item.kind})
    return [witnesses[key] for key in sorted(witnesses)]


def _guard_no_pending_compromised_file_state_bindings(
    projection: GraphProjection,
    node_id: str,
) -> None:
    """Refuse to build runtime bindings from a cleanup-pending snapshot.

    Slice 2.6+ will add richer file-state restore/consumption paths. Until
    then this is the single runtime binding read boundary: if a downstream
    node is bound to a file-state record that the projection has marked as
    compromised and still awaiting cleanup, dispatch must stop before a runner
    can consume that snapshot identity.
    """
    for binding in input_bindings_view(projection).get(node_id, {}).values():
        for raw_record_id in binding.record_ids:
            record = file_state_records_view(projection).get(raw_record_id)
            if record is None:
                continue
            if record.compromised is True and record.superseded_pending is True:
                cleanup_id = record.cleanup_id
                msg = (
                    "refusing to bind compromised file-state record "
                    f"{raw_record_id} for node {node_id}"
                )
                if isinstance(cleanup_id, str) and cleanup_id:
                    msg = f"{msg}; cleanup pending: {cleanup_id}"
                raise CompromisedFileStateError(msg)


def _rejected_cleanup_already_applied(
    events: list[EventEnvelope],
    cleanup_id: str,
) -> bool:
    return any(
        event.event_type == "command_rejected"
        and event.payload.get("command_type") == "record_cleanup_applied"
        and event.payload.get("reason") == f"cleanup already applied: {cleanup_id}"
        for event in events
    )


async def _execute_check_command(
    context: GraphDispatchContext,
    store: ArtifactStore,
    *,
    worktree_boundary: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    command_definition = _check_command_definition(
        context.node_payload,
        context.graph_events,
        context.graph_projection,
    )
    invocation, command_text, shell = _check_invocation(command_definition)
    timeout_seconds = _check_timeout_seconds(command_definition)
    if worktree_boundary is None:
        execution_worktree = await asyncio.to_thread(_prepare_check_execution_worktree, context)
        dependency_provisioning = await asyncio.to_thread(
            _provision_check_dependencies,
            context,
            execution_worktree,
            command_text,
        )
    else:
        execution_worktree = await worktree_boundary(
            _prepare_check_execution_worktree,
            context,
            lock_held=True,
        )
        dependency_provisioning = await worktree_boundary(
            _provision_check_dependencies,
            context,
            execution_worktree,
            command_text,
            lock_held=True,
        )
    started = perf_counter()
    stdout = ""
    stderr = ""
    timed_out = False
    exit_code: int | None
    proc: asyncio.subprocess.Process | None = None

    try:
        if shell:
            proc = await asyncio.create_subprocess_shell(
                cast(str, invocation),
                cwd=execution_worktree.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            argv = cast(list[str], invocation)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=execution_worktree.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
        exit_code = proc.returncode
        stdout = _decode_output(stdout_bytes)
        stderr = _decode_output(stderr_bytes)
    except TimeoutError:
        timed_out = True
        exit_code = None
        if proc is not None:
            proc.kill()
            await proc.wait()
    finally:
        if worktree_boundary is None:
            await asyncio.to_thread(_cleanup_check_execution_worktree, context, execution_worktree)
        else:
            await worktree_boundary(
                _cleanup_check_execution_worktree,
                context,
                execution_worktree,
                lock_held=True,
            )

    duration_ms = int((perf_counter() - started) * 1000)
    status = "timeout" if timed_out else "passed" if exit_code == 0 else "failed"
    classification = _classify_check_result(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        dependency_provisioning=dependency_provisioning,
    )
    if worktree_boundary is None:
        stdout_tail, stdout_ref = await _externalize_check_output(stdout, store)
        stderr_tail, stderr_ref = await _externalize_check_output(stderr, store)
    else:
        stdout_tail, stdout_ref = await worktree_boundary(
            _externalize_check_output,
            stdout,
            store,
            lock_held=True,
            offload=False,
        )
        stderr_tail, stderr_ref = await worktree_boundary(
            _externalize_check_output,
            stderr,
            store,
            lock_held=True,
            offload=False,
        )
    if context.node_payload.get("semantic_stage") == "final_acceptance":
        _final_file_state, final_report = _authoritative_final_acceptance_snapshot(context)
        candidate_id = final_report.candidate_id
    else:
        candidate_id = _candidate_id_for_check(context)
    task_region_id = str(context.node_payload.get("task_region_id") or context.node_id)
    attempt_number = int(context.node_payload.get("attempt_number", 0))
    command_id = str(command_definition.get("id") or context.node_id)
    value: dict[str, Any] = {
        "status": status,
        "classification": classification,
        "command_id": command_id,
        "command_binding": command_definition.get("command_binding")
        or context.node_payload.get("command_binding"),
        "command_text": command_text,
        "command": command_definition,
        "worktree_path": context.worktree_path,
        "source_worktree_path": context.worktree_path,
        "execution_worktree_path": execution_worktree.path,
        "base_snapshot_id": context.base_snapshot_id,
        "execution_snapshot_id": execution_worktree.snapshot_id,
        "execution_snapshot_ref": execution_worktree.snapshot_ref,
        "execution_id": context.execution_id,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout_tail": stdout_tail,
        "stdout_ref": stdout_ref,
        "stderr_tail": stderr_tail,
        "stderr_ref": stderr_ref,
        "stdout_truncated": stdout_ref is not None,
        "stderr_truncated": stderr_ref is not None,
        "timeout_seconds": timeout_seconds,
        "environment_policy": {
            "cwd": execution_worktree.path,
            "env": "inherited",
            "shell": shell,
            "source_worktree_path": context.worktree_path,
            "snapshot_id": execution_worktree.snapshot_id,
            "dependency_provisioning": [
                {
                    "package_dir": result.package_dir,
                    "strategy": result.strategy,
                    "status": result.status,
                    "detail": result.detail,
                }
                for result in dependency_provisioning
            ],
        },
    }
    record_payload = _add_evaluated_record_citations(
        {
            "record_id": f"check-{context.execution_id}",
            "record_kind": "output",
            "record_type": "check_result",
            "producer_node_id": context.node_id,
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": candidate_id,
            "task_region_id": task_region_id,
            "attempt_number": attempt_number,
            "value": value,
        },
        _evaluated_record_citations(context),
        value=True,
    )
    return CheckResultRecord.model_validate(record_payload).model_dump(mode="json")


async def _externalize_check_output(
    output: str,
    store: ArtifactStore,
) -> tuple[str, StoredArtifactRef | None]:
    encoded = output.encode("utf-8")
    if len(encoded) <= CHECK_OUTPUT_EXTERNALIZE_BYTES:
        return output, None
    ref = await store.put(encoded, media_type="text/plain", encoding="utf-8")
    return output[-CHECK_OUTPUT_TAIL_CHARS:], ref


def _prepare_check_execution_worktree(context: GraphDispatchContext) -> CheckExecutionWorktree:
    snapshot = _bound_file_state_snapshot(context)
    if snapshot is None:
        return CheckExecutionWorktree(path=context.worktree_path)

    snapshot_id, snapshot_ref = snapshot
    if not SNAPSHOT_REF_PATTERN.fullmatch(snapshot_ref):
        msg = f"invalid file-state snapshot ref for check execution: {snapshot_ref}"
        raise ValueError(msg)

    tempdir = tempfile.mkdtemp(prefix="orchestrator-check-snapshot-")
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", tempdir, snapshot_ref],
        cwd=context.worktree_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        shutil.rmtree(tempdir, ignore_errors=True)
        msg = f"failed to create check snapshot worktree: {result.stderr.strip()}"
        raise ValueError(msg)
    return CheckExecutionWorktree(
        path=tempdir,
        snapshot_id=snapshot_id,
        snapshot_ref=snapshot_ref,
        temporary_path=tempdir,
    )


def _cleanup_check_execution_worktree(
    context: GraphDispatchContext,
    execution_worktree: CheckExecutionWorktree,
) -> None:
    tempdir = execution_worktree.temporary_path
    if tempdir is None:
        return
    subprocess.run(
        ["git", "worktree", "remove", "--force", tempdir],
        cwd=context.worktree_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    shutil.rmtree(tempdir, ignore_errors=True)


def _provision_check_dependencies(
    context: GraphDispatchContext,
    execution_worktree: CheckExecutionWorktree,
    command_text: str,
) -> list[DependencyProvisionResult]:
    if execution_worktree.temporary_path is None:
        return []
    if not _command_needs_node_dependencies(command_text):
        return []

    source_root = Path(context.worktree_path)
    execution_root = Path(execution_worktree.path)
    results: list[DependencyProvisionResult] = []
    for package_dir in _node_package_dirs(execution_root, command_text):
        source_package_dir = source_root / package_dir
        execution_package_dir = execution_root / package_dir
        node_modules = execution_package_dir / "node_modules"
        if node_modules.exists():
            results.append(
                DependencyProvisionResult(
                    package_dir=package_dir,
                    strategy="existing_node_modules",
                    status="skipped",
                    detail="node_modules already exists in check worktree",
                )
            )
            continue

        source_node_modules = source_package_dir / "node_modules"
        if source_node_modules.exists():
            try:
                os.symlink(source_node_modules, node_modules, target_is_directory=True)
            except OSError as exc:
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="symlink_source_node_modules",
                        status="failed",
                        detail=str(exc),
                    )
                )
            else:
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="symlink_source_node_modules",
                        status="provisioned",
                        detail=f"linked {source_node_modules}",
                    )
                )
            continue

        lockfile = execution_package_dir / "package-lock.json"
        if lockfile.exists():
            result = subprocess.run(
                ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                cwd=execution_package_dir,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode == 0:
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="npm_ci",
                        status="provisioned",
                        detail="npm ci completed",
                    )
                )
            else:
                detail = _trim_check_output(result.stderr or result.stdout)
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="npm_ci",
                        status="failed",
                        detail=detail,
                    )
                )
            continue

        results.append(
            DependencyProvisionResult(
                package_dir=package_dir,
                strategy="node_modules_unavailable",
                status="failed",
                detail="no source node_modules or package-lock.json available",
            )
        )
    return results


def _command_needs_node_dependencies(command_text: str) -> bool:
    lowered = command_text.lower()
    return any(
        token in lowered for token in ("npm", "npx", "vitest", "vite", "tsx", "node_modules")
    )


def _node_package_dirs(execution_root: Path, command_text: str) -> list[str]:
    candidates: list[str] = []
    if (execution_root / "package.json").exists():
        candidates.append(".")
    for match in re.finditer(r"(?:--prefix|-C)\s+([^\s;&|]+)", command_text):
        raw_path = match.group(1).strip("'\"")
        if raw_path and not raw_path.startswith(("/", "..")):
            candidates.append(raw_path)
    if " ui " in f" {command_text} " or "--prefix ui" in command_text or "ui/" in command_text:
        candidates.append("ui")
    if not candidates and (execution_root / "ui" / "package.json").exists():
        candidates.append("ui")

    output: list[str] = []
    for candidate in candidates:
        normalized = candidate.rstrip("/") or "."
        if normalized not in output and (execution_root / normalized / "package.json").exists():
            output.append(normalized)
    return output


def _classify_check_result(
    *,
    status: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    dependency_provisioning: list[DependencyProvisionResult],
) -> str:
    if status in {"passed", "timeout"}:
        return status
    if any(result.status == "failed" for result in dependency_provisioning):
        return "environment_error"
    combined = f"{stdout}\n{stderr}".lower()
    if exit_code == 127 or any(
        phrase in combined
        for phrase in (
            "command not found",
            "no such file or directory",
            "could not determine executable to run",
            "sh: vitest:",
            "vitest: not found",
        )
    ):
        return "tool_unavailable"
    if "enoent" in combined or "cannot find module" in combined:
        return "tool_error"
    return "failed"


def _bound_file_state_snapshot(context: GraphDispatchContext) -> tuple[str, str] | None:
    if context.node_payload.get("semantic_stage") == "final_acceptance":
        record, _report = _authoritative_final_acceptance_snapshot(context)
        snapshot_id = record.snapshot_id
        snapshot_ref = record.git.ref if record.git is not None else None
        if not isinstance(snapshot_id, str) or not isinstance(snapshot_ref, str):
            raise ValueError(
                "final acceptance requires an exact published file-state snapshot identity"
            )
        return snapshot_id, snapshot_ref
    citations = _evaluated_record_citations(context)
    file_state_record_ids = citations.get("file_state_record_ids", [])
    if not file_state_record_ids:
        return None
    records = file_state_records_view(context.graph_projection)
    for record_id in file_state_record_ids:
        record = records.get(record_id)
        if record is None:
            continue
        snapshot_id = record.snapshot_id
        snapshot_ref = record.git.ref if record.git is not None else None
        if isinstance(snapshot_id, str) and isinstance(snapshot_ref, str):
            return snapshot_id, snapshot_ref
    return None


def _authoritative_final_acceptance_snapshot(
    context: GraphDispatchContext,
) -> tuple[Any, VerificationReportRecord]:
    """Resolve the sole current final-batch snapshot or fail closed."""
    bindings = input_bindings_view(context.graph_projection).get(context.node_id, {})
    bound_reports_by_port: list[tuple[str, str]] = []
    for port, binding in bindings.items():
        if not port.startswith("verification_report_") and port != "verification_evidence":
            continue
        if len(binding.record_ids) != 1:
            raise ValueError(f"final acceptance requires exactly one verification report at {port}")
        bound_reports_by_port.append((port, binding.record_ids[0]))
    bound_reports_by_port.sort(key=lambda item: _final_acceptance_port_order(item[0]))
    bound_report_ids = list(dict.fromkeys(record_id for _port, record_id in bound_reports_by_port))
    bound_report_ids = list(dict.fromkeys(bound_report_ids))
    if not bound_report_ids:
        raise ValueError("final acceptance requires bound batch verification reports")

    records = output_record_payloads_view(context.graph_projection)
    for record_id in bound_report_ids:
        report = records.get(record_id)
        if not isinstance(report, VerificationReportRecord) or report.outcome != "passed":
            raise ValueError("final acceptance requires exact passing batch verification reports")

    declared_batch_ids = context.node_payload.get("declared_batch_ids")
    final_batch_id: Any = None
    if (
        isinstance(declared_batch_ids, list)
        and declared_batch_ids
        and isinstance(declared_batch_ids[-1], str)
    ):
        final_batch_id = declared_batch_ids[-1]
    elif bound_reports_by_port:
        final_bound_report = records.get(bound_reports_by_port[-1][1])
        if isinstance(final_bound_report, VerificationReportRecord):
            final_producer = (
                node_payload_view(
                    context.graph_projection,
                    final_bound_report.producer_node_id,
                )
                or {}
            )
            final_batch_id = final_producer.get("declared_batch_id")
    if not isinstance(final_batch_id, str):
        raise ValueError("final acceptance cannot identify the final declared batch")

    if isinstance(declared_batch_ids, list):
        configured_batch_ids = {
            item for item in cast(list[Any], declared_batch_ids) if isinstance(item, str)
        }
    else:
        configured_batch_ids = {
            batch_id
            for record_id in bound_report_ids
            if isinstance(record := records.get(record_id), VerificationReportRecord)
            and isinstance(
                batch_id := (
                    node_payload_view(context.graph_projection, record.producer_node_id) or {}
                ).get("declared_batch_id"),
                str,
            )
        }
    current_reports, ambiguous_batches = authoritative_batch_verification_report_ids(
        context.graph_projection, configured_batch_ids
    )
    if ambiguous_batches or set(current_reports) != configured_batch_ids:
        raise ValueError(
            "final acceptance requires exactly one authoritative report for every declared batch"
        )
    if set(current_reports.values()) != set(bound_report_ids):
        raise ValueError("final acceptance is bound to stale batch verification evidence")
    report = records[current_reports[final_batch_id]]
    if not isinstance(report, VerificationReportRecord):
        raise ValueError("final acceptance authority resolved to a non-verification record")

    candidate_ids = list(dict.fromkeys(report.candidate_record_ids))
    singular_candidate_id = report.candidate_record_id
    if singular_candidate_id is not None and singular_candidate_id not in candidate_ids:
        candidate_ids.append(singular_candidate_id)
    if len(candidate_ids) != 1:
        raise ValueError(
            "final acceptance requires exactly one final candidate record in its verification report"
        )
    candidate = records.get(candidate_ids[0])
    if not isinstance(candidate, CandidateRecord):
        raise ValueError("final acceptance verification cites a missing final candidate record")

    file_state_ids = list(dict.fromkeys(report.file_state_record_ids))
    if len(file_state_ids) != 1:
        raise ValueError(
            "final acceptance requires exactly one final file-state record in its verification report"
        )
    candidate_file_state_ids = list(
        dict.fromkeys(
            [
                *candidate.file_state_record_ids,
                *candidate.value.file_state_record_ids,
                *(
                    [candidate.file_state_record_id]
                    if candidate.file_state_record_id is not None
                    else []
                ),
                *(
                    [candidate.value.file_state_record_id]
                    if candidate.value.file_state_record_id is not None
                    else []
                ),
            ]
        )
    )
    if candidate_file_state_ids != file_state_ids:
        raise ValueError(
            "final acceptance verification does not cite the final candidate's exact file state"
        )
    file_state = file_state_records_view(context.graph_projection).get(file_state_ids[0])
    if file_state is None or file_state.compromised is True or file_state.verdict != "captured":
        raise ValueError("final acceptance final file-state record is unavailable or ineligible")
    if file_state.candidate_id not in {None, report.candidate_id, candidate.candidate_id}:
        raise ValueError("final acceptance final file state has mismatched candidate provenance")
    return file_state, report


def _final_acceptance_port_order(port: str) -> tuple[int, int | str]:
    prefix = "verification_report_batch_"
    if port.startswith(prefix):
        suffix = port[len(prefix) :]
        if suffix.isdigit():
            return (0, int(suffix))
    return (1, port)


def _check_command_definition(
    node: dict[str, Any],
    events: list[EventEnvelope],
    projection: GraphProjection | None = None,
) -> dict[str, Any]:
    command_definition = resolve_check_command_definition(node, events, projection=projection)
    if command_definition is None:
        msg = "check node missing command_definition"
        raise ValueError(msg)
    return command_definition


def _check_invocation(command_definition: dict[str, Any]) -> tuple[str | list[str], str, bool]:
    raw_argv = command_definition.get("argv")
    if isinstance(raw_argv, list):
        raw_parts = cast(list[Any], raw_argv)
        typed_argv = [part for part in raw_parts if isinstance(part, str)]
        if len(typed_argv) != len(raw_parts):
            typed_argv = []
        if typed_argv:
            return typed_argv, " ".join(typed_argv), False

    command = command_definition.get("cmd")
    if not isinstance(command, str):
        command = command_definition.get("command")
    if isinstance(command, str) and command.strip():
        return command, command, True

    msg = "check command_definition requires non-empty argv or cmd"
    raise ValueError(msg)


def _check_timeout_seconds(command_definition: dict[str, Any]) -> float:
    raw_timeout = command_definition.get("timeout_seconds")
    if isinstance(raw_timeout, int | float) and not isinstance(raw_timeout, bool):
        if raw_timeout > 0:
            return float(raw_timeout)
    return float(DEFAULT_CHECK_TIMEOUT_SECONDS)


def _decode_output(output: bytes | None) -> str:
    if output is None:
        return ""
    return output.decode("utf-8", errors="replace")


def _trim_check_output(output: str) -> str:
    if len(output) <= MAX_CHECK_OUTPUT_CHARS:
        return output
    return output[-MAX_CHECK_OUTPUT_CHARS:]


def _payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    msg = f"payload field {key} must be int-compatible"
    raise TypeError(msg)


def _work_mode(value: object) -> Literal["implementation", "oversight"]:
    return "oversight" if value == "oversight" else "implementation"


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    task.exception()
