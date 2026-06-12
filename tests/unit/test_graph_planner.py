"""Unit tests for recursive horizon planner kernel behavior."""

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    project_planner_chain,
    project_run_state,
    reduce_event,
)


def test_planner_lifecycle_states() -> None:
    events = _planner_events()

    accepted = _append(events, _submit_patch(events, "patch-1", _region_ops("successor-1")))
    rejected = _append(
        [*events, *accepted],
        _submit_patch([*events, *accepted], "patch-2", [{"op": "create_gate"}]),
    )

    assert accepted[0].event_type == "graph_patch_accepted"
    assert rejected[0].event_type == "graph_patch_rejected"
    assert _project([*events, *accepted, *rejected])["node_states"]["planner-0"] == "completed"


def test_horizon_patch_creates_region_and_successor() -> None:
    events = _planner_events()
    accepted = _append(events, _submit_patch(events, "patch-1", _region_ops("planner-1")))
    projection = _project([*events, *accepted])

    assert projection["node_kinds"]["worker-1"] == "worker"
    assert projection["node_kinds"]["verifier-1"] == "verifier"
    assert projection["node_kinds"]["planner-1"] == "planner"
    assert "region_summary" not in projection["input_bindings"].get("planner-1", {})

    scheduled = _apply([*events, *accepted], "schedule_tick", {"run_id": "run-1"})
    assert any(
        event.event_type == "node_deferred"
        and event.payload
        == {"node_id": "planner-1", "reason": "missing_required_input:region_summary"}
        for event in scheduled
    )


def test_successor_readiness_via_milestone_records() -> None:
    events = _planner_events()
    events = [*events, *_append(events, _submit_patch(events, "patch-1", _region_ops("planner-1")))]
    events = _drive_region_to_accepted(events)

    projection = _project(events)
    assert projection["input_bindings"]["planner-1"]["region_summary"]["record_ids"] == [
        "summary-1"
    ]
    assert projection["input_bindings"]["planner-1"]["accepted_file_state"]["record_ids"] == [
        "file-state-1"
    ]

    scheduled = _apply(
        events,
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "snapshot-1", "max_grants": 10},
    )
    assert any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "planner-1"
        for event in scheduled
    )


def test_final_planner_no_successor_terminates() -> None:
    events = _planner_events()
    events = [*events, *_append(events, _submit_patch(events, "patch-1", _region_ops(None)))]
    events = _drive_region_to_accepted(events)

    assert project_run_state(events) == "completed"


def test_run_not_complete_with_pending_planner() -> None:
    events = _planner_events()
    events = [*events, *_append(events, _submit_patch(events, "patch-1", _region_ops("planner-1")))]
    events = _drive_region_to_accepted(events)

    assert project_run_state(events) == "active"


def test_lifecycle_completed_does_not_bypass_pending_planner() -> None:
    events = _planner_events()
    events = [*events, *_append(events, _submit_patch(events, "patch-1", _region_ops("planner-1")))]
    events = _drive_region_to_accepted(events)
    completed = _event("run_lifecycle_changed", {"from_state": "active", "to_state": "completed"})
    events = [*events, *_append(events, [completed])]

    assert project_run_state(events) == "active"


def test_generation_budget_rejects_and_gates() -> None:
    events = _planner_events(budget=1, planner_generation=1, planner_id="planner-1")

    rejected = _submit_patch(events, "patch-budget", _region_ops("planner-2", generation=2))

    assert [event.event_type for event in rejected] == [
        "graph_patch_rejected",
        "node_created",
        "node_state_changed",
    ]
    assert rejected[0].payload["reason"] == "planner_generation_budget_exhausted"
    assert rejected[0].payload["budget"] == 1
    assert rejected[0].payload["count"] == 2
    assert rejected[1].payload["kind"] == "gate"
    assert rejected[2].payload["new_state"] == "ready"


def test_parallel_successor_planners_rejected() -> None:
    events = _planner_events()

    rejected = _submit_patch(events, "patch-parallel", _parallel_successor_region_ops())
    projection = _project([*events, *_append(events, rejected)])

    assert [event.event_type for event in rejected] == ["graph_patch_rejected"]
    assert rejected[0].payload["reason"] == "multiple_successor_planners_not_allowed"
    assert "planner-a" not in projection["node_states"]
    assert "planner-b" not in projection["node_states"]
    assert project_planner_chain([*events, *_append(events, rejected)]) == [
        {
            "node_id": "planner-0",
            "generation_index": 0,
            "state": "completed",
            "successor_node_id": None,
        }
    ]


def test_project_planner_chain() -> None:
    events = _planner_events()
    events = [*events, *_append(events, _submit_patch(events, "patch-1", _region_ops("planner-1")))]

    assert project_planner_chain(events) == [
        {
            "node_id": "planner-0",
            "generation_index": 0,
            "state": "completed",
            "successor_node_id": "planner-1",
        },
        {
            "node_id": "planner-1",
            "generation_index": 1,
            "state": "planned",
            "successor_node_id": None,
        },
    ]


def test_patch_acceptance_separate_from_planner_completion() -> None:
    events = _planner_events()

    rejected = _submit_patch(events, "patch-rejected", [{"op": "create_gate"}])
    projection = _project([*events, *_append(events, rejected)])

    assert rejected[0].event_type == "graph_patch_rejected"
    assert projection["node_states"]["planner-0"] == "completed"
    assert "worker-1" not in projection["node_states"]


def _planner_events(
    *,
    budget: int = 8,
    planner_generation: int = 0,
    planner_id: str = "planner-0",
) -> list[EventEnvelope]:
    return _with_positions(
        [
            _event("run_lifecycle_changed", {"to_state": "active"}),
            _event(
                "node_created",
                {
                    "node_id": "root",
                    "kind": "root",
                    "state": "completed",
                    "planner_generation_budget": budget,
                },
            ),
            _event(
                "node_created",
                {
                    "node_id": planner_id,
                    "kind": "planner",
                    "role": "planner",
                    "state": "completed",
                    "generation_index": planner_generation,
                },
            ),
        ]
    )


def _region_ops(successor_id: str | None, *, generation: int = 1) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = [
        {
            "op": "create_node",
            "node": {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "region-1",
                "attempt_number": 1,
                "candidate_id": "candidate-1",
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": "region-1",
                "attempt_number": 1,
                "candidate_id": "candidate-1",
            },
        },
        {
            "op": "create_edge",
            "edge_id": "edge-candidate",
            "from_node_id": "worker-1",
            "from_port": "candidate",
            "to_node_id": "verifier-1",
            "to_port": "candidate_under_test",
        },
    ]
    if successor_id is None:
        return ops
    ops.append(
        {
            "op": "create_node",
            "node": {
                "node_id": successor_id,
                "kind": "planner",
                "role": "planner",
                "state": "planned",
                "generation_index": generation,
                "inputs": [
                    {"port": "region_summary", "direction": "input", "required": True},
                    {"port": "accepted_file_state", "direction": "input", "required": True},
                    {"port": "outstanding_failures", "direction": "input", "required": False},
                ],
            },
        }
    )
    ops.extend(
        [
            _selector_edge(
                "edge-summary",
                "verifier-1",
                "region_summary",
                successor_id,
                "region_summary",
            ),
            _selector_edge(
                "edge-file-state",
                "worker-1",
                "file_state",
                successor_id,
                "accepted_file_state",
            ),
        ]
    )
    return ops


def _parallel_successor_region_ops() -> list[dict[str, Any]]:
    ops = _region_ops("planner-a")
    ops.append(
        {
            "op": "create_node",
            "node": {
                "node_id": "planner-b",
                "kind": "planner",
                "role": "planner",
                "state": "planned",
                "generation_index": 1,
                "inputs": [
                    {"port": "region_summary", "direction": "input", "required": True},
                    {"port": "accepted_file_state", "direction": "input", "required": True},
                    {"port": "outstanding_failures", "direction": "input", "required": False},
                ],
            },
        }
    )
    ops.extend(
        [
            _selector_edge(
                "edge-summary-b",
                "verifier-1",
                "region_summary",
                "planner-b",
                "region_summary",
            ),
            _selector_edge(
                "edge-file-state-b",
                "worker-1",
                "file_state",
                "planner-b",
                "accepted_file_state",
            ),
        ]
    )
    return ops


def _selector_edge(
    edge_id: str,
    from_node_id: str,
    from_port: str,
    to_node_id: str,
    to_port: str,
) -> dict[str, Any]:
    return {
        "op": "create_edge",
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "accepted_record_selector": {"record_kinds": [to_port]},
    }


def _drive_region_to_accepted(events: list[EventEnvelope]) -> list[EventEnvelope]:
    worker_events = [
        _event("node_state_changed", {"node_id": "worker-1", "new_state": "running"}),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-worker",
                "generation": 1,
                "execution_id": "exec-worker",
                "base_snapshot_id": "snapshot-0",
            },
        ),
    ]
    events = [*events, *_append(events, worker_events)]
    worker_callback = _apply(
        events,
        "submit_callback",
        _callback_payload(
            "worker-1",
            "lease-worker",
            "exec-worker",
            [
                {
                    "record_id": "candidate-1",
                    "record_kind": "output",
                    "producer_node_id": "worker-1",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": "candidate-1",
                    "task_region_id": "region-1",
                    "attempt_number": 1,
                    "value": {"summary": "done"},
                },
                {
                    "record_id": "file-state-1",
                    "record_kind": "file_state",
                    "producer_node_id": "worker-1",
                    "snapshot_id": "snapshot-1",
                    "base_snapshot_id": "snapshot-0",
                    "port": "file_state",
                },
            ],
        ),
    )
    events = [*events, *_append(events, worker_callback)]

    verifier_events = [
        _event("node_state_changed", {"node_id": "verifier-1", "new_state": "running"}),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-1",
                "lease_id": "lease-verifier",
                "generation": 1,
                "execution_id": "exec-verifier",
                "base_snapshot_id": "snapshot-1",
            },
        ),
    ]
    events = [*events, *_append(events, verifier_events)]
    verifier_callback = _apply(
        events,
        "submit_callback",
        _callback_payload(
            "verifier-1",
            "lease-verifier",
            "exec-verifier",
            [
                {
                    "record_id": "verification-1",
                    "record_kind": "verification",
                    "candidate_id": "candidate-1",
                    "verdict": "passed",
                },
                {
                    "record_id": "summary-1",
                    "record_kind": "output",
                    "producer_node_id": "verifier-1",
                    "port": "region_summary",
                    "schema": "RegionSummary",
                    "value": {"milestone_kind": "region_summary"},
                },
            ],
            base_snapshot_id="snapshot-1",
        ),
    )
    return [*events, *_append(events, verifier_callback)]


def _submit_patch(
    events: list[EventEnvelope],
    patch_id: str,
    ops: list[dict[str, Any]],
) -> list[EventEnvelope]:
    planner_id = next(
        event.payload["node_id"]
        for event in events
        if event.event_type == "node_created" and event.payload.get("role") == "planner"
    )
    return _apply(
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": patch_id,
            "proposed_by_node_id": planner_id,
            "base_graph_position": max(event.position for event in events),
            "actor_role": "planner",
            "ops": ops,
        },
    )


def _callback_payload(
    node_id: str,
    lease_id: str,
    execution_id: str,
    output_records: list[dict[str, Any]],
    *,
    base_snapshot_id: str = "snapshot-0",
) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "node_id": node_id,
        "execution_id": execution_id,
        "lease_id": lease_id,
        "lease_generation": 1,
        "base_snapshot_id": base_snapshot_id,
        "observed_graph_position": 1,
        "idempotency_key": f"callback-{node_id}",
        "payload": {"payload_hash": f"hash-{node_id}", "output_records": output_records},
    }


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
