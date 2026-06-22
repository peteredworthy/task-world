"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
import posixpath
from typing import Any, Protocol, cast

from orchestrator.graph.callbacks import (
    CallbackOutcome,
    CallbackRequest,
    validate_callback,
)
from orchestrator.graph.command_bindings import canonicalize_check_command_definition
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
    output_port_contract,
    validate_output_record,
)
from orchestrator.graph.macros import expand_patch_macros
from orchestrator.graph.models import (
    Actor,
    ActorKind,
    AnalysisSummaryRecord,
    ArtifactReferenceRecord,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CandidateRecord,
    CheckResultRecord,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    DecisionRecord,
    EventEnvelope,
    FailureRecord,
    FileStateRecord,
    JoinResultRecord,
    GraphPatchProposalRecord,
    OutputRecord,
    PatchEnvelope,
    PatchOp,
    RecoveryPlanRecord,
    VerificationReportRecord,
)
from orchestrator.graph.file_state import GATEKEEPER_TAXONOMY
from orchestrator.graph.patch_validator import validate_patch
from orchestrator.graph.projections import GraphProjection, final_invariant_blockers_for_events
from orchestrator.graph.scheduler import (
    InputEdgeInfo,
    NodeScheduleInfo,
    ResourceClaim,
    claims_conflict,
    evaluate_readiness,
    schedule,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_id(self, prefix: str = "") -> str: ...


RUN_LIFECYCLE_TRANSITIONS: dict[str, dict[str, str]] = {
    "accept_run": {"draft": "queued"},
    "start": {"queued": "active"},
    "pause": {"active": "pausing", "pausing": "paused"},
    "resume": {"paused": "resuming", "resuming": "active"},
    "cancel": {"active": "cancelling", "paused": "cancelling", "cancelling": "cancelled"},
    "complete": {"active": "completed"},
}
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


def apply_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    """Apply a pure graph command and return events a controller would append."""

    run_id = _run_id(events, payload)
    make_event = _event_factory(run_id, command_type, clock, id_gen)

    if command_type in RUN_LIFECYCLE_TRANSITIONS or command_type == "fail":
        return _apply_lifecycle_command(
            projection,
            events,
            command_type,
            payload,
            make_event,
            id_gen,
        )
    if command_type == "seed_compiled_events":
        return _apply_seed_compiled_events(projection, payload, make_event)
    if command_type == "submit_callback":
        return _apply_callback_command(projection, events, payload, make_event)
    if command_type == "submit_patch":
        return _apply_patch_command(projection, events, payload, make_event)
    if command_type == "schedule_tick":
        return _apply_schedule_tick(projection, events, payload, clock, id_gen, make_event)
    if command_type == "acknowledge_start":
        return _apply_acknowledge_start(projection, payload, make_event)
    if command_type == "agent_died":
        return _apply_agent_died(projection, payload, clock, make_event)
    if command_type == "raise_appeal":
        return _apply_raise_appeal(payload, make_event, id_gen)
    if command_type == "record_decision":
        return _apply_record_decision(projection, payload, make_event)
    if command_type == "record_gatekeeper_verdicts":
        return _apply_record_gatekeeper_verdicts(projection, payload, make_event)
    if command_type == "record_requirement_revision":
        return _apply_record_requirement_revision(payload, make_event)
    if command_type == "record_support_evidence":
        return _apply_record_support_evidence(projection, payload, make_event)
    if command_type == "evaluate_join":
        return _apply_evaluate_join(projection, payload, make_event, id_gen)
    if command_type == "evaluate_final_gate":
        return _apply_evaluate_final_gate(projection, events, payload, make_event, id_gen)
    if command_type == "record_cleanup_applied":
        return _apply_record_cleanup_applied(projection, events, payload, make_event)
    if command_type == "record_heartbeat":
        return _apply_record_heartbeat(projection, payload, clock, make_event)

    return [
        make_event(
            "command_rejected",
            {
                "command_type": command_type,
                "reason": f"unknown command: {command_type}",
            },
        )
    ]


def _apply_lifecycle_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    current_state = projection["run_state"] or "draft"
    if command_type == "fail":
        if current_state in NONTERMINAL_RUN_STATES:
            return [
                _lifecycle_event(
                    make_event,
                    command_type,
                    current_state,
                    "failed",
                    payload.get("reason", "unrecoverable_controller_error"),
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
    if command_type == "complete":
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
    trigger = payload.get("trigger", f"{command_type}_command_accepted")
    output: list[EventEnvelope] = []
    if command_type == "complete" and not _has_passed_completion_decision(events):
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


def _has_passed_completion_decision(events: list[EventEnvelope]) -> bool:
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        if event.payload.get("record_type") != "completion_decision":
            continue
        if event.payload.get("port") != "completion_decision":
            continue
        value = event.payload.get("value")
        if isinstance(value, dict) and cast(dict[str, Any], value).get("status") == "passed":
            return True
    return False


def _lifecycle_completion_decision_event(
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> EventEnvelope:
    record_id = payload.get("completion_decision_record_id") or payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = id_gen.next_id("completion-decision")
    producer_node_id = payload.get("node_id")
    if not isinstance(producer_node_id, str) or not producer_node_id:
        producer_node_id = "run_lifecycle"
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
    payload: dict[str, Any],
    clock: Clock,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    lease_id = payload.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        return [_command_rejected(make_event, "record_heartbeat", "heartbeat requires lease_id")]
    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "record_heartbeat", f"unknown lease: {lease_id}")]
    if projection["run_state"] != "active":
        return [_command_rejected(make_event, "record_heartbeat", "run_not_active")]
    if lease.get("state") != "active":
        return [
            _command_rejected(
                make_event,
                "record_heartbeat",
                f"lease_not_active:{lease.get('state')}",
            )
        ]

    node_id = lease.get("node_id")
    payload_node_id = payload.get("node_id")
    if isinstance(payload_node_id, str) and payload_node_id != node_id:
        return [_command_rejected(make_event, "record_heartbeat", "node_id_mismatch")]
    if not isinstance(node_id, str):
        return [_command_rejected(make_event, "record_heartbeat", "lease_missing_node_id")]

    expected_generation = payload.get("generation")
    lease_generation = lease.get("generation")
    if (
        isinstance(expected_generation, int)
        and not isinstance(expected_generation, bool)
        and isinstance(lease_generation, int)
        and expected_generation != lease_generation
    ):
        return [_command_rejected(make_event, "record_heartbeat", "lease_generation_mismatch")]

    ttl_seconds = _positive_int(payload.get("ttl_seconds"), 300)
    expires_at = (clock.now() + timedelta(seconds=ttl_seconds)).isoformat()
    heartbeat_payload: dict[str, Any] = {
        "lease_id": lease_id,
        "node_id": node_id,
        "observed_at": clock.now().isoformat(),
        "expires_at": expires_at,
    }
    if isinstance(lease_generation, int) and not isinstance(lease_generation, bool):
        heartbeat_payload["generation"] = lease_generation
    execution_id = lease.get("execution_id")
    if isinstance(execution_id, str):
        heartbeat_payload["execution_id"] = execution_id
    return [
        make_event("heartbeat_recorded", heartbeat_payload),
        make_event("lease_renewed", heartbeat_payload),
    ]


def _cancel_active_lease_events(
    projection: GraphProjection,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    trigger: Any,
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for lease_id, lease in sorted(projection["leases"].items()):
        if lease.get("state") not in {"active", "suspended"}:
            continue
        node_id = lease.get("node_id")
        if not isinstance(node_id, str):
            continue
        revoke_payload: dict[str, Any] = {
            "node_id": node_id,
            "lease_id": lease_id,
            "trigger": trigger,
            "reason": "run_cancelled",
        }
        generation = lease.get("generation")
        if isinstance(generation, int) and not isinstance(generation, bool):
            revoke_payload["generation"] = generation
        execution_id = lease.get("execution_id")
        if isinstance(execution_id, str):
            revoke_payload["execution_id"] = execution_id
        output.append(make_event("lease_revoked", revoke_payload))

        node_state = projection["node_states"].get(node_id)
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
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    node_id = payload.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        return [_command_rejected(make_event, "evaluate_final_gate", "missing node_id")]
    if projection["node_kinds"].get(node_id) != "final_gate":
        return [_command_rejected(make_event, "evaluate_final_gate", "node is not a final_gate")]

    blockers = final_invariant_blockers_for_events(
        events,
        projection,
        include_completion_decision=False,
    )
    status = "blocked" if blockers else "passed"
    record_id = payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = id_gen.next_id("completion-decision")
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
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    node_id = payload.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        return [_command_rejected(make_event, "evaluate_join", "missing node_id")]
    if projection["node_kinds"].get(node_id) != "join":
        return [_command_rejected(make_event, "evaluate_join", "node is not a join")]

    source_record_ids = _join_source_record_ids(projection, node_id)
    if not source_record_ids:
        return [_command_rejected(make_event, "evaluate_join", "join has no bound source records")]
    record_id = payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = id_gen.next_id("join-result")
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
    bindings = projection["input_bindings"].get(node_id, {})
    output: list[str] = []
    for _, binding in sorted(bindings.items()):
        record_ids = binding.get("record_ids")
        if not isinstance(record_ids, list):
            continue
        for record_id in cast(list[Any], record_ids):
            if isinstance(record_id, str) and record_id not in output:
                output.append(record_id)
    return output


def _maybe_release_lease(
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    node_id: str,
) -> list[EventEnvelope]:
    lease_id = payload.get("lease_id")
    generation = payload.get("lease_generation")
    if not isinstance(lease_id, str) or not isinstance(generation, int):
        return []
    return [
        make_event(
            "lease_released",
            {
                "node_id": node_id,
                "lease_id": lease_id,
                "generation": generation,
            },
        )
    ]


def _release_active_node_leases(
    projection: GraphProjection,
    node_id: str,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for lease_id, lease in sorted(projection["leases"].items()):
        if lease.get("node_id") != node_id or lease.get("state") not in {"active", "suspended"}:
            continue
        payload: dict[str, Any] = {
            "node_id": node_id,
            "lease_id": lease_id,
        }
        generation = lease.get("generation")
        if isinstance(generation, int) and not isinstance(generation, bool):
            payload["generation"] = generation
        output.append(make_event("lease_released", payload))
    return output


def _apply_seed_compiled_events(
    projection: GraphProjection,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    if projection["node_states"] or projection["edges"] or projection["input_bindings"]:
        return [
            _command_rejected(make_event, "seed_compiled_events", "run topology already seeded")
        ]

    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        return [_command_rejected(make_event, "seed_compiled_events", "missing compiled events")]

    run_id = str(payload.get("run_id", ""))
    compiled_events: list[EventEnvelope] = []
    try:
        for raw_event in cast(list[Any], raw_events):
            event = (
                raw_event
                if isinstance(raw_event, EventEnvelope)
                else EventEnvelope.model_validate(raw_event)
            )
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
            compiled_events.append(event)
    except (TypeError, ValueError) as exc:
        return [_command_rejected(make_event, "seed_compiled_events", f"malformed event: {exc}")]

    return compiled_events


def _apply_callback_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    required = [
        "run_id",
        "node_id",
        "execution_id",
        "lease_id",
        "lease_generation",
        "base_snapshot_id",
        "observed_graph_position",
        "idempotency_key",
    ]
    missing = [field for field in required if field not in payload]
    if missing:
        return [
            _command_rejected(
                make_event,
                "submit_callback",
                f"missing callback fields: {', '.join(missing)}",
            )
        ]

    callback_payload = _callback_payload(payload)
    # Mutating-ness is derived from the callback's actual effects, never trusted
    # from the caller's flag: completing the node or carrying output records IS
    # a mutation, so a callback claiming is_mutating=False cannot bypass the
    # running-state and suspended-lease guards.
    has_effects = bool(payload.get("complete_node", True)) or bool(
        (callback_payload or {}).get("output_records")
    )
    request = CallbackRequest(
        run_id=str(payload["run_id"]),
        node_id=str(payload["node_id"]),
        execution_id=str(payload["execution_id"]),
        lease_id=str(payload["lease_id"]),
        lease_generation=int(payload["lease_generation"]),
        base_snapshot_id=str(payload["base_snapshot_id"]),
        observed_graph_position=int(payload["observed_graph_position"]),
        idempotency_key=str(payload["idempotency_key"]),
        payload=callback_payload,
        is_mutating=bool(payload.get("is_mutating", True)) or has_effects,
    )
    result = validate_callback(request, projection, events)

    event_payload = {
        "node_id": request.node_id,
        "lease_id": request.lease_id,
        "lease_generation": request.lease_generation,
        "idempotency_key": request.idempotency_key,
        "payload": request.payload,
        "reason": result.reason,
    }
    if result.outcome == CallbackOutcome.REJECTED_STALE:
        return [make_event("callback_rejected_stale", event_payload)]
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
        successful_completion=(
            bool(payload.get("complete_node", True))
            and str(payload.get("new_state", "completed")) == "completed"
        ),
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
    if payload.get("complete_node", True):
        output.append(
            make_event(
                "node_state_changed",
                {
                    "node_id": request.node_id,
                    "new_state": str(payload.get("new_state", "completed")),
                    "trigger": "callback_accepted",
                },
            )
        )
        output.append(
            make_event(
                "lease_released",
                {
                    "node_id": request.node_id,
                    "lease_id": request.lease_id,
                    "generation": request.lease_generation,
                },
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
    return output


def _lease_node_id(projection: GraphProjection, lease_id: str) -> str | None:
    lease = projection["leases"].get(lease_id)
    if lease is None:
        return None
    node_id = lease.get("node_id")
    return node_id if isinstance(node_id, str) else None


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
    lease = projection["leases"].get(request.lease_id)
    if lease is None:
        return None
    node_id = _lease_node_id(projection, request.lease_id) or request.node_id
    if projection["node_kinds"].get(node_id) != "worker":
        return None
    raw_claims = lease.get("resource_claims", [])
    if not isinstance(raw_claims, list):
        raw_claims = []
    write_claims: list[ResourceClaim] = []
    for raw_claim in cast(list[Any], raw_claims):
        if isinstance(raw_claim, dict):
            write_claims.append(_claim_from_dict(cast(dict[str, Any], raw_claim)))
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
    payload.setdefault("node_id", request.node_id)
    payload.setdefault("lease_id", request.lease_id)
    payload.setdefault("lease_generation", request.lease_generation)
    payload.setdefault("base_snapshot_id", request.base_snapshot_id)
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
    node_kind = projection["node_kinds"].get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = projection["node_roles"].get(expected_producer_node_id)
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
                return f"candidate record at index {index} is invalid: {exc}"
        if _is_check_result_record_payload(record_payload):
            try:
                CheckResultRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"check_result record at index {index} is invalid: {exc}"
        if _is_analysis_summary_record_payload(record_payload):
            record_payload = _analysis_summary_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                AnalysisSummaryRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"analysis_summary record at index {index} is invalid: {exc}"
        if _is_graph_patch_proposal_record_payload(record_payload):
            record_payload = _graph_patch_proposal_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                GraphPatchProposalRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"graph_patch_proposal record at index {index} is invalid: {exc}"
        if _is_artifact_reference_record_payload(record_payload):
            record_payload = _artifact_reference_record_payload_for_validation(
                record_payload,
                expected_producer_node_id,
            )
            try:
                ArtifactReferenceRecord.model_validate(record_payload)
            except ValueError as exc:
                return f"artifact_reference record at index {index} is invalid: {exc}"
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
    output: list[EventEnvelope] = []
    for raw_record in typed_raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        record_payload.setdefault("producer_node_id", expected_producer_node_id)
        if record_payload.get("record_kind") == "file_state":
            record_payload.setdefault("port", "file_state")
            record_payload.setdefault("record_type", "file_state")
        if record_payload.get("record_kind") == "verification":
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
    try:
        record = FileStateRecord.model_validate(record_payload)
    except ValueError:
        return []
    payload = record.model_dump(mode="json")
    output = [
        make_event("output_record_accepted", payload),
        make_event("file_state_accepted", payload),
    ]
    output.extend(
        _input_bound_events_for_record(
            projection,
            record.producer_node_id or expected_producer_node_id,
            record.port,
            record.record_id,
            payload,
            make_event,
            aliases={"accepted_file_state", "file_state"},
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
        if record_payload.get("record_kind") != "verification":
            continue
        if projection["node_kinds"].get(expected_producer_node_id) != "verifier":
            return f"verification record at index {index} was not produced by a verifier"
        candidate_id = _candidate_id_from_payload(record_payload)
        if candidate_id is None:
            return f"verification record at index {index} missing candidate_id"
        if not _candidate_is_bound_to_verifier(projection, expected_producer_node_id, candidate_id):
            return (
                f"verification record candidate_id at index {index} is not bound "
                f"to verifier input: {candidate_id}"
            )
        verdict = record_payload.get("verdict")
        if verdict not in {"passed", "failed", "pass", "fail"}:
            return f"verification record at index {index} has invalid verdict: {verdict}"
        grades = _verification_grades(record_payload)
        if not grades:
            return f"verification record at index {index} missing grades"
        citation_conflict = _evaluated_record_citation_conflict(
            projection,
            expected_producer_node_id,
            record_payload,
            index,
        )
        if citation_conflict is not None:
            return citation_conflict
    return None


def _verification_grades(record_payload: dict[str, Any]) -> list[Any]:
    grades = record_payload.get("grades")
    if isinstance(grades, list):
        return list(cast(list[Any], grades))
    value = record_payload.get("value")
    if isinstance(value, dict):
        value_grades = cast(dict[str, Any], value).get("grades")
        if isinstance(value_grades, list):
            return list(cast(list[Any], value_grades))
    return []


def _required_output_record_conflict(
    projection: GraphProjection,
    request: CallbackRequest,
    expected_producer_node_id: str,
    *,
    successful_completion: bool,
) -> str | None:
    if not successful_completion:
        return None

    node_kind = projection["node_kinds"].get(expected_producer_node_id)
    if not isinstance(node_kind, str):
        return f"output records produced by unknown node: {expected_producer_node_id}"
    node_role = projection["node_roles"].get(expected_producer_node_id)
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
    if port == "verification_result":
        return "verification_report"
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

    record_payload.setdefault("port", "verification_report")
    _canonicalize_verification_record_port(record_payload)
    _add_evaluated_record_citations(record_payload, projection, expected_producer_node_id)
    try:
        record = VerificationReportRecord.model_validate(record_payload)
    except ValueError:
        return []
    payload = record.model_dump(mode="json")
    verdict = record.verdict
    event_type = "verification_passed" if verdict in {"passed", "pass"} else "verification_failed"
    task_region_id = projection["node_task_regions"].get(expected_producer_node_id)
    event_payload = {
        "node_id": request.node_id,
        "verifier_node_id": expected_producer_node_id,
        "candidate_id": candidate_id,
        "verdict": "passed" if event_type == "verification_passed" else "failed",
        "record_id": record.record_id,
        "evidence": payload.get("evidence"),
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
            aliases={"verification_result"},
        )
    )
    return output


def _canonicalize_verification_record_port(record_payload: dict[str, Any]) -> None:
    if record_payload.get("port") == "verification_result":
        record_payload["port"] = "verification_report"


def _candidate_is_bound_to_verifier(
    projection: GraphProjection,
    verifier_node_id: str,
    candidate_id: str,
) -> bool:
    binding = projection["input_bindings"].get(verifier_node_id, {}).get("candidate_under_test")
    if binding is None:
        return False
    record_ids = binding.get("record_ids")
    return isinstance(record_ids, list) and candidate_id in record_ids


def _candidate_id_from_payload(payload: dict[str, Any]) -> str | None:
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
    if record_payload.get("record_kind") == "verification":
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
    for candidates in projection["task_candidates"].values():
        for candidate in candidates:
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or candidate_id not in wanted:
                continue
            file_state_record_ids = candidate.get("file_state_record_ids")
            if isinstance(file_state_record_ids, list):
                output.extend(
                    record_id
                    for record_id in cast(list[Any], file_state_record_ids)
                    if isinstance(record_id, str)
                )
    if output:
        return _unique_record_ids(output)
    for record in projection["file_state_records"].values():
        candidate_id = _candidate_id_from_payload(record)
        if candidate_id in wanted:
            record_id = record.get("record_id")
            if isinstance(record_id, str):
                output.append(record_id)
    return _unique_record_ids(output)


def _bound_record_ids_for_ports(
    projection: GraphProjection,
    node_id: str,
    ports: tuple[str, ...],
) -> list[str]:
    bindings = projection["input_bindings"].get(node_id, {})
    output: list[str] = []
    for port in ports:
        binding = bindings.get(port)
        if binding is None:
            continue
        record_ids = binding.get("record_ids")
        if not isinstance(record_ids, list):
            continue
        output.extend(
            record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)
        )
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
    aliases: set[str] | None = None,
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    # Output records are facts produced by the leased node. Edges are the only
    # authority for routing those facts into downstream required inputs.
    for edge in projection["edges"].values():
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        if edge.get("from_node_id") != producer_node_id:
            continue
        if edge.get("from_port") != port:
            continue
        if not _record_matches_selector(
            edge.get("accepted_record_selector"), record_payload, aliases
        ):
            continue
        edge_id = edge.get("edge_id")
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not isinstance(edge_id, str) or not isinstance(to_node_id, str):
            continue
        if not isinstance(to_port, str):
            continue
        binding_payload = _input_bound_payload_for_record(
            projection,
            edge,
            edge_id=edge_id,
            to_node_id=to_node_id,
            to_port=to_port,
            record_id=record_id,
            record_payload=record_payload,
        )
        if binding_payload is None:
            continue
        output.append(
            make_event(
                "input_bound",
                binding_payload,
            )
        )
    return output


def _input_bound_payload_for_record(
    projection: GraphProjection,
    edge: dict[str, Any],
    *,
    edge_id: str,
    to_node_id: str,
    to_port: str,
    record_id: str,
    record_payload: dict[str, Any],
) -> dict[str, Any] | None:
    existing_ids = _existing_bound_record_ids(projection, to_node_id, to_port)
    target_port = _target_port_contract_for_edge(projection, edge)
    policy = binding_policy_for_edge(edge, target_port)
    next_ids = merge_bound_record_ids(
        policy,
        existing_ids,
        [record_id],
        supersedes_record_id=record_payload.get("supersedes_record_id"),
    )
    if next_ids == existing_ids and existing_ids:
        return None

    payload: dict[str, Any] = {
        "edge_id": edge_id,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "record_ids": next_ids,
        "bound_at_position": 0,
    }
    if policy != "bind_first" or isinstance(edge.get("binding_policy"), str):
        payload["binding_policy"] = policy
    supersedes_record_id = record_payload.get("supersedes_record_id")
    if isinstance(supersedes_record_id, str):
        payload["supersedes_record_id"] = supersedes_record_id
    return payload


def _existing_bound_record_ids(
    projection: GraphProjection,
    to_node_id: str,
    to_port: str,
) -> list[str]:
    binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
    if binding is None:
        return []
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return [record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)]


def _target_port_contract_for_edge(
    projection: GraphProjection,
    edge: dict[str, Any],
) -> PortContract | None:
    to_node_id = edge.get("to_node_id")
    to_port = edge.get("to_port")
    if not isinstance(to_node_id, str) or not isinstance(to_port, str):
        return None
    target_kind = projection["node_kinds"].get(to_node_id)
    if target_kind is None:
        return None
    target_role = projection["node_roles"].get(to_node_id)
    target_contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if target_contract is None:
        return None
    return input_port_contract(target_contract, to_port)


def _record_matches_selector(
    selector: Any,
    record_payload: dict[str, Any],
    aliases: set[str] | None,
) -> bool:
    if not isinstance(selector, dict):
        return True
    typed_selector = cast(dict[str, Any], selector)
    raw_kinds = typed_selector.get("record_kinds")
    if not isinstance(raw_kinds, list):
        return True
    accepted = {kind for kind in cast(list[Any], raw_kinds) if isinstance(kind, str)}
    if not accepted:
        return True
    candidates = {
        value
        for value in (
            record_payload.get("record_kind"),
            record_payload.get("record_type"),
            record_payload.get("schema"),
            record_payload.get("port"),
            record_payload.get("milestone_kind"),
        )
        if isinstance(value, str)
    }
    value = record_payload.get("value")
    if isinstance(value, dict):
        milestone_kind = cast(dict[str, Any], value).get("milestone_kind")
        if isinstance(milestone_kind, str):
            candidates.add(milestone_kind)
    candidates.update(aliases or set())
    return bool(accepted & candidates)


def _apply_patch_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    actor_role = str(payload.get("actor_role", "planner"))
    run_state = projection["run_state"]
    if run_state is not None and run_state != "active":
        return [
            _command_rejected(
                make_event,
                "submit_patch",
                f"run_not_active:{run_state or 'unknown'}",
            )
        ]
    try:
        payload = expand_patch_macros(payload)
        patch = PatchEnvelope(
            patch_id=str(payload["patch_id"]),
            proposed_by_node_id=str(payload.get("proposed_by_node_id", "controller")),
            base_graph_position=int(payload.get("base_graph_position", -1)),
            ops=[PatchOp(**op) for op in cast(list[dict[str, Any]], payload.get("ops", []))],
            rationale_record_id=cast(str | None, payload.get("rationale_record_id")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return [
            make_event(
                "command_rejected",
                {
                    "command_type": "submit_patch",
                    "reason": f"malformed patch: {exc}",
                    "patch_id": payload.get("patch_id"),
                    "base_graph_position": payload.get("base_graph_position"),
                    "actor_role": actor_role,
                    "proposed_by_node_id": payload.get("proposed_by_node_id"),
                },
            )
        ]

    current_position = _current_position(events)
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
            gate_node_id = str(
                payload.get(
                    "budget_gate_node_id",
                    f"gate-planner-budget-{patch.proposed_by_node_id}",
                )
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
                make_event(
                    "node_created",
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

    parent_session_id = projection["planner_sessions"].get(patch.proposed_by_node_id)
    carryover_record_id = _carryover_record_id(payload)
    output = [
        make_event(
            "graph_patch_accepted",
            {
                "patch_id": patch.patch_id,
                "base_graph_position": patch.base_graph_position,
                "actor_role": actor_role,
                "proposed_by_node_id": patch.proposed_by_node_id,
                "successor_planner_node_ids": successor_planner_node_ids,
                "session_id": parent_session_id,
                "carryover_record_id": carryover_record_id,
            },
        )
    ]
    for op in patch.ops:
        output.extend(
            _patch_op_events(
                op,
                events,
                make_event,
                inherited_session_id=parent_session_id,
                carryover_record_id=carryover_record_id,
            )
        )
    if carryover_record_id is not None and successor_planner_node_ids:
        output.append(
            make_event(
                "input_bound",
                {
                    "edge_id": f"edge-session-carryover-{successor_planner_node_ids[0]}",
                    "to_node_id": successor_planner_node_ids[0],
                    "to_port": "session_carryover",
                    "record_ids": [carryover_record_id],
                    "bound_at_position": 0,
                },
            )
        )
    return output


def _patch_rejected_payload(
    patch: PatchEnvelope,
    actor_role: str,
    *,
    reason: str | None,
    read_set_diff: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "patch_id": patch.patch_id,
        "base_graph_position": patch.base_graph_position,
        "actor_role": actor_role,
        "proposed_by_node_id": patch.proposed_by_node_id,
        "reason": reason,
        "read_set_diff": read_set_diff,
    }


def _request_record_validation_error(patch: PatchEnvelope) -> str | None:
    for op in patch.ops:
        if op.op != "create_node" or not isinstance(op.node, dict):
            continue
        try:
            _request_record_bindings_for_node(dict(op.node))
        except ValueError as exc:
            return f"invalid request record for node {op.node.get('node_id')}: {exc}"
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


def _carryover_record_id(payload: dict[str, Any]) -> str | None:
    for key in ("carryover_summary", "carryover_record_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _planner_budget_rejection(
    projection: GraphProjection,
    patch: PatchEnvelope,
) -> dict[str, int] | None:
    parent_generation = projection["planner_generations"].get(patch.proposed_by_node_id, 0)
    attempted_generation = parent_generation + 1
    budget = projection["planner_generation_budget"]
    if attempted_generation <= budget:
        return None
    return {"budget": budget, "count": attempted_generation}


def _apply_schedule_tick(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output = _expired_lease_events(projection, clock.now(), make_event)
    expired_lease_ids = _expired_active_lease_ids(projection, clock.now())
    active_claims = [
        _claim_from_dict(claim)
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        and isinstance(lease.get("lease_id"), str)
        and lease.get("lease_id") not in expired_lease_ids
        for claim in cast(list[dict[str, Any]], lease.get("resource_claims", []))
    ]
    active_lease_node_ids = [
        str(lease["node_id"])
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        and isinstance(lease.get("lease_id"), str)
        and lease.get("lease_id") not in expired_lease_ids
        and isinstance(lease.get("node_id"), str)
    ]
    nodes: list[NodeScheduleInfo] = []
    readied_node_ids: set[str] = set()
    for node_id, node_state in projection["node_states"].items():
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        node = _node_schedule_info(projection, payload, node_id)
        backoff_reason = _retry_backoff_deferred_reason(events, node_id, clock.now())
        if backoff_reason is not None:
            output.append(
                make_event(
                    "node_deferred",
                    {
                        "node_id": node_id,
                        "reason": backoff_reason,
                    },
                )
            )
            continue
        if node_state == "ready":
            nodes.append(node)
            continue
        ready, reason = evaluate_readiness(
            node,
            projection["run_state"] or "draft",
            active_lease_node_ids,
            active_claims,
        )
        if not ready:
            output.append(
                make_event(
                    "node_deferred",
                    {
                        "node_id": node_id,
                        "reason": reason,
                    },
                )
            )
            continue
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
        projection["run_state"] or "draft",
        active_claims,
        _current_position(events),
        max_grants=int(payload.get("max_grants", 10)),
    )
    lease_seconds = int(payload.get("lease_seconds", 300))
    for node_id in decision.selected:
        claims = projection["node_resource_claims"].get(node_id, [])
        lease_id = (
            str(payload.get("lease_ids", {}).get(node_id))
            if isinstance(payload.get("lease_ids"), dict) and node_id in payload["lease_ids"]
            else id_gen.next_id("lease")
        )
        base_snapshot_id = _base_snapshot_id_for_node(projection, payload, node_id)
        if base_snapshot_id is None:
            output.append(
                make_event(
                    "node_deferred",
                    {"node_id": node_id, "reason": "missing_base_snapshot"},
                )
            )
            continue
        if node_id not in readied_node_ids:
            output.append(make_event("node_ready", {"node_id": node_id}))
        planner_session_id = _planner_session_id(projection, node_id, id_gen)
        lease_generation = _next_lease_generation(projection, node_id)
        lease_payload: dict[str, Any] = {
            "lease_id": lease_id,
            "node_id": node_id,
            "generation": lease_generation,
            "execution_id": id_gen.next_id("exec"),
            "base_snapshot_id": base_snapshot_id,
            "expires_at": (clock.now() + timedelta(seconds=lease_seconds)).isoformat(),
            "resource_claims": claims,
        }
        if planner_session_id is not None:
            lease_payload["session_id"] = planner_session_id
        output.append(
            make_event(
                "lease_granted",
                lease_payload,
            )
        )
        if planner_session_id is not None:
            output.append(
                make_event(
                    "session_state_changed",
                    {
                        "session_id": planner_session_id,
                        "state": "attached",
                        "node_id": node_id,
                        "lease_generation": lease_generation,
                        "carryover_record_id": _session_carryover_record_id(projection, node_id),
                    },
                )
            )
        output.append(
            make_event(
                "node_state_changed",
                {"node_id": node_id, "new_state": "leased", "trigger": "scheduler_grants_lease"},
            )
        )
    for node_id in decision.deferred:
        output.append(
            make_event(
                "node_deferred",
                {
                    "node_id": node_id,
                    "reason": decision.deferred_reasons[node_id],
                },
            )
        )
    return output


def _base_snapshot_id_for_node(
    projection: GraphProjection,
    payload: dict[str, Any],
    node_id: str,
) -> str | None:
    """Resolve a node's base snapshot from command override or input bindings.

    Returns None when no snapshot identity exists — the scheduler defers the
    node rather than fabricating an identity (PRD §19: every lease carries a
    real base snapshot).
    """
    override = payload.get("base_snapshot_id")
    if isinstance(override, str) and override:
        return override

    bindings = projection["input_bindings"].get(node_id, {})
    for port in ("base_snapshot", "root_snapshot", "routine_snapshot"):
        record_ids = bindings.get(port, {}).get("record_ids")
        if isinstance(record_ids, list) and record_ids:
            first_record_id = cast(list[Any], record_ids)[0]
            if isinstance(first_record_id, str) and first_record_id:
                return first_record_id
    return None


def _retry_backoff_deferred_reason(
    events: list[EventEnvelope],
    node_id: str,
    now: datetime,
) -> str | None:
    retry_not_before: str | None = None
    for event in events:
        if event.event_type != "runtime_retry_scheduled":
            continue
        if event.payload.get("node_id") != node_id:
            continue
        value = event.payload.get("retry_not_before")
        retry_not_before = value if isinstance(value, str) and value else None
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
    session_id = projection["planner_sessions"].get(node_id)
    if isinstance(session_id, str):
        return session_id
    return id_gen.next_id("session")


def _next_lease_generation(projection: GraphProjection, node_id: str) -> int:
    if not _is_chain_planner(projection, node_id):
        return 1
    session_id = projection["planner_sessions"].get(node_id)
    generations = [
        lease.get("generation")
        for lease in projection["leases"].values()
        if session_id is not None
        and lease.get("session_id") == session_id
        and isinstance(lease.get("generation"), int)
    ]
    return max(cast(list[int], generations), default=0) + 1


def _session_carryover_record_id(projection: GraphProjection, node_id: str) -> str | None:
    binding = projection["input_bindings"].get(node_id, {}).get("session_carryover")
    if binding is None:
        return None
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list) or not record_ids:
        return None
    record_id = cast(list[Any], record_ids)[0]
    return record_id if isinstance(record_id, str) else None


def _planner_session_state_event(
    projection: GraphProjection,
    node_id: str,
    state: str,
    lease_generation: int,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> EventEnvelope | None:
    if not _is_chain_planner(projection, node_id):
        return None
    session_id = projection["planner_sessions"].get(node_id)
    if not isinstance(session_id, str):
        return None
    return make_event(
        "session_state_changed",
        {
            "session_id": session_id,
            "state": state,
            "node_id": node_id,
            "lease_generation": lease_generation,
            "carryover_record_id": _session_carryover_record_id(projection, node_id),
        },
    )


def _is_chain_planner(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "planner"
        and projection["node_roles"].get(node_id) == "planner"
    )


def _apply_acknowledge_start(
    projection: GraphProjection,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    node_id = payload.get("node_id")
    lease_id = payload.get("lease_id")
    lease_generation = payload.get("lease_generation")
    execution_id = payload.get("execution_id")
    if not isinstance(node_id, str) or not isinstance(lease_id, str):
        return [_command_rejected(make_event, "acknowledge_start", "missing lease identity")]
    if not isinstance(lease_generation, int):
        return [_command_rejected(make_event, "acknowledge_start", "missing lease generation")]
    if not isinstance(execution_id, str):
        return [_command_rejected(make_event, "acknowledge_start", "missing execution_id")]

    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "acknowledge_start", "unknown lease")]
    if lease.get("state") != "active":
        return [_command_rejected(make_event, "acknowledge_start", "lease not active")]
    if lease.get("node_id") != node_id:
        return [_command_rejected(make_event, "acknowledge_start", "node_incompatible")]
    if lease.get("generation") != lease_generation:
        return [_command_rejected(make_event, "acknowledge_start", "generation_incompatible")]
    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str) and lease_execution_id != execution_id:
        return [_command_rejected(make_event, "acknowledge_start", "execution_incompatible")]

    return [
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "running",
                "trigger": "runtime_start_acknowledged",
            },
        )
    ]


def _apply_agent_died(
    projection: GraphProjection,
    payload: dict[str, Any],
    clock: Clock,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    lease_id = payload.get("lease_id")
    if not isinstance(lease_id, str):
        return [_command_rejected(make_event, "agent_died", "missing lease_id")]

    lease = projection["leases"].get(lease_id)
    if lease is None:
        return [_command_rejected(make_event, "agent_died", "unknown lease")]
    if lease.get("state") != "active":
        return [_command_rejected(make_event, "agent_died", "lease not active")]

    execution_id = payload.get("execution_id")
    lease_execution_id = lease.get("execution_id")
    if isinstance(lease_execution_id, str):
        # A lease with a recorded execution requires the caller to present the
        # matching execution identity — omitting it cannot revoke the lease.
        if not isinstance(execution_id, str):
            return [_command_rejected(make_event, "agent_died", "missing execution_id")]
        if execution_id != lease_execution_id:
            return [_command_rejected(make_event, "agent_died", "execution_incompatible")]

    node_id = str(lease.get("node_id"))
    generation = lease.get("generation")
    reason = str(payload.get("reason", "runtime_process_died"))
    event_payload = {
        "lease_id": lease_id,
        "node_id": node_id,
        "generation": generation,
        "execution_id": lease_execution_id if isinstance(lease_execution_id, str) else execution_id,
        "reason": reason,
    }

    if _non_gap_planner_has_accepted_patch(projection, node_id):
        return [
            make_event("agent_died", event_payload),
            make_event(
                "lease_revoked",
                {
                    "lease_id": lease_id,
                    "node_id": node_id,
                    "generation": generation,
                    "reason": reason,
                },
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
                {
                    "lease_id": lease_id,
                    "node_id": node_id,
                    "generation": generation,
                    "reason": reason,
                },
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
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

    max_attempts = _positive_int(payload.get("max_attempts"), 0)
    attempt_number = projection["node_attempts"].get(node_id, 0)
    if max_attempts > 0 and attempt_number >= max_attempts:
        return [
            make_event("agent_died", event_payload),
            make_event(
                "lease_revoked",
                {
                    "lease_id": lease_id,
                    "node_id": node_id,
                    "generation": generation,
                    "reason": reason,
                },
            ),
            make_event(
                "output_record_accepted",
                _failure_record_payload(
                    node_id=node_id,
                    phase="runtime",
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
    retry_backoff_seconds = _positive_int(payload.get("retry_backoff_seconds"), 0)
    retry_payload: dict[str, Any] = {
        "node_id": node_id,
        "lease_id": lease_id,
        "generation": generation,
        "policy": "v1_requeue_same_node_after_agent_death",
        "reason": reason,
    }
    node_state_payload = {
        "node_id": node_id,
        "new_state": "ready",
        "trigger": "agent_died_retry_scheduled",
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
        }
    return [
        make_event("agent_died", event_payload),
        make_event(
            "lease_revoked",
            {
                "lease_id": lease_id,
                "node_id": node_id,
                "generation": generation,
                "reason": reason,
            },
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


def _non_gap_planner_has_accepted_patch(projection: GraphProjection, node_id: str) -> bool:
    return (
        projection["node_kinds"].get(node_id) == "planner"
        and projection["node_roles"].get(node_id) != "gap_planner"
        and bool(projection.get("accepted_graph_patches_by_node", {}).get(node_id))
    )


def _is_rate_limit_death(reason: str) -> bool:
    normalized = reason.lower()
    return "rate limit" in normalized or "hit rate limit" in normalized


def _apply_raise_appeal(
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    node_id = payload.get("node_id")
    appeal_type = payload.get("appeal_type")
    if not isinstance(node_id, str) or appeal_type != "invalid_test":
        return [_command_rejected(make_event, "raise_appeal", "malformed appeal")]

    oversight_node_id = str(payload.get("oversight_node_id", id_gen.next_id("oversight")))
    return [
        make_event(
            "appeal_opened",
            {
                "node_id": str(payload.get("appeal_node_id", id_gen.next_id("appeal"))),
                "appealed_node_id": node_id,
                "candidate_id": payload.get("candidate_id"),
                "task_region_id": payload.get("task_region_id"),
                "appeal_type": appeal_type,
                "lease_id": payload.get("lease_id"),
            },
        ),
        make_event(
            "node_created",
            {
                "node_id": oversight_node_id,
                "kind": "oversight",
                "state": "planned",
                "task_region_id": payload.get("task_region_id"),
            },
        ),
    ]


def _apply_record_decision(
    projection: GraphProjection,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    decision_type = payload.get("decision_type")
    if decision_type not in {"approval", "oversight", "authority"}:
        return [_command_rejected(make_event, "record_decision", "unknown decision_type")]

    node_id = payload.get("node_id")
    if not isinstance(node_id, str):
        return [_command_rejected(make_event, "record_decision", "missing target node_id")]
    if not _node_exists(projection, node_id):
        return [_command_rejected(make_event, "record_decision", f"unknown target node: {node_id}")]

    node_kind = projection["node_kinds"].get(node_id)
    if decision_type == "authority" and node_kind != "authority_request":
        return [
            _command_rejected(
                make_event,
                "record_decision",
                "authority decisions require authority_request target",
            )
        ]

    node_state = projection["node_states"].get(node_id)
    if node_state in {"completed", "failed", "cancelled", "retired"}:
        return [
            _command_rejected(make_event, "record_decision", f"terminal target node: {node_state}")
        ]

    run_state = projection["run_state"]
    if run_state in {"cancelled", "failed"}:
        return [_command_rejected(make_event, "record_decision", f"terminal run: {run_state}")]

    decider = payload.get("decider") or payload.get("decider_actor")
    if not _valid_decider(decider):
        return [_command_rejected(make_event, "record_decision", "missing decider actor")]

    decision = _decision_value(decision_type, payload)
    if decision is None:
        return [_command_rejected(make_event, "record_decision", "invalid decision value")]

    event_payload = dict(payload)
    event_payload["decision"] = decision
    event_payload.setdefault("decider", decider)
    task_region_id = projection["node_task_regions"].get(node_id)
    if task_region_id is not None:
        event_payload.setdefault("task_region_id", task_region_id)

    if decision_type == "approval":
        event_type = "approval_decision_recorded"
    elif decision_type == "authority":
        event_type = "authority_decision_recorded"
    else:
        event_type = "oversight_decision_recorded"
    try:
        decision_record = _decision_output_record(projection, node_id, event_payload, decision_type)
    except ValueError as exc:
        return [_command_rejected(make_event, "record_decision", f"invalid decision record: {exc}")]
    output = [make_event(event_type, event_payload)]
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
                _record_selector_aliases(decision_record),
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
    node_kind = projection["node_kinds"].get(node_id)
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
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    record_id = payload.get("file_state_record_id")
    if not isinstance(record_id, str) or not record_id:
        return [_command_rejected(make_event, "record_gatekeeper_verdicts", "missing record id")]

    record = projection["file_state_records"].get(record_id)
    if record is None:
        return [
            _command_rejected(
                make_event,
                "record_gatekeeper_verdicts",
                f"unknown file_state record: {record_id}",
            )
        ]

    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        return [
            _command_rejected(
                make_event,
                "record_gatekeeper_verdicts",
                "missing execution_id",
            )
        ]

    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list) or not raw_verdicts:
        return [_command_rejected(make_event, "record_gatekeeper_verdicts", "missing verdicts")]

    unresolved_paths = {
        str(entry["path"])
        for entry in _record_residue(record)
        if isinstance(entry.get("path"), str) and entry.get("needs_gatekeeper") is True
    }
    accepted: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw_verdict in enumerate(cast(list[Any], raw_verdicts)):
        if not isinstance(raw_verdict, dict):
            return [
                _command_rejected(
                    make_event,
                    "record_gatekeeper_verdicts",
                    f"malformed verdict at index {index}",
                )
            ]
        verdict = dict(cast(dict[str, Any], raw_verdict))
        path = verdict.get("path")
        if not isinstance(path, str) or not path:
            return [
                _command_rejected(
                    make_event,
                    "record_gatekeeper_verdicts",
                    f"verdict at index {index} missing path",
                )
            ]
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
        classification = verdict.get("classification")
        if classification not in GATEKEEPER_TAXONOMY:
            valid = ", ".join(sorted(GATEKEEPER_TAXONOMY))
            return [
                _command_rejected(
                    make_event,
                    "record_gatekeeper_verdicts",
                    f"invalid classification for {path}: {classification}; valid: {valid}",
                )
            ]
        confidence = verdict.get("confidence", 0.0)
        if not isinstance(confidence, int | float) or confidence < 0 or confidence > 1:
            return [
                _command_rejected(
                    make_event,
                    "record_gatekeeper_verdicts",
                    f"invalid confidence for {path}",
                )
            ]
        accepted.append(
            {
                "path": path,
                "classification": classification,
                "confidence": float(confidence),
                "rationale": str(verdict.get("rationale", "")),
                "model_id": str(verdict.get("model_id", payload.get("model_id", "unknown"))),
                "input_tokens": _nonnegative_int(verdict.get("input_tokens", 0)),
                "output_tokens": _nonnegative_int(verdict.get("output_tokens", 0)),
                "cache_read_tokens": _nonnegative_int(verdict.get("cache_read_tokens", 0)),
                "cache_write_tokens": _nonnegative_int(verdict.get("cache_write_tokens", 0)),
                "cost_usd": _nonnegative_float(verdict.get("cost_usd", 0.0)),
                "wall_time_ms": _nonnegative_int(verdict.get("wall_time_ms", 0)),
            }
        )

    consult_id = str(payload.get("consult_id", "gatekeeper-consult"))
    cost_payload = _gatekeeper_cost_payload(record_id, execution_id, consult_id, accepted, payload)
    events = [
        make_event(
            "gatekeeper_verdict_recorded",
            {
                "file_state_record_id": record_id,
                "execution_id": execution_id,
                "producer_node_id": record.get("producer_node_id"),
                "verdicts": accepted,
                "resolved_count": len(accepted),
            },
        ),
    ]
    secret_paths = [
        str(verdict["path"]) for verdict in accepted if verdict.get("classification") == "secret"
    ]
    if secret_paths:
        cleanup_id = f"{record_id}:gatekeeper-secret"
        events.append(
            make_event(
                "cleanup_requested",
                {
                    "cleanup_id": cleanup_id,
                    "file_state_record_id": record_id,
                    "snapshot_id": record.get("snapshot_id"),
                    "paths": secret_paths,
                    "authority": "gatekeeper",
                    "reason": "gatekeeper_classified_secret_after_snapshot",
                    "execution_id": execution_id,
                    "producer_node_id": record.get("producer_node_id"),
                },
            )
        )
    events.append(make_event("gatekeeper_cost_recorded", cost_payload))
    return events


def _apply_record_cleanup_applied(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    cleanup_id = payload.get("cleanup_id")
    if not isinstance(cleanup_id, str) or not cleanup_id:
        return [_command_rejected(make_event, "record_cleanup_applied", "missing cleanup_id")]

    requested = _cleanup_requested_event(events, cleanup_id)
    if requested is None:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"unknown cleanup_requested: {cleanup_id}",
            )
        ]
    if _cleanup_applied_exists(events, cleanup_id):
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"cleanup already applied: {cleanup_id}",
            )
        ]

    record_id = requested.payload.get("file_state_record_id")
    if not isinstance(record_id, str) or record_id not in projection["file_state_records"]:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"unknown cleanup file_state record: {record_id}",
            )
        ]
    compromised_record = projection["file_state_records"][record_id]
    requested_snapshot_id = requested.payload.get("snapshot_id")
    compromised_snapshot_id = compromised_record.get("snapshot_id")
    if requested_snapshot_id != compromised_snapshot_id:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "cleanup snapshot_id does not match compromised record",
            )
        ]

    raw_record = payload.get("superseding_file_state_record")
    if not isinstance(raw_record, dict):
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "missing superseding file_state record",
            )
        ]
    record_payload = dict(cast(dict[str, Any], raw_record))
    record_payload.setdefault("supersedes_record_id", record_id)
    record_payload.setdefault("cleanup_id", cleanup_id)
    if record_payload.get("supersedes_record_id") != record_id:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "superseding record does not match cleanup target",
            )
        ]
    if record_payload.get("cleanup_id") != cleanup_id:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "superseding record cleanup_id does not match cleanup target",
            )
        ]
    if record_payload.get("snapshot_id") == compromised_snapshot_id:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                "superseding record must use a different snapshot_id",
            )
        ]
    secret_paths = _cleanup_secret_paths(requested.payload)
    retained_secret_path = _record_contains_any_path(record_payload, secret_paths)
    if retained_secret_path is not None:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"superseding record still contains cleanup secret path: {retained_secret_path}",
            )
        ]
    try:
        record = FileStateRecord.model_validate(record_payload)
    except ValueError as exc:
        return [
            _command_rejected(
                make_event,
                "record_cleanup_applied",
                f"invalid superseding file_state record: {exc}",
            )
        ]

    applied_payload = {
        "cleanup_id": cleanup_id,
        "file_state_record_id": record_id,
        "superseding_record_id": record.record_id,
        "old_snapshot_id": requested.payload.get("snapshot_id"),
        "new_snapshot_id": record.snapshot_id,
        "paths": requested.payload.get("paths", []),
        "authority": requested.payload.get("authority", "gatekeeper"),
        "reason": payload.get("reason", requested.payload.get("reason")),
        "execution_id": requested.payload.get("execution_id"),
        "deleted_snapshot_ref": payload.get("deleted_snapshot_ref") is True,
    }
    accepted_payload = record.model_dump(mode="json")
    return [
        make_event("cleanup_applied", applied_payload),
        make_event("output_record_accepted", accepted_payload),
        make_event("file_state_accepted", accepted_payload),
    ]


def _apply_record_requirement_revision(
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    requirement_id = payload.get("requirement_id")
    if not isinstance(requirement_id, str) or not requirement_id:
        return [
            _command_rejected(
                make_event,
                "record_requirement_revision",
                "missing requirement_id",
            )
        ]

    version_id = payload.get("version_id")
    if not isinstance(version_id, str) or not version_id:
        version_id = payload.get("requirement_version_id")
    if not isinstance(version_id, str) or not version_id:
        return [
            _command_rejected(
                make_event,
                "record_requirement_revision",
                "missing version_id",
            )
        ]

    event_payload = dict(payload)
    event_payload["requirement_id"] = requirement_id
    event_payload["version_id"] = version_id
    return [make_event("requirement_revision_recorded", event_payload)]


def _apply_record_support_evidence(
    projection: GraphProjection,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    support_id = payload.get("support_id")
    if not isinstance(support_id, str) or not support_id:
        return [_command_rejected(make_event, "record_support_evidence", "missing support_id")]

    evidence_id = payload.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id:
        return [_command_rejected(make_event, "record_support_evidence", "missing evidence_id")]

    requirement_id = payload.get("requirement_id")
    if not isinstance(requirement_id, str) or not requirement_id:
        return [
            _command_rejected(
                make_event,
                "record_support_evidence",
                "missing requirement_id",
            )
        ]

    requirement_version_id = payload.get("requirement_version_id")
    if not isinstance(requirement_version_id, str) or not requirement_version_id:
        requirement_version_id = payload.get("version_id")
    if not isinstance(requirement_version_id, str) or not requirement_version_id:
        requirement_version_id = projection["active_requirement_versions"].get(requirement_id)
    if not isinstance(requirement_version_id, str) or not requirement_version_id:
        return [
            _command_rejected(
                make_event,
                "record_support_evidence",
                f"unknown active requirement version: {requirement_id}",
            )
        ]

    event_payload = dict(payload)
    event_payload["support_id"] = support_id
    event_payload["evidence_id"] = evidence_id
    event_payload["requirement_id"] = requirement_id
    event_payload["requirement_version_id"] = requirement_version_id
    return [make_event("support_evidence_recorded", event_payload)]


def _cleanup_requested_event(
    events: list[EventEnvelope],
    cleanup_id: str,
) -> EventEnvelope | None:
    for event in events:
        if event.event_type != "cleanup_requested":
            continue
        if event.payload.get("cleanup_id") == cleanup_id:
            return event
    return None


def _cleanup_applied_exists(events: list[EventEnvelope], cleanup_id: str) -> bool:
    return any(
        event.event_type == "cleanup_applied" and event.payload.get("cleanup_id") == cleanup_id
        for event in events
    )


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


def _record_residue(record: dict[str, Any]) -> list[dict[str, Any]]:
    residue = record.get("residue")
    if not isinstance(residue, list):
        return []
    typed_residue = cast(list[Any], residue)
    return [dict(cast(dict[str, Any], entry)) for entry in typed_residue if isinstance(entry, dict)]


def _gatekeeper_cost_payload(
    record_id: str,
    execution_id: str,
    consult_id: str,
    verdicts: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    cost = payload.get("cost")
    if isinstance(cost, dict):
        typed_cost = cast(dict[str, Any], cost)
    else:
        typed_cost = {}
    model_ids = sorted({str(verdict.get("model_id", "unknown")) for verdict in verdicts})
    return {
        "file_state_record_id": record_id,
        "execution_id": execution_id,
        "consult_id": consult_id,
        "model_id": str(
            typed_cost.get("model_id") or (model_ids[0] if len(model_ids) == 1 else "mixed")
        ),
        "input_tokens": _nonnegative_int(
            typed_cost.get("input_tokens", sum(int(v["input_tokens"]) for v in verdicts))
        ),
        "output_tokens": _nonnegative_int(
            typed_cost.get("output_tokens", sum(int(v["output_tokens"]) for v in verdicts))
        ),
        "cache_read_tokens": _nonnegative_int(
            typed_cost.get(
                "cache_read_tokens",
                sum(int(v["cache_read_tokens"]) for v in verdicts),
            )
        ),
        "cache_write_tokens": _nonnegative_int(
            typed_cost.get(
                "cache_write_tokens",
                sum(int(v["cache_write_tokens"]) for v in verdicts),
            )
        ),
        "cost_usd": _nonnegative_float(
            typed_cost.get("cost_usd", sum(float(v["cost_usd"]) for v in verdicts))
        ),
        "wall_time_ms": _nonnegative_int(
            typed_cost.get("wall_time_ms", sum(int(v["wall_time_ms"]) for v in verdicts))
        ),
        "item_count": len(verdicts),
    }


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return 0


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float) and value > 0:
        return int(value)
    return default


def _nonnegative_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float) and value >= 0:
        return float(value)
    return 0.0


def _request_record_events_for_node(
    node_payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    for record_payload, to_port in _request_record_bindings_for_node(node_payload):
        output.append(make_event("output_record_accepted", record_payload))
        record_id = record_payload["record_id"]
        node_id = record_payload["producer_node_id"]
        output.append(
            make_event(
                "input_bound",
                {
                    "edge_id": f"edge-{record_id}-to-{node_id}-{to_port}",
                    "to_node_id": node_id,
                    "to_port": to_port,
                    "record_ids": [record_id],
                    "bound_at_position": 0,
                    "binding_policy": "bind_latest",
                },
            )
        )
    return output


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
    events: list[EventEnvelope],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
    *,
    inherited_session_id: str | None = None,
    carryover_record_id: str | None = None,
) -> list[EventEnvelope]:
    op_payload = _op_payload(op)
    if op.op == "create_node" and isinstance(op.node, dict):
        node_payload = dict(op.node)
        _ensure_default_node_authority(node_payload)
        canonicalize_check_command_definition(node_payload, events)
        if node_payload.get("kind") == "planner" and node_payload.get("role") == "planner":
            if inherited_session_id is not None:
                node_payload.setdefault("session_id", inherited_session_id)
            _ensure_optional_session_carryover_input(node_payload)
            if carryover_record_id is not None:
                node_payload["carryover_record_id"] = carryover_record_id
        output = [make_event("node_created", node_payload)]
        output.extend(_request_record_events_for_node(node_payload, make_event))
        return output
    if op.op == "create_edge":
        edge_id = op_payload.get("edge_id")
        required = op_payload.get("required")
        edge_payload = {
            "edge_id": edge_id,
            "from_node_id": op.from_node_id,
            "from_port": _canonical_patch_edge_from_port(op.from_port),
            "to_node_id": op.to_node_id,
            "to_port": op.to_port,
            "required": required if isinstance(required, bool) else True,
            "dependency_type": op_payload.get("dependency_type", "input_binding"),
        }
        for key in (
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
            edge_payload["accepted_record_selector"] = selector
        output = [make_event("edge_created", edge_payload)]
        output.extend(_input_bound_events_for_edge(events, edge_payload, make_event))
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
        node_payload = _node_payload_for_op(op_payload, default_kind="gate")
        return [make_event("node_created", node_payload)]
    if op.op == "create_revision_attempt":
        events = [
            make_event(
                "revision_created",
                {
                    key: value
                    for key, value in op_payload.items()
                    if key not in {"op", "node", "worker_node", "verifier_node"}
                },
            )
        ]
        for node_key, default_kind in (("worker_node", "worker"), ("verifier_node", "verifier")):
            raw_node = op_payload.get(node_key)
            if isinstance(raw_node, dict):
                events.append(
                    make_event(
                        "node_created",
                        _node_payload_for_op(
                            {"node": raw_node, **op_payload},
                            default_kind=default_kind,
                        ),
                    )
                )
        if len(events) == 1:
            events.append(
                make_event("node_created", _node_payload_for_op(op_payload, default_kind="worker"))
            )
        return events
    if op.op == "create_appeal":
        node_payload = _node_payload_for_op(op_payload, default_kind="appeal")
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
    if "resource_claims" not in authority:
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
    for lease in projection["leases"].values():
        if not _lease_is_expired(lease, now):
            continue
        node_id = lease.get("node_id")
        expired.append(
            make_event(
                "lease_expired",
                {
                    "lease_id": lease.get("lease_id"),
                    "node_id": node_id,
                    "generation": lease.get("generation"),
                    "execution_id": lease.get("execution_id"),
                    "expires_at": lease.get("expires_at"),
                    "reason": "lease_expired_without_callback",
                },
            )
        )
        if isinstance(node_id, str):
            lease_id = lease.get("lease_id")
            typed_lease_id = lease_id if isinstance(lease_id, str) else None
            expired.append(
                make_event(
                    "output_record_accepted",
                    _failure_record_payload(
                        node_id=node_id,
                        phase="runtime",
                        error_class="lease_expired_without_callback",
                        retryable=False,
                        lease_id=typed_lease_id,
                        execution_id=lease.get("execution_id"),
                        generation=lease.get("generation"),
                        reason="lease_expired_without_callback",
                        metadata={"expires_at": lease.get("expires_at")},
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
        lease_id
        for lease in projection["leases"].values()
        if isinstance((lease_id := lease.get("lease_id")), str) and _lease_is_expired(lease, now)
    }


def _lease_is_expired(lease: dict[str, Any], now: datetime) -> bool:
    if lease.get("state") != "active":
        return False
    expires_at = lease.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    return datetime.fromisoformat(expires_at) <= now


def _node_schedule_info(
    projection: GraphProjection,
    payload: dict[str, Any],
    node_id: str,
) -> NodeScheduleInfo:
    priorities = (
        cast(dict[str, Any], payload.get("priorities"))
        if isinstance(payload.get("priorities"), dict)
        else {}
    )
    region_order = (
        cast(dict[str, Any], payload.get("region_order"))
        if isinstance(payload.get("region_order"), dict)
        else {}
    )
    required_edges = _required_edges_for_node(projection, node_id)
    upstream_node_ids = {edge.from_node_id for edge in required_edges}
    return NodeScheduleInfo(
        node_id=node_id,
        kind=projection["node_kinds"].get(node_id, "worker"),
        state=projection["node_states"][node_id],
        priority=int(priorities.get(node_id, 0)),
        region_order=int(region_order.get(node_id, 0)),
        creation_position=0,
        resource_claims=[
            _claim_from_dict(claim) for claim in projection["node_resource_claims"].get(node_id, [])
        ],
        required_edges=required_edges,
        satisfied_input_ports=set(projection["input_bindings"].get(node_id, {})),
        upstream_states={
            upstream_node_id: projection["node_states"][upstream_node_id]
            for upstream_node_id in upstream_node_ids
            if upstream_node_id in projection["node_states"]
        },
        upstream_kinds={
            upstream_node_id: projection["node_kinds"][upstream_node_id]
            for upstream_node_id in upstream_node_ids
            if upstream_node_id in projection["node_kinds"]
        },
        upstream_pending_appeals={
            upstream_node_id
            for upstream_node_id in upstream_node_ids
            if projection["node_pending_appeals"].get(upstream_node_id) is True
        },
        gate_decisions={
            gate_node_id: decision
            for gate_node_id, decision in projection["node_gate_decisions"].items()
            if gate_node_id in upstream_node_ids
        },
        failed_candidate_id=projection["node_failed_candidates"].get(node_id),
        preconditions=projection["node_preconditions"].get(node_id, []),
        command_definition_present=node_id in projection["node_command_definitions"],
    )


def _required_edges_for_node(
    projection: GraphProjection,
    node_id: str,
) -> list[InputEdgeInfo]:
    edges: list[InputEdgeInfo] = []
    for edge in projection["edges"].values():
        if edge.get("to_node_id") != node_id:
            continue
        edges.append(
            InputEdgeInfo(
                from_node_id=str(edge.get("from_node_id", "")),
                from_port=str(edge.get("from_port", "")),
                to_node_id=str(edge.get("to_node_id", "")),
                to_port=str(edge.get("to_port", "")),
                required=edge.get("required") is not False,
                dependency_type=str(edge.get("dependency_type", "input_binding")),
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
) -> EventEnvelope:
    return make_event(
        "command_rejected",
        {
            "command_type": command_type,
            "reason": reason,
        },
    )


def _node_exists(projection: GraphProjection, node_id: str) -> bool:
    return node_id in projection["node_states"] or node_id in projection["node_kinds"]


def _decision_value(decision_type: Any, payload: dict[str, Any]) -> str | None:
    decision = payload.get("decision")
    if decision_type == "approval":
        if decision in {"approved", "rejected", "deferred"}:
            return cast(str, decision)
        if decision == "defer":
            return "deferred"
        approved = payload.get("approved")
        if approved is True:
            return "approved"
        if approved is False:
            return "rejected"
        return None

    if decision_type == "authority":
        if decision in {"granted", "denied", "deferred"}:
            return cast(str, decision)
        if decision == "grant":
            return "granted"
        if decision == "deny":
            return "denied"
        if decision == "defer":
            return "deferred"
        return None

    if decision in {"accepted", "rejected", "invalid_test_accepted"}:
        return cast(str, decision)
    return None


def _valid_decider(decider: Any) -> bool:
    if isinstance(decider, str):
        return bool(decider)
    if isinstance(decider, dict):
        typed_decider = cast(dict[str, Any], decider)
        return isinstance(typed_decider.get("kind"), str)
    return False


def _op_payload(op: PatchOp) -> dict[str, Any]:
    return op.model_dump(exclude_none=True)


def _canonical_patch_edge_from_port(from_port: str | None) -> str | None:
    if from_port == "verification_result":
        return "verification_report"
    return from_port


def _node_payload_for_op(op_payload: dict[str, Any], *, default_kind: str) -> dict[str, Any]:
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
    return node_payload


def _input_bound_events_for_edge(
    events: list[EventEnvelope],
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

    output: list[EventEnvelope] = []
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        record_payload = dict(event.payload)
        if record_payload.get("producer_node_id") != from_node_id:
            continue
        if record_payload.get("port") != from_port:
            continue
        record_id = record_payload.get("record_id")
        if not isinstance(record_id, str):
            continue
        if not _record_matches_selector(
            edge_payload.get("accepted_record_selector"),
            record_payload,
            _record_selector_aliases(record_payload),
        ):
            continue
        binding_payload: dict[str, Any] = {
            "edge_id": edge_id,
            "to_node_id": to_node_id,
            "to_port": to_port,
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


def _record_selector_aliases(record_payload: dict[str, Any]) -> set[str]:
    record_kind = record_payload.get("record_kind")
    if record_kind == "verification":
        return {"verification_result"}
    if record_kind == "file_state":
        return {"accepted_file_state", "file_state"}
    return set()


def _event_factory(
    run_id: str,
    command_type: str,
    clock: Clock,
    id_gen: IdGenerator,
) -> Callable[[str, dict[str, Any]], EventEnvelope]:
    def make_event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
        return EventEnvelope(
            event_id=id_gen.next_id("event"),
            run_id=run_id,
            position=-1,
            event_type=event_type,
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            causation_id=command_type,
            timestamp=clock.now(),
            payload=payload,
        )

    return make_event


def _run_id(events: list[EventEnvelope], payload: dict[str, Any]) -> str:
    run_id = payload.get("run_id")
    if isinstance(run_id, str):
        return run_id
    if events:
        return events[-1].run_id
    return "run-1"


def _current_position(events: list[EventEnvelope]) -> int:
    if not events:
        return -1
    return max(event.position for event in events)


def _callback_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_payload = payload.get("payload")
    if raw_payload is None:
        payload_hash = payload.get("payload_hash")
        if isinstance(payload_hash, str):
            return {"payload_hash": payload_hash}
        return None
    if isinstance(raw_payload, dict):
        return cast(dict[str, Any], raw_payload)
    return {"payload": raw_payload}


def _claim_from_dict(claim: dict[str, Any]) -> ResourceClaim:
    return ResourceClaim(
        mode=str(claim.get("mode", "read")),
        scope=str(claim.get("scope", "repo")),
        paths=[str(path) for path in claim.get("paths", [])]
        if isinstance(claim.get("paths"), list)
        else [],
        snapshot_id=cast(str | None, claim.get("snapshot_id")),
        external_resource_key=cast(str | None, claim.get("external_resource_key")),
        exclusive=bool(claim.get("exclusive", False)),
    )
