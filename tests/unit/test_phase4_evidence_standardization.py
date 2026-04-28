"""Unit coverage for the phase-4 evidence standardization coordinator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "run_phase4_evidence_standardization.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("phase4_evidence_standardization", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evidence_bundle_requires_planner_consumable_fields() -> None:
    module = _load_module()
    bundle = module.EvidenceBundle.model_validate(
        module.demo_specs("phase4-test")[0],
    )

    assert bundle.schema_version == "phase4.evidence.v1"
    assert bundle.assumption_tested
    assert bundle.commands_run[0].exit_code == 0
    assert "test -f" in bundle.commands_run[0].command
    assert bundle.test_results[0].status == "passed"
    assert bundle.real_frontend_path_exercised is False
    assert bundle.next_recommendation == "proceed"
    assert bundle.outcome == "verified_fix"


def test_classification_distinguishes_required_phase4_outcomes() -> None:
    module = _load_module()
    outcomes = []

    for spec in module.demo_specs("phase4-test"):
        bundle = module.EvidenceBundle.model_validate(spec)
        outcome, notes = module.classify_bundle(bundle)
        outcomes.append(outcome)
        assert notes == []

    assert outcomes == ["verified_fix", "bug_not_reproduced", "environment_blocked"]


def test_environment_blocked_cannot_claim_real_path_execution() -> None:
    module = _load_module()
    spec = module.demo_specs("phase4-test")[2] | {"real_frontend_path_exercised": True}
    bundle = module.EvidenceBundle.model_validate(spec)

    outcome, notes = module.classify_bundle(bundle)

    assert outcome == "needs_revision"
    assert any("cannot claim real-path execution" in note for note in notes)


def test_local_routine_writes_parseable_bundle(tmp_path: Path) -> None:
    module = _load_module()
    feature = "phase4-test"
    spec = module.demo_specs(feature)[1]
    routine = module.routine_for_bundle(spec, feature)

    evidence_path, execution_notes = module.execute_routine(
        routine,
        feature=feature,
        local_worktree=tmp_path,
        expected_evidence_name="slice-02-bug-not-reproduced-evidence.json",
    )
    bundle, outcome, evaluation_notes = module.load_and_evaluate_bundle(evidence_path)

    assert evidence_path.name == "slice-02-bug-not-reproduced-evidence.json"
    assert bundle is not None
    assert bundle.target_bug_reproduced == "not_reproduced"
    assert outcome == "bug_not_reproduced"
    assert evaluation_notes == []
    assert any("elapsed" in note for note in execution_notes)


def test_success_criteria_require_all_standard_outcomes() -> None:
    module = _load_module()
    records = []
    for index, spec in enumerate(module.demo_specs("phase4-test"), start=1):
        bundle = module.EvidenceBundle.model_validate(spec)
        outcome, notes = module.classify_bundle(bundle)
        records.append(
            module.SliceResult(
                slice_id=bundle.slice_id,
                routine_id=bundle.routine_id,
                routine_path=f"slice-{index:02d}.yaml",
                validation=module.RoutineValidation(status="valid", errors=[]),
                evidence_path=f"slice-{index:02d}.json",
                bundle=bundle.model_dump(),
                outcome=outcome,
                valid_bundle=not notes,
                evaluation_notes=notes,
            )
        )

    orchestrator_execution = module.OrchestratorExecutionEvidence(
        run_id="run-1",
        status="completed",
        pause_reason=None,
        worktree_path="/tmp/worktree",
        evidence_files=["docs/phase4-test/slice-01-verified-fix-evidence.json"],
        activity_events=4,
        notes=[],
    )
    criteria = module.compute_success_criteria(records, orchestrator_execution)

    assert criteria["every_bundle_valid"] is True
    assert criteria["verified_fix_distinguishable"] is True
    assert criteria["bug_not_reproduced_distinguishable"] is True
    assert criteria["environment_blocked_distinguishable"] is True
    assert criteria["orchestrator_validation_passed"] is True
    assert criteria["orchestrator_execution_completed"] is True
    assert criteria["ready_for_phase5"] is True


def test_success_criteria_do_not_pass_when_api_validation_is_unavailable() -> None:
    module = _load_module()
    spec = module.demo_specs("phase4-test")[0]
    bundle = module.EvidenceBundle.model_validate(spec)
    outcome, notes = module.classify_bundle(bundle)
    criteria = module.compute_success_criteria(
        [
            module.SliceResult(
                slice_id=bundle.slice_id,
                routine_id=bundle.routine_id,
                routine_path="slice-01.yaml",
                validation=module.RoutineValidation(status="api_unavailable", errors=["down"]),
                evidence_path="slice-01.json",
                bundle=bundle.model_dump(),
                outcome=outcome,
                valid_bundle=not notes,
                evaluation_notes=notes,
            )
        ],
        module.OrchestratorExecutionEvidence(
            run_id="run-1",
            status="completed",
            pause_reason=None,
            worktree_path="/tmp/worktree",
            evidence_files=["docs/phase4-test/slice-01-verified-fix-evidence.json"],
            activity_events=4,
            notes=[],
        ),
    )

    assert criteria["orchestrator_validation_passed"] is False
    assert criteria["ready_for_phase5"] is False


def test_success_criteria_do_not_pass_without_completed_orchestrator_execution() -> None:
    module = _load_module()
    spec = module.demo_specs("phase4-test")[0]
    bundle = module.EvidenceBundle.model_validate(spec)
    outcome, notes = module.classify_bundle(bundle)
    criteria = module.compute_success_criteria(
        [
            module.SliceResult(
                slice_id=bundle.slice_id,
                routine_id=bundle.routine_id,
                routine_path="slice-01.yaml",
                validation=module.RoutineValidation(status="valid", errors=[]),
                evidence_path="slice-01.json",
                bundle=bundle.model_dump(),
                outcome=outcome,
                valid_bundle=not notes,
                evaluation_notes=notes,
            )
        ],
        module.OrchestratorExecutionEvidence(
            run_id="run-1",
            status="paused",
            pause_reason="no_executor_running",
            worktree_path="/tmp/worktree",
            evidence_files=[],
            activity_events=2,
            notes=["No evidence bundle was produced in the orchestrator worktree."],
        ),
    )

    assert criteria["orchestrator_execution_completed"] is False
    assert criteria["ready_for_phase5"] is False


def test_script_help_is_available() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    assert "--schema-doc" in completed.stdout
    assert "--local-worktree" in completed.stdout
    assert "--orchestrator-run-json" in completed.stdout
