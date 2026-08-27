"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
import posixpath
from typing import Any, Protocol, cast

from pydantic import ValidationError

from orchestrator.graph.callbacks import (
    CallbackOutcome,
    CallbackRequest,
    validate_callback,
    callback_payload_identity,
)
from orchestrator.graph.command_bindings import canonicalize_check_command_definition
from orchestrator.graph.command_models import (
    AcceptRunCommand,
    AcknowledgeStartCommand,
    AgentDiedCommand,
    CancelCommand,
    CompleteCommand,
    EvaluateFinalGateCommand,
    EvaluateJoinCommand,
    FailCommand,
    GatekeeperCostCommandRow,
    GraphCommandContext,
    PatchCommandContext,
    PauseCommand,
    RaiseAppealCommand,
    ReconcileCommand,
    RecordCleanupAppliedCommand,
    RecordManagedSnapshotCleanupAppliedCommand,
    RecordDecisionCommand,
    RecordGatekeeperVerdictsCommand,
    RecordHeartbeatCommand,
    RecordNodeUsageCommand,
    RecordRequirementRevisionCommand,
    RecordSupportEvidenceCommand,
    ResumeCommand,
    ScheduleTickCommand,
    SeedCompiledEventsCommand,
    StartCommand,
    SubmitCallbackCommand,
    SubmitPatchCommand,
)
from orchestrator.graph._error_rendering import safe_exception_reason, safe_validation_diagnostics
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy,
    input_port_contract,
    merge_bound_record_ids,
    output_port_contract,
    validate_edge_payload,
    validate_output_record,
)
from orchestrator.graph.event_registry import (
    EVENT_PAYLOAD_MODELS,
    validate_emitted_event_type,
)
from orchestrator.graph.macros import expand_patch_macros
from orchestrator.graph.models import (
    Actor,
    ActorKind,
    AnalysisSummaryRecord,
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    ArtifactReferenceRecord,
    AuthorityDecisionRecordedPayload,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CandidateRecord,
    CheckResultRecord,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    CleanupRequestedProjection,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    DecisionRecord,
    EdgeProjection,
    EventEnvelope,
    FailureClass,
    FailureRecord,
    FileStateRecord,
    GapClassificationRecord,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdictRow,
    GraphPatchAcceptedPayload,
    JoinResultRecord,
    GraphPatchProposalRecord,
    GraphPatchRejectedPayload,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseProjection,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
    NodeCreatedPayload,
    NodeUsageRecordedPayload,
    OutputRecord,
    OversightDecisionRecordedPayload,
    PatchEnvelope,
    PatchOp,
    PlannerSessionStateChangedPayload,
    RecoveryPlanRecord,
    RequirementRecord,
    RequirementRevisionPayload,
    SupportEvidencePayload,
    VerificationResultProjection,
    VerificationReportRecord,
    normalize_record_selector,
    record_selector_matches,
)
from orchestrator.graph.patch_validator import (
    MODE_RANK,
    resource_claim_dicts,
    validate_patch,
)
from orchestrator.graph.projections import (
    GraphProjection,
    final_invariant_blockers_for_events,
    reduce_event,
)
from orchestrator.graph.scheduler import (
    InputEdgeInfo,
    NodeScheduleInfo,
    ResourceClaim,
    claims_conflict,
    evaluate_readiness,
    schedule,
)
from orchestrator.graph.projection_queries import (
    node_failed_candidates_view,
    node_pending_appeals_view,
    node_preconditions_view,
    accepted_no_successor_patches_by_node_view,
    accepted_output_records_by_node_port_view,
    accepted_record_summaries_by_id_view,
    active_requirement_versions_view,
    check_results_view,
    cleanup_applied_ids_view,
    cleanup_requested_events_view,
    completion_decision_passed,
    edges_view,
    execution_attempts_view,
    failed_verification_candidate_ids_view,
    failed_verification_results_by_record_id_view,
    file_state_records_view,
    input_bindings_view,
    last_deferred_reasons_view,
    latest_routine_snapshot_record,
    cache_authority_binding,
    cache_authority_is_new_format,
    leases_view,
    node_attempts_view,
    node_command_definitions_view,
    node_creation_positions_view,
    node_cache_authority_hash,
    node_gate_decisions_view,
    node_kinds_view,
    non_gap_planner_has_accepted_patch,
    node_resource_claims_view,
    node_roles_view,
    node_states_view,
    node_task_regions_view,
    output_record_payloads_view,
    output_records_by_node_port_view,
    passed_verification_candidate_ids_view,
    passed_verification_results_by_record_id_view,
    planner_generation_budget,
    planner_generations_view,
    planner_sessions_view,
    ready_nodes_view,
    recorded_node_usage_keys_view,
    recovery_nodes_by_record_id_view,
    retry_not_before_by_node_view,
    run_state as query_run_state,
    task_candidates_view,
    task_states_view,
    verifier_verdicts_view,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


RUN_LIFECYCLE_TRANSITIONS: dict[str, dict[str, str]] = {
    "accept_run": {"draft": "queued"},
    "start": {"queued": "active"},
    "pause": {"active": "pausing", "pausing": "paused"},
    # failed -> resuming is the operator reopen edge: it is only legal for a
    # human/operator actor (enforced in _apply_lifecycle_command), so a driver
    # or agent cannot silently un-fail a run. Added after the W2/W4
    # recovery_planner_no_successor false positives (2026-07-04) left runs
    # terminally failed with no kernel-legal recovery path.
    "resume": {"paused": "resuming", "resuming": "active", "failed": "resuming"},
    "cancel": {"active": "cancelling", "paused": "cancelling", "cancelling": "cancelled"},
    "complete": {"active": "completed"},
}
# Actor roles allowed to take the failed -> resuming reopen edge.
REOPEN_ACTOR_ROLES = {"human", "operator"}
TERMINAL_RUN_STATES = {"cancelled", "completed", "failed"}
NONTERMINAL_RUN_STATES = {
    "draft",
    "queued",
    "active",
    "pausing",
    "paused",
    "resuming",
    "cancelling",
}


def _typed_lease_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    model: (
        type[LeaseGrantedPayload]
        | type[LeaseRenewedPayload]
        | type[LeaseReleasedPayload]
        | type[LeaseRevokedPayload]
        | type[LeaseExpiredPayload]
        | None
    )
    if event_type == "lease_granted":
        model = LeaseGrantedPayload
    elif event_type == "lease_renewed":
        model = LeaseRenewedPayload
    elif event_type == "lease_released":
        model = LeaseReleasedPayload
    elif event_type == "lease_revoked":
        model = LeaseRevokedPayload
    elif event_type == "lease_expired":
        model = LeaseExpiredPayload
    else:
        model = None
    if model is None:
        return payload
    return model.model_validate(payload).model_dump(mode="json", exclude_none=True)


_SPARSE_EVENT_PAYLOAD_TYPES = frozenset(
    {
        "file_state_accepted",
        "file_state_rejected",
        "gatekeeper_cost_recorded",
        "gatekeeper_verdict_recorded",
        "input_bound",
        "output_record_accepted",
        "revision_created",
        "verification_failed",
        "verification_passed",
    }
)
_EXCLUDE_NONE_EVENT_PAYLOAD_TYPES = frozenset(
    {
        "agent_died",
        "agent_dispatch_requested",
        "callback_accepted",
        "callback_duplicate_returned",
        "callback_rejected_conflict",
        "callback_rejected_stale",
        "command_rejected",
        "command_recorded",
        "dead_input_detected",
        "heartbeat_recorded",
        "node_authority_changed",
        "node_created",
        "node_deferred",
        "node_ready",
        "node_retired",
        "node_state_changed",
        "plan_region_marked_suspect",
        "run_lifecycle_changed",
        "runner_submission_staged",
        "runtime_retry_scheduled",
    }
)
_CACHE_COMPACT_RUNNER_EVENT_PAYLOAD_TYPES = frozenset(
    {
        "runner_baseline_recorded",
        "runner_submission_staged",
        "runner_boundary_mismatch",
        "runner_recovery_requested",
        "runner_execution_finalized",
    }
)
_REDUNDANT_CACHE_CARRIER_FIELDS = {
    "cache_roots",
    "observed_cache_roots",
    "authorized_cache_roots",
    "legacy_cache_root_paths",
}


def _validate_event_serialization_policy() -> None:
    modeled_event_types = frozenset(EVENT_PAYLOAD_MODELS)
    unknown_policy_types = (
        _SPARSE_EVENT_PAYLOAD_TYPES
        | _EXCLUDE_NONE_EVENT_PAYLOAD_TYPES
        | _CACHE_COMPACT_RUNNER_EVENT_PAYLOAD_TYPES
    ) - modeled_event_types
    if unknown_policy_types:
        mismatch = ", ".join(sorted(unknown_policy_types))
        raise ValueError(f"unknown event payload serialization policy: {mismatch}")


_validate_event_serialization_policy()


def serialize_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    model = EVENT_PAYLOAD_MODELS.get(event_type)
    if model is None:
        return payload
    typed = model.model_validate(payload)
    if event_type in _CACHE_COMPACT_RUNNER_EVENT_PAYLOAD_TYPES:
        return typed.model_dump(
            mode="json",
            exclude=_REDUNDANT_CACHE_CARRIER_FIELDS,
            exclude_none=True,
        )
    if event_type in _SPARSE_EVENT_PAYLOAD_TYPES:
        return typed.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    if event_type in _EXCLUDE_NONE_EVENT_PAYLOAD_TYPES:
        return typed.model_dump(mode="json", exclude_none=True)
    return typed.model_dump(mode="json")


def _apply_lifecycle_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: AcceptRunCommand
    | StartCommand
    | PauseCommand
    | ResumeCommand
    | CancelCommand
    | CompleteCommand
    | FailCommand,
    context: GraphCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    current_state = query_run_state(projection) or "draft"
    if command_type == "fail":
        if current_state in NONTERMINAL_RUN_STATES:
            return [
                _lifecycle_event(
                    make_event,
                    command_type,
                    current_state,
                    "failed",
                    payload.reason
                    if isinstance(payload, FailCommand)
                    else "unrecoverable_controller_error",
                )
            ]
        return [_command_rejected(make_event, command_type, f"terminal run: {current_state}")]

    next_state = RUN_LIFECYCLE_TRANSITIONS[command_type].get(current_state)
    if next_state is None:
        reason = (
            f"terminal run: {current_state}"
            if current_state in TERMINAL_RUN_STATES
            else f"illegal transition from {current_state}"
        )
        return [_command_rejected(make_event, command_type, reason)]
    if command_type == "resume" and current_state == "failed":
        actor_role = context.actor.role if context.actor is not None else None
        if actor_role not in REOPEN_ACTOR_ROLES:
            return [
                _command_rejected(
                    make_event,
                    command_type,
                    "reopen from failed requires an operator: "
                    f"actor_role must be one of {sorted(REOPEN_ACTOR_ROLES)}",
                )
            ]
    if command_type == "complete":
        if any(
            attempt.state == "recovery_requested"
            for attempt in execution_attempts_view(projection).values()
        ):
            return [_command_rejected(make_event, command_type, "runner recovery remains pending")]
        blockers = final_invariant_blockers_for_events(events, projection)
        if blockers:
            return [
                make_event(
                    "command_rejected",
                    {
                        "command_type": command_type,
                        "reason": "final invariant blockers remain",
                        "blockers": blockers,
                    },
                )
            ]
    trigger = (
        payload.trigger
        if not isinstance(payload, FailCommand) and payload.trigger is not None
        else f"{command_type}_command_accepted"
    )
    output: list[EventEnvelope] = []
    if command_type == "complete" and not _has_passed_completion_decision(projection):
        if not isinstance(payload, CompleteCommand):
            raise TypeError("complete command requires CompleteCommand")
        output.append(_lifecycle_completion_decision_event(payload, make_event, id_gen))
    output.append(
        _lifecycle_event(
            make_event,
            command_type,
            current_state,
            next_state,
            trigger,
        )
    )
    if command_type == "cancel":
        output.extend(_cancel_active_lease_events(projection, make_event, trigger))
    return output


def _has_passed_completion_decision(projection: GraphProjection) -> bool:
    return completion_decision_passed(projection)


def _lifecycle_completion_decision_event(
    payload: CompleteCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> EventEnvelope:
    record_id = payload.completion_decision_record_id or id_gen.next_id("completion-decision")
    producer_node_id = payload.node_id or "run_lifecycle"
    record = CompletionDecisionRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "completion_decision",
            "producer_node_id": producer_node_id,
            "port": "completion_decision",
            "schema": "CompletionDecision",
            "value": {"status": "passed", "blockers": []},
            "provenance": {"source": "lifecycle_complete"},
        }
    )
    return make_event(
        "output_record_accepted",
        record.model_dump(mode="json"),
    )


def _apply_record_heartbeat(
    projection: GraphProjection,
    payload: RecordHeartbeatCommand,
    clock: Clock,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    lease_id = payload.lease_id
    lease = leases_view(projection).get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "record_heartbeat", f"unknown lease: {lease_id}")]
    if query_run_state(projection) != "active":
        return [_command_rejected(make_event, "record_heartbeat", "run_not_active")]
    if lease.state != "active":
        return [
            _command_rejected(
                make_event,
                "record_heartbeat",
                f"lease_not_active:{lease.state}",
            )
        ]

    node_id = lease.node_id
    if payload.node_id is not None and payload.node_id != node_id:
        return [_command_rejected(make_event, "record_heartbeat", "node_id_mismatch")]
    if not isinstance(node_id, str):
        return [_command_rejected(make_event, "record_heartbeat", "lease_missing_node_id")]

    expected_generation = payload.generation
    lease_generation = lease.generation
    if (
        expected_generation is not None
        and isinstance(lease_generation, int)
        and expected_generation != lease_generation
    ):
        return [_command_rejected(make_event, "record_heartbeat", "lease_generation_mismatch")]

    ttl_seconds = payload.ttl_seconds
    expires_at = (clock.now() + timedelta(seconds=ttl_seconds)).isoformat()
    heartbeat_payload: dict[str, Any] = {
        "lease_id": lease_id,
        "node_id": node_id,
        "observed_at": clock.now().isoformat(),
        "expires_at": expires_at,
    }
    if isinstance(lease_generation, int) and not isinstance(lease_generation, bool):
        heartbeat_payload["generation"] = lease_generation
    execution_id = lease.execution_id
    if isinstance(execution_id, str):
        heartbeat_payload["execution_id"] = execution_id
    return [
        make_event("heartbeat_recorded", heartbeat_payload),
        make_event("lease_renewed", _typed_lease_event_payload("lease_renewed", heartbeat_payload)),
    ]


def _apply_record_node_usage(
    projection: GraphProjection,
    payload: RecordNodeUsageCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    usage_count = len(payload.usage)
    events: list[EventEnvelope] = []
    for usage_index, usage in enumerate(payload.usage):
        usage_key = f"{payload.execution_id}:{usage_index}"
        if usage_key in recorded_node_usage_keys_view(projection):
            continue
        event_payload = NodeUsageRecordedPayload(
            node_id=payload.node_id,
            node_kind=payload.node_kind,
            node_role=payload.node_role,
            profile=payload.profile,
            execution_id=payload.execution_id,
            usage_index=usage_index,
            usage_count=usage_count,
            usage_key=usage_key,
            num_actions=payload.num_actions if usage_index == 0 else 0,
            **usage.model_dump(mode="json"),
        )
        events.append(make_event("node_usage_recorded", event_payload.model_dump(mode="json")))
    return events


def _cancel_active_lease_events(
    projection: GraphProjection,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    trigger: Any,
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for lease_id, lease in sorted(leases_view(projection).items()):
        if lease.state not in {"active", "suspended"}:
            continue
        node_id = lease.node_id
        if not isinstance(node_id, str):
            continue
        revoke_payload: dict[str, Any] = {
            "node_id": node_id,
            "lease_id": lease_id,
            "trigger": trigger,
            "reason": "run_cancelled",
        }
        generation = lease.generation
        if isinstance(generation, int) and not isinstance(generation, bool):
            revoke_payload["generation"] = generation
        execution_id = lease.execution_id
        if isinstance(execution_id, str):
            revoke_payload["execution_id"] = execution_id
        output.append(
            make_event("lease_revoked", _typed_lease_event_payload("lease_revoked", revoke_payload))
        )

        node_state = node_states_view(projection).get(node_id)
        if node_state not in {"completed", "failed", "cancelled", "retired"}:
            output.append(
                make_event(
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "cancelled",
                        "trigger": "run_cancelled",
                        "reason": "run_cancelled",
                    },
                )
            )
    return output


def _apply_evaluate_final_gate(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: EvaluateFinalGateCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    node_id = payload.node_id
    if node_kinds_view(projection).get(node_id) != "final_gate":
        return [_command_rejected(make_event, "evaluate_final_gate", "node is not a final_gate")]

    blockers = final_invariant_blockers_for_events(
        events,
        projection,
        include_completion_decision=False,
    )
    status = "blocked" if blockers else "passed"
    record_id = payload.record_id or id_gen.next_id("completion-decision")
    decision = {
        "status": status,
        "blockers": blockers,
    }
    output_record = CompletionDecisionRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "completion_decision",
            "producer_node_id": node_id,
            "port": "completion_decision",
            "schema": "CompletionDecision",
            "value": decision,
            "provenance": {"source": "final_gate_evaluated"},
        }
    ).model_dump(mode="json")
    return [
        make_event("output_record_accepted", output_record),
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "completed",
                "trigger": "final_gate_evaluated",
                "completion_status": status,
                "completion_decision_record_id": record_id,
            },
        ),
        *_maybe_release_lease(payload, make_event, node_id),
    ]


def _apply_evaluate_join(
    projection: GraphProjection,
    payload: EvaluateJoinCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    node_id = payload.node_id
    if node_kinds_view(projection).get(node_id) != "join":
        return [_command_rejected(make_event, "evaluate_join", "node is not a join")]

    source_record_ids = _join_source_record_ids(projection, node_id)
    if not source_record_ids:
        return [_command_rejected(make_event, "evaluate_join", "join has no bound source records")]
    record_id = payload.record_id or id_gen.next_id("join-result")
    output_record = JoinResultRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "join_result",
            "producer_node_id": node_id,
            "port": "join_result",
            "schema": "JoinResult",
            "value": {
                "status": "ready",
                "source_record_ids": source_record_ids,
            },
        }
    ).model_dump(mode="json")
    return [
        make_event("output_record_accepted", output_record),
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "completed",
                "trigger": "join_evaluated",
                "join_result_record_id": record_id,
            },
        ),
        *_maybe_release_lease(payload, make_event, node_id),
    ]


def _join_source_record_ids(projection: GraphProjection, node_id: str) -> list[str]:
    bindings = input_bindings_view(projection).get(node_id, {})
    output: list[str] = []
    for _, binding in sorted(bindings.items()):
        for record_id in binding.record_ids:
            if record_id not in output:
                output.append(record_id)
    return output


def _maybe_release_lease(
    payload: EvaluateJoinCommand | EvaluateFinalGateCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    node_id: str,
) -> list[EventEnvelope]:
    lease_id = payload.lease_id
    generation = payload.lease_generation
    if lease_id is None or generation is None:
        return []
    return [
        make_event(
            "lease_released",
            _typed_lease_event_payload(
                "lease_released",
                {
                    "node_id": node_id,
                    "lease_id": lease_id,
                    "generation": generation,
                },
            ),
        )
    ]


def _release_active_node_leases(
    projection: GraphProjection,
    node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for lease_id, lease in sorted(leases_view(projection).items()):
        if lease.node_id != node_id or lease.state not in {"active", "suspended"}:
            continue
        payload: dict[str, Any] = {
            "node_id": node_id,
            "lease_id": lease_id,
        }
        generation = lease.generation
        if isinstance(generation, int) and not isinstance(generation, bool):
            payload["generation"] = generation
        output.append(
            make_event("lease_released", _typed_lease_event_payload("lease_released", payload))
        )
    return output


def _apply_seed_compiled_events(
    projection: GraphProjection,
    payload: SeedCompiledEventsCommand,
    run_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if node_states_view(projection) or edges_view(projection) or input_bindings_view(projection):
        return [
            _command_rejected(make_event, "seed_compiled_events", "run topology already seeded")
        ]

    compiled_events: list[EventEnvelope] = []
    try:
        for event in payload.events:
            if event.run_id != run_id:
                return [
                    _command_rejected(
                        make_event,
                        "seed_compiled_events",
                        f"event run_id mismatch: {event.run_id}",
                    )
                ]
            if event.event_type not in {
                "node_created",
                "edge_created",
                "input_bound",
                "output_record_accepted",
            }:
                return [
                    _command_rejected(
                        make_event,
                        "seed_compiled_events",
                        f"unsupported seed event: {event.event_type}",
                    )
                ]
            if event.event_type == "node_created":
                event = event.model_copy(
                    update={
                        "payload": NodeCreatedPayload.model_validate(event.payload).model_dump(
                            mode="json"
                        )
                    }
                )
            if event.event_type == "edge_created":
                event = event.model_copy(update={"payload": _validated_edge_payload(event.payload)})
            if event.event_type == "output_record_accepted":
                event = event.model_copy(
                    update={"payload": _validated_seed_output_record_payload(event.payload)}
                )
            compiled_events.append(event)
    except (TypeError, ValueError) as exc:
        return [
            _command_rejected(
                make_event,
                "seed_compiled_events",
                safe_exception_reason(
                    exc,
                    code="malformed_seed_event",
                    message="malformed event",
                ),
            )
        ]

    return compiled_events


def _validated_edge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    edge_payload = dict(payload)
    selector = edge_payload.get("accepted_record_selector")
    if isinstance(selector, dict):
        edge_payload["accepted_record_selector"] = normalize_record_selector(selector)
    elif selector is not None:
        msg = "accepted_record_selector must be an object"
        raise ValueError(msg)
    return edge_payload


def _validated_seed_output_record_payload(payload: dict[str, Any]) -> dict[str, Any]:
    record_payload = dict(payload)
    if not _is_verification_report_record_payload(record_payload):
        return record_payload
    if record_payload.get("record_type") != "verification_report":
        msg = "verification records require record_type=verification_report"
        raise ValueError(msg)
    record = VerificationReportRecord.model_validate(record_payload)
    return record.model_dump(mode="json")


def _apply_callback_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: SubmitCallbackCommand,
    run_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    allow_recorded_runner_execution: bool = False,
) -> list[EventEnvelope]:
    callback_payload = _canonical_external_callback_payload(
        _callback_payload(payload),
        payload.node_id,
    )
    # Mutating-ness is derived from the callback's actual effects, never trusted
    # from the caller's flag: completing the node or carrying output records IS
    # a mutation, so a callback claiming is_mutating=False cannot bypass the
    # running-state and suspended-lease guards.
    has_effects = payload.complete_node or bool((callback_payload or {}).get("output_records"))
    request = CallbackRequest(
        run_id=run_id,
        node_id=payload.node_id,
        execution_id=payload.execution_id,
        lease_id=payload.lease_id,
        lease_generation=payload.lease_generation,
        base_snapshot_id=payload.base_snapshot_id,
        observed_graph_position=payload.observed_graph_position,
        idempotency_key=payload.idempotency_key,
        payload=callback_payload,
        is_mutating=payload.is_mutating or has_effects,
    )
    result = validate_callback(request, projection, events)

    payload_hash, payload_size_bytes = callback_payload_identity(request.payload)
    record_ids = _callback_record_ids(request.payload)

    event_payload = {
        "node_id": request.node_id,
        "lease_id": request.lease_id,
        "lease_generation": request.lease_generation,
        "execution_id": request.execution_id,
        "idempotency_key": request.idempotency_key,
        "payload_hash": payload_hash,
        "payload_size_bytes": payload_size_bytes,
        "record_ids": record_ids,
        "reason": result.reason,
    }
    if result.outcome == CallbackOutcome.REJECTED_STALE:
        return [make_event("callback_rejected_stale", event_payload)]
    if (
        payload.execution_id in execution_attempts_view(projection)
        and not allow_recorded_runner_execution
    ):
        return [
            _command_rejected(
                make_event,
                "submit_callback",
                "managed runner execution with baseline requires boundary finalization",
            )
        ]
    if result.outcome in {
        CallbackOutcome.REJECTED_CONFLICT,
        CallbackOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
    }:
        return [make_event("callback_rejected_conflict", event_payload)]
    if result.outcome == CallbackOutcome.DUPLICATE_IDEMPOTENT:
        return [
            make_event(
                "callback_duplicate_returned",
                {**event_payload, "prior_result": result.prior_result},
            )
        ]

    lease_node_id = _lease_node_id(projection, request.lease_id)
    expected_producer_node_id = lease_node_id or request.node_id
    if lease_node_id is not None and request.node_id != lease_node_id:
        return [
            make_event(
                "callback_rejected_conflict",
                {
                    **event_payload,
                    "reason": (
                        "callback node_id does not match lease node: "
                        f"{request.node_id} != {lease_node_id}"
                    ),
                },
            )
        ]
    provenance_conflict = _output_record_provenance_conflict(request, expected_producer_node_id)
    if provenance_conflict is not None:
        return [
            make_event(
                "callback_rejected_conflict",
                {**event_payload, "reason": provenance_conflict},
            )
        ]
    file_state_rejection_conflict = _file_state_rejected_conflict(
        request,
        expected_producer_node_id,
    )
    if file_state_rejection_conflict is not None:
        return [
            make_event(
                "callback_rejected_conflict",
                {**event_payload, "reason": file_state_rejection_conflict},
            )
        ]
    file_state_authority_conflict = _file_state_authority_conflict(
        projection,
        request,
    )
    if file_state_authority_conflict is not None:
        return [
            make_event(
                "callback_rejected_conflict",
                {**event_payload, "reason": file_state_authority_conflict},
            )
        ]
    verification_conflict = _verification_record_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if verification_conflict is not None:
        return [
            make_event(
                "callback_rejected_conflict",
                {**event_payload, "reason": verification_conflict},
            )
        ]
    output_contract_conflict = _output_record_contract_conflict(
        projection,
        request,
        expected_producer_node_id,
    )
    if output_contract_conflict is not None:
        return [
            make_event(
                "callback_rejected_conflict",
                {**event_payload, "reason": output_contract_conflict},
            )
        ]
    missing_output_conflict = _required_output_record_conflict(
        projection,
        request,
        expected_producer_node_id,
        successful_completion=(payload.complete_node and payload.new_state == "completed"),
    )
    if missing_output_conflict is not None:
        return [
            make_event(
                "callback_rejected_conflict",
                {**event_payload, "reason": missing_output_conflict},
            )
        ]

    accepted = make_event("callback_accepted", event_payload)
    output: list[EventEnvelope] = [accepted]
    output.extend(_file_state_rejected_events(request, make_event))
    output.extend(
        _accepted_output_record_events(
            projection,
            request,
            expected_producer_node_id,
            make_event,
        )
    )
    if payload.complete_node:
        output.append(
            make_event(
                "node_state_changed",
                {
                    "node_id": request.node_id,
                    "new_state": payload.new_state,
                    "trigger": "callback_accepted",
                },
            )
        )
        output.append(
            make_event(
                "lease_released",
                _typed_lease_event_payload(
                    "lease_released",
                    {
                        "node_id": request.node_id,
                        "lease_id": request.lease_id,
                        "generation": request.lease_generation,
                    },
                ),
            )
        )
        session_event = _planner_session_state_event(
            projection,
            request.node_id,
            "suspended",
            request.lease_generation,
            make_event,
        )
        if session_event is not None:
            output.append(session_event)
    output.extend(_source_repair_events(projection, events, output, make_event))
    return output


def _lease_node_id(projection: GraphProjection, lease_id: str) -> str | None:
    lease = leases_view(projection).get(lease_id)
    if lease is None:
        return None
    node_id = lease.node_id
    return node_id if isinstance(node_id, str) else None


def _callback_record_ids(payload: dict[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    output = payload.get("output_records")
    if not isinstance(output, list):
        return []
    record_ids: list[str] = []
    for raw_item in cast(list[Any], output):
        if not isinstance(raw_item, dict):
            continue
        record_id = cast(dict[str, Any], raw_item).get("record_id")
        if isinstance(record_id, str):
            record_ids.append(record_id)
    return record_ids


def _output_record_provenance_conflict(
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None

    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        producer_node_id = record_payload.get("producer_node_id", expected_producer_node_id)
        if producer_node_id != expected_producer_node_id:
            return (
                "output record producer_node_id does not match lease node "
                f"at index {index}: {producer_node_id} != {expected_producer_node_id}"
            )
        if record_payload.get("record_kind") == "file_state":
            node_id = record_payload.get("node_id", expected_producer_node_id)
            if node_id != expected_producer_node_id:
                return (
                    "file_state record node_id does not match lease node "
                    f"at index {index}: {node_id} != {expected_producer_node_id}"
                )
    return None


def _file_state_rejected_conflict(
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    rejection = request.payload.get("file_state_rejected") if request.payload is not None else None
    if not isinstance(rejection, dict):
        return None
    rejection_payload = cast(dict[str, Any], rejection)
    node_id = rejection_payload.get("node_id", expected_producer_node_id)
    if node_id != expected_producer_node_id:
        return (
            "file_state_rejected node_id does not match lease node: "
            f"{node_id} != {expected_producer_node_id}"
        )
    producer_node_id = rejection_payload.get("producer_node_id", expected_producer_node_id)
    if producer_node_id != expected_producer_node_id:
        return (
            "file_state_rejected producer_node_id does not match lease node: "
            f"{producer_node_id} != {expected_producer_node_id}"
        )
    return None


def _file_state_authority_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None
    lease = leases_view(projection).get(request.lease_id)
    if lease is None:
        return None
    node_id = _lease_node_id(projection, request.lease_id) or request.node_id
    if node_kinds_view(projection).get(node_id) != "worker":
        return None
    raw_claims = lease.resource_claims
    write_claims: list[ResourceClaim] = []
    for raw_claim in raw_claims:
        write_claims.append(_claim_from_dict(raw_claim))
    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        if record_payload.get("record_kind") != "file_state":
            continue
        changed_paths = _file_state_changed_paths(record_payload)
        unauthorized = [
            path for path in changed_paths if not _repo_write_claim_covers_path(write_claims, path)
        ]
        if unauthorized:
            return (
                f"file_state path outside lease write authority at index {index}: {unauthorized[0]}"
            )
    return None


def _file_state_changed_paths(record_payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for field in (
        "paths",
        "tracked",
        "untracked",
        "ignored",
        "external",
        "classifications",
        "residue",
        "rejected_paths",
    ):
        raw_entries = record_payload.get(field)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            if entry.get("classification") == "tool_cache":
                continue
            path = entry.get("path")
            if isinstance(path, str) and path not in paths:
                paths.append(path)
    return paths


def _repo_write_claim_covers_path(write_claims: list[ResourceClaim], path: str) -> bool:
    if not _file_state_path_is_repo_relative(path):
        return False
    requested = ResourceClaim(mode="read", scope="repo", paths=[path])
    return any(
        _claim_is_repo_write(claim) and claims_conflict(requested, claim) for claim in write_claims
    )


def _claim_is_repo_write(claim: ResourceClaim) -> bool:
    return claim.mode == "write" and claim.scope == "repo" and _claim_paths_are_repo_relative(claim)


def _claim_paths_are_repo_relative(claim: ResourceClaim) -> bool:
    return all(_file_state_path_is_repo_relative(path) for path in claim.paths)


def _file_state_path_is_repo_relative(path: str) -> bool:
    if path == "":
        return False
    if path.startswith("/"):
        return False
    normalized = posixpath.normpath(path)
    return normalized != ".." and not normalized.startswith("../")


def _file_state_rejected_events(
    request: CallbackRequest,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    rejection = request.payload.get("file_state_rejected") if request.payload is not None else None
    if not isinstance(rejection, dict):
        return []
    payload = dict(cast(dict[str, Any], rejection))
    payload.setdefault("record_id", f"file-state-rejected-{request.node_id}-{request.execution_id}")
    payload["record_kind"] = "file_state"
    payload["record_type"] = "file_state"
    payload.setdefault("producer_node_id", request.node_id)
    payload["port"] = "file_state"
    payload["schema"] = "FileStateRecord"
    payload.setdefault("base_snapshot_id", request.base_snapshot_id)
    payload.setdefault("paths", [])
    for key in ("node_id", "execution_id", "lease_id", "lease_generation"):
        payload.pop(key, None)
    return [make_event("file_state_rejected", payload)]


def _output_record_contract_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None

    typed_raw_records = cast(list[Any], raw_records)
    file_state_records = _same_callback_file_state_records(
        typed_raw_records,
        expected_producer_node_id,
    )
    node_kind = node_kinds_view(projection).get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = node_roles_view(projection).get(expected_producer_node_id)
    typed_role = node_role if isinstance(node_role, str) else None
    for index, raw_record in enumerate(typed_raw_records):
        if not isinstance(raw_record, dict):
            return f"malformed output record at index {index}"
        record_payload = dict(cast(dict[str, Any], raw_record))
        if record_payload.get("record_kind") == "file_state":
            record_payload.setdefault("port", "file_state")
            record_payload.setdefault("record_type", "file_state")
        if record_payload.get("record_kind") == "verification":
            record_payload.setdefault("port", "verification_report")
        record_run_id = record_payload.get("run_id")
        if record_run_id is not None and record_run_id != request.run_id:
            return f"output record at index {index} run_id does not match callback run: {record_run_id}"
        if _is_candidate_record_payload(record_payload):
            record_payload = _candidate_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            expected_file_state_ids = _file_state_record_ids_for_candidate(
                record_payload,
                file_state_records,
            )
            citation_conflict = _candidate_file_state_citation_conflict(
                record_payload,
                expected_file_state_ids,
                index,
            )
            if citation_conflict is not None:
                return citation_conflict
        if _is_check_result_record_payload(record_payload):
            record_payload = _check_result_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            citation_conflict = _evaluated_record_citation_conflict(
                projection,
                expected_producer_node_id,
                record_payload,
                index,
            )
            if citation_conflict is not None:
                return citation_conflict
        error = validate_output_record(
            node_kind=node_kind,
            node_role=typed_role,
            record_payload=record_payload,
            index=index,
        )
        if error is not None:
            return error
        if _is_candidate_record_payload(record_payload):
            try:
                CandidateRecord.model_validate(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_candidate_record",
                    message=f"candidate record at index {index} is invalid",
                )
        if _is_check_result_record_payload(record_payload):
            try:
                CheckResultRecord.model_validate(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_check_result_record",
                    message=f"check_result record at index {index} is invalid",
                )
        if _is_verification_report_record_payload(record_payload):
            try:
                _parse_verification_report_record(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_verification_record",
                    message=f"verification record at index {index} is invalid",
                )
        if _is_gap_classification_record_payload(record_payload):
            record_payload = _gap_classification_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                GapClassificationRecord.model_validate(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_gap_classification_record",
                    message=f"gap classification record at index {index} is invalid",
                )
        if _is_analysis_summary_record_payload(record_payload):
            record_payload = _analysis_summary_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                AnalysisSummaryRecord.model_validate(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_analysis_summary_record",
                    message=f"analysis_summary record at index {index} is invalid",
                )
        if _is_graph_patch_proposal_record_payload(record_payload):
            record_payload = _graph_patch_proposal_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                GraphPatchProposalRecord.model_validate(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_graph_patch_proposal_record",
                    message=f"graph_patch_proposal record at index {index} is invalid",
                )
        if _is_artifact_reference_record_payload(record_payload):
            record_payload = _artifact_reference_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                ArtifactReferenceRecord.model_validate(record_payload)
            except ValueError as exc:
                return safe_exception_reason(
                    exc,
                    code="invalid_artifact_reference_record",
                    message=f"artifact_reference record at index {index} is invalid",
                )
    return None


def _accepted_output_record_events(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return []

    typed_raw_records = cast(list[Any], raw_records)
    file_state_records = _same_callback_file_state_records(
        typed_raw_records,
        expected_producer_node_id,
    )
    # File-state records are prerequisites for candidate/output records that
    # cite them.  Publish those accepted records first only when this callback
    # actually creates such a relationship; preserve ordinary callback order.
    cites_same_callback_file_state = any(
        isinstance(raw_record, dict)
        and _is_candidate_record_payload(cast(dict[str, Any], raw_record))
        and bool(
            _file_state_record_ids_for_candidate(
                cast(dict[str, Any], raw_record), file_state_records
            )
        )
        for raw_record in typed_raw_records
    )
    if cites_same_callback_file_state:
        ordered_raw_records: list[Any] = [
            *[
                raw_record
                for raw_record in typed_raw_records
                if isinstance(raw_record, dict)
                and cast(dict[str, Any], raw_record).get("record_kind") == "file_state"
            ],
            *[
                raw_record
                for raw_record in typed_raw_records
                if not (
                    isinstance(raw_record, dict)
                    and cast(dict[str, Any], raw_record).get("record_kind") == "file_state"
                )
            ],
        ]
    else:
        ordered_raw_records = typed_raw_records
    output: list[EventEnvelope] = []
    for raw_record in ordered_raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        record_payload.setdefault("producer_node_id", expected_producer_node_id)
        if record_payload.get("record_kind") == "file_state":
            record_payload.setdefault("port", "file_state")
            record_payload.setdefault("record_type", "file_state")
        if _is_verification_report_record_payload(record_payload):
            output.extend(
                _accepted_verification_record_events(
                    projection,
                    request,
                    expected_producer_node_id,
                    record_payload,
                    make_event,
                )
            )
            continue
        if record_payload.get("record_kind") == "file_state":
            output.extend(
                _accepted_file_state_record_events(
                    projection,
                    expected_producer_node_id,
                    record_payload,
                    make_event,
                )
            )
            continue
        if _is_check_result_record_payload(record_payload):
            _add_evaluated_record_citations(record_payload, projection, expected_producer_node_id)
            record_payload = _check_result_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = CheckResultRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(make_event("output_record_accepted", payload))
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_candidate_record_payload(record_payload):
            _add_candidate_file_state_citations(
                record_payload,
                _file_state_record_ids_for_candidate(record_payload, file_state_records),
            )
            record_payload = _candidate_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = CandidateRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(make_event("output_record_accepted", payload))
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_gap_classification_record_payload(record_payload):
            record_payload = _gap_classification_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = GapClassificationRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(make_event("output_record_accepted", payload))
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_analysis_summary_record_payload(record_payload):
            record_payload = _analysis_summary_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = AnalysisSummaryRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(make_event("output_record_accepted", payload))
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_graph_patch_proposal_record_payload(record_payload):
            record_payload = _graph_patch_proposal_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = GraphPatchProposalRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(make_event("output_record_accepted", payload))
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        if _is_artifact_reference_record_payload(record_payload):
            record_payload = _artifact_reference_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                record = ArtifactReferenceRecord.model_validate(record_payload)
            except ValueError:
                continue
            payload = record.model_dump(mode="json")
            output.append(make_event("output_record_accepted", payload))
            output.extend(
                _input_bound_events_for_record(
                    projection,
                    record.producer_node_id,
                    record.port,
                    record.record_id,
                    payload,
                    make_event,
                )
            )
            continue
        try:
            record = OutputRecord.model_validate(record_payload)
        except ValueError:
            continue
        output.append(make_event("output_record_accepted", record.model_dump(mode="json")))
        output.extend(
            _input_bound_events_for_record(
                projection,
                record.producer_node_id,
                record.port,
                record.record_id,
                record.model_dump(mode="json"),
                make_event,
            )
        )
    return output


def _accepted_file_state_record_events(
    projection: GraphProjection,
    expected_producer_node_id: str,
    record_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    record_payload.setdefault("producer_node_id", expected_producer_node_id)
    record_payload.setdefault("paths", [])
    try:
        record = FileStateRecord.model_validate(record_payload)
    except ValueError:
        return []
    payload = record.model_dump(mode="json")
    # ``file_state_accepted`` is the sole durable owner. Historical streams
    # containing the old full/full pair remain replayable and deduplicate by
    # record identity in the projection.
    output = [make_event("file_state_accepted", payload)]
    output.extend(
        _input_bound_events_for_record(
            projection,
            record.producer_node_id or expected_producer_node_id,
            record.port,
            record.record_id,
            payload,
            make_event,
        )
    )
    return output


def _verification_record_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
) -> str | None:
    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        return None

    for index, raw_record in enumerate(cast(list[Any], raw_records)):
        if not isinstance(raw_record, dict):
            continue
        record_payload = cast(dict[str, Any], raw_record)
        if not _is_verification_report_record_payload(record_payload):
            continue
        try:
            record = _parse_verification_report_record(record_payload)
        except ValueError as exc:
            return safe_exception_reason(
                exc,
                code="invalid_verification_record",
                message=f"verification record at index {index} is invalid",
            )
        if node_kinds_view(projection).get(expected_producer_node_id) != "verifier":
            return f"verification record at index {index} was not produced by a verifier"
        candidate_id = record.candidate_id
        if not _candidate_is_bound_to_verifier(projection, expected_producer_node_id, candidate_id):
            return (
                f"verification record candidate_id at index {index} is not bound "
                f"to verifier input: {candidate_id}"
            )
        represented_requirement_ids = set(active_requirement_versions_view(projection))
        represented_requirement_ids.update(
            item.value.id
            for item in output_record_payloads_view(projection).values()
            if isinstance(item, RequirementRecord) and item.value.source == "routine"
        )
        # An empty rubric has no grades to report. Treat an empty list as the
        # complete evaluation of that rubric; once requirements exist, a
        # verifier must still provide grades and the coverage checks below
        # remain authoritative.
        if not record.value.grades and represented_requirement_ids:
            return f"verification record at index {index} missing grades"
        for grade in record.value.grades:
            if grade.requirement_id not in represented_requirement_ids:
                return (
                    f"verification record at index {index} grades unrepresented requirement: "
                    f"{grade.requirement_id}"
                )
        record_payload = record.model_dump(mode="json")
        citation_conflict = _evaluated_record_citation_conflict(
            projection,
            expected_producer_node_id,
            record_payload,
            index,
        )
        if citation_conflict is not None:
            return citation_conflict
    return None


def _required_output_record_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    *,
    successful_completion: bool,
) -> str | None:
    if not successful_completion:
        return None

    node_kind = node_kinds_view(projection).get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = node_roles_view(projection).get(expected_producer_node_id)
    typed_role = node_role if isinstance(node_role, str) else None
    contract = DEFAULT_NODE_CONTRACTS.contract_for(node_kind, typed_role)
    if contract is None:
        return f"output records produced by unknown node type: {node_kind}"

    required_ports = {port.name for port in contract.output_ports.values() if port.required}
    if not required_ports:
        return None

    raw_records = request.payload.get("output_records") if request.payload is not None else None
    if not isinstance(raw_records, list):
        raw_records = []
    produced_ports = {
        canonical_port
        for raw_record in cast(list[Any], raw_records)
        if isinstance(raw_record, dict)
        for canonical_port in [
            _output_record_contract_port(contract, cast(dict[str, Any], raw_record))
        ]
        if canonical_port is not None
    }
    missing = sorted(required_ports - produced_ports)
    if missing:
        return f"node completion missing required output record ports: {', '.join(missing)}"
    return None


def _output_record_contract_port(
    contract: Any,
    record_payload: dict[str, Any],
) -> str | None:
    record_payload = dict(record_payload)
    if record_payload.get("record_kind") == "file_state":
        record_payload.setdefault("port", "file_state")
    if record_payload.get("record_kind") == "verification":
        record_payload.setdefault("port", "verification_report")
    port = record_payload.get("port")
    if not isinstance(port, str):
        return None
    if output_port_contract(contract, port) is None:
        return None
    return port


def _accepted_verification_record_events(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    record_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    candidate_id = _candidate_id_from_payload(record_payload)
    if candidate_id is None:
        return []
    if not _candidate_is_bound_to_verifier(projection, expected_producer_node_id, candidate_id):
        return []

    _add_evaluated_record_citations(record_payload, projection, expected_producer_node_id)
    try:
        record = _parse_verification_report_record(record_payload)
    except ValueError:
        return []
    payload = record.model_dump(mode="json")
    outcome = record.outcome
    event_type = "verification_passed" if outcome == "passed" else "verification_failed"
    task_region_id = node_task_regions_view(projection).get(expected_producer_node_id)
    evidence = payload.get("evidence")
    evidence_rows: list[dict[str, Any]] = []
    if isinstance(evidence, dict):
        evidence_rows.append(dict(cast(dict[str, Any], evidence)))
    event_payload: dict[str, Any] = {
        "node_id": request.node_id,
        "verifier_node_id": expected_producer_node_id,
        "candidate_id": candidate_id,
        "outcome": outcome,
        "record_id": record.record_id,
        "evidence": evidence_rows,
        "value": payload.get("value"),
    }
    if task_region_id is not None:
        event_payload["task_region_id"] = task_region_id
    output = [
        make_event("output_record_accepted", payload),
        make_event(event_type, event_payload),
    ]
    output.extend(
        _input_bound_events_for_record(
            projection,
            record.producer_node_id,
            record.port,
            record.record_id,
            payload,
            make_event,
        )
    )
    return output


def _candidate_is_bound_to_verifier(
    projection: GraphProjection,
    verifier_node_id: str,
    candidate_id: str,
) -> bool:
    binding = input_bindings_view(projection).get(verifier_node_id, {}).get("candidate_under_test")
    if binding is None:
        return False
    return candidate_id in binding.record_ids


def _candidate_id_from_payload(payload: dict[str, Any] | FileStateRecord) -> str | None:
    if isinstance(payload, FileStateRecord):
        return payload.candidate_id
    candidate_id = payload.get("candidate_id")
    if isinstance(candidate_id, str):
        return candidate_id
    membership = payload.get("membership")
    if isinstance(membership, dict):
        value = cast(dict[str, Any], membership).get("candidate_id")
        if isinstance(value, str):
            return value
    return None


def _is_check_result_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "check_result"
        or payload.get("port") == "check_result"
        or payload.get("record_kind") == "check_result"
    )


def _is_verification_report_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_kind") == "verification"
        or payload.get("record_type") == "verification_report"
        or payload.get("port") in {"verification_report", "verification_result"}
        or payload.get("schema") == "VerificationReport"
    )


def _verification_report_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output["record_kind"] = "verification"
    output["record_type"] = "verification_report"
    output["port"] = "verification_report"
    output["schema"] = "VerificationReport"
    raw_value = output.get("value")
    value = dict(cast(dict[str, Any], raw_value)) if isinstance(raw_value, dict) else {}
    raw_outcome = (
        output.get("outcome")
        or output.get("verdict")
        or value.get("outcome")
        or value.get("verdict")
    )
    if raw_outcome in {"passed", "pass"}:
        output["outcome"] = "passed"
        value["outcome"] = "passed"
    elif raw_outcome in {"failed", "fail"}:
        output["outcome"] = "failed"
        value["outcome"] = "failed"
    for key in ("grades", "reason"):
        if key in output:
            value.setdefault(key, output.pop(key))
    output.pop("verdict", None)
    value.pop("verdict", None)
    output["value"] = value
    return output


def _parse_verification_report_record(payload: dict[str, Any]) -> VerificationReportRecord:
    return VerificationReportRecord.model_validate(payload)


def _check_result_status_value(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    if isinstance(status, str):
        return status
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status
    return "unknown"


def _check_result_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "check_result")
    return output


def _is_candidate_record_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") == "candidate" or payload.get("port") == "candidate"


def _candidate_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "candidate")
    record_id = output.get("record_id")
    if isinstance(record_id, str) and record_id:
        output.setdefault("candidate_id", record_id)
    return output


GAP_CLASSIFICATION_PORTS = frozenset({"gap_plan", "gap_classification", "classified_gap"})


def _is_gap_classification_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") in GAP_CLASSIFICATION_PORTS
        or payload.get("port") in GAP_CLASSIFICATION_PORTS
    )


def _gap_classification_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    port = output.get("port")
    if isinstance(port, str):
        output.setdefault("record_type", port)
    return output


ANALYSIS_SUMMARY_PORTS = frozenset({"analysis_summary", "planning_summary", "region_summary"})


def _is_analysis_summary_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "analysis_summary"
        or payload.get("port") in ANALYSIS_SUMMARY_PORTS
    )


def _analysis_summary_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "analysis_summary")
    return output


GRAPH_PATCH_PROPOSAL_PORTS = frozenset({"graph_patch_proposal", "graph_patch"})


def _is_graph_patch_proposal_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "graph_patch_proposal"
        or payload.get("port") in GRAPH_PATCH_PROPOSAL_PORTS
    )


def _graph_patch_proposal_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_type", "graph_patch_proposal")
    return output


def _is_artifact_reference_record_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") == "artifact_reference" or payload.get("port") in {
        "artifact_reference",
        "artifact",
    }


def _artifact_reference_record_payload_for_validation(
    payload: dict[str, Any],
    expected_producer_node_id: str,
) -> dict[str, Any]:
    output = dict(payload)
    output.setdefault("producer_node_id", expected_producer_node_id)
    output.setdefault("record_kind", "graph_record")
    output.setdefault("record_type", "artifact_reference")
    output.setdefault("schema", "ArtifactReference")
    output.setdefault("port", "artifact_reference")
    return output


def _same_callback_file_state_records(
    raw_records: list[Any],
    expected_producer_node_id: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        if (
            record_payload.get("record_kind") != "file_state"
            and record_payload.get("port") != "file_state"
        ):
            continue
        producer_node_id = record_payload.get("producer_node_id", expected_producer_node_id)
        if producer_node_id != expected_producer_node_id:
            continue
        record_id = record_payload.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        output.append(record_payload)
    return output


def _file_state_record_ids_for_candidate(
    candidate_payload: dict[str, Any],
    file_state_records: list[dict[str, Any]],
) -> list[str]:
    candidate_id = _candidate_id_from_payload(candidate_payload)
    output: list[str] = []
    for record in file_state_records:
        record_candidate_id = _candidate_id_from_payload(record)
        if (
            candidate_id is not None
            and record_candidate_id is not None
            and record_candidate_id != candidate_id
        ):
            continue
        record_id = record.get("record_id")
        if isinstance(record_id, str):
            output.append(record_id)
    return _unique_record_ids(output)


def _candidate_file_state_citation_conflict(
    record_payload: dict[str, Any],
    expected_file_state_ids: list[str],
    index: int,
) -> str | None:
    if not expected_file_state_ids:
        return None
    conflict = _explicit_record_ids_conflict(
        record_payload,
        "file_state_record_ids",
        expected_file_state_ids,
    )
    if conflict is not None:
        return f"output record at index {index} {conflict}"
    file_state_record_id = record_payload.get("file_state_record_id")
    if file_state_record_id is not None:
        if (
            not isinstance(file_state_record_id, str)
            or [file_state_record_id] != expected_file_state_ids
        ):
            return (
                "output record at index "
                f"{index} file_state_record_id does not match same-callback file-state records: "
                f"{file_state_record_id}"
            )
    return None


def _add_candidate_file_state_citations(
    record_payload: dict[str, Any],
    file_state_record_ids: list[str],
) -> None:
    if not file_state_record_ids:
        return
    citations = {"file_state_record_ids": file_state_record_ids}
    record_payload.setdefault("file_state_record_ids", list(file_state_record_ids))
    if len(file_state_record_ids) == 1:
        record_payload.setdefault("file_state_record_id", file_state_record_ids[0])
    _merge_record_citations(record_payload, "value", citations)
    _merge_record_citations(record_payload, "provenance", citations)


def _evaluated_record_citation_conflict(
    projection: GraphProjection,
    node_id: str,
    record_payload: dict[str, Any],
    index: int,
) -> str | None:
    citations = _evaluated_record_citations(projection, node_id)
    for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
        expected = citations.get(field)
        if expected is None:
            continue
        conflict = _explicit_record_ids_conflict(record_payload, field, expected)
        if conflict is not None:
            return f"output record at index {index} {conflict}"
    candidate_record_id = record_payload.get("candidate_record_id")
    expected_candidates = citations.get("candidate_record_ids")
    if candidate_record_id is not None and expected_candidates is not None:
        if not isinstance(candidate_record_id, str) or [candidate_record_id] != expected_candidates:
            return (
                "output record at index "
                f"{index} candidate_record_id does not match bound candidate records: "
                f"{candidate_record_id}"
            )
    return None


def _explicit_record_ids_conflict(
    record_payload: dict[str, Any],
    field: str,
    expected: list[str],
) -> str | None:
    candidates: list[tuple[str, Any]] = [(field, record_payload.get(field))]
    value = record_payload.get("value")
    if isinstance(value, dict):
        candidates.append((f"value.{field}", cast(dict[str, Any], value).get(field)))
    evidence = record_payload.get("evidence")
    if isinstance(evidence, dict):
        candidates.append((f"evidence.{field}", cast(dict[str, Any], evidence).get(field)))
    provenance = record_payload.get("provenance")
    if isinstance(provenance, dict):
        candidates.append((f"provenance.{field}", cast(dict[str, Any], provenance).get(field)))

    for path, value in candidates:
        if value is None:
            continue
        if not isinstance(value, list):
            return f"{path} must be a list of record IDs"
        record_ids = [
            record_id for record_id in cast(list[Any], value) if isinstance(record_id, str)
        ]
        if record_ids != expected:
            return f"{path} does not match bound records: {record_ids} != {expected}"
    return None


def _add_evaluated_record_citations(
    record_payload: dict[str, Any],
    projection: GraphProjection,
    node_id: str,
) -> None:
    citations = _evaluated_record_citations(projection, node_id)
    if not citations:
        return
    for key, value in citations.items():
        record_payload.setdefault(key, list(value))
    candidate_ids = citations.get("candidate_record_ids")
    if candidate_ids is not None and len(candidate_ids) == 1:
        record_payload.setdefault("candidate_record_id", candidate_ids[0])
    _merge_record_citations(record_payload, "provenance", citations)
    if _is_verification_report_record_payload(record_payload):
        _merge_record_citations(record_payload, "evidence", citations)
    if _is_check_result_record_payload(record_payload):
        _merge_record_citations(record_payload, "value", citations)


def _merge_record_citations(
    record_payload: dict[str, Any],
    field: str,
    citations: dict[str, list[str]],
) -> None:
    existing = record_payload.get(field)
    if existing is None:
        record_payload[field] = {key: list(value) for key, value in citations.items()}
        return
    if not isinstance(existing, dict):
        return
    merged = dict(cast(dict[str, Any], existing))
    for key, value in citations.items():
        merged.setdefault(key, list(value))
    record_payload[field] = merged


def _evaluated_record_citations(
    projection: GraphProjection,
    node_id: str,
) -> dict[str, list[str]]:
    candidate_record_ids = _bound_record_ids_for_ports(
        projection,
        node_id,
        ("candidate_under_test", "candidate"),
    )
    file_state_record_ids = _bound_record_ids_for_ports(
        projection,
        node_id,
        ("file_state", "accepted_file_state"),
    )
    if candidate_record_ids:
        file_state_record_ids.extend(
            _file_state_record_ids_for_candidate_records(projection, candidate_record_ids)
        )
    output: dict[str, list[str]] = {}
    unique_candidate_record_ids = _unique_record_ids(candidate_record_ids)
    unique_file_state_record_ids = _unique_record_ids(file_state_record_ids)
    if unique_candidate_record_ids:
        output["candidate_record_ids"] = unique_candidate_record_ids
    if unique_file_state_record_ids:
        output["file_state_record_ids"] = unique_file_state_record_ids
    evaluated_record_ids = _unique_record_ids(
        [*unique_candidate_record_ids, *unique_file_state_record_ids]
    )
    if evaluated_record_ids:
        output["evaluated_record_ids"] = evaluated_record_ids
    return output


def _file_state_record_ids_for_candidate_records(
    projection: GraphProjection,
    candidate_record_ids: list[str],
) -> list[str]:
    wanted = set(candidate_record_ids)
    output: list[str] = []
    for candidates in task_candidates_view(projection).values():
        for candidate in candidates:
            candidate_id = candidate.candidate_id
            if candidate_id not in wanted:
                continue
            output.extend(candidate.file_state_record_ids)
    if output:
        return _unique_record_ids(output)
    for record in file_state_records_view(projection).values():
        candidate_id = _candidate_id_from_payload(record)
        if candidate_id in wanted:
            output.append(record.record_id)
    return _unique_record_ids(output)


def _bound_record_ids_for_ports(
    projection: GraphProjection,
    node_id: str,
    ports: tuple[str, ...],
) -> list[str]:
    bindings = input_bindings_view(projection).get(node_id, {})
    output: list[str] = []
    for port in ports:
        binding = bindings.get(port)
        if binding is None:
            continue
        output.extend(binding.record_ids)
    return _unique_record_ids(output)


def _unique_record_ids(record_ids: list[str]) -> list[str]:
    output: list[str] = []
    for record_id in record_ids:
        if record_id not in output:
            output.append(record_id)
    return output


def _input_bound_events_for_record(
    projection: GraphProjection,
    producer_node_id: str,
    port: str,
    record_id: str,
    record_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    # Output records are facts produced by the leased node. Edges are the only
    # authority for routing those facts into downstream required inputs.
    for edge in edges_view(projection).values():
        if edge.dependency_type != "input_binding":
            continue
        if not _projection_edge_accepts_producer(projection, edge, producer_node_id):
            continue
        if edge.from_port != port:
            continue
        if not record_selector_matches(edge.accepted_record_selector, record_payload):
            continue
        edge_id = edge.edge_id
        to_node_id = edge.to_node_id
        to_port = edge.to_port
        existing_ids = _existing_bound_record_ids(projection, to_node_id, to_port)
        target_port = _target_port_contract_for_edge(projection, edge)
        policy = binding_policy(edge.binding_policy, target_port)
        next_ids = merge_bound_record_ids(
            policy,
            existing_ids,
            [record_id],
            supersedes_record_id=record_payload.get("supersedes_record_id"),
        )
        if next_ids == existing_ids and existing_ids:
            continue
        binding_payload: dict[str, Any] = {
            "edge_id": edge_id,
            "to_node_id": to_node_id,
            "to_port": to_port,
            "record_ids": next_ids,
            "bound_at_position": 0,
        }
        if policy != "bind_first" or isinstance(edge.binding_policy, str):
            binding_payload["binding_policy"] = policy
        supersedes_record_id = record_payload.get("supersedes_record_id")
        if isinstance(supersedes_record_id, str):
            binding_payload["supersedes_record_id"] = supersedes_record_id
        output.append(
            make_event(
                "input_bound",
                binding_payload,
            )
        )
    return output


def _existing_bound_record_ids(
    projection: GraphProjection,
    to_node_id: str,
    to_port: str,
) -> list[str]:
    binding = input_bindings_view(projection).get(to_node_id, {}).get(to_port)
    if binding is None:
        return []
    return list(binding.record_ids)


def _target_port_contract_for_edge(
    projection: GraphProjection,
    edge: EdgeProjection,
) -> PortContract | None:
    to_node_id = edge.to_node_id
    to_port = edge.to_port
    target_kind = node_kinds_view(projection).get(to_node_id)
    if target_kind is None:
        return None
    target_role = node_roles_view(projection).get(to_node_id)
    target_contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if target_contract is None:
        return None
    return input_port_contract(target_contract, to_port)


def _apply_patch_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: SubmitPatchCommand,
    context: PatchCommandContext,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    actor_role = context.actor_role
    run_state = query_run_state(projection)
    if run_state is not None and run_state != "active":
        return [
            _command_rejected(
                make_event,
                "submit_patch",
                f"run_not_active:{run_state or 'unknown'}",
            )
        ]
    try:
        ops = expand_patch_macros(
            payload.ops,
            payload.macro_invocations,
            context.proposed_by_node_id,
        )
        patch = PatchEnvelope.model_validate(
            {
                "patch_id": payload.patch_id,
                "proposed_by_node_id": context.proposed_by_node_id,
                "base_graph_position": payload.base_graph_position,
                # Validate the complete list at once.  Besides avoiding a
                # first-invalid-operation-only failure, this preserves Pydantic's
                # precise ``ops[index].field`` locations for tool feedback.
                "ops": ops,
                "rationale_record_id": payload.rationale_record_id,
            }
        )
    except (TypeError, ValueError) as exc:
        rejected_payload: dict[str, Any] = {
            "command_type": "submit_patch",
            "reason": safe_exception_reason(
                exc,
                code="malformed_patch",
                message="malformed patch",
            ),
            "patch_id": payload.patch_id,
            "actor_role": actor_role,
            "proposed_by_node_id": context.proposed_by_node_id,
            "base_graph_position": payload.base_graph_position,
        }
        if isinstance(exc, ValidationError):
            rejected_payload["diagnostics"] = safe_validation_diagnostics(exc)
        return [
            make_event(
                "command_rejected",
                rejected_payload,
            )
        ]

    current_position = context.current_graph_position
    events_since_base = [event for event in events if event.position > patch.base_graph_position]
    result = validate_patch(patch, current_position, events_since_base, projection, actor_role)
    if not result.accepted:
        return [
            make_event(
                "graph_patch_rejected",
                _patch_rejected_payload(
                    patch,
                    actor_role,
                    reason=result.rejection_reason,
                    read_set_diff=result.read_set_diff,
                ),
            )
        ]

    successor_planner_node_ids = _successor_planner_node_ids(patch)
    if actor_role == "planner" and len(successor_planner_node_ids) > 1:
        return [
            make_event(
                "graph_patch_rejected",
                _patch_rejected_payload(
                    patch,
                    actor_role,
                    reason="multiple_successor_planners_not_allowed",
                    read_set_diff=None,
                ),
            )
        ]
    if actor_role == "planner" and successor_planner_node_ids:
        budget_rejection = _planner_budget_rejection(projection, patch)
        if budget_rejection is not None:
            gate_node_id = payload.budget_gate_node_id or (
                f"gate-planner-budget-{patch.proposed_by_node_id}"
            )
            return [
                make_event(
                    "graph_patch_rejected",
                    {
                        **_patch_rejected_payload(
                            patch,
                            actor_role,
                            reason="planner_generation_budget_exhausted",
                            read_set_diff=None,
                        ),
                        "budget": budget_rejection["budget"],
                        "count": budget_rejection["count"],
                    },
                ),
                _node_created_event(
                    projection,
                    make_event,
                    {
                        "node_id": gate_node_id,
                        "kind": "gate",
                        "state": "planned",
                        "role": "planner_generation_budget_gate",
                        "guarded_planner_node_id": patch.proposed_by_node_id,
                        "rejected_patch_id": patch.patch_id,
                        "reason": "planner_generation_budget_exhausted",
                    },
                ),
                make_event(
                    "node_state_changed",
                    {
                        "node_id": gate_node_id,
                        "new_state": "ready",
                        "trigger": "planner_generation_budget_exhausted",
                    },
                ),
            ]

    request_record_error = _request_record_validation_error(patch)
    if request_record_error is not None:
        return [
            make_event(
                "graph_patch_rejected",
                _patch_rejected_payload(
                    patch,
                    actor_role,
                    reason=request_record_error,
                    read_set_diff=None,
                ),
            )
        ]

    parent_session_id = planner_sessions_view(projection).get(patch.proposed_by_node_id)
    carryover_record_id = payload.carryover_record_id
    carryover_edge_payload: dict[str, Any] | None = None
    if carryover_record_id is not None:
        carryover_error: str | None = None
        if carryover_record_id not in accepted_record_summaries_by_id_view(projection):
            carryover_error = f"unknown_carryover_record_id:{carryover_record_id}"
        elif successor_planner_node_ids:
            carryover_edge_payload, carryover_error = _carryover_binding_edge_payload(
                projection,
                carryover_record_id,
                successor_planner_node_ids[0],
            )
        if carryover_error is not None:
            return [
                make_event(
                    "graph_patch_rejected",
                    _patch_rejected_payload(
                        patch,
                        actor_role,
                        reason=carryover_error,
                        read_set_diff=None,
                    ),
                )
            ]
    output = [
        make_event(
            "graph_patch_accepted",
            GraphPatchAcceptedPayload.model_validate(
                {
                    "patch_id": patch.patch_id,
                    "base_graph_position": patch.base_graph_position,
                    "actor_role": actor_role,
                    "proposed_by_node_id": patch.proposed_by_node_id,
                    "successor_planner_node_ids": successor_planner_node_ids,
                    "session_id": parent_session_id,
                    "carryover_record_id": carryover_record_id,
                }
            ).model_dump(mode="json"),
        )
    ]
    for op in patch.ops:
        output.extend(
            _patch_op_events(
                op,
                projection,
                events,
                make_event,
                patch_id=patch.patch_id,
                inherited_session_id=parent_session_id,
                carryover_record_id=carryover_record_id,
            )
        )
    if carryover_record_id is not None and successor_planner_node_ids:
        assert carryover_edge_payload is not None
        carryover_edge_payload["patch_id"] = patch.patch_id
        output.append(make_event("edge_created", carryover_edge_payload))
        output.append(
            make_event(
                "input_bound",
                {
                    "edge_id": carryover_edge_payload["edge_id"],
                    "to_node_id": successor_planner_node_ids[0],
                    "to_port": "session_carryover",
                    "record_ids": [carryover_record_id],
                    "bound_at_position": 0,
                    "binding_policy": carryover_edge_payload["binding_policy"],
                },
            )
        )
    output.extend(_source_repair_events(projection, events, output, make_event))
    return output


def _patch_rejected_payload(
    patch: PatchEnvelope,
    actor_role: str,
    *,
    reason: str | None,
    read_set_diff: dict[str, Any] | None,
) -> dict[str, Any]:
    return GraphPatchRejectedPayload.model_validate(
        {
            "patch_id": patch.patch_id,
            "base_graph_position": patch.base_graph_position,
            "actor_role": actor_role,
            "proposed_by_node_id": patch.proposed_by_node_id,
            "reason": reason,
            "read_set_diff": read_set_diff,
        }
    ).model_dump(mode="json")


def _request_record_validation_error(patch: PatchEnvelope) -> str | None:
    for op in patch.ops:
        if op.op != "create_node" or not isinstance(op.node, dict):
            continue
        try:
            _request_record_bindings_for_node(dict(op.node))
        except ValueError as exc:
            return safe_exception_reason(
                exc,
                code="invalid_request_record",
                message="invalid request record for patch node",
            )
    return None


def _successor_planner_node_ids(patch: PatchEnvelope) -> list[str]:
    node_ids: list[str] = []
    for op in patch.ops:
        if op.op != "create_node" or not isinstance(op.node, dict):
            continue
        node = op.node
        if node.get("kind") != "planner" or node.get("role") != "planner":
            continue
        node_id = node.get("node_id")
        if isinstance(node_id, str):
            node_ids.append(node_id)
    return node_ids


def _planner_budget_rejection(
    projection: GraphProjection,
    patch: PatchEnvelope,
) -> dict[str, int] | None:
    parent_generation = planner_generations_view(projection).get(patch.proposed_by_node_id, 0)
    attempted_generation = parent_generation + 1
    budget = planner_generation_budget(projection)
    if attempted_generation <= budget:
        return None
    return {"budget": budget, "count": attempted_generation}


def _apply_schedule_tick(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: ScheduleTickCommand,
    current_graph_position: int,
    clock: Clock,
    id_gen: IdGenerator,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if any(
        attempt.state == "recovery_requested"
        for attempt in execution_attempts_view(projection).values()
    ):
        # Restoration is authoritative for a recovering execution.  Do not
        # generate expiry/failure/retry facts before its proof is recorded.
        return []
    output = _expired_lease_events(projection, clock.now(), make_event)
    expired_lease_ids = _expired_active_lease_ids(projection, clock.now())
    active_claims = [
        _claim_from_dict(claim)
        for lease in leases_view(projection).values()
        if lease.state == "active" and lease.lease_id not in expired_lease_ids
        for claim in lease.resource_claims
    ]
    active_lease_node_ids = [
        str(lease.node_id)
        for lease in leases_view(projection).values()
        if lease.state == "active"
        and lease.lease_id not in expired_lease_ids
        and lease.node_id is not None
    ]
    retiring_node_ids = {
        event.payload["node_id"]
        for event in output
        if event.event_type == "node_retired" and isinstance(event.payload.get("node_id"), str)
    }
    nodes: list[NodeScheduleInfo] = []
    readied_node_ids: set[str] = set()
    for node_id, node_state in node_states_view(projection).items():
        if node_id in retiring_node_ids:
            continue
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        node = _node_schedule_info(projection, payload, node_id)
        backoff_reason = _retry_backoff_deferred_reason(projection, node_id, clock.now())
        if backoff_reason is not None:
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                backoff_reason,
                make_event,
            )
            continue
        readiness_node = replace(node, state="planned") if node_state == "ready" else node
        ready, reason = evaluate_readiness(
            readiness_node,
            query_run_state(projection) or "draft",
            active_lease_node_ids,
            active_claims,
        )
        if not ready:
            dead_input = _dead_input_from_readiness(node, reason)
            if dead_input is not None:
                if last_deferred_reasons_view(projection).get(node_id) != reason:
                    output.append(
                        make_event(
                            "dead_input_detected",
                            {
                                "node_id": node_id,
                                **dead_input,
                                "reason": reason,
                            },
                        )
                    )
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                reason,
                make_event,
            )
            continue
        if node_state != "ready":
            output.append(make_event("node_ready", {"node_id": node_id}))
            output.append(
                make_event(
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "ready",
                        "trigger": "readiness_evaluator",
                    },
                )
            )
            readied_node_ids.add(node_id)
        nodes.append(replace(node, state="ready"))
    decision = schedule(
        nodes,
        query_run_state(projection) or "draft",
        active_claims,
        current_graph_position,
        max_grants=payload.max_grants,
    )
    lease_seconds = payload.lease_seconds
    for node_id in decision.selected:
        claims = node_resource_claims_view(projection).get(node_id, [])
        lease_id = payload.lease_ids.get(node_id) or id_gen.next_id("lease")
        base_snapshot_id = _base_snapshot_id_for_node(projection, payload, node_id)
        if base_snapshot_id is None:
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                "missing_base_snapshot",
                make_event,
            )
            continue
        if node_id not in readied_node_ids:
            output.append(make_event("node_ready", {"node_id": node_id}))
        planner_session_id = _planner_session_id(projection, node_id, id_gen)
        lease_generation = _next_lease_generation(projection, node_id)
        projected_cache_authority_hash = cache_authority_binding(projection).hash
        node_cache_authority_hash = _cache_authority_hash_for_node(projection, node_id)
        if (cache_authority_is_new_format(projection) and node_cache_authority_hash is None) or (
            node_cache_authority_hash is not None
            and node_cache_authority_hash != projected_cache_authority_hash
        ):
            _append_node_deferred_if_changed(
                output,
                projection,
                node_id,
                "cache_authority_mismatch",
                make_event,
            )
            continue
        lease_payload: dict[str, Any] = {
            "lease_id": lease_id,
            "node_id": node_id,
            "generation": lease_generation,
            "execution_id": id_gen.next_id("exec"),
            "base_snapshot_id": base_snapshot_id,
            "expires_at": (clock.now() + timedelta(seconds=lease_seconds)).isoformat(),
            "resource_claims": [_resource_claim_payload(claim) for claim in claims],
        }
        if cache_authority_is_new_format(projection):
            lease_payload["cache_authority_hash"] = projected_cache_authority_hash
        if planner_session_id is not None:
            lease_payload["session_id"] = planner_session_id
        output.append(
            make_event(
                "lease_granted",
                _typed_lease_event_payload("lease_granted", lease_payload),
            )
        )
        if planner_session_id is not None:
            session_payload = PlannerSessionStateChangedPayload.model_validate(
                {
                    "session_id": planner_session_id,
                    "state": "attached",
                    "node_id": node_id,
                    "lease_generation": lease_generation,
                    "carryover_record_id": _session_carryover_record_id(projection, node_id),
                }
            )
            output.append(
                make_event(
                    "session_state_changed",
                    session_payload.model_dump(mode="json", exclude_none=False),
                )
            )
        output.append(
            make_event(
                "node_state_changed",
                {"node_id": node_id, "new_state": "leased", "trigger": "scheduler_grants_lease"},
            )
        )
    for node_id in decision.deferred:
        _append_node_deferred_if_changed(
            output,
            projection,
            node_id,
            decision.deferred_reasons[node_id],
            make_event,
        )
    return output


def _append_node_deferred_if_changed(
    output: list[EventEnvelope],
    projection: GraphProjection,
    node_id: str,
    reason: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> None:
    if last_deferred_reasons_view(projection).get(node_id) == reason:
        return
    output.append(make_event("node_deferred", {"node_id": node_id, "reason": reason}))


def _dead_input_from_readiness(
    node: NodeScheduleInfo,
    reason: str,
) -> dict[str, str] | None:
    prefix = "upstream_failed:"
    if not reason.startswith(prefix):
        return None
    from_node_id = reason.removeprefix(prefix)
    for edge in node.required_edges:
        if edge.from_node_id == from_node_id:
            return {"from_node_id": from_node_id, "to_port": edge.to_port}
    return {"from_node_id": from_node_id, "to_port": ""}


def _apply_reconcile(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: ReconcileCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    del events, payload
    run_state = query_run_state(projection)
    if run_state in TERMINAL_RUN_STATES:
        return [_command_rejected(make_event, "reconcile", f"terminal run: {run_state}")]
    return _repair_events(projection, make_event)


def _source_repair_events(
    projection: GraphProjection,
    events: list[EventEnvelope],
    source_events: list[EventEnvelope],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    accepted_records = [
        event.payload
        for event in source_events
        if event.event_type == "output_record_accepted"
        and isinstance(event.payload.get("record_id"), str)
    ]
    repair_node_ids = {
        node_id
        for event in source_events
        for node_id in (
            event.payload.get("proposed_by_node_id"),
            event.payload.get("node_id"),
        )
        if (
            event.event_type == "graph_patch_accepted"
            or (
                event.event_type == "node_state_changed"
                and event.payload.get("new_state") == "completed"
            )
        )
        and isinstance(node_id, str)
    }
    patch_or_completion = bool(repair_node_ids)
    if not accepted_records and not patch_or_completion:
        return []

    scoped_projection = _project_with_events(projection, source_events)
    active_lease_node_ids = _active_lease_node_ids(scoped_projection)
    output: list[EventEnvelope] = []
    for record in accepted_records:
        record_id = cast(str, record["record_id"])
        producer_node_id = record.get("producer_node_id") or record.get("node_id")
        if not isinstance(producer_node_id, str):
            continue
        if _is_check_result_record_payload(record):
            status = _check_result_status_value(record)
            if status in {"passed", "pass", "ok"}:
                output.extend(
                    _passed_check_terminalization_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        check_node_ids={producer_node_id},
                    )
                )
            else:
                output.extend(
                    _failed_check_recovery_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        record_ids={record_id},
                    )
                )
            continue
        if record.get("record_kind") == "verification":
            outcome = record.get("outcome")
            value = record.get("value")
            if outcome is None and isinstance(value, dict):
                outcome = cast(dict[str, Any], value).get("outcome")
            if outcome == "passed":
                output.extend(
                    _passed_verification_terminalization_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        record_ids={record_id},
                    )
                )
            elif outcome == "failed":
                output.extend(
                    _failed_verification_recovery_events(
                        scoped_projection,
                        active_lease_node_ids,
                        make_event,
                        record_ids={record_id},
                    )
                )
    if patch_or_completion:
        output.extend(
            _no_successor_recovery_terminal_failure_events(
                scoped_projection,
                active_lease_node_ids,
                make_event,
                recovery_node_ids=repair_node_ids,
            )
        )
    return _dedupe_repair_events(output)


def _repair_events(
    projection: GraphProjection,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    active_lease_node_ids = _active_lease_node_ids(projection)
    output: list[EventEnvelope] = []
    output.extend(
        _failed_check_recovery_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _failed_verification_recovery_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _passed_verification_terminalization_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _passed_check_terminalization_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    output.extend(
        _no_successor_recovery_terminal_failure_events(
            projection,
            active_lease_node_ids,
            make_event,
        )
    )
    return _dedupe_repair_events(output)


def _active_lease_node_ids(projection: GraphProjection) -> list[str]:
    return [
        str(lease.node_id)
        for lease in leases_view(projection).values()
        if lease.state == "active" and lease.node_id is not None
    ]


def _project_with_events(
    projection: GraphProjection,
    source_events: list[EventEnvelope],
) -> GraphProjection:
    output = projection
    for event in source_events:
        output = reduce_event(output, event)
    return output


def _dedupe_repair_events(repair_events: list[EventEnvelope]) -> list[EventEnvelope]:
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    output: list[EventEnvelope] = []
    for event in repair_events:
        key = (
            event.event_type,
            tuple(sorted((key, repr(value)) for key, value in event.payload.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(event)
    return output


def _failed_check_recovery_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    record_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if query_run_state(projection) != "active":
        return []
    if active_lease_node_ids:
        return []
    if any(
        state in {"planned", "blocked", "ready"} for state in node_states_view(projection).values()
    ):
        return []
    if not any(state != "accepted" for state in task_states_view(projection).values()):
        return []

    routine_snapshot = _latest_routine_snapshot_record(projection)
    if routine_snapshot is None:
        return []

    output: list[EventEnvelope] = []
    for failed_check in _current_failed_check_results(projection):
        if record_ids is not None and failed_check["record_id"] not in record_ids:
            continue
        recovery_node_id = _failed_check_recovery_node_id(failed_check)
        if recovery_node_id in node_states_view(projection):
            continue
        if _has_existing_failed_check_recovery(projection, failed_check):
            continue
        node_id = failed_check["node_id"]
        record_id = failed_check["record_id"]
        task_region_id = failed_check.get("task_region_id", node_id)
        recovery_region_id = f"recovery-{_stable_graph_id_part(task_region_id)}"
        record_type = failed_check.get("record_type", "check_result")
        source_port = "failure_record" if record_type == "failure_record" else "check_result"
        source_schema = "FailureRecord" if record_type == "failure_record" else "CheckResult"
        selector: dict[str, Any] = {"record_type": record_type, "schema": source_schema}
        if record_type == "check_result":
            selector["status"] = "failed"
        output.append(
            _node_created_event(
                projection,
                make_event,
                {
                    "node_id": recovery_node_id,
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                    "task_region_id": recovery_region_id,
                    "recovery_reason": "failed_required_check",
                    "recovery_of_node_id": node_id,
                    "recovery_of_record_id": record_id,
                },
            )
        )
        recovery_edges = [
            {
                "edge_id": f"edge-{_stable_graph_id_part(record_id)}-recovery-evidence",
                "from_node_id": node_id,
                "from_port": source_port,
                "to_node_id": recovery_node_id,
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": selector,
                "metadata": {
                    "purpose": "failed_required_check_recovery",
                    "recovery_of_record_id": record_id,
                },
            },
            {
                "edge_id": f"edge-routine-snapshot-{recovery_node_id}",
                "from_node_id": routine_snapshot["producer_node_id"],
                "from_port": routine_snapshot["port"],
                "to_node_id": recovery_node_id,
                "to_port": "routine_snapshot",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "routine_snapshot",
                    "schema": "RoutineSnapshot",
                },
                "metadata": {"purpose": "failed_required_check_recovery_context"},
            },
        ]
        for edge in recovery_edges:
            if _would_create_directed_cycle(
                projection,
                cast(str, edge["from_node_id"]),
                cast(str, edge["to_node_id"]),
            ):
                continue
            output.append(make_event("edge_created", edge))
            output.extend(_input_bound_events_for_edge(projection, edge, make_event))
    return output


def _failed_verification_recovery_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    record_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if query_run_state(projection) != "active":
        return []
    if active_lease_node_ids or ready_nodes_view(projection):
        return []
    if not any(state != "accepted" for state in task_states_view(projection).values()):
        return []

    routine_snapshot = _latest_routine_snapshot_record(projection)
    if routine_snapshot is None:
        return []

    output: list[EventEnvelope] = []
    for verification in _current_failed_verification_results(projection):
        if record_ids is not None and verification["record_id"] not in record_ids:
            continue
        recovery_node_id = _failed_verification_recovery_node_id(verification)
        if recovery_node_id in node_states_view(projection):
            continue
        if _has_existing_failed_verification_recovery(projection, verification):
            continue
        node_id = verification["node_id"]
        record_id = verification["record_id"]
        task_region_id = verification.get("task_region_id", node_id)
        recovery_region_id = f"recovery-{_stable_graph_id_part(task_region_id)}"
        output.append(
            _node_created_event(
                projection,
                make_event,
                {
                    "node_id": recovery_node_id,
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                    "task_region_id": recovery_region_id,
                    "recovery_reason": "failed_verification",
                    "recovery_of_node_id": node_id,
                    "recovery_of_record_id": record_id,
                },
            )
        )
        recovery_edges = [
            {
                "edge_id": f"edge-{_stable_graph_id_part(record_id)}-recovery-evidence",
                "from_node_id": node_id,
                "from_port": "verification_report",
                "to_node_id": recovery_node_id,
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "failed",
                },
                "metadata": {
                    "purpose": "failed_verification_recovery",
                    "recovery_of_record_id": record_id,
                },
            },
            {
                "edge_id": f"edge-routine-snapshot-{recovery_node_id}",
                "from_node_id": routine_snapshot["producer_node_id"],
                "from_port": routine_snapshot["port"],
                "to_node_id": recovery_node_id,
                "to_port": "routine_snapshot",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "routine_snapshot",
                    "schema": "RoutineSnapshot",
                },
                "metadata": {"purpose": "failed_verification_recovery_context"},
            },
        ]
        for edge in recovery_edges:
            if _would_create_directed_cycle(
                projection,
                cast(str, edge["from_node_id"]),
                cast(str, edge["to_node_id"]),
            ):
                continue
            output.append(make_event("edge_created", edge))
            output.extend(_input_bound_events_for_edge(projection, edge, make_event))
    return output


def _current_failed_verification_results(projection: GraphProjection) -> list[dict[str, str]]:
    passed_candidates = passed_verification_candidate_ids_view(projection)
    current: list[dict[str, str]] = []
    for verification in failed_verification_results_by_record_id_view(projection).values():
        verification_dict = _verification_result_dict(verification)
        if verification_dict is None:
            continue
        if verification_dict.get("candidate_id") in passed_candidates:
            continue
        if _superseded_by_later_regional_pass(projection, verification_dict):
            continue
        current.append(verification_dict)
    return current


def _superseded_by_later_regional_pass(
    projection: GraphProjection,
    verification: dict[str, Any],
) -> bool:
    """True when a later candidate in the same task region passed verification.

    Recovery never re-runs the failed candidate: a gap/recovery planner wires a
    corrective worker that produces a NEW candidate in the same region, and the
    corrective verifier grades that. The old failed verification's own
    candidate therefore never enters passed_verification_candidate_ids, so
    without this check the failure stays "current" forever — which is what let
    the recovery_planner_no_successor sweep fail runs W2/W4 after their
    repairs had already passed (incident 2026-07-04). Supersession requires a
    strictly later passing verdict (by verdict position) in the same region.
    """
    failed_region = _verification_task_region(projection, verification)
    if failed_region is None:
        return False
    failed_position = _candidate_verdict_position(projection, verification.get("candidate_id"))
    if failed_position is None:
        return False
    failed_record_id = verification.get("record_id")
    for passed in passed_verification_results_by_record_id_view(projection).values():
        passed_dict = _verification_result_dict(passed)
        if passed_dict is None:
            continue
        if passed_dict.get("record_id") == failed_record_id:
            continue
        candidate_id = passed_dict.get("candidate_id")
        verdict = verifier_verdicts_view(projection).get(candidate_id or "")
        if verdict is not None and verdict.verdict != "passed":
            # The candidate's latest verdict is a failure; not a supersession.
            continue
        if _verification_task_region(projection, passed_dict) != failed_region:
            continue
        passed_position = _candidate_verdict_position(projection, candidate_id)
        if passed_position is None:
            continue
        if passed_position > failed_position:
            return True
    return False


def _verification_task_region(
    projection: GraphProjection,
    verification: dict[str, str],
) -> str | None:
    task_region_id = verification.get("task_region_id")
    if isinstance(task_region_id, str) and task_region_id:
        return task_region_id
    node_id = verification.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_task_regions_view(projection).get(node_id)
    return None


def _verification_result_dict(
    verification: VerificationResultProjection,
) -> dict[str, str] | None:
    data = verification.model_dump(mode="json")
    if not isinstance(data.get("node_id"), str) or not isinstance(data.get("record_id"), str):
        return None
    return {key: value for key, value in data.items() if isinstance(value, str)}


def _candidate_verdict_position(
    projection: GraphProjection,
    candidate_id: str | None,
) -> int | None:
    if not isinstance(candidate_id, str) or not candidate_id:
        return None
    verdict = verifier_verdicts_view(projection).get(candidate_id)
    if verdict is None:
        return None
    return verdict.position


def _passed_verification_terminalization_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    record_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if query_run_state(projection) != "active":
        return []
    if active_lease_node_ids or ready_nodes_view(projection):
        return []

    output: list[EventEnvelope] = []
    passed_verifications = _current_passed_verification_results(projection)
    latest_passed_verification = passed_verifications[-1] if passed_verifications else None
    for verification in passed_verifications:
        if record_ids is not None and verification["record_id"] not in record_ids:
            continue
        retirable_node_ids = _unreachable_failure_branch_node_ids(
            projection,
            verification["node_id"],
        )
        if verification == latest_passed_verification:
            output.extend(
                _passed_verification_final_check_edges(
                    projection,
                    verification,
                    make_event,
                    allow_create=bool(retirable_node_ids),
                )
            )
        if not retirable_node_ids:
            continue
        for node_id in retirable_node_ids:
            output.extend(_retire_node_events(projection, node_id, make_event))
    return output


def _passed_check_terminalization_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    check_node_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if query_run_state(projection) != "active":
        return []
    if active_lease_node_ids or ready_nodes_view(projection):
        return []

    output: list[EventEnvelope] = []
    for check_node_id, result in sorted(check_results_view(projection).items()):
        if check_node_ids is not None and check_node_id not in check_node_ids:
            continue
        if result.status not in {"passed", "pass", "ok"}:
            continue
        for node_id in _unreachable_check_failure_branch_node_ids(projection, check_node_id):
            output.extend(_retire_node_events(projection, node_id, make_event))
    return output


def _no_successor_recovery_terminal_failure_events(
    projection: GraphProjection,
    active_lease_node_ids: list[str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    recovery_node_ids: set[str] | None = None,
) -> list[EventEnvelope]:
    if query_run_state(projection) != "active":
        return []
    if active_lease_node_ids or ready_nodes_view(projection):
        return []
    if any(
        state in {"planned", "blocked", "ready", "leased", "running", "suspended"}
        for state in node_states_view(projection).values()
    ):
        return []
    if not any(state != "accepted" for state in task_states_view(projection).values()):
        return []

    terminal = _completed_no_successor_recovery(
        projection,
        recovery_node_ids=recovery_node_ids,
    )
    if terminal is None:
        return []
    if terminal.get("environment_failure") == "true":
        return []
    return [
        make_event(
            "run_lifecycle_changed",
            {
                "command_type": "schedule_tick",
                "from_state": "active",
                "to_state": "failed",
                "trigger": "recovery_planner_no_successor",
                "node_id": terminal["node_id"],
                "patch_id": terminal["patch_id"],
                "recovery_of_record_id": terminal["recovery_of_record_id"],
                "recovery_reason": terminal["recovery_reason"],
            },
        )
    ]


def _completed_no_successor_recovery(
    projection: GraphProjection,
    *,
    recovery_node_ids: set[str] | None = None,
) -> dict[str, str] | None:
    """Find a completed recovery planner whose recovery is a genuine dead end.

    A recovery planner only counts as a dead end when ALL of the following
    hold: its latest accepted patch created no successor planner, it created
    no executable successor nodes (worker/verifier/check wired from the
    planner's outputs), and nothing downstream of the planner has since
    produced a passing verification or check. The last two guards were added
    after runs W2 (69ce4f7c) and W4 (0694df2d) were failed by this sweep on
    2026-07-04 even though their recovery patches had spawned corrective
    workers whose candidates passed verification and satisfied the final
    invariant checks — a successful recovery, misread as a dead end because
    only successor *planner* nodes were counted as continuation.
    """
    recovery_nodes = _recovery_nodes_by_record_id(projection)
    for failed in [
        *_current_failed_check_results(projection),
        *_current_failed_verification_results(projection),
    ]:
        record_id = failed["record_id"]
        for recovery in recovery_nodes.get(record_id, []):
            node_id = recovery["node_id"]
            if recovery_node_ids is not None and node_id not in recovery_node_ids:
                continue
            if node_states_view(projection).get(node_id) != "completed":
                continue
            patch_id = _accepted_no_successor_patch_id(projection, node_id)
            if patch_id is None:
                continue
            if _recovery_created_executable_successors(projection, node_id):
                continue
            if _recovery_lineage_superseded(projection, node_id):
                continue
            return {
                "node_id": node_id,
                "patch_id": patch_id,
                "recovery_of_record_id": record_id,
                "recovery_reason": recovery["recovery_reason"],
                "environment_failure": str(
                    failed.get("classification")
                    in {"environment_error", "tool_error", "tool_unavailable"}
                ).lower(),
            }
    return None


def _recovery_nodes_by_record_id(
    projection: GraphProjection,
) -> dict[str, list[dict[str, str]]]:
    return {
        record_id: [
            {
                "node_id": recovery.node_id,
                "recovery_reason": recovery.recovery_reason,
            }
            for recovery in recoveries
        ]
        for record_id, recoveries in recovery_nodes_by_record_id_view(projection).items()
    }


def _accepted_no_successor_patch_id(projection: GraphProjection, node_id: str) -> str | None:
    patch_ids = accepted_no_successor_patches_by_node_view(projection).get(node_id, [])
    return patch_ids[-1] if patch_ids else None


def _recovery_created_executable_successors(
    projection: GraphProjection,
    recovery_node_id: str,
) -> bool:
    """True when a recovery planner wired executable (non-planner) successors.

    A gap/recovery planner's accepted patch links its output records to the
    corrective work it plans (e.g. classified_gap -> worker), so an outgoing
    edge to a later-created non-planner node means the recovery produced real
    work — not a dead end — even though successor_planner_node_ids was empty.
    """
    recovery_position = node_creation_positions_view(projection).get(recovery_node_id, 0)
    for edge in edges_view(projection).values():
        if edge.from_node_id != recovery_node_id:
            continue
        to_node_id = edge.to_node_id
        if to_node_id not in node_kinds_view(projection):
            continue
        if node_kinds_view(projection).get(to_node_id) == "planner":
            continue
        if node_creation_positions_view(projection).get(to_node_id, 0) < recovery_position:
            continue
        return True
    return False


def _recovery_lineage_superseded(
    projection: GraphProjection,
    recovery_node_id: str,
) -> bool:
    """True when work downstream of a recovery planner has already passed.

    Walks the edge graph from the recovery planner and looks for a passing
    verification (whose candidate's latest verdict is still a pass) or a
    passing check result produced by any reachable node. Covers both recovery
    flavors: failed verifications (W2 shape) and failed required checks (W4
    shape), where the corrective chain is planner -> worker -> verifier.
    """
    reachable = _downstream_node_ids(projection, recovery_node_id)
    if not reachable:
        return False
    for verification in passed_verification_results_by_record_id_view(projection).values():
        if verification.node_id not in reachable:
            continue
        candidate_id = verification.candidate_id
        verdict = verifier_verdicts_view(projection).get(candidate_id or "")
        if verdict is None or verdict.verdict == "passed":
            return True
    for check_node_id, result in check_results_view(projection).items():
        if check_node_id not in reachable:
            continue
        if result.status in {"passed", "pass", "ok"}:
            return True
    return False


def _downstream_node_ids(projection: GraphProjection, start_node_id: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in edges_view(projection).values():
        source = edge.from_node_id
        target = edge.to_node_id
        adjacency.setdefault(source, set()).add(target)
    seen: set[str] = set()
    frontier = [start_node_id]
    while frontier:
        node_id = frontier.pop()
        for neighbor in adjacency.get(node_id, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return seen


def _passed_verification_final_check_edges(
    projection: GraphProjection,
    verification: dict[str, str],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    allow_create: bool = True,
) -> list[EventEnvelope]:
    verifier_node_id = verification["node_id"]
    record_id = verification["record_id"]
    output: list[EventEnvelope] = []
    check_node_ids = _final_checks_waiting_for_verification_evidence(projection)
    if allow_create and not check_node_ids and not _has_final_invariant_check(projection):
        check_node_id = f"check-final-invariant-{_stable_graph_id_part(record_id)}"
        if _would_create_directed_cycle(projection, verifier_node_id, check_node_id):
            return output
        output.append(
            _node_created_event(
                projection,
                make_event,
                {
                    "node_id": check_node_id,
                    "kind": "check",
                    "role": "invariant_gate",
                    "state": "planned",
                    "task_region_id": "final-invariant-region",
                    "command_binding": "dynamic_feature_hidden_oracle",
                    "inputs": [
                        {
                            "port": "verification_evidence",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "port": "check_result",
                            "direction": "output",
                            "schema": "CheckResult",
                        }
                    ],
                },
            )
        )
        check_node_ids = [check_node_id]
    for check_node_id in check_node_ids:
        if _has_verification_evidence_edge(projection, verifier_node_id, check_node_id):
            continue
        edge = {
            "edge_id": (
                f"edge-{_stable_graph_id_part(record_id)}-passed-verification-final-"
                f"{_stable_graph_id_part(check_node_id)}"
            ),
            "from_node_id": verifier_node_id,
            "from_port": "verification_report",
            "to_node_id": check_node_id,
            "to_port": "verification_evidence",
            "required": True,
            "accepted_record_selector": {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "passed",
            },
            "metadata": {
                "purpose": "passed_verification_final_invariant_recovery",
                "recovery_of_record_id": record_id,
            },
        }
        if _would_create_directed_cycle(projection, verifier_node_id, check_node_id):
            continue
        output.append(make_event("edge_created", edge))
        output.extend(_input_bound_events_for_edge(projection, edge, make_event))
    return output


def _would_create_directed_cycle(
    projection: GraphProjection,
    from_node_id: str,
    to_node_id: str,
) -> bool:
    if from_node_id == to_node_id:
        return True
    adjacency: dict[str, set[str]] = {}
    for edge in edges_view(projection).values():
        source = edge.from_node_id
        target = edge.to_node_id
        adjacency.setdefault(source, set()).add(target)

    seen: set[str] = set()
    stack = [to_node_id]
    while stack:
        node_id = stack.pop()
        if node_id == from_node_id:
            return True
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(sorted(adjacency.get(node_id, set()), reverse=True))
    return False


def _has_final_invariant_check(projection: GraphProjection) -> bool:
    return any(
        kind == "check" and node_roles_view(projection).get(node_id) == "invariant_gate"
        for node_id, kind in node_kinds_view(projection).items()
    )


def _current_passed_verification_results(projection: GraphProjection) -> list[dict[str, str]]:
    failed_candidates = failed_verification_candidate_ids_view(projection)
    current: list[dict[str, str]] = []
    for verification in passed_verification_results_by_record_id_view(projection).values():
        verification_dict = _verification_result_dict(verification)
        if verification_dict is None:
            continue
        if verification_dict.get("candidate_id") in failed_candidates:
            continue
        current.append(verification_dict)
    return current


def _final_checks_waiting_for_verification_evidence(
    projection: GraphProjection,
) -> list[str]:
    waiting: list[str] = []
    for node_id, kind in sorted(node_kinds_view(projection).items()):
        if kind != "check":
            continue
        if node_roles_view(projection).get(node_id) != "invariant_gate":
            continue
        if node_states_view(projection).get(node_id) not in {"planned", "blocked", "ready"}:
            continue
        if "verification_evidence" in input_bindings_view(projection).get(node_id, {}):
            continue
        waiting.append(node_id)
    return waiting


def _has_verification_evidence_edge(
    projection: GraphProjection,
    verifier_node_id: str,
    check_node_id: str,
) -> bool:
    for edge in edges_view(projection).values():
        if edge.from_node_id != verifier_node_id:
            continue
        if edge.from_port != "verification_report":
            continue
        if edge.to_node_id != check_node_id:
            continue
        if edge.to_port == "verification_evidence":
            return True
    return False


def _unreachable_failure_branch_node_ids(
    projection: GraphProjection,
    passed_verifier_node_id: str,
) -> list[str]:
    roots: list[str] = []
    for edge in edges_view(projection).values():
        if edge.from_node_id != passed_verifier_node_id:
            continue
        if edge.from_port != "verification_report":
            continue
        if edge.to_port != "verification_evidence":
            continue
        if _selector_value_match(edge, "outcome") != "failed":
            continue
        roots.append(edge.to_node_id)
    return _downstream_retirable_node_ids(projection, roots)


def _unreachable_check_failure_branch_node_ids(
    projection: GraphProjection,
    passed_check_node_id: str,
) -> list[str]:
    roots: list[str] = []
    for edge in edges_view(projection).values():
        if edge.from_node_id != passed_check_node_id:
            continue
        if edge.from_port != "check_result":
            continue
        to_node_id = edge.to_node_id
        if edge.required and not _is_gap_planner(projection, to_node_id):
            continue
        roots.append(to_node_id)
    return _downstream_retirable_node_ids(projection, roots)


def _downstream_retirable_node_ids(
    projection: GraphProjection,
    root_node_ids: list[str],
) -> list[str]:
    terminal_states = {"completed", "failed", "cancelled", "retired"}
    seen: set[str] = set()
    output: list[str] = []
    stack = list(reversed(root_node_ids))
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        state = node_states_view(projection).get(node_id)
        if state in terminal_states or state is None:
            continue
        if _is_final_invariant_check(projection, node_id):
            continue
        output.append(node_id)
        downstream = [
            edge.to_node_id
            for edge in edges_view(projection).values()
            if edge.from_node_id == node_id and edge.dependency_type != "state_dependency"
        ]
        for downstream_node_id in reversed(downstream):
            stack.append(downstream_node_id)
    return output


def _is_final_invariant_check(projection: GraphProjection, node_id: str) -> bool:
    return (
        node_kinds_view(projection).get(node_id) == "check"
        and node_roles_view(projection).get(node_id) == "invariant_gate"
    )


def _is_gap_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        node_kinds_view(projection).get(node_id) == "gap_planner"
        or node_roles_view(projection).get(node_id) == "gap_planner"
    )


def _selector_value_match(edge: EdgeProjection, key: str) -> Any:
    selector = edge.accepted_record_selector
    if not isinstance(selector, dict):
        return None
    record_type = selector.get("record_type")
    if record_type == "verification_report" and key == "outcome":
        return selector.get("outcome")
    if record_type == "check_result" and key == "status":
        return selector.get("status")
    if record_type == "gap_classification" and key == "classification":
        return selector.get("classification")
    return None


def _retire_node_events(
    projection: GraphProjection,
    node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if node_states_view(projection).get(node_id) in {"completed", "failed", "cancelled", "retired"}:
        return []
    return [
        make_event(
            "node_retired",
            {
                "node_id": node_id,
                "reason": "unreachable_after_passed_terminal_evidence",
            },
        ),
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "retired",
                "trigger": "passed_terminal_evidence_recovery",
            },
        ),
    ]


def _has_existing_failed_verification_recovery(
    projection: GraphProjection,
    verification: dict[str, str],
) -> bool:
    node_id = verification["node_id"]
    for edge in edges_view(projection).values():
        if edge.from_node_id != node_id:
            continue
        if edge.from_port != "verification_report":
            continue
        if edge.to_port != "verification_evidence":
            continue
        to_node_id = edge.to_node_id
        if node_states_view(projection).get(to_node_id) in {"cancelled", "failed", "retired"}:
            continue
        if node_kinds_view(projection).get(to_node_id) == "planner" and (
            node_roles_view(projection).get(to_node_id) == "gap_planner"
        ):
            return True
    return False


def _current_failed_check_results(projection: GraphProjection) -> list[dict[str, str]]:
    failed: list[dict[str, str]] = []
    for node_id, result in sorted(check_results_view(projection).items()):
        status = result.status
        if status in {"passed", "pass", "ok"}:
            continue
        record_id = result.record_id
        if not isinstance(record_id, str) or not record_id:
            continue
        check_result = {"node_id": node_id, "record_id": record_id}
        classification = result.classification
        if isinstance(classification, str) and classification:
            check_result["classification"] = classification
        task_region_id = result.task_region_id
        if isinstance(task_region_id, str) and task_region_id:
            check_result["task_region_id"] = task_region_id
        failed.append(check_result)
    for node_id, ports in sorted(accepted_output_records_by_node_port_view(projection).items()):
        if node_kinds_view(projection).get(node_id) != "check":
            continue
        if node_states_view(projection).get(node_id) in {"cancelled", "retired"}:
            continue
        if node_id in check_results_view(projection):
            continue
        for accepted_record in ports.get("failure_record", []):
            record_id = accepted_record.get("record_id")
            payload = accepted_record.get("payload")
            if not record_id:
                continue
            if not payload:
                continue
            payload_data = payload.model_dump(mode="json")
            check_result = {
                "node_id": node_id,
                "record_id": record_id,
                "record_type": "failure_record",
            }
            task_region_id = payload_data.get("task_region_id")
            if not isinstance(task_region_id, str) or not task_region_id:
                task_region_id = node_task_regions_view(projection).get(node_id)
            if isinstance(task_region_id, str) and task_region_id:
                check_result["task_region_id"] = task_region_id
            failed.append(check_result)
    return failed


def _has_existing_failed_check_recovery(
    projection: GraphProjection,
    failed_check: dict[str, str],
) -> bool:
    node_id = failed_check["node_id"]
    source_port = (
        "failure_record" if failed_check.get("record_type") == "failure_record" else "check_result"
    )
    for edge in edges_view(projection).values():
        if edge.from_node_id != node_id:
            continue
        if edge.from_port != source_port:
            continue
        if edge.to_port != "verification_evidence":
            continue
        to_node_id = edge.to_node_id
        if node_states_view(projection).get(to_node_id) in {"cancelled", "failed", "retired"}:
            continue
        if node_kinds_view(projection).get(to_node_id) == "planner" and (
            node_roles_view(projection).get(to_node_id) == "gap_planner"
        ):
            return True
    return False


def _latest_routine_snapshot_record(projection: GraphProjection) -> dict[str, str] | None:
    record = latest_routine_snapshot_record(projection)
    if record is not None:
        return {
            "record_id": record.record_id,
            "producer_node_id": record.producer_node_id,
            "port": record.port,
        }
    latest: dict[str, str] | None = None
    for summary in accepted_record_summaries_by_id_view(projection).values():
        record_id = summary.get("record_id")
        producer_node_id = summary.get("producer_node_id")
        port = summary.get("producer_port")
        if not all(
            isinstance(value, str) and value for value in (record_id, producer_node_id, port)
        ):
            continue
        is_routine_snapshot = (
            summary.get("record_type") == "routine_snapshot"
            or summary.get("record_kind") == "routine_snapshot"
            or summary.get("schema") == "RoutineSnapshot"
            or (producer_node_id == "routine-snapshot" and port in {"snapshot", "routine_snapshot"})
        )
        if not is_routine_snapshot:
            continue
        latest = {
            "record_id": cast(str, record_id),
            "producer_node_id": cast(str, producer_node_id),
            "port": cast(str, port),
        }
    return latest


def _failed_check_recovery_node_id(check_result: dict[str, str]) -> str:
    return f"planner-recover-{_stable_graph_id_part(check_result['record_id'])}"


def _failed_verification_recovery_node_id(verification: dict[str, str]) -> str:
    return f"planner-recover-{_stable_graph_id_part(verification['record_id'])}"


def _stable_graph_id_part(value: str) -> str:
    chars = [
        char.lower() if char.isalnum() or char in {"-", "_", "."} else "-" for char in value.strip()
    ]
    normalized = "".join(chars).strip("-")
    return normalized or "unknown"


def _base_snapshot_id_for_node(
    projection: GraphProjection,
    payload: ScheduleTickCommand,
    node_id: str,
) -> str | None:
    """Resolve a node's base snapshot from command override or input bindings.

    Returns None when no snapshot identity exists — the scheduler defers the
    node rather than fabricating an identity (PRD §19: every lease carries a
    real base snapshot).
    """
    if payload.base_snapshot_id:
        return payload.base_snapshot_id

    bindings = input_bindings_view(projection).get(node_id, {})
    for port in ("base_snapshot", "root_snapshot", "routine_snapshot"):
        binding = bindings.get(port)
        record_ids = binding.record_ids if binding is not None else None
        if isinstance(record_ids, list) and record_ids:
            first_record_id = cast(list[Any], record_ids)[0]
            if isinstance(first_record_id, str) and first_record_id:
                return first_record_id
    return None


def _retry_backoff_deferred_reason(
    projection: GraphProjection,
    node_id: str,
    now: datetime,
) -> str | None:
    retry_not_before = retry_not_before_by_node_view(projection).get(node_id)
    if retry_not_before is None:
        return None
    try:
        retry_at = datetime.fromisoformat(retry_not_before)
    except ValueError:
        return None
    if retry_at <= now:
        return None
    return f"retry_backoff_until:{retry_not_before}"


def _planner_session_id(
    projection: GraphProjection,
    node_id: str,
    id_gen: IdGenerator,
) -> str | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = planner_sessions_view(projection).get(node_id)
    if isinstance(session_id, str):
        return session_id
    return id_gen.next_id("session")


def _next_lease_generation(projection: GraphProjection, node_id: str) -> int:
    if not _is_chain_planner(projection, node_id):
        return 1
    session_id = planner_sessions_view(projection).get(node_id)
    generations = [
        lease.generation
        for lease in leases_view(projection).values()
        if session_id is not None
        and lease.session_id == session_id
        and lease.generation is not None
    ]
    return max(generations, default=0) + 1


def _session_carryover_record_id(projection: GraphProjection, node_id: str) -> str | None:
    binding = input_bindings_view(projection).get(node_id, {}).get("session_carryover")
    if binding is None:
        return None
    if not binding.record_ids:
        return None
    return binding.record_ids[0]


def _planner_session_state_event(
    projection: GraphProjection,
    node_id: str,
    state: str,
    lease_generation: int,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> EventEnvelope | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = planner_sessions_view(projection).get(node_id)
    if not isinstance(session_id, str):
        return None
    payload = PlannerSessionStateChangedPayload.model_validate(
        {
            "session_id": session_id,
            "state": state,
            "node_id": node_id,
            "lease_generation": lease_generation,
            "carryover_record_id": _session_carryover_record_id(projection, node_id),
        }
    )
    return make_event(
        "session_state_changed",
        payload.model_dump(mode="json", exclude_none=False),
    )


def _is_chain_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        node_kinds_view(projection).get(node_id) == "planner"
        and node_roles_view(projection).get(node_id) == "planner"
    )


def _apply_acknowledge_start(
    projection: GraphProjection,
    payload: AcknowledgeStartCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    node_id = payload.node_id
    lease_id = payload.lease_id
    lease_generation = payload.lease_generation
    execution_id = payload.execution_id

    lease = leases_view(projection).get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "acknowledge_start", "unknown lease")]
    if lease.state != "active":
        return [_command_rejected(make_event, "acknowledge_start", "lease not active")]
    if lease.node_id != node_id:
        return [_command_rejected(make_event, "acknowledge_start", "node_incompatible")]
    if lease.generation != lease_generation:
        return [_command_rejected(make_event, "acknowledge_start", "generation_incompatible")]
    lease_execution_id = lease.execution_id
    if isinstance(lease_execution_id, str) and lease_execution_id != execution_id:
        return [_command_rejected(make_event, "acknowledge_start", "execution_incompatible")]

    event_payload: dict[str, Any] = {
        "node_id": node_id,
        "new_state": "running",
        "trigger": "runtime_start_acknowledged",
    }
    if payload.prompt_summary is not None:
        event_payload["prompt_summary"] = payload.prompt_summary

    return [make_event("node_state_changed", event_payload)]


def _apply_agent_died(
    projection: GraphProjection,
    payload: AgentDiedCommand,
    clock: Clock,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    lease_id = payload.lease_id

    lease = leases_view(projection).get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "agent_died", "unknown lease")]
    if lease.state != "active":
        return [_command_rejected(make_event, "agent_died", "lease not active")]

    execution_id = payload.execution_id
    lease_execution_id = lease.execution_id
    if isinstance(lease_execution_id, str):
        # A lease with a recorded execution requires the caller to present the
        # matching execution identity — omitting it cannot revoke the lease.
        if execution_id is None:
            return [_command_rejected(make_event, "agent_died", "missing execution_id")]
        if execution_id != lease_execution_id:
            return [_command_rejected(make_event, "agent_died", "execution_incompatible")]

    node_id = str(lease.node_id)
    generation = lease.generation
    reason = payload.reason
    event_payload = {
        "lease_id": lease_id,
        "node_id": node_id,
        "generation": generation,
        "execution_id": lease_execution_id if isinstance(lease_execution_id, str) else execution_id,
        "reason": reason,
    }

    if non_gap_planner_has_accepted_patch(projection, node_id):
        return [
            make_event("agent_died", event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "completed",
                    "trigger": "accepted_graph_patch_before_agent_death",
                },
            ),
        ]

    if _is_rate_limit_death(reason):
        return [
            make_event("agent_died", event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
                    failure_class="infrastructure_failure",
                    error_class="agent_rate_limited",
                    retryable=False,
                    lease_id=lease_id,
                    execution_id=event_payload.get("execution_id"),
                    generation=generation,
                    reason=reason,
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": "agent_rate_limited",
                    "reason": reason,
                },
            ),
        ]

    if _is_non_retryable_runtime_death(reason):
        return [
            make_event("agent_died", event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
                    failure_class="infrastructure_failure",
                    error_class="runtime_configuration_error",
                    retryable=False,
                    lease_id=lease_id,
                    execution_id=event_payload.get("execution_id"),
                    generation=generation,
                    reason=reason,
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": "non_retryable_runtime_error",
                    "reason": reason,
                },
            ),
        ]

    max_attempts = payload.max_attempts
    attempt_number = node_attempts_view(projection).get(node_id, 0)
    if max_attempts > 0 and attempt_number >= max_attempts:
        return [
            make_event("agent_died", event_payload),
            make_event(
                "lease_revoked",
                _typed_lease_event_payload(
                    "lease_revoked",
                    {
                        "lease_id": lease_id,
                        "node_id": node_id,
                        "generation": generation,
                        "reason": reason,
                    },
                ),
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
                    failure_class="infrastructure_failure",
                    error_class="max_attempts_exhausted",
                    retryable=False,
                    lease_id=lease_id,
                    execution_id=event_payload.get("execution_id"),
                    generation=generation,
                    reason=reason,
                    metadata={"attempt_number": attempt_number, "max_attempts": max_attempts},
                ),
            ),
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": "max_attempts_exhausted",
                    "reason": "max_attempts_exhausted",
                    "attempt_number": attempt_number,
                    "max_attempts": max_attempts,
                },
            ),
        ]

    # V1 retry policy: runtime death before an accepted boundary requeues the
    # same executable node. No new retry node is created until output/file-state
    # acceptance semantics exist in the graph runtime slice.
    retry_backoff_seconds = payload.retry_backoff_seconds
    retry_payload: dict[str, Any] = {
        "node_id": node_id,
        "lease_id": lease_id,
        "generation": generation,
        "policy": "v1_requeue_same_node_after_agent_death",
        "reason": reason,
    }
    next_attempt_number = attempt_number + 1
    node_state_payload = {
        "node_id": node_id,
        "new_state": "ready",
        "trigger": "agent_died_retry_scheduled",
        "attempt_number": next_attempt_number,
    }
    if retry_backoff_seconds > 0:
        retry_not_before = (clock.now() + timedelta(seconds=retry_backoff_seconds)).isoformat()
        retry_payload["retry_after_seconds"] = retry_backoff_seconds
        retry_payload["retry_not_before"] = retry_not_before
        node_state_payload = {
            "node_id": node_id,
            "new_state": "blocked",
            "trigger": "agent_died_retry_backoff_scheduled",
            "retry_not_before": retry_not_before,
            "attempt_number": next_attempt_number,
        }
    return [
        make_event("agent_died", event_payload),
        make_event(
            "lease_revoked",
            _typed_lease_event_payload(
                "lease_revoked",
                {
                    "lease_id": lease_id,
                    "node_id": node_id,
                    "generation": generation,
                    "reason": reason,
                },
            ),
        ),
        make_event(
            "runtime_retry_scheduled",
            retry_payload,
        ),
        make_event(
            "output_record_accepted",
            _recovery_plan_record_payload(
                node_id=node_id,
                retry_payload=retry_payload,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
        ),
        make_event(
            "node_state_changed",
            node_state_payload,
        ),
    ]


def _failure_record_payload(
    *,
    node_id: str,
    phase: str,
    failure_class: FailureClass,
    error_class: str,
    retryable: bool,
    lease_id: str | None = None,
    execution_id: Any = None,
    generation: Any = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "failed_node_id": node_id,
        "phase": phase,
        "failure_class": failure_class,
        "error_class": error_class,
        "retryable": retryable,
    }
    if lease_id is not None:
        value["lease_id"] = lease_id
    if isinstance(execution_id, str):
        value["execution_id"] = execution_id
    if isinstance(generation, int) and not isinstance(generation, bool):
        value["lease_generation"] = generation
    if reason is not None:
        value["reason"] = reason
    if metadata:
        value.update(metadata)
    record = FailureRecord.model_validate(
        {
            "record_id": f"failure-{node_id}-{lease_id or error_class}",
            "record_kind": "graph_record",
            "record_type": "failure_record",
            "producer_node_id": node_id,
            "port": "failure_record",
            "schema": "FailureRecord",
            "value": value,
        }
    )
    return record.model_dump(mode="json")


def _recovery_plan_record_payload(
    *,
    node_id: str,
    retry_payload: dict[str, Any],
    retry_backoff_seconds: int,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "action": "retry",
        "responsible_actor": "controller",
        "graph_changes": [
            {
                "op": "set_node_state",
                "node_id": node_id,
                "state": "ready" if retry_backoff_seconds <= 0 else "blocked",
            }
        ],
        "reason": str(retry_payload.get("reason", "runtime_process_died")),
    }
    if retry_backoff_seconds > 0:
        value["retry_after_seconds"] = retry_backoff_seconds
        retry_not_before = retry_payload.get("retry_not_before")
        if isinstance(retry_not_before, str):
            value["retry_not_before"] = retry_not_before
    record = RecoveryPlanRecord.model_validate(
        {
            "record_id": f"recovery-plan-{node_id}-{retry_payload.get('lease_id', 'retry')}",
            "record_kind": "output",
            "record_type": "recovery_plan",
            "producer_node_id": node_id,
            "port": "recovery_plan",
            "schema": "RecoveryPlan",
            "value": value,
        }
    )
    return record.model_dump(mode="json")


def _is_rate_limit_death(reason: str) -> bool:
    normalized = reason.lower()
    return (
        "rate limit" in normalized
        or "hit rate limit" in normalized
        or "usage limit" in normalized
        or "quota" in normalized
    )


def _is_non_retryable_runtime_death(reason: str) -> bool:
    return (
        reason.startswith("cache scan entries budget exceeded at ")
        or reason.startswith("cache scan bytes budget exceeded at ")
        or reason.startswith("check node missing command_definition")
        or reason.startswith("check command_definition requires ")
    )


def _apply_raise_appeal(
    projection: GraphProjection,
    payload: RaiseAppealCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    oversight_node_id = payload.oversight_node_id or id_gen.next_id("oversight")
    return [
        make_event(
            "appeal_opened",
            AppealOpenedPayload.model_validate(
                {
                    "node_id": payload.appeal_node_id or id_gen.next_id("appeal"),
                    "appealed_node_id": payload.node_id,
                    "candidate_id": payload.candidate_id,
                    "task_region_id": payload.task_region_id,
                    "appeal_type": payload.appeal_type,
                    "lease_id": payload.lease_id,
                }
            ).model_dump(mode="json"),
        ),
        _node_created_event(
            projection,
            make_event,
            {
                "node_id": oversight_node_id,
                "kind": "oversight",
                "state": "planned",
                "task_region_id": payload.task_region_id,
            },
        ),
    ]


def _apply_record_decision(
    projection: GraphProjection,
    payload: RecordDecisionCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    decision_type = payload.decision_type
    node_id = payload.node_id
    if not _node_exists(projection, node_id):
        return [_command_rejected(make_event, "record_decision", f"unknown target node: {node_id}")]

    node_kind = node_kinds_view(projection).get(node_id)
    if decision_type == "authority" and node_kind != "authority_request":
        return [
            _command_rejected(
                make_event,
                "record_decision",
                "authority decisions require authority_request target",
            )
        ]
    if decision_type == "approval" and node_kind not in {"gate", "human_gate"}:
        return [
            _command_rejected(
                make_event,
                "record_decision",
                "approval decisions require gate or human_gate target",
            )
        ]

    node_state = node_states_view(projection).get(node_id)
    if node_state in {"completed", "failed", "cancelled", "retired"}:
        return [
            _command_rejected(make_event, "record_decision", f"terminal target node: {node_state}")
        ]

    run_state = query_run_state(projection)
    if run_state in {"cancelled", "failed"}:
        return [_command_rejected(make_event, "record_decision", f"terminal run: {run_state}")]

    event_payload: dict[str, Any] = {
        "decision_type": decision_type,
        "node_id": node_id,
        "decision": payload.decision,
        "decider": (
            payload.decider.model_dump(mode="json", include={"kind", "id"}, exclude_none=True)
            if isinstance(payload.decider, Actor)
            else payload.decider
        ),
        "scope": payload.scope,
        "expires_at": payload.expires_at,
        "reason": payload.reason,
        "record_id": payload.record_id,
    }
    event_payload = {key: value for key, value in event_payload.items() if value is not None}
    task_region_id = node_task_regions_view(projection).get(node_id)
    if task_region_id is not None:
        event_payload.setdefault("task_region_id", task_region_id)

    if decision_type == "approval":
        event_type = "approval_decision_recorded"
    elif decision_type == "authority":
        event_type = "authority_decision_recorded"
    else:
        event_type = "oversight_decision_recorded"
    payload_model = {
        "approval_decision_recorded": ApprovalDecisionRecordedPayload,
        "authority_decision_recorded": AuthorityDecisionRecordedPayload,
        "oversight_decision_recorded": OversightDecisionRecordedPayload,
    }[event_type]
    output = [
        make_event(event_type, payload_model.model_validate(event_payload).model_dump(mode="json"))
    ]
    if decision_type == "approval" and payload.decision == "rejected":
        output.append(
            make_event(
                "node_state_changed",
                {
                    "node_id": node_id,
                    "new_state": "failed",
                    "trigger": f"{event_type}_rejected",
                },
            )
        )
        output.extend(_release_active_node_leases(projection, node_id, make_event))
        return output
    try:
        decision_record = _decision_output_record(projection, node_id, event_payload, decision_type)
    except ValueError as exc:
        return [
            _command_rejected(
                make_event,
                "record_decision",
                safe_exception_reason(
                    exc,
                    code="invalid_decision_record",
                    message="invalid decision record",
                ),
            )
        ]
    if decision_record is not None:
        output.append(make_event("output_record_accepted", decision_record))
        output.extend(
            _input_bound_events_for_record(
                projection,
                node_id,
                str(decision_record["port"]),
                str(decision_record["record_id"]),
                decision_record,
                make_event,
            )
        )
    output.append(
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "completed",
                "trigger": f"{event_type}_accepted",
            },
        )
    )
    output.extend(_release_active_node_leases(projection, node_id, make_event))
    return output


def _decision_output_record(
    projection: GraphProjection,
    node_id: str,
    event_payload: dict[str, Any],
    decision_type: Any,
) -> dict[str, Any] | None:
    node_kind = node_kinds_view(projection).get(node_id)
    if decision_type == "authority" or node_kind == "authority_request":
        record_type = "authority_decision"
        port = "authority_decision"
        schema = "AuthorityDecision"
    elif decision_type == "approval" or node_kind in {"gate", "human_gate"}:
        record_type = "decision_record"
        port = "decision_record"
        schema = "DecisionRecord"
    else:
        return None
    record_id = event_payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = f"{record_type}-{node_id}"
    value = {
        "decision": event_payload.get("decision"),
        "decision_type": decision_type,
        "decider": event_payload.get("decider"),
        "scope": event_payload.get("scope"),
        "expires_at": event_payload.get("expires_at"),
        "reason": event_payload.get("reason"),
    }
    record_payload = {
        "record_id": record_id,
        "record_kind": "output",
        "record_type": record_type,
        "producer_node_id": node_id,
        "port": port,
        "schema": schema,
        "value": {key: entry for key, entry in value.items() if entry is not None},
    }
    if record_type == "authority_decision":
        return AuthorityDecisionRecord.model_validate(record_payload).model_dump(mode="json")
    return DecisionRecord.model_validate(record_payload).model_dump(mode="json")


def _apply_record_gatekeeper_verdicts(
    projection: GraphProjection,
    payload: RecordGatekeeperVerdictsCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    record_id = payload.file_state_record_id

    record = file_state_records_view(projection).get(record_id)
    if record is None:
        return [
            _command_rejected(
                make_event,
                "record_gatekeeper_verdicts",
                f"unknown file_state record: {record_id}",
            )
        ]

    execution_id = payload.execution_id

    unresolved_paths = {
        str(entry["path"])
        for entry in _record_residue(record)
        if isinstance(entry.get("path"), str) and entry.get("needs_gatekeeper") is True
    }
    accepted: list[GatekeeperVerdictRow] = []
    seen_paths: set[str] = set()
    for verdict in payload.verdicts:
        path = verdict.path
        if path in seen_paths:
            return [
                _command_rejected(
                    make_event,
                    "record_gatekeeper_verdicts",
                    f"duplicate verdict path: {path}",
                )
            ]
        seen_paths.add(path)
        if path not in unresolved_paths:
            return [
                _command_rejected(
                    make_event,
                    "record_gatekeeper_verdicts",
                    f"path is not unresolved residue: {path}",
                )
            ]
        accepted_verdict = GatekeeperVerdictRow(
            path=path,
            classification=verdict.classification,
            confidence=verdict.confidence,
            rationale=verdict.rationale,
            model_id=verdict.model_id or payload.model_id or "unknown",
            gen_ai_usage_input_tokens=verdict.gen_ai_usage_input_tokens,
            gen_ai_usage_output_tokens=verdict.gen_ai_usage_output_tokens,
            gen_ai_usage_cache_read_input_tokens=verdict.gen_ai_usage_cache_read_input_tokens,
            gen_ai_usage_cache_creation_input_tokens=verdict.gen_ai_usage_cache_creation_input_tokens,
            cost_usd=verdict.cost_usd,
            wall_time_ms=verdict.wall_time_ms,
        )
        accepted.append(accepted_verdict)

    cost_payload = _gatekeeper_cost_payload(
        record_id, execution_id, payload.consult_id, accepted, payload.cost
    )
    events = [
        make_event(
            "gatekeeper_verdict_recorded",
            {
                "file_state_record_id": record_id,
                "execution_id": execution_id,
                "producer_node_id": record.producer_node_id,
                "verdicts": [verdict.model_dump(mode="json") for verdict in accepted],
                "resolved_count": len(accepted),
            },
        ),
    ]
    secret_paths = [verdict.path for verdict in accepted if verdict.classification == "secret"]
    if secret_paths:
        cleanup_id = f"{record_id}:gatekeeper-secret"
        events.append(
            make_event(
                "cleanup_requested",
                CleanupRequestedPayload.model_validate(
                    {
                        "cleanup_id": cleanup_id,
                        "file_state_record_id": record_id,
                        "snapshot_id": record.snapshot_id,
                        "paths": secret_paths,
                        "authority": "gatekeeper",
                        "reason": "gatekeeper_classified_secret_after_snapshot",
                        "execution_id": execution_id,
                        "producer_node_id": record.producer_node_id,
                    }
                ).model_dump(mode="json"),
            )
        )
    events.append(make_event("gatekeeper_cost_recorded", cost_payload))
    return events


def _apply_record_cleanup_applied(
    projection: GraphProjection,
    payload: RecordCleanupAppliedCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    cleanup_id = payload.cleanup_id

    requested = _cleanup_requested_event(projection, cleanup_id)
    if requested is None:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"unknown cleanup_requested: {cleanup_id}",
            )
        ]
    requested_payload = requested.model_dump(mode="json")
    if _cleanup_applied_exists(projection, cleanup_id):
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"cleanup already applied: {cleanup_id}",
            )
        ]

    record_id = requested_payload.get("file_state_record_id")
    if not isinstance(record_id, str) or record_id not in file_state_records_view(projection):
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"unknown cleanup file_state record: {record_id}",
            )
        ]
    compromised_record = file_state_records_view(projection)[record_id]
    requested_snapshot_id = requested_payload.get("snapshot_id")
    compromised_snapshot_id = compromised_record.snapshot_id
    if requested_snapshot_id != compromised_snapshot_id:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "cleanup snapshot_id does not match compromised record",
            )
        ]

    command_record = payload.superseding_file_state_record
    if command_record.supersedes_record_id not in {None, record_id}:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "superseding record does not match cleanup target",
            )
        ]
    if command_record.cleanup_id not in {None, cleanup_id}:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "superseding record cleanup_id does not match cleanup target",
            )
        ]
    record = command_record.model_copy(
        update={"supersedes_record_id": record_id, "cleanup_id": cleanup_id}
    )
    if record.snapshot_id == compromised_snapshot_id:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "superseding record must use a different snapshot_id",
            )
        ]
    secret_paths = _cleanup_secret_paths(requested_payload)
    retained_secret_path = _record_contains_any_path(record.model_dump(mode="json"), secret_paths)
    if retained_secret_path is not None:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"superseding record still contains cleanup secret path: {retained_secret_path}",
            )
        ]
    applied_payload = CleanupAppliedPayload.model_validate(
        {
            "cleanup_id": cleanup_id,
            "file_state_record_id": record_id,
            "superseding_record_id": record.record_id,
            "old_snapshot_id": requested.snapshot_id,
            "new_snapshot_id": record.snapshot_id,
            "paths": requested.paths,
            "authority": requested.authority or "gatekeeper",
            "reason": payload.reason or requested.reason,
            "execution_id": requested.execution_id,
            "deleted_snapshot_ref": payload.deleted_snapshot_ref,
        }
    ).model_dump(mode="json")
    accepted_payload = record.model_dump(mode="json")
    return [
        make_event("cleanup_applied", applied_payload),
        make_event("output_record_accepted", accepted_payload),
        make_event("file_state_accepted", accepted_payload),
    ]


def apply_record_managed_snapshot_cleanup_applied(
    projection: GraphProjection,
    payload: RecordManagedSnapshotCleanupAppliedCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    """Record completion only for the complete cleanup ownership identity."""
    requested = _cleanup_requested_event(projection, payload.cleanup_id)
    if requested is None:
        return [
            _command_rejected(
                make_event, "record_managed_snapshot_cleanup_applied", "unknown cleanup"
            )
        ]
    expected = {
        "snapshot_id": payload.snapshot_id,
        "snapshot_ref": payload.snapshot_ref,
        "tree_sha": payload.tree_sha,
        "commit_sha": payload.commit_sha,
        "node_id": payload.node_id,
        "lease_id": payload.lease_id,
        "lease_generation": payload.lease_generation,
        "snapshot_role": payload.snapshot_role,
    }
    request_data = requested.model_dump(mode="json")
    if any(request_data.get(key) != value for key, value in expected.items()):
        return [
            _command_rejected(
                make_event, "record_managed_snapshot_cleanup_applied", "cleanup ownership conflicts"
            )
        ]
    if _cleanup_applied_exists(projection, payload.cleanup_id):
        return []
    return [
        make_event(
            "cleanup_applied",
            {
                "cleanup_id": payload.cleanup_id,
                "old_snapshot_id": payload.snapshot_id,
                "snapshot_ref": payload.snapshot_ref,
                "tree_sha": payload.tree_sha,
                "commit_sha": payload.commit_sha,
                "node_id": payload.node_id,
                "lease_id": payload.lease_id,
                "lease_generation": payload.lease_generation,
                "snapshot_role": payload.snapshot_role,
                "execution_id": request_data.get("execution_id"),
                "reason": request_data.get("reason"),
                "deleted_snapshot_ref": payload.deleted_snapshot_ref,
            },
        )
    ]


def _apply_record_requirement_revision(
    payload: RecordRequirementRevisionCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    event_payload = RequirementRevisionPayload.model_validate(
        {
            "requirement_id": payload.requirement_id,
            "version_id": payload.version_id,
            "classification": payload.classification,
            "requires_authority": payload.requires_authority,
            "validation_strengthening": payload.validation_strengthening,
            "active": payload.active,
            "previous_version_id": payload.previous_version_id,
            "revision_index": payload.revision_index,
            "authority_required_reason": payload.authority_required_reason,
            "revision_id": payload.revision_id,
            "proposal_id": payload.proposal_id,
            "patch_id": payload.patch_id,
            "node_id": payload.node_id,
            "requirement": payload.requirement,
        }
    ).model_dump(mode="json")
    return [make_event("requirement_revision_recorded", event_payload)]


def _apply_record_support_evidence(
    projection: GraphProjection,
    payload: RecordSupportEvidenceCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    requirement_id = payload.requirement_id
    requirement_version_id = payload.requirement_version_id
    if requirement_version_id is None:
        requirement_version_id = active_requirement_versions_view(projection).get(requirement_id)
    if not isinstance(requirement_version_id, str) or not requirement_version_id:
        return [
            _command_rejected(
                make_event,
                "record_support_evidence",
                f"unknown active requirement version: {requirement_id}",
            )
        ]

    event_payload = SupportEvidencePayload.model_validate(
        {
            "support_id": payload.support_id,
            "evidence_id": payload.evidence_id,
            "requirement_id": payload.requirement_id,
            "requirement_version_id": requirement_version_id,
            "status": payload.status,
            "stale_reason": payload.stale_reason,
            "confidence": payload.confidence,
        }
    ).model_dump(mode="json")
    return [make_event("support_evidence_recorded", event_payload)]


def _cleanup_requested_event(
    projection: GraphProjection,
    cleanup_id: str,
) -> CleanupRequestedProjection | None:
    return cleanup_requested_events_view(projection).get(cleanup_id)


def _cleanup_applied_exists(projection: GraphProjection, cleanup_id: str) -> bool:
    return cleanup_applied_ids_view(projection).get(cleanup_id) is True


def _cleanup_secret_paths(payload: dict[str, Any]) -> set[str]:
    paths = payload.get("paths")
    if not isinstance(paths, list):
        return set()
    return {path for path in cast(list[Any], paths) if isinstance(path, str) and path}


def _record_contains_any_path(
    record_payload: dict[str, Any],
    paths: set[str],
) -> str | None:
    if not paths:
        return None
    for key in (
        "paths",
        "tracked",
        "untracked",
        "ignored",
        "external",
        "classifications",
        "residue",
        "rejected_paths",
    ):
        entries = record_payload.get(key)
        if not isinstance(entries, list):
            continue
        for raw_entry in cast(list[Any], entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            path = entry.get("path")
            if isinstance(path, str) and path in paths:
                return path
    return None


def _record_residue(record: dict[str, Any] | FileStateRecord) -> list[dict[str, Any]]:
    if isinstance(record, FileStateRecord):
        return [entry.model_dump(mode="json") for entry in record.residue]
    residue = record.get("residue")
    if not isinstance(residue, list):
        raw_paths = record.get("paths")
        derived_residue: list[dict[str, Any]] = []
        if isinstance(raw_paths, list):
            for raw_entry in cast(list[Any], raw_paths):
                if not isinstance(raw_entry, dict):
                    continue
                entry = cast(dict[str, Any], raw_entry)
                if (
                    entry.get("source") in {"untracked", "ignored"}
                    or entry.get("classification") == "external_artifact"
                ):
                    derived_residue.append(entry)
        residue = derived_residue
    typed_residue = cast(list[Any], residue)
    return [dict(cast(dict[str, Any], entry)) for entry in typed_residue if isinstance(entry, dict)]


def _gatekeeper_cost_payload(
    record_id: str,
    execution_id: str,
    consult_id: str,
    verdicts: list[GatekeeperVerdictRow],
    cost: GatekeeperCostCommandRow | None,
) -> dict[str, Any]:
    model_ids = sorted({verdict.model_id or "unknown" for verdict in verdicts})
    defaults = {
        "file_state_record_id": record_id,
        "execution_id": execution_id,
        "consult_id": consult_id,
        "model_id": model_ids[0] if len(model_ids) == 1 else "mixed",
        "gen_ai_usage_input_tokens": sum(verdict.gen_ai_usage_input_tokens for verdict in verdicts),
        "gen_ai_usage_output_tokens": sum(
            verdict.gen_ai_usage_output_tokens for verdict in verdicts
        ),
        "gen_ai_usage_cache_read_input_tokens": sum(
            verdict.gen_ai_usage_cache_read_input_tokens for verdict in verdicts
        ),
        "gen_ai_usage_cache_creation_input_tokens": sum(
            verdict.gen_ai_usage_cache_creation_input_tokens for verdict in verdicts
        ),
        "cost_usd": sum(verdict.cost_usd for verdict in verdicts),
        "wall_time_ms": sum(verdict.wall_time_ms for verdict in verdicts),
        "item_count": len(verdicts),
    }
    overrides = (
        {
            key: value
            for key, value in {
                "model_id": cost.model_id,
                "gen_ai_usage_input_tokens": cost.gen_ai_usage_input_tokens,
                "gen_ai_usage_output_tokens": cost.gen_ai_usage_output_tokens,
                "gen_ai_usage_cache_read_input_tokens": cost.gen_ai_usage_cache_read_input_tokens,
                "gen_ai_usage_cache_creation_input_tokens": cost.gen_ai_usage_cache_creation_input_tokens,
                "cost_usd": cost.cost_usd,
                "wall_time_ms": cost.wall_time_ms,
            }.items()
            if value is not None
        }
        if cost is not None
        else {}
    )
    return GatekeeperCostRecordedPayload.model_validate({**defaults, **overrides}).model_dump(
        mode="json"
    )


def _request_record_events_for_node(
    node_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for record_payload, to_port in _request_record_bindings_for_node(node_payload):
        output.append(make_event("output_record_accepted", record_payload))
        record_id = record_payload["record_id"]
        node_id = record_payload["producer_node_id"]
        target_contract = DEFAULT_NODE_CONTRACTS.contract_for(
            str(node_payload["kind"]),
            node_payload.get("role") if isinstance(node_payload.get("role"), str) else None,
        )
        assert target_contract is not None
        port_contract = input_port_contract(target_contract, to_port)
        assert port_contract is not None
        edge_payload = {
            "edge_id": f"edge-{record_id}-to-{node_id}-{to_port}",
            "from_node_id": node_id,
            "from_port": record_payload["port"],
            "to_node_id": node_id,
            "to_port": to_port,
            "required": port_contract.required,
            "dependency_type": "input_binding",
            "accepted_record_selector": {
                "record_type": record_payload["record_type"],
                "schema": record_payload["schema"],
            },
            "binding_policy": binding_policy(None, port_contract),
        }
        output.append(make_event("edge_created", edge_payload))
        output.append(
            make_event(
                "input_bound",
                {
                    "edge_id": edge_payload["edge_id"],
                    "to_node_id": node_id,
                    "to_port": to_port,
                    "record_ids": [record_id],
                    "bound_at_position": 0,
                    "binding_policy": edge_payload["binding_policy"],
                },
            )
        )
    return output


def _carryover_binding_edge_payload(
    projection: GraphProjection,
    record_id: str,
    successor_node_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    summary = accepted_record_summaries_by_id_view(projection).get(record_id)
    if summary is None:
        return None, f"unknown_carryover_record_id:{record_id}"
    source_node_id = summary.get("producer_node_id")
    source_port = summary.get("producer_port")
    record_type = summary.get("record_type")
    schema = summary.get("schema")
    if (
        not isinstance(source_node_id, str)
        or not isinstance(source_port, str)
        or not isinstance(record_type, str)
        or not isinstance(schema, str)
    ):
        return None, f"invalid_carryover_record_id:{record_id}"
    source_kind = node_kinds_view(projection).get(source_node_id)
    source_role = node_roles_view(projection).get(source_node_id)
    target_contract = DEFAULT_NODE_CONTRACTS.contract_for("planner", "planner")
    if source_kind is None or target_contract is None:
        return None, f"invalid_carryover_record_id:{record_id}"
    target_port = input_port_contract(target_contract, "session_carryover")
    if target_port is None:
        return None, f"invalid_carryover_record_id:{record_id}"
    edge_payload = {
        "edge_id": f"edge-session-carryover-{successor_node_id}",
        "from_node_id": source_node_id,
        "from_port": source_port,
        "to_node_id": successor_node_id,
        "to_port": "session_carryover",
        "required": target_port.required,
        "dependency_type": "input_binding",
        "accepted_record_selector": {"record_type": record_type, "schema": schema},
        "binding_policy": binding_policy(None, target_port),
    }
    edge_error = validate_edge_payload(
        edge_payload,
        source_kind=source_kind,
        source_role=source_role,
        target_kind="planner",
        target_role="planner",
    )
    if edge_error is not None:
        return None, f"invalid_carryover_record_id:{record_id}:{edge_error}"
    return edge_payload, None


def _request_record_bindings_for_node(
    node_payload: dict[str, Any],
) -> list[tuple[dict[str, Any], str]]:
    kind = node_payload.get("kind")
    if kind == "human_gate":
        record = _decision_request_record_for_node(node_payload)
        return [(record.model_dump(mode="json"), "decision_request")]
    if kind == "authority_request":
        record = _authority_request_record_for_node(node_payload)
        return [(record.model_dump(mode="json"), "authority_request_record")]
    return []


def _decision_request_record_for_node(node_payload: dict[str, Any]) -> DecisionRequestRecord:
    node_id = _required_node_id_for_request_record(node_payload)
    raw_request = _request_payload_object(node_payload, "decision_request")
    value = dict(raw_request)
    value.setdefault(
        "decision_type", _request_payload_string(node_payload, "decision_type") or "approval"
    )
    value.setdefault("options", ["approve", "reject"])
    value.setdefault(
        "consequence_summary",
        _request_payload_string(node_payload, "reason")
        or "Manual decision required before graph can continue.",
    )
    return DecisionRequestRecord.model_validate(
        {
            "record_id": _request_payload_string(node_payload, "decision_request_record_id")
            or f"decision-request-{node_id}",
            "record_kind": "graph_record",
            "record_type": "decision_request",
            "producer_node_id": node_id,
            "port": "decision_request",
            "schema": "DecisionRequest",
            "value": value,
        }
    )


def _authority_request_record_for_node(node_payload: dict[str, Any]) -> AuthorityRequestRecord:
    node_id = _required_node_id_for_request_record(node_payload)
    raw_request = _request_payload_object(
        node_payload,
        "authority_request_record",
        alias="authority_request",
    )
    value = dict(raw_request)
    value.setdefault(
        "reason", _request_payload_string(node_payload, "reason") or "Authority required."
    )
    target_region_id = _request_payload_string(node_payload, "task_region_id")
    if target_region_id is not None:
        value.setdefault("target_region_id", target_region_id)
    return AuthorityRequestRecord.model_validate(
        {
            "record_id": _request_payload_string(node_payload, "authority_request_record_id")
            or f"authority-request-{node_id}",
            "record_kind": "graph_record",
            "record_type": "authority_request_record",
            "producer_node_id": node_id,
            "port": "authority_request_record",
            "schema": "AuthorityRequest",
            "value": value,
        }
    )


def _required_node_id_for_request_record(node_payload: dict[str, Any]) -> str:
    node_id = node_payload.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        msg = "request record node requires node_id"
        raise ValueError(msg)
    return node_id


def _request_payload_object(
    node_payload: dict[str, Any],
    key: str,
    *,
    alias: str | None = None,
) -> dict[str, Any]:
    raw_request = node_payload.get(key)
    if raw_request is None and alias is not None:
        raw_request = node_payload.get(alias)
        key = alias if raw_request is not None else key
    if raw_request is None:
        return {}
    if not isinstance(raw_request, dict):
        msg = f"{key} must be an object"
        raise ValueError(msg)
    request = dict(cast(dict[str, Any], raw_request))
    value = request.get("value")
    if isinstance(value, dict):
        return dict(cast(dict[str, Any], value))
    return request


def _request_payload_string(node_payload: dict[str, Any], key: str) -> str | None:
    value = node_payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _patch_op_events(
    op: PatchOp,
    projection: GraphProjection,
    events: list[EventEnvelope],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    patch_id: str,
    inherited_session_id: str | None = None,
    carryover_record_id: str | None = None,
) -> list[EventEnvelope]:
    op_payload = _op_payload(op)
    if op.op == "create_node" and isinstance(op.node, dict):
        node_payload = dict(op.node)
        node_payload["patch_id"] = patch_id
        node_payload.setdefault("state", "planned")
        _ensure_default_node_authority(node_payload)
        canonicalize_check_command_definition(node_payload, events, projection=projection)
        if node_payload.get("kind") == "planner" and node_payload.get("role") == "planner":
            if inherited_session_id is not None:
                node_payload.setdefault("session_id", inherited_session_id)
            _ensure_optional_session_carryover_input(node_payload)
            if carryover_record_id is not None:
                node_payload["carryover_record_id"] = carryover_record_id
        output = [_node_created_event(projection, make_event, node_payload)]
        output.extend(_request_record_events_for_node(node_payload, make_event))
        return output
    if op.op == "create_edge":
        edge_id = op_payload.get("edge_id")
        required = op_payload.get("required")
        edge_payload = {
            "patch_id": patch_id,
            "edge_id": edge_id,
            "from_node_id": op.from_node_id,
            "from_port": op.from_port,
            "to_node_id": op.to_node_id,
            "to_port": op.to_port,
            "required": required if isinstance(required, bool) else True,
            "dependency_type": op_payload.get("dependency_type", "input_binding"),
        }
        for key in (
            "from_node_kind",
            "from_node_role",
            "purpose",
            "description",
            "selection",
            "binding_policy",
            "freshness_policy",
            "prompt_hydration_policy",
            "metadata",
        ):
            if key in op_payload:
                edge_payload[key] = op_payload[key]
        selector = op_payload.get("accepted_record_selector")
        if isinstance(selector, dict):
            edge_payload["accepted_record_selector"] = normalize_record_selector(selector)
        output = [make_event("edge_created", edge_payload)]
        output.extend(_input_bound_events_for_edge(projection, edge_payload, make_event))
        return output
    if op.op == "retire_node" and isinstance(op.node_id, str):
        return [
            make_event("node_retired", {"node_id": op.node_id}),
            make_event(
                "node_state_changed",
                {"node_id": op.node_id, "new_state": "retired", "trigger": "graph_patch_accepted"},
            ),
        ]
    if op.op == "create_gate":
        node_payload = _node_payload_for_op(projection, op_payload, default_kind="gate")
        node_payload["patch_id"] = patch_id
        return [make_event("node_created", node_payload)]
    if op.op == "create_revision_attempt":
        worker_raw = op_payload.get("worker_node")
        verifier_raw = op_payload.get("verifier_node")
        worker_node = dict(cast(dict[str, Any], worker_raw)) if isinstance(worker_raw, dict) else {}
        verifier_node = (
            dict(cast(dict[str, Any], verifier_raw)) if isinstance(verifier_raw, dict) else {}
        )
        task_region_id = str(op_payload.get("task_region_id", "revision"))
        worker_node.setdefault("node_id", f"worker-revision-{task_region_id}")
        worker_node.setdefault("kind", "worker")
        worker_node.setdefault("state", "planned")
        worker_node["patch_id"] = patch_id
        verifier_node.setdefault("node_id", f"verifier-revision-{task_region_id}")
        verifier_node.setdefault("kind", "verifier")
        verifier_node.setdefault("state", "planned")
        verifier_node["patch_id"] = patch_id
        events = [
            make_event(
                "revision_created",
                {
                    "node": {
                        "node_id": f"revision-{task_region_id}",
                        "kind": "task_projection",
                        "state": "planned",
                    },
                    "worker_node": worker_node,
                    "verifier_node": verifier_node,
                },
            )
        ]
        for node_key, default_kind in (("worker_node", "worker"), ("verifier_node", "verifier")):
            raw_node = op_payload.get(node_key)
            if isinstance(raw_node, dict):
                events.append(
                    make_event(
                        "node_created",
                        {
                            **_node_payload_for_op(
                                projection,
                                {"node": raw_node, **op_payload},
                                default_kind=default_kind,
                            ),
                            "patch_id": patch_id,
                        },
                    )
                )
        if len(events) == 1:
            events.append(
                make_event(
                    "node_created",
                    {
                        **_node_payload_for_op(projection, op_payload, default_kind="worker"),
                        "patch_id": patch_id,
                    },
                )
            )
        return events
    if op.op == "create_appeal":
        node_payload = _node_payload_for_op(projection, op_payload, default_kind="appeal")
        node_payload["patch_id"] = patch_id
        appeal_payload = {
            key: value for key, value in op_payload.items() if key not in {"op", "node"}
        }
        appeal_payload.setdefault("node_id", node_payload["node_id"])
        return [
            make_event("node_created", node_payload),
            make_event("appeal_opened", appeal_payload),
        ]
    if op.op == "set_resource_claims" and isinstance(op.node_id, str):
        return [
            make_event(
                "node_authority_changed",
                {
                    "node_id": op.node_id,
                    "resource_claims": [claim.model_dump() for claim in op.resource_claims or []],
                },
            )
        ]
    if op.op == "set_allowed_actions" and isinstance(op.node_id, str):
        return [
            make_event(
                "node_authority_changed",
                {
                    "node_id": op.node_id,
                    "allowed_actions": list(op.allowed_actions or []),
                },
            )
        ]
    if op.op == "mark_plan_region_suspect":
        return [
            make_event(
                "plan_region_marked_suspect",
                {key: value for key, value in op_payload.items() if key != "op"},
            )
        ]
    return []


def _ensure_default_node_authority(node_payload: dict[str, Any]) -> None:
    if node_payload.get("kind") != "worker":
        return
    raw_authority = node_payload.get("authority")
    authority = dict(cast(dict[str, Any], raw_authority)) if isinstance(raw_authority, dict) else {}
    authority.setdefault(
        "allowed_actions",
        ["submit_records", "request_clarification", "raise_appeal"],
    )
    if node_payload.get("access_mode") == "read_only":
        existing_claims = authority.get("resource_claims")
        has_ranked_claim = any(
            isinstance(claim.get("mode"), str) and claim["mode"] in MODE_RANK
            for claim in resource_claim_dicts(existing_claims)
        )
        if not has_ranked_claim:
            claims_list: list[Any] = (
                list(cast(list[Any], existing_claims)) if isinstance(existing_claims, list) else []
            )
            claims_list.append({"mode": "read", "scope": "repo", "paths": ["."]})
            authority["resource_claims"] = claims_list
    elif "resource_claims" not in authority:
        authority["resource_claims"] = [{"mode": "write", "scope": "repo", "paths": ["."]}]
    node_payload["authority"] = authority


def _ensure_optional_session_carryover_input(node_payload: dict[str, Any]) -> None:
    inputs = node_payload.get("inputs")
    if not isinstance(inputs, list):
        node_payload["inputs"] = [
            {"port": "session_carryover", "direction": "input", "required": False}
        ]
        return
    typed_inputs = cast(list[Any], inputs)
    for raw_input in typed_inputs:
        if not isinstance(raw_input, dict):
            continue
        input_payload = cast(dict[str, Any], raw_input)
        if input_payload.get("port") == "session_carryover":
            input_payload["required"] = False
            return
    typed_inputs.append({"port": "session_carryover", "direction": "input", "required": False})


def _expired_lease_events(
    projection: GraphProjection,
    now: datetime,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    expired: list[EventEnvelope] = []
    for lease in leases_view(projection).values():
        if not _lease_is_expired(lease, now):
            continue
        node_id = lease.node_id
        expired.append(
            make_event(
                "lease_expired",
                _typed_lease_event_payload(
                    "lease_expired",
                    {
                        "lease_id": lease.lease_id,
                        "node_id": node_id,
                        "generation": lease.generation,
                        "execution_id": lease.execution_id,
                        "expires_at": lease.expires_at,
                        "reason": "lease_expired_without_callback",
                    },
                ),
            )
        )
        if isinstance(node_id, str):
            expired.append(
                make_event(
                    "output_record_accepted",
                    _failure_record_payload(
                        node_id=node_id,
                        phase="runtime",
                        failure_class="infrastructure_failure",
                        error_class="lease_expired_without_callback",
                        retryable=False,
                        lease_id=lease.lease_id,
                        execution_id=lease.execution_id,
                        generation=lease.generation,
                        reason="lease_expired_without_callback",
                        metadata={"expires_at": lease.expires_at},
                    ),
                )
            )
            expired.append(
                make_event(
                    "node_state_changed",
                    {
                        "node_id": node_id,
                        "new_state": "failed",
                        "trigger": "lease_expired_without_callback",
                        "reason": "lease_expired_without_callback",
                    },
                )
            )
    return expired


def _expired_active_lease_ids(projection: GraphProjection, now: datetime) -> set[str]:
    return {
        lease.lease_id
        for lease in leases_view(projection).values()
        if _lease_is_expired(lease, now)
    }


def _lease_is_expired(lease: LeaseProjection, now: datetime) -> bool:
    if lease.state != "active":
        return False
    expires_at = lease.expires_at
    if not isinstance(expires_at, str):
        return False
    return datetime.fromisoformat(expires_at) <= now


def _node_schedule_info(
    projection: GraphProjection,
    payload: ScheduleTickCommand,
    node_id: str,
) -> NodeScheduleInfo:
    required_edges = _required_edges_for_node(projection, node_id)
    upstream_node_ids = {edge.from_node_id for edge in required_edges}
    return NodeScheduleInfo(
        node_id=node_id,
        kind=node_kinds_view(projection).get(node_id, "worker"),
        state=node_states_view(projection)[node_id],
        priority=payload.priorities.get(node_id, 0),
        region_order=payload.region_order.get(node_id, 0),
        creation_position=_node_creation_position(projection, node_id),
        resource_claims=[
            _claim_from_dict(claim)
            for claim in node_resource_claims_view(projection).get(node_id, [])
        ],
        required_edges=required_edges,
        satisfied_input_ports=set(input_bindings_view(projection).get(node_id, {})),
        upstream_states={
            upstream_node_id: node_states_view(projection)[upstream_node_id]
            for upstream_node_id in upstream_node_ids
            if upstream_node_id in node_states_view(projection)
        },
        upstream_kinds={
            upstream_node_id: node_kinds_view(projection)[upstream_node_id]
            for upstream_node_id in upstream_node_ids
            if upstream_node_id in node_kinds_view(projection)
        },
        upstream_pending_appeals={
            upstream_node_id
            for upstream_node_id in upstream_node_ids
            if node_pending_appeals_view(projection).get(upstream_node_id) is True
        },
        gate_decisions={
            gate_node_id: decision
            for gate_node_id, decision in node_gate_decisions_view(projection).items()
            if gate_node_id in upstream_node_ids
        },
        failed_candidate_id=node_failed_candidates_view(projection).get(node_id),
        preconditions=node_preconditions_view(projection).get(node_id, []),
        command_definition_present=node_id in node_command_definitions_view(projection),
    )


def _node_creation_position(projection: GraphProjection, node_id: str) -> int:
    return node_creation_positions_view(projection).get(node_id, 0)


def _required_edges_for_node(
    projection: GraphProjection,
    node_id: str,
) -> list[InputEdgeInfo]:
    edges: list[InputEdgeInfo] = []
    for edge in edges_view(projection).values():
        if edge.to_node_id != node_id:
            continue
        edges.append(
            InputEdgeInfo(
                from_node_id=edge.from_node_id,
                from_port=edge.from_port,
                to_node_id=edge.to_node_id,
                to_port=edge.to_port,
                required=edge.required,
                dependency_type=edge.dependency_type,
            )
        )
    return edges


def _lifecycle_event(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    command_type: str,
    from_state: str,
    to_state: str,
    trigger: Any,
) -> EventEnvelope:
    return make_event(
        "run_lifecycle_changed",
        {
            "command_type": command_type,
            "from_state": from_state,
            "to_state": to_state,
            "trigger": trigger,
        },
    )


def _command_rejected(
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    command_type: str,
    reason: str,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "command_type": command_type,
        "reason": reason,
    }
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics
    return make_event(
        "command_rejected",
        payload,
    )


def _node_exists(projection: GraphProjection, node_id: str) -> bool:
    return node_id in node_states_view(projection) or node_id in node_kinds_view(projection)


def _op_payload(op: PatchOp) -> dict[str, Any]:
    return op.model_dump(exclude_none=True)


def _node_payload_for_op(
    projection: GraphProjection, op_payload: dict[str, Any], *, default_kind: str
) -> dict[str, Any]:
    raw_node = op_payload.get("node")
    node_payload = dict(cast(dict[str, Any], raw_node)) if isinstance(raw_node, dict) else {}
    node_id = node_payload.get("node_id")
    if not isinstance(node_id, str):
        for key in ("node_id", "gate_id", "appeal_node_id", "revision_node_id"):
            value = op_payload.get(key)
            if isinstance(value, str):
                node_id = value
                break
    node_payload["node_id"] = node_id if isinstance(node_id, str) else default_kind
    node_payload.setdefault("kind", default_kind)
    node_payload.setdefault("state", "planned")
    for key in (
        "task_region_id",
        "attempt_number",
        "candidate_id",
        "predecessor_node_ids",
        "appealed_node_id",
        "failed_candidate_id",
    ):
        if key in op_payload and key not in node_payload:
            node_payload[key] = op_payload[key]
    _ensure_default_node_authority(node_payload)
    is_new_format = cache_authority_is_new_format(projection)
    projected_hash = cache_authority_binding(projection).hash
    supplied_hash = node_payload.get("cache_authority_hash")
    if supplied_hash is not None and (not is_new_format or supplied_hash != projected_hash):
        raise ValueError("dynamic node cache_authority_hash differs from routine snapshot")
    if is_new_format:
        node_payload["cache_authority_hash"] = projected_hash
    return node_payload


def _node_created_event(
    projection: GraphProjection,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    payload: dict[str, Any],
) -> EventEnvelope:
    """Single authority-normalizing constructor for command-created nodes."""
    normalized = _node_payload_for_op(projection, {"node": payload}, default_kind="worker")
    return make_event("node_created", normalized)


def _cache_authority_hash_for_node(projection: GraphProjection, node_id: str) -> str | None:
    return node_cache_authority_hash(projection, node_id)


def _input_bound_events_for_edge(
    projection: GraphProjection,
    edge_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if edge_payload.get("dependency_type", "input_binding") != "input_binding":
        return []
    edge_id = edge_payload.get("edge_id")
    from_node_id = edge_payload.get("from_node_id")
    from_port = edge_payload.get("from_port")
    to_node_id = edge_payload.get("to_node_id")
    to_port = edge_payload.get("to_port")
    if not all(
        isinstance(value, str) for value in (edge_id, from_node_id, from_port, to_node_id, to_port)
    ):
        return []
    typed_edge_id = cast(str, edge_id)
    typed_from_node_id = cast(str, from_node_id)
    typed_from_port = cast(str, from_port)
    typed_to_node_id = cast(str, to_node_id)
    typed_to_port = cast(str, to_port)

    output: list[EventEnvelope] = []
    for producer_node_id in _edge_backfill_producer_node_ids(
        projection,
        edge_payload,
        typed_from_node_id,
    ):
        records_by_port = output_records_by_node_port_view(projection).get(producer_node_id, {})
        for record in records_by_port.get(typed_from_port, []):
            record_payload = record.model_dump(mode="json")
            record_id = record_payload.get("record_id")
            if not isinstance(record_id, str):
                continue
            if not record_selector_matches(
                edge_payload.get("accepted_record_selector"),
                record_payload,
            ):
                continue
            binding_payload: dict[str, Any] = {
                "edge_id": typed_edge_id,
                "to_node_id": typed_to_node_id,
                "to_port": typed_to_port,
                "record_ids": [record_id],
                "bound_at_position": 0,
                "trigger": "edge_backfill",
            }
            binding_policy = edge_payload.get("binding_policy")
            if isinstance(binding_policy, str):
                binding_payload["binding_policy"] = binding_policy
            supersedes_record_id = record_payload.get("supersedes_record_id")
            if isinstance(supersedes_record_id, str):
                binding_payload["supersedes_record_id"] = supersedes_record_id
            output.append(make_event("input_bound", binding_payload))
    return output


def _projection_edge_accepts_producer(
    projection: GraphProjection,
    edge: EdgeProjection,
    producer_node_id: str,
) -> bool:
    if edge.from_node_id == producer_node_id:
        return True
    if edge.from_node_id != "*":
        return False
    if edge.from_node_kind is not None and (
        node_kinds_view(projection).get(producer_node_id) != edge.from_node_kind
    ):
        return False
    if edge.from_node_role is not None and (
        node_roles_view(projection).get(producer_node_id) != edge.from_node_role
    ):
        return False
    return True


def _edge_payload_accepts_producer(
    projection: GraphProjection,
    edge: dict[str, Any],
    producer_node_id: str,
) -> bool:
    from_node_id = edge.get("from_node_id")
    if from_node_id == producer_node_id:
        return True
    if from_node_id != "*":
        return False
    expected_kind = edge.get("from_node_kind")
    if (
        isinstance(expected_kind, str)
        and node_kinds_view(projection).get(producer_node_id) != expected_kind
    ):
        return False
    expected_role = edge.get("from_node_role")
    if (
        isinstance(expected_role, str)
        and node_roles_view(projection).get(producer_node_id) != expected_role
    ):
        return False
    return True


def _edge_backfill_producer_node_ids(
    projection: GraphProjection,
    edge: dict[str, Any],
    from_node_id: str,
) -> list[str]:
    if from_node_id != "*":
        return [from_node_id]
    return [
        node_id
        for node_id in sorted(node_kinds_view(projection))
        if _edge_payload_accepts_producer(projection, edge, node_id)
    ]


def _event_factory(
    run_id: str,
    command_type: str,
    clock: Clock,
    id_gen: IdGenerator,
) -> Callable[[str, dict[str, Any]], EventEnvelope]:
    def make_event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
        validate_emitted_event_type("graph_command_factory", event_type)
        typed_payload = serialize_event_payload(event_type, payload)
        return EventEnvelope(
            event_id=id_gen.next_id("event"),
            run_id=run_id,
            position=-1,
            event_type=event_type,
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            causation_id=command_type,
            timestamp=clock.now(),
            payload=typed_payload,
        )

    return make_event


def _callback_payload(payload: SubmitCallbackCommand) -> dict[str, Any] | None:
    if payload.payload is not None:
        return payload.payload
    if payload.payload_hash is not None:
        return {"payload_hash": payload.payload_hash}
    return None


def _canonical_external_callback_payload(
    payload: dict[str, Any] | None,
    expected_producer_node_id: str,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    canonical = dict(payload)
    records = canonical.get("output_records")
    if not isinstance(records, list):
        return canonical
    canonical_records: list[Any] = []
    for record in cast(list[Any], records):
        if isinstance(record, dict):
            typed_record = cast(dict[str, Any], record)
            if _is_verification_report_record_payload(typed_record):
                record = _verification_report_record_payload_for_validation(
                    typed_record,
                    expected_producer_node_id,
                )
        canonical_records.append(record)
    canonical["output_records"] = canonical_records
    return canonical


def _claim_from_dict(claim: Any) -> ResourceClaim:
    claim_payload = _resource_claim_payload(claim)
    mode = str(claim_payload.get("mode", "read"))
    scope = str(claim_payload.get("scope", "repo"))
    paths = (
        [str(path) for path in claim_payload.get("paths", [])]
        if isinstance(claim_payload.get("paths"), list)
        else []
    )
    # Self-healing normalization (also applied on replay of historic events): planners
    # sometimes put a repo-relative path prefix directly in `scope` instead of the
    # canonical scope="repo" + paths=[...] shape. For read/write claims (the only modes
    # whose scheduling/authority semantics key off `scope == "repo"`), fold a
    # path-shaped scope into `paths` so both the scheduler-conflict check and the
    # write-authority check (`_claim_is_repo_write`) see identical, correct semantics.
    # external/graph_write/review_write claims use `scope` for other purposes (or not at
    # all) and are left untouched.
    if mode in {"read", "write"} and scope not in ("repo", ""):
        if scope not in paths:
            paths = [*paths, scope]
        scope = "repo"
    return ResourceClaim(
        mode=mode,
        scope=scope,
        paths=paths,
        snapshot_id=cast(str | None, claim_payload.get("snapshot_id")),
        external_resource_key=cast(str | None, claim_payload.get("external_resource_key")),
        exclusive=bool(claim_payload.get("exclusive", False)),
    )


def _resource_claim_payload(claim: Any) -> dict[str, Any]:
    if hasattr(claim, "model_dump"):
        dumped = claim.model_dump(mode="json")
        if isinstance(dumped, dict):
            return cast(dict[str, Any], dumped)
    if isinstance(claim, dict):
        return dict(cast(dict[str, Any], claim))
    return {}


command_rejected = _command_rejected
event_factory = _event_factory

apply_lifecycle_command = _apply_lifecycle_command
apply_record_heartbeat = _apply_record_heartbeat
apply_seed_compiled_events = _apply_seed_compiled_events
apply_callback_command = _apply_callback_command
apply_patch_command = _apply_patch_command
apply_schedule_tick = _apply_schedule_tick
apply_reconcile = _apply_reconcile
apply_acknowledge_start = _apply_acknowledge_start
apply_agent_died = _apply_agent_died
apply_raise_appeal = _apply_raise_appeal
apply_record_decision = _apply_record_decision
apply_record_gatekeeper_verdicts = _apply_record_gatekeeper_verdicts
apply_record_node_usage = _apply_record_node_usage
apply_record_requirement_revision = _apply_record_requirement_revision
apply_record_support_evidence = _apply_record_support_evidence
apply_evaluate_join = _apply_evaluate_join
apply_evaluate_final_gate = _apply_evaluate_final_gate


def apply_record_cleanup_applied(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: RecordCleanupAppliedCommand,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    del events
    return _apply_record_cleanup_applied(projection, payload, make_event)
