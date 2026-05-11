from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "run_child_evidence.py"


def _run_helper(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )


def test_run_child_evidence_writes_bundle_and_command_logs(tmp_path: Path) -> None:
    result = _run_helper(
        tmp_path,
        "--slice-id",
        "slice-1",
        "--routine-id",
        "child-slice-1",
        "--assumption",
        "The verification command passes.",
        "--real-execution-surface",
        "unit smoke",
        "--command",
        "smoke::printf 'hello\\n'",
    )

    assert result.returncode == 0, result.stderr
    evidence_path = tmp_path / "docs" / "run-evidence" / "slice-1-evidence.json"
    bundle = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert bundle["schema_version"] == "run.evidence.v1"
    assert bundle["slice_id"] == "slice-1"
    assert bundle["routine_id"] == "child-slice-1"
    assert bundle["outcome"] == "verified_fix"
    assert bundle["next_recommendation"] == "proceed"
    assert bundle["commands_run"][0]["exit_code"] == 0
    assert "hello" in bundle["commands_run"][0]["stdout_excerpt"]
    assert bundle["test_results"][0]["status"] == "passed"
    assert ".evidence/smoke.log" in bundle["evidence_files"]
    assert (tmp_path / ".evidence" / "smoke.log").is_file()


def test_run_child_evidence_keeps_valid_bundle_when_command_fails(tmp_path: Path) -> None:
    result = _run_helper(
        tmp_path,
        "--slice-id",
        "slice-2",
        "--routine-id",
        "child-slice-2",
        "--failure-outcome",
        "environment_blocked",
        "--failure-next-recommendation",
        "environment_blocked",
        "--command",
        "blocked::printf 'missing tool\\n' >&2; exit 7",
    )

    assert result.returncode == 1
    evidence_path = tmp_path / "docs" / "run-evidence" / "slice-2-evidence.json"
    bundle = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert bundle["schema_version"] == "run.evidence.v1"
    assert bundle["outcome"] == "environment_blocked"
    assert bundle["next_recommendation"] == "environment_blocked"
    assert bundle["commands_run"][0]["exit_code"] == 7
    assert "missing tool" in bundle["commands_run"][0]["stderr_excerpt"]
    assert bundle["test_results"][0]["status"] == "failed"
    assert "One or more verification commands failed." in bundle["open_uncertainties"]
