"""Default-collected qualification for the bounded sequential reliable-plan profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    FakeClock,
    PatchCommandContext,
    ReliablePlanEvaluationConfig,
    SequentialIdGenerator,
    event_factory,
    node_payload_view,
    node_states_view,
    run_state,
    reliable_plan_assignment_carrier,
)
from orchestrator.graph_runtime import GraphController


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_two_effectful_horizons_materialize_only_after_accepted_evidence(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "sequential-reliable-plan.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "sequential-reliable-plan"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    requirement_id = "requirement-R-1"
    plan_record_id = "accepted-plan"
    plan_report_id = "accepted-plan-report"
    evaluation = ReliablePlanEvaluationConfig.model_validate_json(
        Path("tests/fixtures/graph/reliable_plan_fff4f6b7.json").read_text()
    )
    carrier = reliable_plan_assignment_carrier(
        skeleton_id="reliable-plan-fff4f6b7-v1",
        arm=evaluation.luna_arm,
        selected_runner_type="codex_server",
    )

    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {"node_id": "routine-snapshot", "kind": "context", "state": "completed"},
                    ),
                    make_event(
                        "output_record_accepted",
                        {
                            "record_id": "plan-schema",
                            "record_kind": "graph_record",
                            "record_type": "semantic_schema_declaration",
                            "producer_node_id": "routine-snapshot",
                            "port": "semantic_schema_declaration",
                            "schema": "SemanticSchemaDeclaration",
                            "schema_version": 1,
                            "value": {
                                "schema_id": "reliable-plan-implementation-plan",
                                "version": 1,
                                "semantic_role": "implementation_plan",
                                "json_schema": {
                                    "type": "object",
                                    "required": ["batches"],
                                    "properties": {"batches": {"type": "array", "minItems": 2}},
                                },
                                "authority": "routine_snapshot",
                            },
                        },
                    ),
                    make_event(
                        "node_created",
                        {"node_id": requirement_id, "kind": "requirement", "state": "completed"},
                    ),
                    make_event(
                        "output_record_accepted",
                        {
                            "record_id": requirement_id,
                            "record_kind": "graph_record",
                            "record_type": "requirement_record",
                            "producer_node_id": requirement_id,
                            "port": "requirement",
                            "schema": "RequirementRecord",
                            "value": {
                                "id": "R-1",
                                "text": "Both batches pass",
                                "source": "routine",
                            },
                        },
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": "worker-plan",
                            "kind": "worker",
                            "role": "discovery",
                            "state": "completed",
                            "semantic_stage": "discovery",
                        },
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": "verifier-plan",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "completed",
                            "semantic_stage": "plan_verification",
                        },
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": "planner-h1",
                            "kind": "planner",
                            "role": "planner",
                            "state": "completed",
                            "semantic_stage": "successor_planning",
                            "planning_horizon": 1,
                            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                            "reliable_plan_one_horizon_authorized": True,
                            "reliable_plan_remaining_horizons": 2,
                            "reliable_plan_assignment_carrier": carrier.model_dump(mode="json"),
                            "reliable_plan_assignment_role": "successor_planner",
                            "reliable_plan_selected_runner_type": "codex_server",
                            "runner_model_override": "gpt-5.6-luna",
                            "profile": "architect",
                        },
                    ),
                    make_event(
                        "edge_created",
                        {
                            "edge_id": "plan-report-to-h1",
                            "from_node_id": "verifier-plan",
                            "from_port": "verification_report",
                            "to_node_id": "planner-h1",
                            "to_port": "verification_report",
                            "accepted_record_selector": {
                                "record_type": "verification_report",
                                "outcome": "passed",
                            },
                        },
                    ),
                    make_event(
                        "output_record_accepted",
                        {
                            "record_id": plan_record_id,
                            "record_kind": "graph_record",
                            "record_type": "semantic_artifact",
                            "producer_node_id": "worker-plan",
                            "port": "semantic_artifact",
                            "schema": "SemanticArtifact",
                            "value": {
                                "schema_id": "reliable-plan-implementation-plan",
                                "schema_version": 1,
                                "semantic_role": "implementation_plan",
                                "authority_status": "accepted",
                                "content": {
                                    "batches": [
                                        {"batch_id": "batch-1", "objective": "First"},
                                        {"batch_id": "batch-2", "objective": "Second"},
                                    ]
                                },
                            },
                        },
                    ),
                    make_event(
                        "output_record_accepted",
                        {
                            "record_id": plan_report_id,
                            "record_kind": "verification",
                            "record_type": "verification_report",
                            "producer_node_id": "verifier-plan",
                            "port": "verification_report",
                            "schema": "VerificationReport",
                            "candidate_id": plan_record_id,
                            "outcome": "passed",
                            "evaluated_record_ids": [plan_record_id],
                            "value": {
                                "outcome": "passed",
                                "grades": [
                                    {
                                        "requirement_id": "R-1",
                                        "grade": "A",
                                        "reason": "plan covers both batches",
                                    }
                                ],
                            },
                        },
                    ),
                    make_event(
                        "input_bound",
                        {
                            "edge_id": "plan-report-to-h1",
                            "to_node_id": "planner-h1",
                            "to_port": "verification_report",
                            "record_ids": [plan_report_id],
                            "bound_at_position": 10,
                        },
                    ),
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")

        horizon_one = await _submit_horizon(
            controller,
            run_id,
            started.projection_position,
            proposer="planner-h1",
            horizon=1,
            plan_record_id=plan_record_id,
            plan_report_id=plan_report_id,
            requirement_id=requirement_id,
            with_successor=True,
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-batch-1"] in {"planned", "ready"}
        assert "worker-batch-2" not in node_states_view(projection)
        h2 = node_payload_view(projection, "planner-h2")
        assert h2 is not None
        assert h2["planning_horizon"] == 2
        assert h2["reliable_plan_remaining_horizons"] == 1
        assert h2["runner_model_override"] == "gpt-5.6-luna"
        assert h2["profile"] == "architect"

        replay = await controller.handle_command(
            run_id,
            horizon_one.projection_position,
            "submit_patch",
            {
                "patch_id": "horizon-1-second-distinct-patch",
                "base_graph_position": horizon_one.projection_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "unauthorized-extra-requirement",
                            "kind": "requirement",
                            "state": "completed",
                        },
                    }
                ],
            },
            context=PatchCommandContext(
                run_id=run_id,
                current_graph_position=horizon_one.projection_position,
                proposed_by_node_id="planner-h1",
                actor_role="planner",
            ),
        )
        assert any(
            event.event_type == "graph_patch_rejected"
            and event.payload.get("reason") == "reliable_plan_horizon_already_materialized"
            for event in replay.events
        ), [event.payload.get("reason") for event in replay.events]

        position = await _accept_batch(controller, run_id, replay.projection_position, 1)
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["verifier-batch-1"] == "completed"
        assert "worker-batch-2" not in node_states_view(projection)

        position = await _complete_without_outputs(controller, run_id, position, "planner-h2")
        horizon_two = await _submit_horizon(
            controller,
            run_id,
            position,
            proposer="planner-h2",
            horizon=2,
            plan_record_id=plan_record_id,
            plan_report_id=plan_report_id,
            requirement_id=requirement_id,
            with_successor=False,
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-batch-1"] == "completed"
        assert node_states_view(projection)["worker-batch-2"] in {"planned", "ready"}

        position = await _accept_batch(controller, run_id, horizon_two.projection_position, 2)
        position, acceptance_lease = await _lease(controller, run_id, position, "final-acceptance")
        position = await _callback(
            controller,
            run_id,
            position,
            acceptance_lease,
            [
                {
                    "record_id": "final-acceptance-result",
                    "record_kind": "output",
                    "record_type": "check_result",
                    "producer_node_id": "final-acceptance",
                    "port": "check_result",
                    "schema": "CheckResult",
                    "candidate_id": "candidate-batch-2",
                    "candidate_record_ids": [
                        "candidate-batch-1",
                        "candidate-batch-2",
                    ],
                    "file_state_record_ids": [
                        "file-state-batch-1",
                        "file-state-batch-2",
                    ],
                    "verification_report_record_ids": [
                        "verification-batch-1",
                        "verification-batch-2",
                    ],
                    "task_region_id": "batch-2",
                    "attempt_number": 1,
                    "value": {
                        "status": "passed",
                        "classification": "passed",
                        "command_id": "dynamic-feature-acceptance",
                        "command_binding": "dynamic_feature_acceptance",
                        "command_text": "true",
                        "command": {"argv": ["true"]},
                        "worktree_path": "/worktree",
                        "base_snapshot_id": "snapshot-batch-2",
                        "execution_snapshot_id": "snapshot-batch-2",
                        "execution_id": str(acceptance_lease["execution_id"]),
                        "exit_code": 0,
                        "duration_ms": 1,
                        "stdout_tail": "",
                        "stderr_tail": "",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                        "timeout_seconds": 1.0,
                        "environment_policy": {},
                    },
                }
            ],
        )
        position, audit_lease = await _lease(controller, run_id, position, "final-audit")
        position = await _callback(
            controller,
            run_id,
            position,
            audit_lease,
            [
                {
                    "record_id": "final-audit-report",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "final-audit",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": "candidate-batch-2",
                    "candidate_record_ids": [
                        "candidate-batch-1",
                        "candidate-batch-2",
                    ],
                    "outcome": "passed",
                    "file_state_record_ids": [
                        "file-state-batch-1",
                        "file-state-batch-2",
                    ],
                    "value": {
                        "outcome": "passed",
                        "grades": [
                            {
                                "requirement_id": "R-1",
                                "grade": "A",
                                "reason": "final independent audit passed",
                            }
                        ],
                    },
                }
            ],
        )
        position, gate_lease = await _lease(controller, run_id, position, "final-gate")
        gated = await controller.handle_command(
            run_id,
            position,
            "evaluate_final_gate",
            {
                "node_id": "final-gate",
                "lease_id": gate_lease["lease_id"],
                "lease_generation": gate_lease["generation"],
            },
        )
        completed = await controller.handle_command(run_id, gated.projection_position, "complete")
        assert any(event.event_type == "run_lifecycle_changed" for event in completed.events), [
            event.payload.get("value", event.payload.get("reason"))
            for event in [*gated.events, *completed.events]
        ]
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-batch-1"] == "completed"
        assert node_states_view(projection)["worker-batch-2"] == "completed"
        assert node_states_view(projection)["verifier-batch-2"] == "completed"
        assert run_state(projection) == "completed"
    finally:
        await engine.dispose()


async def _submit_horizon(
    controller: GraphController,
    run_id: str,
    position: int,
    *,
    proposer: str,
    horizon: int,
    plan_record_id: str,
    plan_report_id: str,
    requirement_id: str,
    with_successor: bool,
) -> Any:
    invocations: list[dict[str, Any]] = [
        {
            "macro": "create_effectful_batch",
            "args": {
                "region_id": f"batch-{horizon}",
                "batch_id": f"batch-{horizon}",
                "plan_source_node_id": "worker-plan",
                "plan_verification_source_node_id": "verifier-plan",
                "worker_id": f"worker-batch-{horizon}",
                "verifier_id": f"verifier-batch-{horizon}",
                "semantic_schema_id": "reliable-plan-implementation-plan",
                "semantic_schema_version": 1,
                "objective": f"Implement batch {horizon}",
                "acceptance": [f"batch {horizon} passes"],
                "requirement_source_node_ids": [requirement_id],
                "checks": [
                    {
                        "check_id": f"check-batch-{horizon}",
                        "command_definition": {
                            "id": f"check-batch-{horizon}",
                            "cmd": "true",
                        },
                    }
                ],
                "rubric": ["R-1 is satisfied"],
                "planning_horizon": horizon,
            },
        }
    ]
    if with_successor:
        invocations.append(
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": f"batch-{horizon}",
                    "node_id": f"planner-h{horizon + 1}",
                    "evidence_source_node_id": f"verifier-batch-{horizon}",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": horizon + 1,
                },
            }
        )
    finalization_ops: list[dict[str, Any]] = []
    if not with_successor:
        finalization_ops = [
            {
                "op": "create_node",
                "node": {
                    "node_id": "final-acceptance",
                    "kind": "check",
                    "role": "acceptance_gate",
                    "state": "planned",
                    "semantic_stage": "final_acceptance",
                    "task_region_id": f"batch-{horizon}",
                    "command_binding": "dynamic_feature_acceptance",
                    "inputs": [
                        {
                            "port": "verification_report_batch_1",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        {
                            "port": "verification_report_batch_2",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                    ],
                    "outputs": [
                        {
                            "port": "check_result",
                            "direction": "output",
                            "schema": "CheckResult",
                            "required": True,
                        }
                    ],
                },
            },
            {
                "op": "create_node",
                "node": {
                    "node_id": "final-audit",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "planned",
                    "semantic_stage": "final_audit",
                    "task_region_id": f"batch-{horizon}",
                    "inputs": [
                        {
                            "port": "verification_report_batch_1",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        {
                            "port": "verification_report_batch_2",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        {
                            "port": "dynamic_feature_acceptance",
                            "direction": "input",
                            "schema": "CheckResult",
                            "required": True,
                        },
                    ],
                    "outputs": [
                        {
                            "port": "verification_report",
                            "direction": "output",
                            "schema": "VerificationReport",
                            "required": True,
                        }
                    ],
                },
            },
            {
                "op": "create_node",
                "node": {
                    "node_id": "final-gate",
                    "kind": "final_gate",
                    "role": "final_gate",
                    "state": "planned",
                    "task_region_id": f"batch-{horizon}",
                    "declared_batch_ids": ["batch-1", "batch-2"],
                    "inputs": [
                        {
                            "port": "verification_report_batch_1",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        {
                            "port": "verification_report_batch_2",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                        {
                            "port": "dynamic_feature_acceptance",
                            "direction": "input",
                            "schema": "CheckResult",
                            "required": True,
                        },
                        {
                            "port": "verification_report_final_audit",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                    ],
                },
            },
            {
                "op": "create_edge",
                "edge_id": "edge-batch-1-to-final-audit",
                "from_node_id": "verifier-batch-1",
                "from_port": "verification_report",
                "to_node_id": "final-audit",
                "to_port": "verification_report_batch_1",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            },
            *[
                {
                    "op": "create_edge",
                    "edge_id": f"edge-batch-{batch}-to-final-acceptance",
                    "from_node_id": f"verifier-batch-{batch}",
                    "from_port": "verification_report",
                    "to_node_id": "final-acceptance",
                    "to_port": f"verification_report_batch_{batch}",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                }
                for batch in (1, 2)
            ],
            *[
                {
                    "op": "create_edge",
                    "edge_id": f"edge-batch-{batch}-to-final-gate",
                    "from_node_id": f"verifier-batch-{batch}",
                    "from_port": "verification_report",
                    "to_node_id": "final-gate",
                    "to_port": f"verification_report_batch_{batch}",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                }
                for batch in (1, 2)
            ],
            {
                "op": "create_edge",
                "edge_id": "edge-batch-2-to-final-audit",
                "from_node_id": "verifier-batch-2",
                "from_port": "verification_report",
                "to_node_id": "final-audit",
                "to_port": "verification_report_batch_2",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            },
            {
                "op": "create_edge",
                "edge_id": "edge-final-audit-to-final-gate",
                "from_node_id": "final-audit",
                "from_port": "verification_report",
                "to_node_id": "final-gate",
                "to_port": "verification_report_final_audit",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            },
            *[
                {
                    "op": "create_edge",
                    "edge_id": f"edge-final-acceptance-to-{target}",
                    "from_node_id": "final-acceptance",
                    "from_port": "check_result",
                    "to_node_id": target,
                    "to_port": "dynamic_feature_acceptance",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "check_result",
                        "schema": "CheckResult",
                        "status": "passed",
                    },
                }
                for target in ("final-audit", "final-gate")
            ],
        ]
    result = await controller.handle_command(
        run_id,
        position,
        "submit_patch",
        {
            "patch_id": f"horizon-{horizon}",
            "base_graph_position": position,
            "ops": finalization_ops,
            "macro_invocations": invocations,
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=position,
            proposed_by_node_id=proposer,
            actor_role="planner",
        ),
    )
    assert any(event.event_type == "graph_patch_accepted" for event in result.events), [
        (event.payload.get("reason"), event.payload.get("rejection_reason"))
        for event in result.events
    ]
    return result


async def _accept_batch(controller: GraphController, run_id: str, position: int, batch: int) -> int:
    worker = f"worker-batch-{batch}"
    check = f"check-batch-{batch}"
    verifier = f"verifier-batch-{batch}"
    position, worker_lease = await _lease(controller, run_id, position, worker)
    position = await _callback(
        controller,
        run_id,
        position,
        worker_lease,
        [
            {
                "record_id": f"candidate-batch-{batch}",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": worker,
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": f"candidate-batch-{batch}",
                "task_region_id": f"batch-{batch}",
                "attempt_number": 1,
                "value": {"summary": f"batch {batch} complete"},
            },
            {
                "record_id": f"file-state-batch-{batch}",
                "record_kind": "file_state",
                "producer_node_id": worker,
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": f"snapshot-batch-{batch}",
                "base_snapshot_id": "baseline",
                "verdict": "captured",
            },
        ],
    )
    position, check_lease = await _lease(controller, run_id, position, check)
    position = await _callback(
        controller,
        run_id,
        position,
        check_lease,
        [
            {
                "record_id": f"check-result-batch-{batch}",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": check,
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": f"candidate-batch-{batch}",
                "task_region_id": f"batch-{batch}",
                "attempt_number": 1,
                "value": {
                    "status": "passed",
                    "classification": "passed",
                    "command_id": f"check-batch-{batch}",
                    "command_text": "true",
                    "command": {"argv": ["true"]},
                    "worktree_path": "/worktree",
                    "base_snapshot_id": f"snapshot-batch-{batch}",
                    "execution_id": str(check_lease["execution_id"]),
                    "exit_code": 0,
                    "duration_ms": 1,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "timeout_seconds": 1.0,
                    "environment_policy": {},
                },
            }
        ],
    )
    position, verifier_lease = await _lease(controller, run_id, position, verifier)
    return await _callback(
        controller,
        run_id,
        position,
        verifier_lease,
        [
            {
                "record_id": f"verification-batch-{batch}",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": verifier,
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": f"candidate-batch-{batch}",
                "candidate_record_id": f"candidate-batch-{batch}",
                "candidate_record_ids": [f"candidate-batch-{batch}"],
                "file_state_record_ids": [f"file-state-batch-{batch}"],
                "task_region_id": f"batch-{batch}",
                "outcome": "passed",
                "evaluated_record_ids": [
                    f"check-result-batch-{batch}",
                    "requirement-R-1",
                    f"candidate-batch-{batch}",
                    f"file-state-batch-{batch}",
                ],
                "value": {
                    "outcome": "passed",
                    "grades": [
                        {"requirement_id": "R-1", "grade": "A", "reason": f"batch {batch} accepted"}
                    ],
                },
            }
        ],
    )


async def _lease(
    controller: GraphController, run_id: str, position: int, node_id: str
) -> tuple[int, dict[str, Any]]:
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
    return acknowledged.projection_position, grant


async def _callback(
    controller: GraphController,
    run_id: str,
    position: int,
    lease: dict[str, Any],
    records: list[dict[str, Any]],
) -> int:
    result = await controller.handle_command(
        run_id,
        position,
        "submit_callback",
        {
            "node_id": lease["node_id"],
            "execution_id": lease["execution_id"],
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "base_snapshot_id": lease["base_snapshot_id"],
            "observed_graph_position": position,
            "idempotency_key": f"callback-{lease['execution_id']}",
            "payload": {"output_records": records},
            "complete_node": True,
            "new_state": "completed",
        },
    )
    assert result.events[0].event_type == "callback_accepted", result.events
    return result.projection_position


async def _complete_without_outputs(
    controller: GraphController, run_id: str, position: int, node_id: str
) -> int:
    position, lease = await _lease(controller, run_id, position, node_id)
    return await _callback(controller, run_id, position, lease, [])
