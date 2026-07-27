from datetime import UTC, datetime

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
