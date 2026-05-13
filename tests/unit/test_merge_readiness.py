"""Pure merge-readiness gate evaluation tests."""

import pytest

from orchestrator.api import evaluate_merge_readiness_gates


def _gate_statuses(**overrides: object) -> dict[str, str]:
    params = {
        "source_branch_configured": True,
        "can_merge_cleanly": True,
        "predicted_conflict_count": 0,
        "worktree_available": True,
        "unresolved_conflict_count": 0,
        "auto_verify_configured": False,
        "tests_running": False,
        "last_test_status": None,
        "agent_running": False,
    }
    params.update(overrides)
    readiness = evaluate_merge_readiness_gates(**params)  # type: ignore[arg-type]
    return {gate.name: gate.status for gate in readiness.gates}


def test_merge_readiness_all_pass() -> None:
    readiness = evaluate_merge_readiness_gates(
        source_branch_configured=True,
        can_merge_cleanly=True,
        predicted_conflict_count=0,
        worktree_available=True,
        unresolved_conflict_count=0,
        auto_verify_configured=False,
        tests_running=False,
        last_test_status=None,
        agent_running=False,
    )

    assert readiness.ready is True
    assert {gate.name: gate.status for gate in readiness.gates} == {
        "clean_merge": "pass",
        "no_unresolved_conflicts": "pass",
        "tests_pass": "pass",
        "no_active_jobs": "pass",
    }


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"source_branch_configured": False}, "pending"),
        ({"can_merge_cleanly": None}, "pending"),
        ({"can_merge_cleanly": False, "predicted_conflict_count": 2}, "fail"),
    ],
)
def test_clean_merge_gate(overrides: dict[str, object], expected_status: str) -> None:
    assert _gate_statuses(**overrides)["clean_merge"] == expected_status


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"worktree_available": False}, "pending"),
        ({"unresolved_conflict_count": None}, "pending"),
        ({"unresolved_conflict_count": 3}, "fail"),
    ],
)
def test_unresolved_conflicts_gate(overrides: dict[str, object], expected_status: str) -> None:
    assert _gate_statuses(**overrides)["no_unresolved_conflicts"] == expected_status


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"auto_verify_configured": False}, "pass"),
        ({"auto_verify_configured": True, "tests_running": True}, "pending"),
        ({"auto_verify_configured": True, "last_test_status": None}, "pending"),
        ({"auto_verify_configured": True, "last_test_status": "passed"}, "pass"),
        ({"auto_verify_configured": True, "last_test_status": "failed"}, "fail"),
        ({"auto_verify_configured": True, "last_test_status": "error"}, "fail"),
    ],
)
def test_tests_pass_gate(overrides: dict[str, object], expected_status: str) -> None:
    assert _gate_statuses(**overrides)["tests_pass"] == expected_status


@pytest.mark.parametrize(
    ("overrides", "expected_description"),
    [
        ({"agent_running": True}, "Active jobs: agent job"),
        ({"tests_running": True}, "Active jobs: test job"),
        ({"agent_running": True, "tests_running": True}, "Active jobs: agent job, test job"),
    ],
)
def test_active_jobs_gate_fails(overrides: dict[str, object], expected_description: str) -> None:
    params = {
        "source_branch_configured": True,
        "can_merge_cleanly": True,
        "predicted_conflict_count": 0,
        "worktree_available": True,
        "unresolved_conflict_count": 0,
        "auto_verify_configured": False,
        "tests_running": False,
        "last_test_status": None,
        "agent_running": False,
    }
    params.update(overrides)
    readiness = evaluate_merge_readiness_gates(**params)  # type: ignore[arg-type]

    gate = next(gate for gate in readiness.gates if gate.name == "no_active_jobs")
    assert gate.status == "fail"
    assert gate.description == expected_description
    assert readiness.ready is False
