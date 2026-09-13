"""Rejected-plan corrections preserve exact proposal lineage and verified authority."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import (
    DecisionContractResolutionError,
    FakeClock,
    PatchCommandContext,
    SequentialIdGenerator,
    apply_command,
    reduce_event,
    edges_view,
    evidence_closure_for_node,
    resolve_batch_decision_context,
    build_projection,
    compile_batch_decision,
    compile_correction_decision,
    projection_to_checkpoint,
    output_record_payloads_view,
    resolve_correction_decision_context,
)
from tests.unit.graph_test_utils import event as graph_event
from tests.unit.test_successor_amendment_decision import _amendment_answer, _two_batch_events


def _rejected_amendment_events(*, horizon: int = 2) -> tuple[list[Any], str, str]:
    events = _two_batch_events(horizon=horizon, disjoint_requirements=True)
    if horizon == 2:
        events = [
            event.model_copy(
                update={"payload": {**event.payload, "record_ids": ["requirement-record-2"]}}
            )
            if event.event_type == "input_bound"
            and event.payload.get("to_node_id") == "planner-plan"
            and event.payload.get("to_port") == "requirement_1"
            else event
            for event in events
        ]
    compiled = compile_batch_decision(
        build_projection(events),
        node_id="planner-plan",
        decision_request_id="rejected-amendment",
        base_graph_position=999,
        answer=_amendment_answer(),
    )
    position = max(event.position for event in events)

    def append(kind: str, payload: dict[str, Any]) -> None:
        nonlocal position
        position += 1
        events.append(graph_event(kind, payload, position=position))

    parent = next(
        dict(event.payload)
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
    )
    for op in compiled.ops:
        if op["op"] == "create_node":
            append(
                "node_created",
                {
                    **{
                        key: value
                        for key, value in parent.items()
                        if key.startswith("reliable_plan_")
                    },
                    **dict(op["node"]),
                },
            )
        elif op["op"] == "create_edge":
            append("edge_created", {key: value for key, value in op.items() if key != "op"})
    semantic = compiled.semantic_records[0]
    append(
        "output_record_accepted",
        {**semantic.model_dump(mode="json"), "graph_position": position + 1},
    )
    verifier_id = next(
        op["node"]["node_id"]
        for op in compiled.ops
        if op["op"] == "create_node" and op["node"].get("kind") == "verifier"
    )
    gap_id = next(
        op["node"]["node_id"]
        for op in compiled.ops
        if op["op"] == "create_node" and op["node"].get("role") == "gap_planner"
    )
    append(
        "output_record_accepted",
        {
            "record_id": "rejected-plan-report",
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": verifier_id,
            "port": "verification_report",
            "schema": "VerificationReport",
            "graph_position": position + 1,
            "outcome": "failed",
            "value": {"outcome": "failed", "grades": []},
            "evaluated_record_ids": [
                semantic.record_id,
                "requirement-record-1",
                "requirement-record-2",
            ],
        },
    )
    for op in compiled.ops:
        if op["op"] != "create_edge":
            continue
        record_id = None
        if op["to_node_id"] == gap_id:
            record_id = (
                "routine-snapshot-record"
                if op["to_port"] == "routine_snapshot"
                else "rejected-plan-report"
            )
        elif op["to_node_id"] == verifier_id and op["to_port"] == "semantic_artifact":
            record_id = semantic.record_id
        if record_id is not None:
            append(
                "input_bound",
                {
                    "edge_id": op["edge_id"],
                    "to_node_id": op["to_node_id"],
                    "to_port": op["to_port"],
                    "record_ids": [record_id],
                    "bound_at_position": position + 1,
                    "record_bound_positions": {record_id: position + 1},
                },
            )
    append(
        "edge_created",
        {
            "edge_id": "baseline-plan-to-verifier",
            "from_node_id": "worker-discovery",
            "from_port": "semantic_artifact",
            "to_node_id": "verifier-plan",
            "to_port": "semantic_artifact",
            "dependency_type": "input_binding",
            "accepted_record_selector": {"record_id": "accepted-decision-plan"},
        },
    )
    append(
        "input_bound",
        {
            "edge_id": "baseline-plan-to-verifier",
            "to_node_id": "verifier-plan",
            "to_port": "semantic_artifact",
            "record_ids": ["accepted-decision-plan"],
            "bound_at_position": position + 1,
            "record_bound_positions": {"accepted-decision-plan": position + 1},
        },
    )
    return events, gap_id, semantic.record_id


def _repair(answer: dict[str, Any] | None = None, *, events: list[Any] | None = None):
    seed, gap_id, rejected_id = _rejected_amendment_events()
    projection = build_projection(events or seed)
    compiled = compile_correction_decision(
        projection,
        node_id=gap_id,
        decision_request_id="repair-amendment",
        base_graph_position=999,
        answer=answer
        or {
            "disposition": "plan_revision",
            "reason": "Resolve the plan verifier finding.",
            "amendment": {
                "refinements": [
                    {"batch": "api", "review_points": ["Confirm rejected amendment remedy."]}
                ]
            },
        },
    )
    return projection, compiled, gap_id, rejected_id


def test_rejected_amendment_uses_last_verified_plan_and_exact_prior_horizon() -> None:
    projection, compiled, gap_id, rejected_id = _repair()
    resolved = resolve_correction_decision_context(projection, gap_id)
    assert resolved.phase == "plan_amendment"
    assert resolved.plan_record_id == rejected_id
    assert resolved.selected_batch is None
    assert resolved.plan_verification_record_id is None
    assert resolved.preserved_plan_record_id == "accepted-decision-plan"
    assert resolved.preserved_plan_verification_record_id == "plan-passed"
    assert resolved.horizon_verification_record_id == "batch-core-passed"
    assert resolved.planning_horizon == 2
    assert resolved.requirement_record_ids == ("requirement-record-1", "requirement-record-2")
    assert set(compiled.read_set) >= {
        rejected_id,
        "rejected-plan-report",
        "accepted-decision-plan",
        "plan-passed",
        "batch-core-passed",
        "REQ-1",
        "REQ-2",
        "requirement-record-1",
        "requirement-record-2",
    }
    replacement = compiled.semantic_records[0]
    assert replacement.value.supersedes_record_id == rejected_id
    assert (
        replacement.value.content["batches"][0]
        == resolved.plan.model_dump(mode="json", exclude_none=True)["batches"][0]
    )
    successor = next(
        op["node"]
        for op in compiled.ops
        if op["op"] == "create_node" and op["node"].get("semantic_stage") == "successor_planning"
    )
    assert successor["planning_horizon"] == 2
    assert any(
        op.get("to_node_id") == successor["node_id"]
        and op.get("to_port") == "verification_report"
        and op.get("from_node_id") == "verifier-batch-core"
        for op in compiled.ops
    )


@pytest.mark.parametrize(
    "answer, message",
    [
        (
            {"disposition": "no_gap", "reason": "Dismiss failure.", "evidence": ["e1"]},
            "permits only",
        ),
        (
            {
                "disposition": "corrective_work",
                "diagnosis": "Rejected plan",
                "remedy": "Edit code",
                "focus": ["src/api.py"],
                "evidence": ["e1"],
            },
            "permits only",
        ),
        (
            {
                "disposition": "plan_revision",
                "reason": "Change completed work",
                "amendment": {
                    "refinements": [{"batch": "core", "objective": "Rewrite completed core."}]
                },
            },
            "accepted prefix",
        ),
        (
            {
                "disposition": "plan_revision",
                "reason": "Widen scope",
                "amendment": {"refinements": [{"batch": "api", "scope": ["src/unauthorized.py"]}]},
            },
            "scope exceeds",
        ),
        (
            {
                "disposition": "escalate",
                "blocker": {
                    "reason": "Need guidance",
                    "needed_information": ["owner decision"],
                    "evidence": ["e999"],
                },
            },
            "unknown evidence",
        ),
    ],
)
def test_rejected_plan_invalid_answers_leave_projection_unchanged(
    answer: dict[str, Any], message: str
) -> None:
    events, gap_id, _ = _rejected_amendment_events()
    projection = build_projection(events)
    before = projection_to_checkpoint(projection, position=999)
    with pytest.raises(ValueError, match=message):
        compile_correction_decision(
            projection,
            node_id=gap_id,
            decision_request_id="invalid-repair",
            base_graph_position=999,
            answer=answer,
        )
    assert projection_to_checkpoint(projection, position=999) == before


def test_rejected_plan_escalation_uses_existing_gate_without_publishing_plan() -> None:
    _, compiled, _, _ = _repair(
        {
            "disposition": "escalate",
            "blocker": {
                "reason": "Scope cannot safely satisfy the finding.",
                "needed_information": ["Revised frozen scope"],
                "evidence": ["e1"],
            },
        }
    )
    assert compiled.completion_state == "failed"
    assert not compiled.semantic_records
    assert any(
        op["op"] == "create_node" and op["node"]["kind"] == "human_gate" for op in compiled.ops
    )


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("wrong_evaluated_plan", "does not evaluate"),
        ("missing_prior_gate", "prior horizon"),
        ("cycle", "cyclic"),
        ("changed_requirement", "requirement authority"),
    ],
)
def test_rejected_plan_lineage_failures_close_without_effects(mutation: str, message: str) -> None:
    events, gap_id, rejected_id = _rejected_amendment_events()
    updated = []
    for event in events:
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            if (
                mutation == "wrong_evaluated_plan"
                and payload.get("record_id") == "rejected-plan-report"
            ):
                payload["evaluated_record_ids"] = ["accepted-decision-plan"]
            if mutation == "missing_prior_gate" and payload.get("record_id") == "batch-core-passed":
                continue
            if payload.get("record_id") == rejected_id and mutation in {
                "cycle",
                "changed_requirement",
            }:
                value = dict(payload["value"])
                if mutation == "cycle":
                    value["supersedes_record_id"] = rejected_id
                    value["source_record_ids"] = [*value["source_record_ids"], rejected_id]
                else:
                    value["requirement_ids"] = list(reversed(value["requirement_ids"]))
                payload["value"] = value
        updated.append(event.model_copy(update={"payload": payload}))
    with pytest.raises(DecisionContractResolutionError, match=message):
        resolve_correction_decision_context(build_projection(updated), gap_id)


def test_later_horizon_repair_patch_accepts_and_resolves_exact_verified_successor() -> None:
    projection, compiled, gap_id, _ = _repair()
    patch_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": compiled.patch_id,
            "base_graph_position": compiled.base_graph_position,
            "ops": list(compiled.ops),
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=999,
            proposed_by_node_id=gap_id,
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert patch_events[0].event_type == "graph_patch_accepted", patch_events[0].payload
    for position, event in enumerate(patch_events, start=1000):
        payload = dict(event.payload)
        if event.event_type == "input_bound":
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {
                record_id: position for record_id in payload["record_ids"]
            }
        projection = reduce_event(
            projection, event.model_copy(update={"position": position, "payload": payload})
        )
    replacement = compiled.semantic_records[0]
    projection = reduce_event(
        projection,
        graph_event(
            "output_record_accepted",
            {**replacement.model_dump(mode="json"), "graph_position": 1200},
            position=1200,
        ),
    )
    successor = next(
        op["node"]
        for op in compiled.ops
        if op["op"] == "create_node" and op["node"].get("semantic_stage") == "successor_planning"
    )
    verifier = next(
        op["node"]
        for op in compiled.ops
        if op["op"] == "create_node" and op["node"].get("kind") == "verifier"
    )
    projection = reduce_event(
        projection,
        graph_event(
            "output_record_accepted",
            {
                "record_id": "repair-plan-passed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": verifier["node_id"],
                "port": "verification_report",
                "schema": "VerificationReport",
                "graph_position": 1201,
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
                "evaluated_record_ids": [replacement.record_id],
            },
            position=1201,
        ),
    )
    for edge in edges_view(projection).values():
        if edge.to_node_id != successor["node_id"] or edge.dependency_type != "input_binding":
            continue
        record_id = {
            "verification_report": "batch-core-passed",
            "plan_verification_report": "repair-plan-passed",
            "semantic_artifact": replacement.record_id,
        }.get(edge.to_port)
        if record_id is None:
            record_id = (edge.accepted_record_selector or {})["record_id"]
        bound_record = output_record_payloads_view(projection)[record_id]
        bound_position = 1202 if bound_record.graph_position is not None else 0
        record_position = bound_position if bound_record.graph_position is not None else -1
        projection = reduce_event(
            projection,
            graph_event(
                "input_bound",
                {
                    "edge_id": edge.edge_id,
                    "to_node_id": edge.to_node_id,
                    "to_port": edge.to_port,
                    "record_ids": [record_id],
                    "bound_at_position": bound_position,
                    "record_bound_positions": {record_id: record_position},
                },
                position=bound_position,
            ),
        )
    resolved = resolve_batch_decision_context(projection, successor["node_id"])
    assert resolved.planning_horizon == 2
    assert resolved.selected_batch.key == "api"
    assert resolved.requirement_record_ids == ("requirement-record-2",)
    assert resolved.plan_record_id == replacement.record_id
    assert resolved.plan_verification_record_id == "repair-plan-passed"
    assert resolved.horizon_verification_record_id == "batch-core-passed"


@pytest.mark.parametrize("direct_pass_available", [True, False])
def test_plan_repair_ignores_indirect_ancestor_mentions_in_passing_reports(
    direct_pass_available: bool,
) -> None:
    events, gap_id, _ = _rejected_amendment_events()
    baseline = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    passed = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "plan-passed"
    )
    position = max(event.position for event in events)
    additions = [
        (
            "node_created",
            {
                "node_id": "verifier-indirect",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "semantic_stage": "plan_verification",
            },
        ),
        (
            "node_created",
            {
                "node_id": "ancestor-evidence-source",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
            },
        ),
        ("output_record_accepted", {**dict(baseline.payload), "record_id": "unrelated-plan"}),
        (
            "output_record_accepted",
            {
                **dict(passed.payload),
                "record_id": "ancestor-review-evidence",
                "producer_node_id": "ancestor-evidence-source",
                "outcome": "failed",
                "value": {"outcome": "failed", "grades": []},
            },
        ),
    ]
    for port, record_id, source in [
        ("semantic_artifact", "unrelated-plan", "worker-discovery"),
        ("verification_evidence", "ancestor-review-evidence", "ancestor-evidence-source"),
    ]:
        edge_id = f"indirect-{port}"
        additions.extend(
            [
                (
                    "edge_created",
                    {
                        "edge_id": edge_id,
                        "from_node_id": source,
                        "from_port": "semantic_artifact"
                        if port == "semantic_artifact"
                        else "verification_report",
                        "to_node_id": "verifier-indirect",
                        "to_port": port,
                        "dependency_type": "input_binding",
                        "accepted_record_selector": {"record_id": record_id},
                    },
                ),
                (
                    "input_bound",
                    {
                        "edge_id": edge_id,
                        "to_node_id": "verifier-indirect",
                        "to_port": port,
                        "record_ids": [record_id],
                        "bound_at_position": position + len(additions) + 2,
                        "record_bound_positions": {record_id: position + len(additions) + 2},
                    },
                ),
            ]
        )
    for kind, payload in additions:
        position += 1
        if kind == "output_record_accepted":
            payload["graph_position"] = position
        events.append(graph_event(kind, payload, position=position))
    if not direct_pass_available:
        events = [event for event in events if event is not passed]
    closure = evidence_closure_for_node(build_projection(events), "verifier-indirect")
    assert "accepted-decision-plan" in closure.evaluated_record_ids
    events.append(
        graph_event(
            "output_record_accepted",
            {
                **dict(passed.payload),
                "record_id": "indirect-plan-passed",
                "producer_node_id": "verifier-indirect",
                "graph_position": position + 1,
                "candidate_id": "unrelated-plan",
                "candidate_record_id": "unrelated-plan",
                "candidate_record_ids": list(closure.candidate_record_ids),
                "evaluated_record_ids": list(closure.evaluated_record_ids),
            },
            position=position + 1,
        )
    )
    projection = build_projection(events)
    if direct_pass_available:
        resolved = resolve_correction_decision_context(projection, gap_id)
        assert resolved.preserved_plan_record_id == "accepted-decision-plan"
        assert resolved.preserved_plan_verification_record_id == "plan-passed"
        assert "indirect-plan-passed" not in resolved.authority_record_ids
    else:
        with pytest.raises(DecisionContractResolutionError, match="requires a verified baseline"):
            resolve_correction_decision_context(projection, gap_id)
