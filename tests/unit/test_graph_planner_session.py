"""Unit coverage for retained planner sessions."""

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    bound_record_ids,
    initial_projection,
    input_binding_for_port,
    lease_by_id,
    node_state,
    planner_session,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_planner_session,
    reduce_event,
)
from tests.unit.graph_test_utils import apply_command, command_context, patch_command_context


def test_successor_inherits_session_id() -> None:
    events = _events_with_active_planner()

    patch = _apply(
        events,
        "submit_patch",
        _patch_payload(events, "planner-0", _region_ops("planner-1")),
        patch_command_context(events, proposed_by_node_id="planner-0", actor_role="planner"),
    )
    events = [*events, *_append(events, patch)]
    lease = _only(
        _apply(
            events,
            "schedule_tick",
            {"base_snapshot_id": "snapshot-1", "max_grants": 10},
        ),
        "lease_granted",
        "planner-1",
    )

    projection = _project(events)
    assert planner_session(projection, "planner-1") == "session-1"
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
            "base_snapshot_id": "snapshot-1",
            "lease_ids": {"planner-0": "lease-planner-0-resume"},
        },
    )

    lease = _only(scheduled, "lease_granted", "planner-0")
    assert lease.payload["session_id"] == "session-1"
    assert lease.payload["generation"] == 2
    released_lease = lease_by_id(
        _project([*events, *_append(events, scheduled)]), "lease-planner-0"
    )
    assert released_lease is not None
    assert released_lease.state == "released"


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
    assert callback[0].event_type == "command_rejected"
    assert "payload [extra_forbidden]" in str(callback[0].payload["reason"])
    assert node_state(projection, "planner-0") == "running"


def test_carryover_binds_as_optional_input() -> None:
    events = _events_with_active_planner(include_carryover=True)
    patch = _apply(
        events,
        "submit_patch",
        {
            **_patch_payload(events, "planner-0", _region_ops("planner-1")),
            "carryover_record_id": "summary-carryover-1",
        },
        patch_command_context(events, proposed_by_node_id="planner-0", actor_role="planner"),
    )
    projection = _project([*events, *_append(events, patch)])

    assert projection_from_checkpoint(projection_to_checkpoint(projection)) == projection
    assert bound_record_ids(projection, "planner-1", "session_carryover") == (
        "summary-carryover-1",
    )
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
        patch_command_context(events, proposed_by_node_id="planner-0", actor_role="planner"),
    )
    without_projection = _project([*events, *_append(events, without_carryover)])
    assert input_binding_for_port(without_projection, "planner-2", "session_carryover") is None
    scheduled = _apply(
        [*events, *_append(events, without_carryover)],
        "schedule_tick",
        {"base_snapshot_id": "snapshot-1", "max_grants": 10},
    )
    assert _only(scheduled, "lease_granted", "planner-2").payload["generation"] == 2


def test_carryover_rejects_unknown_record_without_creating_successor() -> None:
    events = _events_with_active_planner()

    patch = _apply(
        events,
        "submit_patch",
        {
            **_patch_payload(events, "planner-0", _region_ops("planner-1")),
            "carryover_record_id": "unknown-carryover",
        },
        patch_command_context(events, proposed_by_node_id="planner-0", actor_role="planner"),
    )

    assert [event.event_type for event in patch] == ["graph_patch_rejected"]
    assert patch[0].payload["reason"] == "unknown_carryover_record_id:unknown-carryover"


def test_carryover_rejects_unknown_record_without_successor() -> None:
    events = _events_with_active_planner()

    patch = _apply(
        events,
        "submit_patch",
        {
            **_patch_payload(
                events,
                "planner-0",
                [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "summarizer-1",
                            "kind": "summarizer",
                            "state": "planned",
                        },
                    }
                ],
            ),
            "carryover_record_id": "unknown-carryover",
        },
        patch_command_context(events, proposed_by_node_id="planner-0", actor_role="planner"),
    )

    assert [event.event_type for event in patch] == ["graph_patch_rejected"]
    assert patch[0].payload["reason"] == "unknown_carryover_record_id:unknown-carryover"


def test_project_planner_session() -> None:
    events = _events_with_active_planner(include_carryover=True)
    patch = _apply(
        events,
        "submit_patch",
        {
            **_patch_payload(events, "planner-0", _region_ops("planner-1")),
            "carryover_record_id": "summary-carryover-1",
        },
        patch_command_context(events, proposed_by_node_id="planner-0", actor_role="planner"),
    )
    events = [*events, *_append(events, patch)]
    schedule = _apply(
        events,
        "schedule_tick",
        {"base_snapshot_id": "snapshot-1", "max_grants": 10},
    )
    events = [*events, *_append(events, schedule)]

    assert project_planner_session(events) == {
        "session_id": "session-1",
        "state": "attached",
        "generations": [
            {
                "node_id": "planner-0",
                "lease_generation": 1,
                "region_label": None,
                "state": "active",
            },
            {
                "node_id": "planner-1",
                "lease_generation": 2,
                "region_label": None,
                "state": "active",
            },
        ],
        "current_node_id": "planner-1",
        "carryover_record_id": "summary-carryover-1",
    }


def _events_with_active_planner(*, include_carryover: bool = False) -> list[EventEnvelope]:
    events = [
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
    if include_carryover:
        events.append(
            _event(
                "output_record_accepted",
                {
                    "record_id": "summary-carryover-1",
                    "record_kind": "output",
                    "record_type": "analysis_summary",
                    "producer_node_id": "planner-0",
                    "port": "planning_summary",
                    "schema": "AnalysisSummary",
                    "value": {
                        "summary": "Carry this planning context forward.",
                        "source_record_ids": [],
                        "lossy": False,
                        "omitted_details": [],
                    },
                },
            )
        )
    return _with_positions(events)


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
        "patch_id": "patch-1",
        "base_graph_position": max(event.position for event in events),
        "ops": ops,
    }


def _callback_payload(
    node_id: str,
    lease_id: str,
    execution_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    return {
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
    context: Any | None = None,
) -> list[EventEnvelope]:
    return apply_command(
        _project(events),
        events,
        command_type,
        payload,
        context or command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    from tests.unit.graph_test_utils import canonical_event_payload

    return EventEnvelope(
        event_id=f"{event_type}-{payload.get('node_id', payload.get('patch_id', 'event'))}",
        run_id="run-1",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
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
