"""Pure graph projections for scenario fixtures."""

from typing import Any, Literal, TypedDict, cast

from orchestrator.graph.command_bindings import check_command_reference
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
    node_contract_summary,
    output_port_contract,
    port_contract_summary,
)
from orchestrator.graph.models import EventEnvelope, GraphPatchResultRecord


_EDGE_METADATA_KEYS = (
    "purpose",
    "description",
    "selection",
    "binding_policy",
    "freshness_policy",
    "prompt_hydration_policy",
    "metadata",
)


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
    node_output_ports: dict[str, dict[str, list[str]]]
    edges: dict[str, dict[str, Any]]
    input_bindings: dict[str, dict[str, dict[str, Any]]]
    node_pending_appeals: dict[str, bool]
    node_gate_decisions: dict[str, bool]
    task_candidates: dict[str, list[dict[str, Any]]]
    verifier_verdicts: dict[str, dict[str, Any]]
    check_results: dict[str, dict[str, Any]]
    invalid_test_blocks: dict[str, dict[str, Any]]
    configured_gates: dict[str, dict[str, bool]]
    gate_decisions: dict[str, dict[str, bool]]
    environment_failures: dict[str, dict[str, Any]]
    file_state_records: dict[str, dict[str, Any]]
    planner_generation_budget: int
    planner_successors: dict[str, str]
    accepted_graph_patches_by_node: dict[str, list[str]]
    planner_generations: dict[str, int]
    planner_sessions: dict[str, str]
    planner_session_states: dict[str, str]
    planner_session_current_nodes: dict[str, str]
    planner_session_carryovers: dict[str, str | None]
    planner_region_labels: dict[str, str]
    requirement_revisions: dict[str, dict[str, Any]]
    active_requirement_versions: dict[str, str]
    support_evidence: dict[str, dict[str, Any]]


class GraphRecordSummary(TypedDict, total=False):
    record_id: str
    record_type: str
    record_kind: str
    schema: str
    producer_node_id: str
    producer_port: str
    position: int


class GraphTopologyBinding(TypedDict, total=False):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int
    record_bound_positions: dict[str, int]
    binding_policy: str
    trigger: str


class GraphTopologyNode(TypedDict, total=False):
    node_id: str
    kind: str | None
    role: str | None
    state: str | None
    contract: dict[str, Any]


class GraphTopologyEdge(TypedDict, total=False):
    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool
    dependency_type: str
    accepted_record_selector: dict[str, Any]
    metadata: dict[str, Any]
    source_port_contract: dict[str, Any]
    target_port_contract: dict[str, Any]
    record_types: list[str]
    binding: GraphTopologyBinding | None
    bound_records: list[GraphRecordSummary]


class GraphTopologyView(TypedDict):
    nodes: list[GraphTopologyNode]
    edges: list[GraphTopologyEdge]


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


class PendingGateDecision(TypedDict, total=False):
    node_id: str
    gate_type: str
    prompt: str | None
    options: list[str]
    default_option: str
    consequence_summary: str
    expires_at: str
    requested_authority: list[str]
    target_node_id: str
    target_region_id: str


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


class SupportEvidenceFreshness(TypedDict):
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str
    status: str
    freshness: Literal["fresh", "stale"]
    stale_reason: str | None


class RequirementFreshnessFact(TypedDict):
    requirement_id: str
    active_version_id: str
    revision_classification: str
    requires_authority: bool
    authority_required_reason: str | None
    fresh_support_ids: list[str]
    stale_support_ids: list[str]
    unsupported: bool


class FinalInvariantBlocker(TypedDict, total=False):
    kind: str
    reason: str
    node_id: str
    edge_id: str
    to_port: str
    proposal_id: str
    requirement_id: str
    revision_id: str
    task_region_id: str
    state: str
    classification: str
    command_text: str
    stderr: str
    exit_code: int
    support_ids: list[str]


class GraphPatchAttempt(TypedDict, total=False):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: int
    current_graph_position: int
    status: Literal["accepted", "rejected"]
    rejection_reason: str
    diagnostics: dict[str, Any]
    read_set_diff: dict[str, Any]
    accepted_event_id: str
    accepted_position: int
    rejected_event_id: str
    rejected_position: int
    created_node_ids: list[str]
    created_edge_ids: list[str]


class GraphPatchAttemptView(TypedDict):
    run_id: str
    current_graph_position: int
    attempts: list[GraphPatchAttempt]


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
        "node_output_ports": {},
        "edges": {},
        "input_bindings": {},
        "node_pending_appeals": {},
        "node_gate_decisions": {},
        "task_candidates": {},
        "verifier_verdicts": {},
        "check_results": {},
        "invalid_test_blocks": {},
        "configured_gates": {},
        "gate_decisions": {},
        "environment_failures": {},
        "file_state_records": {},
        "planner_generation_budget": 8,
        "planner_successors": {},
        "accepted_graph_patches_by_node": {},
        "planner_generations": {},
        "planner_sessions": {},
        "planner_session_states": {},
        "planner_session_current_nodes": {},
        "planner_session_carryovers": {},
        "planner_region_labels": {},
        "requirement_revisions": {},
        "active_requirement_versions": {},
        "support_evidence": {},
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
        "node_output_ports": {
            node_id: {port: list(record_ids) for port, record_ids in ports.items()}
            for node_id, ports in state.get("node_output_ports", {}).items()
        },
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
        "check_results": {
            node_id: dict(result) for node_id, result in state.get("check_results", {}).items()
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
        "accepted_graph_patches_by_node": {
            node_id: list(patch_ids)
            for node_id, patch_ids in state.get("accepted_graph_patches_by_node", {}).items()
        },
        "planner_generations": dict(state.get("planner_generations", {})),
        "planner_sessions": dict(state.get("planner_sessions", {})),
        "planner_session_states": dict(state.get("planner_session_states", {})),
        "planner_session_current_nodes": dict(state.get("planner_session_current_nodes", {})),
        "planner_session_carryovers": dict(state.get("planner_session_carryovers", {})),
        "planner_region_labels": dict(state.get("planner_region_labels", {})),
        "requirement_revisions": {
            version_id: dict(revision)
            for version_id, revision in state.get("requirement_revisions", {}).items()
        },
        "active_requirement_versions": dict(state.get("active_requirement_versions", {})),
        "support_evidence": {
            support_id: dict(support)
            for support_id, support in state.get("support_evidence", {}).items()
        },
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
            attempt_number = _attempt_number(event.payload)
            if attempt_number is not None:
                next_state["node_attempts"][node_id] = attempt_number
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
    elif event.event_type == "lease_renewed":
        lease_id = event.payload.get("lease_id")
        if isinstance(lease_id, str):
            lease = dict(next_state["leases"].get(lease_id, {"lease_id": lease_id}))
            lease["state"] = "active"
            for key in ("node_id", "generation", "execution_id", "expires_at"):
                value = event.payload.get(key)
                if value is not None:
                    lease[key] = value
            next_state["leases"][lease_id] = lease
    elif event.event_type == "output_record_accepted":
        _record_node_output_port(next_state, event)
        _record_candidate(next_state, event)
        _record_check_result(next_state, event)
        _record_environment_failure(next_state, event)
    elif event.event_type in {"verification_passed", "verification_failed"}:
        _record_verdict(next_state, event)
    elif event.event_type == "appeal_opened":
        _record_open_appeal(next_state, event)
    elif event.event_type == "oversight_decision_recorded":
        _record_oversight_decision(next_state, event)
    elif event.event_type == "approval_decision_recorded":
        _record_gate_decision(next_state, event)
    elif event.event_type == "authority_decision_recorded":
        _record_authority_decision(next_state, event)
    elif event.event_type == "node_authority_changed":
        _record_authority_change(next_state, event)
    elif event.event_type in {"environment_failure_accepted", "check_result_classified"}:
        _record_environment_failure(next_state, event)
    elif event.event_type == "file_state_accepted":
        _record_node_output_port(next_state, event)
        _record_file_state(next_state, event)
    elif event.event_type == "graph_patch_accepted":
        planner_node_id = event.payload.get("proposed_by_node_id")
        patch_id = event.payload.get("patch_id")
        if isinstance(planner_node_id, str) and isinstance(patch_id, str):
            accepted = list(next_state["accepted_graph_patches_by_node"].get(planner_node_id, []))
            accepted.append(patch_id)
            next_state["accepted_graph_patches_by_node"][planner_node_id] = accepted
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
    elif event.event_type in {"requirement_revision_recorded", "requirement_amended"}:
        _record_requirement_revision(next_state, event)
    elif event.event_type in {"support_evidence_recorded", "support_edge_recorded"}:
        _record_support_evidence(next_state, event)
    # node_ready/node_deferred and agent_died/runtime_retry_scheduled are
    # audit/policy facts. Projection facts are updated only by lease_* and
    # node_state_changed events so replay has a single state authority.

    next_state["ready_nodes"] = _ready_nodes(next_state["node_states"])
    next_state["task_states"] = _derive_task_states(next_state)
    return next_state


def project_run_state(events: list[EventEnvelope]) -> str | None:
    projection = _project(events)
    run_state = projection["run_state"]
    blockers = final_invariant_blockers_for_events(events, projection)
    if run_state == "completed":
        if blockers:
            return "active"
        return run_state
    if run_state != "active":
        return run_state
    if blockers:
        return run_state
    task_states = projection["task_states"]
    if task_states and all(state == "accepted" for state in task_states.values()):
        return "completed"
    return run_state


def project_final_invariant_blockers(events: list[EventEnvelope]) -> list[FinalInvariantBlocker]:
    return final_invariant_blockers_for_events(events, _project(events))


def final_invariant_blockers_for_events(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    include_completion_decision: bool = True,
) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    pending_states = {"planned", "ready", "leased", "running", "blocked", "suspended"}
    for node_id, node_state in sorted(projection["node_states"].items()):
        kind = projection["node_kinds"].get(node_id)
        role = projection["node_roles"].get(node_id)
        is_planner = kind == "planner" and role == "planner"
        is_gap_planner = kind == "gap_planner" or role == "gap_planner"
        if (is_planner or is_gap_planner) and node_state in pending_states:
            blockers.append(
                {
                    "kind": "pending_gap_planner" if is_gap_planner else "pending_planner",
                    "reason": "planner node has not completed",
                    "node_id": node_id,
                    "state": node_state,
                }
            )
            continue
        if (
            kind == "gate"
            and role == "planner_generation_budget_gate"
            and node_state in pending_states
        ):
            blockers.append(
                {
                    "kind": "pending_planner_generation_budget_gate",
                    "reason": "planner generation budget gate is unresolved",
                    "node_id": node_id,
                    "state": node_state,
                }
            )
            continue
        if kind == "check" and node_state in pending_states:
            blockers.append(
                {
                    "kind": "pending_check",
                    "reason": "check node has not completed",
                    "node_id": node_id,
                    "state": node_state,
                }
            )
    blockers.extend(_open_proposal_blockers(events))
    blockers.extend(_suspect_node_blockers(events, projection))
    blockers.extend(_requirement_evidence_blockers(events, projection))
    blockers.extend(_authority_revision_blockers(events))
    blockers.extend(_blocked_requirement_node_blockers(events, projection))
    blockers.extend(_impossible_input_blockers(projection))
    blockers.extend(_failed_check_result_blockers(events))
    if include_completion_decision:
        blockers.extend(_completion_decision_blockers(events, projection))
    blockers.extend(_node_fulfillment_blockers(projection))
    blockers.extend(_non_terminal_node_blockers(projection, blockers, pending_states))
    for task_region_id, task_state in sorted(projection["task_states"].items()):
        if task_state == "accepted":
            continue
        blockers.append(
            {
                "kind": "task_not_accepted",
                "reason": "task region has not reached accepted",
                "task_region_id": task_region_id,
                "state": task_state,
            }
        )
    return blockers


def _node_fulfillment_blockers(projection: GraphProjection) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    for node_id, node_state in sorted(projection["node_states"].items()):
        if node_state in {"cancelled", "retired"}:
            continue
        if node_state not in {"completed", "failed"}:
            continue
        contract = _contract_for_node(projection, node_id)
        if contract is None or contract.fulfillment_contribution == "none":
            continue
        if contract.fulfillment_contribution == "task_acceptance":
            continue
        if contract.node_type == "final_gate":
            continue
        missing_ports = _missing_fulfillment_ports(projection, node_id)
        if not missing_ports:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "node_unfulfilled",
            "reason": "node contract fulfillment outputs are missing",
            "node_id": node_id,
            "state": node_state,
            "support_ids": missing_ports,
        }
        task_region_id = projection["node_task_regions"].get(node_id)
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _impossible_input_blockers(projection: GraphProjection) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    terminal_states = {"completed", "failed", "cancelled", "retired"}
    for edge_id, edge in sorted(projection["edges"].items()):
        if edge.get("required") is False:
            continue
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not all(isinstance(value, str) for value in (from_node_id, to_node_id, to_port)):
            continue
        if projection["node_states"].get(str(to_node_id)) in terminal_states:
            continue
        if str(from_node_id) in projection["node_states"]:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "impossible_input",
            "reason": "required input edge has no producer node",
            "node_id": str(to_node_id),
            "edge_id": str(edge_id),
            "to_port": str(to_port),
            "state": projection["node_states"].get(str(to_node_id), "unknown"),
        }
        task_region_id = projection["node_task_regions"].get(str(to_node_id))
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _non_terminal_node_blockers(
    projection: GraphProjection,
    existing_blockers: list[FinalInvariantBlocker],
    pending_states: set[str],
) -> list[FinalInvariantBlocker]:
    blocked_node_ids = {
        node_id
        for blocker in existing_blockers
        if isinstance((node_id := blocker.get("node_id")), str)
    }
    blockers: list[FinalInvariantBlocker] = []
    for node_id, node_state in sorted(projection["node_states"].items()):
        if (
            node_id in blocked_node_ids
            or node_state not in pending_states
            or projection["node_kinds"].get(node_id) == "final_gate"
        ):
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": node_id,
            "state": node_state,
        }
        task_region_id = projection["node_task_regions"].get(node_id)
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _failed_check_result_blockers(events: list[EventEnvelope]) -> list[FinalInvariantBlocker]:
    blockers_by_record: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        if not _is_check_result_record(event.payload):
            continue
        status = _check_result_status(event.payload)
        if status is None:
            continue
        if status in {"passed", "pass", "ok"}:
            continue
        record_id = event.payload.get("record_id")
        key = record_id if isinstance(record_id, str) else f"position-{event.position}"
        blocker: FinalInvariantBlocker = {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
        }
        value = event.payload.get("value")
        if isinstance(value, dict):
            typed_value = cast(dict[str, Any], value)
            classification = typed_value.get("classification")
            command_text = typed_value.get("command_text")
            stderr = typed_value.get("stderr")
            exit_code = typed_value.get("exit_code")
            if isinstance(classification, str):
                blocker["classification"] = classification
            if isinstance(command_text, str):
                blocker["command_text"] = command_text
            if isinstance(stderr, str):
                blocker["stderr"] = stderr
            if isinstance(exit_code, int) and (
                isinstance(command_text, str)
                or isinstance(stderr, str)
                or isinstance(classification, str)
            ):
                blocker["exit_code"] = exit_code
            if classification in {"environment_error", "tool_error", "tool_unavailable"}:
                blocker["reason"] = _environment_failure_reason_from_check_value(typed_value)
        node_id = event.payload.get("producer_node_id") or event.payload.get("node_id")
        if isinstance(node_id, str):
            blocker["node_id"] = node_id
        task_region_id = event.payload.get("task_region_id")
        if isinstance(task_region_id, str):
            blocker["task_region_id"] = task_region_id
        blocker["state"] = status
        blockers_by_record[key] = blocker
    return [blockers_by_record[key] for key in sorted(blockers_by_record)]


def _is_check_result_record(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "check_result"
        or payload.get("port") == "check_result"
        or payload.get("record_kind") == "check_result"
    )


def _check_result_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str):
        return status.lower()
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status.lower()
    return None


def _completion_decision_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    final_gate_node_ids = {
        node_id
        for node_id, kind in projection["node_kinds"].items()
        if kind == "final_gate" and projection["node_states"].get(node_id) != "retired"
    }
    if not final_gate_node_ids:
        return []

    latest: dict[str, tuple[str, list[FinalInvariantBlocker]]] = {}
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        node_id = event.payload.get("producer_node_id")
        if not isinstance(node_id, str) or node_id not in final_gate_node_ids:
            continue
        if event.payload.get("port") != "completion_decision":
            continue
        status = _completion_decision_status(event.payload)
        if status is None:
            continue
        latest[node_id] = (status, _completion_decision_payload_blockers(event.payload))

    blockers: list[FinalInvariantBlocker] = []
    for node_id in sorted(final_gate_node_ids):
        decision = latest.get(node_id)
        if decision is None:
            blockers.append(
                {
                    "kind": "missing_completion_decision",
                    "reason": "final gate has not produced a completion_decision",
                    "node_id": node_id,
                    "state": projection["node_states"].get(node_id, "unknown"),
                }
            )
            continue
        status, decision_blockers = decision
        if status == "passed":
            continue
        if decision_blockers:
            blockers.extend(decision_blockers)
            continue
        blockers.append(
            {
                "kind": "blocked_completion_decision",
                "reason": "final gate completion_decision is blocked",
                "node_id": node_id,
                "state": projection["node_states"].get(node_id, "unknown"),
            }
        )
    return blockers


def _completion_decision_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str):
        return status
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status
    return None


def _completion_decision_payload_blockers(payload: dict[str, Any]) -> list[FinalInvariantBlocker]:
    value = payload.get("value")
    raw_blockers: Any = payload.get("blockers")
    if raw_blockers is None and isinstance(value, dict):
        raw_blockers = cast(dict[str, Any], value).get("blockers")
    if not isinstance(raw_blockers, list):
        return []
    blockers: list[FinalInvariantBlocker] = []
    for raw_blocker in cast(list[Any], raw_blockers):
        if not isinstance(raw_blocker, dict):
            continue
        blocker = cast(dict[str, Any], raw_blocker)
        kind = blocker.get("kind")
        reason = blocker.get("reason")
        if not isinstance(kind, str) or not isinstance(reason, str):
            continue
        blockers.append(cast(FinalInvariantBlocker, dict(blocker)))
    return blockers


def _open_proposal_blockers(events: list[EventEnvelope]) -> list[FinalInvariantBlocker]:
    open_proposals: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        proposal_id = _proposal_id(event.payload)
        if proposal_id is None:
            continue
        if event.event_type in {
            "graph_patch_proposed",
            "planner_proposal_opened",
            "proposal_opened",
            "proposal_recorded",
        }:
            status = event.payload.get("status")
            if status in {"accepted", "rejected", "resolved", "closed"}:
                open_proposals.pop(proposal_id, None)
                continue
            open_proposals[proposal_id] = {
                "kind": "open_planner_proposal",
                "reason": "planner proposal has not been accepted or rejected",
                "proposal_id": proposal_id,
            }
        elif event.event_type in {
            "graph_patch_accepted",
            "graph_patch_rejected",
            "proposal_accepted",
            "proposal_rejected",
            "proposal_resolved",
            "proposal_closed",
        }:
            open_proposals.pop(proposal_id, None)
    return [open_proposals[key] for key in sorted(open_proposals)]


def _suspect_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    suspect_nodes: dict[str, str] = {}
    for event in events:
        if event.event_type in {"plan_region_marked_suspect", "node_marked_suspect"}:
            reason = _payload_reason(event.payload, "suspect graph fact remains unresolved")
            for node_id in _payload_node_ids(event.payload):
                suspect_nodes[node_id] = reason
        elif event.event_type in {
            "plan_region_suspect_resolved",
            "node_suspect_resolved",
            "plan_region_suspect_cleared",
            "node_suspect_cleared",
        }:
            for node_id in _payload_node_ids(event.payload):
                suspect_nodes.pop(node_id, None)

    blockers: list[FinalInvariantBlocker] = []
    inactive_states = {"completed", "failed", "cancelled", "retired"}
    for node_id in sorted(suspect_nodes):
        node_state = projection["node_states"].get(node_id)
        if node_state in inactive_states:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "suspect_active_node",
            "reason": suspect_nodes[node_id],
            "node_id": node_id,
        }
        if node_state is not None:
            blocker["state"] = node_state
        blockers.append(blocker)
    return blockers


def _requirement_evidence_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    for fact in requirement_freshness_facts_from_projection(projection):
        if fact["unsupported"]:
            stale_support_ids = list(fact["stale_support_ids"])
            if stale_support_ids:
                blockers.append(
                    {
                        "kind": "stale_support_evidence",
                        "reason": "active requirement is supported only by stale evidence",
                        "requirement_id": fact["requirement_id"],
                        "support_ids": stale_support_ids,
                    }
                )
            blockers.append(
                {
                    "kind": "unsupported_active_requirement",
                    "reason": "active requirement has no current supporting evidence",
                    "requirement_id": fact["requirement_id"],
                    "support_ids": stale_support_ids,
                }
            )

    if blockers:
        return blockers
    return _legacy_requirement_evidence_blockers(events)


def _legacy_requirement_evidence_blockers(
    events: list[EventEnvelope],
) -> list[FinalInvariantBlocker]:
    blockers_by_requirement: dict[tuple[str, str], FinalInvariantBlocker] = {}
    freshness_events = {
        "requirement_support_evaluated",
        "requirement_freshness_evaluated",
        "requirement_evidence_freshness_recorded",
    }
    for event in events:
        if event.event_type not in freshness_events:
            continue
        requirement_id = _requirement_id(event.payload)
        if requirement_id is None:
            continue
        support_ids = _payload_string_list(event.payload, "support_ids")
        if event.payload.get("supported") is True or event.payload.get("freshness") == "fresh":
            blockers_by_requirement.pop(("unsupported_active_requirement", requirement_id), None)
            blockers_by_requirement.pop(("stale_support_evidence", requirement_id), None)
            continue
        if _payload_truthy(event.payload, "unsupported") or event.payload.get("supported") is False:
            blockers_by_requirement[("unsupported_active_requirement", requirement_id)] = {
                "kind": "unsupported_active_requirement",
                "reason": "active requirement has no current supporting evidence",
                "requirement_id": requirement_id,
                "support_ids": support_ids,
            }
        if _is_stale_only_evidence(event.payload):
            blockers_by_requirement[("stale_support_evidence", requirement_id)] = {
                "kind": "stale_support_evidence",
                "reason": "active requirement is supported only by stale evidence",
                "requirement_id": requirement_id,
                "support_ids": support_ids,
            }
    return [
        blockers_by_requirement[key]
        for key in sorted(blockers_by_requirement, key=lambda item: (item[0], item[1]))
    ]


def _authority_revision_blockers(events: list[EventEnvelope]) -> list[FinalInvariantBlocker]:
    unresolved: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        revision_id = _revision_id(event.payload)
        if revision_id is None:
            continue
        if event.event_type in {
            "requirement_revision_recorded",
            "requirement_amended",
            "requirement_revision_proposed",
        }:
            if not _requires_authority_resolution(event.payload):
                continue
            blocker: FinalInvariantBlocker = {
                "kind": "unresolved_authority_required_revision",
                "reason": "semantic or new-behavior requirement revision lacks authority resolution",
                "revision_id": revision_id,
            }
            requirement_id = _requirement_id(event.payload)
            if requirement_id is not None:
                blocker["requirement_id"] = requirement_id
            unresolved[revision_id] = blocker
        elif event.event_type in {
            "authority_resolution_recorded",
            "authority_resolved",
            "requirement_revision_authorized",
        }:
            unresolved.pop(revision_id, None)
    return [unresolved[key] for key in sorted(unresolved)]


def _blocked_requirement_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    payloads = _latest_node_creation_payloads(events)
    blockers: list[FinalInvariantBlocker] = []
    for node_id, node_state in sorted(projection["node_states"].items()):
        if projection["node_kinds"].get(node_id) != "requirement" or node_state != "blocked":
            continue
        payload = payloads.get(node_id, {})
        priority = _requirement_priority(payload)
        if priority not in {"must", "expected", "critical"}:
            continue
        requirement_id = _requirement_id(payload) or node_id
        blockers.append(
            {
                "kind": "blocked_requirement",
                "reason": "must or expected requirement is blocked without accepted blocker",
                "node_id": node_id,
                "requirement_id": requirement_id,
                "state": node_state,
            }
        )
    return blockers


def _proposal_id(payload: dict[str, Any]) -> str | None:
    for key in ("proposal_id", "patch_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _revision_id(payload: dict[str, Any]) -> str | None:
    for key in ("revision_id", "version_id", "requirement_version_id", "proposal_id", "patch_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _requirement_id(payload)


def _requirement_id(payload: dict[str, Any]) -> str | None:
    for key in ("requirement_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        value = cast(dict[str, Any], requirement).get("id")
        if isinstance(value, str) and value:
            return value
    node_id = payload.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_id
    return None


def _payload_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[Any], value) if isinstance(item, str)]


def _payload_node_ids(payload: dict[str, Any]) -> list[str]:
    node_ids = _payload_string_list(payload, "node_ids")
    node_ids.extend(_payload_string_list(payload, "region_node_ids"))
    node_id = payload.get("node_id")
    if isinstance(node_id, str):
        node_ids.append(node_id)
    region_id = payload.get("region_id")
    if isinstance(region_id, str):
        node_ids.append(region_id)
    return sorted(set(node_ids))


def _payload_reason(payload: dict[str, Any], fallback: str) -> str:
    reason = payload.get("reason")
    return reason if isinstance(reason, str) and reason else fallback


def _payload_truthy(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _is_stale_only_evidence(payload: dict[str, Any]) -> bool:
    if payload.get("stale_only") is True:
        return True
    for key in ("freshness", "status", "evidence_freshness"):
        value = payload.get(key)
        if value in {"stale_only", "stale"}:
            return True
    return False


def _requires_authority_resolution(payload: dict[str, Any]) -> bool:
    if payload.get("requires_authority") is True:
        return True
    if payload.get("semantic_change") is True:
        return True
    revision_type = payload.get("revision_type")
    if not isinstance(revision_type, str):
        revision_type = payload.get("classification")
    return revision_type in {
        "semantic",
        "new_behavior",
        "new-behavior",
        "scope_expansion",
        "scope_reduction",
        "priority_change",
    }


def _requirement_priority(payload: dict[str, Any]) -> str | None:
    priority = payload.get("priority")
    if isinstance(priority, str):
        return priority.lower()
    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        value = cast(dict[str, Any], requirement).get("priority")
        if isinstance(value, str):
            return value.lower()
    return None


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
    metadata: dict[str, dict[str, Any]] = {}
    for node_id in projection["node_states"]:
        kind = projection["node_kinds"].get(node_id)
        role = projection["node_roles"].get(node_id)
        detail: dict[str, Any] = {
            "kind": projection["node_kinds"].get(node_id),
            "role": projection["node_roles"].get(node_id),
            "task_region_id": projection["node_task_regions"].get(node_id),
            "input_ports": {
                port: _bound_record_ids(binding)
                for port, binding in projection["input_bindings"].get(node_id, {}).items()
            },
            "resource_claims": list(projection["node_resource_claims"].get(node_id, [])),
            "allowed_actions": list(projection["node_allowed_actions"].get(node_id, [])),
            "preconditions": list(projection["node_preconditions"].get(node_id, [])),
        }
        command_definition = projection["node_command_definitions"].get(node_id)
        if command_definition is not None:
            detail["command_definition"] = command_definition
        contract = node_contract_summary(kind, role)
        if contract is not None:
            detail["contract"] = contract
        metadata[node_id] = detail
    return metadata


def project_graph_topology(events: list[EventEnvelope]) -> GraphTopologyView:
    projection = _project(events)
    record_summaries = _record_summaries_by_id(events, projection)
    nodes: list[GraphTopologyNode] = []
    for node_id in sorted(projection["node_states"]):
        kind = projection["node_kinds"].get(node_id)
        role = projection["node_roles"].get(node_id)
        node: GraphTopologyNode = {
            "node_id": node_id,
            "kind": kind,
            "role": role,
            "state": projection["node_states"].get(node_id),
        }
        contract = node_contract_summary(kind, role)
        if contract is not None:
            node["contract"] = contract
        nodes.append(node)

    edges = [
        _topology_edge(edge, projection, record_summaries)
        for _, edge in sorted(projection["edges"].items())
    ]
    return {"nodes": nodes, "edges": edges}


def project_graph_patch_attempts(
    events: list[EventEnvelope],
    *,
    run_id: str = "",
    current_graph_position: int | None = None,
) -> GraphPatchAttemptView:
    attempts: dict[str, GraphPatchAttempt] = {}
    order: list[str] = []
    active_patch_id: str | None = None

    def ensure_attempt(patch_id: str) -> GraphPatchAttempt:
        attempt = attempts.get(patch_id)
        if attempt is None:
            attempt = GraphPatchAttempt(
                patch_id=patch_id,
                created_node_ids=[],
                created_edge_ids=[],
            )
            attempts[patch_id] = attempt
            order.append(patch_id)
        return attempt

    for event in events:
        payload = event.payload
        patch_id = _patch_id(payload)
        if event.event_type == "graph_patch_proposed" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            _apply_patch_payload(attempt, payload)
            active_patch_id = patch_id
            continue
        if event.event_type == "graph_patch_accepted" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            attempt["status"] = "accepted"
            attempt["accepted_event_id"] = event.event_id
            attempt["accepted_position"] = event.position
            _apply_patch_payload(attempt, payload)
            if current_graph_position is not None:
                attempt["current_graph_position"] = current_graph_position
            active_patch_id = patch_id
            continue
        if event.event_type == "graph_patch_rejected" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            attempt["status"] = "rejected"
            attempt["rejected_event_id"] = event.event_id
            attempt["rejected_position"] = event.position
            _apply_patch_payload(attempt, payload)
            if current_graph_position is not None:
                attempt["current_graph_position"] = current_graph_position
            active_patch_id = None
            continue
        if active_patch_id is None:
            continue
        attempt = attempts.get(active_patch_id)
        if attempt is None:
            continue
        if event.event_type == "node_created":
            node_id = payload.get("node_id")
            if isinstance(node_id, str):
                created = attempt.setdefault("created_node_ids", [])
                created.append(node_id)
        elif event.event_type == "edge_created":
            edge_id = payload.get("edge_id")
            if isinstance(edge_id, str):
                created = attempt.setdefault("created_edge_ids", [])
                created.append(edge_id)
        else:
            active_patch_id = None

    if current_graph_position is None:
        current_graph_position = max((event.position for event in events), default=0)
    ordered_attempts: list[GraphPatchAttempt] = []
    for patch_id in order:
        attempt = attempts[patch_id]
        if "status" not in attempt:
            continue
        attempt.setdefault("current_graph_position", current_graph_position)
        ordered_attempts.append(
            cast(
                GraphPatchAttempt,
                GraphPatchResultRecord.model_validate(attempt).model_dump(mode="json"),
            )
        )
    return {
        "run_id": run_id,
        "current_graph_position": current_graph_position,
        "attempts": ordered_attempts,
    }


def _apply_patch_payload(attempt: GraphPatchAttempt, payload: dict[str, Any]) -> None:
    proposed_by_node_id = payload.get("proposed_by_node_id")
    if isinstance(proposed_by_node_id, str):
        attempt["proposed_by_node_id"] = proposed_by_node_id
    base_graph_position = payload.get("base_graph_position")
    if (
        isinstance(base_graph_position, int)
        and not isinstance(base_graph_position, bool)
        and base_graph_position >= 0
    ):
        attempt["base_graph_position"] = base_graph_position
    reason = payload.get("reason")
    if isinstance(reason, str) and reason:
        attempt["rejection_reason"] = reason
    read_set_diff = payload.get("read_set_diff")
    if isinstance(read_set_diff, dict):
        attempt["read_set_diff"] = cast(dict[str, Any], read_set_diff)
    diagnostics = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "patch_id",
            "proposed_by_node_id",
            "base_graph_position",
            "reason",
            "read_set_diff",
        }
    }
    if diagnostics:
        attempt["diagnostics"] = diagnostics


def _patch_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("patch_id")
    if isinstance(value, str) and value:
        return value
    return None


def project_task_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["task_states"]


def project_requirement_revisions(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    return _project(events)["requirement_revisions"]


def support_evidence_freshness_from_projection(
    projection: GraphProjection,
) -> dict[str, SupportEvidenceFreshness]:
    freshness: dict[str, SupportEvidenceFreshness] = {}
    for support_id, support in sorted(projection.get("support_evidence", {}).items()):
        evidence_id = support.get("evidence_id")
        requirement_id = support.get("requirement_id")
        requirement_version_id = support.get("requirement_version_id")
        if not isinstance(evidence_id, str):
            continue
        if not isinstance(requirement_id, str):
            continue
        if not isinstance(requirement_version_id, str):
            continue
        stale_reason = _support_stale_reason(projection, support)
        is_fresh = stale_reason is None and support.get("status", "active") == "active"
        freshness[support_id] = {
            "support_id": support_id,
            "evidence_id": evidence_id,
            "requirement_id": requirement_id,
            "requirement_version_id": requirement_version_id,
            "status": str(support.get("status", "active")),
            "freshness": "fresh" if is_fresh else "stale",
            "stale_reason": stale_reason,
        }
    return freshness


def project_support_evidence_freshness(
    events: list[EventEnvelope],
) -> dict[str, SupportEvidenceFreshness]:
    return support_evidence_freshness_from_projection(_project(events))


def requirement_freshness_facts_from_projection(
    projection: GraphProjection,
) -> list[RequirementFreshnessFact]:
    support_freshness = support_evidence_freshness_from_projection(projection)
    facts: list[RequirementFreshnessFact] = []
    for requirement_id, active_version_id in sorted(
        projection.get("active_requirement_versions", {}).items()
    ):
        revision = projection.get("requirement_revisions", {}).get(active_version_id, {})
        fresh_support_ids: list[str] = []
        stale_support_ids: list[str] = []
        for support_id, support in sorted(projection.get("support_evidence", {}).items()):
            if support.get("requirement_id") != requirement_id:
                continue
            support_fact = support_freshness.get(support_id)
            if support_fact is None:
                continue
            if support_fact["freshness"] == "fresh":
                fresh_support_ids.append(support_id)
            else:
                stale_support_ids.append(support_id)
        facts.append(
            {
                "requirement_id": requirement_id,
                "active_version_id": active_version_id,
                "revision_classification": str(revision.get("change_classification", "initial")),
                "requires_authority": revision.get("requires_authority") is True,
                "authority_required_reason": _optional_str(
                    revision.get("authority_required_reason")
                ),
                "fresh_support_ids": fresh_support_ids,
                "stale_support_ids": stale_support_ids,
                "unsupported": not fresh_support_ids,
            }
        )
    return facts


def project_requirement_freshness_facts(
    events: list[EventEnvelope],
) -> list[RequirementFreshnessFact]:
    return requirement_freshness_facts_from_projection(_project(events))


def project_planner_freshness_packet(events: list[EventEnvelope]) -> dict[str, Any]:
    """Expose compact requirement/evidence freshness facts for gap planners."""
    facts = project_requirement_freshness_facts(events)
    return {
        "requirement_freshness": facts,
        "unsupported_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["unsupported"]
        ],
        "stale_support_ids": [
            support_id for fact in facts for support_id in fact["stale_support_ids"]
        ],
        "authority_required_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["requires_authority"]
        ],
    }


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
    for node_id, node_state in sorted(node_states.items()):
        reason = latest_deferrals.get(node_id)
        if node_state == "ready":
            if reason is None:
                continue
            entry = {"node_id": node_id, "reason": reason}
            bucket = _scheduler_bucket_for_reason(reason)
            if bucket == "waiting_resources":
                view[bucket].append(entry)
            continue
        if node_state not in {"planned", "blocked"}:
            continue
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
    authority_decisions = _latest_decisions(events, "authority_decision_recorded")
    oversight_decisions = _latest_decisions(events, "oversight_decision_recorded")
    latest_deferrals = _latest_node_deferrals(events)
    request_details = _request_details_by_node(events)

    pending_gates: list[PendingGateDecision] = []
    appeals: list[AppealDecision] = []
    review_blockers: list[str] = []
    review_node_count = 0
    review_complete_count = 0

    for node_id, state in sorted(projection["node_states"].items()):
        kind = projection["node_kinds"].get(node_id)
        payload = latest_node_payloads.get(node_id, {})
        if (
            kind in {"gate", "human_gate"}
            and state in _PENDING_DECISION_STATES
            and (node_id not in approval_decisions)
        ):
            pending_gate: PendingGateDecision = {
                "node_id": node_id,
                "gate_type": _gate_type(node_id, payload, projection),
                "prompt": _gate_prompt(payload),
            }
            pending_gate.update(
                _request_details_for_pending_gate(node_id, payload, request_details)
            )
            pending_gates.append(pending_gate)
        elif (
            kind == "authority_request"
            and state in _PENDING_DECISION_STATES
            and node_id not in authority_decisions
        ):
            pending_gate = {
                "node_id": node_id,
                "gate_type": "authority_request",
                "prompt": _gate_prompt(payload),
            }
            pending_gate.update(
                _request_details_for_pending_gate(node_id, payload, request_details)
            )
            pending_gates.append(pending_gate)
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


def _topology_edge(
    edge: dict[str, Any],
    projection: GraphProjection,
    record_summaries: dict[str, GraphRecordSummary],
) -> GraphTopologyEdge:
    source_contract, target_contract = _edge_port_contracts(edge, projection)
    metadata = {
        key: edge[key] for key in _EDGE_METADATA_KEYS if key in edge and edge[key] is not None
    }
    topology_edge: GraphTopologyEdge = {
        "edge_id": str(edge["edge_id"]),
        "from_node_id": str(edge["from_node_id"]),
        "from_port": str(edge["from_port"]),
        "to_node_id": str(edge["to_node_id"]),
        "to_port": str(edge["to_port"]),
        "required": _edge_required(edge.get("required")),
        "dependency_type": str(edge.get("dependency_type", "input_binding")),
        "metadata": dict(metadata),
        "record_types": _compatible_edge_record_types(source_contract, target_contract),
        "binding": None,
        "bound_records": [],
    }
    selector = edge.get("accepted_record_selector")
    if isinstance(selector, dict):
        topology_edge["accepted_record_selector"] = dict(cast(dict[str, Any], selector))
    if source_contract is not None:
        topology_edge["source_port_contract"] = port_contract_summary(source_contract)
    if target_contract is not None:
        topology_edge["target_port_contract"] = port_contract_summary(target_contract)

    binding = _binding_for_edge(projection, edge)
    if binding is not None:
        binding_summary = _topology_binding(binding)
        topology_edge["binding"] = binding_summary
        record_ids = binding_summary.get("record_ids", [])
        bound_records: list[GraphRecordSummary] = [
            record_summaries[record_id] for record_id in record_ids if record_id in record_summaries
        ]
        topology_edge["bound_records"] = bound_records
    return topology_edge


def _edge_port_contracts(
    edge: dict[str, Any],
    projection: GraphProjection,
) -> tuple[PortContract | None, PortContract | None]:
    from_node_id = edge.get("from_node_id")
    to_node_id = edge.get("to_node_id")
    from_port = edge.get("from_port")
    to_port = edge.get("to_port")
    if not all(isinstance(value, str) for value in (from_node_id, to_node_id, from_port, to_port)):
        return None, None

    source_kind = projection["node_kinds"].get(cast(str, from_node_id))
    source_role = projection["node_roles"].get(cast(str, from_node_id))
    target_kind = projection["node_kinds"].get(cast(str, to_node_id))
    target_role = projection["node_roles"].get(cast(str, to_node_id))
    source_contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(source_kind, source_role)
        if source_kind is not None
        else None
    )
    target_contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
        if target_kind is not None
        else None
    )
    source_port_contract = (
        output_port_contract(source_contract, cast(str, from_port))
        if source_contract is not None
        else None
    )
    target_port_contract = (
        input_port_contract(target_contract, cast(str, to_port))
        if target_contract is not None
        else None
    )
    return source_port_contract, target_port_contract


def _compatible_edge_record_types(
    source: PortContract | None,
    target: PortContract | None,
) -> list[str]:
    if source is None or target is None:
        return []
    return sorted(source.record_types & target.record_types)


def _binding_for_edge(
    projection: GraphProjection,
    edge: dict[str, Any],
) -> dict[str, Any] | None:
    edge_id = edge.get("edge_id")
    to_node_id = edge.get("to_node_id")
    to_port = edge.get("to_port")
    if isinstance(to_node_id, str) and isinstance(to_port, str):
        binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
        if binding is not None and (
            not isinstance(edge_id, str) or binding.get("edge_id") in {None, edge_id}
        ):
            return binding
    if not isinstance(edge_id, str):
        return None
    for ports in projection["input_bindings"].values():
        for binding in ports.values():
            if binding.get("edge_id") == edge_id:
                return binding
    return None


def _topology_binding(binding: dict[str, Any]) -> GraphTopologyBinding:
    summary: GraphTopologyBinding = {
        "record_ids": _bound_record_ids(binding),
    }
    for key in ("edge_id", "to_node_id", "to_port", "binding_policy", "trigger"):
        value = binding.get(key)
        if isinstance(value, str):
            summary[key] = value
    bound_at_position = binding.get("bound_at_position")
    if isinstance(bound_at_position, int) and not isinstance(bound_at_position, bool):
        summary["bound_at_position"] = bound_at_position
    record_bound_positions = binding.get("record_bound_positions")
    if isinstance(record_bound_positions, dict):
        summary["record_bound_positions"] = {
            record_id: position
            for record_id, position in cast(dict[Any, Any], record_bound_positions).items()
            if isinstance(record_id, str)
            and isinstance(position, int)
            and not isinstance(position, bool)
        }
    return summary


def _record_summaries_by_id(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> dict[str, GraphRecordSummary]:
    records: dict[str, GraphRecordSummary] = {}
    for event in events:
        if event.event_type not in {"output_record_accepted", "file_state_accepted"}:
            continue
        record_id = event.payload.get("record_id")
        if not isinstance(record_id, str):
            continue
        summary: GraphRecordSummary = {"record_id": record_id, "position": event.position}
        record_kind = event.payload.get("record_kind")
        if isinstance(record_kind, str):
            summary["record_kind"] = record_kind
        schema = event.payload.get("schema")
        if isinstance(schema, str):
            summary["schema"] = schema
        producer_node_id = event.payload.get("producer_node_id")
        if isinstance(producer_node_id, str):
            summary["producer_node_id"] = producer_node_id
        producer_port = event.payload.get("port")
        if isinstance(producer_port, str):
            summary["producer_port"] = producer_port
        record_type = _record_type_for_summary(event.payload, projection)
        if record_type is not None:
            summary["record_type"] = record_type
        records[record_id] = summary
    return records


def _record_type_for_summary(
    payload: dict[str, Any],
    projection: GraphProjection,
) -> str | None:
    record_type = payload.get("record_type")
    if isinstance(record_type, str):
        return record_type
    record_kind = payload.get("record_kind")
    if record_kind == "file_state":
        return "file_state"
    if record_kind == "verification":
        return "verification_report"
    producer_node_id = payload.get("producer_node_id")
    port = payload.get("port")
    if isinstance(producer_node_id, str) and isinstance(port, str):
        node_kind = projection["node_kinds"].get(producer_node_id)
        node_role = projection["node_roles"].get(producer_node_id)
        contract = (
            DEFAULT_NODE_CONTRACTS.contract_for(node_kind, node_role)
            if node_kind is not None
            else None
        )
        port_contract = output_port_contract(contract, port) if contract is not None else None
        if port_contract is not None and port_contract.record_types:
            return sorted(port_contract.record_types)[0]
    return record_kind if isinstance(record_kind, str) else None


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


def _request_details_by_node(events: list[EventEnvelope]) -> dict[str, PendingGateDecision]:
    details: dict[str, PendingGateDecision] = {}
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        node_id = event.payload.get("producer_node_id")
        if not isinstance(node_id, str):
            continue
        record_type = event.payload.get("record_type")
        port = event.payload.get("port")
        if record_type not in {"decision_request", "authority_request_record"} and port not in {
            "decision_request",
            "authority_request_record",
        }:
            continue
        value = event.payload.get("value")
        if not isinstance(value, dict):
            continue
        projected = _request_details_from_value(cast(dict[str, Any], value))
        if projected:
            details[node_id] = projected
    return details


def _request_details_for_pending_gate(
    node_id: str,
    payload: dict[str, Any],
    request_details: dict[str, PendingGateDecision],
) -> PendingGateDecision:
    details = request_details.get(node_id)
    if details is not None:
        return cast(PendingGateDecision, dict(details))
    for key in ("decision_request", "authority_request_record", "authority_request"):
        raw_request = payload.get(key)
        if isinstance(raw_request, dict):
            return _request_details_from_value(cast(dict[str, Any], raw_request))
    return {}


def _request_details_from_value(value: dict[str, Any]) -> PendingGateDecision:
    details: PendingGateDecision = {}
    options = value.get("options")
    if isinstance(options, list):
        string_options = [option for option in cast(list[Any], options) if isinstance(option, str)]
        if string_options:
            details["options"] = string_options
    requested_authority = value.get("requested_authority")
    if isinstance(requested_authority, list):
        authorities = [
            authority
            for authority in cast(list[Any], requested_authority)
            if isinstance(authority, str)
        ]
        if authorities:
            details["requested_authority"] = authorities
    for source_key, target_key in (
        ("default_option", "default_option"),
        ("consequence_summary", "consequence_summary"),
        ("expires_at", "expires_at"),
        ("target_node_id", "target_node_id"),
        ("target_region_id", "target_region_id"),
    ):
        value_field = value.get(source_key)
        if isinstance(value_field, str) and value_field:
            details[target_key] = value_field
    return details


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
    if (
        reason.startswith("gate_")
        or reason.startswith("waiting_gate")
        or reason.startswith("authority_")
    ):
        return "waiting_gates"
    return "blocked"


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


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
    record_type = event.payload.get("record_type")
    schema = event.payload.get("schema")
    candidate_ports = {"candidate", "reader_output", "fan_out_inputs"}
    candidate_schemas = {"ImplementationCandidate", "FanOutInputs", "FanOutJoinedInputs"}
    explicit_non_candidate = port is not None or record_type is not None or schema is not None
    if (
        explicit_non_candidate
        and port not in candidate_ports
        and record_type != "candidate"
        and schema not in candidate_schemas
    ):
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
            "file_state_record_ids": _record_ids_from_payload(
                event.payload,
                "file_state_record_ids",
            ),
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


def _record_check_result(state: GraphProjection, event: EventEnvelope) -> None:
    if not _is_check_result_record(event.payload):
        return
    node_id = event.payload.get("producer_node_id") or event.payload.get("node_id")
    if not isinstance(node_id, str):
        return
    status = _check_result_status(event.payload)
    if status is None:
        status = "unknown"
    task_region_id = _task_region_id(event.payload) or state["node_task_regions"].get(node_id)
    result: dict[str, Any] = {
        "node_id": node_id,
        "status": status,
        "position": event.position,
    }
    value = event.payload.get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        for key in ("classification", "command_text", "stderr", "stdout", "exit_code"):
            if key in typed_value:
                result[key] = typed_value[key]
    if task_region_id is not None:
        result["task_region_id"] = task_region_id
    record_id = event.payload.get("record_id")
    if isinstance(record_id, str):
        result["record_id"] = record_id
    for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
        record_ids = _record_ids_from_payload(event.payload, field)
        if record_ids:
            result[field] = record_ids
    state["check_results"][node_id] = result


def _record_node_output_port(state: GraphProjection, event: EventEnvelope) -> None:
    node_id = event.payload.get("producer_node_id") or event.payload.get("node_id")
    if not isinstance(node_id, str):
        return
    port = event.payload.get("port")
    if not isinstance(port, str) or not port:
        if event.event_type == "file_state_accepted":
            port = "file_state"
        else:
            return
    record_id = event.payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = f"{event.event_type}:{event.position}"
    ports = state["node_output_ports"].setdefault(node_id, {})
    records = ports.setdefault(port, [])
    if record_id not in records:
        records.append(record_id)


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


def _record_authority_decision(state: GraphProjection, event: EventEnvelope) -> None:
    node_id = event.payload.get("node_id")
    decision = event.payload.get("decision")
    passed = decision in {"granted", "approved", "passed", "accepted"}
    if isinstance(node_id, str):
        state["node_gate_decisions"][node_id] = passed


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
        "required": _edge_required(required),
        "dependency_type": event.payload.get("dependency_type", "input_binding"),
    }
    selector = event.payload.get("accepted_record_selector")
    if isinstance(selector, dict):
        state["edges"][edge_id]["accepted_record_selector"] = dict(cast(dict[str, Any], selector))
    for key in _EDGE_METADATA_KEYS:
        if key not in event.payload:
            continue
        value = event.payload[key]
        if isinstance(value, dict):
            state["edges"][edge_id][key] = dict(cast(dict[str, Any], value))
        elif isinstance(value, list):
            state["edges"][edge_id][key] = list(cast(list[Any], value))
        elif isinstance(value, str | int | float | bool):
            state["edges"][edge_id][key] = value


def _edge_required(value: Any) -> bool:
    if value is False:
        return False
    if isinstance(value, int) and not isinstance(value, bool) and value == 0:
        return False
    return True


def _record_requirement_revision(state: GraphProjection, event: EventEnvelope) -> None:
    requirement_id = event.payload.get("requirement_id")
    if not isinstance(requirement_id, str):
        return

    version_id = event.payload.get("version_id")
    if not isinstance(version_id, str):
        version_id = event.payload.get("requirement_version_id")
    if not isinstance(version_id, str):
        version_id = f"{requirement_id}.v{event.position}"

    classification = _requirement_revision_classification(event.payload)
    requires_authority = _requires_explicit_requirement_authority(event.payload, classification)
    revision: dict[str, Any] = {
        "requirement_id": requirement_id,
        "version_id": version_id,
        "change_classification": classification,
        "requires_authority": requires_authority,
        "position": event.position,
    }
    previous_version_id = event.payload.get("previous_version_id")
    if isinstance(previous_version_id, str):
        revision["previous_version_id"] = previous_version_id
    revision_index = event.payload.get("revision_index")
    if isinstance(revision_index, int) and not isinstance(revision_index, bool):
        revision["revision_index"] = revision_index
    authority_reason = _authority_required_reason(event.payload, classification)
    if authority_reason is not None:
        revision["authority_required_reason"] = authority_reason
    validation_strengthening = (
        event.payload.get("validation_strengthening") is True
        or classification == "validation_strengthening"
    )
    revision["validation_strengthening"] = validation_strengthening

    state["requirement_revisions"][version_id] = revision
    if event.payload.get("active") is not False:
        state["active_requirement_versions"][requirement_id] = version_id
    if validation_strengthening:
        _mark_superseded_support_stale(state, requirement_id, version_id)


def _record_support_evidence(state: GraphProjection, event: EventEnvelope) -> None:
    support_id = event.payload.get("support_id")
    if not isinstance(support_id, str):
        support_id = event.payload.get("edge_id")
    if not isinstance(support_id, str):
        return

    evidence_id = event.payload.get("evidence_id")
    requirement_id = event.payload.get("requirement_id")
    if not isinstance(evidence_id, str) or not isinstance(requirement_id, str):
        return

    requirement_version_id = event.payload.get("requirement_version_id")
    if not isinstance(requirement_version_id, str):
        requirement_version_id = event.payload.get("version_id")
    if not isinstance(requirement_version_id, str):
        requirement_version_id = state["active_requirement_versions"].get(requirement_id)
    if not isinstance(requirement_version_id, str):
        return

    status = event.payload.get("status", "active")
    if not isinstance(status, str):
        status = "active"
    support: dict[str, Any] = {
        "support_id": support_id,
        "evidence_id": evidence_id,
        "requirement_id": requirement_id,
        "requirement_version_id": requirement_version_id,
        "status": status,
        "position": event.position,
    }
    stale_reason = event.payload.get("stale_reason")
    if isinstance(stale_reason, str):
        support["stale_reason"] = stale_reason
    confidence = event.payload.get("confidence")
    if isinstance(confidence, str):
        support["confidence"] = confidence
    state["support_evidence"][support_id] = support


def _mark_superseded_support_stale(
    state: GraphProjection,
    requirement_id: str,
    active_version_id: str,
) -> None:
    for support in state["support_evidence"].values():
        if support.get("requirement_id") != requirement_id:
            continue
        if support.get("requirement_version_id") == active_version_id:
            continue
        support["status"] = "stale"
        support.setdefault(
            "stale_reason",
            (
                "Evidence was produced for an older requirement version and does not "
                "prove the strengthened validation definition."
            ),
        )


def _support_stale_reason(
    projection: GraphProjection,
    support: dict[str, Any],
) -> str | None:
    status = support.get("status", "active")
    if status != "active":
        reason = support.get("stale_reason")
        return reason if isinstance(reason, str) else f"support edge status is {status}"

    requirement_id = support.get("requirement_id")
    requirement_version_id = support.get("requirement_version_id")
    if not isinstance(requirement_id, str) or not isinstance(requirement_version_id, str):
        return "support edge is missing requirement identity"
    active_version_id = projection.get("active_requirement_versions", {}).get(requirement_id)
    if active_version_id is None:
        return "requirement has no active version"
    if requirement_version_id != active_version_id:
        return "support edge targets a superseded requirement version"
    return None


def _requirement_revision_classification(payload: dict[str, Any]) -> str:
    for key in ("change_classification", "classification", "revision_type"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if payload.get("validation_strengthening") is True:
        return "validation_strengthening"
    if payload.get("new_behavior") is True:
        return "new_behavior"
    if payload.get("semantic_change") is True:
        return "semantic"
    return "initial"


def _requires_explicit_requirement_authority(
    payload: dict[str, Any],
    classification: str,
) -> bool:
    if payload.get("requires_authority") is True:
        return True
    if payload.get("explicit_authority_required") is True:
        return True
    if payload.get("new_behavior") is True or payload.get("behavior_change") is True:
        return True
    return classification in {
        "semantic",
        "new_behavior",
        "scope_expansion",
        "scope_reduction",
        "priority_change",
    }


def _authority_required_reason(payload: dict[str, Any], classification: str) -> str | None:
    reason = payload.get("authority_required_reason")
    if isinstance(reason, str) and reason:
        return reason
    if not _requires_explicit_requirement_authority(payload, classification):
        return None
    if payload.get("new_behavior") is True or classification in {"new_behavior", "scope_expansion"}:
        return "new_behavior"
    if payload.get("behavior_change") is True:
        return "behavior_change"
    return classification


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
    existing_binding = state["input_bindings"].get(to_node_id, {}).get(to_port)
    policy = _binding_policy_for_input_event(state, binding, to_node_id, to_port)
    binding["binding_policy"] = policy
    merged_ids = merge_bound_record_ids(
        policy,
        _bound_record_ids(existing_binding or {}),
        _bound_record_ids(binding),
        supersedes_record_id=binding.get("supersedes_record_id"),
    )
    if existing_binding is not None and merged_ids == _bound_record_ids(existing_binding):
        return
    binding["record_ids"] = merged_ids
    record_positions = _merged_record_bound_positions(existing_binding, binding, merged_ids)
    if record_positions:
        binding["record_bound_positions"] = record_positions
    state["input_bindings"].setdefault(to_node_id, {})[to_port] = binding


def _binding_policy_for_input_event(
    state: GraphProjection,
    binding: dict[str, Any],
    to_node_id: str,
    to_port: str,
) -> str:
    edge = _edge_for_input_binding(state, binding, to_node_id, to_port)
    target_port = _target_port_for_binding(state, edge, to_node_id, to_port)
    if edge is not None:
        return binding_policy_for_edge(edge, target_port)
    return binding_policy_for_edge(binding, target_port)


def _edge_for_input_binding(
    state: GraphProjection,
    binding: dict[str, Any],
    to_node_id: str,
    to_port: str,
) -> dict[str, Any] | None:
    edge_id = binding.get("edge_id")
    if isinstance(edge_id, str):
        edge = state["edges"].get(edge_id)
        if edge is not None:
            return edge
    for edge in state["edges"].values():
        if edge.get("to_node_id") == to_node_id and edge.get("to_port") == to_port:
            return edge
    return None


def _target_port_for_binding(
    state: GraphProjection,
    edge: dict[str, Any] | None,
    to_node_id: str,
    to_port: str,
) -> PortContract | None:
    if edge is not None:
        _, target_port = _edge_port_contracts(edge, state)
        if target_port is not None:
            return target_port
    target_kind = state["node_kinds"].get(to_node_id)
    if target_kind is None:
        return None
    target_role = state["node_roles"].get(to_node_id)
    contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if contract is None:
        return None
    return input_port_contract(contract, to_port)


def _merged_record_bound_positions(
    existing_binding: dict[str, Any] | None,
    incoming_binding: dict[str, Any],
    merged_ids: list[str],
) -> dict[str, int]:
    positions: dict[str, int] = {}
    if existing_binding is not None:
        raw_existing_positions = existing_binding.get("record_bound_positions")
        if isinstance(raw_existing_positions, dict):
            for record_id, position in cast(dict[Any, Any], raw_existing_positions).items():
                if isinstance(record_id, str) and isinstance(position, int):
                    positions[record_id] = position
        else:
            bound_at_position = existing_binding.get("bound_at_position")
            if isinstance(bound_at_position, int) and not isinstance(bound_at_position, bool):
                for record_id in _bound_record_ids(existing_binding):
                    positions.setdefault(record_id, bound_at_position)

    incoming_position = incoming_binding.get("bound_at_position")
    if not isinstance(incoming_position, int) or isinstance(incoming_position, bool):
        incoming_position = 0
    for record_id in _bound_record_ids(incoming_binding):
        positions.setdefault(record_id, incoming_position)
    return {record_id: positions[record_id] for record_id in merged_ids if record_id in positions}


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

    preconditions = _preconditions(event.payload)
    if preconditions:
        state["node_preconditions"][node_id] = preconditions


def _record_environment_failure(state: GraphProjection, event: EventEnvelope) -> None:
    task_region_id = _task_region_id(event.payload)
    node_id = event.payload.get("node_id")
    if task_region_id is None and isinstance(node_id, str):
        task_region_id = state["node_task_regions"].get(node_id)
    if task_region_id is None:
        return

    classification = event.payload.get("classification")
    reason = event.payload.get("reason")
    command_text = event.payload.get("command_text")
    stderr = event.payload.get("stderr")
    exit_code = event.payload.get("exit_code")
    value = event.payload.get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        classification = typed_value.get("classification", classification)
        command_text = typed_value.get("command_text", command_text)
        stderr = typed_value.get("stderr", stderr)
        exit_code = typed_value.get("exit_code", exit_code)
        if reason is None:
            reason = _environment_failure_reason_from_check_value(typed_value)
    is_environment = event.event_type == "environment_failure_accepted" or classification in {
        "environment_error",
        "tool_error",
        "tool_unavailable",
    }
    if is_environment:
        failure = {
            "position": event.position,
            "classification": classification,
            "reason": reason,
        }
        if isinstance(command_text, str):
            failure["command_text"] = command_text
        if isinstance(stderr, str):
            failure["stderr"] = stderr
        if isinstance(exit_code, int):
            failure["exit_code"] = exit_code
        if isinstance(node_id, str):
            failure["node_id"] = node_id
        record_id = event.payload.get("record_id")
        if isinstance(record_id, str):
            failure["record_id"] = record_id
        state["environment_failures"][task_region_id] = failure


def _environment_failure_reason_from_check_value(value: dict[str, Any]) -> str:
    classification = value.get("classification")
    command_text = value.get("command_text")
    command_label = (
        command_text if isinstance(command_text, str) and command_text else "check command"
    )
    stderr = value.get("stderr")
    if classification == "tool_unavailable":
        return f"check tool unavailable while running: {command_label}"
    if classification == "tool_error":
        return f"check tool error while running: {command_label}"
    if classification == "environment_error":
        return f"check environment setup failed while running: {command_label}"
    if isinstance(stderr, str) and stderr.strip():
        return stderr.strip().splitlines()[0]
    return "check failed because of the execution environment"


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
            task_states[task_region_id] = _derive_candidate_free_region_state(
                state,
                task_region_id,
            )
            continue

        candidate_id = latest_candidate["candidate_id"]
        configured_gates = state["configured_gates"].get(task_region_id, {})
        gate_decisions = state["gate_decisions"].get(task_region_id, {})
        gates_passed = _all_configured_gates_passed(configured_gates, gate_decisions)
        invalid_block = state["invalid_test_blocks"].get(task_region_id)

        verifier_passed = _verifier_requirement_passed(state, task_region_id, candidate_id)
        verdict = state["verifier_verdicts"].get(candidate_id)
        file_state_accepted = _task_file_state_accepted(state, task_region_id, candidate_id)
        checks_passed = _required_checks_passed(state, task_region_id)

        if verifier_passed and gates_passed and file_state_accepted and checks_passed:
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


def _derive_candidate_free_region_state(
    state: GraphProjection,
    task_region_id: str,
) -> str:
    if _has_active_task_lease(state, task_region_id):
        return "in_progress"
    node_ids = _task_region_node_ids(state, task_region_id)
    active_node_ids = [
        node_id
        for node_id in node_ids
        if state["node_states"].get(node_id) not in {"retired", "cancelled"}
    ]
    if node_ids and not active_node_ids:
        return "accepted"
    contributing_node_ids = [
        node_id
        for node_id in active_node_ids
        if _contract_fulfillment_contribution(state, node_id) != "none"
    ]
    if not contributing_node_ids:
        return "pending"
    if all(_node_contract_fulfilled(state, node_id) for node_id in contributing_node_ids):
        return "accepted"
    return "pending"


def _task_region_node_ids(state: GraphProjection, task_region_id: str) -> list[str]:
    return [
        node_id
        for node_id, node_task_region_id in sorted(state["node_task_regions"].items())
        if node_task_region_id == task_region_id
    ]


def _contract_for_node(state: GraphProjection, node_id: str) -> Any | None:
    kind = state["node_kinds"].get(node_id)
    if kind is None:
        return None
    return DEFAULT_NODE_CONTRACTS.contract_for(kind, state["node_roles"].get(node_id))


def _contract_fulfillment_contribution(state: GraphProjection, node_id: str) -> str:
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return "none"
    return contract.fulfillment_contribution


def _node_contract_fulfilled(state: GraphProjection, node_id: str) -> bool:
    node_state = state["node_states"].get(node_id)
    if node_state != "completed":
        return False
    missing_ports = _missing_fulfillment_ports(state, node_id)
    if missing_ports:
        return False
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return False
    if contract.fulfillment_contribution == "final_invariant":
        return _final_invariant_node_passed(state, node_id)
    return True


def _missing_fulfillment_ports(state: GraphProjection, node_id: str) -> list[str]:
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return []
    ports = state["node_output_ports"].get(node_id, {})
    return [port for port in sorted(contract.fulfillment_required_outputs) if not ports.get(port)]


def _final_invariant_node_passed(state: GraphProjection, node_id: str) -> bool:
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return False
    if "check_result" in contract.fulfillment_required_outputs:
        result = state.get("check_results", {}).get(node_id)
        return result is not None and result.get("status") in {"passed", "pass", "ok"}
    if "completion_decision" in contract.fulfillment_required_outputs:
        return bool(state["node_output_ports"].get(node_id, {}).get("completion_decision"))
    return True


def _verifier_requirement_passed(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    verdict = state["verifier_verdicts"].get(candidate_id)
    if verdict is not None:
        return verdict.get("verdict") == "passed"

    return not any(
        kind == "verifier"
        and state["node_task_regions"].get(node_id) == task_region_id
        and state["node_states"].get(node_id) not in {"retired", "cancelled"}
        for node_id, kind in state["node_kinds"].items()
    )


def _task_file_state_accepted(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    for record in state.get("file_state_records", {}).values():
        record_region_id = record.get("task_region_id")
        if not isinstance(record_region_id, str):
            producer_node_id = record.get("producer_node_id")
            if isinstance(producer_node_id, str):
                record_region_id = state["node_task_regions"].get(producer_node_id)
        if record_region_id != task_region_id:
            continue
        record_candidate_id = record.get("candidate_id")
        if isinstance(record_candidate_id, str) and record_candidate_id != candidate_id:
            continue
        verdict = record.get("verdict")
        if verdict in {"rejected", "failed"}:
            continue
        return True
    return False


def _required_checks_passed(state: GraphProjection, task_region_id: str) -> bool:
    latest_candidate = _latest_candidate(state["task_candidates"].get(task_region_id, []))
    check_node_ids = [
        node_id
        for node_id, kind in state["node_kinds"].items()
        if kind == "check"
        and state["node_task_regions"].get(node_id) == task_region_id
        and state["node_states"].get(node_id) not in {"retired", "cancelled"}
    ]
    if not check_node_ids:
        return True
    for node_id in check_node_ids:
        result = state.get("check_results", {}).get(node_id)
        if result is None:
            return False
        status = result.get("status")
        if status not in {"passed", "pass", "ok"}:
            return False
        if latest_candidate is not None and not _check_result_cites_latest_candidate(
            result,
            latest_candidate,
        ):
            return False
    return True


def _check_result_cites_latest_candidate(
    result: dict[str, Any],
    latest_candidate: dict[str, Any],
) -> bool:
    candidate_id = latest_candidate.get("candidate_id")
    candidate_record_ids = result.get("candidate_record_ids")
    if not isinstance(candidate_id, str) or not isinstance(candidate_record_ids, list):
        return False
    if candidate_id not in {
        record_id
        for record_id in cast(list[Any], candidate_record_ids)
        if isinstance(record_id, str)
    }:
        return False

    expected_file_state_ids = latest_candidate.get("file_state_record_ids")
    if not isinstance(expected_file_state_ids, list) or not expected_file_state_ids:
        return True
    check_file_state_ids = result.get("file_state_record_ids")
    if not isinstance(check_file_state_ids, list):
        return False
    cited_file_state_ids = {
        record_id
        for record_id in cast(list[Any], check_file_state_ids)
        if isinstance(record_id, str)
    }
    return all(
        record_id in cited_file_state_ids
        for record_id in cast(list[Any], expected_file_state_ids)
        if isinstance(record_id, str)
    )


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


def _record_ids_from_payload(payload: dict[str, Any], field: str) -> list[str]:
    for source in (
        payload,
        payload.get("value"),
        payload.get("provenance"),
        payload.get("evidence"),
    ):
        if not isinstance(source, dict):
            continue
        raw_value = cast(dict[str, Any], source).get(field)
        if not isinstance(raw_value, list):
            continue
        record_ids = [
            record_id for record_id in cast(list[Any], raw_value) if isinstance(record_id, str)
        ]
        if record_ids:
            return record_ids
    return []


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
    if raw_preconditions is None:
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_preconditions = cast(dict[str, Any], authority).get("preconditions")
    if not isinstance(raw_preconditions, list):
        return []
    return [
        precondition
        for precondition in cast(list[Any], raw_preconditions)
        if isinstance(precondition, str)
    ]


def _command_definition(payload: dict[str, Any]) -> Any | None:
    return check_command_reference(payload)
