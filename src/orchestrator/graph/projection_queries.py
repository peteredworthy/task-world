"""Pure queries over graph projection storage.

Each query owns the physical projection access and returns values that cannot
mutate projection containers.
"""

from typing import Any, cast

from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CheckResultProjection,
    CommandDefinitionProjection,
    CleanupRequestedProjection,
    EdgeProjection,
    EnvironmentFailureProjection,
    FileStateRecord,
    InputBindingProjection,
    LeaseProjection,
    OUTPUT_RECORD_MODELS_BY_TYPE,
    OutputRecordAcceptedPayload,
    ResourceClaimProjection,
    VerificationResultProjection,
    VerifierVerdictProjection,
)
from orchestrator.graph.cache_authority import (
    CacheAuthorityBinding,
    CacheAuthorityPolicy,
    LEGACY_CACHE_AUTHORITY_V1,
    POLICY_VERSION,
    cache_authority_hash,
    canonicalize_cache_authority,
    has_cache_authority_carrier,
)
from orchestrator.graph.projection_collections import (
    FrozenJsonValue,
    FrozenMap,
    JsonValue,
    thaw_json,
)
from orchestrator.graph.projection_models import ExecutionAttemptValue
from orchestrator.graph.projection_models import (
    GraphRecordSummaryProjection,
    ProjectedFanOutInputsRecord,
    ProjectionModel,
)
from orchestrator.graph.projections import (
    AcceptedOutputRecord,
    GraphProjection,
    GraphRecordSummary,
    LatestRoutineSnapshotRecord,
    RecoveryNodeIndexEntry,
)
from orchestrator.graph.projection_models import ProjectedRoutineSnapshotRecord


def non_gap_planner_has_accepted_patch(projection: GraphProjection, node_id: str) -> bool:
    """Return whether a regular planner has already published an accepted patch."""
    node = projection.nodes.get(node_id)
    return (
        node is not None
        and node.spec.kind == "planner"
        and node.spec.role != "gap_planner"
        and bool(projection.planning.accepted_patch_ids_by_node.get(node_id))
    )


def output_record_payloads_view(
    projection: GraphProjection,
) -> dict[str, AcceptedOutputRecordPayload]:
    return {
        record_id: OutputRecordAcceptedPayload.model_validate(
            record.model_dump(mode="json", by_alias=True)
        ).root
        for record_id, record in projection.records.by_id.items()
        if record.record_type != "file_state"
    }


def accepted_no_successor_patches_by_node_view(
    projection: GraphProjection,
) -> dict[str, list[str]]:
    return {
        node_id: list(ids)
        for node_id, ids in projection.planning.no_successor_patch_ids_by_node.items()
    }


def accepted_output_records_by_node_port_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[AcceptedOutputRecord]]]:
    return {
        node_id: {
            port: [
                {
                    "record_id": record_id,
                    "payload": _accepted_output_record(projection, record_id),
                }
                for record_id in record_ids
            ]
            for port, record_ids in ports.items()
        }
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def accepted_record_summaries_by_id_view(
    projection: GraphProjection,
) -> dict[str, GraphRecordSummary]:
    return {
        record_id: _graph_record_summary(summary)
        for record_id, summary in projection.records.summaries_by_id.items()
    }


def active_requirement_versions_view(projection: GraphProjection) -> dict[str, str]:
    return dict(projection.requirements.active_version_id_by_requirement)


def callback_idempotency_events_view(
    projection: GraphProjection,
) -> dict[str, CallbackIdempotencyEvent]:
    return {
        key: CallbackIdempotencyEvent.model_validate(value.model_dump(mode="json"))
        for key, value in projection.execution.callback_events_by_key.items()
    }


def execution_attempts_view(projection: GraphProjection) -> dict[str, ExecutionAttemptValue]:
    """Return immutable runner attempts keyed by external execution identity."""
    return dict(projection.execution.attempts_by_execution_id)


def check_results_view(projection: GraphProjection) -> dict[str, CheckResultProjection]:
    return {
        node_id: CheckResultProjection.model_validate(result.model_dump(mode="json"))
        for node_id, result in projection.verification.check_results_by_node.items()
    }


def cleanup_applied_ids_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.execution.applied_cleanup_ids)


def cleanup_requested_events_view(
    projection: GraphProjection,
) -> dict[str, CleanupRequestedProjection]:
    return {
        cleanup_id: CleanupRequestedProjection.model_validate(request.model_dump(mode="json"))
        for cleanup_id, request in projection.execution.cleanup_requests_by_id.items()
    }


def edges_view(projection: GraphProjection) -> dict[str, EdgeProjection]:
    return {
        edge_id: EdgeProjection.model_validate(edge.model_dump(mode="json"))
        for edge_id, edge in projection.topology.edges.items()
    }


def environment_failures_view(
    projection: GraphProjection,
) -> dict[str, EnvironmentFailureProjection]:
    return {
        task_id: EnvironmentFailureProjection.model_validate(failure.model_dump(mode="json"))
        for task_id, failure in projection.execution.environment_failures_by_task.items()
    }


def failed_verification_candidate_ids_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.verification.failed_candidate_ids)


def failed_verification_results_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, VerificationResultProjection]:
    return {
        record_id: VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        for record_id, result in projection.verification.failed_results_by_record_id.items()
    }


def file_state_records_view(projection: GraphProjection) -> dict[str, FileStateRecord]:
    return {
        record_id: FileStateRecord.model_validate(
            {
                key: value
                for key, value in record.model_dump(mode="json", by_alias=True).items()
                if key != "acceptance_identity"
            }
        )
        for record_id, record in projection.records.by_id.items()
        if record.record_type == "file_state"
    }


def input_bindings_view(
    projection: GraphProjection,
) -> dict[str, dict[str, InputBindingProjection]]:
    return {
        node_id: {
            port: InputBindingProjection.model_validate(ports[port].model_dump(mode="json"))
            for port in projection.topology.input_binding_port_order.get(node_id, ())
        }
        for node_id, ports in projection.topology.input_bindings.items()
    }


def last_deferred_reasons_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.scheduling.last_deferred_reason
        for node_id, node in projection.nodes.items()
        if node.scheduling.last_deferred_reason is not None
    }


def leases_view(projection: GraphProjection) -> dict[str, LeaseProjection]:
    return {
        lease_id: LeaseProjection.model_validate(
            projection.execution.leases[lease_id].model_dump(mode="json")
        )
        for lease_id in projection.execution.lease_ids_in_grant_order
    }


def node_attempts_view(projection: GraphProjection) -> dict[str, int]:
    return {
        node_id: node.runtime.attempt_number
        for node_id, node in projection.nodes.items()
        if node.runtime.attempt_number is not None
    }


def node_max_attempts_view(projection: GraphProjection) -> dict[str, int]:
    return {
        node_id: node.spec.max_attempts
        for node_id, node in projection.nodes.items()
        if node.spec.max_attempts is not None
    }


def node_command_definitions_view(
    projection: GraphProjection,
) -> dict[str, CommandDefinitionProjection]:
    return {
        node_id: _command_definition_value(node.spec.command_definition.value)
        for node_id, node in projection.nodes.items()
        if node.spec.command_definition is not None
    }


def node_payload_view(projection: GraphProjection, node_id: str) -> dict[str, Any] | None:
    """Return the durable scheduler payload for one projected node."""
    node = projection.nodes.get(node_id)
    if node is None:
        return None
    payload = node.spec.model_dump(mode="json", exclude_none=True)
    runtime = node.runtime.model_dump(mode="json", exclude_none=True)
    payload.update(runtime)
    command_definition = payload.get("command_definition")
    if isinstance(command_definition, dict) and "value" in command_definition:
        payload["command_definition"] = command_definition["value"]
    return payload


def node_creation_positions_view(projection: GraphProjection) -> dict[str, int]:
    return {node_id: node.spec.creation_position for node_id, node in projection.nodes.items()}


def node_cache_authority_hash(projection: GraphProjection, node_id: str) -> str | None:
    node = projection.nodes.get(node_id)
    return node.spec.cache_authority_hash if node is not None else None


def node_gate_decisions_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.governance.node_gate_decisions)


def node_failed_candidates_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.runtime.failed_candidate_id
        for node_id, node in projection.nodes.items()
        if node.runtime.failed_candidate_id is not None
    }


def node_pending_appeals_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.governance.pending_appeals_by_node)


def node_preconditions_view(projection: GraphProjection) -> dict[str, list[str]]:
    return {node_id: list(node.spec.preconditions) for node_id, node in projection.nodes.items()}


def node_kinds_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.kind
        for node_id, node in projection.nodes.items()
        if node.spec.kind is not None
    }


def node_resource_claims_view(
    projection: GraphProjection,
) -> dict[str, list[ResourceClaimProjection]]:
    return {
        node_id: [
            ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
            for claim in node.spec.resource_claims
        ]
        for node_id, node in projection.nodes.items()
    }


def node_roles_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.role
        for node_id, node in projection.nodes.items()
        if node.spec.role is not None
    }


def node_states_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.runtime.state
        for node_id, node in projection.nodes.items()
        if node.runtime.state is not None
    }


def node_task_regions_view(projection: GraphProjection) -> dict[str, str]:
    return {
        node_id: node.spec.task_region_id
        for node_id, node in projection.nodes.items()
        if node.spec.task_region_id is not None
    }


def output_records_by_node_port_view(
    projection: GraphProjection,
) -> dict[str, dict[str, list[AcceptedOutputRecordPayload]]]:
    return {
        node_id: {
            port: [
                _accepted_output_record(projection, record_id)
                for record_id in record_ids
                if projection.records.by_id[record_id].record_type != "file_state"
            ]
            for port, record_ids in ports.items()
        }
        for node_id, ports in projection.records.ids_by_node_port.items()
    }


def _accepted_output_record(
    projection: GraphProjection, record_id: str
) -> AcceptedOutputRecordPayload:
    record = projection.records.by_id[record_id]
    model = OUTPUT_RECORD_MODELS_BY_TYPE[record.record_type]
    values = (
        record.__dict__
        if isinstance(record, ProjectedFanOutInputsRecord)
        else {name: _event_record_value(value) for name, value in record.__dict__.items()}
    )
    if record.record_type == "file_state":
        values = {name: value for name, value in values.items() if name != "acceptance_identity"}
    return cast(
        AcceptedOutputRecordPayload,
        model.model_validate(values),
    )


def _event_record_value(value: object) -> object:
    if isinstance(value, FrozenMap):
        return value.thaw_json()
    if isinstance(value, ProjectionModel):
        return {name: _event_record_value(item) for name, item in value.__dict__.items()}
    if isinstance(value, tuple):
        return tuple(_event_record_value(item) for item in cast(tuple[object, ...], value))
    return value


def passed_verification_candidate_ids_view(projection: GraphProjection) -> list[str]:
    return list(projection.verification.passed_candidate_ids)


def passed_verification_results_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, VerificationResultProjection]:
    return {
        record_id: VerificationResultProjection.model_validate(result.model_dump(mode="json"))
        for record_id, result in projection.verification.passed_results_by_record_id.items()
    }


def planner_generations_view(projection: GraphProjection) -> dict[str, int]:
    return dict(projection.planning.generation_by_node)


def planner_session_carryovers_view(projection: GraphProjection) -> dict[str, str | None]:
    return {
        session_id: session.carryover_record_id
        for session_id, session in projection.planning.sessions.items()
    }


def planner_sessions_view(projection: GraphProjection) -> dict[str, str]:
    return dict(projection.planning.session_id_by_node)


def ready_nodes_view(projection: GraphProjection) -> list[str]:
    return list(projection.scheduling.ready_node_ids)


def recorded_node_usage_keys_view(projection: GraphProjection) -> dict[str, bool]:
    return dict(projection.usage.recorded_keys)


def recovery_nodes_by_record_id_view(
    projection: GraphProjection,
) -> dict[str, list[RecoveryNodeIndexEntry]]:
    return {
        record_id: [
            RecoveryNodeIndexEntry.model_validate(entry.model_dump(mode="json"))
            for entry in entries
        ]
        for record_id, entries in projection.verification.recovery_nodes_by_record_id.items()
    }


def retry_not_before_by_node_view(projection: GraphProjection) -> dict[str, str | None]:
    return {
        node_id: node.scheduling.retry_not_before
        for node_id, node in projection.nodes.items()
        if node.scheduling.retry_not_before is not None
    }


def task_candidates_view(
    projection: GraphProjection,
) -> dict[str, list[CandidateProjection]]:
    return {
        task_id: [
            CandidateProjection.model_validate(candidate.model_dump(mode="json"))
            for candidate in task.candidates
        ]
        for task_id, task in projection.tasks.items()
        if task.candidates
    }


def task_states_view(projection: GraphProjection) -> dict[str, str]:
    return {
        task_id: task.state for task_id, task in projection.tasks.items() if task.state is not None
    }


def verifier_verdicts_view(
    projection: GraphProjection,
) -> dict[str, VerifierVerdictProjection]:
    return {
        value.candidate_id: VerifierVerdictProjection.model_validate(value.model_dump(mode="json"))
        for value in projection.verification.verdicts_by_node.values()
    }


def resource_claims_for_node(
    projection: GraphProjection,
    node_id: str,
) -> tuple[ResourceClaimProjection, ...]:
    """Return a node's resource claims without exposing mutable projection storage."""
    node = projection.nodes.get(node_id)
    if node is None:
        return ()
    return tuple(
        ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
        for claim in node.spec.resource_claims
    )


def _command_definition_value(value: FrozenMap[str, FrozenJsonValue]) -> dict[str, JsonValue]:
    """Unwrap the frozen command-definition envelope into its public mapping."""
    definition = thaw_json(value)
    while isinstance(definition, dict) and set(definition) == {"value"}:
        definition = definition["value"]
    if not isinstance(definition, dict):
        raise ValueError("command definition must decode to a JSON object")
    return definition


def _graph_record_summary(summary: GraphRecordSummaryProjection) -> GraphRecordSummary:
    """Return the exact public TypedDict shape without exposing frozen storage."""
    view: GraphRecordSummary = {}
    if summary.record_id is not None:
        view["record_id"] = summary.record_id
    if summary.record_type is not None:
        view["record_type"] = summary.record_type
    if summary.record_kind is not None:
        view["record_kind"] = summary.record_kind
    if summary.schema_ is not None:
        view["schema"] = summary.schema_
    if summary.producer_node_id is not None:
        view["producer_node_id"] = summary.producer_node_id
    if summary.producer_port is not None:
        view["producer_port"] = summary.producer_port
    if summary.position is not None:
        view["position"] = summary.position
    return view


def lease_by_id(projection: GraphProjection, lease_id: str) -> LeaseProjection | None:
    """Return an independent lease copy, if it exists."""
    lease = projection.execution.leases.get(lease_id)
    return (
        LeaseProjection.model_validate(lease.model_dump(mode="json")) if lease is not None else None
    )


def run_state(projection: GraphProjection) -> str | None:
    """Return the current lifecycle state, or ``None`` before its first event."""
    return projection.lifecycle.run_state


def completion_decision_passed(projection: GraphProjection) -> bool:
    """Return whether the latest lifecycle completion decision passed."""
    return projection.lifecycle.completion_decision_passed


def planner_generation_budget(projection: GraphProjection) -> int:
    """Return the configured planner generation budget."""
    return projection.planning.generation_budget


def latest_routine_snapshot_record(
    projection: GraphProjection,
) -> LatestRoutineSnapshotRecord | None:
    """Return an independent latest routine snapshot record, if present."""
    record = projection.planning.latest_routine_snapshot
    return (
        LatestRoutineSnapshotRecord.model_validate(record.model_dump(mode="json"))
        if record is not None
        else None
    )


def cache_authority_binding(projection: GraphProjection) -> CacheAuthorityBinding:
    """Return the verified snapshot-owned cache authority, or frozen legacy V1.

    Snapshot values are the only full policy owner.  The preimage and digest are
    checked here rather than trusting a caller-supplied policy or command context.
    """
    record = projection.records.by_id.get("routine-snapshot-record")
    has_carrier = has_cache_authority_carrier(
        any(node.spec.cache_authority_hash is not None for node in projection.nodes.values()),
        (lease.cache_authority_hash for lease in projection.execution.leases.values()),
    )
    if record is None:
        if has_carrier:
            raise ValueError("routine snapshot graph requires canonical routine-snapshot-record")
        policy = LEGACY_CACHE_AUTHORITY_V1
        return CacheAuthorityBinding(
            policy=policy,
            preimage=canonicalize_cache_authority(policy),
            hash=cache_authority_hash(policy),
        )
    if not isinstance(record, ProjectedRoutineSnapshotRecord):
        raise ValueError("routine-snapshot-record must be a routine snapshot record")
    value = getattr(record, "value")
    preimage = getattr(value, "cache_authority_preimage", None)
    digest = getattr(value, "cache_authority_hash", None)
    version = getattr(value, "cache_authority_version", None)
    absent = version is None and preimage is None and digest is None
    present = isinstance(version, str) and isinstance(preimage, str) and isinstance(digest, str)
    if absent:
        if has_carrier:
            raise ValueError("routine snapshot cache authority is mixed with authority carriers")
        policy = LEGACY_CACHE_AUTHORITY_V1
        return CacheAuthorityBinding(
            policy=policy,
            preimage=canonicalize_cache_authority(policy),
            hash=cache_authority_hash(policy),
        )
    if not present or version != POLICY_VERSION:
        raise ValueError("routine snapshot cache authority format is malformed or unknown")
    if not isinstance(preimage, str) or not isinstance(digest, str):
        raise ValueError("routine snapshot cache authority values must be strings")
    try:
        policy = CacheAuthorityPolicy.model_validate_json(preimage)
    except ValueError as exc:
        raise ValueError("routine snapshot has invalid cache authority preimage") from exc
    if canonicalize_cache_authority(policy) != preimage or cache_authority_hash(policy) != digest:
        raise ValueError("routine snapshot cache authority hash verification failed")
    return CacheAuthorityBinding(policy=policy, preimage=preimage, hash=digest)


def cache_authority_is_new_format(projection: GraphProjection) -> bool:
    record = projection.records.by_id.get("routine-snapshot-record")
    return bool(
        record is not None
        and getattr(getattr(record, "value", None), "cache_authority_version", None)
    )
