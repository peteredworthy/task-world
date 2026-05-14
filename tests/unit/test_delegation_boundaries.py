"""Architecture checks for delegated-state write boundaries."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_delegation_boundary_checker_passes_for_source_tree() -> None:
    project_root = Path(__file__).parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_delegation_boundaries.py",
            "src/orchestrator",
            "scripts",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_delegation_boundary_checker_rejects_broad_oversight_assignment(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).parents[2]
    bad_file = tmp_path / "bad_assignment.py"
    bad_file.write_text(
        """
def accidental_service_write(run):
    run.oversight_state = {"delegation_results": []}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_delegation_boundaries.py",
            str(bad_file),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "run.oversight_state assignments may only occur" in result.stderr


def test_delegation_boundary_checker_rejects_keyword_coordination_update(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).parents[2]
    bad_file = tmp_path / "bad_update.py"
    bad_file.write_text(
        """
def accidental_update(state):
    state.update(delegation_results=[{"work_id": "child"}])
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_delegation_boundaries.py",
            str(bad_file),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "coordination JSON keys may only be updated" in result.stderr


def test_delegation_boundary_checker_uses_workflow_owned_coordination_keys(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).parents[2]
    bad_file = tmp_path / "bad_owner_token.py"
    bad_file.write_text(
        """
def accidental_owner_token_write(state):
    state["delegation_owner_token"] = "new-owner"
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_delegation_boundaries.py",
            str(bad_file),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "coordination JSON keys may only be assigned" in result.stderr
