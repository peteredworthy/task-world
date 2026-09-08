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
    ReliablePlanAssignmentCarrier,
    SemanticArtifactRecord,
    SemanticSchemaDeclarationRecord,
    SequentialIdGenerator,
    SubmitPatchCommand,
    VerificationReportRecord,
    apply_command,
    build_projection,
    classify_write_worker_semantics,
    compile_routine,
    correction_superseded_task_region_id,
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


def _reliable_plan_carrier() -> ReliablePlanAssignmentCarrier:
    assignment = {
        "runner_type": "codex_server",
        "model": "gpt-test",
        "profile": "architect",
    }
    return ReliablePlanAssignmentCarrier.model_validate(
        {
            "skeleton_id": "reliable-plan-fff4f6b7-v1",
            "selected_runner_type": "codex_server",
            "arm": {
                "arm_id": "test-arm",
                "planner": assignment,
                "discovery_worker": {**assignment, "profile": "summarizer"},
                "implementation_worker": {**assignment, "profile": "coder"},
                "correction_worker": {**assignment, "profile": "coder"},
                "verifier": {**assignment, "profile": "coder"},
                "successor_planner": assignment,
            },
        }
    )


def _reliable_plan_planner_fields(*, successor: bool = False) -> dict[str, Any]:
    carrier = _reliable_plan_carrier()
    role = "successor_planner" if successor else "planner"
    assignment = carrier.assignment_for(role)
    return {
        "reliable_plan_skeleton_id": carrier.skeleton_id,
        "reliable_plan_assignment_carrier": carrier.model_dump(mode="json"),
        "reliable_plan_assignment_role": role,
        "reliable_plan_selected_runner_type": carrier.selected_runner_type,
        "runner_model_override": assignment.model,
        "profile": assignment.profile.value,
    }


def _macro_patch(macro: str, args: dict[str, Any]) -> PatchEnvelope:
    return _macro_patch_for_planner(
        patch_id=f"patch-{macro}",
        invocations=[{"macro": macro, "args": args}],
    )


def _macro_patch_for_planner(*, patch_id: str, invocations: list[dict[str, Any]]) -> PatchEnvelope:
    expanded_invocations = list(invocations)
    for invocation in invocations:
        if invocation.get("macro") != "create_effectful_batch":
            continue
        batch_id = str(invocation["args"]["batch_id"])
        verifier_id = str(invocation["args"].get("verifier_id", f"verifier-batch-{batch_id}"))
        expanded_invocations.append(
            {
                "macro": "create_gap_planner",
                "args": {
                    "region_id": f"recovery-{batch_id}",
                    "node_id": f"planner-gap-{batch_id}",
                    "evidence_source_node_id": verifier_id,
                    "evidence_source_port": "verification_report",
                },
            }
        )
    command = SubmitPatchCommand.model_validate(
        {
            "patch_id": patch_id,
            "base_graph_position": 0,
            "macro_invocations": expanded_invocations,
        }
    )
    ops = expand_patch_macros(command.ops, command.macro_invocations, "planner-1")
    return PatchEnvelope(
        patch_id=command.patch_id,
        proposed_by_node_id="planner-1",
        base_graph_position=0,
        ops=[PatchOp(**op) for op in ops],
    )


def _atomic_nonfinal_batch_patch(args: dict[str, Any]) -> PatchEnvelope:
    batch_id = str(args["batch_id"])
    planning_horizon = int(args["planning_horizon"])
    return _macro_patch_for_planner(
        patch_id=f"patch-atomic-{batch_id}",
        invocations=[
            {"macro": "create_effectful_batch", "args": args},
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": f"successor-{batch_id}",
                    "node_id": f"planner-h{planning_horizon + 1}",
                    "evidence_source_node_id": f"verifier-batch-{batch_id}",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": planning_horizon + 1,
                },
            },
        ],
    )


def _macro_patch_many(invocations: list[dict[str, Any]]) -> PatchEnvelope:
    expanded_invocations = list(invocations)
    plan_verifiers = [
        invocation["args"]["verifier_id"]
        for invocation in invocations
        if invocation.get("macro") == "create_plan_verification"
    ]
    for verifier_id in plan_verifiers:
        expanded_invocations.append(
            {
                "macro": "create_gap_planner",
                "args": {
                    "region_id": f"recovery-{verifier_id}",
                    "node_id": f"planner-gap-{verifier_id}",
                    "evidence_source_node_id": verifier_id,
                    "evidence_source_port": "verification_report",
                },
            }
        )
    command = SubmitPatchCommand.model_validate(
        {
            "patch_id": "patch-reliable-plan-skeleton",
            "base_graph_position": 0,
            "macro_invocations": expanded_invocations,
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


def _semantic_plan_revision_facts(
    mutation: str | None = None,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    artifact_id = "accepted-plan"
    report_id = "plan-verification-failed"
    worker_id = "worker-plan-revision"
    consumer_id = "verifier-plan-revision"
    declaration = _declaration().model_dump(mode="json")
    artifact = _artifact(batches=[{"batch_id": "batch-1"}]).model_dump(mode="json")
    artifact["value"]["requirement_ids"] = ["requirement-1"]
    report = {
        "record_id": report_id,
        "record_kind": "verification",
        "record_type": "verification_report",
        "producer_node_id": "verifier-plan",
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": artifact_id,
        "candidate_record_id": artifact_id,
        "candidate_record_ids": [artifact_id],
        "task_region_id": "plan-verification",
        "outcome": "failed",
        "value": {"outcome": "failed", "grades": []},
        "evaluated_record_ids": [artifact_id, "requirement-1"],
    }
    discovery = {
        "node_id": "worker-discovery",
        "kind": "worker",
        "role": "discovery",
        "state": "completed",
        "access_mode": "read_only",
        "effect_contract": "read_only_semantic",
        "semantic_stage": "discovery",
        "semantic_schema_id": "ordered-batch-plan",
        "semantic_schema_version": 1,
    }
    plan_verifier = {
        "node_id": "verifier-plan",
        "kind": "verifier",
        "role": "verifier",
        "state": "completed",
        "semantic_stage": "plan_verification",
        "semantic_schema_id": "ordered-batch-plan",
        "semantic_schema_version": 1,
    }
    consumer = {
        "node_id": consumer_id,
        "kind": "verifier",
        "role": "verifier",
        "state": "planned",
        "task_region_id": "plan-revision",
        "failed_candidate_id": artifact_id,
    }
    node = {
        "node_id": worker_id,
        "kind": "worker",
        "role": "fixer",
        "state": "planned",
        "task_region_id": "plan-revision",
        "candidate_id": "revised-plan",
        "failed_candidate_id": artifact_id,
        "recovery_of_record_id": artifact_id,
        "access_mode": "write",
        "effect_contract": "effectful_write",
        "semantic_stage": "corrective_work",
        "semantic_schema_id": "ordered-batch-plan",
        "semantic_schema_version": 1,
        "bound_requirement_ids": ["REQ-1"],
        "objective": "Revise the rejected typed plan.",
        "acceptance": ["The revised plan fixes the failed grade."],
        "outputs": [
            {
                "port": "candidate",
                "direction": "output",
                "schema": "ImplementationCandidate",
                "required": True,
            },
            {
                "port": "semantic_artifact",
                "direction": "output",
                "schema": "SemanticArtifact",
                "required": True,
            },
        ],
    }
    edges = [
        {
            "op": "create_edge",
            "edge_id": "failed-report-to-revision",
            "from_node_id": "verifier-plan",
            "from_port": "verification_report",
            "to_node_id": worker_id,
            "to_port": "verification_report",
            "required": True,
            "dependency_type": "input_binding",
            "accepted_record_selector": {
                "record_id": report_id,
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "failed",
            },
        },
        {
            "op": "create_edge",
            "edge_id": "revision-candidate-to-verifier",
            "from_node_id": worker_id,
            "from_port": "candidate",
            "to_node_id": consumer_id,
            "to_port": "candidate_under_test",
            "required": True,
            "dependency_type": "input_binding",
            "accepted_record_selector": {
                "record_type": "candidate",
                "schema": "ImplementationCandidate",
            },
        },
        {
            "op": "create_edge",
            "edge_id": "revision-artifact-to-verifier",
            "from_node_id": worker_id,
            "from_port": "semantic_artifact",
            "to_node_id": consumer_id,
            "to_port": "semantic_artifact",
            "required": True,
            "dependency_type": "input_binding",
            "accepted_record_selector": {
                "record_type": "semantic_artifact",
                "schema": "SemanticArtifact",
                "semantic_schema_id": "ordered-batch-plan",
                "semantic_schema_version": 1,
            },
        },
    ]
    if mutation == "artifact_role":
        artifact["value"]["semantic_role"] = "implementation_result"
    elif mutation == "artifact_schema":
        artifact["value"]["schema_id"] = "different-plan"
    elif mutation == "artifact_version":
        artifact["value"]["schema_version"] = 2
        artifact["schema_version"] = 2
    elif mutation == "artifact_authority":
        artifact["value"]["authority_status"] = "rejected"
    elif mutation == "artifact_producer":
        artifact["producer_node_id"] = "verifier-plan"
    elif mutation == "failed_recovery_mismatch":
        node["failed_candidate_id"] = "different-plan"
    elif mutation == "node_schema":
        node["semantic_schema_id"] = "different-plan"
    elif mutation == "node_requirement":
        node["bound_requirement_ids"] = ["MISSING"]
    elif mutation == "report_outcome":
        report["outcome"] = "passed"
        report["value"]["outcome"] = "passed"
    elif mutation == "report_candidate":
        report["candidate_id"] = "different-plan"
    elif mutation == "report_evaluated_artifact":
        report["evaluated_record_ids"] = ["requirement-1"]
    elif mutation == "report_evaluated_requirement":
        report["evaluated_record_ids"] = [artifact_id]
    elif mutation == "report_source_stage":
        plan_verifier["semantic_stage"] = "effectful_batch"
    elif mutation == "selector_report":
        edges[0]["accepted_record_selector"]["record_id"] = "different-report"
    elif mutation == "selector_outcome":
        edges[0]["accepted_record_selector"]["outcome"] = "passed"
    elif mutation == "semantic_consumer_schema":
        edges[2]["accepted_record_selector"]["semantic_schema_version"] = 2
    elif mutation == "semantic_consumer":
        consumer["failed_candidate_id"] = "different-plan"
    elif mutation == "candidate_consumer_missing":
        edges.pop(1)

    requirement = {
        "record_id": "requirement-1",
        "record_kind": "graph_record",
        "record_type": "requirement_record",
        "producer_node_id": "requirement-1",
        "port": "requirement",
        "schema": "RequirementRecord",
        "value": {"id": "REQ-1", "text": "Required behavior", "must": True},
    }
    projection = build_projection(
        [
            event("node_created", {"node_id": "routine-snapshot", "kind": "artifact"}),
            event("output_record_accepted", declaration, position=1),
            event(
                "node_created",
                {"node_id": "requirement-1", "kind": "requirement"},
                position=2,
            ),
            event("output_record_accepted", requirement, position=3),
            event("node_created", discovery, position=4),
            event("output_record_accepted", artifact, position=5),
            event("node_created", plan_verifier, position=6),
            event("output_record_accepted", report, position=7),
            event("node_created", consumer, position=8),
        ]
    )
    return projection, node, edges


def test_semantic_plan_revision_is_classified_only_from_exact_typed_lineage() -> None:
    projection, node, edges = _semantic_plan_revision_facts()

    assert (
        classify_write_worker_semantics(node["node_id"], node, projection, edges=edges)
        == "semantic_plan_revision"
    )


def test_semantic_plan_revision_requires_semantic_artifact_output_contract() -> None:
    projection, node, edges = _semantic_plan_revision_facts()
    node.pop("outputs")
    patch = PatchEnvelope(
        patch_id="semantic-plan-revision-without-artifact-output",
        proposed_by_node_id="planner-1",
        base_graph_position=0,
        ops=[PatchOp(op="create_node", node=node), *[PatchOp(**edge) for edge in edges]],
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.rejection_reason == (
        "semantic plan revision must declare a required semantic_artifact output"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "artifact_role",
        "artifact_schema",
        "artifact_version",
        "artifact_authority",
        "artifact_producer",
        "failed_recovery_mismatch",
        "node_schema",
        "node_requirement",
        "report_outcome",
        "report_candidate",
        "report_evaluated_artifact",
        "report_evaluated_requirement",
        "report_source_stage",
        "selector_report",
        "selector_outcome",
        "semantic_consumer_schema",
        "semantic_consumer",
        "candidate_consumer_missing",
    ],
)
def test_semantic_plan_revision_lineage_mutations_fail_closed(mutation: str) -> None:
    projection, node, edges = _semantic_plan_revision_facts(mutation)

    assert (
        classify_write_worker_semantics(node["node_id"], node, projection, edges=edges)
        != "semantic_plan_revision"
    )


def test_declared_batch_write_worker_cannot_relabel_itself_corrective_work() -> None:
    projection, node, edges = _semantic_plan_revision_facts()
    node["recovery_of_record_id"] = None

    patch = PatchEnvelope(
        patch_id="relabelled-implementation",
        proposed_by_node_id="planner-1",
        base_graph_position=0,
        ops=[PatchOp(op="create_node", node=node), *[PatchOp(**edge) for edge in edges]],
    )
    result = validate_patch(patch, 0, [], projection, "human")

    assert result.accepted is False
    assert result.rejection_reason == (
        "implementation against a declared batch plan must use effectful_batch semantics"
    )


def _correction_supersession_facts() -> tuple[Any, dict[str, Any]]:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-batch-1",
                    "kind": "worker",
                    "semantic_stage": "effectful_batch",
                    "declared_batch_id": "batch-1",
                    "task_region_id": "region-batch-1",
                },
            ),
            event(
                "output_record_accepted",
                {
                    "record_id": "candidate-batch-1",
                    "record_kind": "output",
                    "record_type": "candidate",
                    "producer_node_id": "worker-batch-1",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": "candidate-batch-1",
                    "task_region_id": "region-batch-1",
                    "attempt_number": 1,
                    "value": {"summary": "failed candidate"},
                },
                position=1,
            ),
            event(
                "node_created",
                {
                    "node_id": "verifier-batch-1",
                    "kind": "verifier",
                    "semantic_stage": "effectful_batch",
                    "declared_batch_id": "batch-1",
                    "task_region_id": "region-batch-1",
                },
                position=2,
            ),
            event(
                "output_record_accepted",
                {
                    "record_id": "verification-batch-1-failed",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "verifier-batch-1",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": "candidate-batch-1",
                    "task_region_id": "region-batch-1",
                    "outcome": "failed",
                    "value": {"outcome": "failed", "grades": []},
                },
                position=3,
            ),
            event(
                "verification_failed",
                {
                    "node_id": "verifier-batch-1",
                    "verifier_node_id": "verifier-batch-1",
                    "candidate_id": "candidate-batch-1",
                    "task_region_id": "region-batch-1",
                    "record_id": "verification-batch-1-failed",
                    "outcome": "failed",
                },
                position=4,
            ),
        ]
    )
    return projection, {
        "node_id": "worker-correction",
        "kind": "worker",
        "semantic_stage": "corrective_work",
        "declared_batch_id": "batch-1",
        "failed_candidate_id": "candidate-batch-1",
        "failed_verification_record_id": "verification-batch-1-failed",
        "base_snapshot_selection": "rejected_candidate",
        "base_snapshot_candidate_id": "candidate-batch-1",
        "recovery_reason": "failed_verification",
        "recovery_of_node_id": "verifier-batch-1",
        "recovery_of_record_id": "verification-batch-1-failed",
    }


def test_correction_supersession_requires_exact_failed_candidate_lineage() -> None:
    projection, node = _correction_supersession_facts()

    assert correction_superseded_task_region_id(projection, node) == "region-batch-1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("declared_batch_id", "batch-2"),
        ("failed_candidate_id", "candidate-other"),
        ("base_snapshot_selection", "accepted_region"),
        ("base_snapshot_candidate_id", "candidate-other"),
        ("recovery_of_node_id", "verifier-other"),
        ("recovery_of_record_id", "verification-other"),
    ],
)
def test_correction_supersession_lineage_mutations_fail_closed(
    field: str,
    value: str,
) -> None:
    projection, node = _correction_supersession_facts()
    node[field] = value

    assert correction_superseded_task_region_id(projection, node) is None


def test_composite_revision_attempt_uses_same_semantic_plan_revision_classifier() -> None:
    projection, worker, edges = _semantic_plan_revision_facts()
    worker["node_id"] = "worker-composite-plan-revision"
    verifier_id = "verifier-composite-plan-revision"
    verifier = {
        "node_id": verifier_id,
        "kind": "verifier",
        "role": "verifier",
        "state": "planned",
        "task_region_id": worker["task_region_id"],
        "failed_candidate_id": worker["failed_candidate_id"],
    }
    for edge in edges:
        if edge["from_node_id"] == "worker-plan-revision":
            edge["from_node_id"] = worker["node_id"]
        if edge["to_node_id"] == "worker-plan-revision":
            edge["to_node_id"] = worker["node_id"]
        if edge["to_node_id"] == "verifier-plan-revision":
            edge["to_node_id"] = verifier_id
    patch = PatchEnvelope(
        patch_id="composite-semantic-plan-revision",
        proposed_by_node_id="planner-1",
        base_graph_position=0,
        ops=[
            PatchOp(
                op="create_revision_attempt",
                task_region_id=worker["task_region_id"],
                failed_candidate_id=worker["failed_candidate_id"],
                worker_node=worker,
                verifier_node=verifier,
            ),
            *[PatchOp(**edge) for edge in edges],
        ],
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is True, result.rejection_reason


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


def _materialized_first_horizon_projection() -> Any:
    return build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "planner-1",
                    "kind": "planner",
                    "role": "planner",
                    "state": "leased",
                    "semantic_stage": "successor_planning",
                    "planning_horizon": 1,
                    "reliable_plan_one_horizon_authorized": True,
                    "reliable_plan_remaining_horizons": 2,
                    **_reliable_plan_planner_fields(successor=True),
                },
            ),
            event(
                "node_created",
                {
                    "node_id": "worker-batch-1",
                    "kind": "worker",
                    "role": "implementer",
                    "state": "planned",
                    "semantic_stage": "effectful_batch",
                    "planning_horizon": 1,
                    "declared_batch_id": "batch-1",
                    "task_region_id": "batch-1",
                },
                position=1,
            ),
            event(
                "node_created",
                {
                    "node_id": "verifier-batch-1",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "planned",
                    "semantic_stage": "effectful_batch",
                    "planning_horizon": 1,
                    "declared_batch_id": "batch-1",
                    "task_region_id": "batch-1",
                    "outputs": [
                        {
                            "port": "verification_report",
                            "direction": "output",
                            "schema": "VerificationReport",
                            "required": True,
                        }
                    ],
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
                    "outputs": [
                        {
                            "port": "verification_report",
                            "direction": "output",
                            "schema": "VerificationReport",
                            "required": True,
                        }
                    ],
                },
                position=3,
            ),
            event(
                "graph_patch_accepted",
                {
                    "patch_id": "patch-batch-1",
                    "base_graph_position": 0,
                    "actor_role": "planner",
                    "proposed_by_node_id": "planner-1",
                    "successor_planner_node_ids": [],
                },
                position=4,
            ),
        ]
    )


def test_reliable_plan_accepts_successor_after_batch_was_materialized_by_prior_patch() -> None:
    projection = _materialized_first_horizon_projection()
    patch = _macro_patch(
        "create_successor_planner",
        {
            "region_id": "batch-1",
            "node_id": "planner-h2",
            "evidence_source_node_id": "verifier-batch-1",
            "evidence_source_port": "verification_report",
            "planning_horizon": 2,
        },
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "incomplete_reliable_plan_horizon"


def test_reliable_plan_rejects_separate_successor_not_gated_by_batch_verifier() -> None:
    projection = _materialized_first_horizon_projection()
    patch = _macro_patch(
        "create_successor_planner",
        {
            "region_id": "batch-1",
            "node_id": "planner-h2",
            "evidence_source_node_id": "verifier-plan",
            "evidence_source_port": "verification_report",
            "planning_horizon": 2,
        },
    )

    result = validate_patch(patch, 0, [], projection, "planner")

    assert result.accepted is False
    assert result.diagnostics is not None
    assert result.diagnostics["violation"] == "incomplete_reliable_plan_horizon"


def test_reliable_plan_command_accepts_successor_after_prior_batch_patch() -> None:
    projection = _materialized_first_horizon_projection()
    patch = _macro_patch(
        "create_successor_planner",
        {
            "region_id": "batch-1",
            "node_id": "planner-h2",
            "evidence_source_node_id": "verifier-batch-1",
            "evidence_source_port": "verification_report",
            "planning_horizon": 2,
        },
    )

    command_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": patch.patch_id,
            "base_graph_position": 4,
            "ops": [op.model_dump(mode="json") for op in patch.ops],
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=4,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert command_events[0].event_type == "graph_patch_rejected"
    assert command_events[0].payload["diagnostics"]["violation"] == (
        "incomplete_reliable_plan_horizon"
    )


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
            "effect_contract": "effectful_write",
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
                    **_reliable_plan_planner_fields(),
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
                    **_reliable_plan_planner_fields(),
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
                            "effect_contract": "effectful_write",
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
                    "planning_horizon": 1,
                    "reliable_plan_remaining_horizons": 2,
                    **_reliable_plan_planner_fields(successor=True),
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
    patch = _macro_patch_for_planner(
        patch_id="patch-atomic-batch-1",
        invocations=[
            {
                "macro": "create_effectful_batch",
                "args": {
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
                        {
                            "check_id": "check-batch-1",
                            "command_binding": "dynamic_feature_hidden_oracle",
                        }
                    ],
                    "rubric": ["candidate satisfies batch 1 and REQ-1"],
                    "planning_horizon": 1,
                },
            },
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "successor-batch-2",
                    "node_id": "planner-h2",
                    "evidence_source_node_id": "verifier-batch-batch-1",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 2,
                },
            },
        ],
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

    raw_ops = [op.model_dump(mode="json", exclude_none=True) for op in patch.ops]
    worker_op = next(
        op
        for op in raw_ops
        if op.get("op") == "create_node"
        and op.get("node", {}).get("semantic_stage") == "effectful_batch"
    )
    worker_op["node"].pop("kind")
    worker_op["node"].update(
        {
            "reliable_plan_assignment_carrier": {"agent": "supplied"},
            "reliable_plan_assignment_role": "verifier",
            "reliable_plan_selected_runner_type": "cli_subprocess",
            "runner_model_override": "hostile-model",
            "profile": "architect",
        }
    )

    command_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": "patch-default-worker-kind",
            "base_graph_position": 9,
            "ops": raw_ops,
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=9,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert command_events[0].event_type == "graph_patch_accepted", command_events[0].payload
    created_worker = next(
        event.payload
        for event in command_events
        if event.event_type == "node_created"
        and event.payload.get("semantic_stage") == "effectful_batch"
    )
    assignment = _reliable_plan_carrier().assignment_for("implementation_worker")
    assert created_worker["kind"] == "worker"
    assert created_worker["reliable_plan_assignment_carrier"] == (
        _reliable_plan_carrier().model_dump(mode="json")
    )
    assert created_worker["reliable_plan_assignment_role"] == "implementation_worker"
    assert created_worker["reliable_plan_selected_runner_type"] == "codex_server"
    assert created_worker["runner_model_override"] == assignment.model
    assert created_worker["profile"] == assignment.profile.value


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
                "planning_horizon": 1,
                "reliable_plan_remaining_horizons": 2,
                **_reliable_plan_planner_fields(successor=True),
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
    patch = _atomic_nonfinal_batch_patch(
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
                    "planning_horizon": 1,
                    "reliable_plan_remaining_horizons": 2,
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
    patch = _atomic_nonfinal_batch_patch(
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
