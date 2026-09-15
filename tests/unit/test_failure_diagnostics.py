"""Behavioral contract for Slice 5A failure classification."""

from __future__ import annotations

from typing import Any, cast

import pytest

from orchestrator.config import FailureDiagnostic
from orchestrator.graph import boundary_manifest_hash, build_projection
from orchestrator.graph_runtime import (
    DecisionBindingConflictError,
    StaleProjectionError,
    SubmissionGateCommandResult,
    SubmissionQualityGateError,
    classify_failure,
    require_replayed_decision_receipt_before_retry,
)
from orchestrator.runners import (
    AgentExecutionError,
    SubmissionAcknowledgement,
    SubmissionRejectedError,
    SubmissionRejectionEvidence,
    SubmissionRepairExhaustedError,
    submission_rejection_requires_stop,
)
from orchestrator.workflow import AgentErrorEvent
from tests.unit.graph_test_utils import event as graph_event


def _gate_result(category: str) -> SubmissionGateCommandResult:
    return SubmissionGateCommandResult(
        run_id="run-1",
        node_id="node-1",
        execution_id="execution-1",
        command="uv run pytest",
        command_sha256="a" * 64,
        source="routine",
        status="failed",
        exit_code=1,
        duration_ms=12,
        stdout_tail="failed",
        stderr_tail="",
        stdout_sha256="b" * 64,
        stderr_sha256="c" * 64,
        stdout_bytes=6,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        failure_category=category,
    )


@pytest.mark.parametrize(
    ("error", "category", "next_action", "correction_allowed"),
    [
        (ValueError("bad answer shape"), "answer_validation", "correct_answer", True),
        (StaleProjectionError("stale binding"), "stale_binding", "refresh_binding", False),
        (
            DecisionBindingConflictError("bound authority changed"),
            "stale_binding",
            "refresh_binding",
            False,
        ),
        (
            SubmissionQualityGateError(
                "candidate failed",
                report=_gate_result("candidate_check_failure"),
            ),
            "candidate_check",
            "correct_candidate",
            True,
        ),
        (
            SubmissionQualityGateError(
                "environment blocked",
                report=_gate_result("validation_environment_blockage"),
            ),
            "infrastructure_environment",
            "resolve_environment",
            False,
        ),
        (
            AgentExecutionError("cli_subprocess", "process failed"),
            "execution",
            "retry_or_recover",
            False,
        ),
        (
            SubmissionRepairExhaustedError("codex_server", "first", "last"),
            "budget_exhaustion",
            "stop",
            False,
        ),
    ],
)
def test_classify_failure_has_distinct_actionable_paths(
    error: Exception,
    category: str,
    next_action: str,
    correction_allowed: bool,
) -> None:
    diagnostic = classify_failure(error, protected_evidence_refs=("graph-event:run-1:7",))

    assert diagnostic.category == category
    assert diagnostic.next_action == next_action
    assert diagnostic.correction_allowed is correction_allowed
    assert diagnostic.protected_evidence_refs == ("graph-event:run-1:7",)
    assert diagnostic.message


def test_submission_rejection_preserves_typed_diagnostic() -> None:
    acknowledgement = SubmissionAcknowledgement(
        disposition="rejected",
        message="validation environment blocked",
        rejection_category="validation_environment_blocked",
        rejection_evidence=SubmissionRejectionEvidence(
            category="validation_environment_blocked",
            final_diagnostic="environment unavailable",
            durable_audit_reference="graph-event:run-1:9",
        ),
        failure_diagnostic=FailureDiagnostic(
            category="infrastructure_environment",
            code="validation_environment_blocked",
            message="The validation environment is unavailable or blocked.",
            next_action="resolve_environment",
            correction_allowed=False,
            protected_evidence_refs=("graph-event:run-1:9",),
        ),
    )

    diagnostic = classify_failure(SubmissionRejectedError(acknowledgement))

    assert diagnostic.category == "infrastructure_environment"
    assert diagnostic.next_action == "resolve_environment"
    assert diagnostic.correction_allowed is False


def test_failure_diagnostic_rejects_unprotected_evidence_reference() -> None:
    with pytest.raises(ValueError, match="protected evidence"):
        FailureDiagnostic(
            category="execution",
            code="runner_failed",
            message="runner failed",
            next_action="retry_or_recover",
            correction_allowed=False,
            protected_evidence_refs=("raw-output",),
        )


def test_environment_rejection_is_terminal_for_codex_correction_loop() -> None:
    environment_rejection = SubmissionRejectedError(
        SubmissionAcknowledgement(
            disposition="rejected",
            message="environment blocked",
            rejection_category="validation_environment_blocked",
        )
    )
    candidate_rejection = SubmissionRejectedError(
        SubmissionAcknowledgement(
            disposition="rejected",
            message="candidate failed",
            rejection_category="candidate_check_failed",
        )
    )

    assert submission_rejection_requires_stop(environment_rejection.acknowledgement) is True
    assert submission_rejection_requires_stop(candidate_rejection.acknowledgement) is False


def test_agent_error_event_round_trips_failure_diagnostic() -> None:
    event = AgentErrorEvent(
        run_id="run-1",
        error_type="AgentExecutionError",
        error_message="runner failed",
        failure_diagnostic=FailureDiagnostic(
            category="execution",
            code="runner_execution_failed",
            message="The runner did not complete the execution.",
            next_action="retry_or_recover",
            correction_allowed=False,
        ),
    )

    restored = AgentErrorEvent.model_validate_json(event.model_dump_json())

    assert restored.failure_diagnostic == event.failure_diagnostic


@pytest.mark.asyncio
async def test_decision_retry_preflight_rejects_missing_protected_receipt() -> None:
    tree_sha = "a" * 40
    events = [
        graph_event(
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "state": "running"},
            position=1,
        ),
        graph_event(
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "planner-1",
                "generation": 1,
                "execution_id": "execution-1",
                "base_snapshot_id": "snapshot-1",
            },
            position=2,
        ),
        graph_event(
            "runner_baseline_recorded",
            {
                "execution_id": "execution-1",
                "node_id": "planner-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "baseline_snapshot_id": "snapshot-1",
                "baseline_tree_sha": tree_sha,
                "entries": [],
                "boundary_hash": boundary_manifest_hash(tree_sha, []),
                "cache_roots": [],
            },
            position=3,
        ),
        graph_event(
            "decision_answer_rejected",
            {
                "execution_id": "execution-1",
                "node_id": "planner-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "answer_attempt_id": "answer-1",
                "delivery_id": "a" * 64,
                "transport_channel": "test",
                "transport_session_id": "session-1",
                "transport_request_id": "request-1",
                "failure_diagnostic": FailureDiagnostic(
                    category="answer_validation",
                    code="submission_format_rejected",
                    message="The submitted answer is invalid.",
                    next_action="correct_answer",
                    correction_allowed=True,
                ).model_dump(mode="json"),
            },
            position=4,
        ),
    ]

    with pytest.raises(
        ValueError,
        match="decision retry requires a protected rejected-answer receipt",
    ):
        await require_replayed_decision_receipt_before_retry(
            projection=build_projection(events),
            node_id="planner-1",
            execution_id="execution-2",
            artifact_store=cast(Any, object()),
            authorization_session_factory=cast(Any, object()),
            isolated_session_factory=cast(Any, object()),
            run_id="run-1",
            worktree_path="/unused",
            clock=cast(Any, object()),
            id_gen=cast(Any, object()),
        )
