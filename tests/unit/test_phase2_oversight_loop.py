"""Unit coverage for the phase-2 external oversight coordinator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "run_phase2_oversight_loop.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("phase2_oversight_loop", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_demo_planner_changes_second_slice_focus() -> None:
    module = _load_module()

    first = module.demo_planner(1, "phase2-test", None)
    first_evidence = module.SliceEvidence(
        slice_number=1,
        run_id="run-1",
        routine_path="slice-01.yaml",
        status="completed",
        pause_reason=None,
        last_error=None,
        worktree_path="/tmp/worktree",
        elapsed_seconds=1,
        activity_events=3,
        completed_tasks=1,
        total_tasks=1,
        changed_files=["docs/phase2-test/slice-01-evidence.txt"],
        evidence_files=["docs/phase2-test/slice-01-evidence.txt"],
        notes=[],
    )
    first_record = module.SliceRecord(
        slice_number=1,
        planner_source="built-in-demo",
        routine_id=first["id"],
        routine_path="slice-01.yaml",
        validation_errors=[],
        evidence=first_evidence,
        evaluation=module.demo_evaluator(first_evidence, None),
    )

    second = module.demo_planner(2, "phase2-test", first_record)

    assert first["id"] != second["id"]
    first_requirement = first["steps"][0]["tasks"][0]["requirements"][0]["desc"]
    second_requirement = second["steps"][0]["tasks"][0]["requirements"][0]["desc"]
    assert "first bounded slice" in first_requirement
    assert "replan after inspecting concrete slice evidence" in second_requirement


def test_success_criteria_require_second_slice_after_review() -> None:
    module = _load_module()

    first_evidence = module.SliceEvidence(
        slice_number=1,
        run_id="run-1",
        routine_path="slice-01.yaml",
        status="completed",
        pause_reason=None,
        last_error=None,
        worktree_path="/tmp/worktree",
        elapsed_seconds=1,
        activity_events=3,
        completed_tasks=1,
        total_tasks=1,
        changed_files=["docs/phase2-test/slice-01-evidence.txt"],
        evidence_files=["docs/phase2-test/slice-01-evidence.txt"],
        notes=[],
    )
    second_evidence = module.SliceEvidence(
        slice_number=2,
        run_id="run-2",
        routine_path="slice-02.yaml",
        status="completed",
        pause_reason=None,
        last_error=None,
        worktree_path="/tmp/worktree2",
        elapsed_seconds=1,
        activity_events=3,
        completed_tasks=1,
        total_tasks=1,
        changed_files=["docs/phase2-test/slice-02-evidence.txt"],
        evidence_files=["docs/phase2-test/slice-02-evidence.txt"],
        notes=[],
    )
    records = [
        module.SliceRecord(
            slice_number=1,
            planner_source="built-in-demo",
            routine_id="phase2-oversight-slice-01",
            routine_path="slice-01.yaml",
            validation_errors=[],
            evidence=first_evidence,
            evaluation=module.SliceEvaluation(
                decision="continue",
                reason="continue from evidence",
                next_focus="second slice",
                material_difference_basis="second changes focus",
                usable_evidence=True,
            ),
        ),
        module.SliceRecord(
            slice_number=2,
            planner_source="built-in-demo",
            routine_id="phase2-oversight-slice-02",
            routine_path="slice-02.yaml",
            validation_errors=[],
            evidence=second_evidence,
            evaluation=module.SliceEvaluation(
                decision="stop",
                reason="ready for phase 4",
                next_focus=None,
                material_difference_basis="second changes focus",
                usable_evidence=True,
            ),
        ),
    ]

    criteria = module.compute_success_criteria(records)

    assert criteria["second_slice_after_review"] is True
    assert criteria["second_slice_materially_different"] is True
    assert criteria["no_pre_authored_full_plan"] is True
    assert criteria["ready_for_phase4"] is True


def test_external_json_command_protocol(tmp_path: Path) -> None:
    module = _load_module()
    command = tmp_path / "planner.py"
    command.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "json.dump({'routine': {'id': 'slice-' + str(payload['slice_number'])}}, sys.stdout)\n"
    )

    result = module.run_json_command(
        f"{sys.executable} {command}",
        {"slice_number": 7},
        timeout=10,
    )

    assert result == {"routine": {"id": "slice-7"}}


def test_script_help_is_available() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    assert "--planner-command" in completed.stdout
    assert "--demo" in completed.stdout
