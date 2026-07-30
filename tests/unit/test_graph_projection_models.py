"""Observable contracts for the isolated immutable projection scaffold."""

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin, get_type_hints

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    Authority,
    AuthorityRequestRecord,
    AuthorityRequestRecordEnvelopeValue,
    CandidateProjection,
    CallbackEventValue,
    CleanupRequestValue,
    CommandDefinitionValue,
    DecisionActorValue,
    EdgeValue,
    EdgeProjection,
    EnvironmentFailureValue,
    ExecutionAuthorityValue,
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
    NodeCreationProjection,
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


def _concrete_annotation_models(annotation: object) -> set[type[BaseModel]]:
    return {
        model
        for model in _models_in_annotation(annotation)
        if model is not BaseModel and not get_args(model)
    }


def _grouped_paths_containing(root: type[BaseModel], targets: set[type[BaseModel]]) -> set[str]:
    paths: set[str] = set()

    def visit_annotation(annotation: object, path: str, ancestors: frozenset[object]) -> None:
        if annotation in targets:
            paths.add(path)
        if annotation in ancestors:
            return
        next_ancestors = ancestors | {annotation}
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            annotations = get_type_hints(annotation, include_extras=True)
            for name, field in annotation.model_fields.items():
                visit_annotation(
                    annotations.get(name, field.annotation),
                    f"{path}.{name}" if path else name,
                    next_ancestors,
                )
            return
        arguments = get_args(annotation)
        if get_origin(annotation) is Annotated:
            arguments = arguments[:1]
        for argument in arguments:
            visit_annotation(argument, path, next_ancestors)

    visit_annotation(root, "", frozenset())
    return paths


def _flatten_node_paths() -> set[str]:
    paths: set[str] = set()
    for group_name, group_type in (
        ("spec", NodeSpecProjection),
        ("runtime", NodeRuntimeProjection),
        ("scheduling", NodeSchedulingProjection),
    ):
        paths.update(f"nodes.*.{group_name}.{name}" for name in group_type.model_fields)
    return paths


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


def test_node_creation_ownership_exactly_matches_explicit_node_fields() -> None:
    manifest = _manifest()
    ownership = manifest["node_creation_ownership"]
    relationships = [(entry["field_name"], entry["new_path"]) for entry in ownership]
    node_relationships = {
        (source, destination)
        for source, destination in relationships
        if destination.startswith("nodes.*.")
    }
    flattened_by_name = {path.rsplit(".", 1)[-1]: path for path in _flatten_node_paths()}
    expected_node_relationships = {
        (source, flattened_by_name[source])
        for source in NodeCreationProjection.model_fields
        if source in flattened_by_name
    }
    expected_node_relationships.add(("position", flattened_by_name["creation_position"]))

    assert len(relationships) == len(set(relationships))
    assert len({source for source, _ in relationships}) == len(relationships)
    assert node_relationships == expected_node_relationships
    assert _flatten_node_paths() == {
        entry["new_path"]
        for entry in [*manifest["fields"], *ownership]
        if (entry.get("new_path") or "").startswith("nodes.*.")
    }
    assert set(NodeProjection.model_fields) == {"spec", "runtime", "scheduling"}
    assert not {
        name
        for name, field in NodeSpecProjection.model_fields.items()
        if name != "command_definition"
        and (field.annotation is Any or Any in get_args(field.annotation))
    }


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


def test_projection_map_revalidates_and_reconstructs_model_children() -> None:
    class UntrustedNode(NodeProjection):
        pass

    source = UntrustedNode(spec=NodeSpecProjection(node_id="node-1", creation_position=1))

    projection = ImmutableGraphProjection(nodes=FrozenMap({"node-1": source}))

    assert type(projection.nodes["node-1"]) is NodeProjection
    assert projection.nodes["node-1"] is not source
    assert projection.nodes["node-1"].spec is not source.spec


def test_projection_map_rejects_invalid_existing_model_children() -> None:
    invalid_spec = NodeSpecProjection.model_construct(
        node_id="node-1", creation_position=["not-an-integer"]
    )
    invalid_node = NodeProjection.model_construct(
        spec=invalid_spec,
        runtime=NodeRuntimeProjection(),
        scheduling=NodeSchedulingProjection(),
    )

    with pytest.raises(ValidationError):
        ImmutableGraphProjection(nodes=FrozenMap({"node-1": invalid_node}))


def test_populated_frozen_json_models_revalidate_exact_instances() -> None:
    command = CommandDefinitionValue.model_validate(
        {"value": {"argv": ["uv", "run", "pytest"], "options": {"quiet": True}}}
    )
    authority = AuthorityRequestRecordEnvelopeValue.model_validate(
        {
            "record_id": "authority-request-1",
            "record_kind": "graph_record",
            "record_type": "authority_request_record",
            "producer_node_id": "gate-1",
            "port": "authority_request_record",
            "schema": "AuthorityRequest",
            "payload": {"requirements": ["R-1"]},
            "provenance": {"event_ids": ["event-1"]},
            "value": {
                "requested_authority": ["graph_write"],
                "target_node_id": "worker-1",
                "reason": "required",
            },
        }
    )
    edge = EdgeValue.model_validate(
        {
            "edge_id": "edge-1",
            "from_node_id": "planner-1",
            "from_port": "candidate",
            "to_node_id": "worker-1",
            "to_port": "input",
            "accepted_record_selector": {"record_types": ["candidate"]},
            "metadata": {"labels": ["required"]},
        }
    )

    for value in (command, authority, edge):
        restored = type(value).model_validate(value)
        assert restored == value
        assert restored.model_dump(mode="json", by_alias=True) == value.model_dump(
            mode="json", by_alias=True
        )


def test_frozen_json_models_reject_frozen_map_subclasses() -> None:
    class UntrustedFrozenMap(FrozenMap[str, object]):
        pass

    value = UntrustedFrozenMap({"nested": ("value",)})
    cases = (
        (CommandDefinitionValue, {"value": value}),
        (
            AuthorityRequestRecordEnvelopeValue,
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "gate-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "payload": value,
                "value": {
                    "requested_authority": ["graph_write"],
                    "target_node_id": "worker-1",
                    "reason": "required",
                },
            },
        ),
        (
            EdgeValue,
            {
                "edge_id": "edge-1",
                "from_node_id": "planner-1",
                "from_port": "candidate",
                "to_node_id": "worker-1",
                "to_port": "input",
                "metadata": value,
            },
        ),
    )

    for model, payload in cases:
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_model_copy_shares_unchanged_immutable_fields() -> None:
    spec = NodeSpecProjection.model_validate(
        {
            "node_id": "node-1",
            "creation_position": 1,
            "command_definition": {"argv": ["uv", "run", "pytest"]},
            "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
        }
    )

    updated = spec.model_copy(update={"reason": "retry"})

    assert updated.command_definition is spec.command_definition
    assert updated.resource_claims is spec.resource_claims
    assert updated.reason == "retry"


def test_record_store_is_the_only_recursive_full_payload_owner() -> None:
    assert set(RecordStore.model_fields) == {
        "by_id",
        "ids_by_node_port",
        "summaries_by_id",
    }
    ids_annotation = RecordStore.model_fields["ids_by_node_port"].annotation
    assert get_origin(ids_annotation) is FrozenMap
    assert Mapping not in get_args(ids_annotation)

    record_models = _concrete_annotation_models(get_args(ProjectedRecord)[0])
    assert _grouped_paths_containing(ImmutableGraphProjection, record_models) == {"records.by_id"}


def test_recursive_full_payload_owner_guard_detects_a_second_group() -> None:
    class BadRecordGroup(ProjectionModel):
        duplicate_by_id: FrozenMap[str, ProjectedRecord] = FrozenMap()

    class BadRoot(ProjectionModel):
        records: RecordStore = RecordStore()
        bad_records: BadRecordGroup = BadRecordGroup()

    record_models = _concrete_annotation_models(get_args(ProjectedRecord)[0])
    paths = _grouped_paths_containing(BadRoot, record_models)

    assert paths == {"records.by_id", "bad_records.duplicate_by_id"}
    assert paths != {"records.by_id"}


def test_secondary_record_indexes_resolve_only_to_ids_or_compact_summaries() -> None:
    allowed_models = {GraphRecordSummaryProjection}
    allowed_scalars = {str}

    def invalid(annotation: object, ancestors: frozenset[object] = frozenset()) -> set[object]:
        if annotation in allowed_scalars or annotation in allowed_models:
            return set()
        if annotation in ancestors:
            return set()
        origin = get_origin(annotation)
        if origin is Annotated:
            return invalid(get_args(annotation)[0], ancestors | {annotation})
        if origin in {FrozenMap, tuple}:
            return set().union(
                *(
                    invalid(argument, ancestors | {annotation})
                    for argument in get_args(annotation)
                    if argument is not Ellipsis
                )
            )
        return {annotation}

    assert invalid(RecordStore.model_fields["ids_by_node_port"].annotation) == set()
    assert invalid(RecordStore.model_fields["summaries_by_id"].annotation) == set()


def test_new_models_are_available_from_public_graph_api() -> None:
    exported_models = {
        ProjectionModel,
        LifecycleProjection,
        ResourceClaimValue,
        ExecutionAuthorityValue,
        AuthorityRequestRecordEnvelopeValue,
        CommandDefinitionValue,
        DecisionActorValue,
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


def test_node_spec_freezes_complete_canonical_command_definition() -> None:
    command = {
        "id": "check-1",
        "cmd": "pytest",
        "argv": ["tests/unit"],
        "source": "routine",
        "must": True,
        "timeout_seconds": 30,
    }
    spec = NodeSpecProjection.model_validate(
        {"node_id": "node-1", "creation_position": 1, "command_definition": command}
    )

    command["argv"].append("--quiet")
    assert spec.command_definition.value["argv"] == ("tests/unit",)
    assert spec.model_dump(mode="json", by_alias=True)["command_definition"] == {
        "value": {
            "id": "check-1",
            "cmd": "pytest",
            "argv": ["tests/unit"],
            "source": "routine",
            "must": True,
            "timeout_seconds": 30,
        }
    }


@pytest.mark.parametrize(
    ("field", "payload", "message"),
    [
        (
            "decision_request",
            {"decision_type": "approval", "options": [], "consequence_summary": "deploys"},
            "at least one",
        ),
        ("authority_request", {"requested_authority": ["operator"], "reason": "review"}, "target"),
    ],
)
def test_node_request_values_preserve_source_invariants(
    field: str, payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        NodeSpecProjection.model_validate(
            {"node_id": "node-1", "creation_position": 1, field: payload}
        )


def test_node_request_values_preserve_complete_nondefault_payloads() -> None:
    decision = {
        "decision_type": "approval",
        "options": ["approve", "reject"],
        "default_option": "approve",
        "consequence_summary": "deploys",
        "expires_at": "2026-01-01T00:00:00Z",
        "target_node_id": "node-2",
        "target_region_id": "region-1",
    }
    authority = {
        "requested_authority": ["operator"],
        "target_node_id": "node-2",
        "reason": "requires approval",
        "expires_at": "2026-01-01T00:00:00Z",
    }
    spec = NodeSpecProjection.model_validate(
        {
            "node_id": "node-1",
            "creation_position": 1,
            "decision_request": decision,
            "authority_request": authority,
        }
    )

    decision["options"].append("defer")
    authority["requested_authority"].append("admin")
    dumped = spec.model_dump(mode="json")
    assert dumped["decision_request"] == {**decision, "options": ["approve", "reject"]}
    assert dumped["authority_request"] == {
        **authority,
        "requested_authority": ["operator"],
        "target_region_id": None,
    }


def test_node_execution_authority_preserves_canonical_json_and_isolated_children() -> None:
    raw = {
        "resource_claims": [
            {"mode": "write", "scope": "repo", "paths": ["docs/**"]},
            {"mode": "external", "scope": "service", "external_resource_key": "deploy"},
        ],
        "allowed_actions": ["submit_output", "deploy"],
        "preconditions": ["inputs_bound"],
    }
    canonical = Authority.model_validate(raw)
    expected = canonical.model_dump(mode="json", exclude_unset=False)
    spec = NodeSpecProjection.model_validate(
        {"node_id": "node-1", "creation_position": 1, "authority": canonical.model_dump()}
    )

    raw["resource_claims"][0]["paths"].append("src/**")
    raw["allowed_actions"].append("delete")
    assert spec.model_dump(mode="json")["authority"] == expected
    assert isinstance(spec.authority, ExecutionAuthorityValue)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        NodeSpecProjection.model_validate(
            {"node_id": "node-1", "creation_position": 1, "authority": {**raw, "unknown": True}}
        )


def test_wrapped_authority_request_record_preserves_canonical_json_and_isolation() -> None:
    raw = {
        "record_id": "authority-request-1",
        "record_kind": "graph_record",
        "record_type": "authority_request_record",
        "schema_version": 2,
        "producer_node_id": "planner-1",
        "producer_port": "authority_request_record",
        "port": "authority_request_record",
        "schema": "AuthorityRequest",
        "created_at": "2026-01-01T00:00:00Z",
        "graph_position": 7,
        "run_id": "run-1",
        "payload": {"source": {"ids": ["proposal-1"]}},
        "provenance": {"event_ids": ["event-1"]},
        "value": {
            "requested_authority": ["repo:docs/**:write"],
            "target_node_id": "worker-1",
            "target_region_id": "task-1",
            "reason": "Worker needs docs access.",
            "expires_at": "2026-02-01T00:00:00Z",
        },
    }
    canonical = AuthorityRequestRecord.model_validate(raw)
    expected = canonical.model_dump(mode="json", by_alias=True)
    spec = NodeSpecProjection.model_validate(
        {
            "node_id": "gate-authority",
            "creation_position": 1,
            "authority_request_record": canonical.model_dump(mode="json"),
        }
    )

    raw["value"]["requested_authority"].append("graph_write")
    raw["payload"]["source"]["ids"].append("proposal-2")
    assert spec.model_dump(mode="json", by_alias=True)["authority_request_record"] == expected
    assert isinstance(spec.authority_request_record, AuthorityRequestRecordEnvelopeValue)

    with pytest.raises(ValidationError, match="literal_error"):
        NodeSpecProjection.model_validate(
            {
                "node_id": "gate-authority",
                "creation_position": 1,
                "authority_request_record": {**canonical.model_dump(), "schema": "Wrong"},
            }
        )


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
