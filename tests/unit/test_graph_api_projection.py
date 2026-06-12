"""Unit tests for graph API projection helpers."""

from orchestrator.api import (
    _graph_backed_run_ids_from_rows,
    build_graph_projection_response,
    build_node_detail_response,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock


def _event(event_type: str, payload: dict[str, object], *, run_id: str = "run-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-event",
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def test_build_graph_projection_response_empty() -> None:
    projection = build_graph_projection_response("run-empty", [])

    assert projection.run_id == "run-empty"
    assert projection.event_count == 0
    assert projection.run_state is None
    assert projection.node_states == {}
    assert projection.task_states == {}
    assert projection.leases == {}
    assert projection.ready_nodes == []


def test_build_node_detail_filters_by_node_id() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "node-a",
                "kind": "worker",
                "state": "planned",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "node-b",
                "kind": "worker",
                "state": "planned",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "node-a",
                "new_state": "ready",
                "old_state": "planned",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "node-b",
                "new_state": "running",
                "old_state": "planned",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "out-a",
                "record_kind": "output",
                "producer_node_id": "node-a",
                "task_region_id": "task-a",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "out-b",
                "record_kind": "graph_record",
                "producer_node_id": "node-b",
                "task_region_id": "task-b",
            },
        ),
        _event(
            "file_state_accepted",
            {
                "path": "README.md",
                "producer_node_id": "node-a",
                "state": "unchanged",
            },
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "node-a",
                "new_state": "completed",
            },
        ),
    ]

    detail = build_node_detail_response("run-node", "node-a", events)

    assert detail is not None
    assert detail.node_id == "node-a"
    assert detail.state == "completed"
    assert len(detail.output_records) == 1
    assert detail.output_records[0]["record_id"] == "out-a"
    assert len(detail.file_state_records) == 1
    assert detail.file_state_records[0]["path"] == "README.md"
    assert [e.event_id for e in detail.events] == [
        "node_created-event",
        "node_state_changed-event",
        "output_record_accepted-event",
        "file_state_accepted-event",
        "node_state_changed-event",
    ]


def test_batch_graph_backed_detection() -> None:
    rows: list[tuple[str, int]] = [("run-draft", 0), ("run-queued", 2), ("run-complete", 1)]
    assert _graph_backed_run_ids_from_rows(rows) == {"run-queued", "run-complete"}
