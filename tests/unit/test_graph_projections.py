"""Unit tests for pure graph projections."""

from pathlib import Path
import random
from typing import Any, cast

import yaml
import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    FinalInvariantBlocker,
    GraphProjection,
    InMemoryEventStore,
    SequentialIdGenerator,
    initial_projection,
    project_final_invariant_blockers,
    project_graph_patch_attempts,
    project_decision_view,
    project_leases,
    project_node_states,
    project_planner_freshness_packet,
    project_ready_nodes,
    project_requirement_freshness_facts,
    project_requirement_revisions,
    project_run_state,
    project_task_states,
    project_support_evidence_freshness,
    run_scenario,
    reduce_event,
    support_evidence_freshness_from_projection,
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


def _file_state_event(task_region_id: str, candidate_id: str, position: int) -> EventEnvelope:
    return _event(
        "file_state_accepted",
        {
            "record_id": f"file-state-{candidate_id}",
            "record_kind": "file_state",
            "producer_node_id": f"worker-{candidate_id}",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": f"snapshot-{candidate_id}",
            "base_snapshot_id": "S0",
            "task_region_id": task_region_id,
            "candidate_id": candidate_id,
            "verdict": "captured",
        },
    ).model_copy(update={"position": position})


def test_graph_patch_attempt_projection_rejects_malformed_result() -> None:
    events = [
        _event(
            "graph_patch_rejected",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
            },
        ).model_copy(update={"position": 2})
    ]

    with pytest.raises(ValueError, match="requires rejection_reason"):
        project_graph_patch_attempts(events, run_id="run-1", current_graph_position=3)


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


def test_input_binding_replay_accumulates_many_cardinality_records() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}),
        _event(
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "required": True,
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-2"],
                "bound_at_position": 5,
            },
        ),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    binding = projection["input_bindings"]["summarizer-1"]["source_records"]
    assert binding["binding_policy"] == "bind_all"
    assert binding["record_ids"] == ["candidate-1", "candidate-2"]
    assert binding["record_bound_positions"] == {"candidate-1": 4, "candidate-2": 5}


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


def test_requirement_revisions_replay_active_versions() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v1",
                "revision_index": 1,
                "classification": "initial",
            },
        ).model_copy(update={"position": 1}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
                "previous_version_id": "R-1.v1",
                "revision_index": 2,
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 2}),
    ]

    revisions = project_requirement_revisions(events)

    assert revisions["R-1.v1"]["requirement_id"] == "R-1"
    assert revisions["R-1.v2"] == {
        "requirement_id": "R-1",
        "version_id": "R-1.v2",
        "change_classification": "validation_strengthening",
        "requires_authority": False,
        "position": 2,
        "previous_version_id": "R-1.v1",
        "revision_index": 2,
        "validation_strengthening": True,
    }
    assert project_requirement_freshness_facts(events) == [
        {
            "requirement_id": "R-1",
            "active_version_id": "R-1.v2",
            "revision_classification": "validation_strengthening",
            "requires_authority": False,
            "authority_required_reason": None,
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        }
    ]


def test_support_evidence_freshness_can_be_queried_from_projection() -> None:
    state = initial_projection()
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
        ).model_copy(update={"position": 2}),
    ]
    for event in events:
        state = reduce_event(state, event)

    assert support_evidence_freshness_from_projection(state) == {
        "S-1": {
            "support_id": "S-1",
            "evidence_id": "E-1",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v1",
            "status": "active",
            "freshness": "fresh",
            "stale_reason": None,
        }
    }


def test_validation_strengthening_revision_invalidates_older_support_evidence() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-old",
                "evidence_id": "E-old",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
                "previous_version_id": "R-1.v1",
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 3}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-new",
                "evidence_id": "E-new",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v2",
            },
        ).model_copy(update={"position": 4}),
    ]

    assert project_support_evidence_freshness(events) == {
        "S-new": {
            "support_id": "S-new",
            "evidence_id": "E-new",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v2",
            "status": "active",
            "freshness": "fresh",
            "stale_reason": None,
        },
        "S-old": {
            "support_id": "S-old",
            "evidence_id": "E-old",
            "requirement_id": "R-1",
            "requirement_version_id": "R-1.v1",
            "status": "stale",
            "freshness": "stale",
            "stale_reason": (
                "Evidence was produced for an older requirement version and does not "
                "prove the strengthened validation definition."
            ),
        },
    }


def test_semantic_and_new_behavior_revisions_require_explicit_authority() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v1",
                "classification": "semantic",
            },
        ).model_copy(update={"position": 1}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-2",
                "version_id": "R-2.v1",
                "new_behavior": True,
            },
        ).model_copy(update={"position": 2}),
    ]

    facts = project_requirement_freshness_facts(events)

    assert facts == [
        {
            "requirement_id": "R-1",
            "active_version_id": "R-1.v1",
            "revision_classification": "semantic",
            "requires_authority": True,
            "authority_required_reason": "semantic",
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        },
        {
            "requirement_id": "R-2",
            "active_version_id": "R-2.v1",
            "revision_classification": "new_behavior",
            "requires_authority": True,
            "authority_required_reason": "new_behavior",
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        },
    ]


def test_planner_freshness_packet_is_compact_gap_planner_input() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-2",
                "version_id": "R-2.v1",
                "classification": "semantic",
            },
        ).model_copy(update={"position": 3}),
    ]

    assert project_planner_freshness_packet(events) == {
        "requirement_freshness": [
            {
                "requirement_id": "R-1",
                "active_version_id": "R-1.v1",
                "revision_classification": "initial",
                "requires_authority": False,
                "authority_required_reason": None,
                "fresh_support_ids": ["S-1"],
                "stale_support_ids": [],
                "unsupported": False,
            },
            {
                "requirement_id": "R-2",
                "active_version_id": "R-2.v1",
                "revision_classification": "semantic",
                "requires_authority": True,
                "authority_required_reason": "semantic",
                "fresh_support_ids": [],
                "stale_support_ids": [],
                "unsupported": True,
            },
        ],
        "unsupported_requirement_ids": ["R-2"],
        "stale_support_ids": [],
        "authority_required_requirement_ids": ["R-2"],
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


def test_final_invariant_blockers_are_projected_from_graph_events() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "ready",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "gate-planner-budget-planner-1",
                "kind": "gate",
                "role": "planner_generation_budget_gate",
                "state": "planned",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
    ]

    blockers: list[FinalInvariantBlocker] = project_final_invariant_blockers(events)
    assert blockers == [
        {
            "kind": "pending_planner_generation_budget_gate",
            "reason": "planner generation budget gate is unresolved",
            "node_id": "gate-planner-budget-planner-1",
            "state": "planned",
        },
        {
            "kind": "pending_planner",
            "reason": "planner node has not completed",
            "node_id": "planner-1",
            "state": "ready",
        },
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        },
    ]


def test_final_invariant_blockers_include_generic_non_terminal_nodes() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "blocked",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "state": "suspended",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "running",
                "task_region_id": "task-1",
            },
        ),
    ]

    blockers: list[FinalInvariantBlocker] = project_final_invariant_blockers(events)

    assert blockers == [
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "authority-1",
            "state": "blocked",
        },
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "human-gate-1",
            "state": "blocked",
        },
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "verifier-1",
            "state": "suspended",
            "task_region_id": "task-1",
        },
        {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": "worker-1",
            "state": "running",
            "task_region_id": "task-1",
        },
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        },
    ]


def test_check_only_task_region_uses_contract_fulfillment() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-check-only",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-1-result",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "task_region_id": "task-check-only",
                "value": {"status": "passed"},
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert blockers == []
    assert project_task_states(events) == {"task-check-only": "accepted"}


def test_check_only_task_region_missing_contract_output_is_blocked() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-check-only",
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert {
        "kind": "node_unfulfilled",
        "reason": "node contract fulfillment outputs are missing",
        "node_id": "check-1",
        "state": "completed",
        "support_ids": ["check_result"],
        "task_region_id": "task-check-only",
    } in blockers
    assert {
        "kind": "task_not_accepted",
        "reason": "task region has not reached accepted",
        "task_region_id": "task-check-only",
        "state": "pending",
    } in blockers


def test_final_invariant_blockers_explain_required_edge_with_missing_producer() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-missing-candidate",
                "from_node_id": "missing-worker",
                "from_port": "candidate",
                "to_node_id": "worker-1",
                "to_port": "candidate",
                "required": True,
                "dependency_type": "input_binding",
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert {
        "kind": "impossible_input",
        "reason": "required input edge has no producer node",
        "node_id": "worker-1",
        "edge_id": "edge-missing-candidate",
        "to_port": "candidate",
        "task_region_id": "task-1",
        "state": "planned",
    } in blockers


def test_gap_planner_task_region_uses_contract_fulfillment() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "completed",
                "task_region_id": "task-planner-only",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "gap-planner-1",
                "kind": "gap_planner",
                "state": "completed",
                "task_region_id": "task-gap-only",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "classified-gap-1",
                "record_kind": "output",
                "record_type": "classified_gap",
                "producer_node_id": "gap-planner-1",
                "port": "classified_gap",
                "task_region_id": "task-gap-only",
            },
        ),
    ]

    blockers = project_final_invariant_blockers(events)

    assert {
        "kind": "task_not_accepted",
        "reason": "task region has not reached accepted",
        "task_region_id": "task-planner-only",
        "state": "pending",
    } in blockers
    assert all(blocker.get("task_region_id") != "task-gap-only" for blocker in blockers)
    assert project_task_states(events) == {
        "task-gap-only": "accepted",
        "task-planner-only": "pending",
    }


def test_active_nonterminal_random_graph_shapes_have_explicit_blockers() -> None:
    rng = random.Random(17)
    node_kinds = ["worker", "verifier", "check", "human_gate", "authority_request"]
    node_states = ["planned", "ready", "leased", "running", "blocked", "suspended"]

    for graph_index in range(30):
        events = [_event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"})]
        node_count = rng.randint(1, 6)
        expected_node_ids: set[str] = set()
        for node_index in range(node_count):
            kind = rng.choice(node_kinds)
            state = rng.choice(node_states)
            node_id = f"{kind}-{graph_index}-{node_index}"
            task_region_id = f"task-{graph_index}-{rng.randint(1, 3)}"
            payload: dict[str, Any] = {
                "node_id": node_id,
                "kind": kind,
                "state": state,
            }
            if kind not in {"human_gate", "authority_request"}:
                payload["task_region_id"] = task_region_id
            events.append(_event("node_created", payload))
            expected_node_ids.add(node_id)

        blockers = project_final_invariant_blockers(events)
        blocker_node_ids = {
            node_id for blocker in blockers if isinstance((node_id := blocker.get("node_id")), str)
        }

        assert blockers, f"graph {graph_index} silently quiesced"
        assert expected_node_ids <= blocker_node_ids


def test_decision_view_projects_human_gate_and_authority_request() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "human-gate-1",
                "kind": "human_gate",
                "state": "blocked",
                "reason": "approve final scope",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
                "reason": "needs graph_write",
            },
        ),
    ]

    view = project_decision_view(events)

    assert view["pending_gates"] == [
        {
            "node_id": "authority-1",
            "gate_type": "authority_request",
            "prompt": "needs graph_write",
        },
        {
            "node_id": "human-gate-1",
            "gate_type": "approve final scope",
            "prompt": "approve final scope",
        },
    ]


def test_decision_view_clears_resolved_authority_request() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
                "reason": "needs graph_write",
            },
        ),
        _event(
            "authority_decision_recorded",
            {
                "node_id": "authority-1",
                "decision": "granted",
                "decider": {"kind": "human", "id": "alice"},
            },
        ),
    ]

    assert project_decision_view(events)["pending_gates"] == []


def test_completed_lifecycle_projects_active_while_final_blockers_remain() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        }
    ]
    assert project_run_state(events) == "active"


def test_final_gate_requires_passed_completion_decision_for_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "missing_completion_decision",
            "reason": "final gate has not produced a completion_decision",
            "node_id": "gate-final",
            "state": "completed",
        }
    ]
    assert project_run_state(events) == "active"


def test_blocked_final_gate_completion_decision_keeps_projected_run_active() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {
                    "status": "blocked",
                    "blockers": [
                        {
                            "kind": "open_planner_proposal",
                            "reason": "planner proposal has not been accepted or rejected",
                            "proposal_id": "proposal-1",
                        }
                    ],
                },
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "open_planner_proposal",
            "reason": "planner proposal has not been accepted or rejected",
            "proposal_id": "proposal-1",
        }
    ]
    assert project_run_state(events) == "active"


def test_passed_final_gate_completion_decision_allows_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-1",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "gate-final",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {"status": "passed", "blockers": []},
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_pending_gap_planner_blocks_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "gap-planner-1",
                "kind": "gap_planner",
                "role": "gap_planner",
                "state": "leased",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "pending_gap_planner",
            "reason": "planner node has not completed",
            "node_id": "gap-planner-1",
            "state": "leased",
        }
    ]
    assert project_run_state(events) == "active"


def test_pending_check_blocks_projected_completion_after_task_acceptance() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "planned",
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}
    assert project_final_invariant_blockers(events) == [
        {
            "kind": "pending_check",
            "reason": "check node has not completed",
            "node_id": "check-final-1",
            "state": "planned",
        }
    ]
    assert project_run_state(events) == "active"


def test_failed_check_result_blocks_projected_completion_after_task_acceptance() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-1"],
                "file_state_record_ids": ["file-state-candidate-1"],
                "evaluated_record_ids": ["candidate-1", "file-state-candidate-1"],
                "value": {
                    "status": "failed",
                    "exit_code": 1,
                    "candidate_record_ids": ["candidate-1"],
                    "file_state_record_ids": ["file-state-candidate-1"],
                    "evaluated_record_ids": ["candidate-1", "file-state-candidate-1"],
                },
            },
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    check_result = projection["check_results"]["check-final-1"]
    assert check_result["candidate_record_ids"] == ["candidate-1"]
    assert check_result["file_state_record_ids"] == ["file-state-candidate-1"]
    assert check_result["evaluated_record_ids"] == ["candidate-1", "file-state-candidate-1"]
    assert project_task_states(events) == {"task-1": "pending"}
    assert project_final_invariant_blockers(events) == [
        {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
            "node_id": "check-final-1",
            "task_region_id": "task-1",
            "state": "failed",
        },
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        },
    ]
    assert project_run_state(events) == "active"


def test_check_result_candidate_id_does_not_replace_latest_task_candidate() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 1}),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 2}),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-check-final-1",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-1"],
                "evaluated_record_ids": ["candidate-1"],
                "value": {
                    "status": "passed",
                    "exit_code": 0,
                    "candidate_record_ids": ["candidate-1"],
                    "evaluated_record_ids": ["candidate-1"],
                },
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)

    assert projection["task_candidates"]["task-1"] == [
        {
            "candidate_id": "candidate-1",
            "attempt_number": 0,
            "position": 1,
            "file_state_record_ids": [],
        }
    ]
    assert project_task_states(events) == {"task-1": "accepted"}
    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_uncited_check_result_does_not_accept_task_region() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "file_state_record_ids": ["file-state-candidate-1"],
                "value": {"file_state_record_ids": ["file-state-candidate-1"]},
            },
        ).model_copy(update={"position": 1}),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 2}),
        _file_state_event("task-1", "candidate-1", 3),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-check-final-1",
                "task_region_id": "task-1",
                "value": {"status": "passed", "exit_code": 0},
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events) == {"task-1": "pending"}
    assert project_final_invariant_blockers(events) == [
        {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": "task-1",
            "state": "pending",
        }
    ]
    assert project_run_state(events) == "active"


def test_check_result_must_cite_latest_candidate_file_state() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-old",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-old",
                "task_region_id": "task-1",
                "attempt_number": 1,
                "file_state_record_ids": ["file-state-old"],
                "value": {"file_state_record_ids": ["file-state-old"]},
            },
        ).model_copy(update={"position": 1}),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-new",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-new",
                "task_region_id": "task-1",
                "attempt_number": 2,
                "file_state_record_ids": ["file-state-candidate-new"],
                "value": {"file_state_record_ids": ["file-state-candidate-new"]},
            },
        ).model_copy(update={"position": 2}),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "candidate_id": "candidate-new",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 3}),
        _file_state_event("task-1", "candidate-new", 4),
        _event(
            "node_created",
            {
                "node_id": "check-final-1",
                "kind": "check",
                "state": "completed",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "task-1",
                "candidate_record_ids": ["candidate-old"],
                "file_state_record_ids": ["file-state-old"],
                "value": {
                    "status": "passed",
                    "candidate_record_ids": ["candidate-old"],
                    "file_state_record_ids": ["file-state-old"],
                },
            },
        ).model_copy(update={"position": 5}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_task_states(events) == {"task-1": "pending"}
    assert project_run_state(events) == "active"


def test_open_proposal_blocks_projected_completion_until_resolved() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("proposal_opened", {"proposal_id": "proposal-1"}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "open_planner_proposal",
            "reason": "planner proposal has not been accepted or rejected",
            "proposal_id": "proposal-1",
        }
    ]
    assert project_run_state(events) == "active"

    resolved = [
        *events[:2],
        _event("proposal_accepted", {"proposal_id": "proposal-1"}),
        events[2],
    ]
    assert project_final_invariant_blockers(resolved) == []
    assert project_run_state(resolved) == "completed"


def test_accepted_graph_patch_does_not_leave_open_proposal_blocker() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("graph_patch_proposed", {"patch_id": "patch-1"}),
        _event("graph_patch_accepted", {"patch_id": "patch-1"}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_freshness_and_authority_facts_block_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-01", "version_id": "R-01.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-old",
                "evidence_id": "E-old",
                "requirement_id": "R-01",
                "requirement_version_id": "R-01.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-01",
                "version_id": "R-01.v2",
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 3}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-02",
                "version_id": "R-02.v1",
                "classification": "semantic",
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "stale_support_evidence",
            "reason": "active requirement is supported only by stale evidence",
            "requirement_id": "R-01",
            "support_ids": ["S-old"],
        },
        {
            "kind": "unsupported_active_requirement",
            "reason": "active requirement has no current supporting evidence",
            "requirement_id": "R-01",
            "support_ids": ["S-old"],
        },
        {
            "kind": "unsupported_active_requirement",
            "reason": "active requirement has no current supporting evidence",
            "requirement_id": "R-02",
            "support_ids": [],
        },
        {
            "kind": "unresolved_authority_required_revision",
            "reason": "semantic or new-behavior requirement revision lacks authority resolution",
            "revision_id": "R-02.v1",
            "requirement_id": "R-02",
        },
    ]
    assert project_run_state(events) == "active"


def test_later_fresh_support_clears_requirement_freshness_blocker() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-01", "version_id": "R-01.v1"},
        ).model_copy(update={"position": 1}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-old",
                "evidence_id": "E-old",
                "requirement_id": "R-01",
                "requirement_version_id": "R-01.v1",
            },
        ).model_copy(update={"position": 2}),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-01",
                "version_id": "R-01.v2",
                "classification": "validation_strengthening",
            },
        ).model_copy(update={"position": 3}),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-fresh",
                "evidence_id": "E-fresh",
                "requirement_id": "R-01",
                "requirement_version_id": "R-01.v2",
            },
        ).model_copy(update={"position": 4}),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == []
    assert project_run_state(events) == "completed"


def test_suspect_and_blocked_requirement_facts_block_projected_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}),
        _event(
            "node_created",
            {
                "node_id": "requirement-1",
                "kind": "requirement",
                "state": "blocked",
                "requirement": {"id": "R-01", "priority": "expected"},
            },
        ),
        _event(
            "plan_region_marked_suspect",
            {"region_node_ids": ["worker-1"], "reason": "requirement_changed"},
        ),
        _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"}),
    ]

    assert project_final_invariant_blockers(events) == [
        {
            "kind": "suspect_active_node",
            "reason": "requirement_changed",
            "node_id": "worker-1",
            "state": "ready",
        },
        {
            "kind": "blocked_requirement",
            "reason": "must or expected requirement is blocked without accepted blocker",
            "node_id": "requirement-1",
            "requirement_id": "R-01",
            "state": "blocked",
        },
    ]
    assert project_run_state(events) == "active"


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
        _file_state_event("task-1", "cand-1", 2),
        _event(
            "approval_decision_recorded",
            {"task_region_id": "task-1", "gate_id": "gate-1", "approved": True},
        ).model_copy(update={"position": 3}),
    ]

    assert project_task_states(events) == {"task-1": "accepted"}


def test_task_projection_accepts_no_verifier_region_after_file_state() -> None:
    events = [
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "task_region_id": "task-1"},
        ).model_copy(update={"position": 0}),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "task_region_id": "task-1",
            },
        ).model_copy(update={"position": 1}),
        _file_state_event("task-1", "candidate-1", 2),
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
        _file_state_event("task-1", "cand-1", 3),
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
        _file_state_event("task-1", "candidate-1", 3),
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
        _file_state_event("task-1", "cand-later", 3),
        _event("verification_failed", {"candidate_id": "cand-old"}).model_copy(
            update={"position": 4}
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
        _file_state_event("task-1", "cand-2", 5),
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
