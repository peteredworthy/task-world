"""Observable contracts for the isolated immutable projection scaffold."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    CallbackEventValue,
    CleanupRequestValue,
    CommandDefinitionValue,
    DecisionValue,
    EdgeValue,
    EnvironmentFailureValue,
    ExecutionProjection,
    FinalInvariantBlockerProjection,
    FrozenMap,
    GovernanceProjection,
    GraphRecordSummaryProjection,
    ImmutableGraphProjection,
    InputBindingValue,
    InvalidTestBlockValue,
    LeaseValue,
    LifecycleProjection,
    NodeProjection,
    NodeRuntimeProjection,
    NodeSchedulingProjection,
    NodeSpecProjection,
    PlannerSessionProjection,
    PlanningProjection,
    ProjectedCandidateValue,
    ProjectedCheckResultValue,
    ProjectionAuthorityRequestValue,
    ProjectionDecisionRequestValue,
    ProjectionModel,
    RecordStore,
    RecoveryNodeIndexValue,
    RequirementRevisionValue,
    RequirementsProjection,
    ResourceClaimValue,
    SchedulingProjection,
    SupportEvidenceValue,
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


def test_root_has_exactly_the_twelve_manifest_groups() -> None:
    assert set(ImmutableGraphProjection.model_fields) == ROOT_GROUPS


def test_manifest_retained_destinations_are_explicitly_owned() -> None:
    manifest = _manifest()
    destinations = _destination_paths(ImmutableGraphProjection)
    retained_paths = {
        entry["new_path"].replace(".*", "")
        for entry in manifest["fields"]
        if entry["new_path"] is not None
    }
    retained_paths.update(
        entry["new_path"].replace(".*", "") for entry in manifest["node_creation_ownership"]
    )

    assert retained_paths <= destinations


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
        DecisionValue,
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
