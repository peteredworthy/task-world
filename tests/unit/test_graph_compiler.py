"""Unit tests for pure routine graph compilation."""

from typing import Any

import pytest

from orchestrator.config.models import (
    ArtifactSpec,
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
    GraphProjection,
    SequentialIdGenerator,
    compile_routine,
    edges_view,
    initial_projection,
    input_bindings_view,
    node_command_definitions_view,
    node_attempts_view,
    node_kinds_view,
    node_task_regions_view,
    planner_generation_budget,
    reduce_event,
)
from tests.unit.graph_test_utils import apply_command, command_context


def test_routine_maps_to_root_and_routine_snapshot_record_node() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert node_kinds_view(projection)["root"] == "root"
    assert node_kinds_view(projection)["routine-snapshot"] == "artifact"
    root_record = _accepted_record(events, "run-context")
    assert root_record.payload["record_type"] == "run_context"
    assert root_record.payload["port"] == "run_context"
    assert root_record.payload["schema"] == "RunContext"
    assert root_record.payload["value"]["routine_id"] == "minimal"
    snapshot_event = _node_event(events, "routine-snapshot")
    assert snapshot_event.payload["role"] == "routine_snapshot"
    assert snapshot_event.payload["snapshot"]["routine_id"] == "minimal"
    assert len(snapshot_event.payload["snapshot"]["content_hash"]) == 64
    snapshot_record = _accepted_record(events, "routine-snapshot-record")
    assert snapshot_record.payload["record_type"] == "routine_snapshot"
    assert snapshot_record.payload["producer_node_id"] == "routine-snapshot"
    assert snapshot_record.payload["value"] == snapshot_event.payload["snapshot"]


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
    node_kinds = node_kinds_view(projection)
    task_regions = node_task_regions_view(projection)

    assert "step-S-01" not in node_kinds
    assert "step-S-02" not in node_kinds
    assert task_regions["worker-s-01-t-01"] == "S-01/T-01"
    assert task_regions["worker-s-02-t-02"] == "S-02/T-02"
    assert any(
        edge.from_node_id == "worker-s-01-t-01"
        and edge.to_node_id == "worker-s-02-t-02"
        and edge.to_port == "prior_step_completion"
        and edge.dependency_type == "state_dependency"
        for edge in edges_view(projection).values()
    )


def test_task_maps_to_task_region_projection_and_worker_node() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert node_kinds_view(projection)["worker-s-01-t-01"] == "worker"
    assert node_task_regions_view(projection)["worker-s-01-t-01"] == "S-01/T-01"
    assert node_attempts_view(projection)["worker-s-01-t-01"] == 1
    assert projection.nodes["worker-s-01-t-01"].runtime.candidate_id == "candidate-s-01-t-01-1"


def test_worker_write_claims_are_scoped_to_declared_artifacts() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            artifacts=[
                ArtifactSpec(path="docs/out.md"),
                ArtifactSpec(path="./tests/../tests/out.md"),
                ArtifactSpec(path="/tmp/not-repo.md"),
                ArtifactSpec(path="../outside.md"),
            ],
        )
    )

    events = _compile(routine)
    worker = _node_event(events, "worker-s-01-t-01").payload

    assert worker["authority"]["resource_claims"] == [
        {"mode": "write", "scope": "repo", "paths": ["docs/out.md", "tests/out.md"]}
    ]


def test_worker_write_claims_include_declared_implementation_helpers() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            artifacts=[ArtifactSpec(path="src/package/feature.py")],
            implementation_paths=["tests/unit/feature_cases.py", "./tests/unit/feature_cases.py"],
        )
    )

    worker = _node_event(_compile(routine), "worker-s-01-t-01").payload

    assert worker["authority"]["resource_claims"] == [
        {
            "mode": "write",
            "scope": "repo",
            "paths": ["src/package/feature.py", "tests/unit/feature_cases.py"],
        }
    ]


@pytest.mark.parametrize(
    "path", ["", "/tmp/helper.py", "../helper.py", "\\helper.py", "C:\\helper.py"]
)
def test_implementation_paths_reject_non_repo_relative_paths(path: str) -> None:
    with pytest.raises(ValueError, match="implementation_paths"):
        TaskConfig(id="T-01", title="Task", implementation_paths=[path])


def test_same_step_artifact_scoped_workers_can_schedule_without_conflict() -> None:
    routine = RoutineConfig(
        id="path-scoped",
        name="Path Scoped",
        steps=[
            StepConfig(
                id="S-01",
                title="Step",
                tasks=[
                    TaskConfig(
                        id="DOCS",
                        title="Docs",
                        artifacts=[ArtifactSpec(path="docs/a.md")],
                    ),
                    TaskConfig(
                        id="TESTS",
                        title="Tests",
                        artifacts=[ArtifactSpec(path="tests/a.txt")],
                    ),
                    TaskConfig(
                        id="DOCS-OVERLAP",
                        title="Docs overlap",
                        artifacts=[ArtifactSpec(path="docs/a.md")],
                    ),
                ],
            )
        ],
    )
    active_events = _with_lifecycle_started(_compile(routine))

    schedule_events = _apply(
        active_events,
        "schedule_tick",
        {"max_grants": 10},
    )

    lease_grants = schedule_events_by_type(schedule_events, "lease_granted")
    assert [event.payload["node_id"] for event in lease_grants] == [
        "worker-s-01-docs",
        "worker-s-01-tests",
    ]
    assert [event.payload["resource_claims"][0]["paths"] for event in lease_grants] == [
        ["docs/a.md"],
        ["tests/a.txt"],
    ]
    assert any(
        event.payload
        == {
            "node_id": "worker-s-01-docs-overlap",
            "reason": "resource_conflict:write:write",
        }
        for event in schedule_events_by_type(schedule_events, "node_deferred")
    )


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
    assert node_kinds_view(projection)[requirement_id] == "requirement"
    assert node_kinds_view(projection)["verifier-s-01-t-01"] == "verifier"
    requirement_event = _node_event(events, requirement_id)
    assert requirement_event.payload["outputs"][0]["schema"] == "RequirementRecord"
    assert requirement_event.payload["requirement"] == {
        "id": "R-01",
        "text": "Must be done",
        "desc": "Must be done",
        "priority": "critical",
        "source": "routine",
        "version": "initial",
        "must": True,
    }
    assert requirement_event.payload["requirement_record"] == {
        "record_id": requirement_id,
        "record_kind": "graph_record",
        "record_type": "requirement_record",
        "producer_node_id": requirement_id,
        "port": "requirement",
        "schema": "RequirementRecord",
        "value": {
            "id": "R-01",
            "text": "Must be done",
            "desc": "Must be done",
            "priority": "critical",
            "source": "routine",
            "version": "initial",
            "must": True,
        },
    }
    requirement_edges = [
        edge for edge in edges_view(projection).values() if edge.from_node_id == requirement_id
    ]
    assert {edge.to_node_id for edge in requirement_edges} == {
        "worker-s-01-t-01",
        "verifier-s-01-t-01",
    }
    for edge in requirement_edges:
        assert edge.to_port in input_bindings_view(projection)[edge.to_node_id]


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
    command_definitions = node_command_definitions_view(projection)
    edges = edges_view(projection)
    for check_id in check_ids:
        assert command_definitions[check_id]["tail_lines"] == 7
        assert any(
            edge.from_node_id == "worker-s-01-t-01"
            and edge.to_node_id == check_id
            and edge.to_port == "candidate_under_test"
            for edge in edges.values()
        )


def test_auto_verify_cmd_resolves_run_config_placeholders() -> None:
    routine = _routine_with_task(
        TaskConfig(
            id="T-01",
            title="Task",
            auto_verify=AutoVerifyConfig(
                items=[
                    AutoVerifyItemConfig(id="spec-exists", cmd="test -f {{spec_path}}"),
                    AutoVerifyItemConfig(id="unresolved", cmd="echo {{unknown_key}}"),
                ],
            ),
        )
    )

    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-1",
        run_config={"spec_path": "docs/spec.md", "slice_id": "2.6"},
    )
    projection = _project(events)

    definitions = node_command_definitions_view(projection)
    assert definitions["check-s-01-t-01-auto_verify-spec-exists"]["cmd"] == "test -f docs/spec.md"
    # Placeholders without a matching run-config key stay literal.
    assert definitions["check-s-01-t-01-auto_verify-unresolved"]["cmd"] == "echo {{unknown_key}}"


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

    assert node_kinds_view(projection)["verifier-s-01-t-01"] == "verifier"
    assert any(
        edge.from_node_id == "worker-s-01-t-01"
        and edge.to_node_id == "verifier-s-01-t-01"
        and edge.to_port == "candidate_under_test"
        for edge in edges_view(projection).values()
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
        for edge in edges_view(projection).values()
        if edge.from_node_id == "worker-s-01-t-01"
        and edge.from_port == "file_state"
        and edge.to_port == "file_state"
    ]
    consumers = {edge.to_node_id for edge in file_state_edges}
    assert "verifier-s-01-t-01" in consumers
    assert any(consumer.startswith("check-") for consumer in consumers)
    assert all(not edge.required for edge in file_state_edges)


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

    assert node_kinds_view(projection)["gate-s-01"] == "gate"
    assert tuple(sorted(projection.governance.configured_gates_by_task.get("S-01/T-01", ()))) == (
        "gate-s-01",
    )
    gate_edges = [
        edge for edge in edges_view(projection).values() if edge.from_node_id == "gate-s-01"
    ]
    assert len(gate_edges) == 1
    assert gate_edges[0].to_node_id == "worker-s-01-t-01"
    assert "approval" in input_bindings_view(projection)["worker-s-01-t-01"]

    no_gate_projection = _project(_compile(_minimal_routine()))
    assert _node_ids_by_kind(no_gate_projection, "gate") == []
    assert "approval" not in input_bindings_view(no_gate_projection).get("worker-s-01-t-01", {})


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
    assert node_kinds_view(projection)[context_id] == "artifact"
    assert any(
        edge.from_node_id == context_id
        and edge.to_node_id == "worker-s-01-t-01"
        and edge.to_port == "context_0"
        for edge in edges_view(projection).values()
    )
    bindings = input_bindings_view(projection)
    assert "context_0" in bindings["worker-s-01-t-01"]
    artifact_record = _accepted_record(events, "artifact-reference-s-01-t-01-0")
    assert artifact_record.payload["record_type"] == "artifact_reference"
    assert artifact_record.payload["producer_node_id"] == context_id
    assert artifact_record.payload["value"]["uri"] == "docs/plan.md"
    assert bindings["worker-s-01-t-01"]["context_0"].record_ids == [
        "artifact-reference-s-01-t-01-0"
    ]


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

    assert node_kinds_view(projection)["fanout-reader-s-01-t-01"] == "planner"
    assert _node_event(events, "fanout-reader-s-01-t-01").payload["role"] == "fan_out_reader"
    assert node_kinds_view(projection)["fanout-join-s-01-t-01"] == "planner"
    assert _node_event(events, "fanout-join-s-01-t-01").payload["role"] == "fan_out_join"
    assert node_kinds_view(projection)["worker-s-01-t-01"] == "worker"
    assert _node_event(events, "worker-s-01-t-01").payload["role"] == "builder"
    assert any(
        edge.from_node_id == "fanout-reader-s-01-t-01"
        and edge.to_node_id == "fanout-join-s-01-t-01"
        and edge.to_port == "reader_outputs"
        for edge in edges_view(projection).values()
    )
    assert any(
        edge.from_node_id == "fanout-join-s-01-t-01"
        and edge.to_node_id == "worker-s-01-t-01"
        and edge.to_port == "fan_out_inputs"
        for edge in edges_view(projection).values()
    )


def test_minimal_single_task_graph_has_exact_minimum_executable_node_set_and_schedules() -> None:
    events = _compile(_minimal_routine())
    projection = _project(events)

    assert node_kinds_view(projection) == {
        "root": "root",
        "routine-snapshot": "artifact",
        "worker-s-01-t-01": "worker",
    }
    assert _node_ids_by_kind(projection, "verifier") == []
    assert _node_ids_by_kind(projection, "check") == []
    assert _node_ids_by_kind(projection, "gate") == []

    active_events = _with_lifecycle_started(events)
    schedule_events = _apply(active_events, "schedule_tick", {"max_grants": 1})

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

    assert planner_generation_budget(projection) == 3
    assert node_kinds_view(projection)["planner-plan"] == "planner"
    assert _node_event(events, "planner-plan").payload["role"] == "planner"
    assert _node_event(events, "planner-plan").payload["generation_index"] == 0
    assert input_bindings_view(projection)["planner-plan"]["routine_snapshot"].record_ids == [
        "routine-snapshot-record"
    ]


def test_dynamic_graph_feature_run_inputs_seed_planner_context() -> None:
    routine = RoutineConfig(
        id="dynamic-graph-feature",
        name="Dynamic Feature",
        steps=[
            StepConfig(
                id="S-01",
                kind="planner",
                title="Plan dynamic feature execution graph",
                step_context="Use submit_graph_patch only.",
            )
        ],
    )

    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-1",
        run_config={
            "feature_spec_path": "docs/graph-approach/dynamic-smoke-feature-spec.md",
            "feature_spec_content": "Build the dynamic-smoke artifact.",
            "feature_spec_content_source": "worktree",
            "acceptance_command": "uv run pytest tests/smoke -q",
            "hidden_oracle_command": "uv run pytest tests/oracle -q",
            "patch_budget": 4,
            "gap_policy_profile": "standard",
            "ignored": "not exposed",
        },
    )

    planner = _node_event(events, "planner-s-01").payload
    dynamic_feature = planner["dynamic_feature"]
    assert dynamic_feature == {
        "feature_spec_path": "docs/graph-approach/dynamic-smoke-feature-spec.md",
        "feature_spec_content": "Build the dynamic-smoke artifact.",
        "feature_spec_content_source": "worktree",
        "acceptance_command": "uv run pytest tests/smoke -q",
        "hidden_oracle_command": "uv run pytest tests/oracle -q",
        "patch_budget": 4,
        "gap_policy_profile": "standard",
    }
    assert "Dynamic feature inputs:" in planner["task_context"]
    assert "docs/graph-approach/dynamic-smoke-feature-spec.md" in planner["task_context"]
    assert "Build the dynamic-smoke artifact." in planner["task_context"]
    assert "uv run pytest tests/oracle -q" not in planner["task_context"]
    assert "hidden_oracle_binding: dynamic_feature_hidden_oracle" in planner["task_context"]

    snapshot = _node_event(events, "routine-snapshot").payload["snapshot"]
    assert snapshot["dynamic_feature"] == dynamic_feature


def test_dynamic_feature_inputs_compile_canonical_acceptance_requirement() -> None:
    routine = RoutineConfig(
        id="dynamic-graph-feature",
        name="Dynamic Feature",
        steps=[StepConfig(id="S-01", kind="planner", title="Plan dynamic feature execution graph")],
    )

    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-1",
        run_config={"acceptance_command": "uv run pytest tests/smoke -q"},
    )

    requirement_nodes = [
        event
        for event in events
        if event.event_type == "node_created" and event.payload.get("kind") == "requirement"
    ]
    assert len(requirement_nodes) == 1
    requirement_node = requirement_nodes[0]
    assert requirement_node.payload["node_id"] == "requirement-dynamic-feature-acceptance"
    assert requirement_node.payload["requirement"]["id"] == "dynamic_feature_acceptance"
    accepted = _accepted_record(events, "requirement-dynamic-feature-acceptance")
    assert accepted.payload == requirement_node.payload["requirement_record"]
    assert accepted.payload["value"]["id"] == "dynamic_feature_acceptance"


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

    assert len(node_kinds_view(projection)) == 3
    assert len(edges_view(projection)) == 1
    assert input_bindings_view(projection)["worker-s-01-t-01"]["routine_snapshot"].record_ids == [
        "routine-snapshot-record"
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

    schedule_events = _apply(active_events, "schedule_tick", {"max_grants": 10})

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
        _apply(events, "schedule_tick", {"max_grants": 10}),
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

    second_tick = _apply(events, "schedule_tick", {"max_grants": 10})
    second_grants = schedule_events_by_type(second_tick, "lease_granted")
    assert [event.payload["node_id"] for event in second_grants] == ["worker-s-02-t-02"]


def test_two_step_routine_worker_failure_blocks_next_step_worker() -> None:
    events = _with_positions(_with_lifecycle_started(_compile(_two_step_routine())))
    first_tick = _append(
        events,
        _apply(events, "schedule_tick", {"max_grants": 10}),
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

    second_tick = _apply(events, "schedule_tick", {"max_grants": 10})

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
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )


def _with_lifecycle_started(events: list[EventEnvelope]) -> list[EventEnvelope]:
    accepted = _apply(events, "accept_run", {})
    queued_events = [*events, *accepted]
    started = _apply(queued_events, "start", {})
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
    node_id = str(lease_granted.payload["node_id"])
    payload: dict[str, Any] = {
        "node_id": node_id,
        "execution_id": lease_granted.payload["execution_id"],
        "lease_id": lease_granted.payload["lease_id"],
        "lease_generation": lease_granted.payload["generation"],
        "base_snapshot_id": lease_granted.payload["base_snapshot_id"],
        "observed_graph_position": lease_granted.position,
        "idempotency_key": f"callback-{node_id}-{new_state}",
        "payload_hash": f"hash-{node_id}-{new_state}",
        "new_state": new_state,
    }
    if new_state == "completed" and node_id.startswith("worker-"):
        payload["payload"] = {
            "payload_hash": f"hash-{node_id}-{new_state}",
            "output_records": [
                {
                    "record_id": f"candidate-{node_id}",
                    "record_kind": "output",
                    "producer_node_id": node_id,
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": {"summary": "done"},
                },
                {
                    "record_id": f"file-state-{node_id}",
                    "record_kind": "file_state",
                    "producer_node_id": node_id,
                    "port": "file_state",
                    "schema": "FileStateRecord",
                    "snapshot_id": f"snapshot-{node_id}",
                    "base_snapshot_id": lease_granted.payload["base_snapshot_id"],
                    "verdict": "captured",
                },
            ],
        }
    return payload


def _start_payload(lease_granted: EventEnvelope) -> dict[str, Any]:
    return {
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


def _accepted_record(events: list[EventEnvelope], record_id: str) -> EventEnvelope:
    for event in events:
        if (
            event.event_type == "output_record_accepted"
            and event.payload.get("record_id") == record_id
        ):
            return event
    raise AssertionError(f"missing output_record_accepted event for {record_id}")


def _node_ids_by_kind(projection: GraphProjection, kind: str) -> list[str]:
    return sorted(
        node_id for node_id, node_kind in node_kinds_view(projection).items() if node_kind == kind
    )


def schedule_events_by_type(events: list[EventEnvelope], event_type: str) -> list[EventEnvelope]:
    return [event for event in events if event.event_type == event_type]
