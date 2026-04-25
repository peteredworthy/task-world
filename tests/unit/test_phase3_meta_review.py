"""Unit coverage for the phase-3 meta-review coordinator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "run_phase3_meta_review.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("phase3_meta_review", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_demo_review_requires_revision_for_broad_candidate() -> None:
    module = _load_module()
    routine = module.demo_candidate(1, "phase3-test", None)

    review = module.demo_meta_review(review_number=1, routine=routine)

    assert review.decision == "revise"
    assert review.incremental_score == 1
    assert review.dead_code_risk_score == 1
    assert any("multiple executable tasks" in finding for finding in review.findings)
    assert any("one executable task" in change for change in review.required_changes)


def test_revised_candidate_is_approved_and_covers_review_dimensions() -> None:
    module = _load_module()
    first_review = module.demo_meta_review(
        review_number=1,
        routine=module.demo_candidate(1, "phase3-test", None),
    )
    routine = module.demo_candidate(2, "phase3-test", first_review)

    review = module.demo_meta_review(review_number=2, routine=routine)

    assert review.decision == "approve"
    assert review.incremental_score == 5
    assert review.real_surface_score == 5
    assert review.dead_code_risk_score == 5
    assert review.bug_absent_detection is True


def test_success_criteria_require_block_then_approved_execution() -> None:
    module = _load_module()
    broad = module.demo_candidate(1, "phase3-test", None)
    first_review = module.demo_meta_review(review_number=1, routine=broad)
    revised = module.demo_candidate(2, "phase3-test", first_review)
    second_review = module.demo_meta_review(review_number=2, routine=revised)
    candidates = [
        module.CandidateRecord(
            review_number=1,
            routine_id=broad["id"],
            routine_path="candidate-01.yaml",
            task_count=module.count_tasks(broad),
            validation_errors=[],
            review=first_review,
        ),
        module.CandidateRecord(
            review_number=2,
            routine_id=revised["id"],
            routine_path="candidate-02.yaml",
            task_count=module.count_tasks(revised),
            validation_errors=[],
            review=second_review,
        ),
    ]
    execution = module.ExecutionEvidence(
        routine_id=revised["id"],
        status="completed",
        worktree_path="/tmp/phase3",
        evidence_files=["docs/phase3-test/approved-slice-evidence.txt"],
        elapsed_seconds=0,
        notes=[],
    )
    post_review = module.demo_meta_review(
        review_number=3,
        routine=revised,
        execution=execution,
    )

    criteria = module.compute_success_criteria(candidates, execution, post_review)

    assert criteria["review_rejected_broad_candidate"] is True
    assert criteria["approved_only_after_revision"] is True
    assert criteria["executed_only_approved_candidate"] is True
    assert criteria["planner_tuning_emitted"] is True
    assert criteria["ready_for_phase4"] is True


def test_external_json_command_protocol(tmp_path: Path) -> None:
    module = _load_module()
    command = tmp_path / "reviewer.py"
    command.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "json.dump({'decision': 'approve', 'findings': [str(payload['review_number'])], "
        "'required_changes': [], 'planner_tuning': [], 'incremental_score': 5, "
        "'real_surface_score': 5, 'dead_code_risk_score': 5, "
        "'bug_absent_detection': True}, sys.stdout)\n"
    )

    response = module.run_json_command(
        f"{sys.executable} {command}",
        {"review_number": 4},
        timeout=10,
    )
    review = module.review_from_response(response, 4)

    assert review.decision == "approve"
    assert review.findings == ["4"]
    assert review.bug_absent_detection is True


def test_script_help_is_available() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    assert "--reviewer-command" in completed.stdout
    assert "--demo" in completed.stdout
