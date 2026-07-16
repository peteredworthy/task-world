import pytest
from pydantic import ValidationError

import orchestrator.graph as graph
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph_runtime import GraphEventStore


def _dispatch_payload() -> dict[str, object]:
    return {
        "lease_granted_event_id": "event-lease-granted",
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "generation": 1,
        "execution_id": "exec-1",
        "base_snapshot_id": "S0",
        "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
    }


def _command_payload() -> dict[str, object]:
    return {
        "command_type": "schedule_tick",
        "command_payload": {"base_snapshot_id": "S0", "lease_seconds": 60},
    }


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("agent_dispatch_requested", _dispatch_payload()),
        ("command_recorded", _command_payload()),
    ],
)
def test_runtime_event_payload_models_serialize_canonical_json(
    event_type: str,
    payload: dict[str, object],
) -> None:
    model = graph.EVENT_PAYLOAD_MODELS[event_type]

    assert model.model_validate(payload).model_dump(mode="json", exclude_none=True) == payload


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("agent_dispatch_requested", {**_dispatch_payload(), "future_field": True}),
        ("agent_dispatch_requested", {**_dispatch_payload(), "generation": "1"}),
        (
            "agent_dispatch_requested",
            {
                **_dispatch_payload(),
                "resource_claims": [
                    {
                        "mode": "write",
                        "scope": "repo",
                        "paths": ["src/**"],
                        "future_field": True,
                    }
                ],
            },
        ),
        ("command_recorded", {**_command_payload(), "node_id": "worker-1"}),
        ("command_recorded", {"command_type": 7, "command_payload": {}}),
        ("command_recorded", {"command_type": "start", "command_payload": []}),
        ("command_recorded", {"command_type": "start", "reason": "flattened"}),
    ],
)
def test_runtime_event_payload_models_reject_unknown_and_wrong_typed_fields(
    event_type: str,
    payload: dict[str, object],
) -> None:
    model = graph.EVENT_PAYLOAD_MODELS[event_type]

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_public_event_serializer_uses_canonical_runtime_event_models() -> None:
    serializer = getattr(graph, "serialize_event_payload", None)
    assert callable(serializer)

    serialize = serializer
    assert serialize("agent_dispatch_requested", _dispatch_payload()) == _dispatch_payload()
    assert serialize("command_recorded", _command_payload()) == _command_payload()
    with pytest.raises(ValidationError):
        serialize(
            "command_recorded",
            {"command_type": "start", "command_payload": {}, "unexpected": True},
        )


@pytest.mark.asyncio
async def test_runtime_event_payloads_have_full_compact_reader_parity() -> None:
    payloads = {
        "agent_dispatch_requested": _dispatch_payload(),
        "command_recorded": _command_payload(),
    }
    events = [
        graph.EventEnvelope(
            event_id=f"event-{index}",
            run_id="run-1",
            position=-1,
            event_type=event_type,
            schema_version=1,
            actor=graph.Actor(kind=graph.ActorKind.CONTROLLER),
            timestamp=graph.FakeClock().now(),
            payload=payload,
        )
        for index, (event_type, payload) in enumerate(payloads.items(), start=1)
    ]
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events("run-1", 0, events)
            store = GraphEventStore(session)
            readers = (
                store.read_run_projection,
                store.read_run_light,
                store.read_run_summary_rebuild,
                store.read_run_node_detail,
            )
            for reader in readers:
                compact = await reader("run-1")
                assert {event.event_type: event.payload for event in compact} == payloads
    finally:
        await engine.dispose()
