"""Unit tests for pure graph human-decision projections."""

from typing import Any

from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, project_decision_view


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def test_decision_view_lists_pending_gates_and_appeals() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "gate-human-1",
                "kind": "gate",
                "state": "ready",
                "gate_type": "human_approval",
                "prompt": "Review the implementation before merge.",
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "gate-approved-1",
                "kind": "gate",
                "state": "ready",
                "gate_type": "quality_gate",
            },
            2,
        ),
        _event(
            "approval_decision_recorded",
            {"node_id": "gate-approved-1", "decision": "approved"},
            3,
        ),
        _event(
            "node_created",
            {"node_id": "appeal-1", "kind": "appeal", "state": "completed"},
            4,
        ),
        _event(
            "oversight_decision_recorded",
            {
                "appeal_node_id": "appeal-1",
                "node_id": "oversight-1",
                "decision": "invalid_test_accepted",
            },
            5,
        ),
        _event(
            "node_created",
            {"node_id": "review-1", "kind": "review", "state": "completed"},
            6,
        ),
    ]

    view = project_decision_view(events)

    assert view == {
        "pending_gates": [
            {
                "node_id": "gate-human-1",
                "gate_type": "human_approval",
                "prompt": "Review the implementation before merge.",
            }
        ],
        "appeals": [
            {
                "node_id": "appeal-1",
                "state": "completed",
                "outcome": "invalid_test_accepted",
            }
        ],
        "review": {"ready": True, "blockers": []},
    }


def test_planner_budget_gate_surfaces_as_pending_decision() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "gate-planner-budget-planner-1",
                "kind": "gate",
                "state": "planned",
                "role": "planner_generation_budget_gate",
                "reason": "planner_generation_budget_exhausted",
            },
            1,
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "gate-planner-budget-planner-1",
                "new_state": "ready",
                "trigger": "planner_generation_budget_exhausted",
            },
            2,
        ),
    ]

    view = project_decision_view(events)

    assert view["pending_gates"] == [
        {
            "node_id": "gate-planner-budget-planner-1",
            "gate_type": "planner_generation_budget_exhausted",
            "prompt": "planner_generation_budget_exhausted",
        }
    ]
    assert view["appeals"] == []
    assert view["review"] == {"ready": False, "blockers": []}


def test_decision_view_includes_typed_request_details() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "planned",
                "reason": "Approve widened tool access.",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-request-1",
                "record_kind": "graph_record",
                "record_type": "decision_request",
                "producer_node_id": "human-gate-1",
                "port": "decision_request",
                "schema": "DecisionRequest",
                "value": {
                    "decision_type": "approval",
                    "options": ["approve", "reject", "defer"],
                    "default_option": "defer",
                    "consequence_summary": "Approval grants wider graph tooling.",
                    "expires_at": "2026-01-02T00:00:00+00:00",
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
                "reason": "Needs docs write access.",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "authority-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["repo:docs/**:write"],
                    "target_node_id": "worker-docs",
                    "reason": "Needs docs write access.",
                    "expires_at": "2026-01-02T00:00:00+00:00",
                },
            },
            4,
        ),
    ]

    view = project_decision_view(events)

    assert view["pending_gates"] == [
        {
            "node_id": "authority-1",
            "gate_type": "authority_request",
            "prompt": "Needs docs write access.",
            "requested_authority": ["repo:docs/**:write"],
            "target_node_id": "worker-docs",
            "expires_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "node_id": "human-gate-1",
            "gate_type": "Approve widened tool access.",
            "prompt": "Approve widened tool access.",
            "options": ["approve", "reject", "defer"],
            "default_option": "defer",
            "consequence_summary": "Approval grants wider graph tooling.",
            "expires_at": "2026-01-02T00:00:00+00:00",
        },
    ]
