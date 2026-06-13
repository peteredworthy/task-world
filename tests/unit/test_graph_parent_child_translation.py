"""Parent/child oversight translation into planner-chain graph seeds."""

from typing import Any

from orchestrator.config.models import RoutineConfig, StepConfig
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    compile_routine,
    initial_projection,
    project_planner_chain,
    reduce_event,
)


def test_parent_child_routine_compiles_to_planner_chain() -> None:
    events = _compile(_parent_child_routine())
    projection = _project(events)
    planner = _node_event(events, "planner-parent")

    assert projection["node_kinds"]["planner-parent"] == "planner"
    assert planner.payload["planner_chain"] == {
        "source": "legacy_parent_child",
        "regions": [
            {
                "generation_index": 0,
                "region_label": "child-one",
                "child_routine": "child-one",
            },
            {
                "generation_index": 1,
                "region_label": "Child Two",
                "child_routine": "child-two",
            },
        ],
    }
    assert planner.payload["region_label"] == "child-one"
    assert all(event.event_type != "run_lifecycle_changed" for event in events)
    assert not any(_contains_legacy_child_artifact(event.payload) for event in events)


def test_child_order_is_chain_order() -> None:
    events = _compile_active_parent_child()
    events = [
        *events,
        *_append(
            events,
            _submit_patch(
                events, "patch-child-one", "planner-parent", _region_ops("one", "planner-child-two")
            ),
        ),
    ]

    blocked = _apply(
        events,
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "snapshot-0", "max_grants": 10},
    )
    assert not any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "planner-child-two"
        for event in blocked
    )
    assert any(
        event.event_type == "node_deferred"
        and event.payload
        == {
            "node_id": "planner-child-two",
            "reason": "missing_required_input:region_summary",
        }
        for event in blocked
    )

    events = _drive_region_to_accepted(events, "one")
    scheduled = _apply(
        events,
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "snapshot-one", "max_grants": 10},
    )

    assert any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "planner-child-two"
        for event in scheduled
    )


def test_region_label_names_child_routine() -> None:
    events = _compile_active_parent_child()
    events = [
        *events,
        *_append(
            events,
            _submit_patch(
                events, "patch-child-one", "planner-parent", _region_ops("one", "planner-child-two")
            ),
        ),
    ]

    assert project_planner_chain(events) == [
        {
            "node_id": "planner-parent",
            "generation_index": 0,
            "session_id": None,
            "lease_generation": None,
            "region_label": "child-one",
            "state": "planned",
            "successor_node_id": "planner-child-two",
        },
        {
            "node_id": "planner-child-two",
            "generation_index": 1,
            "session_id": None,
            "lease_generation": None,
            "region_label": "Child Two",
            "state": "planned",
            "successor_node_id": None,
        },
    ]


def test_non_parent_routine_compiles_unchanged() -> None:
    routine = RoutineConfig(
        id="plain-planner",
        name="Plain Planner",
        steps=[StepConfig(id="Plan", kind="planner", title="Plan")],
    )

    implicit_default = [event.model_dump(mode="json") for event in _compile(routine)]
    explicit_empty = [
        event.model_dump(mode="json")
        for event in _compile(
            RoutineConfig(
                id="plain-planner",
                name="Plain Planner",
                steps=[StepConfig(id="Plan", kind="planner", title="Plan", child_routines=[])],
            )
        )
    ]

    assert explicit_empty == implicit_default
    planner = _node_event(_compile(routine), "planner-plan")
    assert "planner_chain" not in planner.payload
    assert "region_label" not in planner.payload


def _parent_child_routine() -> RoutineConfig:
    return RoutineConfig(
        id="parent-child",
        name="Parent Child",
        steps=[
            StepConfig(
                id="Parent",
                kind="planner",
                title="Parent",
                child_routines=[
                    {"routine": "child-one"},
                    {"routine": "child-two", "label": "Child Two"},
                ],
            )
        ],
    )


def _compile(routine: RoutineConfig) -> list[EventEnvelope]:
    return _with_positions(
        compile_routine(routine, FakeClock(), SequentialIdGenerator(), run_id="run-1")
    )


def _compile_active_parent_child() -> list[EventEnvelope]:
    events = _compile(_parent_child_routine())
    return [
        *_with_positions([_event("run_lifecycle_changed", {"to_state": "active"})]),
        *[event.model_copy(update={"position": event.position + 1}) for event in events],
    ]


def _region_ops(prefix: str, successor_id: str | None) -> list[dict[str, Any]]:
    worker_id = f"worker-{prefix}"
    verifier_id = f"verifier-{prefix}"
    candidate_id = f"candidate-{prefix}"
    ops: list[dict[str, Any]] = [
        {
            "op": "create_node",
            "node": {
                "node_id": worker_id,
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": f"region-{prefix}",
                "attempt_number": 1,
                "candidate_id": candidate_id,
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": verifier_id,
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": f"region-{prefix}",
                "attempt_number": 1,
                "candidate_id": candidate_id,
            },
        },
        {
            "op": "create_edge",
            "edge_id": f"edge-candidate-{prefix}",
            "from_node_id": worker_id,
            "from_port": "candidate",
            "to_node_id": verifier_id,
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
                "generation_index": 1,
                "inputs": [
                    {"port": "region_summary", "direction": "input", "required": True},
                    {"port": "accepted_file_state", "direction": "input", "required": True},
                ],
            },
        }
    )
    ops.extend(
        [
            _selector_edge(
                f"edge-summary-{prefix}",
                verifier_id,
                "region_summary",
                successor_id,
                "region_summary",
            ),
            _selector_edge(
                f"edge-file-{prefix}",
                worker_id,
                "file_state",
                successor_id,
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


def _drive_region_to_accepted(events: list[EventEnvelope], prefix: str) -> list[EventEnvelope]:
    worker_id = f"worker-{prefix}"
    verifier_id = f"verifier-{prefix}"
    worker_events = [
        _event("node_state_changed", {"node_id": worker_id, "new_state": "running"}),
        _event(
            "lease_granted",
            {
                "node_id": worker_id,
                "lease_id": f"lease-{worker_id}",
                "generation": 1,
                "execution_id": f"exec-{worker_id}",
                "base_snapshot_id": "snapshot-0",
            },
        ),
    ]
    events = [*events, *_append(events, worker_events)]
    events = [
        *events,
        *_append(
            events,
            _apply(
                events,
                "submit_callback",
                _callback_payload(
                    worker_id,
                    f"lease-{worker_id}",
                    f"exec-{worker_id}",
                    [
                        {
                            "record_id": f"candidate-{prefix}",
                            "record_kind": "output",
                            "producer_node_id": worker_id,
                            "port": "candidate",
                            "schema": "ImplementationCandidate",
                            "candidate_id": f"candidate-{prefix}",
                            "task_region_id": f"region-{prefix}",
                            "attempt_number": 1,
                            "value": {"summary": "done"},
                        },
                        {
                            "record_id": f"file-state-{prefix}",
                            "record_kind": "file_state",
                            "producer_node_id": worker_id,
                            "snapshot_id": f"snapshot-{prefix}",
                            "base_snapshot_id": "snapshot-0",
                            "port": "file_state",
                        },
                    ],
                ),
            ),
        ),
    ]
    verifier_events = [
        _event("node_state_changed", {"node_id": verifier_id, "new_state": "running"}),
        _event(
            "lease_granted",
            {
                "node_id": verifier_id,
                "lease_id": f"lease-{verifier_id}",
                "generation": 1,
                "execution_id": f"exec-{verifier_id}",
                "base_snapshot_id": f"snapshot-{prefix}",
            },
        ),
    ]
    events = [*events, *_append(events, verifier_events)]
    return [
        *events,
        *_append(
            events,
            _apply(
                events,
                "submit_callback",
                _callback_payload(
                    verifier_id,
                    f"lease-{verifier_id}",
                    f"exec-{verifier_id}",
                    [
                        {
                            "record_id": f"verification-{prefix}",
                            "record_kind": "verification",
                            "candidate_id": f"candidate-{prefix}",
                            "verdict": "passed",
                        },
                        {
                            "record_id": f"summary-{prefix}",
                            "record_kind": "output",
                            "producer_node_id": verifier_id,
                            "port": "region_summary",
                            "schema": "RegionSummary",
                            "value": {"milestone_kind": "region_summary"},
                        },
                    ],
                    base_snapshot_id=f"snapshot-{prefix}",
                ),
            ),
        ),
    ]


def _submit_patch(
    events: list[EventEnvelope],
    patch_id: str,
    planner_id: str,
    ops: list[dict[str, Any]],
) -> list[EventEnvelope]:
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
        "observed_graph_position": max(1, len(output_records)),
        "idempotency_key": f"callback-{node_id}",
        "payload": {"payload_hash": f"hash-{node_id}", "output_records": output_records},
    }


def _contains_legacy_child_artifact(payload: dict[str, Any]) -> bool:
    legacy_terms = {
        "child_run_id",
        "parent_run_id",
        "worktree_path",
        "child_worktree_path",
        "merge_step",
        "merge_commit",
    }
    return any(term in payload for term in legacy_terms) or payload.get("kind") == "merge"


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


def _node_event(events: list[EventEnvelope], node_id: str) -> EventEnvelope:
    return next(
        event
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == node_id
    )


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
