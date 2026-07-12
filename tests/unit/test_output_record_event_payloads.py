from __future__ import annotations

import pytest

from orchestrator.graph.events.records import OutputRecordAcceptedPayload
from orchestrator.graph import (
    FileStatePath,
    FileStatePolicy,
    WorktreeStatus,
    classify_file_state,
)
from collections.abc import Iterable
from typing import Any, get_args

from pydantic import BaseModel

from orchestrator.graph.models import (
    STRICT_OUTPUT_RECORD_BRANCHES,
    StrictVerificationReportRecord,
)


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
    with pytest.raises(ValueError, match="strict_nested_typo"):
        OutputRecordAcceptedPayload.model_validate(
            {"record": {**_candidate_record(), "strict_nested_typo": True}}
        )


def test_output_record_envelope_rejects_unknown_nested_value_keys() -> None:
    with pytest.raises(ValueError, match="nested_typo"):
        OutputRecordAcceptedPayload.model_validate(
            {
                "record": {
                    **_candidate_record(),
                    "value": {"summary": "implemented", "nested_typo": True},
                }
            }
        )


def test_output_record_envelope_rejects_unknown_record_type() -> None:
    with pytest.raises(ValueError, match="totally_unknown"):
        OutputRecordAcceptedPayload.model_validate(
            {
                "record": {
                    "record_id": "unknown-1",
                    "record_kind": "output",
                    "record_type": "totally_unknown",
                    "producer_node_id": "worker-1",
                    "port": "unknown",
                    "schema": "UnknownRecord",
                    "value": {"arbitrary": "fields"},
                }
            }
        )


def test_output_record_envelope_requires_verification_record_type() -> None:
    with pytest.raises(ValueError, match="missing_record_type"):
        OutputRecordAcceptedPayload.model_validate(
            {
                "record": {
                    "record_id": "verification-1",
                    "record_kind": "verification",
                    "producer_node_id": "verifier-1",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": "candidate-1",
                    "outcome": "passed",
                    "value": {"outcome": "passed", "grades": []},
                }
            }
        )


def test_strict_verification_variant_has_no_before_model_validator() -> None:
    validators = StrictVerificationReportRecord.__pydantic_decorators__.model_validators.values()

    assert all(validator.info.mode != "before" for validator in validators)


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


def test_candidate_variant_accepts_only_declared_active_detail_fields() -> None:
    candidate = _candidate_record()
    candidate["value"] = {
        "summary": "implemented",
        "body": [{"path": "src/example.py"}],
        "grades": {"requirement-1": "pass"},
        "node_creation_context": {"body": [{"path": "src/example.py"}]},
        "node_id": "worker-1",
    }

    payload = OutputRecordAcceptedPayload.model_validate({"record": candidate})

    assert payload.to_json()["record"]["value"]["node_id"] == "worker-1"
    with pytest.raises(ValueError, match="unknown_detail"):
        OutputRecordAcceptedPayload.model_validate(
            {"record": {**candidate, "value": {**candidate["value"], "unknown_detail": True}}}
        )


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
                    "source_worktree_path": "/tmp/worktree",
                    "execution_worktree_path": "/tmp/check-worktree",
                    "base_snapshot_id": "snapshot-1",
                    "execution_snapshot_id": "snapshot-check-1",
                    "execution_snapshot_ref": "refs/check/snapshot-1",
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


def test_output_record_boundary_retains_source_from_live_untracked_file_state_capture() -> None:
    classified = classify_file_state(
        WorktreeStatus(
            untracked=(
                FileStatePath(
                    path="notes/untracked.txt",
                    kind="untracked",
                    size_bytes=1,
                ),
            )
        ),
        FileStatePolicy(),
    )
    entry = classified.paths[0].to_record()

    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "untracked": [entry],
            }
        }
    )

    assert payload.to_json()["record"]["untracked"] == [entry]


def test_output_record_boundary_accepts_canonical_tracked_file_state_without_source() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "file-state-tracked-1",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "tracked": [{"path": "docs/out.md", "status": "modified"}],
            }
        }
    )

    assert payload.to_json()["record"]["tracked"] == [{"path": "docs/out.md", "status": "modified"}]


def test_output_record_boundary_accepts_compiler_artifact_reference_value_fields() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "artifact-reference-1",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": "context-1",
                "port": "artifact",
                "schema": "ContextArtifact",
                "value": {
                    "artifact_id": "plan",
                    "artifact_type": "context_source",
                    "uri": "docs/plan.md",
                    "required": True,
                    "section": "implementation",
                    "max_tokens": 4000,
                    "summarize": True,
                    "summarize_model": "summarizer-model",
                },
            }
        }
    )

    assert payload.to_json()["record"]["value"]["max_tokens"] == 4000


def test_output_record_boundary_accepts_decision_request_prompt() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "decision-request-1",
                "record_kind": "graph_record",
                "record_type": "decision_request",
                "producer_node_id": "human-gate-1",
                "port": "decision_request",
                "schema": "DecisionRequest",
                "value": {
                    "decision_type": "approval",
                    "options": ["approve", "reject"],
                    "consequence_summary": "Work cannot continue without a decision.",
                    "prompt": "Approve the proposed change?",
                },
            }
        }
    )

    assert payload.to_json()["record"]["value"]["prompt"] == "Approve the proposed change?"


def test_output_record_boundary_accepts_verification_value_candidate_id() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "outcome": "passed",
                "value": {"outcome": "passed", "candidate_id": "candidate-1", "grades": []},
            }
        }
    )

    assert payload.to_json()["record"]["value"]["candidate_id"] == "candidate-1"


def test_output_record_boundary_accepts_file_entry_hash_and_external_manifest_shape() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(
        {
            "record": {
                "record_id": "file-state-external-1",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "tracked": [{"path": "docs/out.md", "hash": "sha256:tracked"}],
                "external": [
                    {
                        "path": "artifact.bin",
                        "hash": "sha256:external",
                        "manifest": {
                            "path": "artifact.bin",
                            "hash": "sha256:external",
                            "origin": "generated",
                            "retention": "keep",
                        },
                    }
                ],
            }
        }
    )

    record = payload.to_json()["record"]
    assert record["tracked"][0]["hash"] == "sha256:tracked"
    assert record["external"][0]["manifest"]["retention"] == "keep"


def _reachable_models(annotation: Any) -> Iterable[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        for field in annotation.model_fields.values():
            yield from _reachable_models(field.annotation)
        return
    for argument in get_args(annotation):
        yield from _reachable_models(argument)


def test_every_strict_output_record_branch_and_nested_model_is_closed_immutable_and_has_no_before_validator() -> (
    None
):
    reachable = {
        model for branch in STRICT_OUTPUT_RECORD_BRANCHES for model in _reachable_models(branch)
    }

    assert len(STRICT_OUTPUT_RECORD_BRANCHES) == 21
    assert reachable
    for model in reachable:
        assert model.model_config.get("strict") is True, model.__name__
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert model.model_config.get("frozen") is True, model.__name__
        assert all(
            validator.info.mode != "before"
            for validator in model.__pydantic_decorators__.model_validators.values()
        ), model.__name__
        with pytest.raises(ValueError, match="extra_forbidden"):
            model.model_validate({"strict_unknown_field": True})
        instance = model.model_construct()
        field_name = next(iter(model.model_fields))
        with pytest.raises(ValueError, match="frozen"):
            setattr(instance, field_name, None)
