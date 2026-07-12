from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    AgentDiedPayload,
    CallbackAcceptedPayload,
    CallbackDuplicateReturnedPayload,
    CallbackRejectedPayload,
    CommandRejectedPayload,
    CommandExecutionContext,
    DeadInputDetectedPayload,
    EventEnvelope,
    FakeClock,
    HEARTBEAT_RECORDED,
    HeartbeatRecordedPayload,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
    SequentialIdGenerator,
    apply_command,
    build_projection,
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
    build_graph_catalog,
    build_graph_command_dependencies,
    ProjectionParticipation,
    EventMetadata,
)
from orchestrator.graph_runtime.store import (
    GRAPH_PROJECTION_PAYLOAD_FIELDS,
    LIGHT_GRAPH_PAYLOAD_FIELDS,
    NODE_DETAIL_PAYLOAD_FIELDS,
    SUMMARY_REBUILD_PAYLOAD_FIELDS,
    GraphEventStore,
    _json_extract_payload_value,
    graph_aggregate_id,
)


def _typed_apply(events: list[EventEnvelope], command_type: str, payload: dict[str, Any]):
    clock = FakeClock()
    ids = SequentialIdGenerator()
    return apply_command(
        build_projection(build_graph_catalog(), events),
        events,
        command_type,
        {key: value for key, value in payload.items() if key != "run_id"},
        clock,
        ids,
        catalog=build_graph_catalog(),
        context=CommandExecutionContext(
            run_id=str(payload.get("run_id", "run-1")),
            current_position=max((e.position for e in events), default=-1),
            clock=clock,
            id_generator=ids,
            actor=Actor(kind=ActorKind.CONTROLLER),
            events=(),
            future_effects=build_graph_command_dependencies().future_effects,
        ),
    )


def _typed_event_type(event: Any) -> str:
    return event.event_type if isinstance(event, EventEnvelope) else event.metadata.event_type


def test_heartbeat_is_native_datetime_until_json_storage_boundary() -> None:
    clock = FakeClock()
    event = HEARTBEAT_RECORDED.create(
        EventMetadata(
            event_id="event-1",
            run_id="run-1",
            position=1,
            event_type=HEARTBEAT_RECORDED.name,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=clock.now(),
            payload_schema_generation=2,
        ),
        HeartbeatRecordedPayload(
            node_id="node-1",
            lease_id="lease-1",
            lease_generation=1,
            observed_at=clock.now(),
        ),
    )

    assert event.payload.observed_at == clock.now()
    assert isinstance(HEARTBEAT_RECORDED.serialize(event).payload["observed_at"], str)


STRICT_LIFECYCLE_EVENT_SAMPLES: dict[str, tuple[dict[str, Any], str]] = {
    "run_lifecycle_changed": ({"to_state": "active"}, "to_state"),
    "command_rejected": ({"command_type": "start", "reason": "illegal transition"}, "command_type"),
    "callback_accepted": (
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "idempotency_key": "key-1",
            "payload": None,
            "reason": "accepted",
        },
        "node_id",
    ),
    "callback_rejected_stale": (
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "idempotency_key": "key-1",
            "payload": None,
            "reason": "lease revoked",
        },
        "node_id",
    ),
    "callback_rejected_conflict": (
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "idempotency_key": "key-1",
            "payload": None,
            "reason": "node not running",
        },
        "node_id",
    ),
    "callback_duplicate_returned": (
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "idempotency_key": "key-1",
            "payload": None,
            "reason": "duplicate idempotent callback",
            "prior_result": None,
        },
        "node_id",
    ),
    "runtime_retry_scheduled": (
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "generation": 1,
            "policy": "v1_requeue_same_node_after_agent_death",
            "reason": "process_exit",
        },
        "generation",
    ),
    "heartbeat_recorded": (
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "observed_at": FakeClock().now(),
        },
        "lease_generation",
    ),
    "agent_died": (
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-1",
            "reason": "process_exit",
        },
        "generation",
    ),
    "agent_dispatch_requested": (
        {
            "lease_granted_event_id": "event-1",
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-1",
            "base_snapshot_id": "S0",
            "resource_claims": [],
        },
        "generation",
    ),
}


@pytest.mark.parametrize("event_name", STRICT_LIFECYCLE_EVENT_SAMPLES)
def test_lifecycle_event_specs_are_strict(event_name: str) -> None:
    sample, scalar_field = STRICT_LIFECYCLE_EVENT_SAMPLES[event_name]
    spec = build_graph_catalog().resolve_event(event_name)
    assert spec.validate_payload(sample).model_dump(mode="json")
    with pytest.raises(ValidationError):
        spec.validate_payload({**sample, "unknown_field": "forbidden"})
    with pytest.raises(ValidationError):
        spec.validate_payload({**sample, scalar_field: [sample[scalar_field]]})


@pytest.mark.parametrize(
    "event_name",
    (
        "command_rejected",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
        "heartbeat_recorded",
        "agent_died",
        "agent_dispatch_requested",
    ),
)
def test_lifecycle_audit_event_specs_are_projection_neutral(event_name: str) -> None:
    spec = build_graph_catalog().resolve_event(event_name)
    assert spec.projection_participation is ProjectionParticipation.NEUTRAL


def test_run_lifecycle_payload_accepts_declared_recovery_shape() -> None:
    sparse = RunLifecycleChangedPayload.model_validate({"to_state": "active"})
    recovery = RunLifecycleChangedPayload.model_validate(
        {
            "command_type": "schedule_tick",
            "from_state": "active",
            "to_state": "failed",
            "trigger": "recovery_planner_no_successor",
            "node_id": "recovery-1",
            "patch_id": "patch-1",
            "recovery_of_record_id": "failure-1",
            "recovery_reason": "verification_failed",
        }
    )
    assert sparse.to_state == "active"
    assert recovery.recovery_of_record_id == "failure-1"


def test_command_rejected_payload_models_blockers_and_patch_diagnostics() -> None:
    payload = CommandRejectedPayload.model_validate(
        {
            "command_type": "submit_patch",
            "reason": "final invariant blockers remain",
            "blockers": [{"kind": "open_proposal", "patch_id": "patch-1"}],
            "patch_id": "patch-1",
            "base_graph_position": 12,
            "actor_role": "planner",
            "proposed_by_node_id": "planner-1",
            "diagnostics": {"op_index": 2},
            "read_set_diff": {"missing": ["node-1"]},
        }
    )

    assert payload.blockers == [{"kind": "open_proposal", "patch_id": "patch-1"}]
    assert payload.base_graph_position == 12
    assert payload.diagnostics == {"op_index": 2}
    assert payload.read_set_diff == {"missing": ["node-1"]}


def test_callback_payloads_preserve_explicit_none_and_duplicate_prior_result() -> None:
    dumped = CallbackAcceptedPayload(
        node_id="n", idempotency_key="k", payload=None, reason="accepted"
    ).model_dump(mode="json")
    duplicate = CallbackDuplicateReturnedPayload.model_validate(
        {
            "node_id": "n",
            "lease_id": "lease-1",
            "lease_generation": 2,
            "idempotency_key": "k",
            "payload": None,
            "reason": "duplicate idempotency key",
            "prior_result": {"outcome": "callback_accepted", "payload": None},
        }
    )
    rejected = CallbackRejectedPayload.model_validate(
        {"node_id": "n", "idempotency_key": "k", "payload": None, "reason": "stale"}
    )

    assert "payload" in dumped
    assert dumped["payload"] is None
    assert duplicate.prior_result == {"outcome": "callback_accepted", "payload": None}
    assert rejected.reason == "stale"


def test_callback_accepted_reducer_records_idempotency_through_typed_payload() -> None:
    projection = reduce_event(
        build_graph_catalog(),
        initial_projection(),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": None,
                "reason": "accepted",
            },
            position=1,
        ),
    )

    recorded = projection["callback_idempotency_events"]["worker-1\0key-1"]
    assert recorded.event_type == "callback_accepted"
    assert recorded.payload is None


def test_runtime_retry_payload_preserves_retry_backoff_projection() -> None:
    payload = RuntimeRetryScheduledPayload.model_validate(
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "generation": 1,
            "policy": "v1_requeue_same_node_after_agent_death",
            "reason": "process_exit",
            "retry_after_seconds": 60,
            "retry_not_before": "2026-07-09T12:01:00+00:00",
        }
    )
    projection = reduce_event(
        build_graph_catalog(),
        initial_projection(),
        _event("runtime_retry_scheduled", payload.model_dump(mode="json"), position=1),
    )

    assert payload.retry_after_seconds == 60
    assert projection["retry_not_before_by_node"] == {"worker-1": "2026-07-09T12:01:00+00:00"}


def test_dead_input_audit_remains_projection_neutral() -> None:
    audit_payloads = [
        (
            "dead_input_detected",
            DeadInputDetectedPayload.model_validate(
                {
                    "node_id": "worker-1",
                    "from_node_id": "upstream-1",
                    "to_port": "candidate",
                    "reason": "upstream_failed:upstream-1",
                }
            ),
        ),
    ]
    baseline = projection_to_checkpoint(initial_projection())

    for position, (event_type, payload) in enumerate(audit_payloads, start=1):
        projected = reduce_event(
            build_graph_catalog(),
            initial_projection(),
            _event(event_type, payload.model_dump(mode="json"), position=position),
        )
        assert projection_to_checkpoint(projected) == baseline


def test_dead_input_audit_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DeadInputDetectedPayload.model_validate(
            {
                "node_id": "worker-1",
                "from_node_id": "upstream-1",
                "to_port": "candidate",
                "reason": "upstream_failed:upstream-1",
                "legacy": 1,
            }
        )


def test_lifecycle_callback_and_runtime_producers_emit_typed_payloads() -> None:
    lifecycle = _typed_apply(
        [_event("run_lifecycle_changed", {"to_state": "queued"}, position=1)],
        "start",
        {"run_id": "run-1"},
    )
    assert RunLifecycleChangedPayload.model_validate(lifecycle[0].payload).to_state == "active"

    events = _active_lease_events()
    callback = _typed_apply(
        events,
        "submit_callback",
        {
            "run_id": "run-1",
            "node_id": "worker-1",
            "execution_id": "exec-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "base_snapshot_id": "S0",
            "observed_graph_position": 3,
            "idempotency_key": "key-1",
            "payload": None,
            "complete_node": False,
        },
    )
    accepted = next(event for event in callback if _typed_event_type(event) == "callback_accepted")
    assert CallbackAcceptedPayload.model_validate(accepted.payload).reason == "accepted"
    assert accepted.payload.payload is None

    death_events = _typed_apply(
        events,
        "agent_died",
        {
            "run_id": "run-1",
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": "process_exit",
            "retry_backoff_seconds": 60,
        },
    )
    died = next(event for event in death_events if _typed_event_type(event) == "agent_died")
    retry = next(
        event for event in death_events if _typed_event_type(event) == "runtime_retry_scheduled"
    )
    assert AgentDiedPayload.model_validate(died.payload).reason == "process_exit"
    assert RuntimeRetryScheduledPayload.model_validate(retry.payload).retry_after_seconds == 60


def test_declared_lifecycle_and_callback_events_remain_replayable() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, position=1),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": None,
                "reason": "accepted",
            },
            position=2,
        ),
    ]

    projection = build_projection(build_graph_catalog(), events)

    assert projection["run_state"] == "active"
    assert set(projection["callback_idempotency_events"]) == {"worker-1\0key-1"}


def test_retry_not_before_is_retained_by_every_compact_payload_allowlist() -> None:
    retry_not_before = "2026-07-09T12:01:00+00:00"
    for fields in (
        GRAPH_PROJECTION_PAYLOAD_FIELDS,
        LIGHT_GRAPH_PAYLOAD_FIELDS,
        SUMMARY_REBUILD_PAYLOAD_FIELDS,
        NODE_DETAIL_PAYLOAD_FIELDS,
    ):
        compact = _compact_payload(
            {"node_id": "worker-1", "retry_not_before": retry_not_before}, fields
        )
        assert compact["retry_not_before"] == retry_not_before


def test_compact_runtime_retry_reconstructs_scheduler_backoff() -> None:
    retry_not_before = "2026-07-09T12:01:00+00:00"
    payload = _compact_payload(
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "generation": 1,
            "policy": "retry",
            "reason": "agent_died",
            "retry_not_before": retry_not_before,
        },
        SUMMARY_REBUILD_PAYLOAD_FIELDS,
    )

    projection = build_projection(
        build_graph_catalog(), [_event("runtime_retry_scheduled", payload, position=1)]
    )

    assert projection["retry_not_before_by_node"] == {"worker-1": retry_not_before}


@pytest.mark.asyncio
async def test_sqlite_compact_readers_retain_runtime_retry_not_before() -> None:
    retry_not_before = "2026-07-09T12:01:00+00:00"
    event = _event(
        "runtime_retry_scheduled",
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "generation": 1,
            "policy": "retry",
            "reason": "agent_died",
            "retry_not_before": retry_not_before,
        },
        position=1,
    )
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id("run-1"),
                    version=1,
                    event_type=event.event_type,
                    payload=event.model_dump_json(),
                    timestamp=event.timestamp.isoformat(),
                )
            )
            await session.flush()
            store = GraphEventStore(
                session,
                build_graph_catalog(),
            )
            readers = (
                store.read_run_projection,
                store.read_run_light,
                store.read_run_summary_rebuild,
                store.read_run_node_detail,
            )
            for reader in readers:
                compact_events = await reader("run-1")
                assert compact_events[0].payload["retry_not_before"] == retry_not_before
                assert build_projection(build_graph_catalog(), compact_events)[
                    "retry_not_before_by_node"
                ] == {"worker-1": retry_not_before}
    finally:
        await engine.dispose()


def _active_lease_events() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, position=1),
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "running"},
            position=2,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "S0",
            },
            position=3,
        ),
    ]


def _compact_payload(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: _json_extract_payload_value(field, payload[field])
        for field in fields
        if field in payload
    }


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
