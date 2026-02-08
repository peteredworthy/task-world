"""Integration test: load routine from YAML, create run, verify structure."""

from pathlib import Path

from orchestrator.config.enums import RoutineSource, RunStatus
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.factory import create_run_from_routine

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


def test_create_run_from_loaded_routine() -> None:
    """Integration: Load routine from file, create run."""
    routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")

    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
        config={"feature_name": "authentication"},
        routine_source=RoutineSource.LOCAL,
    )

    assert run.routine_id == "complete-routine"
    assert run.status == RunStatus.DRAFT
    assert run.config["feature_name"] == "authentication"

    # Verify structure
    assert len(run.steps) == 2
    task = run.steps[0].tasks[0]
    assert task.config_id == "T-01"
    assert len(task.checklist) == 2  # R1 and R2 from fixture
    assert task.max_attempts == 3  # From retry config

    # Step 2 has two tasks
    assert len(run.steps[1].tasks) == 2
    assert run.steps[1].tasks[0].config_id == "T-02"
    assert run.steps[1].tasks[0].max_attempts == 2
    assert run.steps[1].tasks[1].config_id == "T-03"
