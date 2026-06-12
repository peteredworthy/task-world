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


def test_fixture_corpus_then_projections_satisfied() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        assert isinstance(raw, list), f"{path.name} must contain a list of scenarios"
        for scenario in raw:
            assert isinstance(scenario, dict), f"{path.name} contains a non-mapping scenario"
            typed_scenario = cast(dict[str, Any], scenario)
            then_projection = typed_scenario.get("then_projection")
            if not then_projection:
                continue
            assert isinstance(then_projection, dict)

            result = run_scenario(
                typed_scenario,
                InMemoryEventStore(),
                FakeClock(),
                SequentialIdGenerator(),
            )

            assert result.passed, f"{typed_scenario['name']}: {result.failures}"
