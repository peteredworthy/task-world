from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from orchestrator.api import CreateRunRequest
from orchestrator.config import RoutineConfig
from orchestrator.db import RunRepository
from orchestrator.graph import (
    FakeClock,
    PatchCommandContext,
    ReliablePlanEvaluationConfig,
    ReliablePlanScenarioResult,
    ReliablePlanSkeletonQualification,
    SequentialIdGenerator,
    authorize_reliable_plan_one_horizon,
    compile_routine,
    require_reliable_plan_one_horizon_authorization,
    serialize_authorized_reliable_plan_run_config,
)
from orchestrator.graph_runtime import (
    GraphController,
    require_reliable_plan_qualification_for_run,
    run_reliable_plan_product_path_scenarios,
    verified_reliable_plan_seed_config,
)


FIXTURE = Path("tests/fixtures/graph/reliable_plan_fff4f6b7.json")


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
            "steps": [{"id": "plan", "kind": "planner", "title": "Plan"}],
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
                        "node_id": "planner-successor-one",
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
