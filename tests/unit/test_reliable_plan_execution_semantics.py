from __future__ import annotations

from typing import Any

import pytest

from orchestrator.config import RoutineConfig, SemanticArtifactSchemaConfig, StepConfig, TaskConfig
from orchestrator.graph import (
    FakeClock,
    PatchEnvelope,
    PatchOp,
    SemanticArtifactRecord,
    SemanticSchemaDeclarationRecord,
    SequentialIdGenerator,
    SubmitPatchCommand,
    build_projection,
    compile_routine,
    expand_patch_macros,
    initial_projection,
    semantic_schema_declarations_view,
    semantic_declaration_conflict,
    validate_patch,
    validate_semantic_artifact_content,
)
from tests.unit.graph_test_utils import event


PLAN_SCHEMA = SemanticArtifactSchemaConfig(
    schema_id="ordered-batch-plan",
    version=1,
    semantic_role="implementation_plan",
    json_schema={
        "type": "object",
        "required": ["batches"],
        "properties": {
            "batches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["batch_id"],
                    "properties": {"batch_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    },
)


def _macro_patch(macro: str, args: dict[str, Any]) -> PatchEnvelope:
    command = SubmitPatchCommand.model_validate(
        {
            "patch_id": f"patch-{macro}",
            "base_graph_position": 0,
            "macro_invocations": [{"macro": macro, "args": args}],
        }
    )
    ops = expand_patch_macros(command.ops, command.macro_invocations, "planner-1")
    return PatchEnvelope(
        patch_id=command.patch_id,
        proposed_by_node_id="planner-1",
        base_graph_position=0,
        ops=[PatchOp(**op) for op in ops],
    )


def _declaration() -> SemanticSchemaDeclarationRecord:
    return SemanticSchemaDeclarationRecord.model_validate(
        {
            "record_id": "schema-plan-v1",
            "record_kind": "graph_record",
            "record_type": "semantic_schema_declaration",
            "schema_version": 1,
            "producer_node_id": "routine-snapshot",
            "port": "semantic_schema_declaration",
            "schema": "SemanticSchemaDeclaration",
            "value": {**PLAN_SCHEMA.model_dump(mode="json"), "authority": "routine_snapshot"},
        }
    )


def _artifact(*, batches: list[dict[str, str]]) -> SemanticArtifactRecord:
    return SemanticArtifactRecord.model_validate(
        {
            "record_id": "accepted-plan",
            "record_kind": "graph_record",
            "record_type": "semantic_artifact",
            "schema_version": 1,
            "producer_node_id": "worker-discovery",
            "producer_port": "semantic_artifact",
            "port": "semantic_artifact",
            "schema": "SemanticArtifact",
            "value": {
                "semantic_role": "implementation_plan",
                "schema_id": "ordered-batch-plan",
                "schema_version": 1,
                "content": {"batches": batches},
                "provenance": {"source": "discovery"},
                "source_record_ids": [],
                "requirement_ids": ["REQ-1"],
                "task_region_id": "discovery",
                "validation_status": "validated",
                "authority_status": "accepted",
            },
        }
    )


def test_compiler_seeds_versioned_run_scoped_semantic_schema_as_accepted_record() -> None:
    routine = RoutineConfig(
        id="semantic-routine",
        name="Semantic routine",
        semantic_artifact_schemas=[PLAN_SCHEMA],
        steps=[StepConfig(id="S1", title="Work", tasks=[TaskConfig(id="T1", title="Do")])],
    )

    events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-semantic",
    )
    projection = build_projection(events)
    declarations = semantic_schema_declarations_view(projection)

    declaration = declarations[("ordered-batch-plan", 1)]
    assert declaration.value.authority == "routine_snapshot"
    assert declaration.value.semantic_role == "implementation_plan"
    assert declaration.run_id is None


def test_compiler_input_rejects_invalid_routine_schema_before_seeding_records() -> None:
    with pytest.raises(ValueError, match="semantic artifact json_schema is invalid"):
        routine = RoutineConfig.model_validate(
            {
                "id": "invalid-semantic-routine",
                "name": "Invalid semantic routine",
                "semantic_artifact_schemas": [
                    {
                        "schema_id": "ordered-batch-plan",
                        "version": 1,
                        "semantic_role": "implementation_plan",
                        "json_schema": {"type": "object", "required": "batches"},
                    }
                ],
                "steps": [{"id": "S1", "title": "Work", "tasks": [{"id": "T1", "title": "Do"}]}],
            }
        )
        compile_routine(
            routine,
            FakeClock(),
            SequentialIdGenerator(),
            run_id="run-invalid-semantic",
        )


def test_semantic_artifact_content_requires_exact_accepted_declaration() -> None:
    declaration = _declaration()
    artifact = _artifact(batches=[{"batch_id": "batch-1"}])

    assert (
        validate_semantic_artifact_content(artifact, {("ordered-batch-plan", 1): declaration})
        is None
    )
    invalid = artifact.model_copy(
        update={"value": artifact.value.model_copy(update={"content": {"batches": [{}]}})}
    )
    assert "'batch_id' is a required property" in str(
        validate_semantic_artifact_content(invalid, {("ordered-batch-plan", 1): declaration})
    )
    assert "undeclared schema" in str(validate_semantic_artifact_content(artifact, {}))


def test_semantic_artifact_content_honors_string_array_composition_and_conditionals() -> None:
    declaration = _declaration().model_copy(
        update={
            "value": _declaration().value.model_copy(
                update={
                    "json_schema": {
                        "type": "object",
                        "required": ["name", "items", "mode"],
                        "properties": {
                            "name": {"type": "string", "minLength": 3, "pattern": "^[a-z]+$"},
                            "items": {"type": "array", "minItems": 1, "uniqueItems": True},
                            "mode": {"enum": ["relaxed", "strict"]},
                        },
                        "allOf": [
                            {
                                "if": {"properties": {"mode": {"const": "strict"}}},
                                "then": {"properties": {"items": {"minItems": 2}}},
                            }
                        ],
                        "additionalProperties": False,
                    }
                }
            )
        }
    )
    declarations = {("ordered-batch-plan", 1): declaration}

    for content, keyword in (
        ({"name": "X", "items": [1], "mode": "relaxed"}, "minLength"),
        ({"name": "ABC", "items": [1], "mode": "relaxed"}, "pattern"),
        ({"name": "abc", "items": [], "mode": "relaxed"}, "minItems"),
        ({"name": "abc", "items": [1, 1], "mode": "relaxed"}, "uniqueItems"),
        ({"name": "abc", "items": [1], "mode": "strict"}, "minItems"),
        ({"name": "abc", "items": [1], "mode": "relaxed", "extra": True}, "additionalProperties"),
    ):
        artifact = _artifact(batches=[]).model_copy(
            update={"value": _artifact(batches=[]).value.model_copy(update={"content": content})}
        )
        assert f"keyword={keyword}" in str(
            validate_semantic_artifact_content(artifact, declarations)
        )


def test_semantic_schema_declaration_rejects_invalid_json_schema() -> None:
    declaration = _declaration().model_copy(
        update={
            "value": _declaration().value.model_copy(
                update={"json_schema": {"type": "object", "required": "name"}}
            )
        }
    )

    error = semantic_declaration_conflict(declaration, {})

    assert error is not None
    assert "semantic schema declaration ordered-batch-plan@1 is invalid" in error


def test_planner_schema_amendment_cannot_remove_unmodeled_string_constraints() -> None:
    original = _declaration().model_copy(
        update={
            "value": _declaration().value.model_copy(
                update={
                    "json_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "pattern": "^[a-z]+$", "minLength": 3}
                        },
                    }
                }
            )
        }
    )
    amended = original.model_copy(
        update={
            "record_id": "schema-plan-v2",
            "producer_node_id": "planner-1",
            "schema_version": 2,
            "value": original.value.model_copy(
                update={
                    "version": 2,
                    "authority": "planner_amendment",
                    "supersedes_declaration_record_id": original.record_id,
                    "json_schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            ),
        }
    )

    error = semantic_declaration_conflict(
        amended,
        {(original.value.schema_id, original.value.version): original},
    )

    assert error is not None
    assert "changes schema without an authorized equivalence proof" in error


def test_discovery_and_plan_verification_macros_preserve_read_only_typed_handoff() -> None:
    discovery = _macro_patch(
        "create_discovery_region",
        {
            "region_id": "discovery",
            "semantic_schema_id": "ordered-batch-plan",
            "semantic_schema_version": 1,
            "objective": "Discover the ordered implementation batches.",
            "acceptance": ["inventory and batches are complete"],
        },
    )
    result = validate_patch(
        discovery,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )
    assert result.accepted is False
    assert result.rejection_reason == (
        "semantic discovery stage requires an accepted exact schema declaration"
    )
    declared_projection = build_projection(
        [event("output_record_accepted", _declaration().model_dump(mode="json"))]
    )
    result = validate_patch(
        discovery,
        current_position=0,
        events_since_base=[],
        projection=declared_projection,
        actor_role="planner",
    )
    assert result.accepted is True
    worker = discovery.ops[0].node
    assert worker is not None
    assert worker["access_mode"] == "read_only"
    assert worker["authority"]["resource_claims"][0]["mode"] == "read"

    projection = build_projection(
        [
            event("output_record_accepted", _declaration().model_dump(mode="json")),
            event(
                "node_created",
                {
                    **worker,
                    "node_id": "worker-discovery",
                    "state": "completed",
                },
                position=1,
            ),
            event(
                "node_created",
                {
                    "node_id": "requirement-1",
                    "kind": "requirement",
                    "role": "requirement",
                    "state": "completed",
                },
                position=2,
            ),
        ]
    )
    verification = _macro_patch(
        "create_plan_verification",
        {
            "region_id": "plan-verification",
            "artifact_source_node_id": "worker-discovery",
            "semantic_schema_id": "ordered-batch-plan",
            "semantic_schema_version": 1,
            "objective": "Verify the discovered ordered batch plan.",
            "acceptance": ["all requirements map to ordered batches"],
            "requirement_source_node_ids": ["requirement-1"],
            "rubric": ["plan covers REQ-1"],
        },
    )
    result = validate_patch(
        verification,
        current_position=0,
        events_since_base=[],
        projection=projection,
        actor_role="planner",
    )
    assert result.accepted is True


def test_effectful_batch_macro_requires_plan_verification_checks_and_distinct_region() -> None:
    declaration = _declaration()
    artifact = _artifact(batches=[{"batch_id": "batch-1"}, {"batch_id": "batch-2"}])
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "routine-snapshot",
                    "kind": "artifact",
                    "role": "routine_snapshot",
                    "state": "completed",
                },
            ),
            event(
                "node_created",
                {
                    "node_id": "worker-discovery",
                    "kind": "worker",
                    "role": "discovery",
                    "state": "completed",
                },
                position=1,
            ),
            event(
                "node_created",
                {
                    "node_id": "verifier-plan",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "completed",
                    "semantic_stage": "plan_verification",
                },
                position=2,
            ),
            event(
                "node_created",
                {
                    "node_id": "requirement-1",
                    "kind": "requirement",
                    "role": "requirement",
                    "state": "completed",
                },
                position=3,
            ),
            event("output_record_accepted", declaration.model_dump(mode="json"), position=4),
            event("output_record_accepted", artifact.model_dump(mode="json"), position=5),
        ]
    )
    patch = _macro_patch(
        "create_effectful_batch",
        {
            "region_id": "region-batch-1",
            "batch_id": "batch-1",
            "plan_source_node_id": "worker-discovery",
            "plan_verification_source_node_id": "verifier-plan",
            "semantic_schema_id": "ordered-batch-plan",
            "semantic_schema_version": 1,
            "objective": "Implement only batch 1.",
            "acceptance": ["batch 1 checks pass"],
            "requirement_source_node_ids": ["requirement-1"],
            "checks": [
                {"check_id": "check-batch-1", "command_binding": "dynamic_feature_hidden_oracle"}
            ],
            "rubric": ["candidate satisfies batch 1 and REQ-1"],
            "planning_horizon": 1,
        },
    )
    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=projection,
        actor_role="planner",
    )
    assert result.accepted is True
    assert {
        op.node["task_region_id"]
        for op in patch.ops
        if op.node is not None and op.node.get("kind") in {"worker", "check", "verifier"}
    } == {"region-batch-1"}
