from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.graph import (
    ReliablePlanComparisonArtifact,
    ReliablePlanCorrectnessMetrics,
    ReliablePlanEvaluationConfig,
    ReliablePlanEvaluationResult,
    ReliablePlanGraphShapeMetrics,
    ReliablePlanRecoveryMetrics,
    ReliablePlanScenarioResult,
    ReliablePlanSkeletonQualification,
    ReliablePlanUsageMetrics,
    build_projection,
    evaluate_reliable_plan_projection,
    run_reliable_plan_scenarios,
)
from tests.unit.graph_test_utils import event


FIXTURE = Path("tests/fixtures/graph/reliable_plan_fff4f6b7.json")


def _config() -> ReliablePlanEvaluationConfig:
    return ReliablePlanEvaluationConfig.model_validate_json(FIXTURE.read_text())


def _qualification(
    config: ReliablePlanEvaluationConfig,
    *,
    failed: int | None = None,
) -> ReliablePlanSkeletonQualification:
    results = tuple(
        ReliablePlanScenarioResult(
            number=scenario.number,
            name=scenario.name,
            product_path=scenario.product_path,
            run_id=f"scenario-{scenario.number}",
            passed=scenario.number != failed,
            evidence=(f"assertion-{scenario.number}",),
        )
        for scenario in config.scenario_manifest.scenarios
    )
    return ReliablePlanSkeletonQualification.from_results(config.scenario_manifest, results)


def _result(
    *,
    run_id: str,
    arm,
    baseline_kind: str = "dynamic_graph",
    tokens: int = 10,
    revisions: int = 0,
) -> ReliablePlanEvaluationResult:
    return ReliablePlanEvaluationResult(
        run_id=run_id,
        arm_id=arm.arm_id,
        evidence_status="complete",
        baseline_kind=baseline_kind,
        correctness=ReliablePlanCorrectnessMetrics(
            passed=True,
            terminal_state="completed",
            final_blocker_count=0,
            failed_node_count=0,
        ),
        revision_count=revisions,
        graph_shape=ReliablePlanGraphShapeMetrics(node_count=5, edge_count=4),
        usage=ReliablePlanUsageMetrics(total_tokens=tokens, total_actions=2, total_duration_ms=100),
        recovery=ReliablePlanRecoveryMetrics(
            infrastructure_failure_count=0,
            retry_count=revisions,
            recovery_node_count=0,
            revoked_lease_count=0,
            active_lease_count=0,
        ),
        model_profiles=arm,
    )


def test_fixture_validates_directly_and_cannot_self_attest_qualification() -> None:
    config = _config()

    assert config.qualification is None
    assert config.enable_luna_one_horizon_planning is False
    assert [item.number for item in config.scenario_manifest.scenarios] == list(range(1, 11))
    assert config.luna_arm.planner.profile == "architect"
    assert config.luna_arm.discovery_worker.model == "gpt-5.6-luna"
    assert config.luna_arm.verifier.model == "gpt-5.6-sol"
    assert config.alternate_arm.implementation_worker.model == "gpt-5.6-terra"

    raw = json.loads(FIXTURE.read_text())
    raw["self_attested_pass"] = True
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ReliablePlanEvaluationConfig.model_validate(raw)


def test_public_evaluation_config_cannot_self_authorize_one_horizon() -> None:
    config = _config()
    for qualification in (_qualification(config, failed=10), _qualification(config)):
        raw = config.model_dump(mode="json")
        raw.update(
            qualification=qualification.model_dump(mode="json"),
            enable_luna_one_horizon_planning=True,
        )
        with pytest.raises(ValueError, match="public JSON cannot enable"):
            ReliablePlanEvaluationConfig.model_validate(raw)


@pytest.mark.asyncio
async def test_scenario_runner_computes_pass_status_and_executes_all_manifest_entries() -> None:
    config = _config()
    called: list[int] = []

    async def execute(scenario):
        called.append(scenario.number)
        if scenario.number == 7:
            raise AssertionError("rejected snapshot selected")
        return f"controller-run-{scenario.number}", (f"product-proof-{scenario.number}",)

    results = await run_reliable_plan_scenarios(config.scenario_manifest, execute)

    assert called == list(range(1, 11))
    assert [result.number for result in results if result.passed] == [1, 2, 3, 4, 5, 6, 8, 9, 10]
    assert results[6].passed is False
    assert "rejected snapshot selected" in results[6].evidence[0]


def test_evaluation_models_reject_blank_mismatched_and_duplicate_identities() -> None:
    config = _config()
    luna = _result(run_id="run-luna", arm=config.luna_arm)
    alternate = _result(run_id="run-alt", arm=config.alternate_arm)
    legacy_arm = config.alternate_arm.model_copy(update={"arm_id": "legacy"})
    legacy = _result(
        run_id="run-legacy",
        arm=legacy_arm,
        baseline_kind="legacy_plan_then_execute",
    )

    with pytest.raises(ValueError, match="nonempty after trimming"):
        _result(run_id="  ", arm=config.luna_arm)
    with pytest.raises(ValueError, match="must match"):
        ReliablePlanEvaluationResult.model_validate(
            {**luna.model_dump(mode="json"), "arm_id": "different"}
        )
    with pytest.raises(ValueError, match="run IDs must be unique"):
        ReliablePlanComparisonArtifact(
            qualification=_qualification(config),
            luna=luna,
            alternate=alternate.model_copy(update={"run_id": "run-luna"}),
            legacy_baseline=legacy,
        )


def test_complete_comparison_requires_legacy_and_computes_metric_deltas() -> None:
    config = _config()
    luna = _result(run_id="run-luna", arm=config.luna_arm, tokens=10, revisions=1)
    alternate = _result(run_id="run-alt", arm=config.alternate_arm, tokens=14, revisions=2)
    legacy_arm = config.alternate_arm.model_copy(update={"arm_id": "legacy"})
    legacy = _result(
        run_id="run-legacy",
        arm=legacy_arm,
        baseline_kind="legacy_plan_then_execute",
        tokens=20,
        revisions=3,
    )
    comparison = ReliablePlanComparisonArtifact(
        qualification=_qualification(config),
        luna=luna,
        alternate=alternate,
        legacy_baseline=legacy,
    )

    assert comparison.deltas is not None
    assert comparison.deltas.alternate_minus_luna.tokens == 4
    assert comparison.deltas.alternate_minus_luna.revisions == 1
    assert comparison.deltas.luna_minus_legacy.tokens == -10
    assert comparison.deltas.luna_minus_legacy.revisions == -2


def test_evaluate_projection_extracts_all_comparison_metrics_from_events() -> None:
    config = _config()
    projection = build_projection(
        [
            event("run_lifecycle_changed", {"to_state": "active"}, position=0),
            event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "state": "completed",
                    "attempt_number": 2,
                    "declared_batch_id": "batch-1",
                    "planning_horizon": 1,
                },
                position=1,
            ),
            event(
                "node_created",
                {
                    "node_id": "planner-recover-1",
                    "kind": "planner",
                    "state": "completed",
                    "recovery_reason": "failed_verification",
                    "recovery_of_record_id": "verification-failed-1",
                },
                position=2,
            ),
            event(
                "edge_created",
                {
                    "edge_id": "edge-1",
                    "from_node_id": "worker-1",
                    "from_port": "candidate",
                    "to_node_id": "planner-recover-1",
                    "to_port": "failed_verification",
                    "edge_type": "state_dependency",
                },
                position=3,
            ),
            event(
                "node_usage_recorded",
                {
                    "node_id": "worker-1",
                    "node_kind": "worker",
                    "execution_id": "execution-1",
                    "usage_index": 0,
                    "usage_count": 1,
                    "usage_key": "execution-1:0",
                    "model": "gpt-test",
                    "gen_ai_usage_input_tokens": 5,
                    "gen_ai_usage_output_tokens": 7,
                    "num_actions": 3,
                    "latency_ms": 40,
                },
                position=4,
            ),
            event(
                "lease_granted",
                {
                    "lease_id": "lease-1",
                    "node_id": "worker-1",
                    "generation": 1,
                    "execution_id": "execution-1",
                    "base_snapshot_id": "snapshot-1",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
                position=5,
            ),
            event(
                "lease_revoked",
                {"lease_id": "lease-1", "node_id": "worker-1", "reason": "recovered"},
                position=6,
            ),
            event(
                "run_lifecycle_changed",
                {"from_state": "active", "to_state": "completed"},
                position=7,
            ),
        ]
    )

    result = evaluate_reliable_plan_projection(
        projection,
        run_id="run-metrics",
        arm=config.luna_arm,
    )

    assert result.correctness.passed
    assert result.correctness.terminal_state == "completed"
    assert result.revision_count == 1
    assert result.graph_shape.node_count == 2
    assert result.graph_shape.edge_count == 1
    assert result.graph_shape.batch_ids == ("batch-1",)
    assert result.graph_shape.planning_horizons == (1,)
    assert result.usage.total_tokens == 12
    assert result.usage.total_actions == 3
    assert result.usage.total_duration_ms == 40
    assert result.recovery.recovery_node_count == 1
    assert result.recovery.revoked_lease_count == 1
    assert result.recovery.active_lease_count == 0
