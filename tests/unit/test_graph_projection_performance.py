"""Direct deterministic performance contract for pure graph projection replay."""

from datetime import UTC, datetime, timedelta
from statistics import median
from time import perf_counter
from typing import Literal

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjection,
    accepted_record_summaries_by_id_view,
    edges_view,
    initial_projection,
    node_states_view,
    reduce_event,
)

pytestmark = pytest.mark.slow


SCENARIOS = ("general", "edge-heavy", "record-heavy")
EVENT_COUNT = 10_000


def _performance_event(index: int, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"performance-{event_type}-{index}",
        run_id="performance-run",
        position=index,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        payload=payload,
    )


def _performance_event_stream(
    scenario: Literal["general", "edge-heavy", "record-heavy"], size: int
) -> tuple[EventEnvelope, ...]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown performance scenario: {scenario}")
    if size <= 0:
        raise ValueError("performance event stream size must be positive")

    def node_event(index: int, node_id: str) -> EventEnvelope:
        return _performance_event(
            index,
            "node_created",
            {"node_id": node_id, "kind": "worker", "state": "planned"},
        )

    def edge_event(index: int, previous_node_id: str, node_id: str) -> EventEnvelope:
        return _performance_event(
            index,
            "edge_created",
            {
                "edge_id": f"performance-edge-{index:06d}",
                "from_node_id": previous_node_id,
                "from_port": "output",
                "to_node_id": node_id,
                "to_port": "input",
                "dependency_type": "input_binding",
            },
        )

    def record_event(index: int, node_id: str) -> EventEnvelope:
        body = f"{scenario}-record-value-{index:06d}"
        return _performance_event(
            index,
            "output_record_accepted",
            {
                "record_id": f"performance-{scenario}-record-{index:06d}",
                "record_type": "fan_out_inputs",
                "record_kind": "output",
                "producer_node_id": node_id,
                "producer_port": "candidate",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {
                    "index": index,
                    "summary": body,
                    "changed_paths": [f"src/{index:06d}.py"],
                },
                "payload": {"corpus": scenario, "sequence": index},
                "provenance": {"producer": node_id, "source": "performance"},
            },
        )

    events = [node_event(0, "performance-node-000000")]
    for index in range(1, size):
        if scenario == "record-heavy":
            events.append(record_event(index, "performance-node-000000"))
        elif scenario == "edge-heavy":
            node_number = (index + 1) // 2
            node_id = f"performance-node-{node_number:06d}"
            if index % 2:
                events.append(node_event(index, node_id))
            else:
                events.append(edge_event(index, f"performance-node-{node_number - 1:06d}", node_id))
        else:
            node_number = (index + 3) // 4
            node_id = f"performance-node-{node_number:06d}"
            phase = (index - 1) % 4
            if phase == 0:
                events.append(node_event(index, node_id))
            elif phase == 1:
                events.append(edge_event(index, f"performance-node-{node_number - 1:06d}", node_id))
            elif phase == 2:
                events.append(
                    _performance_event(
                        index,
                        "node_state_changed",
                        {"node_id": node_id, "new_state": "ready", "reason": "performance"},
                    )
                )
            else:
                events.append(record_event(index, node_id))
    return tuple(events)


def _replay(events: tuple[EventEnvelope, ...]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


@pytest.mark.xdist_group(name="graph-projection-performance")
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ten_thousand_event_replay_median_is_strictly_subsecond(scenario: str) -> None:
    events = _performance_event_stream(scenario, EVENT_COUNT)
    assert len(events) == EVENT_COUNT
    assert len({event.event_id for event in events}) == EVENT_COUNT
    assert tuple(event.position for event in events) == tuple(range(EVENT_COUNT))

    warmup = _replay(events)
    samples: list[float] = []
    results: list[GraphProjection] = []
    for _ in range(3):
        started = perf_counter()
        results.append(_replay(events))
        samples.append(perf_counter() - started)

    expected_nodes = sum(event.event_type == "node_created" for event in events)
    expected_edges = sum(event.event_type == "edge_created" for event in events)
    expected_records = sum(event.event_type == "output_record_accepted" for event in events)
    assert all(result == warmup for result in results)
    assert len(node_states_view(warmup)) == expected_nodes
    assert len(edges_view(warmup)) == expected_edges
    assert len(accepted_record_summaries_by_id_view(warmup)) == expected_records
    assert expected_nodes > 0
    if scenario != "record-heavy":
        assert expected_edges > 0
    if scenario != "edge-heavy":
        assert expected_records > 0
    assert median(samples) < 1.0, (scenario, samples)
