"""Integration tests for routine compilation and graph-runtime seeding."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pytest
from sqlalchemy import func, select

from orchestrator.config import RoutineConfig, load_routine_from_path
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    EventEnvelope,
    FakeClock,
    GraphProjection,
    SequentialIdGenerator,
    compile_routine,
    initial_projection,
    reduce_event,
)
from orchestrator.graph_runtime import (
    GraphCommandResult,
    GraphController,
    GraphEventStore,
    seed_run,
)
from orchestrator.graph_runtime.controller import rebuild_projection

ROUTINE_PATHS = [
    Path("routines/demo-task.yaml"),
    *sorted(Path("routines").glob("*/routine.yaml")),
    *sorted(Path("examples/routines").glob("*.yaml")),
]

DYNAMIC_FEATURE_ROUTINE_PATH = Path("routines/dynamic-graph-feature/routine.yaml")


@pytest.mark.parametrize("routine_path", ROUTINE_PATHS, ids=lambda path: str(path))
def test_routine_corpus_loads_and_compiles_cleanly(routine_path: Path) -> None:
    """Corpus scope is active top-level routines plus examples, not archived fragments."""
    routine = load_routine_from_path(routine_path)

    events = compile_routine(routine, FakeClock(), SequentialIdGenerator(), run_id="corpus-run")
    projection = _project(events)

    assert _count_nodes(projection, "worker") == _task_count(routine)
    assert _count_nodes(projection, "verifier") == _verifier_count(routine)
    assert _count_nodes(projection, "check") == _check_count(routine)
    assert _count_nodes(projection, "gate") == _gate_count(routine)
    assert len(projection["node_kinds"]) >= 3


def test_dynamic_graph_feature_routine_loads_with_graph_head_config() -> None:
    routine = load_routine_from_path(DYNAMIC_FEATURE_ROUTINE_PATH)

    assert routine.id == "dynamic-graph-feature"
    assert routine.execution_mode == "graph"
    assert routine.planner_generation_budget == 10
    assert routine.steps
    first_step = routine.steps[0]
    assert first_step.kind == "planner"
    assert first_step.tasks == []
    assert first_step.step_context is not None
    assert "submit_graph_patch" in first_step.step_context
    assert "horizon_region_templates" in first_step.step_context
    inputs = {input_def.name: input_def for input_def in routine.inputs}
    assert "feature_spec_path" in inputs
    assert "feature_spec_content" in inputs
    assert "acceptance_command" in inputs
    assert inputs["feature_spec_path"].required is True
    assert inputs["feature_spec_content"].required is False
    assert inputs["feature_spec_content"].default == ""
    assert inputs["acceptance_command"].required is True
    assert inputs["hidden_oracle_command"].required is False
    assert inputs["hidden_oracle_command"].default == ""
    assert inputs["patch_budget"].required is False
    assert inputs["patch_budget"].default == 8
    assert inputs["gap_policy_profile"].required is False
    assert inputs["gap_policy_profile"].default == "standard"


@pytest.mark.asyncio
async def test_seed_run_persists_demo_graph_and_rebuilds_matching_projection(
    tmp_path: Path,
) -> None:
    routine = load_routine_from_path(Path("routines/demo-task.yaml"))
    clock = FakeClock()
    run_id = "seed-demo"
    expected_events = compile_routine(
        routine,
        clock,
        SequentialIdGenerator(),
        run_id=run_id,
        source_path="routines/demo-task.yaml",
        source_ref="test-ref",
    )
    expected_projection = _project(expected_events)
    engine = create_engine(tmp_path / "seed-demo.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    try:
        result = await seed_run(
            session_factory,
            routine,
            run_id=run_id,
            clock=clock,
            id_gen=SequentialIdGenerator(),
            source_path="routines/demo-task.yaml",
            source_ref="test-ref",
        )
        async with session_factory() as session:
            stored_events = await GraphEventStore(session).read_run(run_id)
            outbox_count_result = await session.execute(
                select(func.count(GraphOutboxModel.outbox_id))
            )
            outbox_count = int(outbox_count_result.scalar_one())

        assert result.projection_position == len(expected_events)
        assert rebuild_projection(stored_events) == expected_projection
        snapshot = _node_event(stored_events, "routine-snapshot").payload["snapshot"]
        assert snapshot["source_path"] == "routines/demo-task.yaml"
        assert snapshot["source_ref"] == "test-ref"
        assert outbox_count == 0
    finally:
        await engine.dispose()


def test_dynamic_graph_feature_compiles_to_single_initial_planner_head() -> None:
    routine = load_routine_from_path(DYNAMIC_FEATURE_ROUTINE_PATH)
    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="dynamic-feature",
        source_path=str(DYNAMIC_FEATURE_ROUTINE_PATH),
    )
    projection = _project(events)

    assert projection["node_kinds"]["root"] == "root"
    assert projection["node_kinds"]["routine-snapshot"] == "artifact"
    planner_ids = [
        node_id for node_id, node_kind in projection["node_kinds"].items() if node_kind == "planner"
    ]
    assert planner_ids == ["planner-s-01"]
    assert len(planner_ids) == 1
    assert _count_nodes(projection, "worker") == 0
    assert _count_nodes(projection, "verifier") == 0

    planner = _node_event(events, planner_ids[0])
    assert planner.payload["generation_index"] == 0
    authority = planner.payload["authority"]
    assert authority["resource_claims"] == [{"mode": "graph_write", "scope": "graph"}]
    output_ports = {output["port"] for output in planner.payload["outputs"]}
    assert output_ports == {"graph_patch", "completion"}
    assert planner.payload["state"] == "planned"

    planner_input_binding = projection["input_bindings"][planner_ids[0]]["routine_snapshot"]
    assert planner_input_binding["record_ids"] == ["routine-snapshot"]

    root_node = _node_event(events, "root")
    assert root_node.payload["planner_generation_budget"] == 10


@pytest.mark.asyncio
async def test_seed_dynamic_graph_feature_persists_run_inputs(tmp_path: Path) -> None:
    routine = load_routine_from_path(DYNAMIC_FEATURE_ROUTINE_PATH)
    engine = create_engine(tmp_path / "seed-dynamic-feature.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_config = {
        "feature_spec_path": "docs/graph-approach/dynamic-smoke-feature-spec.md",
        "feature_spec_content": "Build the dynamic-smoke artifact.",
        "acceptance_command": "uv run python -c 'print(\"dynamic-smoke\")'",
        "hidden_oracle_command": "uv run python -c 'print(\"validation-strengthened\")'",
        "patch_budget": 4,
        "gap_policy_profile": "standard",
    }

    try:
        await seed_run(
            session_factory,
            routine,
            run_id="seed-dynamic-feature",
            clock=FakeClock(),
            id_gen=SequentialIdGenerator(),
            source_path=str(DYNAMIC_FEATURE_ROUTINE_PATH),
            run_config=run_config,
        )
        async with session_factory() as session:
            stored_events = await GraphEventStore(session).read_run("seed-dynamic-feature")

        planner = _node_event(stored_events, "planner-s-01").payload
        assert planner["dynamic_feature"] == run_config
        assert "docs/graph-approach/dynamic-smoke-feature-spec.md" in planner["task_context"]
        assert "validation-strengthened" not in planner["task_context"]
        assert "hidden_oracle_binding: dynamic_feature_hidden_oracle" in planner["task_context"]
        snapshot = _node_event(stored_events, "routine-snapshot").payload["snapshot"]
        assert snapshot["dynamic_feature"] == run_config
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_controller_two_step_callback_completion_unblocks_next_step(tmp_path: Path) -> None:
    routine = RoutineConfig(
        id="two-step",
        name="Two Step",
        steps=[
            {
                "id": "S-01",
                "title": "First",
                "tasks": [{"id": "T-01", "title": "First task"}],
            },
            {
                "id": "S-02",
                "title": "Second",
                "tasks": [{"id": "T-02", "title": "Second task"}],
            },
        ],
    )
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    engine = create_engine(tmp_path / "controller-two-step.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)

    try:
        seed = await seed_run(
            session_factory, routine, run_id="two-step", clock=clock, id_gen=id_gen
        )
        accepted = await controller.handle_command(
            "two-step", seed.projection_position, "accept_run"
        )
        started = await controller.handle_command("two-step", accepted.projection_position, "start")
        first = await _schedule_ack_and_complete_next(
            controller, "two-step", started.projection_position
        )
        assert first.node_id == "worker-s-01-t-01"

        second_tick = await controller.handle_command(
            "two-step",
            first.projection_position,
            "schedule_tick",
            {"max_grants": 10, "lease_seconds": 60},
        )

        assert _leased_node_ids(second_tick.events) == ["worker-s-02-t-02"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_controller_upstream_failure_blocks_next_step(tmp_path: Path) -> None:
    routine = RoutineConfig(
        id="two-step",
        name="Two Step",
        steps=[
            {
                "id": "S-01",
                "title": "First",
                "tasks": [{"id": "T-01", "title": "First task"}],
            },
            {
                "id": "S-02",
                "title": "Second",
                "tasks": [{"id": "T-02", "title": "Second task"}],
            },
        ],
    )
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    engine = create_engine(tmp_path / "controller-two-step-failed.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)

    try:
        seed = await seed_run(
            session_factory, routine, run_id="two-step", clock=clock, id_gen=id_gen
        )
        accepted = await controller.handle_command(
            "two-step", seed.projection_position, "accept_run"
        )
        started = await controller.handle_command("two-step", accepted.projection_position, "start")
        first = await _schedule_ack_and_complete_next(
            controller,
            "two-step",
            started.projection_position,
            new_state="failed",
        )
        blocked = await controller.handle_command(
            "two-step",
            first.projection_position,
            "schedule_tick",
            {"max_grants": 10, "lease_seconds": 60},
        )

        assert _leased_node_ids(blocked.events) == []
        assert any(
            event.event_type == "node_deferred"
            and event.payload["node_id"] == "worker-s-02-t-02"
            and event.payload["reason"] == "upstream_failed:worker-s-01-t-01"
            for event in blocked.events
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_demo_task_traverses_all_workers_in_step_order(tmp_path: Path) -> None:
    routine = load_routine_from_path(Path("routines/demo-task.yaml"))
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    engine = create_engine(tmp_path / "demo-traversal.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)

    try:
        seed = await seed_run(session_factory, routine, run_id="demo", clock=clock, id_gen=id_gen)
        accepted = await controller.handle_command("demo", seed.projection_position, "accept_run")
        result = await controller.handle_command("demo", accepted.projection_position, "start")
        leased_workers: list[str] = []

        for _ in range(20):
            completed = await _schedule_ack_and_complete_next(
                controller,
                "demo",
                result.projection_position,
                output_candidate=True,
            )
            result = completed.result
            if completed.kind == "worker":
                leased_workers.append(completed.node_id)
            if completed.node_id == "worker-s-02-t-03":
                break

        assert leased_workers == [
            "worker-s-01-t-01",
            "worker-s-01-t-02",
            "worker-s-02-t-03",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compile_seed_and_first_schedule_tick_overhead_is_bounded(tmp_path: Path) -> None:
    """Measured 2026-06-12 locally: prints ms/node and events/node for demo-task.yaml."""
    routine = load_routine_from_path(Path("routines/demo-task.yaml"))
    run_id = "overhead-demo"
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    engine = create_engine(tmp_path / "overhead-demo.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)

    started_at = perf_counter()
    try:
        seed_result = await seed_run(
            session_factory,
            routine,
            run_id=run_id,
            clock=clock,
            id_gen=id_gen,
        )
        accepted = await controller.handle_command(
            run_id,
            seed_result.projection_position,
            "accept_run",
        )
        started = await controller.handle_command(
            run_id,
            accepted.projection_position,
            "start",
        )
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {"max_grants": 1, "lease_seconds": 60},
        )
        elapsed_seconds = perf_counter() - started_at

        async with session_factory() as session:
            stored_events = await GraphEventStore(session).read_run(run_id)

        projection = rebuild_projection(stored_events)
        node_count = len(projection["node_kinds"])
        events_per_node = len(stored_events) / node_count
        ms_per_node = elapsed_seconds * 1000 / node_count
        print(
            "graph_compile_seed_schedule_overhead "
            f"nodes={node_count} events={len(stored_events)} "
            f"events_per_node={events_per_node:.2f} ms_per_node={ms_per_node:.2f}"
        )

        assert scheduled.events
        assert any(event.event_type == "lease_granted" for event in scheduled.events)
        assert ms_per_node < 50
        assert events_per_node < 15
    finally:
        await engine.dispose()


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _task_count(routine: RoutineConfig) -> int:
    return sum(len(step.tasks) for step in routine.steps)


def _verifier_count(routine: RoutineConfig) -> int:
    return sum(1 for step in routine.steps for task in step.tasks if task.verifier.rubric)


def _check_count(routine: RoutineConfig) -> int:
    return sum(
        len(task.auto_verify.items)
        + (len(task.fan_out.auto_verify.items) if task.fan_out and task.fan_out.auto_verify else 0)
        for step in routine.steps
        for task in step.tasks
    )


def _gate_count(routine: RoutineConfig) -> int:
    return sum(1 for step in routine.steps if step.gate is not None)


def _count_nodes(projection: GraphProjection, kind: str) -> int:
    return sum(1 for node_kind in projection["node_kinds"].values() if node_kind == kind)


class CompletedLease:
    def __init__(
        self,
        node_id: str,
        kind: str,
        projection_position: int,
        result: GraphCommandResult,
    ) -> None:
        self.node_id = node_id
        self.kind = kind
        self.projection_position = projection_position
        self.result = result


async def _schedule_ack_and_complete_next(
    controller: GraphController,
    run_id: str,
    position: int,
    *,
    new_state: str = "completed",
    output_candidate: bool = False,
) -> CompletedLease:
    scheduled = await controller.handle_command(
        run_id,
        position,
        "schedule_tick",
        {"max_grants": 1, "lease_seconds": 60},
    )
    lease = next(event for event in scheduled.events if event.event_type == "lease_granted")
    node_id = str(lease.payload["node_id"])
    acknowledged = await controller.handle_command(
        run_id,
        scheduled.projection_position,
        "acknowledge_start",
        {
            "node_id": node_id,
            "lease_id": lease.payload["lease_id"],
            "lease_generation": lease.payload["generation"],
            "execution_id": lease.payload["execution_id"],
        },
    )
    callback_payload = {
        "run_id": run_id,
        "node_id": node_id,
        "execution_id": lease.payload["execution_id"],
        "lease_id": lease.payload["lease_id"],
        "lease_generation": lease.payload["generation"],
        "base_snapshot_id": lease.payload["base_snapshot_id"],
        "observed_graph_position": acknowledged.projection_position,
        "idempotency_key": f"callback-{node_id}-{new_state}",
        "payload_hash": f"hash-{node_id}-{new_state}",
        "new_state": new_state,
    }
    kind = _lease_kind(lease)
    if output_candidate and kind == "worker":
        callback_payload["payload"] = {
            "payload_hash": callback_payload.pop("payload_hash"),
            "output_records": [_candidate_record(node_id)],
        }
    completed = await controller.handle_command(
        run_id,
        acknowledged.projection_position,
        "submit_callback",
        callback_payload,
    )
    return CompletedLease(node_id, kind, completed.projection_position, completed)


def _candidate_record(node_id: str) -> dict[str, object]:
    return {
        "record_id": f"candidate-{node_id}",
        "record_kind": "output",
        "producer_node_id": node_id,
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "value": {"node_id": node_id},
    }


def _leased_node_ids(events: list[EventEnvelope]) -> list[str]:
    return [
        str(event.payload["node_id"]) for event in events if event.event_type == "lease_granted"
    ]


def _lease_kind(lease_granted: EventEnvelope) -> str:
    node_id = lease_granted.payload.get("node_id")
    if isinstance(node_id, str):
        return node_id.split("-", maxsplit=1)[0]
    return "worker"


def _node_event(events: list[EventEnvelope], node_id: str) -> EventEnvelope:
    for event in events:
        if event.event_type == "node_created" and event.payload.get("node_id") == node_id:
            return event
    raise AssertionError(f"missing node_created event for {node_id}")
