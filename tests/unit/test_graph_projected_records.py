"""Boundary conversion contracts for immutable projected records."""

from copy import deepcopy
from contextlib import nullcontext
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, cast, get_type_hints
from uuid import UUID

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from orchestrator.graph import (
    OUTPUT_RECORD_MODELS_BY_TYPE,
    ProjectedAnalysisSummaryRecord,
    ProjectedArtifactReferenceRecord,
    ProjectedAuthorityDecisionRecord,
    ProjectedAuthorityRequestRecord,
    ProjectedCandidateRecord,
    ProjectedCandidateRecordValue,
    ProjectedCheckResultRecord,
    ProjectedCompletionDecisionRecord,
    ProjectedDecisionRecord,
    ProjectedDecisionRequestRecord,
    ProjectedFailureRecord,
    ProjectedFanOutInputsRecord,
    ProjectedFileStateRecord,
    ProjectedGapClassificationRecord,
    ProjectedGraphPatchProposalRecord,
    ProjectedJoinResultRecord,
    ProjectedRecoveryPlanRecord,
    ProjectedRequirementRecord,
    ProjectedRoutineSnapshotRecord,
    ProjectedRunContextRecord,
    ProjectedRecord,
    ProjectedRecordBase,
    ProjectionModel,
    ProjectedVerificationReportRecord,
    ProjectedAnalysisSummaryValue,
    ProjectedArtifactReferenceValue,
    ProjectedAuthorityDecisionRecordValue,
    ProjectedAuthorityRequestRecordValue,
    ProjectedCheckResultRecordValue,
    ProjectedCompletionDecisionValue,
    ProjectedDecisionRecordValue,
    ProjectedDecisionRequestRecordValue,
    ProjectedFailureRecordValue,
    ProjectedFileEntry,
    ProjectedExternalArtifactManifest,
    ProjectedExternalFileEntry,
    ProjectedFanOutInputsValue,
    ProjectedGapClassificationValue,
    ProjectedGraphPatchProposalValue,
    ProjectedGitRef,
    ProjectedGradeRow,
    ProjectedJoinResultValue,
    ProjectedRecoveryPlanValue,
    ProjectedRequirementRecordValue,
    ProjectedRoutineSnapshotValue,
    ProjectedRunContextValue,
    ProjectedStoredArtifactRef,
    ProjectedDecisionActor,
    ProjectedVerificationReportValue,
    FrozenJsonValue,
    FrozenMap,
    OutputRecord,
    project_record,
    project_validated_record_for_reducer,
)
from tests.unit.test_output_record_event_payloads import OUTPUT_RECORD_CASES


def _isolation_record_payload(record_type: str) -> dict[str, Any]:
    payload = deepcopy(OUTPUT_RECORD_CASES[record_type])
    payload["payload"] = {"mutable": {"items": ["payload-item"]}}
    payload["provenance"] = {"event_ids": ["event-1"]}

    value = payload.get("value")
    if isinstance(value, dict):
        if record_type == "analysis_summary":
            value.update(source_record_ids=["record-1"], omitted_details=["detail"])
        elif record_type == "artifact_reference":
            value["source_record_ids"] = ["record-1"]
        elif record_type in {"authority_decision", "decision_record"}:
            value["decider"] = {"kind": "human", "id": "alice"}
            value["scope"] = {"regions": ["region-1"]}
        elif record_type == "authority_request_record":
            value["requested_authority"] = ["graph_write", "repo_write"]
        elif record_type == "candidate":
            value.update(
                changed_paths=["src/a.py"],
                requirements_addressed=["R-1"],
                file_state_record_ids=["file-state-1"],
            )
            payload["file_state_record_ids"] = ["file-state-1"]
            payload["supersedes_task_region_ids"] = ["region-0"]
        elif record_type == "check_result":
            value["command"] = {"argv": ["uv", "run", "pytest"], "shell": False}
            value["command_binding"] = {"kind": "known", "tags": ["unit"]}
            value["environment_policy"] = {"env": {"CI": "1"}}
            value["candidate_record_ids"] = ["candidate-record-1"]
            payload["candidate_record_ids"] = ["candidate-record-1"]
        elif record_type == "completion_decision":
            value["status"] = "blocked"
            value["blockers"] = [{"requirement_id": "R-1", "evidence": ["check-1"]}]
        elif record_type == "decision_request":
            value["options"] = ["approved", "rejected", "deferred"]
        elif record_type == "fan_out_inputs":
            value.update(inputs=[{"requirement": "R-1"}], options={"retry": True})
            payload["file_state_record_ids"] = ["file-state-1"]
        elif record_type == "graph_patch_proposal":
            value["ops"] = [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "requirements": ["R-1"],
                    },
                }
            ]
            value["expected_downstream_effects"] = ["worker scheduled"]
        elif record_type == "join_result":
            value.update(
                source_record_ids=["candidate-record-1"],
                missing_optional_inputs=["context"],
            )
        elif record_type == "recovery_plan":
            value["graph_changes"] = [
                {"op": "retry_node", "steps": ["release lease", "schedule node"]}
            ]
        elif record_type == "requirement_record":
            value["acceptance_criteria"] = ["focused tests pass"]
        elif record_type == "routine_snapshot":
            value["dynamic_feature"] = {"requirements": ["R-1"], "options": {"retry": True}}
        elif record_type == "verification_report":
            value["grades"] = [{"requirement_id": "R-1", "grade": "A", "reason": "met"}]
            payload["evidence"] = {
                "checks": ["check-1"],
                "artifact_references": [{"artifact_id": "log-1"}],
            }
            payload["candidate_record_ids"] = ["candidate-record-1"]

    if record_type == "file_state":
        payload.update(
            git={"commit_sha": "abc", "diff_summary": {"changed_paths": ["src/a.py"]}},
            tracked=[{"path": "src/a.py", "status": "modified"}],
            external=[
                {
                    "path": "vendor/tool",
                    "source": "external",
                    "manifest": {
                        "path": "vendor/tool",
                        "hash": "sha256:tool",
                        "origin": "registry",
                        "retention": "keep",
                    },
                }
            ],
            classifications=[{"path": "secret.txt", "classification": "secret"}],
            cleanup_excluded_paths=["secret.txt"],
        )
    return payload


def _mutate_source_children(value: object) -> None:
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _mutate_source_children(getattr(value, name))
        return
    if isinstance(value, dict):
        for child in tuple(value.values()):
            _mutate_source_children(child)
        value["source_mutation"] = True
        return
    if isinstance(value, list):
        for child in tuple(value):
            _mutate_source_children(child)
        value.append("source mutation")
        return
    if isinstance(value, set):
        value.add("source mutation")


def _assert_deeply_immutable(value: object) -> None:
    assert not isinstance(value, (dict, list, set))
    if isinstance(value, BaseModel):
        assert isinstance(value, ProjectionModel)
        field_name = next(iter(type(value).model_fields))
        with pytest.raises(ValidationError, match="frozen_instance"):
            setattr(value, field_name, getattr(value, field_name))
        for name in type(value).model_fields:
            _assert_deeply_immutable(getattr(value, name))
        return
    if isinstance(value, FrozenMap):
        with pytest.raises(TypeError):
            cast(Any, value)["mutation"] = True
        if value:
            key = next(iter(value))
            with pytest.raises(TypeError):
                del cast(Any, value)[key]
        for child in value.values():
            _assert_deeply_immutable(child)
        return
    if isinstance(value, tuple):
        if value:
            with pytest.raises(TypeError):
                cast(Any, value)[0] = value[0]
        for child in value:
            _assert_deeply_immutable(child)


def test_projected_record_contracts_are_public_graph_interfaces() -> None:
    assert all(
        isinstance(contract, type)
        for contract in (
            ProjectedRecordBase,
            ProjectedCandidateRecordValue,
            ProjectedAnalysisSummaryValue,
            ProjectedArtifactReferenceValue,
            ProjectedAuthorityDecisionRecordValue,
            ProjectedAuthorityRequestRecordValue,
            ProjectedCheckResultRecordValue,
            ProjectedCompletionDecisionValue,
            ProjectedDecisionRecordValue,
            ProjectedDecisionRequestRecordValue,
            ProjectedFailureRecordValue,
            ProjectedFileEntry,
            ProjectedExternalArtifactManifest,
            ProjectedExternalFileEntry,
            ProjectedGapClassificationValue,
            ProjectedGraphPatchProposalValue,
            ProjectedGitRef,
            ProjectedGradeRow,
            ProjectedJoinResultValue,
            ProjectedRecoveryPlanValue,
            ProjectedRequirementRecordValue,
            ProjectedRoutineSnapshotValue,
            ProjectedRunContextValue,
            ProjectedStoredArtifactRef,
            ProjectedDecisionActor,
            ProjectedVerificationReportValue,
            ProjectedAnalysisSummaryRecord,
            ProjectedArtifactReferenceRecord,
            ProjectedAuthorityDecisionRecord,
            ProjectedAuthorityRequestRecord,
            ProjectedCandidateRecord,
            ProjectedCheckResultRecord,
            ProjectedCompletionDecisionRecord,
            ProjectedDecisionRecord,
            ProjectedDecisionRequestRecord,
            ProjectedFailureRecord,
            ProjectedFanOutInputsRecord,
            ProjectedFileStateRecord,
            ProjectedGapClassificationRecord,
            ProjectedGraphPatchProposalRecord,
            ProjectedJoinResultRecord,
            ProjectedRecoveryPlanRecord,
            ProjectedRequirementRecord,
            ProjectedRoutineSnapshotRecord,
            ProjectedRunContextRecord,
            ProjectedVerificationReportRecord,
        )
    )
    assert ProjectedFanOutInputsValue is not None


PROJECTED_RECORD_SEMANTICS = (
    (
        "analysis_summary",
        OUTPUT_RECORD_MODELS_BY_TYPE["analysis_summary"],
        ProjectedAnalysisSummaryRecord,
        ProjectedAnalysisSummaryValue,
        "output",
        "analysis_summary",
        "AnalysisSummary",
    ),
    (
        "artifact_reference",
        OUTPUT_RECORD_MODELS_BY_TYPE["artifact_reference"],
        ProjectedArtifactReferenceRecord,
        ProjectedArtifactReferenceValue,
        "graph_record",
        "artifact",
        "ContextArtifact",
    ),
    (
        "authority_decision",
        OUTPUT_RECORD_MODELS_BY_TYPE["authority_decision"],
        ProjectedAuthorityDecisionRecord,
        ProjectedAuthorityDecisionRecordValue,
        "output",
        "authority_decision",
        "AuthorityDecision",
    ),
    (
        "authority_request_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["authority_request_record"],
        ProjectedAuthorityRequestRecord,
        ProjectedAuthorityRequestRecordValue,
        "graph_record",
        "authority_request_record",
        "AuthorityRequest",
    ),
    (
        "candidate",
        OUTPUT_RECORD_MODELS_BY_TYPE["candidate"],
        ProjectedCandidateRecord,
        ProjectedCandidateRecordValue,
        "output",
        "candidate",
        "ImplementationCandidate",
    ),
    (
        "check_result",
        OUTPUT_RECORD_MODELS_BY_TYPE["check_result"],
        ProjectedCheckResultRecord,
        ProjectedCheckResultRecordValue,
        "output",
        "check_result",
        "CheckResult",
    ),
    (
        "classified_gap",
        OUTPUT_RECORD_MODELS_BY_TYPE["classified_gap"],
        ProjectedGapClassificationRecord,
        ProjectedGapClassificationValue,
        "output",
        "classified_gap",
        "GapClassification",
    ),
    (
        "completion_decision",
        OUTPUT_RECORD_MODELS_BY_TYPE["completion_decision"],
        ProjectedCompletionDecisionRecord,
        ProjectedCompletionDecisionValue,
        "output",
        "completion_decision",
        "CompletionDecision",
    ),
    (
        "decision_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["decision_record"],
        ProjectedDecisionRecord,
        ProjectedDecisionRecordValue,
        "output",
        "decision_record",
        "DecisionRecord",
    ),
    (
        "decision_request",
        OUTPUT_RECORD_MODELS_BY_TYPE["decision_request"],
        ProjectedDecisionRequestRecord,
        ProjectedDecisionRequestRecordValue,
        "graph_record",
        "decision_request",
        "DecisionRequest",
    ),
    (
        "failure_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["failure_record"],
        ProjectedFailureRecord,
        ProjectedFailureRecordValue,
        "graph_record",
        "failure_record",
        "FailureRecord",
    ),
    (
        "fan_out_inputs",
        OUTPUT_RECORD_MODELS_BY_TYPE["fan_out_inputs"],
        ProjectedFanOutInputsRecord,
        FrozenMap,
        "output",
        "candidate",
        "ImplementationCandidate",
    ),
    (
        "file_state",
        OUTPUT_RECORD_MODELS_BY_TYPE["file_state"],
        ProjectedFileStateRecord,
        object,
        "file_state",
        "file_state",
        "FileStateRecord",
    ),
    (
        "gap_classification",
        OUTPUT_RECORD_MODELS_BY_TYPE["gap_classification"],
        ProjectedGapClassificationRecord,
        ProjectedGapClassificationValue,
        "output",
        "gap_classification",
        "GapClassification",
    ),
    (
        "gap_plan",
        OUTPUT_RECORD_MODELS_BY_TYPE["gap_plan"],
        ProjectedGapClassificationRecord,
        ProjectedGapClassificationValue,
        "output",
        "gap_plan",
        "GapClassification",
    ),
    (
        "graph_patch_proposal",
        OUTPUT_RECORD_MODELS_BY_TYPE["graph_patch_proposal"],
        ProjectedGraphPatchProposalRecord,
        ProjectedGraphPatchProposalValue,
        "output",
        "graph_patch_proposal",
        "GraphPatch",
    ),
    (
        "join_result",
        OUTPUT_RECORD_MODELS_BY_TYPE["join_result"],
        ProjectedJoinResultRecord,
        ProjectedJoinResultValue,
        "output",
        "join_result",
        "JoinResult",
    ),
    (
        "recovery_plan",
        OUTPUT_RECORD_MODELS_BY_TYPE["recovery_plan"],
        ProjectedRecoveryPlanRecord,
        ProjectedRecoveryPlanValue,
        "output",
        "recovery_plan",
        "RecoveryPlan",
    ),
    (
        "requirement_record",
        OUTPUT_RECORD_MODELS_BY_TYPE["requirement_record"],
        ProjectedRequirementRecord,
        ProjectedRequirementRecordValue,
        "graph_record",
        "requirement",
        "RequirementRecord",
    ),
    (
        "routine_snapshot",
        OUTPUT_RECORD_MODELS_BY_TYPE["routine_snapshot"],
        ProjectedRoutineSnapshotRecord,
        ProjectedRoutineSnapshotValue,
        "graph_record",
        "snapshot",
        "RoutineSnapshot",
    ),
    (
        "run_context",
        OUTPUT_RECORD_MODELS_BY_TYPE["run_context"],
        ProjectedRunContextRecord,
        ProjectedRunContextValue,
        "graph_record",
        "run_context",
        "RunContext",
    ),
    (
        "verification_report",
        OUTPUT_RECORD_MODELS_BY_TYPE["verification_report"],
        ProjectedVerificationReportRecord,
        ProjectedVerificationReportValue,
        "verification",
        "verification_report",
        "VerificationReport",
    ),
)


@pytest.mark.parametrize(
    ("record_type", "source_type", "projected_type", "value_type", "record_kind", "port", "schema"),
    PROJECTED_RECORD_SEMANTICS,
)
def test_project_record_has_explicit_canonical_contract(
    record_type: str,
    source_type: type[object],
    projected_type: type[object],
    value_type: type[object],
    record_kind: str,
    port: str,
    schema: str,
) -> None:
    source = source_type.model_validate(_isolation_record_payload(record_type))
    expected = source.model_dump(mode="json", by_alias=True, exclude_unset=True)

    projected = project_record(source)
    projected_type_before_mutation = type(projected)

    assert projected.record_type == record_type
    assert projected.record_kind == record_kind
    assert projected.port == port
    assert projected.schema_ == schema
    assert type(projected) is projected_type
    if value_type is not object:
        assert type(getattr(projected, "value")) is value_type
    assert projected.model_dump(mode="json", by_alias=True, exclude_unset=True) == expected
    assert TypeAdapter(ProjectedRecord).validate_python(expected) == projected
    projected_json = projected.model_dump_json(by_alias=True, exclude_unset=True)
    restored = TypeAdapter(ProjectedRecord).validate_json(projected_json)
    assert restored == projected
    assert restored.model_dump_json(by_alias=True, exclude_unset=True) == projected_json
    _assert_deeply_immutable(projected)

    _mutate_source_children(source)
    after_source_mutation = projected.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert type(projected) is projected_type_before_mutation
    assert after_source_mutation == expected
    if "value" in expected:
        assert after_source_mutation["value"] == expected["value"]
    _assert_deeply_immutable(projected)
    assert "data" not in type(projected).model_fields


def test_project_record_isolated_from_source_event_mutation() -> None:
    raw: dict[str, Any] = dict(OUTPUT_RECORD_CASES["candidate"])
    source = OUTPUT_RECORD_MODELS_BY_TYPE["candidate"].model_validate(raw)
    projected = project_record(source)

    raw["value"]["summary"] = "mutated after projection"

    assert projected.value.summary == "Implemented the requested change"


class _NormalizationEnum(str, Enum):
    VALUE = "value"


def _fan_out_payload() -> dict[str, object]:
    return {
        "record_id": "fan-out-normalization",
        "record_kind": "output",
        "record_type": "fan_out_inputs",
        "producer_node_id": "planner-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "value": {},
    }


def test_project_record_fan_out_preserves_json_mode_normalization() -> None:
    source = OutputRecord.model_validate(
        {
            **_fan_out_payload(),
            "value": {
                "date": date(2026, 1, 2),
                "datetime": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
                "uuid": UUID("12345678-1234-5678-1234-567812345678"),
                "enum": _NormalizationEnum.VALUE,
            },
            "payload": {"date": date(2026, 1, 2)},
            "provenance": {"uuid": UUID("12345678-1234-5678-1234-567812345678")},
        }
    )
    expected_payload = source.model_dump(
        mode="json", by_alias=True, exclude_unset=True, exclude_none=True
    )
    expected = ProjectedFanOutInputsRecord.model_validate(expected_payload)

    assert project_record(source) == expected


@pytest.mark.parametrize(
    ("source", "serializer_warning"),
    (
        (OutputRecord.model_construct(**_fan_out_payload(), schema_version=0), False),
        (OutputRecord.model_construct(**_fan_out_payload(), producer_port="other"), False),
        (OutputRecord.model_construct(**{**_fan_out_payload(), "record_id": 7}), True),
    ),
    ids=("schema-version", "producer-port", "strict-record-id"),
)
def test_project_record_does_not_bypass_fan_out_destination_validation(
    source: OutputRecord, serializer_warning: bool
) -> None:
    warning_context = (
        pytest.warns(UserWarning, match="Pydantic serializer warnings")
        if serializer_warning
        else nullcontext()
    )
    with warning_context, pytest.raises(ValidationError):
        project_record(source)


def test_project_record_validates_fan_out_subclass_extra_fields() -> None:
    class ExtendedOutputRecord(OutputRecord):
        extra_value: str

    source = ExtendedOutputRecord.model_validate(
        {**_fan_out_payload(), "extra_value": "unexpected"}
    )

    with pytest.raises(ValidationError):
        project_record(source)


def test_projected_fan_out_normalizes_list_and_dict_subclasses() -> None:
    class JsonList(list[object]):
        pass

    class JsonDict(dict[str, object]):
        pass

    projected = ProjectedFanOutInputsRecord.model_validate(
        {
            **_fan_out_payload(),
            "value": JsonDict({"items": JsonList([JsonDict({"name": "candidate"})])}),
        }
    )

    assert projected.value == FrozenMap({"items": (FrozenMap({"name": "candidate"}),)})


@pytest.mark.parametrize(
    "optional_fields",
    (
        {"payload": None, "provenance": None},
        {"payload": {}, "provenance": {}, "file_state_record_ids": []},
    ),
    ids=("explicit-null", "explicit-empty"),
)
def test_reducer_fan_out_fast_path_matches_public_field_set_policy(
    optional_fields: dict[str, object],
) -> None:
    source = OutputRecord.model_validate({**_fan_out_payload(), **optional_fields})

    fast = project_validated_record_for_reducer(source)
    public = project_record(source)

    assert fast == public
    assert fast.model_fields_set == public.model_fields_set
    assert fast.model_dump(by_alias=True, exclude_unset=True) == public.model_dump(
        by_alias=True, exclude_unset=True
    )


def test_reducer_fan_out_fast_path_falls_back_for_missing_required_attributes() -> None:
    source = OutputRecord.model_construct(record_type="fan_out_inputs")

    with pytest.raises(ValidationError):
        project_validated_record_for_reducer(source)


def test_projected_record_revalidates_exact_instance_and_rejects_map_subclass() -> None:
    source = OUTPUT_RECORD_MODELS_BY_TYPE["candidate"].model_validate(
        _isolation_record_payload("candidate")
    )
    projected = project_record(source)

    restored = type(projected).model_validate(projected)

    assert restored == projected
    assert restored.model_dump(mode="json", by_alias=True) == projected.model_dump(
        mode="json", by_alias=True
    )

    class UntrustedFrozenMap(FrozenMap[str, object]):
        pass

    with pytest.raises(ValidationError):
        type(projected).model_validate(
            {
                **projected.model_dump(mode="json", by_alias=True),
                "payload": UntrustedFrozenMap({"nested": ("value",)}),
            }
        )


def test_project_record_rejects_unknown_discriminator() -> None:
    with pytest.raises(ValueError, match="unknown projected record discriminator"):
        project_record(cast(Any, {"record_type": "unknown"}))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"record_type": "unknown"},
        {**OUTPUT_RECORD_CASES["candidate"], "port": "check_result"},
        {**OUTPUT_RECORD_CASES["candidate"], "schema": "CheckResult"},
        {**OUTPUT_RECORD_CASES["verification_report"], "outcome": "failed"},
        {**OUTPUT_RECORD_CASES["gap_plan"], "port": "gap_classification"},
    ],
)
def test_public_projected_record_union_rejects_invalid_contracts(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {**OUTPUT_RECORD_CASES["artifact_reference"], "port": "artifact_reference"},
        {**OUTPUT_RECORD_CASES["artifact_reference"], "schema": "ArtifactReference"},
    ],
)
def test_public_projected_record_union_rejects_crossed_artifact_reference_pairs(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


@pytest.mark.parametrize(
    ("port", "schema"),
    [
        ("analysis_summary", "AnalysisSummary"),
        ("analysis_summary", "RegionSummary"),
        ("planning_summary", "AnalysisSummary"),
        ("planning_summary", "RegionSummary"),
        ("region_summary", "AnalysisSummary"),
        ("region_summary", "RegionSummary"),
    ],
)
def test_projected_analysis_summary_accepts_every_source_port_schema_alias(
    port: str, schema: str
) -> None:
    payload = {**OUTPUT_RECORD_CASES["analysis_summary"], "port": port, "schema": schema}
    source = OUTPUT_RECORD_MODELS_BY_TYPE["analysis_summary"].model_validate(payload)

    projected = project_record(source)

    assert TypeAdapter(ProjectedRecord).validate_python(payload) == projected
    assert projected.port == port
    assert projected.schema_ == schema


@pytest.mark.parametrize(
    "record_type, mutation",
    [
        ("fan_out_inputs", {"port": 7}),
        ("fan_out_inputs", {"schema": 7}),
        ("file_state", {"port": "candidate"}),
        ("file_state", {"schema": "ImplementationCandidate"}),
        ("verification_report", {"value": {"outcome": "failed", "grades": []}}),
        (
            "check_result",
            {"value": {**OUTPUT_RECORD_CASES["check_result"]["value"], "timeout_seconds": 0}},
        ),
        (
            "graph_patch_proposal",
            {
                "value": {
                    "patch_id": "patch",
                    "proposed_by_node_id": "node",
                    "base_graph_position": 0,
                }
            },
        ),
        (
            "decision_request",
            {"value": {"decision_type": "approval", "options": [], "consequence_summary": "x"}},
        ),
        ("authority_request_record", {"value": {"requested_authority": ["write"], "reason": "x"}}),
        (
            "decision_record",
            {"value": {"decision": "approved", "decision_type": "approval", "decider": ""}},
        ),
        ("gap_plan", {"port": "gap_classification"}),
    ],
)
def test_public_projected_records_preserve_source_invariants(
    record_type: str, mutation: dict[str, Any]
) -> None:
    payload = {**OUTPUT_RECORD_CASES[record_type], **mutation}

    with pytest.raises(ValidationError):
        TypeAdapter(ProjectedRecord).validate_python(payload)


def test_projected_record_envelope_payloads_are_object_only() -> None:
    hints = get_type_hints(ProjectedRecordBase)

    assert "FrozenMap" in str(hints["payload"])
    assert "FrozenMap" in str(hints["provenance"])
    assert FrozenJsonValue not in (hints["payload"], hints["provenance"])
    assert FrozenMap is not None


def test_project_record_preserves_nondefault_verification_check_and_decision_nested_values() -> (
    None
):
    verification_source = OUTPUT_RECORD_MODELS_BY_TYPE["verification_report"].model_validate(
        {
            "record_id": "verification-nested-1",
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": "verifier-1",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": "candidate-1",
            "task_region_id": "region-1",
            "outcome": "passed",
            "value": {
                "outcome": "passed",
                "grades": [{"requirement_id": "R-1", "grade": "A", "reason": "met"}],
                "reason": "all requirements met",
            },
            "evidence": {"checks": ["check-1"], "confidence": 0.9},
            "candidate_record_ids": ["candidate-record-1"],
        }
    )
    check_source = OUTPUT_RECORD_MODELS_BY_TYPE["check_result"].model_validate(
        {
            "record_id": "check-nested-1",
            "record_kind": "output",
            "record_type": "check_result",
            "producer_node_id": "check-1",
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": "candidate-1",
            "task_region_id": "region-1",
            "attempt_number": 2,
            "value": {
                "status": "failed",
                "classification": "failed",
                "command_id": "pytest",
                "command_binding": {"kind": "known", "tags": ["unit"]},
                "command_text": "uv run pytest tests/unit",
                "command": {"argv": ["uv", "run", "pytest"], "shell": False},
                "worktree_path": "/tmp/worktree",
                "source_worktree_path": "/tmp/source",
                "execution_worktree_path": "/tmp/execution",
                "base_snapshot_id": "S0",
                "execution_snapshot_id": "S1",
                "execution_snapshot_ref": "refs/snapshots/S1",
                "execution_id": "execution-1",
                "exit_code": 1,
                "duration_ms": 42,
                "stdout_tail": "partial",
                "stdout_ref": {
                    "artifact_id": "stdout-1",
                    "content_hash": "sha256:" + "a" * 64,
                    "size_bytes": 42,
                    "media_type": "text/plain",
                    "encoding": "utf-8",
                    "storage_uri": "artifact://sha256/" + "a" * 64,
                },
                "stderr_tail": "failure",
                "stderr_truncated": False,
                "stdout_truncated": True,
                "timeout_seconds": 30.5,
                "environment_policy": {"cwd": "/tmp/worktree", "env": {"CI": "1"}},
                "candidate_record_ids": ["candidate-record-1"],
                "file_state_record_ids": ["file-state-1"],
                "verification_report_record_ids": ["verification-nested-1"],
                "evaluated_record_ids": ["requirement-1"],
            },
        }
    )
    decision_source = OUTPUT_RECORD_MODELS_BY_TYPE["decision_record"].model_validate(
        {
            "record_id": "decision-nested-1",
            "record_kind": "output",
            "record_type": "decision_record",
            "producer_node_id": "gate-1",
            "port": "decision_record",
            "schema": "DecisionRecord",
            "value": {
                "decision": "approved",
                "decision_type": "approval",
                "decider": {"kind": "human", "id": "alice"},
                "scope": {"regions": ["region-1"]},
                "expires_at": "2026-07-30T00:00:00Z",
                "reason": "reviewed",
            },
        }
    )

    verification = project_record(verification_source)
    check = project_record(check_source)
    decision = project_record(decision_source)

    assert type(verification.value) is ProjectedVerificationReportValue
    assert type(verification.value.grades[0]) is ProjectedGradeRow
    assert verification.evidence == FrozenMap({"checks": ("check-1",), "confidence": 0.9})
    assert type(check.value) is ProjectedCheckResultRecordValue
    assert type(check.value.stdout_ref) is ProjectedStoredArtifactRef
    assert check.value.command == FrozenMap({"argv": ("uv", "run", "pytest"), "shell": False})
    assert type(decision.value) is ProjectedDecisionRecordValue
    assert type(decision.value.decider) is ProjectedDecisionActor
    assert decision.value.scope == FrozenMap({"regions": ("region-1",)})
    for source, projected in (
        (verification_source, verification),
        (check_source, check),
        (decision_source, decision),
    ):
        assert projected.model_dump(
            mode="json", by_alias=True, exclude_unset=True
        ) == source.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert TypeAdapter(ProjectedRecord).validate_json(projected.model_dump_json()) == projected


def test_project_record_preserves_nondefault_file_state_and_fan_out_nested_values() -> None:
    file_state_source = OUTPUT_RECORD_MODELS_BY_TYPE["file_state"].model_validate(
        {
            "record_id": "file-state-nested-1",
            "record_kind": "file_state",
            "record_type": "file_state",
            "producer_node_id": "worker-1",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": "S1",
            "base_snapshot_id": "S0",
            "git": {"commit_sha": "abc", "tree_sha": "tree", "diff_summary": {"changed": 2}},
            "tracked": [{"path": "src/a.py", "status": "modified", "size_bytes": 12}],
            "external": [
                {
                    "path": "vendor/tool",
                    "source": "external",
                    "manifest": {
                        "path": "vendor/tool",
                        "hash": "sha256:tool",
                        "origin": "registry",
                        "retention": "keep",
                    },
                }
            ],
            "classifications": [
                {"path": "secret.txt", "classification": "secret", "rejected": True}
            ],
            "verdict": "rejected",
            "patch_bundle_id": "bundle-1",
            "cleanup_excluded_paths": ["secret.txt"],
            "compromised": True,
        }
    )
    fan_out_source = OUTPUT_RECORD_MODELS_BY_TYPE["fan_out_inputs"].model_validate(
        {
            "record_id": "fan-out-nested-1",
            "record_kind": "output",
            "record_type": "fan_out_inputs",
            "producer_node_id": "planner-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": "candidate-1",
            "task_region_id": "region-1",
            "attempt_number": 3,
            "file_state_record_ids": ["file-state-nested-1"],
            "value": {"inputs": [{"requirement": "R-1"}], "options": {"retry": True}},
        }
    )

    file_state = project_record(file_state_source)
    fan_out = project_record(fan_out_source)

    assert type(file_state.git) is ProjectedGitRef
    assert type(file_state.tracked[0]) is ProjectedFileEntry
    assert type(file_state.external[0]) is ProjectedExternalFileEntry
    assert type(file_state.external[0].manifest) is ProjectedExternalArtifactManifest
    assert type(fan_out.value) is FrozenMap
    assert type(fan_out.value["inputs"]) is tuple
    assert type(fan_out.value["inputs"][0]) is FrozenMap
    assert type(fan_out.value["options"]) is FrozenMap
    assert fan_out.value == FrozenMap(
        {"inputs": (FrozenMap({"requirement": "R-1"}),), "options": FrozenMap({"retry": True})}
    )
    for source, projected in ((file_state_source, file_state), (fan_out_source, fan_out)):
        assert projected.model_dump(
            mode="json", by_alias=True, exclude_unset=True
        ) == source.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert TypeAdapter(ProjectedRecord).validate_json(projected.model_dump_json()) == projected


@pytest.mark.parametrize(
    ("port", "schema"),
    [("reader_output", "FanOutInputs"), ("fan_out_inputs", "FanOutJoinedInputs")],
)
def test_project_record_preserves_runtime_fan_out_contract(port: str, schema: str) -> None:
    source = OUTPUT_RECORD_MODELS_BY_TYPE["fan_out_inputs"].model_validate(
        {
            "record_id": f"fan-out-{port}",
            "record_kind": "output",
            "record_type": "fan_out_inputs",
            "producer_node_id": "planner-1",
            "port": port,
            "schema": schema,
            "value": {"summary": "fan-out inputs"},
        }
    )

    projected = project_record(source)

    assert projected.port == port
    assert projected.schema_ == schema
