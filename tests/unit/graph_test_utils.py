from datetime import datetime, timezone
from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCommandContext,
    PatchCommandContext,
    apply_command as apply_strict_command,
)


def command_context(
    events: list[EventEnvelope],
    *,
    run_id: str = "run-1",
    actor: Actor | None = None,
) -> GraphCommandContext:
    return GraphCommandContext(
        run_id=run_id,
        current_graph_position=max((event.position for event in events), default=-1),
        actor=actor,
    )


def patch_command_context(
    events: list[EventEnvelope],
    *,
    proposed_by_node_id: str,
    actor_role: str,
    run_id: str = "run-1",
) -> PatchCommandContext:
    return PatchCommandContext(
        run_id=run_id,
        current_graph_position=max((event.position for event in events), default=-1),
        proposed_by_node_id=proposed_by_node_id,
        actor_role=actor_role,
    )


def apply_command(
    projection: Any,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    context: GraphCommandContext,
    clock: Any,
    id_gen: Any,
) -> list[EventEnvelope]:
    return apply_strict_command(
        projection,
        events,
        command_type,
        payload,
        context,
        clock,
        id_gen,
    )


def canonical_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Complete sparse test fixtures into the smallest canonical event payload."""
    canonical = dict(payload)
    if event_type == "output_record_accepted":
        record_kind = canonical.get("record_kind")
        if record_kind == "file_state":
            canonical.setdefault("record_type", "file_state")
            canonical.setdefault("port", "file_state")
            canonical.setdefault("schema", "FileStateRecord")
            canonical.setdefault("record_id", "file-state-record")
            return canonical
        if record_kind == "verification":
            candidate_id = str(canonical.setdefault("candidate_id", "candidate-1"))
            canonical.setdefault("record_type", "verification_report")
            canonical.setdefault("producer_node_id", "verifier-1")
            canonical.setdefault("port", "verification_report")
            canonical.setdefault("schema", "VerificationReport")
            canonical.setdefault("record_id", f"verification-{candidate_id}")
            outcome = canonical.setdefault("outcome", "passed")
            canonical.setdefault("value", {"outcome": outcome, "grades": []})
            return canonical
        if record_kind == "check_result" or canonical.get("record_type") == "check_result":
            candidate_id = str(canonical.setdefault("candidate_id", "candidate-1"))
            canonical.setdefault("task_region_id", "task-1")
            value = dict(canonical.get("value", {}))
            value.pop("body", None)
            value.pop("reason", None)
            status = str(value.setdefault("status", canonical.pop("status", "failed")))
            value.setdefault("classification", canonical.get("classification", status))
            canonical.pop("classification", None)
            value.setdefault("command_id", "test-command")
            value.setdefault("command_text", "check command")
            value.setdefault("command", {})
            value.setdefault("worktree_path", "/worktree")
            value.setdefault("base_snapshot_id", "snapshot-1")
            value.setdefault("execution_id", "execution-1")
            value.setdefault("duration_ms", 0)
            value.setdefault("stdout", "")
            value.setdefault("stderr", "")
            value.setdefault("stdout_truncated", False)
            value.setdefault("stderr_truncated", False)
            value.setdefault("timeout_seconds", 1.0)
            value.setdefault("environment_policy", {})
            canonical["value"] = value
            canonical.setdefault("record_id", "check-result")
            canonical["record_kind"] = "output"
            canonical["record_type"] = "check_result"
            producer_node_id = canonical.get("producer_node_id") or canonical.get("node_id")
            canonical["producer_node_id"] = str(producer_node_id or "check-1")
            canonical.pop("node_id", None)
            canonical["port"] = "check_result"
            canonical["schema"] = "CheckResult"
            canonical.setdefault("attempt_number", 0)
            return canonical
        if canonical.get("record_type") == "completion_decision":
            canonical.setdefault("record_id", "completion-decision")
            canonical["record_kind"] = "output"
            canonical.setdefault("producer_node_id", "final-gate")
            canonical["port"] = "completion_decision"
            canonical["schema"] = "CompletionDecision"
            return canonical
        if canonical.get("record_type") == "decision_request":
            canonical.setdefault("record_id", "decision-request")
            canonical["record_kind"] = "graph_record"
            canonical.setdefault("producer_node_id", "human-gate-1")
            canonical["port"] = "decision_request"
            canonical["schema"] = "DecisionRequest"
            value = dict(canonical.get("value", {}))
            value.setdefault("decision_type", "approval")
            canonical["value"] = value
            return canonical
        if record_kind == "routine_snapshot" or canonical.get("record_type") == "routine_snapshot":
            canonical["record_kind"] = "graph_record"
            canonical["record_type"] = "routine_snapshot"
            canonical.setdefault("producer_node_id", "routine-snapshot")
            canonical.setdefault("port", "snapshot")
            canonical.setdefault("schema", "RoutineSnapshot")
            canonical.setdefault(
                "value",
                {
                    "routine_id": "routine-1",
                    "name": "Routine 1",
                    "content_hash": "test-routine-hash",
                    "step_count": 1,
                    "task_count": 1,
                },
            )
            return canonical
        if "candidate_id" in canonical or canonical.get("record_id", "").startswith("candidate"):
            candidate_id = str(
                canonical.setdefault("candidate_id", canonical.get("record_id", "candidate-1"))
            )
            canonical.setdefault("record_id", candidate_id)
            canonical["record_kind"] = "output"
            canonical["record_type"] = "candidate"
            canonical.setdefault("producer_node_id", "worker-1")
            canonical["port"] = "candidate"
            canonical["schema"] = "ImplementationCandidate"
            canonical.setdefault("value", {"summary": "test candidate"})
            return canonical
        canonical.setdefault("record_id", "output-record")
        canonical.setdefault("record_kind", "output")
        canonical.setdefault("producer_node_id", "worker-1")
        canonical.setdefault("port", canonical.get("record_type", "output"))
        canonical.setdefault("schema", "TestRecord")
        canonical.setdefault("value", {})
    elif event_type in {"verification_passed", "verification_failed"}:
        outcome = "passed" if event_type == "verification_passed" else "failed"
        candidate_id = str(canonical.setdefault("candidate_id", "candidate-1"))
        node_id = str(canonical.setdefault("node_id", "verifier-1"))
        canonical.setdefault("verifier_node_id", node_id)
        canonical.setdefault("record_id", f"verification-{candidate_id}")
        canonical.setdefault("outcome", outcome)
        canonical.setdefault("evidence", [])
        canonical.setdefault("value", {"outcome": outcome, "grades": []})
    elif event_type == "input_bound":
        edge_id = str(canonical.setdefault("edge_id", "edge-1"))
        canonical.setdefault("to_node_id", "node-1")
        canonical.setdefault("to_port", "input")
        canonical.setdefault("record_ids", [f"record-{edge_id}"])
        canonical.setdefault("bound_at_position", 0)
    elif event_type == "file_state_accepted":
        canonical.setdefault("record_id", "file-state-record")
        canonical.setdefault("record_kind", "file_state")
        canonical.setdefault("record_type", "file_state")
        canonical.setdefault("port", "file_state")
        canonical.setdefault("schema", "FileStateRecord")
    return canonical


def event(
    event_type: str,
    payload: dict[str, Any],
    *,
    position: int = 0,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        payload=canonical_event_payload(event_type, payload),
    )
