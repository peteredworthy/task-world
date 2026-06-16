"""Compact activity-feed projections for durable graph events."""

from __future__ import annotations

from typing import Any, cast


GRAPH_ACTIVITY_EVENT_TYPES = {
    "command_rejected",
    "graph_patch_accepted",
    "graph_patch_rejected",
    "node_deferred",
    "verification_failed",
    "verification_passed",
}


def compact_graph_activity_payload(event_type: str, envelope: dict[str, Any]) -> dict[str, Any]:
    """Return operator-facing graph facts without raw prompts or transcripts."""
    raw_payload = envelope.get("payload")
    payload = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}

    if event_type == "graph_patch_accepted":
        return _compact_patch_accepted(payload)
    if event_type == "graph_patch_rejected":
        return _compact_patch_rejected(payload)
    if event_type == "command_rejected":
        return _compact_command_rejected(payload)
    if event_type in {"verification_passed", "verification_failed"}:
        return _compact_verification(event_type, payload)
    if event_type == "node_deferred":
        return _compact_node_deferred(payload)
    if event_type == "node_created":
        return _compact_review_node_created(payload)
    return {"summary": event_type}


def _compact_patch_accepted(payload: dict[str, Any]) -> dict[str, Any]:
    successor_planners = _string_list(payload.get("successor_planner_node_ids"))
    compact: dict[str, Any] = {
        "summary": _join_summary(
            "Graph patch accepted",
            _fact("patch", payload.get("patch_id")),
            _fact("proposer", payload.get("proposed_by_node_id")),
            _fact("actor", payload.get("actor_role")),
            _fact("successor_planners", ", ".join(successor_planners)),
        ),
        "decision": "accepted",
        "patch_id": _optional_str(payload.get("patch_id")),
        "proposed_by_node_id": _optional_str(payload.get("proposed_by_node_id")),
        "actor_role": _optional_str(payload.get("actor_role")),
        "base_graph_position": payload.get("base_graph_position"),
        "successor_planner_node_ids": successor_planners,
    }
    return _drop_none(compact)


def _compact_patch_rejected(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "summary": _join_summary(
            "Graph patch rejected",
            _fact("patch", payload.get("patch_id")),
            _fact("proposer", payload.get("proposed_by_node_id")),
            _fact("actor", payload.get("actor_role")),
            _fact("reason", payload.get("reason")),
        ),
        "decision": "rejected",
        "patch_id": _optional_str(payload.get("patch_id")),
        "proposed_by_node_id": _optional_str(payload.get("proposed_by_node_id")),
        "actor_role": _optional_str(payload.get("actor_role")),
        "reason": _optional_str(payload.get("reason")),
        "read_set_diff": payload.get("read_set_diff"),
    }
    for key in ("budget", "count"):
        if key in payload:
            compact[key] = payload[key]
    return _drop_none(compact)


def _compact_command_rejected(payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_none(
        {
            "summary": _join_summary(
                "Graph command rejected",
                _fact("command", payload.get("command_type")),
                _fact("reason", payload.get("reason")),
            ),
            "decision": "rejected",
            "command_type": _optional_str(payload.get("command_type")),
            "reason": _optional_str(payload.get("reason")),
        }
    )


def _compact_verification(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    verdict = "passed" if event_type == "verification_passed" else "failed"
    grades = _compact_grades(payload.get("value"))
    compact: dict[str, Any] = {
        "summary": _join_summary(
            f"Graph verifier {verdict}",
            _fact("verifier", payload.get("verifier_node_id") or payload.get("node_id")),
            _fact("candidate", payload.get("candidate_id")),
            _fact("task", payload.get("task_region_id")),
            _fact("grades", _grade_summary(grades)),
        ),
        "verdict": verdict,
        "verifier_node_id": _optional_str(
            payload.get("verifier_node_id") or payload.get("node_id")
        ),
        "candidate_id": _optional_str(payload.get("candidate_id")),
        "task_region_id": _optional_str(payload.get("task_region_id")),
        "record_id": _optional_str(payload.get("record_id")),
        "grades": grades,
    }
    return _drop_none(compact)


def _compact_node_deferred(payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_none(
        {
            "summary": _join_summary(
                "Graph node blocked",
                _fact("node", payload.get("node_id")),
                _fact("reason", payload.get("reason")),
            ),
            "node_id": _optional_str(payload.get("node_id")),
            "reason": _optional_str(payload.get("reason")),
        }
    )


def _compact_review_node_created(payload: dict[str, Any]) -> dict[str, Any]:
    blocker = payload.get("blocker") or payload.get("blocker_reason") or payload.get("reason")
    return _drop_none(
        {
            "summary": _join_summary(
                "Graph final invariant blocked",
                _fact("node", payload.get("node_id")),
                _fact("reason", blocker),
            ),
            "node_id": _optional_str(payload.get("node_id")),
            "kind": _optional_str(payload.get("kind")),
            "state": _optional_str(payload.get("state")),
            "reason": _optional_str(blocker),
        }
    )


def _compact_grades(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    typed_value = cast(dict[str, Any], value)
    raw_grades = typed_value.get("grades")
    if not isinstance(raw_grades, list):
        return []
    grades: list[dict[str, Any]] = []
    for raw_grade in cast(list[Any], raw_grades):
        if not isinstance(raw_grade, dict):
            continue
        typed_grade = cast(dict[str, Any], raw_grade)
        grade = {
            "requirement_id": _optional_str(typed_grade.get("requirement_id")),
            "grade": _optional_str(typed_grade.get("grade")),
            "reason": _optional_str(typed_grade.get("reason")),
        }
        grades.append(_drop_none(grade))
    return grades


def _grade_summary(grades: list[dict[str, Any]]) -> str | None:
    if not grades:
        return None
    parts: list[str] = []
    for grade in grades:
        requirement_id = grade.get("requirement_id")
        value = grade.get("grade")
        if requirement_id and value:
            parts.append(f"{requirement_id}={value}")
        elif value:
            parts.append(str(value))
    return ", ".join(parts) or None


def _join_summary(prefix: str, *facts: str | None) -> str:
    present = [fact for fact in facts if fact]
    if not present:
        return prefix
    return f"{prefix}: {'; '.join(present)}"


def _fact(name: str, value: Any) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    return f"{name}={text}"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_optional_str(item) for item in cast(list[Any], value)) if item]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
