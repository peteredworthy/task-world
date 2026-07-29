import pytest
from pydantic import ValidationError

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    CallbackAcceptedPayload,
    FakeClock,
    RunLifecycleChangedPayload,
    SequentialIdGenerator,
    build_projection,
    retry_not_before_by_node_view,
)
from tests.unit.graph_test_utils import apply_command, command_context
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph import event_factory
from tests.unit.graph_test_utils import event


def test_lifecycle_payload_serializes_canonical_shape() -> None:
    raw = {
        "command_type": "start",
        "from_state": "queued",
        "to_state": "active",
        "trigger": "start_command_accepted",
    }
    assert (
        RunLifecycleChangedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"to_state": "active", "future_field": True},
        {"to_state": 7},
    ],
)
def test_lifecycle_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunLifecycleChangedPayload.model_validate(raw)


def test_callback_payload_requires_explicit_payload_even_when_null() -> None:
    raw = {
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "execution_id": "exec-1",
        "idempotency_key": "callback-1",
        "reason": "accepted",
    }
    with pytest.raises(ValidationError):
        CallbackAcceptedPayload.model_validate(raw)
    explicit_null = CallbackAcceptedPayload.model_validate({**raw, "payload": None})
    assert "payload" in explicit_null.model_fields_set
    assert explicit_null.model_dump(mode="json")["payload"] is None


def test_lifecycle_producer_matches_typed_payload_json() -> None:
    events = [
        event(
            "run_lifecycle_changed",
            {
                "command_type": "accept_run",
                "from_state": "draft",
                "to_state": "queued",
                "trigger": "accept_run_command_accepted",
            },
            position=1,
        )
    ]
    emitted = apply_command(
        build_projection(events),
        events,
        "start",
        {},
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )
    payload = next(item.payload for item in emitted if item.event_type == "run_lifecycle_changed")

    assert payload == RunLifecycleChangedPayload.model_validate(payload).model_dump(
        mode="json", exclude_unset=True
    )


def test_lifecycle_event_factory_excludes_explicit_none() -> None:
    make_event = event_factory("run-1", "start", FakeClock(), SequentialIdGenerator())

    emitted = make_event(
        "run_lifecycle_changed",
        {
            "command_type": "start",
            "from_state": "queued",
            "to_state": "active",
            "trigger": "start_command_accepted",
            "reason": None,
        },
    )

    assert emitted.payload == {
        "command_type": "start",
        "from_state": "queued",
        "to_state": "active",
        "trigger": "start_command_accepted",
    }


@pytest.mark.asyncio
async def test_sqlite_compact_readers_retain_runtime_retry_backoff() -> None:
    retry_not_before = "2026-07-09T12:01:00+00:00"
    retry = event(
        "runtime_retry_scheduled",
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "generation": 1,
            "policy": "v1_requeue_same_node_after_agent_death",
            "reason": "process_exit",
            "retry_after_seconds": 60,
            "retry_not_before": retry_not_before,
        },
        position=1,
    )
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events("run-1", 0, [retry])
            store = GraphEventStore(session)
            for reader in (
                store.read_run_projection,
                store.read_run_light,
                store.read_run_summary_rebuild,
                store.read_run_node_detail,
            ):
                compact_events = await reader("run-1")
                assert compact_events[0].payload["retry_not_before"] == retry_not_before
                assert retry_not_before_by_node_view(build_projection(compact_events)) == {
                    "worker-1": retry_not_before
                }
    finally:
        await engine.dispose()
