"""Unit coverage for idempotent graph node-usage facts."""

from datetime import UTC, datetime

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCommandContext,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
)


def _event(event_type: str, payload: dict[str, object], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{position}",
        run_id="run-usage",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def test_record_node_usage_emits_one_idempotent_fact_per_execution_model() -> None:
    projection = initial_projection()
    context = GraphCommandContext(run_id="run-usage", current_graph_position=0)

    events = apply_command(
        projection,
        [],
        "record_node_usage",
        {
            "node_id": "worker-1",
            "node_kind": "worker",
            "node_role": "builder",
            "profile": "coder",
            "execution_id": "execution-1",
            "usage": [
                {
                    "model": "model-a",
                    "gen_ai_usage_input_tokens": 100,
                    "gen_ai_usage_output_tokens": 50,
                    "gen_ai_usage_cache_read_input_tokens": 20,
                    "gen_ai_usage_cache_creation_input_tokens": 0,
                    "gen_ai_usage_reasoning_output_tokens": 10,
                    "gen_ai_response_finish_reasons": ["stop"],
                    "cost_usd": 0.25,
                    "latency_ms": 900,
                    "rate_missing": False,
                },
                {
                    "model": "model-b",
                    "gen_ai_usage_input_tokens": 200,
                    "gen_ai_usage_output_tokens": 20,
                    "cost_usd": 0.5,
                    "latency_ms": 900,
                    "rate_missing": True,
                },
            ],
        },
        context,
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert [event.event_type for event in events] == ["node_usage_recorded", "node_usage_recorded"]
    assert [event.payload["usage_key"] for event in events] == ["execution-1:0", "execution-1:1"]
    assert [event.payload["usage_count"] for event in events] == [2, 2]
    assert [event.payload["profile"] for event in events] == ["coder", "coder"]


def test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once() -> None:
    usage_payload = {
        "node_id": "worker-1",
        "node_kind": "worker",
        "node_role": "builder",
        "profile": "coder",
        "execution_id": "execution-1",
        "usage_index": 0,
        "usage_count": 2,
        "usage_key": "execution-1:0",
        "model": "model-a",
        "gen_ai_usage_input_tokens": 100,
        "gen_ai_usage_output_tokens": 50,
        "gen_ai_usage_cache_read_input_tokens": 20,
        "gen_ai_usage_cache_creation_input_tokens": 0,
        "gen_ai_usage_reasoning_output_tokens": 10,
        "gen_ai_response_finish_reasons": ["stop"],
        "cost_usd": 0.25,
        "latency_ms": 900,
        "rate_missing": False,
    }
    second_usage_payload = {
        **usage_payload,
        "usage_index": 1,
        "usage_key": "execution-1:1",
        "model": "model-b",
        "gen_ai_usage_input_tokens": 200,
        "gen_ai_usage_output_tokens": 20,
        "rate_missing": True,
    }

    projection = initial_projection()
    for event in (
        _event("node_usage_recorded", usage_payload, 1),
        _event("node_usage_recorded", second_usage_payload, 2),
        _event("node_usage_recorded", usage_payload, 3),
    ):
        projection = reduce_event(projection, event)

    assert projection["recorded_node_usage_keys"] == {"execution-1:0": True, "execution-1:1": True}
    assert projection["tokens_by_node"] == {"worker-1": 370}
    assert projection["tokens_by_node_kind"] == {"worker": 370}
    assert projection["latency_ms_by_node_kind"] == {"worker": 900}
    assert projection["execution_count_by_node_kind"] == {"worker": 1}

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))
    assert restored["tokens_by_node"] == {"worker-1": 370}
    assert restored["recorded_node_usage_keys"] == {"execution-1:0": True, "execution-1:1": True}
