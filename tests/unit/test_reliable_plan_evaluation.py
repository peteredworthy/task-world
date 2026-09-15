from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.config import RoutineConfig, RunStatus
from orchestrator.graph import (
    DECISION_COMPILER_CONTRACT_VERSION,
    DECISION_PLAN_SCHEMA_ID,
    DECISION_PLAN_SCHEMA_VERSION,
    ReliablePlanContractIdentity,
    ReliablePlanJoinedCaseObservation,
    ReliablePlanComparisonArtifact,
    ReliablePlanQualificationAuthorityFacts,
    ReliablePlanQualificationReceipt,
    ReliablePlanCorrectnessMetrics,
    ReliablePlanEvaluationConfig,
    ReliablePlanEvaluationResult,
    ReliablePlanGraphShapeMetrics,
    ReliablePlanRecoveryMetrics,
    ReliablePlanScenarioResult,
    ReliablePlanSkeletonQualification,
    ReliablePlanUsageMetrics,
    ReliablePlanEvaluationReport,
    ReliablePlanEvaluationCaseResult,
    ReliablePlanEvaluationAttempt,
    RunLifecycleState,
    FakeClock,
    SequentialIdGenerator,
    compile_routine,
    canonical_decision_v1_model_evaluation_manifest,
    canonical_decision_v1_reliable_plan_scenario_manifest,
    canonical_decision_v1_joined_case_manifest,
    decision_plan_schema_sha256,
    reliable_plan_manifest_hash,
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


def test_legacy_qualification_identity_is_implicit_and_round_trips() -> None:
    config = _config()
    identity = config.scenario_manifest.contract_identity

    assert identity.interaction_contract == "legacy"
    assert identity.answer_schema_id is None
    assert identity.compiler_contract_version is None
    assert ReliablePlanContractIdentity.model_validate(identity.model_dump()) == identity
    assert "contract_identity" not in config.scenario_manifest.model_dump(
        mode="json", exclude_defaults=True
    )


def test_decision_v1_qualification_identity_binds_generated_plan_schema_and_compiler() -> None:
    manifest = canonical_decision_v1_reliable_plan_scenario_manifest()
    identity = manifest.contract_identity

    assert identity.interaction_contract == "decision-v1"
    assert identity.answer_schema_id == DECISION_PLAN_SCHEMA_ID
    assert identity.answer_schema_version == DECISION_PLAN_SCHEMA_VERSION
    assert identity.answer_schema_sha256 == decision_plan_schema_sha256()
    assert identity.compiler_contract_version == DECISION_COMPILER_CONTRACT_VERSION

    payload = manifest.model_dump(mode="json")
    payload["contract_identity"]["answer_schema_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="generated decision-v1 implementation-plan schema"):
        type(manifest).model_validate(payload)


def test_decision_qualification_describes_the_actual_joined_cases() -> None:
    manifest = canonical_decision_v1_reliable_plan_scenario_manifest()
    joined = canonical_decision_v1_joined_case_manifest()
    assert [(s.name, s.product_path) for s in manifest.scenarios] == [
        (case.name, case.product_path) for case in joined.cases
    ]
    assert manifest.scenarios != _config().scenario_manifest.scenarios


@pytest.mark.parametrize("interaction", [None, "decision-v1"])
def test_projection_evaluation_derives_identity_from_frozen_snapshot(
    interaction: str | None,
) -> None:
    routine = RoutineConfig.model_validate(
        {
            "id": "identity",
            "name": "Identity",
            "agent_interaction_contract": interaction,
            "steps": [{"id": "plan", "title": "Plan", "kind": "planner"}],
        }
    )
    compiled = compile_routine(routine, FakeClock(), SequentialIdGenerator(), run_id="identity")
    projection = build_projection(compiled)
    result = evaluate_reliable_plan_projection(
        projection, run_id="identity", arm=_config().luna_arm
    )
    assert result.contract_identity.interaction_contract == (interaction or "legacy")
    wrong_identity = ReliablePlanContractIdentity.for_interaction(
        "legacy" if interaction else "decision-v1"
    )
    with pytest.raises(ValueError, match="frozen routine snapshot"):
        evaluate_reliable_plan_projection(
            projection,
            run_id="identity",
            arm=_config().luna_arm,
            contract_identity=wrong_identity,
        )


def test_legacy_manifest_hash_remains_compatible_with_historical_serialized_receipts() -> None:
    manifest = _config().scenario_manifest
    historical_payload = manifest.model_dump(mode="json")
    historical_payload.pop("contract_identity", None)
    historical_manifest = type(manifest).model_validate(historical_payload)

    assert reliable_plan_manifest_hash(historical_manifest) == reliable_plan_manifest_hash(manifest)


def test_comparison_cannot_use_legacy_results_as_decision_v1_qualification() -> None:
    config = _config()
    decision_manifest = canonical_decision_v1_reliable_plan_scenario_manifest()
    decision_qualification = ReliablePlanSkeletonQualification.from_results(
        decision_manifest,
        tuple(
            ReliablePlanScenarioResult(
                number=scenario.number,
                name=scenario.name,
                product_path=scenario.product_path,
                run_id=f"scenario-{scenario.number}",
                passed=True,
                evidence=(f"assertion-{scenario.number}",),
            )
            for scenario in decision_manifest.scenarios
        ),
    )
    legacy_arm = config.alternate_arm.model_copy(update={"arm_id": "legacy"})

    with pytest.raises(ValueError, match="do not match qualification contract identity"):
        ReliablePlanComparisonArtifact(
            qualification=decision_qualification,
            luna=_result(run_id="run-luna", arm=config.luna_arm),
            alternate=_result(run_id="run-alt", arm=config.alternate_arm),
            legacy_baseline=_result(
                run_id="run-legacy",
                arm=legacy_arm,
                baseline_kind="legacy_plan_then_execute",
            ),
        )


def test_decision_comparison_preserves_legacy_baseline_identity() -> None:
    config = _config()
    manifest = canonical_decision_v1_reliable_plan_scenario_manifest()
    qualification = _qualification(config.model_copy(update={"scenario_manifest": manifest}))
    identity = manifest.contract_identity
    legacy_arm = config.alternate_arm.model_copy(update={"arm_id": "legacy"})
    comparison = ReliablePlanComparisonArtifact(
        qualification=qualification,
        luna=_result(run_id="luna", arm=config.luna_arm).model_copy(
            update={"contract_identity": identity}
        ),
        alternate=_result(run_id="alternate", arm=config.alternate_arm).model_copy(
            update={"contract_identity": identity}
        ),
        legacy_baseline=_result(
            run_id="legacy", arm=legacy_arm, baseline_kind="legacy_plan_then_execute"
        ),
    )
    assert comparison.legacy_baseline.contract_identity.interaction_contract == "legacy"
    assert type(comparison).model_validate_json(comparison.model_dump_json()) == comparison
    payload = comparison.model_dump(mode="json")
    payload["legacy_baseline"]["contract_identity"] = identity.model_dump(mode="json")
    with pytest.raises(ValueError, match="legacy baseline"):
        type(comparison).model_validate(payload)


def test_joined_case_manifest_is_fixed_and_contract_bound() -> None:
    manifest = canonical_decision_v1_joined_case_manifest()

    assert {case.case_id for case in manifest.cases} == {
        "single-batch",
        "dependent-batches",
        "plan-amendment",
        "smoke",
        "correction",
        "blocked",
        "cancellation-restart",
        "defective-candidate",
        "defective-verifier",
        "compatibility",
    }
    payload = manifest.model_dump(mode="json")
    payload["contract_identity"]["compiler_contract_version"] = 99
    with pytest.raises(ValueError, match="generated decision-v1 implementation-plan schema"):
        type(manifest).model_validate(payload)


def test_joined_case_readback_distinguishes_isolated_and_unfinished_nodes() -> None:
    manifest = canonical_decision_v1_joined_case_manifest()
    base = manifest.cases[0]
    with pytest.raises(ValueError, match="both isolated and unfinished"):
        ReliablePlanJoinedCaseObservation(
            case_id=base.case_id,
            run_id="joined-run",
            outcome=base.expected_outcome,
            passed=True,
            false_acceptance=False,
            intervention_recorded=True,
            intentionally_unexecuted_node_ids=("node-a",),
            unfinished_node_ids=("node-a",),
            evidence=("invalid overlap",),
            contract_identity=manifest.contract_identity,
            finalized_execution_count=1,
            active_lease_count=0,
            suspended_lease_count=0,
            owned_process_count=0,
            pending_outbox_count=0,
            candidate_paths=("stage3-smoke.txt",),
            exact_candidate=True,
            clean_checkout=True,
            graph_state=RunLifecycleState.COMPLETED,
            workflow_status=RunStatus.COMPLETED,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"graph_state": "active"},
        {"workflow_status": "active"},
        {"active_lease_count": 3},
        {"suspended_lease_count": 1},
        {"owned_process_count": 1},
        {"pending_outbox_count": 1},
        {"finalized_execution_count": 0},
        {"unfinished_node_ids": ["worker"]},
        {"exact_candidate": False},
        {"clean_checkout": False},
    ],
)
def test_joined_completion_requires_terminal_runtime_and_exact_product(changes: dict) -> None:
    payload = {
        "case_id": "correction",
        "run_id": "joined-run",
        "outcome": "completed",
        "passed": True,
        "false_acceptance": False,
        "intervention_recorded": False,
        "evidence": ["fresh durable readback"],
        "contract_identity": canonical_decision_v1_joined_case_manifest().contract_identity,
        "finalized_execution_count": 8,
        "active_lease_count": 0,
        "suspended_lease_count": 0,
        "owned_process_count": 0,
        "pending_outbox_count": 0,
        "candidate_paths": ["stage3-smoke.txt"],
        "exact_candidate": True,
        "clean_checkout": True,
        "graph_state": "completed",
        "workflow_status": "completed",
    }
    assert ReliablePlanJoinedCaseObservation.model_validate(payload).passed
    with pytest.raises(ValueError, match="completion|ownership"):
        ReliablePlanJoinedCaseObservation.model_validate({**payload, **changes})


def test_authority_rejects_a_receipt_with_a_different_schema_or_compiler_identity() -> None:
    manifest = canonical_decision_v1_reliable_plan_scenario_manifest()
    qualification = ReliablePlanSkeletonQualification.from_results(
        manifest,
        tuple(
            ReliablePlanScenarioResult(
                number=scenario.number,
                name=scenario.name,
                product_path=scenario.product_path,
                run_id=f"scenario-{scenario.number}",
                passed=True,
                evidence=(f"assertion-{scenario.number}",),
            )
            for scenario in manifest.scenarios
        ),
    )
    receipt = ReliablePlanQualificationReceipt(
        receipt_record_id="receipt-1",
        contract_identity=ReliablePlanContractIdentity(),
        manifest_hash=reliable_plan_manifest_hash(manifest),
        observation_record_ids=tuple(f"observation-{number}" for number in range(1, 11)),
        observation_hashes=tuple("sha256:" + "a" * 64 for _ in range(10)),
        evidence_hash="sha256:" + "b" * 64,
    )

    with pytest.raises(ValueError, match="contract identity"):
        ReliablePlanQualificationAuthorityFacts(
            qualification=qualification,
            receipt=receipt,
        )


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
                "runtime_retry_scheduled",
                {
                    "node_id": "worker-1",
                    "lease_id": "lease-1",
                    "generation": 1,
                    "policy": "v1_requeue_same_node_after_agent_death",
                    "reason": "callback_conflict",
                },
                position=7,
            ),
            event(
                "runtime_retry_scheduled",
                {
                    "node_id": "worker-1",
                    "lease_id": "lease-2",
                    "generation": 2,
                    "policy": "v1_requeue_same_node_after_agent_death",
                    "reason": "callback_conflict",
                },
                position=8,
            ),
            event(
                "run_lifecycle_changed",
                {"from_state": "active", "to_state": "completed"},
                position=9,
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
    assert result.recovery.retry_count == 2
    assert result.recovery.revoked_lease_count == 1
    assert result.recovery.active_lease_count == 0


def test_fixed_model_evaluation_manifest_declares_cases_assignment_budgets_and_stops() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()

    assert [case.case_id for case in manifest.cases] == [
        "single-batch",
        "dependent-batches",
        "correction",
        "plan-amendment",
        "verifier-negative",
    ]
    assert manifest.contract_identity.interaction_contract == "decision-v1"
    assert manifest.assignment.runner_type == "codex_server"
    assert manifest.assignment.model == "gpt-5.6-luna"
    assert manifest.per_execution_budget.max_model_executions == 1
    assert manifest.per_execution_budget.max_rejected_answers == 2
    assert manifest.per_execution_budget.max_wall_seconds == 180
    assert manifest.per_case_budget.max_model_executions >= 8
    assert manifest.total_budget.max_model_executions == (
        len(manifest.cases) * manifest.per_case_budget.max_model_executions
    )
    assert manifest.stop_rules.no_automatic_retry is True
    assert manifest.stop_rules.stop_on_false_acceptance is True
    assert manifest.stop_rules.stop_on_missing_evidence is True
    assert type(manifest).model_validate_json(manifest.model_dump_json()) == manifest
    artifact = Path("docs/intent/31-decision-runtime/slice-6e-evaluation-manifest.json").read_text()
    assert type(manifest).model_validate_json(artifact) == manifest


def test_model_evaluation_manifest_rejects_duplicate_cases_and_unsafe_budget() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    duplicate = manifest.model_dump(mode="json")
    duplicate["cases"][1] = duplicate["cases"][0]
    with pytest.raises(ValueError, match="case IDs must be unique"):
        type(manifest).model_validate(duplicate)

    unsafe = manifest.model_dump(mode="json")
    unsafe["stop_rules"]["no_automatic_retry"] = False
    with pytest.raises(ValueError, match="no_automatic_retry"):
        type(manifest).model_validate(unsafe)

    expanded = manifest.model_dump(mode="json")
    expanded["per_case_budget"]["max_model_executions"] = 17
    expanded["total_budget"]["max_model_executions"] = 85
    with pytest.raises(ValueError, match="fixed per-case budget"):
        type(manifest).model_validate(expanded)

    shortened = manifest.model_dump(mode="json")
    shortened["per_execution_budget"]["max_wall_seconds"] = 179
    with pytest.raises(ValueError, match="each phase permits"):
        type(manifest).model_validate(shortened)


def test_evaluation_report_keeps_missing_accounting_unknown_and_counts_failed_attempts() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    results = tuple(
        ReliablePlanEvaluationCaseResult(
            case_id=case.case_id,
            run_id=f"run-{case.case_id}",
            outcome=case.expected_outcome,
            false_acceptance=False,
            intervention_count=1 if case.case_id == "correction" else 0,
            interventions=("bounded-correction",) if case.case_id == "correction" else (),
            attempts=(
                ReliablePlanEvaluationAttempt(
                    attempt_id=f"{case.case_id}-failed",
                    node_id=f"{case.case_id}-node",
                    execution_id=f"{case.case_id}-execution",
                    status="completed" if case.case_id != "verifier-negative" else "failed",
                    model_execution_count=1,
                    rejected_answer_count=0,
                    latency_ms=10 if case.case_id != "verifier-negative" else None,
                    usage=None,
                    cost_usd=None,
                    failure_class=(
                        "provider_failure" if case.case_id == "verifier-negative" else None
                    ),
                ),
            ),
            evidence=("bounded-result",),
        )
        for case in manifest.cases
    )

    report = ReliablePlanEvaluationReport.from_results(manifest, results)

    assert report.metrics.case_count == 5
    assert report.metrics.denominator == 5
    assert report.metrics.correct_completion_count == 4
    assert report.metrics.correct_completion_denominator == 4
    assert report.metrics.bounded_failure_count == 0
    assert report.metrics.bounded_failure_denominator == 1
    assert report.metrics.false_acceptance_count == 0
    assert report.metrics.false_acceptance_denominator == 5
    assert report.metrics.intervention_count == 1
    assert report.metrics.intervention_denominator == 5
    assert report.metrics.intervention_rate == pytest.approx(0.2)
    assert report.metrics.model_execution_count == 5
    assert report.metrics.failed_attempt_count == 1
    assert report.metrics.latency_ms_total is None
    assert report.metrics.total_tokens is None
    assert report.metrics.total_cost_usd is None
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_false_acceptance_invalidates_evaluation_report() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    results = []
    for case in manifest.cases:
        results.append(
            ReliablePlanEvaluationCaseResult(
                case_id=case.case_id,
                run_id=f"run-{case.case_id}",
                outcome=case.expected_outcome,
                false_acceptance=case.case_id == "verifier-negative",
                intervention_count=0,
                interventions=(),
                attempts=(
                    ReliablePlanEvaluationAttempt(
                        attempt_id=f"{case.case_id}-attempt",
                        node_id=f"{case.case_id}-node",
                        execution_id=f"{case.case_id}-execution",
                        status="completed",
                        model_execution_count=1,
                        rejected_answer_count=0,
                        latency_ms=10,
                    ),
                ),
                evidence=("observed",),
            )
        )

    report = ReliablePlanEvaluationReport.from_results(manifest, tuple(results))

    assert report.metrics.false_acceptance_count == 1
    assert report.passed is False


def test_evaluation_report_preserves_stop_on_first_partial_results_with_fixed_denominators() -> (
    None
):
    manifest = canonical_decision_v1_model_evaluation_manifest()
    case = manifest.cases[0]
    result = ReliablePlanEvaluationCaseResult(
        case_id=case.case_id,
        run_id="run-stop-on-first",
        outcome=case.expected_outcome,
        false_acceptance=False,
        intervention_count=0,
        attempts=(
            ReliablePlanEvaluationAttempt(
                attempt_id="attempt-1",
                node_id="planner-1",
                execution_id="execution-1",
                status="completed",
                model_execution_count=1,
                rejected_answer_count=0,
                latency_ms=10,
            ),
        ),
        evidence=("durable result evidence",),
    )

    report = ReliablePlanEvaluationReport.from_results(manifest, (result,))

    assert report.metrics.case_count == 1
    assert report.metrics.denominator == 5
    assert report.metrics.correct_completion_count == 1
    assert report.metrics.correct_completion_denominator == 4
    assert report.metrics.false_acceptance_denominator == 5
    assert report.metrics.intervention_denominator == 5
    assert report.passed is False
    assert set(report.violations) == {
        "missing result for case dependent-batches",
        "missing result for case correction",
        "missing result for case plan-amendment",
        "missing result for case verifier-negative",
    }


def test_evaluation_report_records_per_node_and_execution_budget_violations() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    case = manifest.cases[0]
    result = ReliablePlanEvaluationCaseResult(
        case_id=case.case_id,
        run_id="run-over-budget",
        outcome="failed",
        false_acceptance=False,
        intervention_count=0,
        attempts=(
            ReliablePlanEvaluationAttempt(
                attempt_id="delivery-1",
                node_id="planner-1",
                execution_id="execution-1",
                status="failed",
                model_execution_count=1,
                rejected_answer_count=2,
                latency_ms=90_000,
                failure_class="validation_rejection",
            ),
            ReliablePlanEvaluationAttempt(
                attempt_id="delivery-2",
                node_id="planner-1",
                execution_id="execution-1",
                status="failed",
                model_execution_count=1,
                rejected_answer_count=1,
                latency_ms=100_000,
                failure_class="validation_rejection",
            ),
            ReliablePlanEvaluationAttempt(
                attempt_id="automatic-retry",
                node_id="planner-1",
                execution_id="execution-2",
                status="failed",
                model_execution_count=1,
                rejected_answer_count=0,
                latency_ms=1,
                failure_class="provider_failure",
            ),
        ),
        evidence=("retained rejection and retry evidence",),
    )

    report = ReliablePlanEvaluationReport.from_results(manifest, (result,))

    assert report.metrics.model_execution_count == 3
    assert report.metrics.failed_attempt_count == 3
    assert report.metrics.rejected_answer_count == 3
    assert report.passed is False
    assert (
        "case single-batch execution planner-1/execution-1 exceeded model-execution budget"
        in report.violations
    )
    assert (
        "case single-batch execution planner-1/execution-1 exceeded rejected-answer budget"
        in report.violations
    )
    assert (
        "case single-batch execution planner-1/execution-1 exceeded wall-time budget"
        in report.violations
    )
    assert "case single-batch node planner-1 exceeded model-execution budget" in report.violations


def test_evaluation_report_distinguishes_required_evidence_from_unknown_budget() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    case = manifest.cases[0]
    result = ReliablePlanEvaluationCaseResult(
        case_id=case.case_id,
        run_id="run-unknown",
        outcome=case.expected_outcome,
        false_acceptance=False,
        intervention_count=0,
        attempts=(
            ReliablePlanEvaluationAttempt(
                attempt_id="attempt-unknown-latency",
                node_id="planner-1",
                execution_id="execution-1",
                status="completed",
                model_execution_count=1,
                rejected_answer_count=0,
                latency_ms=None,
                usage=None,
                cost_usd=None,
            ),
        ),
        evidence=(),
    )

    report = ReliablePlanEvaluationReport.from_results(manifest, (result,))

    assert report.metrics.latency_ms_total is None
    assert "case single-batch is missing required evidence" in report.violations
    assert (
        "case single-batch execution planner-1/execution-1 has unknown wall time"
        in report.violations
    )
    assert report.passed is False


def test_evaluation_report_can_pass_without_optional_usage_or_cost_telemetry() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    results = tuple(
        ReliablePlanEvaluationCaseResult(
            case_id=case.case_id,
            run_id=f"run-{case.case_id}",
            outcome=case.expected_outcome,
            false_acceptance=False,
            intervention_count=0,
            attempts=(
                ReliablePlanEvaluationAttempt(
                    attempt_id=f"{case.case_id}-attempt",
                    node_id=f"{case.case_id}-node",
                    execution_id=f"{case.case_id}-execution",
                    status="completed" if case.expected_outcome == "completed" else "failed",
                    model_execution_count=1,
                    rejected_answer_count=0,
                    latency_ms=10,
                    usage=None,
                    cost_usd=None,
                    failure_class=(
                        None if case.expected_outcome == "completed" else "verifier_failure"
                    ),
                ),
            ),
            evidence=("durable case evidence",),
        )
        for case in manifest.cases
    )

    report = ReliablePlanEvaluationReport.from_results(manifest, results)

    assert report.metrics.total_tokens is None
    assert report.metrics.total_cost_usd is None
    assert report.violations == ()
    assert report.passed is True

    reused_run = results[:-1] + (results[-1].model_copy(update={"run_id": results[0].run_id}),)
    reused_report = ReliablePlanEvaluationReport.from_results(manifest, reused_run)
    assert reused_report.passed is False
    assert f"run ID {results[0].run_id} is reused across cases" in reused_report.violations


@pytest.mark.parametrize("starts", [0, 1])
def test_provider_failure_does_not_qualify_a_verifier_negative(starts: int) -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    case = manifest.cases[-1]
    result = ReliablePlanEvaluationCaseResult(
        case_id=case.case_id,
        run_id="outage",
        outcome="blocked",
        false_acceptance=False,
        intervention_count=0,
        attempts=(
            ReliablePlanEvaluationAttempt(
                attempt_id="outage",
                node_id="verifier",
                execution_id="execution",
                status="failed",
                model_execution_count=starts,
                rejected_answer_count=0,
                latency_ms=10 if starts else None,
                failure_class="provider_failure",
            ),
        ),
        evidence=("provider failed before the negative could be judged",),
    )
    report = ReliablePlanEvaluationReport.from_results(manifest, (result,))
    assert report.metrics.bounded_failure_count == 0
    assert "case verifier-negative did not exercise its required failure" in report.violations


def test_empty_negative_is_retained_as_incomplete_evidence() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    result = ReliablePlanEvaluationCaseResult(
        case_id="verifier-negative",
        run_id="empty-negative",
        outcome="blocked",
        false_acceptance=False,
        intervention_count=0,
        attempts=(),
        evidence=(),
    )
    report = ReliablePlanEvaluationReport.from_results(manifest, (result,))
    assert report.passed is False
    assert report.metrics.bounded_failure_count == 0
    assert "case verifier-negative did not exercise its required failure" in report.violations


def test_over_budget_completion_is_not_correct_completion_under_manifest() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    result = ReliablePlanEvaluationCaseResult(
        case_id="single-batch",
        run_id="over-time",
        outcome="completed",
        false_acceptance=False,
        intervention_count=0,
        attempts=(
            ReliablePlanEvaluationAttempt(
                attempt_id="slow",
                node_id="worker",
                execution_id="slow-execution",
                status="completed",
                model_execution_count=1,
                rejected_answer_count=0,
                latency_ms=180001,
            ),
        ),
        evidence=("product completed after the phase deadline",),
    )
    report = ReliablePlanEvaluationReport.from_results(manifest, (result,))
    assert report.metrics.correct_completion_count == 0
    assert report.results[0].outcome == "completed"
    assert report.passed is False


def test_evaluation_report_rejects_completed_cases_without_an_actual_runner_start() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    results = tuple(
        ReliablePlanEvaluationCaseResult(
            case_id=case.case_id,
            run_id=f"run-{case.case_id}",
            outcome=case.expected_outcome,
            false_acceptance=False,
            intervention_count=0,
            attempts=(
                ReliablePlanEvaluationAttempt(
                    attempt_id=f"{case.case_id}-attempt",
                    node_id=f"{case.case_id}-node",
                    execution_id=f"{case.case_id}-execution",
                    status="completed" if case.expected_outcome == "completed" else "failed",
                    model_execution_count=0,
                    rejected_answer_count=0,
                    latency_ms=0,
                    failure_class=(
                        None if case.expected_outcome == "completed" else "provider_failure"
                    ),
                ),
            ),
            evidence=("durable case evidence",),
        )
        for case in manifest.cases
    )

    report = ReliablePlanEvaluationReport.from_results(manifest, results)

    assert report.passed is False
    for case in manifest.cases:
        if case.expected_outcome == "completed":
            assert f"case {case.case_id} has no recorded model execution" in report.violations
            assert (
                f"case {case.case_id} execution {case.case_id}-node/"
                f"{case.case_id}-execution has no model execution"
            ) in report.violations


def test_evaluation_execution_start_requirement_distinguishes_upstream_failure() -> None:
    manifest = canonical_decision_v1_model_evaluation_manifest()
    case = manifest.cases[-1]
    with_received_answer = ReliablePlanEvaluationCaseResult(
        case_id=case.case_id,
        run_id="run-received-answer",
        outcome=case.expected_outcome,
        false_acceptance=False,
        intervention_count=0,
        attempts=(
            ReliablePlanEvaluationAttempt(
                attempt_id="runner-start",
                node_id="verifier-1",
                execution_id="execution-1",
                status="failed",
                model_execution_count=1,
                rejected_answer_count=0,
                latency_ms=10,
                failure_class="validation_rejection",
            ),
            ReliablePlanEvaluationAttempt(
                attempt_id="rejected-delivery",
                node_id="verifier-1",
                execution_id="execution-1",
                status="failed",
                model_execution_count=0,
                rejected_answer_count=1,
                latency_ms=None,
                failure_class="validation_rejection",
            ),
        ),
        evidence=("received answer rejection",),
    )
    started_report = ReliablePlanEvaluationReport.from_results(manifest, (with_received_answer,))
    assert not any("has no model execution" in item for item in started_report.violations)

    missing_start = with_received_answer.model_copy(
        update={
            "run_id": "run-missing-start",
            "attempts": (with_received_answer.attempts[-1],),
        }
    )
    missing_start_report = ReliablePlanEvaluationReport.from_results(manifest, (missing_start,))
    assert (
        "case verifier-negative execution verifier-1/execution-1 has no model execution"
        in missing_start_report.violations
    )

    upstream_failure = with_received_answer.model_copy(
        update={
            "run_id": "run-upstream-failure",
            "attempts": (
                ReliablePlanEvaluationAttempt(
                    attempt_id="provider-failure",
                    node_id="verifier-1",
                    execution_id="execution-2",
                    status="failed",
                    model_execution_count=0,
                    rejected_answer_count=0,
                    latency_ms=None,
                    failure_class="provider_failure",
                ),
            ),
        }
    )
    upstream_report = ReliablePlanEvaluationReport.from_results(manifest, (upstream_failure,))
    assert not any(
        "execution verifier-1/execution-2" in item for item in upstream_report.violations
    )
