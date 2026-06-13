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
