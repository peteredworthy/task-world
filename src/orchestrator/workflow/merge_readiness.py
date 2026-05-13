"""Pure merge-readiness gate evaluation."""

from pydantic import BaseModel


class Gate(BaseModel):
    """A single readiness gate with pass/fail/pending status."""

    name: str
    status: str
    description: str


class MergeReadiness(BaseModel):
    """Aggregate merge readiness computed from all gates."""

    ready: bool
    gates: list[Gate]


def evaluate_merge_readiness_gates(
    *,
    source_branch_configured: bool,
    can_merge_cleanly: bool | None,
    predicted_conflict_count: int,
    worktree_available: bool,
    unresolved_conflict_count: int | None,
    auto_verify_configured: bool,
    tests_running: bool,
    last_test_status: str | None,
    agent_running: bool,
) -> MergeReadiness:
    """Evaluate merge-readiness gates from already-collected facts."""
    gates: list[Gate] = []

    if not source_branch_configured:
        gates.append(
            Gate(
                name="clean_merge",
                status="pending",
                description="No source branch configured",
            )
        )
    elif can_merge_cleanly is None:
        gates.append(
            Gate(
                name="clean_merge",
                status="pending",
                description="Unable to compute merge prediction",
            )
        )
    elif can_merge_cleanly:
        gates.append(
            Gate(
                name="clean_merge",
                status="pass",
                description="Merge prediction is clean",
            )
        )
    else:
        gates.append(
            Gate(
                name="clean_merge",
                status="fail",
                description=f"Merge conflicts predicted in {predicted_conflict_count} file(s)",
            )
        )

    if not worktree_available:
        gates.append(
            Gate(
                name="no_unresolved_conflicts",
                status="pending",
                description="Worktree not available",
            )
        )
    elif unresolved_conflict_count is None:
        gates.append(
            Gate(
                name="no_unresolved_conflicts",
                status="pending",
                description="Unable to check conflict status",
            )
        )
    elif unresolved_conflict_count == 0:
        gates.append(
            Gate(
                name="no_unresolved_conflicts",
                status="pass",
                description="No unresolved merge conflicts",
            )
        )
    else:
        gates.append(
            Gate(
                name="no_unresolved_conflicts",
                status="fail",
                description=f"{unresolved_conflict_count} file(s) have unresolved merge conflicts",
            )
        )

    if not auto_verify_configured:
        gates.append(
            Gate(
                name="tests_pass",
                status="pass",
                description="No tests configured",
            )
        )
    elif tests_running:
        gates.append(
            Gate(
                name="tests_pass",
                status="pending",
                description="Test run is in progress",
            )
        )
    elif last_test_status is None:
        gates.append(
            Gate(
                name="tests_pass",
                status="pending",
                description="No test run recorded yet",
            )
        )
    elif last_test_status == "passed":
        gates.append(
            Gate(
                name="tests_pass",
                status="pass",
                description="Most recent test run passed",
            )
        )
    else:
        gates.append(
            Gate(
                name="tests_pass",
                status="fail",
                description=f"Most recent test run {last_test_status}",
            )
        )

    if agent_running or tests_running:
        reasons: list[str] = []
        if agent_running:
            reasons.append("agent job")
        if tests_running:
            reasons.append("test job")
        gates.append(
            Gate(
                name="no_active_jobs",
                status="fail",
                description=f"Active jobs: {', '.join(reasons)}",
            )
        )
    else:
        gates.append(
            Gate(
                name="no_active_jobs",
                status="pass",
                description="No active agent or test jobs",
            )
        )

    return MergeReadiness(ready=all(g.status == "pass" for g in gates), gates=gates)


__all__ = ["Gate", "MergeReadiness", "evaluate_merge_readiness_gates"]
