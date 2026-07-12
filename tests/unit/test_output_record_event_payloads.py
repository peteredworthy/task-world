from __future__ import annotations

import pytest

from orchestrator.graph.events.records import OutputRecordAcceptedPayload


def _candidate_record() -> dict[str, object]:
    return {
        "record_id": "candidate-1",
        "record_kind": "output",
        "record_type": "candidate",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": "candidate-1",
        "value": {"summary": "implemented"},
    }


def test_output_record_envelope_requires_a_record() -> None:
    with pytest.raises(ValueError):
        OutputRecordAcceptedPayload.model_validate({})


def test_output_record_envelope_rejects_unknown_record_keys() -> None:
    with pytest.raises(ValueError):
        OutputRecordAcceptedPayload.model_validate(
            {"record": {**_candidate_record(), "typo": True}}
        )


def test_output_record_envelope_rejects_malformed_variant_value() -> None:
    with pytest.raises(ValueError):
        OutputRecordAcceptedPayload.model_validate(
            {"record": {**_candidate_record(), "value": {"summary": 7}}}
        )


def test_output_record_envelope_accepts_candidate_variant() -> None:
    payload = OutputRecordAcceptedPayload.model_validate({"record": _candidate_record()})
    assert payload.record.record_id == "candidate-1"
    assert payload.to_json()["record"]["record_type"] == "candidate"
    assert payload.to_json()["record"]["value"]["summary"] == "implemented"


def test_output_record_envelope_accepts_run_context_variant() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "run-context",
                "record_kind": "graph_record",
                "record_type": "run_context",
                "producer_node_id": "root",
                "port": "run_context",
                "schema": "RunContext",
                "value": {
                    "routine_id": "routine-1",
                    "routine_name": "Routine",
                    "planner_generation_budget": None,
                },
            }
        }
    )

    assert payload.record.record_type == "run_context"
    assert payload.to_json()["record"]["schema"] == "RunContext"


def test_candidate_record_accepts_matching_file_state_lineage() -> None:
    candidate = _candidate_record()
    candidate["file_state_record_id"] = "file-state-1"
    candidate["file_state_record_ids"] = ["file-state-1"]
    candidate["value"] = {
        "summary": "implemented",
        "file_state_record_ids": ["file-state-1"],
    }

    payload = OutputRecordAcceptedPayload.model_validate({"record": candidate})

    assert payload.to_json()["record"]["file_state_record_ids"] == ["file-state-1"]


def test_candidate_record_rejects_mismatched_file_state_lineage() -> None:
    candidate = _candidate_record()
    candidate["file_state_record_ids"] = ["file-state-1"]

    with pytest.raises(ValueError, match="file_state_record_ids"):
        OutputRecordAcceptedPayload.model_validate({"record": candidate})


def test_candidate_record_accepts_explicit_superseded_regions() -> None:
    candidate = _candidate_record()
    candidate["supersedes_task_region_ids"] = ["task-old"]

    payload = OutputRecordAcceptedPayload.model_validate({"record": candidate})

    assert payload.to_json()["record"]["supersedes_task_region_ids"] == ["task-old"]


def test_check_result_accepts_bound_verification_report_lineage() -> None:
    verification_ids = ["verification-1"]
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "check-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-node-1",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-1",
                "task_region_id": "region-1",
                "verification_report_record_ids": verification_ids,
                "evaluated_record_ids": verification_ids,
                "value": {
                    "status": "passed",
                    "classification": "passed",
                    "command_id": "hidden-oracle",
                    "command_text": "verify",
                    "command": {"cmd": "verify"},
                    "worktree_path": "/tmp/worktree",
                    "base_snapshot_id": "snapshot-1",
                    "execution_id": "execution-1",
                    "duration_ms": 0,
                    "stdout": "",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "timeout_seconds": 1,
                    "environment_policy": {},
                    "verification_report_record_ids": verification_ids,
                    "evaluated_record_ids": verification_ids,
                },
            }
        }
    )

    assert payload.to_json()["record"]["verification_report_record_ids"] == verification_ids
