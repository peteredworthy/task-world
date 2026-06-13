"""Pure graph projections for scenario fixtures."""

from typing import Any, Literal, TypedDict, cast

from orchestrator.graph.models import EventEnvelope


class GraphProjection(TypedDict):
    run_state: str | None
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, dict[str, Any]]
    ready_nodes: list[str]
    node_kinds: dict[str, str]
    node_roles: dict[str, str]
    node_task_regions: dict[str, str]
    node_attempts: dict[str, int]
    node_candidates: dict[str, str]
    node_failed_candidates: dict[str, str]
    node_resource_claims: dict[str, list[dict[str, Any]]]
    node_allowed_actions: dict[str, list[str]]
    node_preconditions: dict[str, list[str]]
    node_command_definitions: dict[str, Any]
    edges: dict[str, dict[str, Any]]
    input_bindings: dict[str, dict[str, dict[str, Any]]]
    node_pending_appeals: dict[str, bool]
    node_gate_decisions: dict[str, bool]
    task_candidates: dict[str, list[dict[str, Any]]]
    verifier_verdicts: dict[str, dict[str, Any]]
    invalid_test_blocks: dict[str, dict[str, Any]]
    configured_gates: dict[str, dict[str, bool]]
    gate_decisions: dict[str, dict[str, bool]]
    environment_failures: dict[str, dict[str, Any]]
    file_state_records: dict[str, dict[str, Any]]
    planner_generation_budget: int
    planner_successors: dict[str, str]
    planner_generations: dict[str, int]
    planner_sessions: dict[str, str]
    planner_session_states: dict[str, str]
    planner_session_current_nodes: dict[str, str]
    planner_session_carryovers: dict[str, str | None]
    planner_region_labels: dict[str, str]


class SchedulerBlockedNode(TypedDict):
    node_id: str
    reason: str


class SchedulerView(TypedDict):
    ready: list[str]
    blocked: list[SchedulerBlockedNode]
    waiting_resources: list[SchedulerBlockedNode]
    waiting_gates: list[SchedulerBlockedNode]


class LeaseViewEntry(TypedDict):
    lease_id: str
    node_id: str
    generation: int | None
    state: str
    execution_id: str | None
    expires_at: str | None


class LeaseView(TypedDict):
    active: list[LeaseViewEntry]
    suspended: list[LeaseViewEntry]


class PendingGateDecision(TypedDict):
    node_id: str
    gate_type: str
    prompt: str | None


class AppealDecision(TypedDict):
    node_id: str
    state: str
    outcome: str | None


class ReviewReadiness(TypedDict):
    ready: bool
    blockers: list[str]


class DecisionView(TypedDict):
    pending_gates: list[PendingGateDecision]
    appeals: list[AppealDecision]
    review: ReviewReadiness


def initial_projection() -> GraphProjection:
    return {
        "run_state": None,
        "node_states": {},
        "task_states": {},
        "leases": {},
        "ready_nodes": [],
        "node_kinds": {},
        "node_roles": {},
        "node_task_regions": {},
        "node_attempts": {},
        "node_candidates": {},
        "node_failed_candidates": {},
        "node_resource_claims": {},
        "node_allowed_actions": {},
        "node_preconditions": {},
        "node_command_definitions": {},
        "edges": {},
        "input_bindings": {},
        "node_pending_appeals": {},
        "node_gate_decisions": {},
        "task_candidates": {},
        "verifier_verdicts": {},
        "invalid_test_blocks": {},
        "configured_gates": {},
        "gate_decisions": {},
        "environment_failures": {},
        "file_state_records": {},
        "planner_generation_budget": 8,
        "planner_successors": {},
        "planner_generations": {},
        "planner_sessions": {},
        "planner_session_states": {},
        "planner_session_current_nodes": {},
        "planner_session_carryovers": {},
        "planner_region_labels": {},
    }


def reduce_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    next_state: GraphProjection = {
        "run_state": state["run_state"],
        "node_states": dict(state["node_states"]),
        "task_states": dict(state["task_states"]),
        "leases": {lease_id: dict(lease) for lease_id, lease in state["leases"].items()},
        "ready_nodes": list(state["ready_nodes"]),
        "node_kinds": dict(state["node_kinds"]),
        "node_roles": dict(state.get("node_roles", {})),
        "node_task_regions": dict(state["node_task_regions"]),
        "node_attempts": dict(state["node_attempts"]),
        "node_candidates": dict(state["node_candidates"]),
        "node_failed_candidates": dict(state["node_failed_candidates"]),
        "node_resource_claims": {
            node_id: [dict(claim) for claim in claims]
            for node_id, claims in state["node_resource_claims"].items()
        },
        "node_allowed_actions": {
            node_id: list(actions) for node_id, actions in state["node_allowed_actions"].items()
        },
        "node_preconditions": {
            node_id: list(preconditions)
            for node_id, preconditions in state["node_preconditions"].items()
        },
        "node_command_definitions": dict(state["node_command_definitions"]),
        "edges": {edge_id: dict(edge) for edge_id, edge in state["edges"].items()},
        "input_bindings": {
            node_id: {port: dict(binding) for port, binding in ports.items()}
            for node_id, ports in state["input_bindings"].items()
        },
        "node_pending_appeals": dict(state["node_pending_appeals"]),
        "node_gate_decisions": dict(state["node_gate_decisions"]),
        "task_candidates": {
            task_region_id: [dict(candidate) for candidate in candidates]
            for task_region_id, candidates in state["task_candidates"].items()
        },
        "verifier_verdicts": {
            candidate_id: dict(verdict)
            for candidate_id, verdict in state["verifier_verdicts"].items()
        },
        "invalid_test_blocks": {
            task_region_id: dict(block)
            for task_region_id, block in state["invalid_test_blocks"].items()
        },
        "configured_gates": {
            task_region_id: dict(gates)
            for task_region_id, gates in state["configured_gates"].items()
        },
        "gate_decisions": {
            task_region_id: dict(decisions)
            for task_region_id, decisions in state["gate_decisions"].items()
        },
        "environment_failures": {
            task_region_id: dict(failure)
            for task_region_id, failure in state["environment_failures"].items()
        },
        "file_state_records": {
            record_id: _copy_file_state_record(record)
            for record_id, record in state.get("file_state_records", {}).items()
        },
        "planner_generation_budget": state.get("planner_generation_budget", 8),
        "planner_successors": dict(state.get("planner_successors", {})),
        "planner_generations": dict(state.get("planner_generations", {})),
        "planner_sessions": dict(state.get("planner_sessions", {})),
        "planner_session_states": dict(state.get("planner_session_states", {})),
        "planner_session_current_nodes": dict(state.get("planner_session_current_nodes", {})),
        "planner_session_carryovers": dict(state.get("planner_session_carryovers", {})),
        "planner_region_labels": dict(state.get("planner_region_labels", {})),
    }

    if event.event_type == "run_lifecycle_changed":
        to_state = event.payload.get("to_state")
        if isinstance(to_state, str):
            next_state["run_state"] = to_state
    elif event.event_type == "node_created":
        node_id = event.payload.get("node_id")
        kind = event.payload.get("kind")
        role = event.payload.get("role")
        node_state = event.payload.get("state")
        task_region_id = _task_region_id(event.payload)
        attempt_number = _attempt_number(event.payload)
        candidate_id = _candidate_id(event.payload)
        if isinstance(node_id, str) and isinstance(node_state, str):
            next_state["node_states"][node_id] = node_state
        if isinstance(node_id, str):
            if kind == "root":
                budget = event.payload.get("planner_generation_budget")
                if isinstance(budget, int) and not isinstance(budget, bool) and budget >= 0:
                    next_state["planner_generation_budget"] = budget
            if isinstance(kind, str):
                next_state["node_kinds"][node_id] = kind
            if isinstance(role, str):
                next_state["node_roles"][node_id] = role
            if kind == "planner" and role == "planner":
                generation_index = event.payload.get("generation_index")
                if isinstance(generation_index, int) and not isinstance(generation_index, bool):
                    next_state["planner_generations"][node_id] = generation_index
                region_label = event.payload.get("region_label")
                if isinstance(region_label, str):
                    next_state["planner_region_labels"][node_id] = region_label
                session_id = event.payload.get("session_id")
                if isinstance(session_id, str):
                    next_state["planner_sessions"][node_id] = session_id
                    next_state["planner_session_states"].setdefault(session_id, "detached")
                    next_state["planner_session_carryovers"].setdefault(session_id, None)
            if task_region_id is not None:
                next_state["node_task_regions"][node_id] = task_region_id
            if attempt_number is not None:
                next_state["node_attempts"][node_id] = attempt_number
            if candidate_id is not None:
                next_state["node_candidates"][node_id] = candidate_id
            failed_candidate_id = _failed_candidate_id(event.payload)
            if failed_candidate_id is not None:
                next_state["node_failed_candidates"][node_id] = failed_candidate_id
            resource_claims = _resource_claims(event.payload)
            if resource_claims:
                next_state["node_resource_claims"][node_id] = resource_claims
            allowed_actions = _allowed_actions(event.payload)
            if allowed_actions:
                next_state["node_allowed_actions"][node_id] = allowed_actions
            preconditions = _preconditions(event.payload)
            if kind == "check" and "has_command_definition" not in preconditions:
                preconditions.append("has_command_definition")
            if preconditions:
                next_state["node_preconditions"][node_id] = preconditions
            command_definition = _command_definition(event.payload)
            if command_definition is not None:
                next_state["node_command_definitions"][node_id] = command_definition
            if kind == "gate" and task_region_id is not None:
                next_state["configured_gates"].setdefault(task_region_id, {})[node_id] = True
    elif event.event_type == "node_state_changed":
        node_id = event.payload.get("node_id")
        new_state = event.payload.get("new_state")
        if isinstance(node_id, str) and isinstance(new_state, str):
            next_state["node_states"][node_id] = new_state
    elif event.event_type == "node_retired":
        node_id = event.payload.get("node_id")
        if isinstance(node_id, str):
            next_state["node_states"][node_id] = "retired"
    elif event.event_type == "edge_created":
        _record_edge(next_state, event)
    elif event.event_type == "input_bound":
        _record_input_binding(next_state, event)
    elif event.event_type == "lease_granted":
        lease_id = event.payload.get("lease_id")
        node_id = event.payload.get("node_id")
        generation = event.payload.get("generation")
        if isinstance(lease_id, str) and isinstance(node_id, str):
            lease: dict[str, Any] = {
                "lease_id": lease_id,
                "node_id": node_id,
                "state": "active",
            }
            if isinstance(generation, int):
                lease["generation"] = generation
            session_id = event.payload.get("session_id")
            if isinstance(session_id, str):
                lease["session_id"] = session_id
                next_state["planner_sessions"][node_id] = session_id
            expires_at = event.payload.get("expires_at")
            if isinstance(expires_at, str):
                lease["expires_at"] = expires_at
            execution_id = event.payload.get("execution_id")
            if isinstance(execution_id, str):
                lease["execution_id"] = execution_id
            base_snapshot_id = event.payload.get("base_snapshot_id")
            if isinstance(base_snapshot_id, str):
                lease["base_snapshot_id"] = base_snapshot_id
            task_region_id = _task_region_id(event.payload) or next_state["node_task_regions"].get(
                node_id
            )
            if task_region_id is not None:
                lease["task_region_id"] = task_region_id
            kind = event.payload.get("kind")
            if isinstance(kind, str):
                lease["kind"] = kind
            elif node_id in next_state["node_kinds"]:
                lease["kind"] = next_state["node_kinds"][node_id]
            resource_claims = _resource_claims(event.payload)
            if not resource_claims:
                resource_claims = next_state["node_resource_claims"].get(node_id, [])
            if resource_claims:
                lease["resource_claims"] = resource_claims
            next_state["leases"][lease_id] = lease
    elif event.event_type == "session_state_changed":
        session_id = event.payload.get("session_id")
        session_state = event.payload.get("state")
        if isinstance(session_id, str) and isinstance(session_state, str):
            next_state["planner_session_states"][session_id] = session_state
            node_id = event.payload.get("node_id")
            if session_state == "attached" and isinstance(node_id, str):
                next_state["planner_session_current_nodes"][session_id] = node_id
            elif session_state in {"suspended", "detached", "dead"}:
                next_state["planner_session_current_nodes"].pop(session_id, None)
            carryover_record_id = event.payload.get("carryover_record_id")
            if isinstance(carryover_record_id, str):
                next_state["planner_session_carryovers"][session_id] = carryover_record_id
            elif carryover_record_id is None and "carryover_record_id" in event.payload:
                next_state["planner_session_carryovers"][session_id] = None
    elif event.event_type in {
        "lease_suspended",
        "lease_revoked",
        "lease_expired",
        "lease_released",
    }:
        lease_id = event.payload.get("lease_id")
        if isinstance(lease_id, str):
            lease = dict(next_state["leases"].get(lease_id, {"lease_id": lease_id}))
            lease["state"] = event.event_type.removeprefix("lease_")
            next_state["leases"][lease_id] = lease
    elif event.event_type == "output_record_accepted":
        _record_candidate(next_state, event)
    elif event.event_type in {"verification_passed", "verification_failed"}:
        _record_verdict(next_state, event)
    elif event.event_type == "appeal_opened":
        _record_open_appeal(next_state, event)
    elif event.event_type == "oversight_decision_recorded":
        _record_oversight_decision(next_state, event)
    elif event.event_type == "approval_decision_recorded":
        _record_gate_decision(next_state, event)
    elif event.event_type == "node_authority_changed":
        _record_authority_change(next_state, event)
    elif event.event_type in {"environment_failure_accepted", "check_result_classified"}:
        _record_environment_failure(next_state, event)
    elif event.event_type == "file_state_accepted":
        _record_file_state(next_state, event)
    elif event.event_type == "graph_patch_accepted":
        planner_node_id = event.payload.get("proposed_by_node_id")
        successor_node_ids = event.payload.get("successor_planner_node_ids")
        if isinstance(planner_node_id, str) and isinstance(successor_node_ids, list):
            for successor_node_id in cast(list[Any], successor_node_ids):
                if isinstance(successor_node_id, str):
                    next_state["planner_successors"][planner_node_id] = successor_node_id
                    break
    elif event.event_type == "gatekeeper_verdict_recorded":
        _record_gatekeeper_verdicts(next_state, event)
    elif event.event_type == "cleanup_requested":
        _record_cleanup_requested(next_state, event)
    elif event.event_type == "cleanup_applied":
        _record_cleanup_applied(next_state, event)
    # node_ready/node_deferred and agent_died/runtime_retry_scheduled are
    # audit/policy facts. Projection facts are updated only by lease_* and
    # node_state_changed events so replay has a single state authority.

    next_state["ready_nodes"] = _ready_nodes(next_state["node_states"])
    next_state["task_states"] = _derive_task_states(next_state)
    return next_state


def project_run_state(events: list[EventEnvelope]) -> str | None:
    projection = _project(events)
    run_state = projection["run_state"]
    if run_state == "completed":
        if _has_pending_planner(projection):
            return "active"
        if _has_pending_planner_budget_gate(projection):
            return "active"
        if any(state != "accepted" for state in projection["task_states"].values()):
            return "active"
        return run_state
    if run_state != "active":
        return run_state
    if _has_pending_planner(projection):
        return run_state
    if _has_pending_planner_budget_gate(projection):
        return run_state
    task_states = projection["task_states"]
    if task_states and all(state == "accepted" for state in task_states.values()):
        return "completed"
    return run_state


def project_planner_chain(events: list[EventEnvelope]) -> list[dict[str, Any]]:
    projection = _project(events)
    planner_ids = [
        node_id
        for node_id, kind in projection["node_kinds"].items()
        if kind == "planner" and projection["node_roles"].get(node_id) == "planner"
    ]
    ordered = sorted(
        planner_ids,
        key=lambda node_id: (
            projection["planner_generations"].get(node_id, 0),
            _node_creation_position(events, node_id),
            node_id,
        ),
    )
    return [
        {
            "node_id": node_id,
            "generation_index": projection["planner_generations"].get(node_id, 0),
            "session_id": projection["planner_sessions"].get(node_id),
            "lease_generation": _latest_lease_generation(events, node_id),
            "region_label": _planner_region_label(events, projection, node_id),
            "state": projection["node_states"].get(node_id),
            "successor_node_id": projection["planner_successors"].get(node_id),
        }
        for node_id in ordered
    ]


def project_planner_session(events: list[EventEnvelope]) -> dict[str, Any]:
    projection = _project(events)
    session_ids = list(projection["planner_session_states"])
    if not session_ids:
        session_ids = list(projection["planner_sessions"].values())
    session_id = sorted(set(session_ids))[0] if session_ids else None
    if session_id is None:
        return {
            "session_id": None,
            "state": None,
            "generations": [],
            "current_node_id": None,
            "carryover_record_id": None,
        }

    generations: list[dict[str, Any]] = [
        {
            "node_id": event.payload["node_id"],
            "lease_generation": event.payload["generation"],
            "region_label": _planner_region_label(
                events,
                projection,
                str(event.payload["node_id"]),
            ),
            "state": _planner_generation_state(events, str(event.payload["lease_id"])),
        }
        for event in events
        if event.event_type == "lease_granted"
        and event.payload.get("session_id") == session_id
        and isinstance(event.payload.get("node_id"), str)
        and isinstance(event.payload.get("lease_id"), str)
        and isinstance(event.payload.get("generation"), int)
    ]
    generations.sort(key=lambda generation: int(generation["lease_generation"]))
    return {
        "session_id": session_id,
        "state": projection["planner_session_states"].get(session_id),
        "generations": generations,
        "current_node_id": projection["planner_session_current_nodes"].get(session_id),
        "carryover_record_id": projection["planner_session_carryovers"].get(session_id),
    }


def project_node_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["node_states"]


def project_node_metadata(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    projection = _project(events)
    return {
        node_id: {
            "kind": projection["node_kinds"].get(node_id),
            "role": projection["node_roles"].get(node_id),
            "input_ports": {
                port: _bound_record_ids(binding)
                for port, binding in projection["input_bindings"].get(node_id, {}).items()
            },
        }
        for node_id in projection["node_states"]
    }


def project_task_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["task_states"]


def project_leases(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    return _project(events)["leases"]


def project_ready_nodes(events: list[EventEnvelope]) -> list[str]:
    return _project(events)["ready_nodes"]


def project_scheduler_view(events: list[EventEnvelope]) -> SchedulerView:
    """Project ready/deferred scheduler buckets from graph events.

    Readiness remains governed by node_state_changed facts. Deferred scheduler
    events are audit facts, so this view uses only the latest deferral reason
    for nodes that are not currently ready.
    """
    node_states = project_node_states(events)
    ready = sorted(project_ready_nodes(events))
    latest_deferrals = _latest_node_deferrals(events)
    view: SchedulerView = {
        "ready": ready,
        "blocked": [],
        "waiting_resources": [],
        "waiting_gates": [],
    }
    pending_states = {"planned", "blocked"}
    for node_id, node_state in sorted(node_states.items()):
        if node_state not in pending_states:
            continue
        reason = latest_deferrals.get(node_id)
        if reason is None and node_state != "blocked":
            continue
        if reason is None:
            reason = "blocked"
        entry: SchedulerBlockedNode = {"node_id": node_id, "reason": reason}
        bucket = _scheduler_bucket_for_reason(reason)
        view[bucket].append(entry)
    return view


def project_lease_view(events: list[EventEnvelope]) -> LeaseView:
    leases = project_leases(events)
    view: LeaseView = {"active": [], "suspended": []}
    for lease_id in sorted(leases):
        lease = leases[lease_id]
        state = lease.get("state")
        if state not in {"active", "suspended"}:
            continue
        node_id = lease.get("node_id")
        if not isinstance(node_id, str):
            continue
        entry: LeaseViewEntry = {
            "lease_id": lease_id,
            "node_id": node_id,
            "generation": _optional_int(lease.get("generation")),
            "state": state,
            "execution_id": _optional_str(lease.get("execution_id")),
            "expires_at": _optional_str(lease.get("expires_at")),
        }
        if state == "active":
            view["active"].append(entry)
        else:
            view["suspended"].append(entry)
    return view


def project_decision_view(events: list[EventEnvelope]) -> DecisionView:
    """Project human decisions, appeal outcomes, and review readiness."""
    projection = _project(events)
    latest_node_payloads = _latest_node_creation_payloads(events)
    approval_decisions = _latest_decisions(events, "approval_decision_recorded")
    oversight_decisions = _latest_decisions(events, "oversight_decision_recorded")
    latest_deferrals = _latest_node_deferrals(events)

    pending_gates: list[PendingGateDecision] = []
    appeals: list[AppealDecision] = []
    review_blockers: list[str] = []
    review_node_count = 0
    review_complete_count = 0

    for node_id, state in sorted(projection["node_states"].items()):
        kind = projection["node_kinds"].get(node_id)
        payload = latest_node_payloads.get(node_id, {})
        if (
            kind == "gate"
            and state in _PENDING_DECISION_STATES
            and node_id not in approval_decisions
        ):
            pending_gates.append(
                {
                    "node_id": node_id,
                    "gate_type": _gate_type(node_id, payload, projection),
                    "prompt": _gate_prompt(payload),
                }
            )
        elif kind == "appeal":
            appeals.append(
                {
                    "node_id": node_id,
                    "state": state,
                    "outcome": _decision_outcome(oversight_decisions.get(node_id)),
                }
            )
        elif kind == "review":
            review_node_count += 1
            if state == "completed":
                review_complete_count += 1
            else:
                review_blockers.append(_review_blocker(node_id, state, payload, latest_deferrals))

    return {
        "pending_gates": pending_gates,
        "appeals": appeals,
        "review": {
            "ready": review_node_count > 0 and review_complete_count == review_node_count,
            "blockers": review_blockers,
        },
    }


def project_residue_report(events: list[EventEnvelope]) -> dict[str, list[dict[str, Any]]]:
    """Project accepted file-state residue classifications by path."""
    report: dict[str, list[dict[str, Any]]] = {}
    for record in _project(events)["file_state_records"].values():
        node_id = record.get("producer_node_id")
        record_id = record.get("record_id")
        residue = record.get("residue")
        if not isinstance(residue, list):
            residue = record.get("classifications", [])
        if not isinstance(residue, list):
            continue
        for raw_entry in cast(list[Any], residue):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            report.setdefault(path, []).append(
                {
                    "path": path,
                    "classification": entry.get("classification"),
                    "matched_rule": entry.get("matched_rule") or entry.get("policy"),
                    "needs_gatekeeper": entry.get("needs_gatekeeper") is True,
                    "run_id": record.get("run_id"),
                    "node_id": node_id,
                    "record_id": record_id,
                    "source": entry.get("source"),
                }
            )
    return {path: report[path] for path in sorted(report)}


def _bound_record_ids(binding: dict[str, Any]) -> list[str]:
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return [record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)]


def project_pattern_library(events: list[EventEnvelope]) -> dict[str, Any]:
    """Project accepted gatekeeper verdicts into exact paths and derived globs.

    Learned patterns are scoped to untracked/ignored residue. The derived
    pattern rule is deterministic: ``dirname/*.ext`` when a non-root path has
    an extension, otherwise the exact path. Root-level files derive exact-path
    patterns only, never bare ``*.ext`` globs. Identical derived patterns merge
    and accumulate occurrence counts; exact paths are kept separately so the
    next boundary can classify both the same path and sibling files with the
    same directory-scoped shape.
    """
    patterns: dict[str, dict[str, Any]] = {}
    paths: dict[str, dict[str, Any]] = {}
    file_state_records: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type == "file_state_accepted":
            record_id = event.payload.get("record_id")
            if isinstance(record_id, str):
                file_state_records[record_id] = event.payload
            continue
        if event.event_type != "gatekeeper_verdict_recorded":
            continue
        record_id = event.payload.get("file_state_record_id")
        verdicts = event.payload.get("verdicts")
        if not isinstance(verdicts, list):
            continue
        source_by_path = _file_state_source_by_path(file_state_records.get(str(record_id)))
        for raw_verdict in cast(list[Any], verdicts):
            if not isinstance(raw_verdict, dict):
                continue
            verdict = cast(dict[str, Any], raw_verdict)
            path = verdict.get("path")
            classification = verdict.get("classification")
            if not isinstance(path, str) or not isinstance(classification, str):
                continue
            source = source_by_path.get(path)
            if source not in {"untracked", "ignored"} or classification == "secret":
                continue
            pattern = _derive_gatekeeper_pattern(path)
            _merge_pattern_entry(
                patterns,
                pattern,
                classification,
                path,
                event.position,
                record_id,
            )
            paths[path] = {
                "path": path,
                "classification": classification,
                "matched_rule": f"pattern_library:{path}",
                "source_record_ids": [record_id] if isinstance(record_id, str) else [],
                "last_position": event.position,
                "source_kinds": ["untracked", "ignored"],
            }
    return {
        "patterns": {pattern: patterns[pattern] for pattern in sorted(patterns)},
        "paths": {path: paths[path] for path in sorted(paths)},
    }


def project_gatekeeper_report(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    """Project gatekeeper cost, hit-rate, and pattern-library growth per run."""
    reports: dict[str, dict[str, Any]] = {}
    prefixes: dict[str, list[EventEnvelope]] = {}
    for event in events:
        run = reports.setdefault(event.run_id, _empty_gatekeeper_report(event.run_id))
        prefixes.setdefault(event.run_id, []).append(event)
        if event.event_type == "file_state_accepted":
            classifications = _payload_entries(event.payload, "classifications")
            deterministic = sum(
                1 for entry in classifications if entry.get("needs_gatekeeper") is not True
            )
            unresolved = sum(
                1 for entry in classifications if entry.get("needs_gatekeeper") is True
            )
            run["deterministic_classifications"] += deterministic
            run["unresolved_residue"] += unresolved
            run["boundary_count"] += 1
            library = project_pattern_library(prefixes[event.run_id])
            run["pattern_library_size_over_time"].append(
                {
                    "position": event.position,
                    "file_state_record_id": event.payload.get("record_id"),
                    "size": len(library["patterns"]),
                }
            )
        elif event.event_type == "gatekeeper_verdict_recorded":
            verdicts = event.payload.get("verdicts")
            resolved = len(cast(list[Any], verdicts)) if isinstance(verdicts, list) else 0
            run["gatekeeper_resolved"] += resolved
            run["unresolved_residue"] = max(0, int(run["unresolved_residue"]) - resolved)
            library = project_pattern_library(prefixes[event.run_id])
            run["pattern_library_size_over_time"].append(
                {
                    "position": event.position,
                    "file_state_record_id": event.payload.get("file_state_record_id"),
                    "size": len(library["patterns"]),
                }
            )
        elif event.event_type == "gatekeeper_cost_recorded":
            run["gatekeeper_consults"] += 1
            run["input_tokens"] += _payload_number(event.payload, "input_tokens")
            run["output_tokens"] += _payload_number(event.payload, "output_tokens")
            run["cache_read_tokens"] += _payload_number(event.payload, "cache_read_tokens")
            run["cache_write_tokens"] += _payload_number(event.payload, "cache_write_tokens")
            run["cost_usd"] += _payload_float(event.payload, "cost_usd")
            run["wall_time_ms"] += _payload_number(event.payload, "wall_time_ms")
            _record_model_cost(run, event.payload)

    for run in reports.values():
        total_classified = int(run["deterministic_classifications"]) + int(
            run["gatekeeper_resolved"]
        )
        run["total_classified"] = total_classified
        run["hit_rate"] = (
            float(run["deterministic_classifications"]) / total_classified
            if total_classified
            else 0.0
        )
        run["pattern_library_size"] = (
            int(run["pattern_library_size_over_time"][-1]["size"])
            if run["pattern_library_size_over_time"]
            else 0
        )
    return reports


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


_PENDING_DECISION_STATES = {"planned", "blocked", "ready", "leased", "running", "suspended"}


def _latest_node_creation_payloads(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        node_id = event.payload.get("node_id")
        if isinstance(node_id, str):
            payloads[node_id] = dict(event.payload)
    return payloads


def _latest_decisions(
    events: list[EventEnvelope],
    event_type: str,
) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type != event_type:
            continue
        node_id = event.payload.get("node_id")
        if isinstance(node_id, str):
            decisions[node_id] = dict(event.payload)
        appeal_node_id = event.payload.get("appeal_node_id")
        if isinstance(appeal_node_id, str):
            decisions[appeal_node_id] = dict(event.payload)
    return decisions


def _gate_type(
    node_id: str,
    payload: dict[str, Any],
    projection: GraphProjection,
) -> str:
    for key in ("gate_type", "approval_type", "reason", "role"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    role = projection["node_roles"].get(node_id)
    if role is not None:
        return role
    return "approval"


def _gate_prompt(payload: dict[str, Any]) -> str | None:
    for key in ("prompt", "approval_prompt", "human_prompt", "message", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _decision_outcome(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    for key in ("outcome", "decision", "verdict"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    approved = payload.get("approved")
    if isinstance(approved, bool):
        return "approved" if approved else "rejected"
    return None


def _review_blocker(
    node_id: str,
    state: str,
    payload: dict[str, Any],
    latest_deferrals: dict[str, str],
) -> str:
    for key in ("blocker", "blocker_reason", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return f"{node_id}: {value}"
    reason = latest_deferrals.get(node_id)
    if reason is not None:
        return f"{node_id}: {reason}"
    return f"{node_id}: {state}"


def _latest_node_deferrals(events: list[EventEnvelope]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        if event.event_type != "node_deferred":
            continue
        node_id = event.payload.get("node_id")
        reason = event.payload.get("reason")
        if isinstance(node_id, str) and isinstance(reason, str):
            reasons[node_id] = reason
    return reasons


def _scheduler_bucket_for_reason(
    reason: str,
) -> Literal["blocked", "waiting_resources", "waiting_gates"]:
    if reason.startswith("resource_") or reason.startswith("invalid_claim:"):
        return "waiting_resources"
    if reason.startswith("gate_") or reason.startswith("waiting_gate"):
        return "waiting_gates"
    return "blocked"


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _has_pending_planner(projection: GraphProjection) -> bool:
    pending_states = {"planned", "ready", "leased", "running"}
    return any(
        projection["node_kinds"].get(node_id) == "planner"
        and node_state in pending_states
        and projection["node_roles"].get(node_id) == "planner"
        for node_id, node_state in projection["node_states"].items()
    )


def _has_pending_planner_budget_gate(projection: GraphProjection) -> bool:
    pending_states = {"planned", "ready", "leased", "running"}
    return any(
        projection["node_kinds"].get(node_id) == "gate"
        and projection["node_roles"].get(node_id) == "planner_generation_budget_gate"
        and node_state in pending_states
        for node_id, node_state in projection["node_states"].items()
    )


def _node_creation_position(events: list[EventEnvelope], node_id: str) -> int:
    for event in events:
        if event.event_type == "node_created" and event.payload.get("node_id") == node_id:
            return event.position
    return 0


def _latest_lease_generation(events: list[EventEnvelope], node_id: str) -> int | None:
    generation: int | None = None
    for event in events:
        if event.event_type != "lease_granted" or event.payload.get("node_id") != node_id:
            continue
        value = event.payload.get("generation")
        if isinstance(value, int) and not isinstance(value, bool):
            generation = value
    return generation


def _planner_region_label(
    events: list[EventEnvelope],
    projection: GraphProjection,
    node_id: str,
) -> str | None:
    label = projection["planner_region_labels"].get(node_id)
    if label is not None:
        return label
    generation_index = projection["planner_generations"].get(node_id)
    if generation_index is None:
        return None
    labels = _seeded_planner_chain_labels(events)
    return labels.get(generation_index)


def _seeded_planner_chain_labels(events: list[EventEnvelope]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        raw_planner_chain = event.payload.get("planner_chain")
        if not isinstance(raw_planner_chain, dict):
            continue
        planner_chain = cast(dict[str, Any], raw_planner_chain)
        regions = planner_chain.get("regions")
        if not isinstance(regions, list):
            continue
        for raw_region in cast(list[Any], regions):
            if not isinstance(raw_region, dict):
                continue
            region = cast(dict[str, Any], raw_region)
            generation_index = region.get("generation_index")
            region_label = region.get("region_label")
            if (
                isinstance(generation_index, int)
                and not isinstance(generation_index, bool)
                and isinstance(region_label, str)
            ):
                labels.setdefault(generation_index, region_label)
    return labels


def _planner_generation_state(events: list[EventEnvelope], lease_id: str) -> str:
    state = "active"
    for event in events:
        if event.payload.get("lease_id") != lease_id:
            continue
        if event.event_type == "lease_suspended":
            state = "suspended"
        elif event.event_type == "lease_released":
            state = "released"
        elif event.event_type == "lease_revoked":
            state = "revoked"
        elif event.event_type == "lease_expired":
            state = "expired"
    return state


def _ready_nodes(node_states: dict[str, str]) -> list[str]:
    return [node_id for node_id, node_state in node_states.items() if node_state == "ready"]


def _record_candidate(state: GraphProjection, event: EventEnvelope) -> None:
    record_kind = event.payload.get("record_kind")
    if record_kind is not None and record_kind != "output":
        return
    port = event.payload.get("port")
    if port != "candidate" and not isinstance(event.payload.get("candidate_id"), str):
        return

    producer_node_id = event.payload.get("producer_node_id")
    task_region_id = _task_region_id(event.payload)
    if task_region_id is None and isinstance(producer_node_id, str):
        task_region_id = state["node_task_regions"].get(producer_node_id)
    if task_region_id is None:
        return

    candidate_id = _candidate_id(event.payload)
    if candidate_id is None:
        record_id = event.payload.get("record_id")
        candidate_id = record_id if isinstance(record_id, str) else None
    if candidate_id is None:
        return

    attempt_number = _attempt_number(event.payload)
    if attempt_number is None and isinstance(producer_node_id, str):
        attempt_number = state["node_attempts"].get(producer_node_id)
    if attempt_number is None:
        attempt_number = 0

    state["task_candidates"].setdefault(task_region_id, []).append(
        {
            "candidate_id": candidate_id,
            "attempt_number": attempt_number,
            "position": event.position,
        }
    )


def _record_verdict(state: GraphProjection, event: EventEnvelope) -> None:
    candidate_id = _candidate_id(event.payload)
    if candidate_id is None:
        return
    state["verifier_verdicts"][candidate_id] = {
        "candidate_id": candidate_id,
        "verdict": "passed" if event.event_type == "verification_passed" else "failed",
        "position": event.position,
    }


def _record_open_appeal(state: GraphProjection, event: EventEnvelope) -> None:
    appealed_node_id = event.payload.get("appealed_node_id")
    if not isinstance(appealed_node_id, str):
        node_id = event.payload.get("node_id")
        if isinstance(node_id, str) and node_id in state["node_states"]:
            appealed_node_id = node_id
    if isinstance(appealed_node_id, str):
        state["node_pending_appeals"][appealed_node_id] = True

    task_region_id = _task_region_id(event.payload)
    candidate_id = _candidate_id(event.payload)
    if task_region_id is None and candidate_id is not None:
        task_region_id = _task_region_for_candidate(state, candidate_id)
    if task_region_id is None:
        return
    if event.payload.get("appeal_type") == "invalid_test":
        block = dict(state["invalid_test_blocks"].get(task_region_id, {}))
        block.update(
            {
                "appeal_open": True,
                "candidate_id": candidate_id,
                "position": event.position,
            }
        )
        state["invalid_test_blocks"][task_region_id] = block


def _record_oversight_decision(state: GraphProjection, event: EventEnvelope) -> None:
    appealed_node_id = event.payload.get("appealed_node_id")
    if isinstance(appealed_node_id, str):
        state["node_pending_appeals"][appealed_node_id] = False

    task_region_id = _task_region_id(event.payload)
    candidate_id = _candidate_id(event.payload)
    if task_region_id is None and candidate_id is not None:
        task_region_id = _task_region_for_candidate(state, candidate_id)
    if task_region_id is None:
        return

    decision = event.payload.get("decision")
    outcome = event.payload.get("outcome")
    appeal_type = event.payload.get("appeal_type")
    accepted_invalid_test = (
        decision in {"accepted", "invalid_test_accepted"}
        or outcome in {"accepted", "invalid_test_accepted"}
    ) and (appeal_type in {None, "invalid_test"} or outcome == "invalid_test_accepted")
    if accepted_invalid_test:
        state["invalid_test_blocks"][task_region_id] = {
            "accepted": True,
            "candidate_id": candidate_id,
            "position": event.position,
        }


def _record_gate_decision(state: GraphProjection, event: EventEnvelope) -> None:
    task_region_id = _task_region_id(event.payload)
    node_id = event.payload.get("node_id")
    decision = event.payload.get("decision")
    approved = event.payload.get("approved")
    passed = approved is True or decision in {"approved", "passed", "accepted"}
    if isinstance(node_id, str):
        state["node_gate_decisions"][node_id] = passed
    if task_region_id is None and isinstance(node_id, str):
        task_region_id = state["node_task_regions"].get(node_id)
    if task_region_id is None:
        return
    gate_id = event.payload.get("gate_id")
    if not isinstance(gate_id, str):
        gate_id = node_id
    if not isinstance(gate_id, str):
        gate_id = "default"
    state["gate_decisions"].setdefault(task_region_id, {})[gate_id] = passed


def _record_edge(state: GraphProjection, event: EventEnvelope) -> None:
    from_node_id = event.payload.get("from_node_id")
    from_port = event.payload.get("from_port")
    to_node_id = event.payload.get("to_node_id")
    to_port = event.payload.get("to_port")
    if not all(isinstance(value, str) for value in (from_node_id, from_port, to_node_id, to_port)):
        return

    edge_id = event.payload.get("edge_id")
    if not isinstance(edge_id, str):
        edge_id = f"{from_node_id}:{from_port}->{to_node_id}:{to_port}"
    required = event.payload.get("required")
    state["edges"][edge_id] = {
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "required": required is not False,
        "dependency_type": event.payload.get("dependency_type", "input_binding"),
    }
    selector = event.payload.get("accepted_record_selector")
    if isinstance(selector, dict):
        state["edges"][edge_id]["accepted_record_selector"] = dict(cast(dict[str, Any], selector))


def _record_input_binding(state: GraphProjection, event: EventEnvelope) -> None:
    to_node_id = event.payload.get("to_node_id")
    if not isinstance(to_node_id, str):
        return

    to_port = event.payload.get("to_port")
    edge_id = event.payload.get("edge_id")
    if not isinstance(to_port, str) and isinstance(edge_id, str):
        edge = state["edges"].get(edge_id)
        if edge is not None:
            edge_to_port = edge.get("to_port")
            if isinstance(edge_to_port, str):
                to_port = edge_to_port
    if not isinstance(to_port, str):
        legacy_input = event.payload.get("input")
        if isinstance(legacy_input, str):
            to_port = legacy_input
    if not isinstance(to_port, str):
        return

    binding = dict(event.payload)
    binding.setdefault("to_node_id", to_node_id)
    binding.setdefault("to_port", to_port)
    state["input_bindings"].setdefault(to_node_id, {})[to_port] = binding


def _record_authority_change(state: GraphProjection, event: EventEnvelope) -> None:
    node_id = event.payload.get("node_id")
    if not isinstance(node_id, str):
        return

    resource_claims = _resource_claims(event.payload)
    if resource_claims:
        state["node_resource_claims"][node_id] = resource_claims

    allowed_actions = _allowed_actions(event.payload)
    if allowed_actions:
        state["node_allowed_actions"][node_id] = allowed_actions


def _record_environment_failure(state: GraphProjection, event: EventEnvelope) -> None:
    task_region_id = _task_region_id(event.payload)
    node_id = event.payload.get("node_id")
    if task_region_id is None and isinstance(node_id, str):
        task_region_id = state["node_task_regions"].get(node_id)
    if task_region_id is None:
        return

    classification = event.payload.get("classification")
    reason = event.payload.get("reason")
    is_environment = event.event_type == "environment_failure_accepted" or classification in {
        "environment_error",
        "tool_error",
        "tool_unavailable",
    }
    if is_environment:
        state["environment_failures"][task_region_id] = {
            "position": event.position,
            "classification": classification,
            "reason": reason,
        }


def _record_file_state(state: GraphProjection, event: EventEnvelope) -> None:
    record_id = event.payload.get("record_id")
    if not isinstance(record_id, str):
        return
    record = _copy_file_state_record(event.payload)
    record["run_id"] = event.run_id
    record["position"] = event.position
    state["file_state_records"][record_id] = record


def _record_gatekeeper_verdicts(state: GraphProjection, event: EventEnvelope) -> None:
    record_id = event.payload.get("file_state_record_id")
    if not isinstance(record_id, str):
        return
    record = state["file_state_records"].get(record_id)
    if record is None:
        return
    verdicts = event.payload.get("verdicts")
    if not isinstance(verdicts, list):
        return
    by_path: dict[str, dict[str, Any]] = {}
    for raw_verdict in cast(list[Any], verdicts):
        if not isinstance(raw_verdict, dict):
            continue
        verdict = cast(dict[str, Any], raw_verdict)
        path = verdict.get("path")
        if isinstance(path, str):
            by_path[path] = verdict
    for key in ("classifications", "residue", "untracked", "ignored", "external"):
        entries = record.get(key)
        if not isinstance(entries, list):
            continue
        record[key] = [_resolved_file_entry(entry, by_path) for entry in cast(list[Any], entries)]


def _record_cleanup_requested(state: GraphProjection, event: EventEnvelope) -> None:
    record_id = event.payload.get("file_state_record_id")
    if not isinstance(record_id, str):
        return
    record = state["file_state_records"].get(record_id)
    if record is None:
        return
    paths = event.payload.get("paths")
    record["compromised"] = True
    record["superseded_pending"] = True
    record["cleanup_id"] = event.payload.get("cleanup_id")
    record["cleanup_reason"] = event.payload.get("reason")
    record["compromised_paths"] = list(cast(list[Any], paths)) if isinstance(paths, list) else []


def _record_cleanup_applied(state: GraphProjection, event: EventEnvelope) -> None:
    record_id = event.payload.get("file_state_record_id")
    if not isinstance(record_id, str):
        return
    record = state["file_state_records"].get(record_id)
    if record is None:
        return
    record["compromised"] = True
    record["superseded_pending"] = False
    record["superseded_by_record_id"] = event.payload.get("superseding_record_id")
    record["cleanup_applied_event_id"] = event.event_id
    record["compromised_snapshot_deleted"] = event.payload.get("deleted_snapshot_ref") is True


def _resolved_file_entry(
    raw_entry: Any,
    verdicts_by_path: dict[str, dict[str, Any]],
) -> Any:
    if not isinstance(raw_entry, dict):
        return raw_entry
    entry = dict(cast(dict[str, Any], raw_entry))
    path = entry.get("path")
    if not isinstance(path, str) or path not in verdicts_by_path:
        return entry
    verdict = verdicts_by_path[path]
    entry["classification"] = verdict.get("classification")
    entry["matched_rule"] = f"gatekeeper:{verdict.get('model_id', 'unknown')}"
    entry["needs_gatekeeper"] = False
    entry["gatekeeper_confidence"] = verdict.get("confidence")
    entry["gatekeeper_rationale"] = verdict.get("rationale")
    return entry


def _copy_file_state_record(record: dict[str, Any]) -> dict[str, Any]:
    copied = dict(record)
    for key in ("tracked", "untracked", "ignored", "external", "classifications", "residue"):
        value = copied.get(key)
        if isinstance(value, list):
            copied[key] = [
                dict(cast(dict[str, Any], entry)) if isinstance(entry, dict) else entry
                for entry in cast(list[Any], value)
            ]
    return copied


def _derive_gatekeeper_pattern(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    dirname, _, filename = normalized.rpartition("/")
    if not dirname:
        return filename
    stem, dot, extension = filename.rpartition(".")
    if dot and stem:
        glob = f"*.{extension}"
    else:
        glob = filename
    return f"{dirname}/{glob}"


def _merge_pattern_entry(
    patterns: dict[str, dict[str, Any]],
    pattern: str,
    classification: str,
    path: str,
    position: int,
    record_id: Any,
) -> None:
    entry = patterns.get(pattern)
    if entry is None:
        patterns[pattern] = {
            "pattern": pattern,
            "classification": classification,
            "occurrences": 1,
            "paths": [path],
            "source_record_ids": [record_id] if isinstance(record_id, str) else [],
            "source_kinds": ["untracked", "ignored"],
            "first_position": position,
            "last_position": position,
        }
        return
    entry["occurrences"] = int(entry["occurrences"]) + 1
    entry["last_position"] = position
    if path not in entry["paths"]:
        entry["paths"].append(path)
        entry["paths"].sort()
    if isinstance(record_id, str) and record_id not in entry["source_record_ids"]:
        entry["source_record_ids"].append(record_id)


def _file_state_source_by_path(record: dict[str, Any] | None) -> dict[str, str]:
    if record is None:
        return {}
    sources: dict[str, str] = {}
    for key in ("residue", "classifications"):
        entries = record.get(key)
        if not isinstance(entries, list):
            continue
        for raw_entry in cast(list[Any], entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            path = entry.get("path")
            source = entry.get("source")
            if isinstance(path, str) and isinstance(source, str):
                sources[path] = source
    return sources


def _payload_entries(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [
        dict(cast(dict[str, Any], entry))
        for entry in cast(list[Any], value)
        if isinstance(entry, dict)
    ]


def _payload_number(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _payload_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _empty_gatekeeper_report(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "boundary_count": 0,
        "deterministic_classifications": 0,
        "gatekeeper_consults": 0,
        "gatekeeper_resolved": 0,
        "unresolved_residue": 0,
        "total_classified": 0,
        "hit_rate": 0.0,
        "pattern_library_size": 0,
        "pattern_library_size_over_time": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "wall_time_ms": 0,
        "models": {},
    }


def _record_model_cost(run: dict[str, Any], payload: dict[str, Any]) -> None:
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        model_id = "unknown"
    models = cast(dict[str, dict[str, Any]], run["models"])
    model = models.setdefault(
        model_id,
        {
            "model_id": model_id,
            "consults": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_usd": 0.0,
            "wall_time_ms": 0,
            "executions": [],
        },
    )
    model["consults"] += 1
    model["input_tokens"] += _payload_number(payload, "input_tokens")
    model["output_tokens"] += _payload_number(payload, "output_tokens")
    model["cache_read_tokens"] += _payload_number(payload, "cache_read_tokens")
    model["cache_write_tokens"] += _payload_number(payload, "cache_write_tokens")
    model["cost_usd"] += _payload_float(payload, "cost_usd")
    model["wall_time_ms"] += _payload_number(payload, "wall_time_ms")
    execution_id = payload.get("execution_id")
    if isinstance(execution_id, str) and execution_id not in model["executions"]:
        model["executions"].append(execution_id)


def _derive_task_states(state: GraphProjection) -> dict[str, str]:
    task_region_ids = set(state["task_candidates"])
    task_region_ids.update(state["invalid_test_blocks"])
    task_region_ids.update(state["configured_gates"])
    task_region_ids.update(state["gate_decisions"])
    task_region_ids.update(state["environment_failures"])
    task_region_ids.update(
        lease["task_region_id"]
        for lease in state["leases"].values()
        if isinstance(lease.get("task_region_id"), str)
    )
    task_region_ids.update(state["node_task_regions"].values())

    task_states: dict[str, str] = {}
    for task_region_id in sorted(task_region_ids):
        latest_candidate = _latest_candidate(state["task_candidates"].get(task_region_id, []))
        if latest_candidate is None:
            task_states[task_region_id] = (
                "in_progress" if _has_active_task_lease(state, task_region_id) else "pending"
            )
            continue

        candidate_id = latest_candidate["candidate_id"]
        verdict = state["verifier_verdicts"].get(candidate_id)
        configured_gates = state["configured_gates"].get(task_region_id, {})
        gate_decisions = state["gate_decisions"].get(task_region_id, {})
        gates_passed = _all_configured_gates_passed(configured_gates, gate_decisions)
        invalid_block = state["invalid_test_blocks"].get(task_region_id)

        if verdict is not None and verdict.get("verdict") == "passed" and gates_passed:
            task_states[task_region_id] = "accepted"
        elif (
            invalid_block is not None
            and invalid_block.get("accepted") is True
            and not _replacement_verification_passed(state, task_region_id, invalid_block)
        ):
            task_states[task_region_id] = "blocked_invalid_test"
        elif (
            verdict is not None
            and verdict.get("verdict") == "failed"
            and not _active_invalid_test_override(invalid_block, candidate_id)
        ):
            task_states[task_region_id] = "needs_revision"
        elif task_region_id in state["environment_failures"]:
            task_states[task_region_id] = "blocked_environment"
        elif _has_active_task_lease(state, task_region_id):
            task_states[task_region_id] = "in_progress"
        else:
            task_states[task_region_id] = "pending"

    return task_states


def _latest_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(
        candidates, key=lambda candidate: (candidate["attempt_number"], candidate["position"])
    )


def _active_invalid_test_override(block: dict[str, Any] | None, candidate_id: str) -> bool:
    if block is None:
        return False
    return block.get("appeal_open") is True and block.get("candidate_id") == candidate_id


def _all_configured_gates_passed(
    configured_gates: dict[str, bool],
    gate_decisions: dict[str, bool],
) -> bool:
    return all(gate_decisions.get(gate_id) is True for gate_id in configured_gates) and all(
        gate_decisions.values()
    )


def _replacement_verification_passed(
    state: GraphProjection,
    task_region_id: str,
    invalid_block: dict[str, Any],
) -> bool:
    block_position = invalid_block.get("position")
    if not isinstance(block_position, int):
        return False
    for candidate in state["task_candidates"].get(task_region_id, []):
        verdict = state["verifier_verdicts"].get(candidate["candidate_id"])
        if (
            verdict is not None
            and verdict.get("verdict") == "passed"
            and candidate["position"] > block_position
        ):
            return True
    return False


def _has_active_task_lease(state: GraphProjection, task_region_id: str) -> bool:
    for lease in state["leases"].values():
        if lease.get("state") != "active":
            continue
        if lease.get("task_region_id") != task_region_id:
            continue
        if lease.get("kind") in {"worker", "verifier", "check"}:
            return True
    return False


def _task_region_for_candidate(state: GraphProjection, candidate_id: str) -> str | None:
    for task_region_id, candidates in state["task_candidates"].items():
        if any(candidate.get("candidate_id") == candidate_id for candidate in candidates):
            return task_region_id
    return None


def _task_region_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("task_region_id")
    if isinstance(value, str):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("task_region_id")
        if isinstance(value, str):
            return value
    return None


def _attempt_number(payload: dict[str, Any]) -> int | None:
    value = payload.get("attempt_number")
    if isinstance(value, int):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("attempt_number")
        if isinstance(value, int):
            return value
    return None


def _candidate_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("candidate_id")
    if isinstance(value, str):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("candidate_id")
        if isinstance(value, str):
            return value
    return None


def _failed_candidate_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("failed_candidate_id")
    if isinstance(value, str):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("failed_candidate_id")
        if isinstance(value, str):
            return value
    return None


def _resource_claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_claims = payload.get("resource_claims")
    if raw_claims is None:
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_claims = cast(dict[str, Any], authority).get("resource_claims")
    if not isinstance(raw_claims, list):
        return []
    claims: list[dict[str, Any]] = []
    for raw_claim in cast(list[Any], raw_claims):
        if isinstance(raw_claim, dict):
            claims.append(dict(cast(dict[str, Any], raw_claim)))
    return claims


def _allowed_actions(payload: dict[str, Any]) -> list[str]:
    raw_actions = payload.get("allowed_actions")
    if raw_actions is None:
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_actions = cast(dict[str, Any], authority).get("allowed_actions")
    if not isinstance(raw_actions, list):
        return []
    return [action for action in cast(list[Any], raw_actions) if isinstance(action, str)]


def _preconditions(payload: dict[str, Any]) -> list[str]:
    raw_preconditions = payload.get("preconditions")
    if not isinstance(raw_preconditions, list):
        return []
    return [
        precondition
        for precondition in cast(list[Any], raw_preconditions)
        if isinstance(precondition, str)
    ]


def _command_definition(payload: dict[str, Any]) -> Any | None:
    command_definition = payload.get("command_definition")
    if isinstance(command_definition, dict):
        return dict(cast(dict[str, Any], command_definition))
    command_definition_id = payload.get("command_definition_id")
    if isinstance(command_definition_id, str):
        return command_definition_id
    return None
