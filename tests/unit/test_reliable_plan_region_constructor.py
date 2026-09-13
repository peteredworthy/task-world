from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import (
    PatchEnvelope,
    PatchOp,
    SubmitPatchCommand,
    build_projection,
    expand_patch_macros,
    validate_patch,
)
from tests.unit.graph_test_utils import event


def _requirement_record() -> dict[str, Any]:
    return {
        "record_id": "requirement-record-1",
        "record_kind": "graph_record",
        "record_type": "requirement_record",
        "producer_node_id": "routine-snapshot",
        "port": "requirement",
        "schema": "RequirementRecord",
        "value": {
            "id": "REQ-1",
            "text": "Implement the bounded feature.",
            "acceptance_criteria": ["the bounded feature works"],
        },
    }


def _schema_record() -> dict[str, Any]:
    return {
        "record_id": "schema-plan-v1",
        "record_kind": "graph_record",
        "record_type": "semantic_schema_declaration",
        "schema_version": 1,
        "producer_node_id": "routine-snapshot",
        "port": "semantic_schema_declaration",
        "schema": "SemanticSchemaDeclaration",
        "value": {
            "schema_id": "ordered-plan",
            "version": 1,
            "semantic_role": "implementation_plan",
            "json_schema": {
                "type": "object",
                "required": ["batches"],
                "properties": {"batches": {"type": "array"}},
            },
            "authority": "routine_snapshot",
        },
    }


def _plan_record() -> dict[str, Any]:
    return {
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
            "schema_id": "ordered-plan",
            "schema_version": 1,
            "content": {"batches": [{"batch_id": "batch-1"}, {"batch_id": "batch-2"}]},
            "provenance": {"source": "discovery"},
            "source_record_ids": ["requirement-record-1"],
            "requirement_ids": ["REQ-1"],
            "task_region_id": "discovery",
            "validation_status": "validated",
            "authority_status": "accepted",
        },
    }


def _plan_verification_record() -> dict[str, Any]:
    return {
        "record_id": "plan-verification-passed",
        "record_kind": "verification",
        "record_type": "verification_report",
        "producer_node_id": "verifier-plan",
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": "accepted-plan",
        "candidate_record_id": "accepted-plan",
        "candidate_record_ids": ["accepted-plan"],
        "task_region_id": "plan-verification",
        "outcome": "passed",
        "value": {"outcome": "passed", "grades": []},
        "evaluated_record_ids": ["accepted-plan", "requirement-record-1"],
    }


def _base_events(*, successor: bool, remaining: int = 2) -> list[Any]:
    planner: dict[str, Any] = {
        "node_id": "planner-1",
        "kind": "planner",
        "role": "planner",
        "state": "leased",
        "reliable_plan_skeleton_id": "reliable-plan-v1",
        "reliable_plan_one_horizon_authorized": True,
        "reliable_plan_remaining_horizons": remaining,
    }
    if successor:
        planner.update(
            {
                "semantic_stage": "successor_planning",
                "planning_horizon": 1,
                "task_region_id": "successor-region",
            }
        )
    return [
        event("node_created", planner, position=0),
        event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "requirement",
                "role": "requirement",
                "state": "completed",
                "outputs": [
                    {"port": "requirement", "direction": "output", "schema": "Requirement"},
                    {
                        "port": "semantic_schema_declaration",
                        "direction": "output",
                        "schema": "SemanticSchemaDeclaration",
                    },
                ],
            },
            position=1,
        ),
        event("output_record_accepted", _requirement_record(), position=2),
        event("output_record_accepted", _schema_record(), position=3),
    ]


def _semantic_args(*, scope: str, dependencies: list[str] | None = None) -> dict[str, Any]:
    return {
        "operation_key": "construct-" + scope.replace(" ", "-"),
        "scope": scope,
        "objective": f"Complete {scope}.",
        "requirement_ids": ["REQ-1"],
        "dependencies": dependencies or [],
        "acceptance": [f"{scope} obligations pass"],
        "checks": [
            {
                "name": "bounded project check",
                "command_binding": "dynamic_feature_hidden_oracle",
            }
        ],
        "rubric": ["REQ-1 is satisfied independently"],
    }


def _sealed_assignment_carrier() -> dict[str, Any]:
    assignments = {
        role: {
            "runner_type": "codex_server",
            "model": "user-selected-model",
            "profile": profile,
        }
        for role, profile in {
            "planner": "architect",
            "discovery_worker": "summarizer",
            "implementation_worker": "coder",
            "correction_worker": "coder",
            "verifier": "coder",
            "successor_planner": "architect",
        }.items()
    }
    return {
        "skeleton_id": "reliable-plan-fff4f6b7-v1",
        "selected_runner_type": "codex_server",
        "arm": {"arm_id": "constructor-test", **assignments},
    }


def _expand(projection: Any, args: dict[str, Any], *, patch_id: str = "patch-stable") -> list:
    command = SubmitPatchCommand.model_validate(
        {
            "patch_id": patch_id,
            "base_graph_position": 0,
            "macro_invocations": [{"macro": "construct_reliable_plan_region", "args": args}],
        }
    )
    return expand_patch_macros(
        command.ops,
        command.macro_invocations,
        "planner-1",
        projection=projection,
        patch_id=patch_id,
    )


def test_constructor_rejects_unavailable_hidden_oracle_from_routine_snapshot() -> None:
    projection = build_projection(
        [
            *_base_events(successor=True),
            event(
                "output_record_accepted",
                {
                    "record_id": "routine-snapshot-record",
                    "record_kind": "graph_record",
                    "record_type": "routine_snapshot",
                    "producer_node_id": "routine-snapshot",
                    "port": "snapshot",
                    "schema": "RoutineSnapshot",
                    "value": {
                        "routine_id": "dynamic-graph-feature",
                        "name": "Dynamic graph feature",
                        "content_hash": "hash",
                        "step_count": 1,
                        "task_count": 1,
                        "dynamic_feature": {
                            "hidden_oracle_command": "",
                            "acceptance_command": "uv run pytest tests -q",
                        },
                    },
                },
                position=4,
            ),
        ]
    )

    with pytest.raises(ValueError, match="non-empty hidden_oracle_command"):
        _expand(projection, _semantic_args(scope="batch-1"))


def test_constructor_builds_atomic_initial_region_without_planner_graph_ids() -> None:
    projection = build_projection(_base_events(successor=False))
    args = {**_semantic_args(scope="whole feature"), "checks": []}

    first = _expand(projection, args)
    second = _expand(projection, args)

    assert first == second
    nodes = [op["node"] for op in first if op["op"] == "create_node"]
    assert [node.get("semantic_stage") for node in nodes] == [
        "discovery",
        "plan_verification",
        "successor_planning",
        None,
    ]
    assert nodes[-1]["role"] == "gap_planner"
    assert nodes[-2]["generation_index"] == 1
    requirement_edges = [
        op for op in first if str(op.get("to_port", "")).startswith("requirement_")
    ]
    assert requirement_edges
    assert all(
        edge["accepted_record_selector"]["record_id"] == "requirement-record-1"
        for edge in requirement_edges
    )
    patch = PatchEnvelope(
        patch_id="patch-stable",
        proposed_by_node_id="planner-1",
        base_graph_position=3,
        ops=[PatchOp(**op) for op in first],
    )
    validation = validate_patch(
        patch,
        current_position=3,
        events_since_base=[],
        projection=projection,
        actor_role="planner",
    )
    assert validation.accepted is True, validation.rejection_reason


def test_semantic_operation_identity_does_not_depend_on_transport_patch_id() -> None:
    projection = build_projection(_base_events(successor=False))
    args = {**_semantic_args(scope="whole feature"), "checks": []}

    assert _expand(projection, args, patch_id="transport-a") == _expand(
        projection, args, patch_id="transport-b"
    )


def test_constructor_builds_nonfinal_batch_with_mechanical_check_and_successor() -> None:
    projection = build_projection(
        [
            *_base_events(successor=True),
            event(
                "node_created",
                {
                    "node_id": "worker-discovery",
                    "kind": "worker",
                    "role": "discovery",
                    "state": "completed",
                },
                position=4,
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
                position=5,
            ),
            event("output_record_accepted", _plan_record(), position=6),
            event("output_record_accepted", _plan_verification_record(), position=7),
        ]
    )

    ops = _expand(projection, _semantic_args(scope="batch-1"))
    nodes = [op["node"] for op in ops if op["op"] == "create_node"]

    assert sum(node.get("semantic_stage") == "effectful_batch" for node in nodes) == 3
    successor = next(node for node in nodes if node.get("semantic_stage") == "successor_planning")
    assert successor["planning_horizon"] == 2
    assert successor["generation_index"] == 2
    assert any(node.get("role") == "gap_planner" for node in nodes)
    assert not any(node.get("semantic_stage") == "final_gate" for node in nodes)


def test_constructor_builds_final_acceptance_audit_and_completion_dependencies() -> None:
    events = [
        *_base_events(successor=True, remaining=1),
        event(
            "node_created",
            {
                "node_id": "worker-discovery",
                "kind": "worker",
                "role": "discovery",
                "state": "completed",
            },
            position=4,
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
            position=5,
        ),
        event("output_record_accepted", _plan_record(), position=6),
        event("output_record_accepted", _plan_verification_record(), position=7),
        event(
            "node_created",
            {
                "node_id": "verifier-batch-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "task_region_id": "batch-1-region",
            },
            position=8,
        ),
    ]
    projection = build_projection(events)

    ops = _expand(
        projection,
        _semantic_args(scope="batch-2", dependencies=["batch-1"]),
    )
    nodes = [op["node"] for op in ops if op["op"] == "create_node"]
    acceptance = next(node for node in nodes if node.get("semantic_stage") == "final_acceptance")
    audit = next(node for node in nodes if node.get("semantic_stage") == "final_audit")
    gate = next(node for node in nodes if node.get("kind") == "final_gate")

    assert {
        node["task_region_id"]
        for node in nodes
        if node.get("semantic_stage") in {"effectful_batch", "final_acceptance", "final_audit"}
    } == {"successor-region"}
    assert gate["task_region_id"] == "successor-region"
    assert acceptance["command_binding"] == "dynamic_feature_acceptance"
    assert gate["declared_batch_ids"] == ["batch-1", "batch-2"]
    gate_sources = {
        op["from_node_id"]
        for op in ops
        if op.get("op") == "create_edge" and op.get("to_node_id") == gate["node_id"]
    }
    assert acceptance["node_id"] in gate_sources
    assert audit["node_id"] in gate_sources
    assert "verifier-batch-1" in gate_sources
    assert any(
        source.startswith("verifier-batch-") for source in gate_sources - {"verifier-batch-1"}
    )
    recovery_sources = {
        op["from_node_id"]
        for op in ops
        if op.get("op") == "create_edge"
        and str(op.get("to_node_id", "")).startswith("planner-gap-")
    }
    assert acceptance["node_id"] in recovery_sources
    assert audit["node_id"] in recovery_sources


def test_constructor_schema_rejects_planner_authored_execution_identity() -> None:
    args = {**_semantic_args(scope="batch-1"), "worker_id": "planner-picked-worker"}
    command = SubmitPatchCommand.model_validate(
        {
            "patch_id": "patch-stable",
            "base_graph_position": 0,
            "macro_invocations": [{"macro": "construct_reliable_plan_region", "args": args}],
        }
    )

    with pytest.raises(ValueError, match="worker_id"):
        expand_patch_macros(
            command.ops,
            command.macro_invocations,
            "planner-1",
            projection=build_projection(_base_events(successor=True)),
            patch_id=command.patch_id,
        )


def test_constructor_requires_a_mechanical_check_only_for_effectful_horizons() -> None:
    projection = build_projection(
        [
            *_base_events(successor=True),
            event(
                "node_created",
                {
                    "node_id": "worker-discovery",
                    "kind": "worker",
                    "role": "discovery",
                    "state": "completed",
                },
                position=4,
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
                position=5,
            ),
            event("output_record_accepted", _plan_record(), position=6),
            event("output_record_accepted", _plan_verification_record(), position=7),
        ]
    )

    with pytest.raises(ValueError, match="requires at least one check"):
        _expand(projection, {**_semantic_args(scope="batch-1"), "checks": []})


@pytest.mark.parametrize("classification_committed", [True, False])
def test_gap_planner_constructor_derives_exact_failed_batch_correction_and_successor(
    classification_committed: bool,
) -> None:
    failed_check = {
        "record_id": "check-result-failed",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "check-batch-1",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "candidate-a",
        "task_region_id": "batch-1-region",
        "attempt_number": 1,
        "value": {
            "status": "failed",
            "classification": "failed",
            "command_id": "project-test",
            "command_text": "exit 1",
            "command": {"argv": ["exit", "1"]},
            "worktree_path": "/tmp/worktree",
            "base_snapshot_id": "snapshot-a",
            "execution_id": "execution-check",
            "exit_code": 1,
            "duration_ms": 1,
            "stdout_tail": "",
            "stderr_tail": "failed",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 30.0,
            "environment_policy": {},
            "candidate_record_ids": ["candidate-a"],
            "evaluated_record_ids": ["candidate-a"],
        },
        "candidate_record_id": "candidate-a",
        "candidate_record_ids": ["candidate-a"],
        "evaluated_record_ids": ["candidate-a"],
    }
    failed_report = {
        "record_id": "verification-failed",
        "record_kind": "verification",
        "record_type": "verification_report",
        "producer_node_id": "verifier-batch-1",
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": "candidate-a",
        "candidate_record_id": "candidate-a",
        "candidate_record_ids": ["candidate-a"],
        "task_region_id": "batch-1-region",
        "outcome": "failed",
        "value": {"outcome": "failed", "grades": []},
        "evaluated_record_ids": ["candidate-record-a", "check-result-failed"],
    }
    classification = {
        "record_id": "classified-gap",
        "record_kind": "output",
        "record_type": "classified_gap",
        "producer_node_id": "planner-1",
        "port": "gap_classification",
        "schema": "GapClassification",
        "value": {
            "milestone_kind": "failed_verification",
            "classification": "corrective_work_required",
            "source": "verification-failed",
            "task_region_id": "batch-1-region",
            "attempt_number": 1,
        },
    }
    events = [
        *_base_events(successor=False)[1:],
        event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "leased",
                "reliable_plan_skeleton_id": "reliable-plan-v1",
                "recovery_of_record_id": "verification-failed",
            },
            position=4,
        ),
        event(
            "node_created",
            {
                "node_id": "worker-discovery",
                "kind": "worker",
                "role": "discovery",
                "state": "completed",
            },
            position=5,
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
            position=6,
        ),
        event("output_record_accepted", _plan_record(), position=7),
        event("output_record_accepted", _plan_verification_record(), position=8),
        event(
            "node_created",
            {
                "node_id": "check-batch-1",
                "kind": "check",
                "role": "batch_check",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "planning_horizon": 1,
                "task_region_id": "batch-1-region",
            },
            position=9,
        ),
        event(
            "node_created",
            {
                "node_id": "verifier-batch-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "planning_horizon": 1,
                "task_region_id": "batch-1-region",
            },
            position=10,
        ),
        event(
            "node_created",
            {
                "node_id": "planner-stale-h2",
                "kind": "planner",
                "role": "planner",
                "state": "blocked",
                "semantic_stage": "successor_planning",
                "planning_horizon": 2,
            },
            position=11,
        ),
        event("output_record_accepted", failed_check, position=12),
        event("output_record_accepted", failed_report, position=13),
        event("output_record_accepted", classification, position=14)
        if classification_committed
        else event(
            "lease_granted",
            {
                "node_id": "planner-1",
                "lease_id": "lease-gap",
                "execution_id": "execution-gap",
                "generation": 1,
            },
            position=14,
        ),
    ]
    projection = build_projection(events)

    ops = _expand(projection, _semantic_args(scope="batch-1"), patch_id="patch-correction")
    nodes = [op["node"] for op in ops if op["op"] == "create_node"]
    corrective_worker = next(
        node
        for node in nodes
        if node.get("kind") == "worker" and node.get("semantic_stage") == "corrective_work"
    )
    successor = next(node for node in nodes if node.get("semantic_stage") == "successor_planning")

    assert corrective_worker["failed_verification_record_id"] == "verification-failed"
    assert corrective_worker["failed_check_record_ids"] == ["check-result-failed"]
    assert corrective_worker["classified_gap_record_id"] == (
        "classified-gap" if classification_committed else "classified-gap-execution-gap"
    )
    assert corrective_worker["base_snapshot_selection"] == "rejected_candidate"
    assert corrective_worker["base_snapshot_candidate_id"] == "candidate-a"
    assert successor["planning_horizon"] == 2
    assert successor["generation_index"] == 2
    assert {op["node_id"] for op in ops if op["op"] == "retire_node"} == {"planner-stale-h2"}


def test_gap_planner_replaces_finalization_after_failed_independent_audit() -> None:
    acceptance = {
        "record_id": "acceptance-a",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "acceptance-old",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "candidate-a",
        "task_region_id": "batch-2-region",
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "acceptance",
            "command_text": "true",
            "command": {"argv": ["true"]},
            "worktree_path": "/tmp/worktree",
            "base_snapshot_id": "snapshot-a",
            "execution_snapshot_id": "snapshot-a",
            "execution_id": "acceptance-a",
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_tail": "",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 30.0,
            "environment_policy": {},
            "candidate_record_ids": ["candidate-record-a"],
            "evaluated_record_ids": ["candidate-record-a"],
        },
        "candidate_record_id": "candidate-record-a",
        "candidate_record_ids": ["candidate-record-a"],
        "evaluated_record_ids": ["candidate-record-a"],
    }
    audit = {
        "record_id": "audit-failed-a",
        "record_kind": "verification",
        "record_type": "verification_report",
        "producer_node_id": "audit-old",
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": "candidate-a",
        "candidate_record_id": "candidate-record-a",
        "candidate_record_ids": ["candidate-record-a"],
        "task_region_id": "batch-2-region",
        "outcome": "failed",
        "value": {"outcome": "failed", "grades": []},
        "evaluated_record_ids": ["candidate-a", "acceptance-a"],
    }
    classification = {
        "record_id": "classified-final-gap",
        "record_kind": "output",
        "record_type": "classified_gap",
        "producer_node_id": "planner-1",
        "port": "gap_classification",
        "schema": "GapClassification",
        "value": {
            "milestone_kind": "failed_verification",
            "classification": "corrective_work_required",
            "source": "audit-failed-a",
            "task_region_id": "batch-2-region",
            "attempt_number": 1,
        },
        "provenance": {"evaluated_record_ids": ["audit-failed-a", "acceptance-a"]},
    }
    events = [
        *_base_events(successor=False)[1:],
        event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "leased",
                "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                "reliable_plan_assignment_carrier": _sealed_assignment_carrier(),
                "recovery_of_record_id": "audit-failed-a",
            },
            position=4,
        ),
        event(
            "node_created",
            {
                "node_id": "worker-discovery",
                "kind": "worker",
                "role": "discovery",
                "state": "completed",
            },
            position=5,
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
            position=6,
        ),
        event("output_record_accepted", _plan_record(), position=7),
        event("output_record_accepted", _plan_verification_record(), position=8),
        event(
            "node_created",
            {
                "node_id": "verifier-batch-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "planning_horizon": 1,
                "task_region_id": "batch-1-region",
            },
            position=9,
        ),
        event(
            "node_created",
            {
                "node_id": "worker-batch-1",
                "kind": "worker",
                "role": "implementer",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "task_region_id": "batch-1-region",
            },
            position=10,
        ),
        event(
            "node_created",
            {
                "node_id": "check-batch-1",
                "kind": "check",
                "role": "batch_check",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "task_region_id": "batch-1-region",
            },
            position=11,
        ),
        event(
            "edge_created",
            {
                "edge_id": "edge-worker-batch-1-verifier",
                "from_node_id": "worker-batch-1",
                "from_port": "candidate",
                "to_node_id": "verifier-batch-1",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "candidate",
                    "schema": "ImplementationCandidate",
                },
            },
            position=12,
        ),
        event(
            "edge_created",
            {
                "edge_id": "edge-check-batch-1-verifier",
                "from_node_id": "check-batch-1",
                "from_port": "check_result",
                "to_node_id": "verifier-batch-1",
                "to_port": "check_result_1",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "any_of",
                    "selectors": [
                        {
                            "record_type": "check_result",
                            "schema": "CheckResult",
                            "status": "passed",
                        },
                        {
                            "record_type": "check_result",
                            "schema": "CheckResult",
                            "status": "failed",
                        },
                    ],
                },
            },
            position=13,
        ),
        event(
            "node_created",
            {
                "node_id": "verifier-batch-2",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-2",
                "planning_horizon": 2,
            },
            position=14,
        ),
        event(
            "node_created",
            {
                "node_id": "worker-batch-2",
                "kind": "worker",
                "role": "implementer",
                "state": "completed",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-2",
                "task_region_id": "batch-2-region",
            },
            position=15,
        ),
        event(
            "output_record_accepted",
            {
                "record_id": "candidate-a",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-batch-2",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-a",
                "task_region_id": "batch-2-region",
                "value": {"summary": "candidate A"},
            },
            position=16,
        ),
        event(
            "node_created",
            {
                "node_id": "acceptance-old",
                "kind": "check",
                "role": "acceptance_gate",
                "state": "completed",
                "semantic_stage": "final_acceptance",
            },
            position=17,
        ),
        event(
            "node_created",
            {
                "node_id": "audit-old",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "final_audit",
            },
            position=18,
        ),
        event(
            "node_created",
            {
                "node_id": "gate-old",
                "kind": "final_gate",
                "role": "final_gate",
                "state": "blocked",
                "semantic_stage": "final_gate",
            },
            position=19,
        ),
        event(
            "node_created",
            {
                "node_id": "planner-gap-old",
                "kind": "planner",
                "role": "gap_planner",
                "state": "blocked",
            },
            position=20,
        ),
        event("output_record_accepted", acceptance, position=21),
        event("output_record_accepted", audit, position=22),
        event(
            "verification_failed",
            {
                "node_id": "audit-old",
                "verifier_node_id": "audit-old",
                "candidate_id": "candidate-a",
                "record_id": "audit-failed-a",
                "outcome": "failed",
                "task_region_id": "batch-2-region",
            },
            position=23,
        ),
        event("output_record_accepted", classification, position=24),
        event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "dynamic-graph-feature",
                    "name": "Dynamic graph feature",
                    "content_hash": "hash",
                    "step_count": 1,
                    "task_count": 1,
                    "dynamic_feature": {
                        "hidden_oracle_command": "printf hidden-oracle",
                        "acceptance_command": "printf acceptance",
                    },
                },
            },
            position=25,
        ),
    ]

    ops = _expand(
        build_projection(events),
        _semantic_args(scope="batch-2", dependencies=["batch-1"]),
        patch_id="replace-finalization",
    )
    nodes = [op["node"] for op in ops if op["op"] == "create_node"]
    worker = next(
        node
        for node in nodes
        if node.get("semantic_stage") == "corrective_work" and node.get("kind") == "worker"
    )
    worker.update(
        {
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_assignment_carrier": _sealed_assignment_carrier(),
            "reliable_plan_assignment_role": "correction_worker",
            "reliable_plan_selected_runner_type": "codex_server",
            "runner_model_override": "user-selected-model",
            "profile": "coder",
        }
    )

    assert worker["correction_trigger"] == "failed_final_audit"
    assert worker["failed_verification_record_id"] == "audit-failed-a"
    assert worker["failed_check_record_ids"] == ["acceptance-a"]
    assert not any(node.get("semantic_stage") == "successor_planning" for node in nodes)
    assert sum(node.get("semantic_stage") == "final_acceptance" for node in nodes) == 1
    assert sum(node.get("semantic_stage") == "final_audit" for node in nodes) == 1
    assert sum(node.get("kind") == "final_gate" for node in nodes) == 1
    retired = {op["node_id"] for op in ops if op["op"] == "retire_node"}
    assert {"acceptance-old", "audit-old", "gate-old", "planner-gap-old"}.issubset(retired)
    validation = validate_patch(
        PatchEnvelope(
            patch_id="replace-finalization",
            proposed_by_node_id="planner-1",
            base_graph_position=24,
            ops=[PatchOp(**op) for op in ops],
        ),
        current_position=24,
        events_since_base=[],
        projection=build_projection(events),
        actor_role="gap_planner",
    )
    assert validation.accepted is True, validation.rejection_reason
