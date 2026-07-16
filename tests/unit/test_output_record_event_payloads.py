import pytest
from pydantic import ValidationError

from typing import Any, get_args

from orchestrator.graph import (
    OUTPUT_RECORD_MODELS_BY_TYPE,
    AcceptedOutputRecordPayload,
    OutputRecordAcceptedPayload,
)


CANONICAL_RECORD = {
    "record_id": "candidate-record-1",
    "record_kind": "output",
    "record_type": "candidate",
    "producer_node_id": "worker-1",
    "port": "candidate",
    "schema": "ImplementationCandidate",
    "candidate_id": "candidate-1",
    "value": {"summary": "Implemented the requested change"},
}


def test_output_record_event_uses_a_typed_record() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(CANONICAL_RECORD)

    assert payload.root.record_id == CANONICAL_RECORD["record_id"]


def test_output_record_event_rejects_unknown_record_fields() -> None:
    with pytest.raises(ValidationError):
        OutputRecordAcceptedPayload.model_validate({**CANONICAL_RECORD, "legacy_value": "old"})


def _check_value() -> dict[str, Any]:
    return {
        "status": "passed",
        "classification": "passed",
        "command_id": "pytest",
        "command_binding": {"kind": "known", "id": "unit"},
        "command_text": "uv run pytest",
        "command": {"id": "pytest", "argv": ["uv", "run", "pytest"]},
        "worktree_path": "/tmp/worktree",
        "base_snapshot_id": "S0",
        "execution_id": "exec-1",
        "exit_code": 0,
        "duration_ms": 1,
        "stdout": "ok",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 30,
        "environment_policy": {"cwd": "/tmp/worktree", "env": "inherited", "shell": False},
    }


def _record_cases() -> dict[str, dict[str, Any]]:
    common = {"record_kind": "output", "producer_node_id": "node-1"}
    gap_value = {
        "milestone_kind": "gap_analysis",
        "classification": "corrective_work_required",
        "source": "accepted_gap_planner_patch",
        "task_region_id": "task-1",
        "attempt_number": 1,
    }
    return {
        "analysis_summary": {
            **common,
            "record_id": "summary-1",
            "record_type": "analysis_summary",
            "port": "analysis_summary",
            "schema": "AnalysisSummary",
            "value": {
                "summary": "condensed",
                "source_record_ids": [],
                "lossy": False,
                "omitted_details": [],
            },
        },
        "artifact_reference": {
            "record_id": "artifact-1",
            "record_kind": "graph_record",
            "record_type": "artifact_reference",
            "producer_node_id": "node-1",
            "port": "artifact",
            "schema": "ContextArtifact",
            "value": {"artifact_id": "spec", "artifact_type": "context", "uri": "docs/spec.md"},
        },
        "authority_decision": {
            **common,
            "record_id": "authority-1",
            "record_type": "authority_decision",
            "port": "authority_decision",
            "schema": "AuthorityDecision",
            "value": {
                "decision": "granted",
                "decision_type": "authority",
                "decider": {"kind": "human", "id": "alice"},
            },
        },
        "authority_request_record": {
            "record_id": "authority-request-1",
            "record_kind": "graph_record",
            "record_type": "authority_request_record",
            "producer_node_id": "node-1",
            "port": "authority_request_record",
            "schema": "AuthorityRequest",
            "value": {
                "requested_authority": ["graph_write"],
                "target_region_id": "region-1",
                "reason": "corrective work required",
            },
        },
        "candidate": CANONICAL_RECORD,
        "check_result": {
            **common,
            "record_id": "check-1",
            "record_type": "check_result",
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": "candidate-1",
            "task_region_id": "task-1",
            "attempt_number": 1,
            "value": _check_value(),
        },
        **{
            record_type: {
                **common,
                "record_id": f"{record_type}-1",
                "record_type": record_type,
                "port": record_type,
                "schema": "GapClassification",
                "value": gap_value,
            }
            for record_type in ("classified_gap", "gap_classification", "gap_plan")
        },
        "completion_decision": {
            **common,
            "record_id": "completion-1",
            "record_type": "completion_decision",
            "port": "completion_decision",
            "schema": "CompletionDecision",
            "value": {"status": "passed", "blockers": []},
        },
        "decision_record": {
            **common,
            "record_id": "decision-1",
            "record_type": "decision_record",
            "port": "decision_record",
            "schema": "DecisionRecord",
            "value": {
                "decision": "approved",
                "decision_type": "approval",
                "decider": {"kind": "human", "id": "alice"},
            },
        },
        "decision_request": {
            "record_id": "request-1",
            "record_kind": "graph_record",
            "record_type": "decision_request",
            "producer_node_id": "node-1",
            "port": "decision_request",
            "schema": "DecisionRequest",
            "value": {
                "decision_type": "approval",
                "options": ["approved", "rejected"],
                "consequence_summary": "Approval releases the worker.",
            },
        },
        "failure_record": {
            "record_id": "failure-1",
            "record_kind": "graph_record",
            "record_type": "failure_record",
            "producer_node_id": "runtime",
            "port": "failure_record",
            "schema": "FailureRecord",
            "value": {
                "failed_node_id": "node-1",
                "phase": "agent_execution",
                "error_class": "lease_expired",
                "retryable": True,
            },
        },
        "fan_out_inputs": {
            **common,
            "record_id": "fan-out-1",
            "record_type": "fan_out_inputs",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "value": {"summary": "fan out"},
        },
        "file_state": {
            "record_id": "file-state-1",
            "record_kind": "file_state",
            "record_type": "file_state",
            "producer_node_id": "node-1",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": "S1",
        },
        "graph_patch_proposal": {
            **common,
            "record_id": "patch-1",
            "record_type": "graph_patch_proposal",
            "port": "graph_patch_proposal",
            "schema": "GraphPatch",
            "value": {
                "patch_id": "patch-1",
                "proposed_by_node_id": "node-1",
                "base_graph_position": 1,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {"node_id": "worker-1", "kind": "worker", "role": "builder"},
                    }
                ],
            },
        },
        "join_result": {
            **common,
            "record_id": "join-1",
            "record_type": "join_result",
            "port": "join_result",
            "schema": "JoinResult",
            "value": {"status": "ready", "source_record_ids": []},
        },
        "recovery_plan": {
            **common,
            "record_id": "recovery-1",
            "record_type": "recovery_plan",
            "port": "recovery_plan",
            "schema": "RecoveryPlan",
            "value": {
                "action": "retry",
                "responsible_actor": "controller",
                "graph_changes": [],
            },
        },
        "requirement_record": {
            "record_id": "requirement-1",
            "record_kind": "graph_record",
            "record_type": "requirement_record",
            "producer_node_id": "requirement-1",
            "port": "requirement",
            "schema": "RequirementRecord",
            "value": {"id": "R-1", "text": "Must pass"},
        },
        "routine_snapshot": {
            "record_id": "routine-1",
            "record_kind": "graph_record",
            "record_type": "routine_snapshot",
            "producer_node_id": "routine-snapshot",
            "port": "snapshot",
            "schema": "RoutineSnapshot",
            "value": {
                "routine_id": "routine-1",
                "name": "Routine",
                "content_hash": "abc",
                "step_count": 1,
                "task_count": 1,
            },
        },
        "run_context": {
            "record_id": "context-1",
            "record_kind": "graph_record",
            "record_type": "run_context",
            "producer_node_id": "root",
            "port": "run_context",
            "schema": "RunContext",
            "value": {"routine_id": "routine-1", "routine_name": "Routine"},
        },
        "verification_report": {
            "record_id": "verification-1",
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": "verifier-1",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": "candidate-1",
            "outcome": "passed",
            "value": {"outcome": "passed", "grades": []},
        },
    }


OUTPUT_RECORD_CASES = _record_cases()


def test_output_record_matrix_tracks_explicit_record_type_map() -> None:
    assert set(OUTPUT_RECORD_CASES) == set(OUTPUT_RECORD_MODELS_BY_TYPE)
    assert set(get_args(AcceptedOutputRecordPayload)) == set(OUTPUT_RECORD_MODELS_BY_TYPE.values())


@pytest.mark.parametrize(("record_type", "payload"), OUTPUT_RECORD_CASES.items())
def test_output_record_event_accepts_every_produced_record_type(
    record_type: str,
    payload: dict[str, Any],
) -> None:
    accepted = OutputRecordAcceptedPayload.model_validate(payload).root

    assert accepted.record_type == record_type
    assert type(accepted) is OUTPUT_RECORD_MODELS_BY_TYPE[record_type]
