from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestrator.config import (
    RoutineConfig,
    SemanticArtifactSchemaConfig,
    StepConfig,
    TaskConfig,
    load_routine_from_path,
)
from orchestrator.graph import (
    FakeClock,
    PatchEnvelope,
    PatchCommandContext,
    PatchOp,
    SemanticArtifactRecord,
    SemanticSchemaDeclarationRecord,
    SequentialIdGenerator,
    SubmitPatchCommand,
    VerificationReportRecord,
    apply_command,
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


def _macro_patch_many(invocations: list[dict[str, Any]]) -> PatchEnvelope:
    command = SubmitPatchCommand.model_validate(
        {
            "patch_id": "patch-reliable-plan-skeleton",
            "base_graph_position": 0,
            "macro_invocations": invocations,
        }
    )
    ops = expand_patch_macros(command.ops, command.macro_invocations, "planner-initial")
    return PatchEnvelope(
        patch_id=command.patch_id,
        proposed_by_node_id="planner-initial",
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


def _artifact(
    *,
    batches: list[dict[str, str]],
    record_id: str = "accepted-plan",
) -> SemanticArtifactRecord:
    return SemanticArtifactRecord.model_validate(
        {
            "record_id": record_id,
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


def _verification_report(
    *,
    evaluated_record_ids: list[str],
    record_id: str = "plan-verification-passed",
) -> VerificationReportRecord:
    return VerificationReportRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": "verifier-plan",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": "accepted-plan",
            "task_region_id": "plan-verification",
            "outcome": "passed",
            "value": {"outcome": "passed", "grades": []},
            "evaluated_record_ids": evaluated_record_ids,
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


def test_production_dynamic_graph_routine_compiles_reliable_plan_schema_snapshot() -> None:
    routine_path = Path("routines/dynamic-graph-feature/routine.yaml")
    routine = load_routine_from_path(routine_path)

    projection = build_projection(
        compile_routine(
            routine,
            FakeClock(),
            SequentialIdGenerator(),
            run_id="run-production-reliable-plan-schema",
            source_path=str(routine_path),
            run_config={
                "feature_spec_path": "docs/spec.md",
                "acceptance_command": "uv run pytest",
            },
        )
    )

    declaration = semantic_schema_declarations_view(projection)[
        ("reliable-plan-implementation-plan", 1)
    ]
    assert declaration.value.authority == "routine_snapshot"
    assert declaration.value.semantic_role == "implementation_plan"
    assert declaration.value.json_schema["required"] == ("batches",)


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


def test_reliable_plan_initial_skeleton_is_one_atomic_pass_gated_topology() -> None:
    projection = build_projection(
        [
            event("output_record_accepted", _declaration().model_dump(mode="json")),
            event(
                "node_created",
                {
                    "node_id": "planner-initial",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "reliable_plan_skeleton_id": "reliable-plan-v1",
                    "reliable_plan_one_horizon_authorized": True,
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
                    "outputs": [
                        {
                            "port": "requirement",
                            "direction": "output",
                            "schema": "Requirement",
                        }
                    ],
                },
                position=2,
            ),
        ]
    )
    patch = _macro_patch_many(
        [
            {
                "macro": "create_discovery_region",
                "args": {
                    "region_id": "discovery",
                    "worker_id": "worker-discovery",
                    "semantic_schema_id": "ordered-batch-plan",
                    "semantic_schema_version": 1,
                    "objective": "Discover the implementation plan.",
                    "acceptance": ["plan is complete"],
                    "requirement_source_node_ids": ["requirement-1"],
                },
            },
            {
                "macro": "create_plan_verification",
                "args": {
                    "region_id": "plan-verification",
                    "verifier_id": "verifier-plan",
                    "artifact_source_node_id": "worker-discovery",
                    "semantic_schema_id": "ordered-batch-plan",
                    "semantic_schema_version": 1,
                    "objective": "Independently verify the plan.",
                    "acceptance": ["requirements are covered"],
                    "rubric": ["every requirement maps to a batch"],
                    "requirement_source_node_ids": ["requirement-1"],
                },
            },
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "successor",
                    "node_id": "planner-successor",
                    "evidence_source_node_id": "verifier-plan",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 1,
                },
            },
        ]
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is True
    successor_edge = next(op for op in patch.ops if op.to_node_id == "planner-successor")
    assert successor_edge.from_node_id == "verifier-plan"
    assert successor_edge.accepted_record_selector is not None
    assert successor_edge.accepted_record_selector.model_dump(mode="json")["outcome"] == "passed"


def test_reliable_plan_successor_only_patch_fails_closed_with_diagnostics() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "planner-initial",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "reliable_plan_skeleton_id": "reliable-plan-v1",
                    "reliable_plan_one_horizon_authorized": True,
                },
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
                position=1,
            ),
        ]
    )
    patch = _macro_patch_many(
        [
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "successor",
                    "node_id": "planner-successor",
                    "evidence_source_node_id": "verifier-plan",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 1,
                },
            }
        ]
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "missing_or_ambiguous_discovery"


@pytest.mark.parametrize(
    "extra_node",
    [
        {
            "node_id": "worker-bypass",
            "kind": "worker",
            "role": "implementer",
            "state": "planned",
            "objective": "Bypass verification.",
            "access_mode": "write",
            "acceptance": ["write happened"],
        },
        {
            "node_id": "oversight-bypass",
            "kind": "oversight",
            "role": "oversight",
            "state": "planned",
        },
    ],
    ids=["generic-worker", "oversight"],
)
def test_reliable_plan_initial_skeleton_rejects_extra_dispatchable_atomically(
    extra_node: dict[str, Any],
) -> None:
    projection = build_projection(
        [
            event("output_record_accepted", _declaration().model_dump(mode="json")),
            event(
                "node_created",
                {
                    "node_id": "planner-initial",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "reliable_plan_skeleton_id": "reliable-plan-v1",
                    "reliable_plan_one_horizon_authorized": True,
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
                    "outputs": [
                        {
                            "port": "requirement",
                            "direction": "output",
                            "schema": "Requirement",
                        }
                    ],
                },
                position=2,
            ),
        ]
    )
    patch = _macro_patch_many(
        [
            {
                "macro": "create_discovery_region",
                "args": {
                    "region_id": "discovery",
                    "worker_id": "worker-discovery",
                    "semantic_schema_id": "ordered-batch-plan",
                    "semantic_schema_version": 1,
                    "objective": "Discover the implementation plan.",
                    "acceptance": ["plan is complete"],
                    "requirement_source_node_ids": ["requirement-1"],
                },
            },
            {
                "macro": "create_plan_verification",
                "args": {
                    "region_id": "plan-verification",
                    "verifier_id": "verifier-plan",
                    "artifact_source_node_id": "worker-discovery",
                    "semantic_schema_id": "ordered-batch-plan",
                    "semantic_schema_version": 1,
                    "objective": "Independently verify the plan.",
                    "acceptance": ["requirements are covered"],
                    "rubric": ["every requirement maps to a batch"],
                    "requirement_source_node_ids": ["requirement-1"],
                },
            },
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "successor",
                    "node_id": "planner-successor",
                    "evidence_source_node_id": "verifier-plan",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 1,
                },
            },
        ]
    )
    patch = patch.model_copy(
        update={
            "ops": [
                *patch.ops,
                PatchOp.model_validate(
                    {
                        "op": "create_node",
                        "node": extra_node,
                    }
                ),
            ]
        }
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "unexpected_initial_executable_nodes"
    assert result.diagnostics["unexpected_executable_node_ids"] == [extra_node["node_id"]]

    command_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": patch.patch_id,
            "base_graph_position": 2,
            "ops": [op.model_dump(mode="json") for op in patch.ops],
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=2,
            proposed_by_node_id="planner-initial",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert [event.event_type for event in command_events] == ["graph_patch_rejected"]
    assert not any(
        event.event_type in {"node_created", "node_state_changed", "lease_granted"}
        for event in command_events
    )


def test_reliable_plan_successor_stage_cannot_masquerade_as_write_worker() -> None:
    projection = build_projection(
        [
            event("output_record_accepted", _declaration().model_dump(mode="json")),
            event(
                "node_created",
                {
                    "node_id": "planner-initial",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "reliable_plan_skeleton_id": "reliable-plan-v1",
                    "reliable_plan_one_horizon_authorized": True,
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
                    "outputs": [
                        {
                            "port": "requirement",
                            "direction": "output",
                            "schema": "Requirement",
                        }
                    ],
                },
                position=2,
            ),
        ]
    )
    patch = _macro_patch_many(
        [
            {
                "macro": "create_discovery_region",
                "args": {
                    "region_id": "discovery",
                    "worker_id": "worker-discovery",
                    "semantic_schema_id": "ordered-batch-plan",
                    "semantic_schema_version": 1,
                    "objective": "Discover the implementation plan.",
                    "acceptance": ["plan is complete"],
                    "requirement_source_node_ids": ["requirement-1"],
                },
            },
            {
                "macro": "create_plan_verification",
                "args": {
                    "region_id": "plan-verification",
                    "verifier_id": "verifier-plan",
                    "artifact_source_node_id": "worker-discovery",
                    "semantic_schema_id": "ordered-batch-plan",
                    "semantic_schema_version": 1,
                    "objective": "Independently verify the plan.",
                    "acceptance": ["requirements are covered"],
                    "rubric": ["every requirement maps to a batch"],
                    "requirement_source_node_ids": ["requirement-1"],
                },
            },
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "successor",
                    "node_id": "planner-successor",
                    "evidence_source_node_id": "verifier-plan",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 1,
                },
            },
        ]
    )
    patch = patch.model_copy(
        update={
            "ops": [
                op.model_copy(
                    update={
                        "node": {
                            **op.node,
                            "kind": "worker",
                            "role": "implementer",
                            "access_mode": "write",
                            "objective": "Masquerade as the successor planner.",
                            "acceptance": ["implementation happened"],
                        }
                    }
                )
                if op.node is not None and op.node.get("node_id") == "planner-successor"
                else op
                for op in patch.ops
            ]
        }
    )

    result = validate_patch(patch, 0, [], projection, "planner")
    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "invalid_successor_contract"

    command_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": patch.patch_id,
            "base_graph_position": 2,
            "ops": [op.model_dump(mode="json") for op in patch.ops],
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=2,
            proposed_by_node_id="planner-initial",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert [event.event_type for event in command_events] == ["graph_patch_rejected"]
    assert not any(
        event.event_type in {"node_created", "node_state_changed", "lease_granted"}
        for event in command_events
    )


def test_effectful_batch_macro_requires_plan_verification_checks_and_distinct_region() -> None:
    declaration = _declaration()
    artifact = _artifact(batches=[{"batch_id": "batch-1"}, {"batch_id": "batch-2"}])
    report = _verification_report(evaluated_record_ids=[artifact.record_id])
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
                    "node_id": "planner-1",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "semantic_stage": "successor_planning",
                    "reliable_plan_skeleton_id": "reliable-plan-v1",
                },
                position=1,
            ),
            event(
                "node_created",
                {
                    "node_id": "worker-discovery",
                    "kind": "worker",
                    "role": "discovery",
                    "state": "completed",
                },
                position=2,
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
                position=3,
            ),
            event(
                "node_created",
                {
                    "node_id": "requirement-1",
                    "kind": "requirement",
                    "role": "requirement",
                    "state": "completed",
                },
                position=4,
            ),
            event("output_record_accepted", declaration.model_dump(mode="json"), position=5),
            event("output_record_accepted", artifact.model_dump(mode="json"), position=6),
            event("output_record_accepted", report.model_dump(mode="json"), position=7),
            event(
                "edge_created",
                {
                    "edge_id": "edge-verifier-plan-to-successor",
                    "from_node_id": "verifier-plan",
                    "from_port": "verification_report",
                    "to_node_id": "planner-1",
                    "to_port": "verification_report",
                    "schemas": ["VerificationReport"],
                },
                position=8,
            ),
            event(
                "input_bound",
                {
                    "edge_id": "edge-verifier-plan-to-successor",
                    "to_node_id": "planner-1",
                    "to_port": "verification_report",
                    "record_ids": [report.record_id],
                    "bound_at_position": 7,
                },
                position=9,
            ),
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


def test_effectful_batch_rejects_pass_report_for_a_different_plan_artifact() -> None:
    declaration = _declaration()
    artifact = _artifact(batches=[{"batch_id": "batch-1"}])
    report = _verification_report(evaluated_record_ids=["different-plan"])
    projection_events = [
        event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "leased",
                "semantic_stage": "successor_planning",
                "reliable_plan_skeleton_id": "reliable-plan-v1",
            },
        ),
        event(
            "node_created",
            {"node_id": "worker-discovery", "kind": "worker", "state": "completed"},
            position=1,
        ),
        event(
            "node_created",
            {
                "node_id": "verifier-plan",
                "kind": "verifier",
                "state": "completed",
                "semantic_stage": "plan_verification",
            },
            position=2,
        ),
        event(
            "node_created",
            {"node_id": "requirement-1", "kind": "requirement", "state": "completed"},
            position=3,
        ),
        event("output_record_accepted", declaration.model_dump(mode="json"), position=4),
        event("output_record_accepted", artifact.model_dump(mode="json"), position=5),
        event("output_record_accepted", report.model_dump(mode="json"), position=6),
        event(
            "input_bound",
            {
                "to_node_id": "planner-1",
                "to_port": "verification_report",
                "record_ids": [report.record_id],
                "bound_at_position": 6,
            },
            position=7,
        ),
    ]
    projection = build_projection(projection_events)
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
            "rubric": ["candidate satisfies batch 1"],
            "planning_horizon": 1,
        },
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "unverified_exact_plan_lineage"
    assert result.diagnostics["accepted_plan_record_ids"] == ["accepted-plan"]
    assert result.diagnostics["lineage_verified_report_ids"] == []

    command_events = apply_command(
        projection,
        projection_events,
        "submit_patch",
        {
            "patch_id": "patch-unverified-effectful-batch",
            "base_graph_position": 7,
            "ops": [op.model_dump(mode="json") for op in patch.ops],
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=7,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert [event.event_type for event in command_events] == ["graph_patch_rejected"]
    assert command_events[0].payload["diagnostics"]["violation"] == (
        "unverified_exact_plan_lineage"
    )
    assert not any(
        event.event_type in {"node_created", "node_state_changed", "lease_granted"}
        for event in command_events
    )


def test_effectful_batch_rejects_report_for_later_plan_when_bind_first_uses_earlier() -> None:
    declaration = _declaration()
    plan_a = _artifact(batches=[{"batch_id": "batch-1"}], record_id="accepted-plan-a")
    plan_b = _artifact(batches=[{"batch_id": "batch-1"}], record_id="accepted-plan-b")
    report_b = _verification_report(
        evaluated_record_ids=[plan_b.record_id],
        record_id="plan-b-verification-passed",
    )
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "planner-1",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "semantic_stage": "successor_planning",
                    "reliable_plan_skeleton_id": "reliable-plan-v1",
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
            event("output_record_accepted", plan_a.model_dump(mode="json"), position=5),
            event("output_record_accepted", plan_b.model_dump(mode="json"), position=6),
            event("output_record_accepted", report_b.model_dump(mode="json"), position=7),
            event(
                "input_bound",
                {
                    "to_node_id": "planner-1",
                    "to_port": "verification_report",
                    "record_ids": [report_b.record_id],
                    "bound_at_position": 7,
                },
                position=8,
            ),
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
            "rubric": ["candidate satisfies batch 1"],
            "planning_horizon": 1,
        },
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "unverified_exact_plan_lineage"
    assert result.diagnostics["effective_plan_record_ids"] == ["accepted-plan-a"]
    assert result.diagnostics["effective_verification_record_ids"] == ["plan-b-verification-passed"]
    assert result.diagnostics["lineage_verified_report_ids"] == []
