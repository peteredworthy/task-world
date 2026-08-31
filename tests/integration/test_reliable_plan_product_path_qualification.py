from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from orchestrator.api import CreateRunRequest
from orchestrator.config import RoutineConfig, load_routine_from_path
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    GraphCommandContext,
    FakeClock,
    PatchCommandContext,
    ReliablePlanEvaluationConfig,
    ReliablePlanScenarioResult,
    ReliablePlanSkeletonQualification,
    SequentialIdGenerator,
    authorize_reliable_plan_one_horizon,
    compile_routine,
    event_factory,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_attempts_view,
    node_states_view,
    output_record_payloads_view,
    runtime_retry_counts_view,
    require_reliable_plan_one_horizon_authorization,
    serialize_authorized_reliable_plan_run_config,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphEventStore,
    assemble_graph_dispatch_context,
    require_reliable_plan_qualification_for_run,
    run_reliable_plan_product_path_scenarios,
    verified_reliable_plan_seed_config,
)


FIXTURE = Path("tests/fixtures/graph/reliable_plan_fff4f6b7.json")


@pytest.mark.asyncio
async def test_production_reliable_plan_controller_path_gates_first_effectful_lease(
    tmp_path: Path,
) -> None:
    routine_path = Path("routines/dynamic-graph-feature/routine.yaml")
    routine = load_routine_from_path(routine_path)

    async def run_arm(outcome: str) -> tuple[GraphController, AsyncEngine, int, str]:
        engine = create_engine(tmp_path / f"reliable-plan-{outcome}.db")
        sessions = create_session_factory(engine)
        await init_db(engine)
        clock = FakeClock()
        controller = GraphController(sessions, clock, SequentialIdGenerator(), auto_dispatch=False)
        run_id = f"reliable-plan-{outcome}"
        compiled = compile_routine(
            routine,
            clock,
            SequentialIdGenerator(),
            run_id=run_id,
            source_path=str(routine_path),
            run_config={
                "feature_spec_path": "docs/spec.md",
                "acceptance_command": "uv run pytest",
                "reliable_plan_skeleton_id": "reliable-plan-v1",
                "reliable_plan_one_horizon_authorized": True,
            },
        )
        seeded = await controller.handle_command(
            run_id, 0, "seed_compiled_events", {"events": compiled}
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        position = started.projection_position
        skeleton = await controller.handle_command(
            run_id,
            position,
            "submit_patch",
            {
                "patch_id": f"initial-skeleton-{outcome}",
                "base_graph_position": position,
                "macro_invocations": [
                    {
                        "macro": "create_discovery_region",
                        "args": {
                            "region_id": "discovery",
                            "worker_id": "worker-discovery",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "objective": "Discover the implementation plan.",
                            "acceptance": ["plan is complete"],
                            "requirement_source_node_ids": [
                                "requirement-dynamic-feature-acceptance"
                            ],
                        },
                    },
                    {
                        "macro": "create_plan_verification",
                        "args": {
                            "region_id": "plan-verification",
                            "verifier_id": "verifier-plan",
                            "artifact_source_node_id": "worker-discovery",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "objective": "Independently verify the plan.",
                            "acceptance": ["requirements are covered"],
                            "rubric": ["dynamic_feature_acceptance maps to batch-1"],
                            "requirement_source_node_ids": [
                                "requirement-dynamic-feature-acceptance"
                            ],
                        },
                    },
                    {
                        "macro": "create_successor_planner",
                        "args": {
                            "region_id": "successor",
                            "node_id": "planner-successor",
                            "evidence_source_node_id": "verifier-plan",
                            "evidence_source_port": "verification_report",
                            "planning_horizon": 1,
                        },
                    },
                ],
            },
            context=PatchCommandContext(
                run_id=run_id,
                current_graph_position=position,
                proposed_by_node_id="planner-s-01",
                actor_role="planner",
            ),
        )
        assert any(event.event_type == "graph_patch_accepted" for event in skeleton.events)
        position = skeleton.projection_position
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-discovery"] == "planned"
        assert node_states_view(projection)["verifier-plan"] == "planned"
        assert node_states_view(projection)["planner-successor"] == "planned"
        assert not input_bindings_view(projection).get("verifier-plan", {}).get("semantic_artifact")
        assert (
            not input_bindings_view(projection)
            .get("planner-successor", {})
            .get("verification_report")
        )

        async def lease(node_id: str) -> tuple[int, dict[str, object]]:
            nonlocal position
            scheduled = await controller.handle_command(
                run_id,
                position,
                "schedule_tick",
                {
                    "max_grants": 1,
                    "lease_seconds": 60,
                    "base_snapshot_id": "baseline",
                    "priorities": {node_id: 100},
                },
            )
            grant = next(
                event.payload
                for event in scheduled.events
                if event.event_type == "lease_granted" and event.payload.get("node_id") == node_id
            )
            acknowledged = await controller.handle_command(
                run_id,
                scheduled.projection_position,
                "acknowledge_start",
                {
                    "node_id": node_id,
                    "lease_id": grant["lease_id"],
                    "lease_generation": grant["generation"],
                    "execution_id": grant["execution_id"],
                },
            )
            position = acknowledged.projection_position
            return position, grant

        async def callback(grant: dict[str, object], record: dict[str, object]) -> None:
            nonlocal position
            result = await controller.handle_command(
                run_id,
                position,
                "submit_callback",
                {
                    "node_id": grant["node_id"],
                    "execution_id": grant["execution_id"],
                    "lease_id": grant["lease_id"],
                    "lease_generation": grant["generation"],
                    "base_snapshot_id": grant["base_snapshot_id"],
                    "observed_graph_position": position,
                    "idempotency_key": f"callback-{grant['node_id']}-{outcome}",
                    "payload": {"output_records": [record]},
                    "complete_node": True,
                    "new_state": "completed",
                },
            )
            assert result.events[0].event_type == "callback_accepted", result.events
            position = result.projection_position

        _, discovery_lease = await lease("worker-discovery")
        await callback(
            discovery_lease,
            {
                "record_id": "accepted-plan",
                "record_kind": "graph_record",
                "record_type": "semantic_artifact",
                "schema_version": 1,
                "producer_node_id": "worker-discovery",
                "port": "semantic_artifact",
                "schema": "SemanticArtifact",
                "value": {
                    "semantic_role": "implementation_plan",
                    "schema_id": "reliable-plan-implementation-plan",
                    "schema_version": 1,
                    "content": {
                        "batches": [
                            {
                                "batch_id": "batch-1",
                                "objective": "Implement batch 1.",
                                "acceptance": ["batch 1 passes"],
                            }
                        ]
                    },
                    "provenance": {"source": "discovery"},
                    "source_record_ids": ["requirement-dynamic-feature-acceptance"],
                    "requirement_ids": ["dynamic_feature_acceptance"],
                    "task_region_id": "discovery",
                    "validation_status": "validated",
                    "authority_status": "accepted",
                },
            },
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["verifier-plan"] in {"planned", "ready"}
        assert (
            not input_bindings_view(projection)
            .get("planner-successor", {})
            .get("verification_report")
        )

        _, verifier_lease = await lease("verifier-plan")
        await callback(
            verifier_lease,
            {
                "record_id": f"verification-{outcome}",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-plan",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "accepted-plan",
                "task_region_id": "plan-verification",
                "outcome": outcome,
                "value": {
                    "outcome": outcome,
                    "grades": [
                        {
                            "requirement_id": "dynamic_feature_acceptance",
                            "grade": "grade-A" if outcome == "passed" else "grade-C",
                            "reason": "independent plan review",
                        }
                    ],
                },
            },
        )
        return controller, engine, position, run_id

    failed_controller, failed_engine, failed_position, failed_run_id = await run_arm("failed")
    try:
        failed_projection = await failed_controller.read_projection(str(failed_run_id))
        assert (
            not input_bindings_view(failed_projection)
            .get("planner-successor", {})
            .get("verification_report")
        )
        assert not any(
            kind == "worker" and node_id != "worker-discovery"
            for node_id, kind in node_kinds_view(failed_projection).items()
        )
        assert all(lease.state != "active" for lease in leases_view(failed_projection).values())
    finally:
        await failed_engine.dispose()

    passed_controller, passed_engine, position, passed_run_id = await run_arm("passed")
    try:
        passed_projection = await passed_controller.read_projection(str(passed_run_id))
        assert (
            input_bindings_view(passed_projection)
            .get("planner-successor", {})
            .get("verification_report")
        ), {node_id: state for node_id, state in node_states_view(passed_projection).items()}
        scheduled_successor = await passed_controller.handle_command(
            str(passed_run_id),
            position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {"planner-successor": 100},
            },
        )
        assert any(
            event.event_type == "lease_granted"
            and event.payload.get("node_id") == "planner-successor"
            for event in scheduled_successor.events
        )
        effectful = await passed_controller.handle_command(
            str(passed_run_id),
            scheduled_successor.projection_position,
            "submit_patch",
            {
                "patch_id": "first-effectful-batch",
                "base_graph_position": scheduled_successor.projection_position,
                "macro_invocations": [
                    {
                        "macro": "create_effectful_batch",
                        "args": {
                            "region_id": "region-batch-1",
                            "batch_id": "batch-1",
                            "plan_source_node_id": "worker-discovery",
                            "plan_verification_source_node_id": "verifier-plan",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "objective": "Implement batch 1.",
                            "acceptance": ["batch 1 passes"],
                            "requirement_source_node_ids": [
                                "requirement-dynamic-feature-acceptance"
                            ],
                            "checks": [
                                {
                                    "check_id": "check-batch-1",
                                    "command_binding": "dynamic_feature_hidden_oracle",
                                }
                            ],
                            "rubric": ["batch 1 passes"],
                            "planning_horizon": 1,
                        },
                    }
                ],
            },
            context=PatchCommandContext(
                run_id=str(passed_run_id),
                current_graph_position=scheduled_successor.projection_position,
                proposed_by_node_id="planner-successor",
                actor_role="planner",
            ),
        )
        assert any(event.event_type == "graph_patch_accepted" for event in effectful.events)
        effectful_projection = await passed_controller.read_projection(str(passed_run_id))
        effectful_ids = {
            node_id
            for node_id, kind in node_kinds_view(effectful_projection).items()
            if kind == "worker" and node_id != "worker-discovery"
        }
        assert effectful_ids
        effectful_schedule = await passed_controller.handle_command(
            str(passed_run_id),
            effectful.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {next(iter(effectful_ids)): 100},
            },
        )
        assert any(
            event.event_type == "lease_granted" and event.payload.get("node_id") in effectful_ids
            for event in effectful_schedule.events
        )
    finally:
        await passed_engine.dispose()


@pytest.mark.asyncio
async def test_real_appeal_dispatch_context_and_callback_accept_recovery_plan(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "appeal-product-path.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "reliable-plan-real-appeal"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {
                            "node_id": "verifier-plan",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "blocked",
                        },
                    )
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        appealed = await controller.handle_command(
            run_id,
            started.projection_position,
            "raise_appeal",
            {"node_id": "verifier-plan", "appeal_type": "invalid_test"},
            context=GraphCommandContext(
                run_id=run_id,
                current_graph_position=started.projection_position,
            ),
        )
        oversight = next(
            event.payload for event in appealed.events if event.event_type == "node_created"
        )
        oversight_id = str(oversight["node_id"])
        scheduled = await controller.handle_command(
            run_id,
            appealed.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {oversight_id: 100},
            },
        )
        dispatch_item = next(
            item
            for item in scheduled.outbox_items
            if item.kind == "agent_dispatch" and item.payload.get("node_id") == oversight_id
        )
        dispatch = await assemble_graph_dispatch_context(
            sessions, dispatch_item, worktree_path=str(tmp_path)
        )
        assert dispatch.node_kind == "oversight"
        assert dispatch.node_payload["outputs"] == [
            {
                "port": "recovery_plan",
                "direction": "output",
                "schema": "RecoveryPlan",
                "required": True,
            }
        ]
        acknowledged = await controller.handle_command(
            run_id,
            scheduled.projection_position,
            "acknowledge_start",
            {
                "node_id": oversight_id,
                "lease_id": dispatch.lease_id,
                "lease_generation": dispatch.lease_generation,
                "execution_id": dispatch.execution_id,
            },
        )
        record_id = "appeal-recovery-plan"
        callback = await controller.handle_command(
            run_id,
            acknowledged.projection_position,
            "submit_callback",
            {
                "node_id": oversight_id,
                "execution_id": dispatch.execution_id,
                "lease_id": dispatch.lease_id,
                "lease_generation": dispatch.lease_generation,
                "base_snapshot_id": dispatch.base_snapshot_id,
                "observed_graph_position": acknowledged.projection_position,
                "idempotency_key": "appeal-recovery-plan-callback",
                "payload": {
                    "output_records": [
                        {
                            "record_id": record_id,
                            "record_kind": "output",
                            "record_type": "recovery_plan",
                            "producer_node_id": oversight_id,
                            "port": "recovery_plan",
                            "schema": "RecoveryPlan",
                            "value": {
                                "action": "pause",
                                "responsible_actor": "oversight",
                                "graph_changes": [],
                                "reason": "bounded appeal decision",
                                "attempt_number": oversight["attempt_number"],
                                "max_attempts": oversight["max_attempts"],
                            },
                        }
                    ]
                },
                "complete_node": True,
                "new_state": "completed",
            },
        )
        assert callback.events[0].event_type == "callback_accepted"
        assert any(
            event.event_type == "output_record_accepted"
            and event.payload.get("record_id") == record_id
            and event.payload.get("record_type") == "recovery_plan"
            for event in callback.events
        ), [(event.event_type, event.payload) for event in callback.events]
        projection = await controller.read_projection(run_id)
        assert output_record_payloads_view(projection)[record_id].record_type == "recovery_plan"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconstructed_controller_honors_durable_three_attempt_retry_budget(
    tmp_path: Path,
) -> None:
    """The persistent controller boundary survives the same reconstruction as a driver restart.

    A real GraphRunDriver needs runner/worktree orchestration to manufacture a
    runtime death. The durable decision is made below the driver by the public
    controller command, so recreating that controller before every attempt is
    the closest deterministic file-backed proof of the restart invariant.
    """
    engine = create_engine(tmp_path / "durable-retry-reconstruction.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    run_id = "durable-retry-reconstruction"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    health_record = {
        "record_id": "health-check-passed",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "health-check",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "runtime-health",
        "task_region_id": "region-retry",
        "attempt_number": 1,
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "runtime-health",
            "command_text": "runner health probe",
            "command": {"argv": ["true"]},
            "worktree_path": "/work",
            "base_snapshot_id": "baseline",
            "execution_id": "health-exec",
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_tail": "healthy",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 1.0,
            "environment_policy": {},
        },
        "evaluated_record_ids": [],
    }
    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {"node_id": "health-check", "kind": "check", "state": "completed"},
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": "worker-retry",
                            "kind": "worker",
                            "role": "builder",
                            "state": "planned",
                            "attempt_number": 1,
                            "max_attempts": 3,
                            "objective": "Exercise bounded runtime recovery.",
                            "access_mode": "read_only",
                            "acceptance": ["retry is bounded"],
                        },
                    ),
                    make_event("output_record_accepted", health_record),
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        position = started.projection_position

        lease_ids: list[str] = []
        retry_events = []
        exhausted_events = []
        for attempt in range(1, 4):
            # Recreate all process-local controller state before every drive.
            controller = GraphController(sessions, FakeClock(), ids, auto_dispatch=False)
            scheduled = await controller.handle_command(
                run_id,
                position,
                "schedule_tick",
                {
                    "max_grants": 1,
                    "lease_seconds": 60,
                    "base_snapshot_id": "baseline",
                    "priorities": {"worker-retry": 100},
                },
            )
            grant = next(
                event.payload
                for event in scheduled.events
                if event.event_type == "lease_granted"
                and event.payload.get("node_id") == "worker-retry"
            )
            lease_ids.append(str(grant["lease_id"]))
            died = await controller.handle_command(
                run_id,
                scheduled.projection_position,
                "agent_died",
                {
                    "lease_id": grant["lease_id"],
                    "execution_id": grant["execution_id"],
                    "reason": "callback contract conflict",
                    "health_evidence_record_id": "health-check-passed",
                    "max_attempts": 3,
                },
            )
            retry_events.extend(
                event for event in died.events if event.event_type == "runtime_retry_scheduled"
            )
            exhausted_events.extend(
                event
                for event in died.events
                if event.event_type == "node_state_changed"
                and event.payload.get("trigger") == "max_attempts_exhausted"
            )
            position = died.projection_position
            if attempt < 3:
                assert len(retry_events) == attempt

        reconstructed = GraphController(sessions, FakeClock(), ids, auto_dispatch=False)
        projection = await reconstructed.read_projection(run_id)
        assert len(lease_ids) == 3
        assert len(set(lease_ids)) == 3
        assert len(retry_events) == 2
        assert len(exhausted_events) == 1
        assert node_attempts_view(projection)["worker-retry"] == 3
        assert runtime_retry_counts_view(projection)["worker-retry"] == 2
        assert node_states_view(projection)["worker-retry"] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        fourth = await reconstructed.handle_command(
            run_id,
            position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {"worker-retry": 100},
            },
        )
        assert not any(event.event_type == "lease_granted" for event in fourth.events)
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
        assert sum(event.event_type == "lease_granted" for event in events) == 3
        assert sum(event.event_type == "runtime_retry_scheduled" for event in events) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_api_consumes_server_qualification_once_and_rejects_forgery(
    _shared_app_fixture,
    git_repo: Path,
) -> None:
    client: AsyncClient = _shared_app_fixture[0]
    issued = await client.post("/api/runs/reliable-plan-qualification")
    assert issued.status_code == 201, issued.text
    reference = issued.json()["reference"]
    evaluation = ReliablePlanEvaluationConfig.model_validate_json(FIXTURE.read_text())
    base_request = {
        "routine_embedded": {
            "id": "reliable-plan-api",
            "name": "Reliable plan API",
            "execution_mode": "graph",
            "planner_generation_budget": 2,
            "semantic_artifact_schemas": [
                {
                    "schema_id": "reliable-plan-implementation-plan",
                    "version": 1,
                    "semantic_role": "implementation_plan",
                    "json_schema": {
                        "type": "object",
                        "required": ["batches"],
                        "properties": {"batches": {"type": "array"}},
                    },
                }
            ],
            "steps": [
                {
                    "id": "plan",
                    "kind": "planner",
                    "title": "Plan",
                    "tasks": [
                        {
                            "id": "scope",
                            "title": "Scope",
                            "requirements": [
                                {"id": "REQ-1", "desc": "Implement the qualified scope"}
                            ],
                        }
                    ],
                }
            ],
        },
        "repo_name": git_repo.name,
        "branch": "main",
        "execution_mode": "graph",
        "config": {
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_model_assignments": evaluation.luna_arm.model_dump(mode="json"),
        },
    }

    accepted = await client.post(
        "/api/runs",
        json={
            **base_request,
            "reliable_plan_qualification_reference": reference,
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    run_id = accepted_body["id"]
    assert accepted_body["config"]["_reliable_plan_authorization"]["reference"] == reference

    app = _shared_app_fixture[4]
    async with app.state.session_factory() as session:
        run = await RunRepository(session).get(run_id)
        facts = await require_reliable_plan_qualification_for_run(
            session,
            run_id=run_id,
            run_config=run.config,
        )
    seed_config = verified_reliable_plan_seed_config(run.config, facts)
    compiled = compile_routine(
        RoutineConfig.model_validate(run.routine_embedded),
        FakeClock(),
        SequentialIdGenerator(),
        run_id=run_id,
        run_config=seed_config,
    )
    planner_created = next(
        event
        for event in compiled
        if event.event_type == "node_created" and event.payload.get("kind") == "planner"
    )
    assert planner_created.payload["reliable_plan_one_horizon_authorized"] is True
    requirement_node_id = "requirement-qualified-scope"

    controller = GraphController(
        app.state.session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": compiled},
    )
    activated = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    activated = await controller.handle_command(
        run_id,
        activated.projection_position,
        "start",
    )
    first = await controller.handle_command(
        run_id,
        activated.projection_position,
        "submit_patch",
        {
            "patch_id": "authorized-horizon-one",
            "base_graph_position": activated.projection_position,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": requirement_node_id,
                        "kind": "requirement",
                        "role": "requirement",
                        "state": "completed",
                        "outputs": [
                            {
                                "port": "requirement",
                                "direction": "output",
                                "schema": "Requirement",
                            }
                        ],
                    },
                }
            ],
            "macro_invocations": [
                {
                    "macro": "create_discovery_region",
                    "args": {
                        "region_id": "discovery",
                        "worker_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Discover the implementation plan.",
                        "acceptance": ["plan is complete"],
                        "requirement_source_node_ids": [requirement_node_id],
                    },
                },
                {
                    "macro": "create_plan_verification",
                    "args": {
                        "region_id": "plan-verification",
                        "verifier_id": "verifier-plan",
                        "artifact_source_node_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Independently verify the plan.",
                        "acceptance": ["requirements are covered"],
                        "rubric": ["REQ-1 maps to a batch"],
                        "requirement_source_node_ids": [requirement_node_id],
                    },
                },
                {
                    "macro": "create_successor_planner",
                    "args": {
                        "region_id": "successor",
                        "node_id": "planner-successor-one",
                        "evidence_source_node_id": "verifier-plan",
                        "evidence_source_port": "verification_report",
                        "planning_horizon": 1,
                    },
                },
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=activated.projection_position,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
    )
    assert any(event.event_type == "graph_patch_accepted" for event in first.events)
    successor_created = next(
        event
        for event in first.events
        if event.event_type == "node_created"
        and event.payload.get("node_id") == "planner-successor-one"
    )
    assert successor_created.payload["runner_model_override"] == (
        evaluation.luna_arm.successor_planner.model
    )
    assert successor_created.payload["reliable_plan_one_horizon_authorized"] is False
    second = await controller.handle_command(
        run_id,
        first.projection_position,
        "submit_patch",
        {
            "patch_id": "copied-horizon-two",
            "base_graph_position": first.projection_position,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "planner-successor-two",
                        "kind": "planner",
                        "role": "planner",
                        "state": "planned",
                        "planning_horizon": 1,
                    },
                }
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=first.projection_position,
            proposed_by_node_id="planner-successor-one",
            actor_role="planner",
        ),
    )
    assert any(
        event.event_type == "graph_patch_rejected"
        and event.payload["reason"] == "reliable_plan_successor_planning_not_authorized"
        for event in second.events
    )

    copied = await client.post(
        "/api/runs",
        json={
            **base_request,
            "reliable_plan_qualification_reference": reference,
        },
    )
    assert copied.status_code == 409
    assert "already been consumed" in copied.json()["detail"]

    unknown = await client.post(
        "/api/runs",
        json={
            **base_request,
            "reliable_plan_qualification_reference": "rpq_" + "x" * 43,
        },
    )
    assert unknown.status_code == 422
    assert "unknown reliable-plan qualification reference" in unknown.json()["detail"]

    forged = await client.post(
        "/api/runs",
        json={
            **base_request,
            "config": {
                **base_request["config"],
                "_reliable_plan_authorization": {
                    "reference": "rpq_" + "f" * 43,
                    "evidence_hash": "sha256:" + "0" * 64,
                },
            },
            "reliable_plan_qualification_reference": "rpq_" + "f" * 43,
        },
    )
    assert forged.status_code == 422
    assert forged.json()["detail"] == "reliable-plan authorization is server-owned"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_product_path_runner_is_the_only_all_ten_one_horizon_gate(
    tmp_path: Path,
) -> None:
    config = ReliablePlanEvaluationConfig.model_validate_json(FIXTURE.read_text())
    assert config.qualification is None
    assert config.enable_luna_one_horizon_planning is False
    assert config.one_horizon_authorized is False

    qualification_run = await run_reliable_plan_product_path_scenarios(
        config.scenario_manifest,
        root=tmp_path / "qualification",
    )
    qualification = qualification_run.qualification

    assert qualification.qualified
    assert [result.number for result in qualification.results] == list(range(1, 11))
    assert all(result.product_path_passed for result in qualification.results)
    assert all(result.evidence for result in qualification.results)
    gated = authorize_reliable_plan_one_horizon(
        config,
        qualification_run.projection,
        qualification_run.accepted_receipt_record_id,
    )
    assert gated.one_horizon_authorized
    assert (
        require_reliable_plan_one_horizon_authorization(gated).evidence_hash
        == qualification_run.receipt.evidence_hash
    )
    live_run_config = serialize_authorized_reliable_plan_run_config(gated, gated.luna_arm)
    assert live_run_config == {
        "reliable_plan_skeleton_id": gated.skeleton_id,
        "reliable_plan_model_assignments": gated.luna_arm.model_dump(mode="json"),
    }
    assert {
        "enable_luna_one_horizon_planning",
        "qualification",
        "qualification_receipt",
        "qualification_receipt_record_id",
    }.isdisjoint(live_run_config)
    create_request = CreateRunRequest(
        routine_id="reliable-plan-live",
        repo_name="registered-repository",
        branch="main",
        config=live_run_config,
    )
    assert create_request.config == live_run_config

    gated_payload = config.model_dump(mode="json")
    gated_payload.update(
        qualification=qualification.model_dump(mode="json"),
        enable_luna_one_horizon_planning=True,
    )
    with pytest.raises(ValueError, match="public JSON cannot enable"):
        ReliablePlanEvaluationConfig.model_validate(gated_payload)

    artifact_payload = config.model_dump(mode="json")
    artifact_payload["qualification_receipt"] = qualification_run.receipt.model_dump(mode="json")
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ReliablePlanEvaluationConfig.model_validate(artifact_payload)

    failed_results = list(qualification.results)
    observed = failed_results[-1]
    failed_results[-1] = ReliablePlanScenarioResult(
        **{
            **observed.model_dump(exclude={"product_path_passed"}),
            "passed": False,
            "evidence": ("observed scenario failure",),
        }
    )
    failed_qualification = ReliablePlanSkeletonQualification.from_results(
        config.scenario_manifest,
        tuple(failed_results),
    )
    blocked_payload = config.model_dump(mode="json")
    blocked_payload.update(
        qualification=failed_qualification.model_dump(mode="json"),
        enable_luna_one_horizon_planning=True,
    )
    with pytest.raises(ValueError, match="public JSON cannot enable"):
        ReliablePlanEvaluationConfig.model_validate(json.loads(json.dumps(blocked_payload)))

    arbitrary = config.model_copy(
        update={
            "qualification": qualification,
            "enable_luna_one_horizon_planning": True,
        }
    )
    with pytest.raises(ValueError, match="controller-accepted qualification receipt"):
        require_reliable_plan_one_horizon_authorization(arbitrary)
    with pytest.raises(ValueError, match="controller-accepted qualification receipt"):
        serialize_authorized_reliable_plan_run_config(arbitrary, arbitrary.luna_arm)

    public_round_trip = ReliablePlanEvaluationConfig.model_validate_json(
        gated.model_dump_json(exclude={"enable_luna_one_horizon_planning", "qualification"})
    )
    with pytest.raises(ValueError, match="controller-accepted qualification receipt"):
        serialize_authorized_reliable_plan_run_config(
            public_round_trip,
            public_round_trip.luna_arm,
        )
