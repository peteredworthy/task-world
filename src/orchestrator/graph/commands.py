"""Pure command applier for execution graph fixtures."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from orchestrator.graph.callbacks import (
    CallbackOutcome,
    CallbackRequest,
    validate_callback,
)
from orchestrator.graph.models import (
    Actor,
    ActorKind,
    EventEnvelope,
    OutputRecord,
    PatchEnvelope,
    PatchOp,
)
from orchestrator.graph.patch_validator import validate_patch
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.scheduler import (
    InputEdgeInfo,
    NodeScheduleInfo,
    ResourceClaim,
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
        return _apply_lifecycle_command(projection, command_type, payload, make_event)
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
        return _apply_agent_died(projection, payload, make_event)
    if command_type == "raise_appeal":
        return _apply_raise_appeal(payload, make_event, id_gen)
    if command_type == "record_decision":
        return _apply_record_decision(projection, payload, make_event)

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
    command_type: str,
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
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
    return [
        _lifecycle_event(
            make_event,
            command_type,
            current_state,
            next_state,
            payload.get("trigger", f"{command_type}_command_accepted"),
        )
    ]


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
            if event.event_type not in {"node_created", "edge_created", "input_bound"}:
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

    accepted = make_event("callback_accepted", event_payload)
    output: list[EventEnvelope] = [accepted]
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

    output: list[EventEnvelope] = []
    for raw_record in cast(list[Any], raw_records):
        if not isinstance(raw_record, dict):
            continue
        record_payload = dict(cast(dict[str, Any], raw_record))
        record_payload.setdefault("producer_node_id", expected_producer_node_id)
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
        try:
            record = OutputRecord.model_validate(record_payload)
        except ValueError:
            continue
        output.append(make_event("output_record_accepted", record.model_dump(mode="json")))
        output.extend(_input_bound_events_for_record(projection, record, make_event))
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
    return None


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

    verdict = str(record_payload.get("verdict"))
    event_type = "verification_passed" if verdict in {"passed", "pass"} else "verification_failed"
    task_region_id = projection["node_task_regions"].get(expected_producer_node_id)
    event_payload = {
        "node_id": request.node_id,
        "verifier_node_id": expected_producer_node_id,
        "candidate_id": candidate_id,
        "verdict": "passed" if event_type == "verification_passed" else "failed",
        "record_id": record_payload.get("record_id"),
        "evidence": record_payload.get("evidence"),
        "value": record_payload.get("value"),
    }
    if task_region_id is not None:
        event_payload["task_region_id"] = task_region_id
    return [
        make_event("output_record_accepted", record_payload),
        make_event(event_type, event_payload),
    ]


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


def _input_bound_events_for_record(
    projection: GraphProjection,
    record: OutputRecord,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output: list[EventEnvelope] = []
    # Output records are facts produced by the leased node. Edges are the only
    # authority for routing those facts into downstream required inputs.
    for edge in projection["edges"].values():
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        if edge.get("from_node_id") != record.producer_node_id:
            continue
        if edge.get("from_port") != record.port:
            continue
        edge_id = edge.get("edge_id")
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not isinstance(edge_id, str) or not isinstance(to_node_id, str):
            continue
        if not isinstance(to_port, str):
            continue
        output.append(
            make_event(
                "input_bound",
                {
                    "edge_id": edge_id,
                    "to_node_id": to_node_id,
                    "to_port": to_port,
                    "record_ids": [record.record_id],
                    "bound_at_position": 0,
                },
            )
        )
    return output


def _apply_patch_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    try:
        patch = PatchEnvelope(
            patch_id=str(payload["patch_id"]),
            proposed_by_node_id=str(payload.get("proposed_by_node_id", "controller")),
            base_graph_position=int(payload.get("base_graph_position", -1)),
            ops=[PatchOp(**op) for op in cast(list[dict[str, Any]], payload.get("ops", []))],
            rationale_record_id=cast(str | None, payload.get("rationale_record_id")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return [_command_rejected(make_event, "submit_patch", f"malformed patch: {exc}")]

    current_position = _current_position(events)
    events_since_base = [event for event in events if event.position > patch.base_graph_position]
    actor_role = str(payload.get("actor_role", "planner"))
    result = validate_patch(patch, current_position, events_since_base, projection, actor_role)
    if not result.accepted:
        return [
            make_event(
                "graph_patch_rejected",
                {
                    "patch_id": patch.patch_id,
                    "reason": result.rejection_reason,
                    "read_set_diff": result.read_set_diff,
                },
            )
        ]

    output = [
        make_event(
            "graph_patch_accepted",
            {
                "patch_id": patch.patch_id,
                "base_graph_position": patch.base_graph_position,
                "actor_role": actor_role,
            },
        )
    ]
    for op in patch.ops:
        output.extend(_patch_op_events(op, make_event))
    return output


def _apply_schedule_tick(
    projection: GraphProjection,
    events: list[EventEnvelope],
    payload: dict[str, Any],
    clock: Clock,
    id_gen: IdGenerator,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    output = _expired_lease_events(projection, clock.now(), make_event)
    active_claims = [
        _claim_from_dict(claim)
        for lease in projection["leases"].values()
        if lease.get("state") == "active"
        for claim in cast(list[dict[str, Any]], lease.get("resource_claims", []))
    ]
    active_lease_node_ids = [
        str(lease["node_id"])
        for lease in projection["leases"].values()
        if lease.get("state") == "active" and isinstance(lease.get("node_id"), str)
    ]
    nodes: list[NodeScheduleInfo] = []
    readied_node_ids: set[str] = set()
    for node_id, node_state in projection["node_states"].items():
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        node = _node_schedule_info(projection, payload, node_id)
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
        output.append(
            make_event(
                "lease_granted",
                {
                    "lease_id": lease_id,
                    "node_id": node_id,
                    "generation": 1,
                    "execution_id": id_gen.next_id("exec"),
                    "base_snapshot_id": base_snapshot_id,
                    "expires_at": (clock.now() + timedelta(seconds=lease_seconds)).isoformat(),
                    "resource_claims": claims,
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
    if (
        isinstance(execution_id, str)
        and isinstance(lease_execution_id, str)
        and execution_id != lease_execution_id
    ):
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

    # V1 retry policy: runtime death before an accepted boundary requeues the
    # same executable node. No new retry node is created until output/file-state
    # acceptance semantics exist in the graph runtime slice.
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
            {
                "node_id": node_id,
                "lease_id": lease_id,
                "generation": generation,
                "policy": "v1_requeue_same_node_after_agent_death",
                "reason": reason,
            },
        ),
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "ready",
                "trigger": "agent_died_retry_scheduled",
            },
        ),
    ]


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
    if decision_type not in {"approval", "oversight"}:
        return [_command_rejected(make_event, "record_decision", "unknown decision_type")]

    node_id = payload.get("node_id")
    if not isinstance(node_id, str):
        return [_command_rejected(make_event, "record_decision", "missing target node_id")]
    if not _node_exists(projection, node_id):
        return [_command_rejected(make_event, "record_decision", f"unknown target node: {node_id}")]

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

    event_type = (
        "approval_decision_recorded"
        if decision_type == "approval"
        else "oversight_decision_recorded"
    )
    return [
        make_event(event_type, event_payload),
        make_event(
            "node_state_changed",
            {
                "node_id": node_id,
                "new_state": "completed",
                "trigger": f"{event_type}_accepted",
            },
        ),
    ]


def _patch_op_events(
    op: PatchOp,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    op_payload = _op_payload(op)
    if op.op == "create_node" and isinstance(op.node, dict):
        return [make_event("node_created", dict(op.node))]
    if op.op == "create_edge":
        edge_id = op_payload.get("edge_id")
        required = op_payload.get("required")
        return [
            make_event(
                "edge_created",
                {
                    "edge_id": edge_id,
                    "from_node_id": op.from_node_id,
                    "from_port": op.from_port,
                    "to_node_id": op.to_node_id,
                    "to_port": op.to_port,
                    "required": required if isinstance(required, bool) else True,
                    "dependency_type": op_payload.get("dependency_type", "input_binding"),
                },
            )
        ]
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


def _expired_lease_events(
    projection: GraphProjection,
    now: datetime,
    make_event: Callable[[str, dict[str, Any]], EventEnvelope],
) -> list[EventEnvelope]:
    expired: list[EventEnvelope] = []
    for lease in projection["leases"].values():
        if lease.get("state") != "active":
            continue
        expires_at = lease.get("expires_at")
        if not isinstance(expires_at, str):
            continue
        if datetime.fromisoformat(expires_at) <= now:
            expired.append(
                make_event(
                    "lease_expired",
                    {
                        "lease_id": lease.get("lease_id"),
                        "node_id": lease.get("node_id"),
                        "generation": lease.get("generation"),
                        "expires_at": expires_at,
                    },
                )
            )
    return expired


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
        if decision in {"approved", "rejected"}:
            return cast(str, decision)
        approved = payload.get("approved")
        if approved is True:
            return "approved"
        if approved is False:
            return "rejected"
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
    return node_payload


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
