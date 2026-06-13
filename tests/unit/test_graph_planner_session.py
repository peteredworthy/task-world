"""Unit coverage for retained planner sessions."""

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    project_planner_session,
    reduce_event,
)


def test_successor_inherits_session_id() -> None:
    events = _events_with_active_planner()

    patch = _apply(
        events,
        "submit_patch",
        _patch_payload(events, "planner-0", _region_ops("planner-1")),
    )
    events = [*events, *_append(events, patch)]
    lease = _only(
        _apply(
            events,
            "schedule_tick",
            {"run_id": "run-1", "base_snapshot_id": "snapshot-1", "max_grants": 10},
        ),
        "lease_granted",
        "planner-1",
    )

    projection = _project(events)
    assert projection["planner_sessions"]["planner-1"] == "session-1"
    assert lease.payload["session_id"] == "session-1"
    assert lease.payload["generation"] == 2


def test_resume_emits_new_generation_same_session() -> None:
    events = _events_with_active_planner()
    callback = _apply(
        events,
        "submit_callback",
        _callback_payload("planner-0", "lease-planner-0", "exec-planner-0", 1),
    )
    events = [*events, *_append(events, callback)]
    requeued = _event("node_state_changed", {"node_id": "planner-0", "new_state": "planned"})
    events = [*events, *_append(events, [requeued])]

    scheduled = _apply(
        events,
        "schedule_tick",
        {
            "run_id": "run-1",
            "base_snapshot_id": "snapshot-1",
            "lease_ids": {"planner-0": "lease-planner-0-resume"},
        },
    )

    lease = _only(scheduled, "lease_granted", "planner-0")
    assert lease.payload["session_id"] == "session-1"
    assert lease.payload["generation"] == 2
    assert (
        _project([*events, *_append(events, scheduled)])["leases"]["lease-planner-0"]["state"]
        == "released"
    )


def test_session_does_not_grant_authority() -> None:
    events = _events_with_active_planner()
    callback = _apply(
        events,
        "submit_callback",
        {
            **_callback_payload("planner-0", "lease-planner-0", "exec-planner-0", 0),
            "lease_generation": 0,
            "session_id": "session-1",
        },
    )

    projection = _project([*events, *_append(events, callback)])
    assert callback[0].event_type == "callback_rejected_stale"
    assert projection["node_states"]["planner-0"] == "running"


def test_carryover_binds_as_optional_input() -> None:
    events = _events_with_active_planner()
    patch = _apply(
        events,
        "submit_patch",
        {
            **_patch_payload(events, "planner-0", _region_ops("planner-1")),
            "carryover_summary": "summary-carryover-1",
        },
    )
    projection = _project([*events, *_append(events, patch)])

    assert projection["input_bindings"]["planner-1"]["session_carryover"]["record_ids"] == [
        "summary-carryover-1"
    ]
    created = _only(patch, "node_created", "planner-1")
    carryover_port = next(
        raw_port
        for raw_port in created.payload["inputs"]
        if raw_port["port"] == "session_carryover"
    )
    assert carryover_port["required"] is False

    without_carryover = _apply(
        events,
        "submit_patch",
        _patch_payload(events, "planner-0", _region_ops("planner-2")),
    )
    without_projection = _project([*events, *_append(events, without_carryover)])
    assert "session_carryover" not in without_projection["input_bindings"].get("planner-2", {})
    scheduled = _apply(
        [*events, *_append(events, without_carryover)],
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "snapshot-1", "max_grants": 10},
    )
    assert _only(scheduled, "lease_granted", "planner-2").payload["generation"] == 2


def test_project_planner_session() -> None:
    events = _events_with_active_planner()
    patch = _apply(
        events,
        "submit_patch",
        {
            **_patch_payload(events, "planner-0", _region_ops("planner-1")),
            "carryover_summary": "summary-carryover-1",
        },
    )
    events = [*events, *_append(events, patch)]
    schedule = _apply(
        events,
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "snapshot-1", "max_grants": 10},
    )
    events = [*events, *_append(events, schedule)]

    assert project_planner_session(events) == {
        "session_id": "session-1",
        "state": "attached",
        "generations": [
            {"node_id": "planner-0", "lease_generation": 1, "state": "active"},
            {"node_id": "planner-1", "lease_generation": 2, "state": "active"},
        ],
        "current_node_id": "planner-1",
        "carryover_record_id": "summary-carryover-1",
    }


def _events_with_active_planner() -> list[EventEnvelope]:
    return _with_positions(
        [
            _event("run_lifecycle_changed", {"to_state": "active"}),
            _event("node_created", {"node_id": "root", "kind": "root", "state": "completed"}),
            _event(
                "node_created",
                {
                    "node_id": "planner-0",
                    "kind": "planner",
                    "role": "planner",
                    "state": "running",
                    "generation_index": 0,
                    "session_id": "session-1",
                },
            ),
            _event(
                "lease_granted",
                {
                    "node_id": "planner-0",
                    "lease_id": "lease-planner-0",
                    "generation": 1,
                    "execution_id": "exec-planner-0",
                    "base_snapshot_id": "snapshot-0",
                    "session_id": "session-1",
                },
            ),
            _event(
                "session_state_changed",
                {
                    "session_id": "session-1",
                    "state": "attached",
                    "node_id": "planner-0",
                    "lease_generation": 1,
                    "carryover_record_id": None,
                },
            ),
        ]
    )


def _region_ops(successor_id: str) -> list[dict[str, Any]]:
    return [
        {
            "op": "create_node",
            "node": {
                "node_id": successor_id,
                "kind": "planner",
                "role": "planner",
                "state": "planned",
                "generation_index": 1,
                "inputs": [
                    {"port": "region_summary", "direction": "input", "required": False},
                    {"port": "accepted_file_state", "direction": "input", "required": False},
                ],
            },
        }
    ]


def _patch_payload(
    events: list[EventEnvelope],
    planner_id: str,
    ops: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "patch_id": "patch-1",
        "proposed_by_node_id": planner_id,
        "base_graph_position": max(event.position for event in events),
        "actor_role": "planner",
        "ops": ops,
    }


def _callback_payload(
    node_id: str,
    lease_id: str,
    execution_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "node_id": node_id,
        "execution_id": execution_id,
        "lease_id": lease_id,
        "lease_generation": lease_generation,
        "base_snapshot_id": "snapshot-0",
        "observed_graph_position": 1,
        "idempotency_key": f"callback-{node_id}-{lease_generation}",
        "payload": {"payload_hash": f"hash-{node_id}-{lease_generation}"},
    }


def _only(
    events: list[EventEnvelope],
    event_type: str,
    node_id: str,
) -> EventEnvelope:
    return next(
        event
        for event in events
        if event.event_type == event_type and event.payload.get("node_id") == node_id
    )


def _apply(
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
) -> list[EventEnvelope]:
    return apply_command(
        _project(events),
        events,
        command_type,
        payload,
        FakeClock(),
        SequentialIdGenerator(),
    )


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{payload.get('node_id', payload.get('patch_id', 'event'))}",
        run_id="run-1",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def _with_positions(events: list[EventEnvelope]) -> list[EventEnvelope]:
    return [
        event.model_copy(update={"position": index}) for index, event in enumerate(events, start=1)
    ]


def _append(
    existing_events: list[EventEnvelope],
    new_events: list[EventEnvelope],
) -> list[EventEnvelope]:
    position = max((event.position for event in existing_events), default=0)
    return [
        event.model_copy(update={"position": position + offset})
        for offset, event in enumerate(new_events, start=1)
    ]
