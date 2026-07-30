"""Observable contracts for the isolated immutable projection scaffold."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    CandidateProjection,
    CallbackEventValue,
    CleanupRequestValue,
    CommandDefinitionValue,
    EdgeValue,
    EdgeProjection,
    EnvironmentFailureValue,
    ExecutionProjection,
    FinalInvariantBlockerProjection,
    FrozenMap,
    GovernanceProjection,
    GraphRecordSummaryProjection,
    GraphProjection,
    ImmutableGraphProjection,
    InputBindingValue,
    InputBindingProjection,
    InvalidTestBlockValue,
    LeaseValue,
    LatestRoutineSnapshotProjection,
    LifecycleProjection,
    NodeProjection,
    NodeRuntimeProjection,
    NodeSchedulingProjection,
    NodeSpecProjection,
    PlannerSessionProjection,
    PlanningProjection,
    ProjectedCandidateValue,
    ProjectedCheckResultValue,
    ProjectedRecord,
    ProjectionAuthorityRequestValue,
    ProjectionApprovalDecisionValue,
    ProjectionAuthorityDecisionValue,
    ProjectionDecisionRequestValue,
    ProjectionOversightDecisionValue,
    ProjectionModel,
    RecordStore,
    RecoveryNodeIndexValue,
    RequirementRevisionValue,
    RequirementsProjection,
    ResourceClaimValue,
    SchedulingProjection,
    SupportEvidenceValue,
    SupportEvidenceProjection,
    TaskProjection,
    TopologyProjection,
    UsageProjection,
    VerificationProjection,
    VerificationResultValue,
    VerifierVerdictValue,
)


ROOT_GROUPS = {
    "lifecycle",
    "nodes",
    "tasks",
    "topology",
    "records",
    "scheduling",
    "planning",
    "verification",
    "governance",
    "requirements",
    "execution",
    "usage",
}


def _manifest() -> dict[str, Any]:
    root = Path(__file__).parents[2]
    return yaml.safe_load((root / "scripts/codemods/graph_projection_manifest.yaml").read_text())


def _destination_paths(model: type[BaseModel]) -> set[str]:
    destinations: set[str] = set()

    def visit(current: type[BaseModel], prefix: str) -> None:
        for name, field in current.model_fields.items():
            path = f"{prefix}.{name}" if prefix else name
            destinations.add(path)
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                visit(annotation, path)
            elif get_origin(annotation) is FrozenMap:
                value_type = get_args(annotation)[1]
                if isinstance(value_type, type) and issubclass(value_type, BaseModel):
                    visit(value_type, path)

    visit(model, "")
    return destinations


def _mutable_annotation_violations(annotation: object) -> list[str]:
    origin = get_origin(annotation)
    if annotation in {Any, list, dict} or origin in {list, dict}:
        return [str(annotation)]
    return [
        violation
        for argument in get_args(annotation)
        for violation in _mutable_annotation_violations(argument)
    ]


def _models_in_annotation(annotation: object) -> set[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    return {model for argument in get_args(annotation) for model in _models_in_annotation(argument)}


def test_root_groups_equal_manifest_groups_and_architecture() -> None:
    manifest_groups = {entry["group"] for entry in _manifest()["fields"] if entry["group"]}
    assert manifest_groups == ROOT_GROUPS
    assert set(ImmutableGraphProjection.model_fields) == manifest_groups


def test_manifest_exactly_owns_each_legacy_field_at_its_retained_destination() -> None:
    manifest = _manifest()
    destinations = _destination_paths(ImmutableGraphProjection)
    by_old_name = {entry["old_name"]: entry for entry in manifest["fields"]}

    assert set(by_old_name) == set(GraphProjection.__annotations__)
    assert len(by_old_name) == len(manifest["fields"])
    retained = {
        (old_name, entry["new_path"].replace(".*", ""), entry["group"])
        for old_name, entry in by_old_name.items()
        if entry["new_path"] is not None
    }

    assert all(path in destinations for _, path, _ in retained)
    assert all(group in ROOT_GROUPS for _, _, group in retained)
    assert {entry["old_name"] for entry in manifest["fields"] if entry["new_path"] is None} == {
        "open_proposal_blockers"
    }


def test_every_node_creation_fact_has_one_explicit_node_or_group_owner() -> None:
    manifest = _manifest()
    destinations = _destination_paths(ImmutableGraphProjection)
    assert {
        entry["new_path"].replace(".*", "") for entry in manifest["node_creation_ownership"]
    } <= destinations
    assert "details" not in NodeSpecProjection.model_fields
    assert set(NodeProjection.model_fields) == {"spec", "runtime", "scheduling"}


def test_model_graph_has_no_mutable_annotations_or_open_extra() -> None:
    pending = [ImmutableGraphProjection]
    visited: set[type[BaseModel]] = set()
    violations: list[str] = []
    while pending:
        model = pending.pop()
        if model in visited:
            continue
        visited.add(model)
        if model.model_config.get("frozen") is not True:
            violations.append(f"{model.__name__} is not frozen")
        if model.model_config.get("extra") != "forbid":
            violations.append(f"{model.__name__} accepts extra fields")
        for annotation in get_type_hints(model).values():
            violations.extend(_mutable_annotation_violations(annotation))
            pending.extend(_models_in_annotation(annotation))
    assert violations == []


def test_graph_projection_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ImmutableGraphProjection.model_validate({"unknown": True})


def test_empty_projection_uses_persistent_defaults() -> None:
    projection = ImmutableGraphProjection()

    assert isinstance(projection.nodes, FrozenMap)
    assert projection.scheduling.ready_node_ids == ()
    assert projection.planning.generation_budget == 8


def test_projection_groups_are_frozen() -> None:
    projection = ImmutableGraphProjection()

    with pytest.raises(ValidationError, match="frozen_instance"):
        projection.scheduling.ready_node_ids = ("node-1",)


def test_node_values_and_maps_cannot_be_mutated() -> None:
    node = NodeProjection(spec=NodeSpecProjection(node_id="node-1", creation_position=1))
    projection = ImmutableGraphProjection(nodes=FrozenMap({"node-1": node}))

    with pytest.raises(ValidationError, match="frozen_instance"):
        node.runtime = NodeRuntimeProjection(state="ready")
    with pytest.raises(AttributeError):
        setattr(projection.nodes, "node-2", node)
    with pytest.raises(ValidationError, match="frozen_instance"):
        node.scheduling = NodeSchedulingProjection(last_deferred_reason="later")


def test_record_store_is_the_only_full_payload_owner_and_indexes_are_id_only() -> None:
    assert set(RecordStore.model_fields) == {
        "by_id",
        "ids_by_node_port",
        "summaries_by_id",
    }
    ids_annotation = RecordStore.model_fields["ids_by_node_port"].annotation
    assert get_origin(ids_annotation) is FrozenMap
    assert Mapping not in get_args(ids_annotation)

    reachable_annotations = [
        annotation
        for model in _models_in_annotation(ImmutableGraphProjection)
        for annotation in get_type_hints(model).values()
    ]
    assert sum("ProjectedRecord" in str(annotation) for annotation in reachable_annotations) == 0
    by_id_value = get_args(get_type_hints(RecordStore)["by_id"])[1]
    assert get_args(by_id_value) == get_args(get_args(ProjectedRecord)[0])


def test_new_models_are_available_from_public_graph_api() -> None:
    exported_models = {
        ProjectionModel,
        LifecycleProjection,
        ResourceClaimValue,
        CommandDefinitionValue,
        ProjectionDecisionRequestValue,
        ProjectionAuthorityRequestValue,
        NodeSpecProjection,
        NodeRuntimeProjection,
        NodeSchedulingProjection,
        NodeProjection,
        ProjectedCandidateValue,
        TaskProjection,
        EdgeValue,
        InputBindingValue,
        TopologyProjection,
        GraphRecordSummaryProjection,
        FinalInvariantBlockerProjection,
        RecordStore,
        SchedulingProjection,
        PlannerSessionProjection,
        PlanningProjection,
        RecoveryNodeIndexValue,
        VerificationResultValue,
        ProjectedCheckResultValue,
        InvalidTestBlockValue,
        VerifierVerdictValue,
        VerificationProjection,
        GovernanceProjection,
        ProjectionApprovalDecisionValue,
        ProjectionAuthorityDecisionValue,
        ProjectionOversightDecisionValue,
        LatestRoutineSnapshotProjection,
        RequirementsProjection,
        RequirementRevisionValue,
        SupportEvidenceValue,
        ExecutionProjection,
        LeaseValue,
        EnvironmentFailureValue,
        CallbackEventValue,
        CleanupRequestValue,
        UsageProjection,
    }

    assert all(isinstance(model, type) for model in exported_models)


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (
            EdgeProjection(
                edge_id="edge-1",
                from_node_id="from",
                from_port="out",
                to_node_id="to",
                to_port="in",
                from_node_kind="builder",
                from_node_role="coder",
                accepted_record_selector={"record_type": "candidate"},
                purpose="handoff",
                description="needed",
                selection={"latest": True},
                binding_policy="append",
                freshness_policy="fresh",
                prompt_hydration_policy="summary",
                metadata={"priority": 1},
            ),
            EdgeValue,
            {
                "required": True,
                "dependency_type": "input_binding",
                "from_node_kind": "builder",
                "accepted_record_selector": {"record_type": "candidate"},
                "prompt_hydration_policy": "summary",
            },
        ),
        (
            InputBindingProjection(
                edge_id="edge-1",
                to_node_id="to",
                to_port="in",
                record_ids=["record-1"],
                bound_at_position=2,
                record_bound_positions={"record-1": 2},
                binding_policy="append",
                trigger="accepted",
                supersedes_record_id="old-record",
            ),
            InputBindingValue,
            {"bound_at_position": 2, "record_bound_positions": {"record-1": 2}},
        ),
        (
            CandidateProjection(
                candidate_id="candidate-1",
                attempt_number=1,
                position=3,
                file_state_record_ids=["file-1"],
                supersedes_task_region_ids=["task-0"],
            ),
            ProjectedCandidateValue,
            {"position": 3, "file_state_record_ids": ["file-1"]},
        ),
        (
            SupportEvidenceProjection(
                support_id="support-1",
                evidence_id="evidence-1",
                requirement_id="requirement-1",
                requirement_version_id="version-1",
                status="fresh",
                position=4,
                stale_reason="none",
                confidence="high",
            ),
            SupportEvidenceValue,
            {"requirement_version_id": "version-1", "position": 4, "confidence": "high"},
        ),
    ],
)
def test_projection_values_preserve_canonical_source_facts(
    source: BaseModel, target: type[ProjectionModel], expected: dict[str, object]
) -> None:
    projected = target.model_validate(source.model_dump(by_alias=True))
    dumped = projected.model_dump(mode="json", by_alias=True)

    for field, value in expected.items():
        assert dumped[field] == value


def test_latest_routine_snapshot_has_required_identity_not_summary_shape() -> None:
    assert set(PlanningProjection.model_fields["latest_routine_snapshot"].annotation.__args__) != {
        GraphRecordSummaryProjection,
        type(None),
    }
