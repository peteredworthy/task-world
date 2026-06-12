"""Unit tests for pure routine graph compilation."""

from typing import Any

from orchestrator.config.models import (
    AutoVerifyConfig,
    AutoVerifyItemConfig,
    ContextSource,
    FanOutConfig,
    GateConfig,
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
    VerifierConfig,
)
from orchestrator.config.enums import GateType
from orchestrator.graph import (
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    compile_routine,
    initial_projection,
    reduce_event,
)


def test_routine_maps_to_root_and_routine_snapshot_record_node() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert projection["node_kinds"]["root"] == "root"
    assert projection["node_kinds"]["routine-snapshot"] == "artifact"
    snapshot_event = _node_event(events, "routine-snapshot")
    assert snapshot_event.payload["role"] == "routine_snapshot"
    assert snapshot_event.payload["snapshot"]["routine_id"] == "minimal"
    assert len(snapshot_event.payload["snapshot"]["content_hash"]) == 64


def test_routine_snapshot_content_hash_is_deterministic_and_changes_with_content() -> None:
    first = _node_event(_compile(_minimal_routine()), "routine-snapshot").payload["snapshot"]
    second = _node_event(_compile(_minimal_routine()), "routine-snapshot").payload["snapshot"]
    changed_routine = _routine_with_task(TaskConfig(id="T-01", title="Changed title"))
    changed = _node_event(_compile(changed_routine), "routine-snapshot").payload["snapshot"]

    assert first["content_hash"] == second["content_hash"]
    assert first["content_hash"] != changed["content_hash"]


def test_step_maps_to_grouping_metadata_and_sequential_task_region_edges() -> None:
    routine = RoutineConfig(
        id="two-step",
        name="Two Step",
        steps=[
            StepConfig(
                id="S-01",
                title="First",
                tasks=[TaskConfig(id="T-01", title="First task")],
            ),
            StepConfig(
                id="S-02",
                title="Second",
                tasks=[TaskConfig(id="T-02", title="Second task")],
            ),
        ],
    )

    events = _compile(routine)
    projection = _project(events)

    assert "step-S-01" not in projection["node_kinds"]
    assert "step-S-02" not in projection["node_kinds"]
    assert projection["node_task_regions"]["worker-s-01-t-01"] == "S-01/T-01"
    assert projection["node_task_regions"]["worker-s-02-t-02"] == "S-02/T-02"
    assert any(
        edge["from_node_id"] == "worker-s-01-t-01"
        and edge["to_node_id"] == "worker-s-02-t-02"
        and edge["to_port"] == "prior_step_completion"
        and edge["dependency_type"] == "state_dependency"
        for edge in projection["edges"].values()
    )


def test_task_maps_to_task_region_projection_and_worker_node() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert projection["node_kinds"]["worker-s-01-t-01"] == "worker"
    assert projection["node_task_regions"]["worker-s-01-t-01"] == "S-01/T-01"
    assert projection["node_attempts"]["worker-s-01-t-01"] == 1
    assert projection["node_candidates"]["worker-s-01-t-01"] == "candidate-s-01-t-01-1"


def test_requirements_map_to_requirement_nodes_and_bound_edges_to_worker_and_verifier() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            requirements=[RequirementConfig(id="R-01", desc="Must be done")],
            verifier=VerifierConfig(),
        )
    )

    events = _compile(routine)
    projection = _project(events)

    requirement_id = "requirement-s-01-t-01-r-01"
    assert projection["node_kinds"][requirement_id] == "requirement"
    assert projection["node_kinds"]["verifier-s-01-t-01"] == "verifier"
    requirement_edges = [
        edge for edge in projection["edges"].values() if edge["from_node_id"] == requirement_id
    ]
    assert {edge["to_node_id"] for edge in requirement_edges} == {
        "worker-s-01-t-01",
        "verifier-s-01-t-01",
    }
    for edge in requirement_edges:
        assert edge["to_port"] in projection["input_bindings"][edge["to_node_id"]]


def test_auto_verify_maps_to_one_check_node_per_item() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            auto_verify=AutoVerifyConfig(
                items=[
                    AutoVerifyItemConfig(id="unit", cmd="uv run pytest tests/unit -q"),
                    AutoVerifyItemConfig(id="lint", cmd="uv run ruff check ."),
                ],
                tail_lines=7,
            ),
        )
    )

    events = _compile(routine)
    projection = _project(events)

    check_ids = _node_ids_by_kind(projection, "check")
    assert check_ids == [
        "check-s-01-t-01-auto_verify-lint",
        "check-s-01-t-01-auto_verify-unit",
    ]
    for check_id in check_ids:
        assert projection["node_command_definitions"][check_id]["tail_lines"] == 7
        assert any(
            edge["from_node_id"] == "worker-s-01-t-01"
            and edge["to_node_id"] == check_id
            and edge["to_port"] == "candidate_under_test"
            for edge in projection["edges"].values()
        )


def test_verifier_rubric_maps_to_verifier_node() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            verifier={"rubric": [{"id": "rubric-1", "text": "Is it correct?"}]},
        )
    )

    events = _compile(routine)
    projection = _project(events)

    assert projection["node_kinds"]["verifier-s-01-t-01"] == "verifier"
    assert any(
        edge["from_node_id"] == "worker-s-01-t-01"
        and edge["to_node_id"] == "verifier-s-01-t-01"
        and edge["to_port"] == "candidate_under_test"
        for edge in projection["edges"].values()
    )


def test_verifier_and_checks_get_optional_file_state_consumption_edge() -> None:
    """§20.4: downstream consumers bind to the worker's accepted file-state record."""
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            verifier={"rubric": [{"id": "rubric-1", "text": "Is it correct?"}]},
            auto_verify={"items": [{"id": "check-1", "cmd": "true"}]},
        )
    )

    events = _compile(routine)
    projection = _project(events)

    file_state_edges = [
        edge
        for edge in projection["edges"].values()
        if edge["from_node_id"] == "worker-s-01-t-01"
        and edge["from_port"] == "file_state"
        and edge["to_port"] == "file_state"
    ]
    consumers = {edge["to_node_id"] for edge in file_state_edges}
    assert "verifier-s-01-t-01" in consumers
    assert any(consumer.startswith("check-") for consumer in consumers)
    assert all(edge["required"] is False for edge in file_state_edges)


def test_human_approval_gate_maps_to_gate_node_only_when_configured() -> None:
    routine = RoutineConfig(
        id="gate-routine",
        name="Gate Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Gated step",
                gate=GateConfig(
                    type=GateType.HUMAN_APPROVAL,
                    approval_prompt="Approve?",
                ),
                tasks=[TaskConfig(id="T-01", title="Task")],
            )
        ],
    )

    events = _compile(routine)
    projection = _project(events)

    assert projection["node_kinds"]["gate-s-01"] == "gate"
    assert projection["configured_gates"]["S-01/T-01"]["gate-s-01"] is True
    gate_edges = [
        edge for edge in projection["edges"].values() if edge["from_node_id"] == "gate-s-01"
    ]
    assert len(gate_edges) == 1
    assert gate_edges[0]["to_node_id"] == "worker-s-01-t-01"
    assert "approval" in projection["input_bindings"]["worker-s-01-t-01"]

    no_gate_projection = _project(_compile(_minimal_routine()))
    assert _node_ids_by_kind(no_gate_projection, "gate") == []
    assert "approval" not in no_gate_projection["input_bindings"].get("worker-s-01-t-01", {})


def test_context_dependency_maps_to_bound_input_edge() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            context_from=[ContextSource.model_validate({"artifact": "docs/plan.md", "as": "plan"})],
        )
    )

    events = _compile(routine)
    projection = _project(events)

    context_id = "context-s-01-t-01-0-plan"
    assert projection["node_kinds"][context_id] == "artifact"
    assert any(
        edge["from_node_id"] == context_id
        and edge["to_node_id"] == "worker-s-01-t-01"
        and edge["to_port"] == "context_0"
        for edge in projection["edges"].values()
    )
    assert "context_0" in projection["input_bindings"]["worker-s-01-t-01"]


def test_fan_out_maps_to_reader_template_and_distinct_synthesis_join_template() -> None:
    """Fan-out glob expansion is runtime work; compile emits template reader and join nodes."""
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Fan out",
            fan_out=FanOutConfig(
                input_glob="docs/*.md",
                output_pattern="out/{name}.md",
                per_item_prompt="Summarize",
            ),
        )
    )

    events = _compile(routine)
    projection = _project(events)

    assert projection["node_kinds"]["fanout-reader-s-01-t-01"] == "planner"
    assert _node_event(events, "fanout-reader-s-01-t-01").payload["role"] == "fan_out_reader"
    assert projection["node_kinds"]["fanout-join-s-01-t-01"] == "planner"
    assert _node_event(events, "fanout-join-s-01-t-01").payload["role"] == "fan_out_join"
    assert projection["node_kinds"]["worker-s-01-t-01"] == "worker"
    assert _node_event(events, "worker-s-01-t-01").payload["role"] == "builder"
    assert any(
        edge["from_node_id"] == "fanout-reader-s-01-t-01"
        and edge["to_node_id"] == "fanout-join-s-01-t-01"
        and edge["to_port"] == "reader_outputs"
        for edge in projection["edges"].values()
    )
    assert any(
        edge["from_node_id"] == "fanout-join-s-01-t-01"
        and edge["to_node_id"] == "worker-s-01-t-01"
        and edge["to_port"] == "fan_out_inputs"
        for edge in projection["edges"].values()
    )


def test_minimal_single_task_graph_has_exact_minimum_executable_node_set_and_schedules() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert projection["node_kinds"] == {
        "root": "root",
        "routine-snapshot": "artifact",
        "worker-s-01-t-01": "worker",
    }
    assert _node_ids_by_kind(projection, "verifier") == []
    assert _node_ids_by_kind(projection, "check") == []
    assert _node_ids_by_kind(projection, "gate") == []

    active_events = _with_lifecycle_started(events)
    schedule_events = _apply(active_events, "schedule_tick", {"run_id": "run-1", "max_grants": 1})

    assert "lease_granted" in [event.event_type for event in schedule_events]
    assert schedule_events_by_type(schedule_events, "lease_granted")[0].payload["node_id"] == (
        "worker-s-01-t-01"
    )


def test_compile_planner_step_seeds_chain_head() -> None:
    routine = RoutineConfig(
        id="planner-routine",
        name="Planner Routine",
        planner_generation_budget=3,
        steps=[StepConfig(id="Plan", kind="planner", title="Plan horizons")],
    )

    events = _compile(routine)
    projection = _project(events)

    assert projection["planner_generation_budget"] == 3
    assert projection["node_kinds"]["planner-plan"] == "planner"
    assert _node_event(events, "planner-plan").payload["role"] == "planner"
    assert _node_event(events, "planner-plan").payload["generation_index"] == 0
    assert projection["input_bindings"]["planner-plan"]["routine_snapshot"]["record_ids"] == [
        "routine-snapshot"
    ]


def test_compile_without_planner_unchanged() -> None:
    events = _compile(_minimal_routine())

    assert "planner_generation_budget" not in _node_event(events, "root").payload
    assert [event.model_dump(mode="json") for event in events] == [
        event.model_dump(mode="json") for event in _compile(_minimal_routine())
    ]


def test_compiler_is_deterministic_for_same_clock_and_id_sequence() -> None:
    first = _compile(_minimal_routine())
    second = _compile(_minimal_routine())

    assert first == second


def test_events_replay_cleanly_into_expected_projection() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert len(projection["node_kinds"]) == 3
    assert len(projection["edges"]) == 1
    assert projection["input_bindings"]["worker-s-01-t-01"]["routine_snapshot"]["record_ids"] == [
        "routine-snapshot"
    ]


def test_compiled_projection_schedules_first_worker_and_blocks_downstream_step() -> None:
    routine = RoutineConfig(
        id="two-step",
        name="Two Step",
        steps=[
            StepConfig(
                id="S-01",
                title="First",
                tasks=[TaskConfig(id="T-01", title="First task")],
            ),
            StepConfig(
                id="S-02",
                title="Second",
                tasks=[TaskConfig(id="T-02", title="Second task")],
            ),
        ],
    )
    active_events = _with_lifecycle_started(_compile(routine))

    schedule_events = _apply(active_events, "schedule_tick", {"run_id": "run-1", "max_grants": 10})

    lease_grants = schedule_events_by_type(schedule_events, "lease_granted")
    assert [event.payload["node_id"] for event in lease_grants] == ["worker-s-01-t-01"]
    deferred = schedule_events_by_type(schedule_events, "node_deferred")
    assert any(
        event.payload["node_id"] == "worker-s-02-t-02"
        and event.payload["reason"] == "upstream_pending:worker-s-01-t-01"
        for event in deferred
    )


def test_two_step_routine_worker_completion_unblocks_next_step_worker() -> None:
    events = _with_positions(_with_lifecycle_started(_compile(_two_step_routine())))

    first_tick = _append(
        events,
        _apply(events, "schedule_tick", {"run_id": "run-1", "max_grants": 10}),
    )
    first_lease = schedule_events_by_type(first_tick, "lease_granted")[0]
    assert first_lease.payload["node_id"] == "worker-s-01-t-01"
    events = [*events, *first_tick]
    started = _append(
        events,
        _apply(events, "acknowledge_start", _start_payload(first_lease)),
    )
    events = [*events, *started]

    completed = _append(
        events,
        _apply(events, "submit_callback", _callback_payload(first_lease)),
    )
    assert [event.event_type for event in completed][-2:] == [
        "node_state_changed",
        "lease_released",
    ]
    events = [*events, *completed]

    second_tick = _apply(events, "schedule_tick", {"run_id": "run-1", "max_grants": 10})
    second_grants = schedule_events_by_type(second_tick, "lease_granted")
    assert [event.payload["node_id"] for event in second_grants] == ["worker-s-02-t-02"]


def test_two_step_routine_worker_failure_blocks_next_step_worker() -> None:
    events = _with_positions(_with_lifecycle_started(_compile(_two_step_routine())))
    first_tick = _append(
        events,
        _apply(events, "schedule_tick", {"run_id": "run-1", "max_grants": 10}),
    )
    first_lease = schedule_events_by_type(first_tick, "lease_granted")[0]
    events = [*events, *first_tick]
    started = _append(
        events,
        _apply(events, "acknowledge_start", _start_payload(first_lease)),
    )
    events = [*events, *started]
    failed = _append(
        events,
        _apply(events, "submit_callback", _callback_payload(first_lease, new_state="failed")),
    )
    events = [*events, *failed]

    second_tick = _apply(events, "schedule_tick", {"run_id": "run-1", "max_grants": 10})

    assert schedule_events_by_type(second_tick, "lease_granted") == []
    assert any(
        event.payload["node_id"] == "worker-s-02-t-02"
        and event.payload["reason"] == "upstream_failed:worker-s-01-t-01"
        for event in schedule_events_by_type(second_tick, "node_deferred")
    )


def _minimal_routine() -> RoutineConfig:
    return _routine_with_task(TaskConfig(id="T-01", title="Task"))


def _two_step_routine() -> RoutineConfig:
    return RoutineConfig(
        id="two-step",
        name="Two Step",
        steps=[
            StepConfig(
                id="S-01",
                title="First",
                tasks=[TaskConfig(id="T-01", title="First task")],
            ),
            StepConfig(
                id="S-02",
                title="Second",
                tasks=[TaskConfig(id="T-02", title="Second task")],
            ),
        ],
    )


def _routine_with_task(task: TaskConfig) -> RoutineConfig:
    return RoutineConfig(
        id="minimal",
        name="Minimal",
        steps=[StepConfig(id="S-01", title="Step", tasks=[task])],
    )


def _compile(routine: RoutineConfig) -> list[EventEnvelope]:
    return compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-1",
    )


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


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


def _with_lifecycle_started(events: list[EventEnvelope]) -> list[EventEnvelope]:
    accepted = _apply(events, "accept_run", {"run_id": "run-1"})
    queued_events = [*events, *accepted]
    started = _apply(queued_events, "start", {"run_id": "run-1"})
    return [*queued_events, *started]


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


def _callback_payload(
    lease_granted: EventEnvelope,
    *,
    new_state: str = "completed",
) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "node_id": lease_granted.payload["node_id"],
        "execution_id": lease_granted.payload["execution_id"],
        "lease_id": lease_granted.payload["lease_id"],
        "lease_generation": lease_granted.payload["generation"],
        "base_snapshot_id": lease_granted.payload["base_snapshot_id"],
        "observed_graph_position": lease_granted.position,
        "idempotency_key": f"callback-{lease_granted.payload['node_id']}-{new_state}",
        "payload_hash": f"hash-{lease_granted.payload['node_id']}-{new_state}",
        "new_state": new_state,
    }


def _start_payload(lease_granted: EventEnvelope) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "node_id": lease_granted.payload["node_id"],
        "execution_id": lease_granted.payload["execution_id"],
        "lease_id": lease_granted.payload["lease_id"],
        "lease_generation": lease_granted.payload["generation"],
    }


def _node_event(events: list[EventEnvelope], node_id: str) -> EventEnvelope:
    for event in events:
        if event.event_type == "node_created" and event.payload.get("node_id") == node_id:
            return event
    raise AssertionError(f"missing node_created event for {node_id}")


def _node_ids_by_kind(projection: Any, kind: str) -> list[str]:
    return sorted(
        node_id for node_id, node_kind in projection["node_kinds"].items() if node_kind == kind
    )


def schedule_events_by_type(events: list[EventEnvelope], event_type: str) -> list[EventEnvelope]:
    return [event for event in events if event.event_type == event_type]
