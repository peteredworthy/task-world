"""Unit tests for pure graph projections."""

from pathlib import Path
from typing import Any, cast

import yaml

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    GraphProjection,
    InMemoryEventStore,
    SequentialIdGenerator,
    initial_projection,
    project_leases,
    project_node_states,
    project_ready_nodes,
    project_run_state,
    project_task_states,
    run_scenario,
    reduce_event,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "graph"


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-event",
        run_id="run-1",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def test_empty_projection() -> None:
    assert initial_projection() == {
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
    }


def test_replay_determinism() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "ready"}),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}),
    ]

    first = initial_projection()
    second = initial_projection()
    for event in events:
        first = reduce_event(first, event)
        second = reduce_event(second, event)

    assert first == second
    assert project_run_state(events) == "active"
    assert project_node_states(events) == {"worker-1": "ready"}
    assert project_leases(events) == {
        "lease-1": {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "kind": "worker",
            "state": "active",
        }
    }


def test_projection_immutability() -> None:
    state: GraphProjection = {
        "run_state": "active",
        "node_states": {"worker-1": "ready"},
        "task_states": {"task-1": "running"},
        "leases": {"lease-1": {"lease_id": "lease-1", "state": "active"}},
        "ready_nodes": ["worker-1"],
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
    }

    next_state = reduce_event(
        state,
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
    )

    assert next_state is not state
    assert next_state["node_states"] is not state["node_states"]
    assert next_state["task_states"] is not state["task_states"]
    assert next_state["leases"] is not state["leases"]
    assert next_state["leases"]["lease-1"] is not state["leases"]["lease-1"]
    assert state == {
        "run_state": "active",
        "node_states": {"worker-1": "ready"},
        "task_states": {"task-1": "running"},
        "leases": {"lease-1": {"lease_id": "lease-1", "state": "active"}},
        "ready_nodes": ["worker-1"],
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
    }
    assert next_state["node_states"] == {"worker-1": "running"}


def test_run_state_transitions() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "draft", "to_state": "queued"}),
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_run_state(events) == "completed"


def test_run_unknown_event_ignored() -> None:
    initial = initial_projection()
    next_state = reduce_event(initial, _event("unknown_event", {"to_state": "failed"}))

    assert next_state == initial
    assert next_state is not initial


def test_node_created_sets_planned() -> None:
    events = [_event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"})]

    assert project_node_states(events) == {"worker-1": "planned"}


def test_node_state_transitions() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "ready"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "completed"}),
    ]

    assert project_node_states(events) == {"worker-1": "completed"}


def test_ready_nodes_derived() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}),
        _event("node_created", {"node_id": "worker-2", "kind": "worker", "state": "planned"}),
        _event("node_state_changed", {"node_id": "worker-2", "new_state": "ready"}),
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
    ]

    assert project_ready_nodes(events) == ["worker-2"]


def test_lease_lifecycle() -> None:
    events = [
        _event(
            "lease_granted",
            {"node_id": "worker-1", "lease_id": "lease-1", "generation": 2},
        ),
        _event("lease_suspended", {"lease_id": "lease-1"}),
        _event("lease_revoked", {"lease_id": "lease-1"}),
        _event("lease_expired", {"lease_id": "lease-1"}),
        _event("lease_released", {"lease_id": "lease-1"}),
    ]

    assert project_leases(events) == {
        "lease-1": {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 2,
            "state": "released",
        }
    }


def test_task_projection_accepted() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_passed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "approval_decision_recorded",
            {"task_region_id": "task-1", "gate_id": "gate-1", "approved": True},
        ).model_copy(update={"position": 2}),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_configured_gate_requires_decision() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "gate",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 2}
        ),
    ]

    assert project_task_states(events) == {"task-1": "pending"}

    approved_events = [
        *events,
        _event(
            "approval_decision_recorded",
            {"node_id": "gate-1", "decision": "approved"},
        ).model_copy(update={"position": 3}),
    ]
    assert project_task_states(approved_events) == {"task-1": "accepted"}

    rejected_events = [
        *events,
        _event(
            "approval_decision_recorded",
            {"node_id": "gate-1", "decision": "rejected"},
        ).model_copy(update={"position": 3}),
    ]
    assert project_task_states(rejected_events) == {"task-1": "pending"}


def test_task_projection_needs_revision() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
    ]

    assert project_task_states(events) == {"task-1": "needs_revision"}


def test_verification_output_record_is_not_projected_as_candidate() -> None:
    events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 1,
            },
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "task_region_id": "task-1",
                "candidate_id": "candidate-2",
                "attempt_number": 99,
            },
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "candidate-1"}).model_copy(
            update={"position": 2}
        ),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_blocked_invalid_test() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
    ]

    assert project_task_states(events) == {"task-1": "blocked_invalid_test"}


def test_task_projection_blocked_environment() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event(
            "environment_failure_accepted",
            {"task_region_id": "task-1", "reason": "tool_unavailable"},
        ).model_copy(update={"position": 1}),
    ]

    assert project_task_states(events) == {"task-1": "blocked_environment"}


def test_task_projection_in_progress() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"}
        ),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}),
    ]

    assert project_task_states(events) == {"task-1": "in_progress"}


def test_task_projection_pending() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"}
        )
    ]

    assert project_task_states(events) == {"task-1": "pending"}


def test_task_projection_latest_candidate_by_attempt_then_position() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-old", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-new-pos", "attempt_number": 1},
        ).model_copy(update={"position": 2}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-new-attempt", "attempt_number": 2},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-new-pos"}).model_copy(
            update={"position": 3}
        ),
        _event("verification_failed", {"candidate_id": "cand-new-attempt"}).model_copy(
            update={"position": 4}
        ),
    ]

    assert project_task_states(events) == {"task-1": "needs_revision"}


def test_task_projection_latest_candidate_position_tiebreak() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-old", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-later", "attempt_number": 1},
        ).model_copy(update={"position": 1}),
        _event("verification_passed", {"candidate_id": "cand-later"}).model_copy(
            update={"position": 2}
        ),
        _event("verification_failed", {"candidate_id": "cand-old"}).model_copy(
            update={"position": 3}
        ),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_ignores_mismatched_verdict_candidate() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_passed", {"candidate_id": "other-candidate"}).model_copy(
            update={"position": 1}
        ),
    ]

    assert project_task_states(events) == {"task-1": "pending"}


def test_task_projection_active_appeal_overrides_latest_failure() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "appeal_opened",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
            },
        ).model_copy(update={"position": 2}),
    ]

    assert project_task_states(events) == {"task-1": "pending"}


def test_task_projection_invalid_test_block_exits_after_replacement_pass() -> None:
    events = [
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1},
        ).model_copy(update={"position": 0}),
        _event("verification_failed", {"candidate_id": "cand-1"}).model_copy(
            update={"position": 1}
        ),
        _event(
            "oversight_decision_recorded",
            {
                "task_region_id": "task-1",
                "candidate_id": "cand-1",
                "appeal_type": "invalid_test",
                "decision": "accepted",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "output_record_accepted",
            {"task_region_id": "task-1", "candidate_id": "cand-2", "attempt_number": 2},
        ).model_copy(update={"position": 3}),
        _event("verification_passed", {"candidate_id": "cand-2"}).model_copy(
            update={"position": 4}
        ),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_fixture_corpus_then_projections_satisfied() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        assert isinstance(raw, list), f"{path.name} must contain a list of scenarios"
        for scenario in raw:
            assert isinstance(scenario, dict), f"{path.name} contains a non-mapping scenario"
            typed_scenario = cast(dict[str, Any], scenario)
            then_projection = typed_scenario.get("then_projection")
            assert isinstance(then_projection, dict)
            assert then_projection, f"{path.name}::{typed_scenario['name']} has empty projection"

            result = run_scenario(
                typed_scenario,
                InMemoryEventStore(),
                FakeClock(),
                SequentialIdGenerator(),
            )

            assert result.passed, f"{typed_scenario['name']}: {result.failures}"
