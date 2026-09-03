"""Integration tests for routine compilation and graph-runtime seeding."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pytest
from sqlalchemy import func, inspect, select, text

from orchestrator.config import RoutineConfig, load_routine_from_path
from orchestrator.db import (
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphOutboxModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    cache_authority_binding,
    input_bindings_view,
    node_attempts_view,
    node_kinds_view,
    node_payload_view,
    node_task_regions_view,
    output_record_payloads_view,
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

pytestmark = pytest.mark.slow

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
    assert len(node_kinds_view(projection)) >= 3


def test_dynamic_graph_feature_routine_loads_with_graph_head_config() -> None:
    routine = load_routine_from_path(DYNAMIC_FEATURE_ROUTINE_PATH)

    assert routine.id == "dynamic-graph-feature"
    assert routine.execution_mode == "graph"
    assert routine.planner_generation_budget == 10
    assert routine.file_state_policy is not None
    assert routine.file_state_policy.scan_budget.max_entries == 50_000
    assert routine.file_state_policy.scan_budget.max_bytes == 1_073_741_824
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
    assert inputs["acceptance_command_timeout_seconds"].required is False
    assert inputs["acceptance_command_timeout_seconds"].default == 180.0
    assert inputs["hidden_oracle_command"].required is False
    assert inputs["hidden_oracle_command"].default == ""
    assert inputs["patch_budget"].required is False
    assert inputs["patch_budget"].default == 8
    assert inputs["gap_policy_profile"].required is False
    assert inputs["gap_policy_profile"].default == "standard"


def test_worker_payload_carries_required_routine_checks_into_submission_gate() -> None:
    routine = RoutineConfig.model_validate(
        {
            "id": "submission-gate-commands",
            "name": "Submission gate commands",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Task 1",
                            "accepted_baseline_failure_fingerprints": ["a" * 64],
                            "acceptance_command_timeout_seconds": 725,
                            "auto_verify": {
                                "items": [
                                    {"id": "required", "cmd": "uv run pytest -q"},
                                    {
                                        "id": "advisory",
                                        "cmd": "uv run ruff check .",
                                        "must": False,
                                    },
                                ]
                            },
                            "fan_out": {
                                "input_glob": "plans/*.md",
                                "output_pattern": "results/{stem}.md",
                                "per_item_prompt": "Implement {input}",
                                "auto_verify": {
                                    "items": [
                                        {"id": "duplicate", "cmd": "uv run pytest -q"},
                                        {"id": "types", "cmd": "uv run pyright"},
                                    ]
                                },
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="submission-gate-commands-run",
    )
    worker = next(
        event
        for event in events
        if event.event_type == "node_created" and event.payload.get("kind") == "worker"
    )

    assert worker.payload["acceptance_commands"] == [
        "uv run pytest -q",
        "uv run pyright",
    ]
    assert worker.payload["accepted_baseline_failure_fingerprints"] == ["a" * 64]
    assert worker.payload["acceptance_command_timeout_seconds"] == 725
    assert worker.payload["effect_contract"] == "effectful_write"
    assert worker.payload["access_mode"] == "write"


@pytest.mark.asyncio
async def test_seed_run_checkpoint_retains_worker_submission_gate_contract(
    tmp_path: Path,
) -> None:
    routine = RoutineConfig.model_validate(
        {
            "id": "persisted-submission-gate-contract",
            "name": "Persisted submission gate contract",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Task 1",
                            "accepted_baseline_failure_fingerprints": ["a" * 64],
                            "acceptance_command_timeout_seconds": 725,
                            "auto_verify": {
                                "items": [
                                    {
                                        "id": "required",
                                        "cmd": "uv run pytest -q",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )
    engine = create_engine(tmp_path / "persisted-gate-contract.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "persisted-gate-contract"

    try:
        await seed_run(
            session_factory,
            routine,
            run_id=run_id,
            clock=FakeClock(),
            id_gen=SequentialIdGenerator(),
        )
        async with session_factory() as session:
            checkpoint = await GraphEventStore(session).read_current_projection_view(run_id)

        assert checkpoint is not None
        payload = node_payload_view(checkpoint.projection, "worker-step-1-task-1")
        assert payload is not None
        assert payload["acceptance_commands"] == ["uv run pytest -q"]
        assert payload["accepted_baseline_failure_fingerprints"] == ["a" * 64]
        assert payload["acceptance_command_timeout_seconds"] == 725
        assert payload["effect_contract"] == "effectful_write"
    finally:
        await engine.dispose()


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
        assert stored_events == result.events
        assert rebuild_projection(stored_events) == rebuild_projection(result.events)
        snapshot = _node_event(stored_events, "routine-snapshot").payload["snapshot"]
        assert snapshot["source_path"] == "routines/demo-task.yaml"
        assert snapshot["source_ref"] == "test-ref"
        assert outbox_count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_seed_run_uses_v2_node_detail_owner_without_mutating_legacy_tables(
    tmp_path: Path,
) -> None:
    """A pre-semantic-contract database remains readable after current init/seed."""
    engine = create_engine(tmp_path / "pre-bd92-node-detail.db")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE graph_node_detail_summaries ("
                "run_id VARCHAR NOT NULL, node_id VARCHAR NOT NULL, position INTEGER NOT NULL, "
                "kind VARCHAR, role VARCHAR, state VARCHAR, task_region_id VARCHAR, "
                "input_ports JSON NOT NULL, output_records JSON NOT NULL, "
                "file_state_records JSON NOT NULL, leases JSON NOT NULL, active_lease JSON, "
                "callback_history JSON NOT NULL, events JSON NOT NULL, prompt_summary JSON, "
                "PRIMARY KEY (run_id, node_id))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX idx_graph_node_detail_summaries_run "
                "ON graph_node_detail_summaries (run_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX idx_graph_node_detail_summaries_run_position "
                "ON graph_node_detail_summaries (run_id, position)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE graph_node_detail_summary_checkpoints ("
                "run_id VARCHAR NOT NULL PRIMARY KEY, position INTEGER NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO graph_node_detail_summaries "
                "(run_id, node_id, position, kind, role, state, task_region_id, "
                "input_ports, output_records, file_state_records, leases, active_lease, "
                "callback_history, events, prompt_summary) VALUES "
                "('legacy-run', 'legacy-node', 17, 'worker', 'builder', 'completed', "
                "'legacy-region', '{}', '[]', '[]', '[]', NULL, '[]', '[]', "
                "'{\"sentinel\": true}')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO graph_node_detail_summary_checkpoints "
                "(run_id, position) VALUES ('legacy-run', 17)"
            )
        )

    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with engine.begin() as conn:
            schema = await conn.run_sync(
                lambda sync_conn: {
                    "tables": set(inspect(sync_conn).get_table_names()),
                    "legacy_columns": {
                        column["name"]
                        for column in inspect(sync_conn).get_columns("graph_node_detail_summaries")
                    },
                    "legacy_indexes": {
                        index["name"]
                        for index in inspect(sync_conn).get_indexes("graph_node_detail_summaries")
                    },
                    "legacy_checkpoint_columns": {
                        column["name"]
                        for column in inspect(sync_conn).get_columns(
                            "graph_node_detail_summary_checkpoints"
                        )
                    },
                    "legacy_checkpoint_indexes": {
                        index["name"]
                        for index in inspect(sync_conn).get_indexes(
                            "graph_node_detail_summary_checkpoints"
                        )
                    },
                    "v2_columns": {
                        column["name"]
                        for column in inspect(sync_conn).get_columns(
                            "graph_node_detail_summaries_v2"
                        )
                    },
                    "v2_indexes": {
                        index["name"]
                        for index in inspect(sync_conn).get_indexes(
                            "graph_node_detail_summaries_v2"
                        )
                    },
                }
            )
            legacy_summary = (
                await conn.execute(
                    text(
                        "SELECT position, prompt_summary "
                        "FROM graph_node_detail_summaries "
                        "WHERE run_id = 'legacy-run' AND node_id = 'legacy-node'"
                    )
                )
            ).one()
            legacy_checkpoint = (
                await conn.execute(
                    text(
                        "SELECT position FROM graph_node_detail_summary_checkpoints "
                        "WHERE run_id = 'legacy-run'"
                    )
                )
            ).scalar_one()

        assert {
            "graph_node_detail_summaries",
            "graph_node_detail_summary_checkpoints",
            "graph_node_detail_summaries_v2",
            "graph_node_detail_summary_checkpoints_v2",
        } <= schema["tables"]
        assert schema["legacy_columns"] == {
            "run_id",
            "node_id",
            "position",
            "kind",
            "role",
            "state",
            "task_region_id",
            "input_ports",
            "output_records",
            "file_state_records",
            "leases",
            "active_lease",
            "callback_history",
            "events",
            "prompt_summary",
        }
        assert schema["legacy_indexes"] == {
            "idx_graph_node_detail_summaries_run",
            "idx_graph_node_detail_summaries_run_position",
        }
        assert schema["legacy_checkpoint_columns"] == {"run_id", "position"}
        assert schema["legacy_checkpoint_indexes"] == set()
        assert {
            "semantic_contract",
            "readiness_reason",
            "usage_summary",
            "snapshot_authority",
        } <= schema["v2_columns"]
        assert schema["v2_indexes"] == {
            "idx_graph_node_detail_summaries_v2_run",
            "idx_graph_node_detail_summaries_v2_run_position",
        }
        assert legacy_summary == (17, '{"sentinel": true}')
        assert legacy_checkpoint == 17

        run_id = "current-seed-on-legacy-db"
        result = await seed_run(
            session_factory,
            load_routine_from_path(Path("routines/demo-task.yaml")),
            run_id=run_id,
            clock=FakeClock(),
            id_gen=SequentialIdGenerator(),
        )
        async with session_factory() as session:
            stored_events = await GraphEventStore(session).read_run(run_id)
            rows = list(
                (
                    await session.execute(
                        select(GraphNodeDetailSummaryModel)
                        .where(GraphNodeDetailSummaryModel.run_id == run_id)
                        .order_by(GraphNodeDetailSummaryModel.node_id)
                    )
                ).scalars()
            )
            checkpoint = await session.get(GraphNodeDetailSummaryCheckpointModel, run_id)

        assert stored_events == result.events
        assert rows
        task_row = next(row for row in rows if row.kind == "worker")
        assert task_row.semantic_contract["work_mode"] == "implementation"
        assert task_row.semantic_contract["inputs"]
        assert task_row.semantic_contract["outputs"]
        assert task_row.readiness_reason == "planned"
        assert task_row.usage_summary == {}
        assert checkpoint is not None
        assert checkpoint.position == len(stored_events)

        async with engine.begin() as conn:
            assert (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM graph_node_detail_summaries "
                        "WHERE run_id = 'legacy-run' AND node_id = 'legacy-node'"
                    )
                )
            ).scalar_one() == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM graph_node_detail_summary_checkpoints "
                        "WHERE run_id = 'legacy-run' AND position = 17"
                    )
                )
            ).scalar_one() == 1
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

    authority = cache_authority_binding(projection)
    assert authority.policy.scan_budget.max_entries == 50_000
    assert authority.policy.scan_budget.max_bytes == 1_073_741_824

    assert node_kinds_view(projection)["root"] == "root"
    assert node_kinds_view(projection)["routine-snapshot"] == "artifact"
    planner_ids = [
        node_id
        for node_id, node_kind in node_kinds_view(projection).items()
        if node_kind == "planner"
    ]
    assert planner_ids == ["planner-s-01"]
    assert len(planner_ids) == 1
    assert _count_nodes(projection, "worker") == 0
    assert _count_nodes(projection, "verifier") == 0

    planner = _node_event(events, planner_ids[0])
    assert planner.payload["generation_index"] == 0
    planner_authority = planner.payload["authority"]
    assert planner_authority["resource_claims"] == [{"mode": "graph_write", "scope": "graph"}]
    assert planner.payload["cache_authority_hash"] == authority.hash
    output_ports = {output["port"] for output in planner.payload["outputs"]}
    assert output_ports == {"graph_patch", "completion"}
    assert planner.payload["state"] == "planned"

    planner_input_binding = input_bindings_view(projection)[planner_ids[0]]["routine_snapshot"]
    assert planner_input_binding.record_ids == ["routine-snapshot-record"]
    snapshot_record = _accepted_record(events, "routine-snapshot-record")
    assert snapshot_record.payload["record_type"] == "routine_snapshot"
    assert snapshot_record.payload["producer_node_id"] == "routine-snapshot"
    assert snapshot_record.payload["value"]["cache_authority_hash"] == authority.hash
    assert snapshot_record.payload["value"]["cache_authority_preimage"] == authority.preimage

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
        "acceptance_command_timeout_seconds": 725,
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
        seeded_authority = cache_authority_binding(_project(stored_events))
        assert seeded_authority.policy.scan_budget.max_entries == 50_000
        assert seeded_authority.policy.scan_budget.max_bytes == 1_073_741_824
        assert snapshot["cache_authority_hash"] == seeded_authority.hash
        assert snapshot["cache_authority_preimage"] == seeded_authority.preimage
    finally:
        await engine.dispose()


@pytest.mark.parametrize("timeout", [True, 0, 3601, "725"])
def test_dynamic_feature_timeout_fails_at_compile_boundary(timeout: object) -> None:
    routine = load_routine_from_path(DYNAMIC_FEATURE_ROUTINE_PATH)

    with pytest.raises(ValueError, match="acceptance_command_timeout_seconds"):
        compile_routine(
            routine,
            FakeClock(),
            SequentialIdGenerator(),
            run_id="invalid-dynamic-timeout",
            run_config={
                "feature_spec_path": "docs/spec.md",
                "acceptance_command": "true",
                "acceptance_command_timeout_seconds": timeout,
            },
        )


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
        seeded_at = perf_counter()
        accepted = await controller.handle_command(
            run_id,
            seed_result.projection_position,
            "accept_run",
        )
        accepted_at = perf_counter()
        started = await controller.handle_command(
            run_id,
            accepted.projection_position,
            "start",
        )
        run_started_at = perf_counter()
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {"max_grants": 1, "lease_seconds": 60},
        )
        scheduled_at = perf_counter()
        elapsed_seconds = scheduled_at - started_at

        async with session_factory() as session:
            stored_events = await GraphEventStore(session).read_run(run_id)

        projection = rebuild_projection(stored_events)
        node_count = len(node_kinds_view(projection))
        events_per_node = len(stored_events) / node_count
        ms_per_node = elapsed_seconds * 1000 / node_count
        print(
            "graph_compile_seed_schedule_overhead "
            f"nodes={node_count} events={len(stored_events)} "
            f"events_per_node={events_per_node:.2f} ms_per_node={ms_per_node:.2f}"
            f" seed_ms={(seeded_at - started_at) * 1000:.2f}"
            f" accept_ms={(accepted_at - seeded_at) * 1000:.2f}"
            f" start_ms={(run_started_at - accepted_at) * 1000:.2f}"
            f" schedule_ms={(scheduled_at - run_started_at) * 1000:.2f}"
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
    return sum(1 for node_kind in node_kinds_view(projection).values() if node_kind == kind)


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
    projection = await controller.read_projection(run_id)
    candidate_id = projection.nodes[node_id].runtime.candidate_id
    task_region_id = node_task_regions_view(projection).get(node_id)
    attempt_number = node_attempts_view(projection).get(node_id)
    assert candidate_id is not None
    assert task_region_id is not None
    output_records: list[dict[str, object]] = []
    if new_state == "completed" and kind == "worker":
        output_records = [
            _candidate_record(node_id, candidate_id, task_region_id, attempt_number),
            _file_state_record(node_id),
        ]
    elif new_state == "completed" and kind == "check":
        output_records = [
            _check_result_record(node_id, candidate_id, task_region_id, attempt_number)
        ]
    elif new_state == "completed" and kind == "verifier":
        requirement_prefix = f"requirement-{task_region_id.lower().replace('/', '-')}-"
        requirement_id = next(
            record.value.id
            for record in output_record_payloads_view(projection).values()
            if record.record_type == "requirement_record"
            and record.producer_node_id.startswith(requirement_prefix)
        )
        output_records = [
            _verification_record(node_id, candidate_id, task_region_id, requirement_id)
        ]
    elif output_candidate:
        output_records = [
            _candidate_record(node_id, candidate_id, task_region_id, attempt_number),
            _file_state_record(node_id),
        ]

    if output_records:
        callback_payload["payload"] = {
            "payload_hash": callback_payload.pop("payload_hash"),
            "output_records": output_records,
        }
    completed = await controller.handle_command(
        run_id,
        acknowledged.projection_position,
        "submit_callback",
        callback_payload,
    )
    return CompletedLease(node_id, kind, completed.projection_position, completed)


def _candidate_record(
    node_id: str, candidate_id: str, task_region_id: str, attempt_number: int
) -> dict[str, object]:
    return {
        "record_id": candidate_id,
        "record_kind": "output",
        "producer_node_id": node_id,
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": candidate_id,
        "task_region_id": task_region_id,
        "attempt_number": attempt_number,
        "value": {"summary": f"completed {node_id}"},
    }


def _file_state_record(node_id: str) -> dict[str, object]:
    return {
        "record_id": f"file-state-{node_id}",
        "record_kind": "file_state",
        "producer_node_id": node_id,
        "port": "file_state",
        "schema": "FileStateRecord",
        "snapshot_id": f"snapshot-{node_id}",
        "base_snapshot_id": "S0",
        "verdict": "captured",
    }


def _check_result_record(
    node_id: str, candidate_id: str, task_region_id: str, attempt_number: int
) -> dict[str, object]:
    return {
        "record_id": f"check-result-{node_id}",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": node_id,
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": candidate_id,
        "task_region_id": task_region_id,
        "attempt_number": attempt_number,
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": f"check-{node_id}",
            "command_binding": None,
            "command_text": "test helper check",
            "command": {"id": f"check-{node_id}", "argv": ["true"]},
            "worktree_path": "/tmp/test-worktree",
            "base_snapshot_id": "S0",
            "execution_id": f"exec-{node_id}",
            "exit_code": 0,
            "duration_ms": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 60,
            "environment_policy": {
                "cwd": "/tmp/test-worktree",
                "env": "inherited",
                "shell": False,
            },
        },
    }


def _verification_record(
    node_id: str, candidate_id: str, task_region_id: str, requirement_id: str
) -> dict[str, object]:
    return {
        "record_id": f"verification-{node_id}",
        "record_kind": "verification",
        "producer_node_id": node_id,
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": candidate_id,
        "task_region_id": task_region_id,
        "outcome": "passed",
        "value": {
            "outcome": "passed",
            "grades": [{"requirement_id": requirement_id, "grade": "A"}],
        },
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


def _accepted_record(events: list[EventEnvelope], record_id: str) -> EventEnvelope:
    for event in events:
        if (
            event.event_type == "output_record_accepted"
            and event.payload.get("record_id") == record_id
        ):
            return event
    raise AssertionError(f"missing output_record_accepted event for {record_id}")
