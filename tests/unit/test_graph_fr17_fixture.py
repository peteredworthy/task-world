from datetime import UTC, datetime
from hashlib import sha256
import json

from tests.graph_fr17_fixture import less_used_events


def test_less_used_events_are_deterministic_and_scoped_to_run() -> None:
    run_id = "deterministic-fr17-run"

    first = less_used_events(run_id)
    second = less_used_events(run_id)

    assert first == second
    assert [event.event_id for event in first] == [
        f"fr17-event-{position}" for position in range(1, len(first) + 1)
    ]
    assert [event.timestamp for event in first] == [datetime(2026, 1, 1, tzinfo=UTC)] * len(first)
    assert [event.run_id for event in first] == [run_id] * len(first)
    assert [
        event.payload["bound_at_position"] for event in first if event.event_type == "input_bound"
    ] == [0, 0]
    assert [event.event_type for event in first] == [
        "run_lifecycle_changed",
        "node_created",
        "output_record_accepted",
        "node_created",
        "node_created",
        "node_created",
        "node_created",
        "node_deferred",
        "node_created",
        "node_created",
        "node_created",
        "node_created",
        "edge_created",
        "output_record_accepted",
        "input_bound",
        "lease_granted",
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
        "edge_created",
        "input_bound",
        "output_record_accepted",
        "output_record_accepted",
        "edge_created",
        "node_created",
        "output_record_accepted",
        "appeal_opened",
        "oversight_decision_recorded",
        "graph_patch_rejected",
    ]
    signature = json.dumps(
        [event.model_dump(mode="json") for event in first],
        sort_keys=True,
        separators=(",", ":"),
    )
    assert (
        sha256(signature.encode()).hexdigest()
        == "3026b0b3ffe4552322fcf0bf8a99eb0ba51bae45200f9c444cc7d54bea11e29d"
    )
