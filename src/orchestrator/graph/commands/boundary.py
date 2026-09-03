"""Pure runner execution-boundary command handlers."""

from __future__ import annotations

from typing import Any, cast

from orchestrator.graph._commands import (
    apply_callback_command,
    apply_record_managed_snapshot_cleanup_applied,
)
from orchestrator.graph.command_models import (
    CompleteRunnerRecoveryCommand,
    FinalizeRunnerExecutionCommand,
    GraphCommandContext,
    RecordRunnerBaselineCommand,
    RecordManagedSnapshotCleanupAppliedCommand,
    RequestRunnerRecoveryCommand,
    StageRunnerSubmissionCommand,
    WitnessRunnerCompletionCommand,
)
from orchestrator.graph.models import EventEnvelope, FileStateRecord, LeaseRevokedPayload
from orchestrator.graph.projection_collections import thaw_json
from orchestrator.graph.projection_models import GraphProjection
from orchestrator.graph.projection_queries import (
    execution_attempts_view,
    node_attempts_view,
    node_max_attempts_view,
)
from orchestrator.graph.projection_queries import (
    cache_authority_binding,
    cache_authority_is_new_format,
    lease_by_id,
    node_cache_authority_hash,
    non_gap_planner_has_accepted_patch,
)
from orchestrator.graph.cache_authority import RunnerCacheRoot, validate_authorized_cache_roots
from orchestrator.graph.boundary_types import (
    derive_recovery_paths,
    recovery_proof_hash,
    validate_callback_json,
)
from orchestrator.graph.callbacks import callback_payload_identity


def _conflict(make_event: Any, command: str, reason: str) -> list[EventEnvelope]:
    return [make_event("command_rejected", {"command_type": command, "reason": reason})]


def _same_identity(attempt: Any, payload: Any) -> bool:
    return (
        attempt.node_id == payload.node_id
        and attempt.lease_id == payload.lease_id
        and attempt.lease_generation == payload.lease_generation
    )


def _authority_reason(projection: GraphProjection, payload: Any) -> str | None:
    """Bind every boundary fact to its snapshot, node, and active lease."""
    binding = cache_authority_binding(projection)
    supplied = getattr(payload, "cache_authority_hash", None)
    expected = binding.hash
    node_hash = node_cache_authority_hash(projection, payload.node_id)
    lease = lease_by_id(projection, payload.lease_id)
    if cache_authority_is_new_format(projection) and supplied != expected:
        return "cache_authority_hash does not match routine snapshot"
    if supplied is not None and supplied != expected:
        return "cache_authority_hash does not match routine snapshot"
    if cache_authority_is_new_format(projection) and node_hash != expected:
        return "node cache_authority_hash does not match routine snapshot"
    if lease is None or lease.cache_authority_hash not in (
        {expected} if cache_authority_is_new_format(projection) else {None, expected}
    ):
        return "lease cache_authority_hash does not match routine snapshot"
    roots = getattr(payload, "observed_cache_roots", getattr(payload, "cache_roots", ()))
    evidence = getattr(payload, "cache_status_evidence", ())
    try:
        validate_authorized_cache_roots(roots, binding.policy, status=evidence)
    except ValueError as exc:
        return str(exc)
    return None


def _authorized_roots(attempt: Any, roots: Any) -> list[RunnerCacheRoot]:
    from orchestrator.graph.cache_authority import latest_cache_root_union

    return list(
        latest_cache_root_union(
            *(
                tuple(value for value in phase if not isinstance(value, str))
                for phase in (
                    attempt.baseline_cache_roots,
                    attempt.staged_cache_roots,
                    attempt.final_cache_roots,
                    attempt.recovery_observed_cache_roots,
                    roots,
                )
            )
        )
    )


def handle_record_runner_baseline(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordRunnerBaselineCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    del events, command_type, context, clock, id_gen
    if reason := _authority_reason(projection, payload):
        return _conflict(make_event, "record_runner_baseline", reason)
    attempt = execution_attempts_view(projection).get(payload.execution_id)
    event_payload = payload.model_dump(mode="json", exclude={"cache_roots"})
    if attempt is not None:
        if (
            attempt.state == "baseline_captured"
            and attempt.node_id == payload.node_id
            and attempt.lease_id == payload.lease_id
            and attempt.lease_generation == payload.lease_generation
            and attempt.lease_base_snapshot_id == payload.lease_base_snapshot_id
            and attempt.baseline_snapshot_id == payload.baseline_snapshot_id
            and attempt.baseline_snapshot_ref == payload.baseline_snapshot_ref
            and attempt.baseline_commit_sha == payload.baseline_commit_sha
            and attempt.baseline_tree_sha == payload.baseline_tree_sha
            and attempt.baseline_boundary_hash == payload.boundary_hash
            and tuple(item.model_dump(mode="json") for item in attempt.baseline_entries)
            == tuple(event_payload["entries"])
            and tuple(attempt.baseline_cache_roots) == tuple(payload.cache_roots)
        ):
            return []
        return _conflict(make_event, "record_runner_baseline", "execution baseline conflicts")
    lease = lease_by_id(projection, payload.lease_id)
    if (
        lease is None
        or lease.state != "active"
        or lease.execution_id != payload.execution_id
        or lease.node_id != payload.node_id
        or lease.generation != payload.lease_generation
        or lease.base_snapshot_id
        != (payload.lease_base_snapshot_id or payload.baseline_snapshot_id)
    ):
        return _conflict(
            make_event, "record_runner_baseline", "unknown or incompatible active lease"
        )
    return [make_event("runner_baseline_recorded", event_payload)]


def handle_stage_runner_submission(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: StageRunnerSubmissionCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    del command_type, clock, id_gen
    if (
        payload.validation_witness is not None
        and payload.validation_witness.get("run_id") != context.run_id
    ):
        return _conflict(
            make_event,
            "stage_runner_submission",
            "validation_witness run_id does not match graph run",
        )
    if reason := _authority_reason(projection, payload):
        return _conflict(make_event, "stage_runner_submission", reason)
    attempt = execution_attempts_view(projection).get(payload.execution_id)
    if attempt is None or not _same_identity(attempt, payload):
        return _conflict(
            make_event, "stage_runner_submission", "unknown or incompatible execution baseline"
        )
    _, payload_size_bytes = validate_callback_json(payload.payload)
    digest, canonical_size_bytes = callback_payload_identity(payload.payload)
    if payload_size_bytes != canonical_size_bytes:
        return _conflict(make_event, "stage_runner_submission", "payload size is not canonical")
    if payload.payload_hash is not None and payload.payload_hash != digest:
        return _conflict(
            make_event, "stage_runner_submission", "payload_hash does not match payload"
        )
    if payload.payload_ref is not None and (
        payload.payload_ref.content_hash != digest
        or payload.payload_ref.artifact_id != digest
        or payload.payload_ref.size_bytes != payload_size_bytes
    ):
        return _conflict(
            make_event, "stage_runner_submission", "payload_ref does not match payload"
        )
    if attempt.state != "baseline_captured":
        same = (
            attempt.state
            in {
                "submission_staged",
                "completion_witnessed",
                "recovery_requested",
                "recovered",
                "finalized",
            }
            and attempt.idempotency_key == payload.idempotency_key
            and attempt.payload_hash == digest
            and attempt.staged_boundary_hash == payload.boundary_hash
            and tuple(attempt.staged_boundary_entries) == tuple(payload.boundary_entries)
            and attempt.staged_snapshot_id == payload.staged_snapshot_id
            and attempt.staged_snapshot_ref == payload.staged_snapshot_ref
            and attempt.staged_commit_sha == payload.staged_commit_sha
            and attempt.staged_tree_sha == payload.staged_tree_sha
            and attempt.observed_graph_position == payload.observed_graph_position
            and attempt.is_mutating == payload.is_mutating
            and attempt.complete_node == payload.complete_node
            and attempt.new_state == payload.new_state
            and attempt.payload_size_bytes == payload_size_bytes
            and attempt.staged_cache_roots == tuple(payload.cache_roots)
            and attempt.staged_cache_status_evidence == tuple(payload.cache_status_evidence)
            and attempt.cache_authority_hash == payload.cache_authority_hash
            and thaw_json(attempt.validation_witness) == payload.validation_witness
        )
        return (
            []
            if same
            else _conflict(make_event, "stage_runner_submission", "execution submission conflicts")
        )
    # Reuse the established callback validator/contract checks, but deliberately
    # discard its effect events until the boundary is finalized.
    validation = apply_callback_command(
        projection,
        events,
        payload,
        context.run_id,
        make_event,
        allow_recorded_runner_execution=True,
    )
    if not validation or validation[0].event_type != "callback_accepted":
        return [make_event(item.event_type, item.payload) for item in validation]
    if any(item.event_type == "file_state_rejected" for item in validation):
        # A rejected boundary has no staged snapshot. Preserve the callback
        # and rejection facts so runtime recovery is armed instead of
        # publishing a synthetic staged submission that finalization cannot
        # validate.
        return [make_event(item.event_type, item.payload) for item in validation]
    owns_file_state_snapshot = _accepted_file_state_owns_staged_snapshot(validation, payload)
    staged = {
        "execution_id": payload.execution_id,
        "node_id": payload.node_id,
        "lease_id": payload.lease_id,
        "lease_generation": payload.lease_generation,
        "idempotency_key": payload.idempotency_key,
        # Inline bodies are retained only for legacy command callers. Runtime
        # staging always supplies a CAS ref and therefore emits no body.
        **(
            {"payload_ref": payload.payload_ref.model_dump(mode="json")}
            if payload.payload_ref is not None
            else {"payload": payload.payload}
        ),
        "payload_hash": digest,
        "payload_size_bytes": payload_size_bytes,
        "staged_snapshot_id": payload.staged_snapshot_id,
        "staged_snapshot_ref": payload.staged_snapshot_ref,
        "staged_commit_sha": payload.staged_commit_sha,
        "staged_tree_sha": payload.staged_tree_sha,
        "boundary_hash": payload.boundary_hash,
        "boundary_entries": [entry.model_dump(mode="json") for entry in payload.boundary_entries],
        "base_snapshot_id": payload.base_snapshot_id,
        "observed_graph_position": payload.observed_graph_position,
        "is_mutating": payload.is_mutating,
        "complete_node": payload.complete_node,
        "new_state": payload.new_state,
        "owns_file_state_snapshot": owns_file_state_snapshot,
        "cache_authority_hash": payload.cache_authority_hash,
        "cache_status_evidence": payload.cache_status_evidence,
        "validation_witness": payload.validation_witness,
        "disposition": "durably_staged",
    }
    return [make_event("runner_submission_staged", staged)]


def handle_finalize_runner_execution(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: FinalizeRunnerExecutionCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    del command_type, clock, id_gen
    if reason := _authority_reason(projection, payload):
        return _conflict(make_event, "finalize_runner_execution", reason)
    attempt = execution_attempts_view(projection).get(payload.execution_id)
    if attempt is None or not _same_identity(attempt, payload):
        return _conflict(
            make_event, "finalize_runner_execution", "unknown or incompatible execution baseline"
        )
    if attempt.state == "finalized":
        same = (
            attempt.final_snapshot_id == payload.final_snapshot_id
            and attempt.final_snapshot_ref == payload.final_snapshot_ref
            and attempt.final_commit_sha == payload.final_commit_sha
            and attempt.final_tree_sha == payload.final_tree_sha
            and attempt.final_boundary_hash == payload.boundary_hash
            and tuple(attempt.final_boundary_entries) == tuple(payload.boundary_entries)
            and attempt.final_cache_roots == tuple(payload.cache_roots)
            and attempt.final_cache_status_evidence == tuple(payload.cache_status_evidence)
            and attempt.cache_authority_hash == payload.cache_authority_hash
        )
        return (
            []
            if same
            else _conflict(
                make_event, "finalize_runner_execution", "execution finalization conflicts"
            )
        )
    if attempt.state != "completion_witnessed":
        return _conflict(
            make_event,
            "finalize_runner_execution",
            "runner completion and final boundary are not durably witnessed",
        )
    if not _final_boundary_matches_attempt(attempt, payload):
        return _conflict(
            make_event,
            "finalize_runner_execution",
            "finalization does not match durable completion witness",
        )
    resolved_callback_payload = (
        payload.callback_payload
        if payload.callback_payload is not None
        else thaw_json(attempt.payload)
    )
    if not isinstance(resolved_callback_payload, dict):
        return _conflict(
            make_event,
            "finalize_runner_execution",
            "staged callback artifact was not resolved",
        )
    resolved_callback_payload = cast(dict[str, Any], resolved_callback_payload)
    _, resolved_size = validate_callback_json(resolved_callback_payload)
    resolved_hash, canonical_size = callback_payload_identity(resolved_callback_payload)
    if (
        resolved_size != canonical_size
        or resolved_hash != attempt.payload_hash
        or resolved_size != attempt.payload_size_bytes
    ):
        return _conflict(
            make_event,
            "finalize_runner_execution",
            "resolved callback payload does not match staged identity",
        )
    callback = {
        "node_id": attempt.node_id,
        "execution_id": attempt.execution_id,
        "lease_id": attempt.lease_id,
        "lease_generation": attempt.lease_generation,
        "base_snapshot_id": attempt.callback_base_snapshot_id or attempt.baseline_snapshot_id,
        "observed_graph_position": attempt.observed_graph_position,
        "idempotency_key": attempt.idempotency_key,
        "payload": resolved_callback_payload,
        "is_mutating": attempt.is_mutating,
        "complete_node": attempt.complete_node,
        "new_state": attempt.new_state,
    }
    # This dry run owns the existing callback/lease/run/node and output-contract
    # validation.  Never publish a finalization fact until every callback effect
    # is known to be accepted.
    callback_plan = apply_callback_command(
        projection,
        events,
        StageRunnerSubmissionCommand.model_validate(
            {
                **callback,
                "staged_snapshot_id": attempt.staged_snapshot_id,
                "staged_snapshot_ref": attempt.staged_snapshot_ref,
                "staged_commit_sha": attempt.staged_commit_sha,
                "staged_tree_sha": attempt.staged_tree_sha,
                "boundary_hash": attempt.staged_boundary_hash,
                "boundary_entries": [
                    entry.model_dump(mode="json") for entry in attempt.staged_boundary_entries
                ],
                "cache_authority_hash": attempt.cache_authority_hash,
                "cache_roots": [
                    RunnerCacheRoot.model_validate(root).model_dump(mode="json")
                    for root in attempt.staged_cache_roots
                    if not isinstance(root, str)
                ],
                "cache_status_evidence": [
                    item.model_dump(mode="json") for item in attempt.staged_cache_status_evidence
                ],
            }
        ),
        context.run_id,
        make_event,
        allow_recorded_runner_execution=True,
    )
    if not callback_plan or callback_plan[0].event_type != "callback_accepted":
        return [make_event(item.event_type, item.payload) for item in callback_plan]
    # Finalization precedes every externally visible callback effect atomically.
    final_payload = payload.model_dump(mode="json", exclude={"callback_payload", "cache_roots"})
    final_payload["disposition"] = "finalized_accepted"
    staged_snapshot_transferred = _accepted_file_state_owns_staged_snapshot(callback_plan, attempt)
    return [
        make_event("runner_execution_finalized", final_payload),
        *(make_event(item.event_type, item.payload) for item in callback_plan),
        *_snapshot_cleanup_events(
            make_event,
            attempt,
            final_snapshot=(
                payload.final_snapshot_id,
                payload.final_snapshot_ref,
                payload.final_tree_sha,
                payload.final_commit_sha,
            ),
            retain_staged_snapshot=staged_snapshot_transferred,
        ),
    ]


def handle_witness_runner_completion(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: WitnessRunnerCompletionCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    """Record runner success and its final boundary before acceptance."""
    del command_type, context, clock, id_gen
    if reason := _authority_reason(projection, payload):
        return _conflict(make_event, "witness_runner_completion", reason)
    attempt = execution_attempts_view(projection).get(payload.execution_id)
    if attempt is None or not _same_identity(attempt, payload):
        return _conflict(
            make_event,
            "witness_runner_completion",
            "unknown or incompatible staged execution",
        )
    if attempt.state in {"completion_witnessed", "recovery_requested", "recovered"}:
        return (
            []
            if _witness_matches_attempt(attempt, payload)
            else _conflict(
                make_event,
                "witness_runner_completion",
                "runner completion witness conflicts",
            )
        )
    if attempt.state == "finalized":
        return (
            []
            if _witness_matches_attempt(attempt, payload)
            else _conflict(
                make_event,
                "witness_runner_completion",
                "runner completion witness conflicts with finalization",
            )
        )
    if attempt.state != "submission_staged":
        return _conflict(
            make_event,
            "witness_runner_completion",
            "execution submission is not staged",
        )
    staged_identity_matches = (
        attempt.payload_hash == payload.staged_payload_hash
        and attempt.payload_size_bytes == payload.staged_payload_size_bytes
        and attempt.staged_snapshot_id == payload.staged_snapshot_id
        and attempt.staged_snapshot_ref == payload.staged_snapshot_ref
        and attempt.staged_commit_sha == payload.staged_commit_sha
        and attempt.staged_tree_sha == payload.staged_tree_sha
        and attempt.staged_boundary_hash == payload.staged_boundary_hash
    )
    if not staged_identity_matches:
        return _conflict(
            make_event,
            "witness_runner_completion",
            "staged payload or snapshot identity does not match",
        )
    witness_payload = payload.model_dump(mode="json", exclude={"callback_payload", "cache_roots"})
    witness_payload["disposition"] = "completion_witnessed"
    witnessed = make_event("runner_completion_witnessed", witness_payload)
    if attempt.staged_boundary_hash == payload.boundary_hash:
        return [witnessed]
    recovery_paths = _recovery_paths(attempt, payload)
    if not recovery_paths:
        return _conflict(
            make_event,
            "witness_runner_completion",
            "boundary mismatch has no manifest delta",
        )
    recovery_id = f"recovery:{payload.execution_id}:{attempt.staged_boundary_hash}"
    return [
        witnessed,
        make_event(
            "runner_boundary_mismatch",
            {
                "execution_id": payload.execution_id,
                "node_id": payload.node_id,
                "lease_id": payload.lease_id,
                "lease_generation": payload.lease_generation,
                "staged_boundary_hash": attempt.staged_boundary_hash,
                "final_boundary_hash": payload.boundary_hash,
                "final_tree_sha": payload.final_tree_sha,
                "final_snapshot_id": payload.final_snapshot_id,
                "final_snapshot_ref": payload.final_snapshot_ref,
                "final_commit_sha": payload.final_commit_sha,
                "final_boundary_entries": [
                    entry.model_dump(mode="json") for entry in payload.boundary_entries
                ],
                "cache_authority_hash": payload.cache_authority_hash,
                "cache_status_evidence": payload.cache_status_evidence,
                "reason": "boundary_mismatch",
            },
        ),
        make_event(
            "runner_recovery_requested",
            {
                "execution_id": payload.execution_id,
                "recovery_id": recovery_id,
                "node_id": attempt.node_id,
                "lease_id": attempt.lease_id,
                "lease_generation": attempt.lease_generation,
                "reason": "boundary_mismatch",
                "max_attempts": node_max_attempts_view(projection).get(attempt.node_id, 0),
                "baseline_snapshot_id": attempt.baseline_snapshot_id,
                "baseline_tree_sha": attempt.baseline_tree_sha,
                "final_tree_sha": payload.final_tree_sha,
                "final_snapshot_id": payload.final_snapshot_id,
                "final_snapshot_ref": payload.final_snapshot_ref,
                "final_commit_sha": payload.final_commit_sha,
                "final_boundary_hash": payload.boundary_hash,
                "final_boundary_entries": [
                    entry.model_dump(mode="json") for entry in payload.boundary_entries
                ],
                "cache_authority_hash": payload.cache_authority_hash,
                "cache_status_evidence": payload.cache_status_evidence,
                "paths": recovery_paths,
            },
        ),
    ]


def _final_boundary_matches_attempt(attempt: Any, payload: Any) -> bool:
    return (
        attempt.final_snapshot_id == payload.final_snapshot_id
        and attempt.final_snapshot_ref == payload.final_snapshot_ref
        and attempt.final_commit_sha == payload.final_commit_sha
        and attempt.final_tree_sha == payload.final_tree_sha
        and attempt.final_boundary_hash == payload.boundary_hash
        and tuple(attempt.final_boundary_entries) == tuple(payload.boundary_entries)
        and attempt.final_cache_roots == tuple(payload.cache_roots)
        and attempt.final_cache_status_evidence == tuple(payload.cache_status_evidence)
        and attempt.cache_authority_hash == payload.cache_authority_hash
    )


def _witness_matches_attempt(attempt: Any, payload: WitnessRunnerCompletionCommand) -> bool:
    return (
        attempt.payload_hash == payload.staged_payload_hash
        and attempt.payload_size_bytes == payload.staged_payload_size_bytes
        and attempt.staged_snapshot_id == payload.staged_snapshot_id
        and attempt.staged_snapshot_ref == payload.staged_snapshot_ref
        and attempt.staged_commit_sha == payload.staged_commit_sha
        and attempt.staged_tree_sha == payload.staged_tree_sha
        and attempt.staged_boundary_hash == payload.staged_boundary_hash
        and attempt.runner_return_kind == payload.runner_return_kind
        and _final_boundary_matches_attempt(attempt, payload)
    )


def _accepted_file_state_owns_staged_snapshot(
    callback_plan: list[EventEnvelope], attempt: Any
) -> bool:
    """Return whether durable accepted output takes exact staged-ref ownership.

    The accepted ``file_state_accepted`` event is the durable owner.  Equality
    includes the private ref and both Git object identities, preventing a
    same-tree alias or foreign ref from suppressing managed cleanup.
    """
    for event in callback_plan:
        if event.event_type != "file_state_accepted":
            continue
        record = FileStateRecord.model_validate(event.payload)
        git = record.git
        if (
            record.snapshot_id == attempt.staged_snapshot_id
            and git is not None
            and git.ref == attempt.staged_snapshot_ref
            and git.commit_sha == attempt.staged_commit_sha
            and git.tree_sha == attempt.staged_tree_sha
        ):
            return True
    return False


def _recovery_paths(attempt: Any, final: FinalizeRunnerExecutionCommand) -> list[str]:
    """Derive recovery authority from all persisted boundary preimages."""
    return list(
        derive_recovery_paths(
            attempt.baseline_entries,
            attempt.staged_boundary_entries,
            final.boundary_entries,
            _authorized_roots(attempt, final.cache_roots),
            attempt.legacy_cache_root_paths,
        )
    )


def handle_request_runner_recovery(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RequestRunnerRecoveryCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    """Request durable restore after no-submit, failure, exception, or cancellation."""
    del events, command_type, context, clock, id_gen
    if reason := _authority_reason(projection, payload):
        return _conflict(make_event, "request_runner_recovery", reason)
    attempt = execution_attempts_view(projection).get(payload.execution_id)
    if attempt is None or not _same_identity(attempt, payload):
        return _conflict(make_event, "request_runner_recovery", "unknown execution baseline")
    if attempt.state not in {"baseline_captured", "submission_staged", "completion_witnessed"}:
        if attempt.state == "recovery_requested":
            paths = _request_recovery_paths(attempt, payload)
            recovery_id = f"recovery:{payload.execution_id}:{payload.reason}"
            # The baseline identity is persisted on the attempt; keep this
            # explicit rather than treating a repeated recovery request as an
            # unconditional no-op.
            same = (
                attempt.recovery_id == recovery_id
                and attempt.recovery_reason == payload.reason
                and attempt.recovery_error_detail == payload.error_detail
                and attempt.recovery_max_attempts == payload.max_attempts
                and attempt.retry_after_recovery == payload.retry_after_recovery
                and attempt.node_id == payload.node_id
                and attempt.lease_id == payload.lease_id
                and attempt.lease_generation == payload.lease_generation
                and attempt.recovery_snapshot_id == payload.recovery_snapshot_id
                and attempt.recovery_snapshot_ref == payload.recovery_snapshot_ref
                and attempt.recovery_commit_sha == payload.recovery_commit_sha
                and attempt.final_tree_sha == payload.final_tree_sha
                and attempt.final_boundary_hash == payload.boundary_hash
                and attempt.final_boundary_entries == tuple(payload.boundary_entries)
                and attempt.recovery_paths == tuple(paths)
                and attempt.recovery_scope == payload.recovery_scope
            )
            if same:
                return []
            return _conflict(make_event, "request_runner_recovery", "recovery request conflicts")
        return _conflict(make_event, "request_runner_recovery", "execution is already terminal")
    paths = _request_recovery_paths(attempt, payload)
    # A runner which made no observable filesystem change still needs its lease
    # released through the durable recovery completion path.  Restoring no paths
    # is an idempotent proof of that cleanup.
    recovery_id = f"recovery:{payload.execution_id}:{payload.reason}"
    return [
        make_event(
            "runner_recovery_requested",
            {
                "execution_id": payload.execution_id,
                "recovery_id": recovery_id,
                "node_id": attempt.node_id,
                "lease_id": attempt.lease_id,
                "lease_generation": attempt.lease_generation,
                "reason": payload.reason,
                "error_detail": payload.error_detail,
                "max_attempts": payload.max_attempts,
                "retry_after_recovery": payload.retry_after_recovery,
                "recovery_snapshot_id": payload.recovery_snapshot_id,
                "recovery_snapshot_ref": payload.recovery_snapshot_ref,
                "recovery_commit_sha": payload.recovery_commit_sha,
                "baseline_snapshot_id": attempt.baseline_snapshot_id,
                "baseline_tree_sha": attempt.baseline_tree_sha,
                "final_tree_sha": payload.final_tree_sha,
                "final_boundary_hash": payload.boundary_hash,
                "final_boundary_entries": [
                    entry.model_dump(mode="json") for entry in payload.boundary_entries
                ],
                "cache_authority_hash": payload.cache_authority_hash,
                "cache_status_evidence": payload.cache_status_evidence,
                "paths": paths,
                "recovery_scope": payload.recovery_scope,
            },
        )
    ]


def _request_recovery_paths(attempt: Any, payload: RequestRunnerRecoveryCommand) -> list[str]:
    """Use compact full-baseline scope instead of serializing overflow paths."""
    if payload.recovery_scope == "full_baseline":
        return []
    return list(
        derive_recovery_paths(
            attempt.baseline_entries,
            attempt.staged_boundary_entries,
            payload.boundary_entries,
            _authorized_roots(attempt, payload.observed_cache_roots),
            attempt.legacy_cache_root_paths,
        )
    )


def handle_complete_runner_recovery(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: CompleteRunnerRecoveryCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    del events, command_type, context, clock, id_gen
    attempt = execution_attempts_view(projection).get(payload.execution_id)
    if attempt is None or attempt.recovery_id != payload.recovery_id:
        return _conflict(make_event, "complete_runner_recovery", "unknown recovery")
    if attempt.state == "recovered":
        if (
            payload.node_id == attempt.node_id
            and payload.lease_id == attempt.lease_id
            and payload.lease_generation == attempt.lease_generation
            and payload.baseline_snapshot_id == attempt.baseline_snapshot_id
            and payload.baseline_tree_sha == attempt.baseline_tree_sha
            and tuple(payload.requested_paths) == attempt.recovery_paths
            and tuple(payload.restored_paths) == attempt.restored_paths
            and tuple(payload.removed_paths) == attempt.removed_paths
            and payload.proof_hash == attempt.recovery_proof_hash
            and payload.recovery_scope == attempt.recovery_scope
        ):
            return []
        return _conflict(make_event, "complete_runner_recovery", "recovery completion conflicts")
    if attempt.state != "recovery_requested":
        return _conflict(make_event, "complete_runner_recovery", "recovery is not pending")
    if (
        payload.node_id != attempt.node_id
        or payload.lease_id != attempt.lease_id
        or payload.lease_generation != attempt.lease_generation
        or payload.baseline_snapshot_id != attempt.baseline_snapshot_id
        or payload.baseline_tree_sha != attempt.baseline_tree_sha
        or tuple(payload.requested_paths) != attempt.recovery_paths
        or payload.recovery_scope != attempt.recovery_scope
        or payload.proof_hash
        != recovery_proof_hash(
            execution_id=payload.execution_id,
            recovery_id=payload.recovery_id,
            node_id=payload.node_id,
            lease_id=payload.lease_id,
            lease_generation=payload.lease_generation,
            baseline_snapshot_id=payload.baseline_snapshot_id,
            baseline_tree_sha=payload.baseline_tree_sha,
            requested_paths=tuple(payload.requested_paths),
            restored_paths=tuple(payload.restored_paths),
            removed_paths=tuple(payload.removed_paths),
            recovery_scope=payload.recovery_scope,
        )
    ):
        return _conflict(make_event, "complete_runner_recovery", "recovery proof conflicts")
    lifecycle_events = [
        make_event(
            "lease_revoked",
            LeaseRevokedPayload(
                lease_id=attempt.lease_id,
                node_id=attempt.node_id,
                generation=attempt.lease_generation,
                execution_id=attempt.execution_id,
                trigger="runner_recovery_completed",
                reason=attempt.recovery_reason,
            ).model_dump(mode="json", exclude_none=True),
        )
    ]
    retryable_recovery = attempt.recovery_reason in {
        "boundary_mismatch",
        "runner_died",
        "staged_artifact_missing",
        "staged_artifact_corrupt",
    } or (attempt.recovery_reason == "cancelled" and attempt.retry_after_recovery)
    if retryable_recovery:
        attempt_number = node_attempts_view(projection).get(attempt.node_id, 0)
        max_attempts = attempt.recovery_max_attempts or 0
        if attempt.recovery_reason == "runner_died" and non_gap_planner_has_accepted_patch(
            projection, attempt.node_id
        ):
            lifecycle_events.append(
                make_event(
                    "node_state_changed",
                    {
                        "node_id": attempt.node_id,
                        "new_state": "completed",
                        "trigger": "accepted_graph_patch_before_agent_death",
                    },
                )
            )
        elif max_attempts > 0 and attempt_number >= max_attempts:
            failure_reason = (
                attempt.recovery_error_detail or attempt.recovery_reason or "max_attempts_exhausted"
            )
            lifecycle_events.append(
                make_event(
                    "node_state_changed",
                    {
                        "node_id": attempt.node_id,
                        "new_state": "failed",
                        "trigger": "max_attempts_exhausted",
                        "reason": failure_reason,
                        "attempt_number": attempt_number,
                        "max_attempts": max_attempts,
                    },
                )
            )
        else:
            next_attempt_number = attempt_number + 1
            lifecycle_events.extend(
                [
                    make_event(
                        "runtime_retry_scheduled",
                        {
                            "node_id": attempt.node_id,
                            "lease_id": attempt.lease_id,
                            "generation": attempt.lease_generation,
                            "policy": "v1_requeue_same_node_after_agent_death",
                            "reason": attempt.recovery_reason,
                        },
                    ),
                    make_event(
                        "node_state_changed",
                        {
                            "node_id": attempt.node_id,
                            "new_state": "ready",
                            "trigger": "runner_recovery_completed_retry_scheduled",
                            "attempt_number": next_attempt_number,
                        },
                    ),
                ]
            )
    return [
        make_event(
            "runner_recovery_completed",
            {
                **payload.model_dump(mode="json"),
                "disposition": _recovery_completion_disposition(attempt),
            },
        ),
        *lifecycle_events,
        # A recovered candidate remains operator-inspectable. Its exact staged
        # ref and CAS identity are retained; only a later explicit disposition
        # policy may garbage-collect them.
        *_snapshot_cleanup_events(make_event, attempt, retain_staged_snapshot=True),
    ]


def _recovery_completion_disposition(attempt: Any) -> str:
    if attempt.recovery_reason == "staged_artifact_missing":
        return "restored_artifact_missing"
    if attempt.recovery_reason == "staged_artifact_corrupt":
        return "restored_artifact_corrupt"
    if attempt.runner_return_kind == "successful_return":
        return "restored_boundary_mismatch"
    return "restored_unwitnessed"


def _snapshot_cleanup_events(
    make_event: Any,
    attempt: Any,
    *,
    final_snapshot: tuple[str, str | None, str, str | None] | None = None,
    retain_staged_snapshot: bool = False,
) -> list[EventEnvelope]:
    """Plan exact owned-ref deletion after its last recovery use.

    A missing ref marks pre-ownership history and is intentionally never
    guessed.  Every emitted cleanup fact includes the full lease identity and
    expected tree, allowing the worker to delete only the ref this execution
    created even when another execution captured an identical commit.
    """
    snapshots: list[tuple[str, str, str | None, str | None, str | None]] = [
        (
            "baseline",
            attempt.baseline_snapshot_id,
            attempt.baseline_snapshot_ref,
            attempt.baseline_tree_sha,
            attempt.baseline_commit_sha,
        ),
    ]
    if not retain_staged_snapshot:
        snapshots.append(
            (
                "staged",
                attempt.staged_snapshot_id,
                attempt.staged_snapshot_ref,
                attempt.staged_tree_sha,
                attempt.staged_commit_sha,
            )
        )
    if final_snapshot is not None:
        snapshots.append(("final", *final_snapshot))
    else:
        snapshots.append(
            (
                "final",
                attempt.final_snapshot_id,
                attempt.final_snapshot_ref,
                attempt.final_tree_sha,
                attempt.final_commit_sha,
            )
        )
    # Recovery snapshots are intentionally absent until recovery completion;
    # baseline remains available to the restorer until that same transaction.
    recovery_id = getattr(attempt, "recovery_snapshot_id", None)
    recovery_ref = getattr(attempt, "recovery_snapshot_ref", None)
    if recovery_id is not None:
        snapshots.append(
            (
                "recovery",
                recovery_id,
                recovery_ref,
                attempt.final_tree_sha,
                attempt.recovery_commit_sha,
            )
        )
    events: list[EventEnvelope] = []
    for role, snapshot_id, snapshot_ref, tree_sha, commit_sha in snapshots:
        if not all(
            isinstance(value, str) and value
            for value in (snapshot_id, snapshot_ref, tree_sha, commit_sha)
        ):
            continue
        events.append(
            make_event(
                "cleanup_requested",
                {
                    "cleanup_id": f"runner-snapshot:{attempt.execution_id}:{role}",
                    "snapshot_id": snapshot_id,
                    "snapshot_ref": snapshot_ref,
                    "tree_sha": tree_sha,
                    "commit_sha": commit_sha,
                    "node_id": attempt.node_id,
                    "lease_id": attempt.lease_id,
                    "lease_generation": attempt.lease_generation,
                    "snapshot_role": role,
                    "reason": "managed_runner_boundary_no_longer_needed",
                    "execution_id": attempt.execution_id,
                },
            )
        )
    return events


def handle_record_managed_snapshot_cleanup_applied(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: RecordManagedSnapshotCleanupAppliedCommand,
    context: GraphCommandContext,
    make_event: Any,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    del events, command_type, context, clock, id_gen
    return apply_record_managed_snapshot_cleanup_applied(projection, payload, make_event)
