"""Pure graph projections for scenario fixtures."""

from typing import Any, TypedDict, cast

from orchestrator.graph.models import EventEnvelope


class GraphProjection(TypedDict):
    run_state: str | None
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, dict[str, Any]]
    ready_nodes: list[str]
    node_kinds: dict[str, str]
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


def initial_projection() -> GraphProjection:
    return {
        "run_state": None,
        "node_states": {},
        "task_states": {},
        "leases": {},
        "ready_nodes": [],
        "node_kinds": {},
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
    }


def reduce_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    next_state: GraphProjection = {
        "run_state": state["run_state"],
        "node_states": dict(state["node_states"]),
        "task_states": dict(state["task_states"]),
        "leases": {lease_id: dict(lease) for lease_id, lease in state["leases"].items()},
        "ready_nodes": list(state["ready_nodes"]),
        "node_kinds": dict(state["node_kinds"]),
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
    }

    if event.event_type == "run_lifecycle_changed":
        to_state = event.payload.get("to_state")
        if isinstance(to_state, str):
            next_state["run_state"] = to_state
    elif event.event_type == "node_created":
        node_id = event.payload.get("node_id")
        kind = event.payload.get("kind")
        node_state = event.payload.get("state")
        task_region_id = _task_region_id(event.payload)
        attempt_number = _attempt_number(event.payload)
        candidate_id = _candidate_id(event.payload)
        if isinstance(node_id, str) and isinstance(node_state, str):
            next_state["node_states"][node_id] = node_state
        if isinstance(node_id, str):
            if isinstance(kind, str):
                next_state["node_kinds"][node_id] = kind
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
    # node_ready/node_deferred and agent_died/runtime_retry_scheduled are
    # audit/policy facts. Projection facts are updated only by lease_* and
    # node_state_changed events so replay has a single state authority.

    next_state["ready_nodes"] = _ready_nodes(next_state["node_states"])
    next_state["task_states"] = _derive_task_states(next_state)
    return next_state


def project_run_state(events: list[EventEnvelope]) -> str | None:
    return _project(events)["run_state"]


def project_node_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["node_states"]


def project_task_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["task_states"]


def project_leases(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    return _project(events)["leases"]


def project_ready_nodes(events: list[EventEnvelope]) -> list[str]:
    return _project(events)["ready_nodes"]


def project_residue_report(events: list[EventEnvelope]) -> dict[str, list[dict[str, Any]]]:
    """Project accepted file-state residue classifications by path."""
    report: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.event_type != "file_state_accepted":
            continue
        node_id = event.payload.get("producer_node_id")
        record_id = event.payload.get("record_id")
        residue = event.payload.get("residue")
        if not isinstance(residue, list):
            residue = event.payload.get("classifications", [])
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
                    "run_id": event.run_id,
                    "node_id": node_id,
                    "record_id": record_id,
                    "source": entry.get("source"),
                }
            )
    return {path: report[path] for path in sorted(report)}


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _ready_nodes(node_states: dict[str, str]) -> list[str]:
    return [node_id for node_id, node_state in node_states.items() if node_state == "ready"]


def _record_candidate(state: GraphProjection, event: EventEnvelope) -> None:
    record_kind = event.payload.get("record_kind")
    if record_kind is not None and record_kind != "output":
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
