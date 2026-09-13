"""Behavior-first tests for canonical gap-planner correction answers."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from orchestrator.graph import (
    CorrectionDecision,
    DecisionContractResolutionError,
    FakeClock,
    PatchCommandContext,
    RequirementRecord,
    SequentialIdGenerator,
    apply_command,
    build_projection,
    compile_decision,
    resolve_correction_decision_context,
    reduce_event,
    node_payload_view,
    output_record_payloads_view,
)
from tests.unit.graph_test_utils import event as graph_event
from tests.unit.test_graph_decisions import decision_successor_events


def _correction_projection(*, failed: bool = True, check_count: int = 1):
    events = decision_successor_events()
    for item in events:
        if item.event_type == "node_created" and item.payload.get("node_id") == "planner-plan":
            payload = dict(item.payload)
            payload.update(
                {
                    "role": "gap_planner",
                    "semantic_stage": "gap_planning",
                    "inputs": [
                        {
                            "port": "routine_snapshot",
                            "direction": "input",
                            "schema": "RoutineSnapshot",
                            "required": True,
                        },
                        {
                            "port": "verification_evidence",
                            "direction": "input",
                            "schema": "VerificationReport",
                            "required": True,
                        },
                    ],
                    "outputs": [
                        {
                            "port": "decision",
                            "direction": "output",
                            "schema": "DecisionAnswer",
                            "record_layers": ["graph_record"],
                            "required": True,
                        },
                        {
                            "port": "classified_gap",
                            "direction": "output",
                            "schema": "GapClassification",
                            "record_layers": ["graph_record"],
                            "required": True,
                        },
                        {
                            "port": "semantic_artifact",
                            "direction": "output",
                            "schema": "SemanticArtifact",
                            "record_layers": ["graph_record"],
                            "required": False,
                        },
                    ],
                }
            )
            events[events.index(item)] = item.model_copy(update={"payload": payload})

    position = len(events) + 1
    events.extend(
        [
            graph_event(
                "node_created",
                {
                    "node_id": "check-batch-core",
                    "kind": "check",
                    "role": "check",
                    "state": "completed",
                    "command_definition": {"argv": ["pytest"]},
                    "outputs": [
                        {
                            "port": "check_result",
                            "direction": "output",
                            "schema": "CheckResult",
                            "record_layers": ["verification"],
                        }
                    ],
                },
                position=position,
            ),
            graph_event(
                "node_created",
                {
                    "node_id": "verifier-batch-core",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "completed",
                    "semantic_stage": "effectful_batch",
                    "declared_batch_id": "core",
                    "planning_horizon": 1,
                    "outputs": [
                        {
                            "port": "verification_report",
                            "direction": "output",
                            "schema": "VerificationReport",
                            "record_layers": ["verification"],
                        },
                        {
                            "port": "check_result",
                            "direction": "output",
                            "schema": "CheckResult",
                            "record_layers": ["verification"],
                        },
                    ],
                },
                position=position + 1,
            ),
            graph_event(
                "output_record_accepted",
                {
                    "record_id": "gap-evidence-report",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "verifier-batch-core",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "graph_position": position + 1,
                    "candidate_id": "candidate-core",
                    "candidate_record_id": "candidate-core",
                    "candidate_record_ids": ["candidate-core"],
                    "task_region_id": "successor-core",
                    "outcome": "failed" if failed else "passed",
                    "value": {"outcome": "failed" if failed else "passed", "grades": []},
                    "evaluated_record_ids": ["gap-evidence-check"],
                },
                position=position + 1,
            ),
            graph_event(
                "output_record_accepted",
                {
                    "record_id": "gap-evidence-check",
                    "record_kind": "output",
                    "record_type": "check_result",
                    "producer_node_id": "check-batch-core",
                    "port": "check_result",
                    "schema": "CheckResult",
                    "schema_version": 1,
                    "graph_position": position + 2,
                    "candidate_id": "candidate-core",
                    "task_region_id": "successor-core",
                    "attempt_number": 1,
                    "value": {
                        "status": "failed" if failed else "passed",
                        "classification": "failed" if failed else "passed",
                        "command_id": "unit",
                        "command_text": "pytest",
                        "command": {"argv": ["pytest"]},
                        "worktree_path": "/tmp/worktree",
                        "base_snapshot_id": "decision-base",
                        "execution_id": "gap-execution",
                        "exit_code": 1 if failed else 0,
                        "duration_ms": 1,
                        "stdout_tail": "",
                        "stderr_tail": "failed" if failed else "",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                        "timeout_seconds": 10.0,
                        "environment_policy": {},
                        "verification_report_record_ids": ["gap-evidence-report"],
                    },
                },
                position=position + 2,
            ),
            graph_event(
                "edge_created",
                {
                    "edge_id": "gap-evidence-to-planner",
                    "from_node_id": "verifier-batch-core",
                    "from_port": "verification_report",
                    "to_node_id": "planner-plan",
                    "to_port": "verification_evidence",
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "failed" if failed else "passed",
                    },
                },
                position=position + 3,
            ),
            graph_event(
                "input_bound",
                {
                    "edge_id": "gap-evidence-to-planner",
                    "to_node_id": "planner-plan",
                    "to_port": "verification_evidence",
                    "record_ids": ["gap-evidence-report"],
                    "bound_at_position": position + 4,
                    "record_bound_positions": {"gap-evidence-report": position + 1},
                },
                position=position + 4,
            ),
        ]
    )
    check_node = next(
        item
        for item in events
        if item.event_type == "node_created" and item.payload.get("node_id") == "check-batch-core"
    )
    check_record = next(
        item
        for item in events
        if item.event_type == "output_record_accepted"
        and item.payload.get("record_id") == "gap-evidence-check"
    )
    extra_ids = []
    for index in range(2, check_count + 1):
        extra_id = f"gap-evidence-check-{index}"
        extra_ids.append(extra_id)
        node_id = f"check-batch-core-{index}"
        extra_position = max(item.position for item in events) + 1
        events.extend(
            [
                graph_event(
                    "node_created",
                    {**check_node.payload, "node_id": node_id},
                    position=extra_position,
                ),
                graph_event(
                    "output_record_accepted",
                    {
                        **check_record.payload,
                        "record_id": extra_id,
                        "producer_node_id": node_id,
                        "graph_position": extra_position + 1,
                    },
                    position=extra_position + 1,
                ),
            ]
        )
    for index, item in enumerate(events):
        if item.payload.get("record_id") == "gap-evidence-report":
            events[index] = item.model_copy(
                update={
                    "payload": {
                        **item.payload,
                        "evaluated_record_ids": ["gap-evidence-check", *extra_ids],
                    }
                }
            )
    return build_projection(events)


def test_correction_answer_schema_accepts_all_dispositions() -> None:
    adapter = TypeAdapter(CorrectionDecision)
    assert (
        adapter.validate_python(
            {"disposition": "no_gap", "reason": "Closed.", "evidence": ["e1"]}
        ).disposition
        == "no_gap"
    )
    assert (
        adapter.validate_python(
            {
                "disposition": "corrective_work",
                "diagnosis": "The batch failed.",
                "remedy": "Repair the bounded batch.",
                "focus": ["src/core.py"],
                "evidence": ["e1"],
            }
        ).disposition
        == "corrective_work"
    )
    assert (
        adapter.validate_python(
            {
                "disposition": "plan_revision",
                "reason": "Add a missing check.",
                "amendment": {
                    "refinements": [
                        {
                            "batch": "core",
                            "checks": [
                                {"name": "extra", "command_definition": {"argv": ["pytest"]}}
                            ],
                        }
                    ]
                },
            }
        ).disposition
        == "plan_revision"
    )
    assert (
        adapter.validate_python(
            {
                "disposition": "escalate",
                "blocker": {
                    "reason": "Evidence is ambiguous.",
                    "needed_information": ["a human decision"],
                    "evidence": ["e1"],
                },
            }
        ).disposition
        == "escalate"
    )


def test_correction_context_binds_exact_failure_evidence_and_baseline() -> None:
    resolved = resolve_correction_decision_context(_correction_projection(), "planner-plan")

    assert resolved.scope == "core"
    assert resolved.failed_verification_record_id == "gap-evidence-report"
    assert dict(resolved.evidence_aliases.object_items()) == {
        "e1": "gap-evidence-report",
        "e2": "gap-evidence-check",
    }
    assert resolved.plan_record_id == "accepted-decision-plan"


@pytest.mark.parametrize(
    ("answer", "expected_disposition"),
    [
        (
            {
                "disposition": "corrective_work",
                "diagnosis": "Failure.",
                "remedy": "Repair.",
                "focus": ["src/core.py"],
                "evidence": ["e1"],
            },
            "corrective_work",
        ),
        (
            {
                "disposition": "plan_revision",
                "reason": "Add a check.",
                "amendment": {
                    "refinements": [
                        {
                            "batch": "core",
                            "checks": [
                                {"name": "extra", "command_definition": {"argv": ["pytest"]}}
                            ],
                        }
                    ]
                },
            },
            "plan_revision",
        ),
        (
            {
                "disposition": "escalate",
                "blocker": {
                    "reason": "Ambiguous.",
                    "needed_information": ["owner decision"],
                    "evidence": ["e1"],
                },
            },
            "escalate",
        ),
    ],
)
def test_compile_correction_decision_uses_durable_answer(
    answer: dict[str, Any], expected_disposition: str
) -> None:
    compiled = compile_decision(
        _correction_projection(),
        node_id="planner-plan",
        decision_request_id="gap-request",
        base_graph_position=999,
        answer=answer,
    )

    assert compiled.disposition == expected_disposition
    assert compiled.decision_record.value.family == "correction_decision"
    assert compiled.gap_records[0].value.classification in {
        "corrective_work_required",
        "graph_mutation_required",
        "human_decision_required",
    }


def test_no_gap_is_empty_and_cannot_dismiss_failed_mandatory_check() -> None:
    passed = compile_decision(
        _correction_projection(failed=False),
        node_id="planner-plan",
        decision_request_id="no-gap-request",
        base_graph_position=999,
        answer={
            "disposition": "no_gap",
            "reason": "The evidence closes the gap.",
            "evidence": ["e1"],
        },
    )
    assert passed.ops == ()
    assert passed.gap_records[0].value.classification == "no_gap"

    with pytest.raises((DecisionContractResolutionError, ValueError), match="failed"):
        compile_decision(
            _correction_projection(),
            node_id="planner-plan",
            decision_request_id="invalid-no-gap",
            base_graph_position=999,
            answer={
                "disposition": "no_gap",
                "reason": "Ignore the failed check.",
                "evidence": ["e1"],
            },
        )


def test_unknown_evidence_and_stale_baseline_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown evidence"):
        compile_decision(
            _correction_projection(),
            node_id="planner-plan",
            decision_request_id="unknown-evidence",
            base_graph_position=999,
            answer={
                "disposition": "escalate",
                "blocker": {
                    "reason": "Need help.",
                    "needed_information": ["owner"],
                    "evidence": ["e9"],
                },
            },
        )

    with pytest.raises((DecisionContractResolutionError, ValueError)):
        compile_decision(
            _correction_projection(),
            node_id="planner-plan",
            decision_request_id="stale-baseline",
            base_graph_position=0,
            answer={
                "disposition": "corrective_work",
                "diagnosis": "Failure.",
                "remedy": "Repair.",
                "focus": ["src/core.py"],
                "evidence": ["e1"],
            },
        )


def test_no_gap_rejects_unknown_evidence_alias() -> None:
    with pytest.raises(ValueError, match="unknown evidence"):
        compile_decision(
            _correction_projection(failed=False),
            node_id="planner-plan",
            decision_request_id="unknown-no-gap-evidence",
            base_graph_position=999,
            answer={"disposition": "no_gap", "reason": "Closed.", "evidence": ["e999"]},
        )


def test_correction_accepts_unrelated_output_after_observed_position() -> None:
    projection = _correction_projection(failed=False)
    unrelated = output_record_payloads_view(projection)["gap-evidence-check"].model_dump(
        mode="json"
    )
    unrelated.update(record_id="unrelated-check", graph_position=1000)
    projection = reduce_event(
        projection,
        graph_event(
            "output_record_accepted",
            unrelated,
            position=1000,
        ),
    )
    compiled = compile_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="unrelated-tail",
        base_graph_position=999,
        answer={"disposition": "no_gap", "reason": "Closed.", "evidence": ["e1"]},
    )
    assert compiled.disposition == "no_gap"
    assert "unrelated-check" not in compiled.read_set


def test_correction_compiles_all_checks_from_one_failure_report() -> None:
    projection = _correction_projection(check_count=3)
    resolved = resolve_correction_decision_context(projection, "planner-plan")
    check_ids = ("gap-evidence-check", "gap-evidence-check-2", "gap-evidence-check-3")
    assert resolved.failed_check_record_ids == check_ids
    assert dict(resolved.evidence_aliases.object_items()) == {
        f"e{index}": record_id
        for index, record_id in enumerate(("gap-evidence-report", *check_ids), 1)
    }
    compiled = compile_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="multiple-checks",
        base_graph_position=999,
        answer={
            "disposition": "corrective_work",
            "diagnosis": "The batch fails three checks.",
            "remedy": "Repair the bounded implementation.",
            "focus": ["src/core.py"],
            "evidence": ["e1", "e2", "e3", "e4"],
        },
    )
    assert set(check_ids).issubset(compiled.read_set)
    check_edges = [
        op
        for op in compiled.ops
        if op.get("op") == "create_edge" and op.get("to_port") == "check_result"
    ]
    assert {op["accepted_record_selector"]["record_id"] for op in check_edges} == set(check_ids)
    projection = reduce_event(
        projection,
        graph_event(
            "output_record_accepted",
            compiled.gap_records[0].model_dump(mode="json", by_alias=True),
            position=100,
        ),
    )
    events = apply_command(
        projection,
        [],
        "submit_patch",
        {"patch_id": compiled.patch_id, "base_graph_position": 999, "ops": list(compiled.ops)},
        PatchCommandContext(
            run_id="decision-run",
            current_graph_position=999,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert events[0].event_type == "graph_patch_accepted", events[0].payload


def test_correction_read_set_tracks_logical_requirements_and_authority_producers() -> None:
    projection = _correction_projection()
    compiled = compile_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="revision-sensitive-correction",
        base_graph_position=999,
        answer={
            "disposition": "corrective_work",
            "diagnosis": "Failure.",
            "remedy": "Repair.",
            "focus": ["src/core.py"],
            "evidence": ["e1"],
        },
    )
    records = output_record_payloads_view(projection)
    requirement = records["requirement-record-1"]
    assert isinstance(requirement, RequirementRecord)
    assert requirement.value.id in compiled.read_set
    assert requirement.value.version in compiled.read_set
    assert {
        records[record_id].producer_node_id
        for record_id in (
            "routine-snapshot-record",
            "accepted-decision-plan",
            "plan-passed",
            "requirement-record-1",
            "gap-evidence-report",
            "gap-evidence-check",
        )
    }.issubset(compiled.read_set)


def test_corrective_patch_uses_execution_promised_gap_identity() -> None:
    projection = _correction_projection()
    root = node_payload_view(projection, "root")
    assert root is not None
    projection = reduce_event(
        projection,
        graph_event(
            "lease_granted",
            {
                "lease_id": "gap-lease",
                "node_id": "planner-plan",
                "generation": 1,
                "execution_id": "gap-execution",
                "base_snapshot_id": "decision-base",
                "cache_authority_hash": root["cache_authority_hash"],
            },
            position=100,
        ),
    )
    compiled = compile_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="promised-gap",
        base_graph_position=999,
        answer={
            "disposition": "corrective_work",
            "diagnosis": "Failure.",
            "remedy": "Repair.",
            "focus": ["src/core.py"],
            "evidence": ["e1"],
        },
    )
    assert compiled.gap_records[0].record_id == "classified-gap-gap-execution"
    events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": compiled.patch_id,
            "base_graph_position": compiled.base_graph_position,
            "ops": list(compiled.ops),
        },
        PatchCommandContext(
            run_id="decision-run",
            current_graph_position=999,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert events[0].event_type == "graph_patch_accepted"
