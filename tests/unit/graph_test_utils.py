from copy import deepcopy
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCommandContext,
    GraphProjection,
    PatchCommandContext,
    apply_command as apply_strict_command,
    initial_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
)


def _fixture_checkpoint(projection: GraphProjection) -> dict[str, Any]:
    try:
        checkpoint = to_jsonable_python(projection_to_checkpoint(projection))
    except (AttributeError, TypeError, ValueError):
        checkpoint = to_jsonable_python(cast(dict[str, Any], projection))
    if not isinstance(checkpoint, dict):
        raise TypeError("projection checkpoint must be a mapping")
    normalized = cast(dict[str, Any], checkpoint)
    projection_from_checkpoint(normalized)
    return normalized


def _require_fixture_field(field: str) -> None:
    if field not in initial_projection():
        raise KeyError(f"unknown graph projection fixture field: {field}")


def _normalize_fixture_value(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("fixture mapping keys must contain only strings")
        return {key: _normalize_fixture_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalize_fixture_value(item) for item in value]
    return to_jsonable_python(value)


def _fixture_projection(projection: GraphProjection) -> GraphProjection:
    _fixture_checkpoint(projection)
    return cast(GraphProjection, deepcopy(cast(dict[str, Any], projection)))


def projection_fixture_replace(
    projection: GraphProjection, field: str, value: object
) -> GraphProjection:
    _require_fixture_field(field)
    replaced = _fixture_projection(projection)
    cast(dict[str, Any], replaced)[field] = _normalize_fixture_value(value)
    return replaced


def projection_fixture_set(
    projection: GraphProjection,
    field: str,
    keys: Sequence[str],
    value: object,
) -> GraphProjection:
    _require_fixture_field(field)
    if isinstance(keys, (str, bytes)) or not keys:
        raise ValueError("fixture mapping keys must be a nonempty sequence of strings")
    if any(not isinstance(key, str) for key in keys):
        raise TypeError("fixture mapping keys must contain only strings")
    replaced = _fixture_projection(projection)
    root = cast(dict[str, Any], replaced)[field]
    if not isinstance(root, Mapping):
        raise TypeError(f"fixture field {field!r} must be a mapping")
    replacement: dict[str, Any] = dict(root)
    cast(dict[str, Any], replaced)[field] = replacement
    current = replacement
    for key in keys[:-1]:
        nested = current.get(key)
        if not isinstance(nested, Mapping):
            raise TypeError(f"fixture key {key!r} must traverse a mapping")
        cloned = dict(nested)
        current[key] = cloned
        current = cloned
    current[keys[-1]] = _normalize_fixture_value(value)
    return replaced


def projection_fixture_update(
    projection: GraphProjection, field: str, values: Mapping[str, object]
) -> GraphProjection:
    _require_fixture_field(field)
    replaced = _fixture_projection(projection)
    current = cast(dict[str, Any], replaced)[field]
    if not isinstance(current, Mapping):
        raise TypeError(f"fixture field {field!r} must be a mapping")
    if not isinstance(values, Mapping):
        raise TypeError("fixture update values must be a mapping")
    cast(dict[str, Any], replaced)[field] = {**current, **_normalize_fixture_value(values)}
    return replaced


def projection_fixture_append(
    projection: GraphProjection, field: str, value: object
) -> GraphProjection:
    _require_fixture_field(field)
    replaced = _fixture_projection(projection)
    current = cast(dict[str, Any], replaced)[field]
    if not isinstance(current, list):
        raise TypeError(f"fixture field {field!r} must be a list")
    cast(dict[str, Any], replaced)[field] = [*current, _normalize_fixture_value(value)]
    return replaced


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
    if event_type == "run_lifecycle_changed":
        to_state = str(canonical.setdefault("to_state", "active"))
        canonical.setdefault("command_type", "fixture_transition")
        canonical.setdefault("from_state", "queued" if to_state == "active" else "active")
        canonical.setdefault("trigger", "fixture_transition")
    elif event_type == "node_created":
        canonical.setdefault("kind", "worker")
        canonical.setdefault("state", "planned")
    elif event_type in {
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
    }:
        canonical.setdefault("lease_id", "lease-1")
        canonical.setdefault("lease_generation", 1)
        canonical.setdefault("execution_id", "execution-1")
        canonical.setdefault("idempotency_key", "fixture-callback")
        canonical.setdefault("payload", None)
        canonical.setdefault(
            "reason", "accepted" if event_type == "callback_accepted" else "rejected"
        )
        if event_type == "callback_duplicate_returned":
            canonical.setdefault("prior_result", None)
    elif event_type in {
        "approval_decision_recorded",
        "authority_decision_recorded",
        "oversight_decision_recorded",
    }:
        canonical.setdefault("decision_type", event_type.removesuffix("_decision_recorded"))
        canonical.setdefault("node_id", "decision-node-1")
        canonical.setdefault("decider", "fixture-controller")
    elif event_type == "appeal_opened":
        canonical.setdefault("node_id", "appeal-1")
        canonical.setdefault("appealed_node_id", "verifier-1")
        canonical.setdefault("appeal_type", "invalid_test")
    elif event_type == "runtime_retry_scheduled":
        canonical.setdefault("node_id", "worker-1")
        canonical.setdefault("lease_id", "lease-1")
        canonical.setdefault("generation", 1)
        canonical.setdefault("policy", "v1_requeue_same_node_after_agent_death")
        canonical.setdefault("reason", "fixture_runtime_death")
    elif event_type == "heartbeat_recorded":
        canonical.setdefault("lease_id", "lease-1")
        canonical.setdefault("node_id", "worker-1")
        canonical.setdefault("observed_at", "2026-01-01T00:00:00+00:00")
        canonical.setdefault("expires_at", "2026-01-01T00:05:00+00:00")
    elif event_type == "agent_died":
        canonical.setdefault("lease_id", "lease-1")
        canonical.setdefault("node_id", "worker-1")
        canonical.setdefault("reason", "fixture_runtime_death")
    elif event_type == "dead_input_detected":
        canonical.setdefault("node_id", "worker-1")
        canonical.setdefault("from_node_id", "producer-1")
        canonical.setdefault("to_port", "input")
        canonical.setdefault("reason", "upstream_failed:producer-1")
    elif event_type == "output_record_accepted":
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
            value.setdefault("stdout_tail", "")
            value.setdefault("stderr_tail", "")
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
