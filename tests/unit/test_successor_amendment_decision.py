"""Behavioral coverage for Slice 3D successor amendment and blocker decisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest

from orchestrator.graph import (
    FakeClock,
    PatchCommandContext,
    SequentialIdGenerator,
    apply_command,
    build_projection,
    compile_batch_decision,
    compile_reliable_plan_region_ops,
    edges_view,
    input_bindings_view,
    node_payload_view,
    node_states_view,
    projection_to_checkpoint,
    reduce_event,
    resolve_batch_decision_context,
)
from tests.unit.test_graph_decisions import decision_successor_events
from tests.unit.graph_test_utils import event as graph_event


def _two_batch_events(
    *,
    horizon: int = 1,
    patch_budget: int = 2,
    disjoint_requirements: bool = False,
) -> list[Any]:
    events = decision_successor_events(2 if disjoint_requirements else 1)
    for index, event in enumerate(events):
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload.update(
                {
                    "planning_horizon": horizon,
                    "reliable_plan_remaining_horizons": 3 - horizon,
                    "scope": "core" if horizon == 1 else "api",
                }
            )
            if horizon > 1:
                cast(list[dict[str, Any]], payload["inputs"]).append(
                    {
                        "port": "plan_verification_report",
                        "direction": "input",
                        "schema": "VerificationReport",
                        "required": True,
                    }
                )
                if disjoint_requirements:
                    payload["inputs"] = [
                        item
                        for item in cast(list[dict[str, Any]], payload["inputs"])
                        if item.get("port") != "requirement_2"
                    ]
        elif (
            horizon > 1
            and event.event_type in {"edge_created", "input_bound"}
            and payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "verification_report"
        ):
            payload["to_port"] = "plan_verification_report"
        elif disjoint_requirements and event.event_type in {"edge_created", "input_bound"}:
            if (
                payload.get("to_node_id") == "planner-plan"
                and payload.get("to_port") == "requirement_2"
            ):
                continue
        elif (
            event.event_type == "output_record_accepted"
            and payload.get("record_id") == "routine-snapshot-record"
        ):
            value = dict(cast(dict[str, Any], payload["value"]))
            dynamic = dict(cast(dict[str, Any], value["dynamic_feature"]))
            dynamic["patch_budget"] = patch_budget
            value["dynamic_feature"] = dynamic
            payload["value"] = value
        elif (
            event.event_type == "output_record_accepted"
            and payload.get("record_id") == "accepted-decision-plan"
        ):
            value = dict(cast(dict[str, Any], payload["value"]))
            content = deepcopy(cast(dict[str, Any], value["content"]))
            first = deepcopy(cast(dict[str, Any], content["batches"][0]))
            if disjoint_requirements:
                first["requirements"] = ["r1"]
            content["summary"] = "Implement the core before its API."
            content["batches"] = [
                first,
                {
                    **first,
                    "key": "api",
                    "objective": "Expose the bounded core API.",
                    "scope": ["src/api.py"],
                    "requirements": ["r2"] if disjoint_requirements else ["r1"],
                    "depends_on": ["core"],
                    "acceptance": ["The API exposes the accepted core."],
                    "review_points": ["The API keeps the core contract."],
                },
            ]
            value["content"] = content
            payload["value"] = value
        events[index] = event.model_copy(update={"payload": payload})
    if disjoint_requirements:
        events = [
            event
            for event in events
            if not (
                event.event_type in {"edge_created", "input_bound"}
                and event.payload.get("to_node_id") == "planner-plan"
                and event.payload.get("to_port") == "requirement_2"
            )
        ]
    if horizon > 1:
        position = max(event.position for event in events)
        position += 1
        events.append(
            graph_event(
                "node_created",
                {
                    "node_id": "verifier-batch-core",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "completed",
                    "semantic_stage": "effectful_batch",
                    "planning_horizon": 1,
                    "declared_batch_id": "core",
                    "task_region_id": "successor-core",
                    "outputs": [
                        {
                            "port": "verification_report",
                            "direction": "output",
                            "schema": "VerificationReport",
                            "required": True,
                        }
                    ],
                },
                position=position,
            )
        )
        position += 1
        events.append(
            graph_event(
                "output_record_accepted",
                {
                    "record_id": "batch-core-passed",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "verifier-batch-core",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "graph_position": position,
                    "candidate_id": "candidate-core",
                    "candidate_record_id": "candidate-core",
                    "candidate_record_ids": ["candidate-core"],
                    "task_region_id": "successor-core",
                    "outcome": "passed",
                    "value": {"outcome": "passed", "grades": []},
                    "evaluated_record_ids": ["candidate-core"],
                },
                position=position,
            )
        )
        position += 1
        events.append(
            graph_event(
                "edge_created",
                {
                    "edge_id": "batch-core-verification-to-successor",
                    "from_node_id": "verifier-batch-core",
                    "from_port": "verification_report",
                    "to_node_id": "planner-plan",
                    "to_port": "verification_report",
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {"record_id": "batch-core-passed"},
                },
                position=position,
            )
        )
        position += 1
        events.append(
            graph_event(
                "input_bound",
                {
                    "edge_id": "batch-core-verification-to-successor",
                    "to_node_id": "planner-plan",
                    "to_port": "verification_report",
                    "record_ids": ["batch-core-passed"],
                    "bound_at_position": position,
                    "record_bound_positions": {"batch-core-passed": position},
                },
                position=position,
            )
        )
    return events


def _projection_with_bound_next_successor(
    events: list[Any],
) -> tuple[Any, str]:
    projection = build_projection(events)
    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-proceed-core",
        base_graph_position=99,
        answer={"disposition": "proceed", "implementation_notes": "Keep the API narrow."},
    )
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
            current_graph_position=99,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert patch_events[0].event_type == "graph_patch_accepted", patch_events
    position = max(event.position for event in events)
    positioned_patch = []
    for event in patch_events:
        position += 1
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        elif event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        positioned_patch.append(event.model_copy(update={"position": position, "payload": payload}))
    patched = build_projection([*events, *positioned_patch])
    successor_id = next(
        node_id
        for node_id in node_states_view(patched)
        if (
            (node := node_payload_view(patched, node_id)) is not None
            and node.get("semantic_stage") == "successor_planning"
            and node_id != "planner-plan"
        )
    )
    successor_edges = [
        edge
        for edge in edges_view(patched).values()
        if edge.to_node_id == successor_id and edge.dependency_type == "input_binding"
    ]
    verifier_edge = next(edge for edge in successor_edges if edge.to_port == "verification_report")
    position += 1
    report_id = "batch-core-passed"
    report = graph_event(
        "output_record_accepted",
        {
            "record_id": report_id,
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": verifier_edge.from_node_id,
            "port": "verification_report",
            "schema": "VerificationReport",
            "graph_position": position,
            "candidate_id": "candidate-core",
            "candidate_record_id": "candidate-core",
            "candidate_record_ids": ["candidate-core"],
            "task_region_id": "successor-core",
            "outcome": "passed",
            "value": {"outcome": "passed", "grades": []},
            "evaluated_record_ids": ["candidate-core"],
        },
        position=position,
    )
    bound_events = []
    for edge in successor_edges:
        selector = edge.accepted_record_selector or {}
        record_id = (
            report_id
            if edge.to_port == "verification_report"
            else (
                "accepted-decision-plan"
                if edge.to_port == "semantic_artifact"
                else (
                    "plan-passed"
                    if edge.to_port == "plan_verification_report"
                    else cast(str, selector.get("record_id"))
                )
            )
        )
        position += 1
        bound_events.append(
            graph_event(
                "input_bound",
                {
                    "edge_id": edge.edge_id,
                    "to_node_id": successor_id,
                    "to_port": edge.to_port,
                    "record_ids": [record_id],
                    "bound_at_position": position,
                    "record_bound_positions": {record_id: position},
                },
                position=position,
            )
        )
    return build_projection([*events, *positioned_patch, report, *bound_events]), successor_id


def _amendment_answer() -> dict[str, Any]:
    return {
        "disposition": "revise_plan",
        "reason": "The API batch needs a narrower contract before implementation.",
        "amendment": {
            "refinements": [
                {
                    "batch": "api",
                    "objective": "Expose only the accepted public core API.",
                    "scope": ["src/api.py"],
                    "acceptance": ["The API rejects unsupported input."],
                    "checks": [
                        {
                            "name": "api tests",
                            "command_definition": {"argv": ["pytest", "tests/test_api.py"]},
                        }
                    ],
                    "review_points": ["The public API remains backward compatible."],
                    "depends_on": [],
                }
            ]
        },
    }


def _mutate_event_payload(
    events: list[Any],
    *,
    event_type: str,
    predicate: Any,
    updates: dict[str, Any],
) -> list[Any]:
    result = []
    matched = False
    for event in events:
        payload = dict(event.payload)
        if event.event_type == event_type and predicate(payload):
            payload.update(updates)
            event = event.model_copy(update={"payload": payload})
            matched = True
        result.append(event)
    assert matched
    return result


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing-plan", "independent plan verification"),
        ("failed-plan", "independent plan verifier"),
        ("stale-plan", "independent plan verifier"),
        ("wrong-plan", "independent plan verifier"),
        ("missing-prior", "horizon verification"),
        ("failed-prior", "horizon verifier"),
        ("stale-prior", "exact prior batch verification"),
        ("wrong-prior", "exact prior batch verification"),
    ],
)
def test_horizon_two_rejects_inexact_separate_authorities_without_effects(
    case: str,
    message: str,
) -> None:
    events = _two_batch_events(horizon=2, disjoint_requirements=True)
    if case in {"missing-plan", "missing-prior"}:
        port = "plan_verification_report" if case == "missing-plan" else "verification_report"
        events = [
            event
            for event in events
            if not (
                event.event_type == "input_bound"
                and event.payload.get("to_node_id") == "planner-plan"
                and event.payload.get("to_port") == port
            )
        ]
    elif case in {"failed-plan", "stale-plan"}:
        updates = (
            {"outcome": "failed", "value": {"outcome": "failed", "grades": []}}
            if case == "failed-plan"
            else {"evaluated_record_ids": ["stale-plan"]}
        )
        events = _mutate_event_payload(
            events,
            event_type="output_record_accepted",
            predicate=lambda payload: payload.get("record_id") == "plan-passed",
            updates=updates,
        )
    elif case == "wrong-plan":
        events = _mutate_event_payload(
            events,
            event_type="input_bound",
            predicate=lambda payload: payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "plan_verification_report",
            updates={"record_ids": ["batch-core-passed"]},
        )
    elif case == "failed-prior":
        events = _mutate_event_payload(
            events,
            event_type="output_record_accepted",
            predicate=lambda payload: payload.get("record_id") == "batch-core-passed",
            updates={"outcome": "failed", "value": {"outcome": "failed", "grades": []}},
        )
    elif case == "stale-prior":
        events = _mutate_event_payload(
            events,
            event_type="node_created",
            predicate=lambda payload: payload.get("node_id") == "verifier-batch-core",
            updates={"planning_horizon": 0},
        )
    else:
        events = _mutate_event_payload(
            events,
            event_type="input_bound",
            predicate=lambda payload: payload.get("to_node_id") == "planner-plan"
            and payload.get("to_port") == "verification_report",
            updates={"record_ids": ["plan-passed"]},
        )
    projection = build_projection(events)
    before_projection = projection_to_checkpoint(projection, position=999)

    with pytest.raises(ValueError, match=message):
        compile_batch_decision(
            projection,
            node_id="planner-plan",
            decision_request_id=f"request-rejected-{case}",
            base_graph_position=999,
            answer={"disposition": "proceed", "implementation_notes": "Must not publish."},
        )

    assert projection_to_checkpoint(projection, position=999) == before_projection


def _events_with_transitively_cited_plan_verification() -> list[Any]:
    events = decision_successor_events()
    plan_event = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    other_plan_payload = deepcopy(dict(plan_event.payload))
    other_plan_payload["record_id"] = "other-decision-plan"
    events.append(
        graph_event(
            "output_record_accepted",
            other_plan_payload,
            position=max(event.position for event in events) + 1,
        )
    )
    events = _mutate_event_payload(
        events,
        event_type="output_record_accepted",
        predicate=lambda payload: payload.get("record_id") == "plan-passed",
        updates={
            "candidate_id": "other-decision-plan",
            "candidate_record_id": "other-decision-plan",
            "candidate_record_ids": ["other-decision-plan"],
            "evaluated_record_ids": [
                "other-decision-plan",
                "accepted-decision-plan",
                "requirement-record-1",
            ],
        },
    )
    events = _mutate_event_payload(
        events,
        event_type="input_bound",
        predicate=lambda payload: payload.get("to_node_id") == "verifier-plan"
        and payload.get("to_port") == "semantic_artifact",
        updates={"record_ids": ["other-decision-plan"]},
    )
    return events


def test_successor_rejects_plan_report_with_only_transitive_plan_evidence() -> None:
    events = _events_with_transitively_cited_plan_verification()

    with pytest.raises(ValueError, match="directly bound to the accepted plan"):
        resolve_batch_decision_context(build_projection(events), "planner-plan")


def test_trusted_macro_rejects_report_with_only_transitive_plan_evidence() -> None:
    projection = build_projection(_events_with_transitively_cited_plan_verification())

    with pytest.raises(ValueError, match="directly bound to the accepted plan"):
        compile_reliable_plan_region_ops(
            {
                "operation_key": "construct-core",
                "scope": "core",
                "objective": "Implement the bounded core.",
                "requirement_ids": ["REQ-1"],
                "dependencies": [],
                "acceptance": ["The bounded core passes."],
                "checks": [{"name": "oracle", "command_binding": "dynamic_feature_hidden_oracle"}],
                "rubric": ["The bounded requirement is satisfied."],
            },
            projection=projection,
            proposed_by_node_id="planner-plan",
            patch_id="patch-transitive-plan-report",
            trusted_plan_record_id="accepted-decision-plan",
            trusted_plan_verification_record_id="plan-passed",
            trusted_requirement_record_ids=("requirement-record-1",),
        )


@pytest.mark.parametrize(
    ("disjoint_requirements", "expected_aliases", "expected_record_ids"),
    [
        (False, {"r1": "REQ-1"}, ("requirement-record-1",)),
        (True, {"r2": "REQ-2"}, ("requirement-record-2",)),
    ],
)
def test_nonfinal_proceed_next_horizon_resolves_exact_selected_batch_authority(
    disjoint_requirements: bool,
    expected_aliases: dict[str, str],
    expected_record_ids: tuple[str, ...],
) -> None:
    projection, successor_id = _projection_with_bound_next_successor(
        _two_batch_events(disjoint_requirements=disjoint_requirements)
    )

    resolved = resolve_batch_decision_context(projection, successor_id)

    assert resolved.planning_horizon == 2
    assert resolved.selected_batch.key == "api"
    assert resolved.selected_batch.scope == ["src/api.py"]
    assert dict(resolved.requirement_aliases.object_items()) == expected_aliases
    assert resolved.requirement_record_ids == expected_record_ids

    compiled = compile_batch_decision(
        projection,
        node_id=successor_id,
        decision_request_id="request-proceed-api",
        base_graph_position=999,
        answer={"disposition": "proceed", "implementation_notes": "Finish the API."},
    )
    assert compiled.disposition == "proceed"
    submitted = apply_command(
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
            proposed_by_node_id=successor_id,
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert submitted[0].event_type == "graph_patch_accepted", submitted


def test_disjoint_horizon_amendment_retains_separate_ordered_authorities() -> None:
    projection, successor_id = _projection_with_bound_next_successor(
        _two_batch_events(patch_budget=3, disjoint_requirements=True)
    )
    answer = _amendment_answer()
    answer["amendment"]["additional_batches"] = [
        {
            "key": "docs",
            "objective": "Document the accepted API.",
            "scope": ["src/api.py"],
            "requirements": ["r1"],
            "depends_on": ["api"],
            "acceptance": ["The accepted API is documented."],
            "checks": [
                {
                    "name": "docs tests",
                    "command_definition": {"argv": ["pytest", "tests/test_docs.py"]},
                }
            ],
        }
    ]
    amended = compile_batch_decision(
        projection,
        node_id=successor_id,
        decision_request_id="request-amend-disjoint-api",
        base_graph_position=999,
        answer=answer,
    )
    semantic = amended.semantic_records[0]
    assert semantic.value.requirement_ids == ["REQ-1", "REQ-2"]
    assert semantic.value.source_record_ids[-2:] == [
        "requirement-record-1",
        "requirement-record-2",
    ]
    patch_events = apply_command(
        projection,
        [],
        "submit_patch",
        {
            "patch_id": amended.patch_id,
            "base_graph_position": amended.base_graph_position,
            "ops": list(amended.ops),
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=999,
            proposed_by_node_id=successor_id,
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert patch_events[0].event_type == "graph_patch_accepted", patch_events
    position = 1_000
    durable_patch = []
    for event in patch_events:
        position += 1
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        elif event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        durable_patch.append(event.model_copy(update={"position": position, "payload": payload}))
    position += 1
    semantic_payload = semantic.model_dump(mode="json", by_alias=True)
    semantic_payload["graph_position"] = position
    semantic_event = graph_event("output_record_accepted", semantic_payload, position=position)
    created = [op["node"] for op in amended.ops if op.get("op") == "create_node"]
    verifier_id = next(
        node["node_id"] for node in created if node.get("semantic_stage") == "plan_verification"
    )
    replacement_id = next(
        node["node_id"] for node in created if node.get("semantic_stage") == "successor_planning"
    )
    position += 1
    verifier_edge = next(
        op
        for op in amended.ops
        if op.get("op") == "create_edge"
        and op.get("to_node_id") == verifier_id
        and op.get("to_port") == "semantic_artifact"
    )
    verifier_binding_event = graph_event(
        "input_bound",
        {
            "edge_id": verifier_edge["edge_id"],
            "to_node_id": verifier_id,
            "to_port": "semantic_artifact",
            "record_ids": [semantic.record_id],
            "bound_at_position": position,
            "record_bound_positions": {semantic.record_id: position},
        },
        position=position,
    )
    position += 1
    report_id = "amended-plan-passed"
    report_event = graph_event(
        "output_record_accepted",
        {
            "record_id": report_id,
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": verifier_id,
            "port": "verification_report",
            "schema": "VerificationReport",
            "graph_position": position,
            "candidate_id": semantic.record_id,
            "candidate_record_id": semantic.record_id,
            "candidate_record_ids": [semantic.record_id],
            "task_region_id": "amendment-verification",
            "outcome": "passed",
            "value": {"outcome": "passed", "grades": []},
            "evaluated_record_ids": [semantic.record_id],
        },
        position=position,
    )
    interim = projection
    for event in [*durable_patch, semantic_event, verifier_binding_event, report_event]:
        interim = reduce_event(interim, event)
    bindings = input_bindings_view(interim).get(replacement_id, {})
    bound_events = []
    for edge in edges_view(interim).values():
        if edge.to_node_id != replacement_id or edge.to_port in bindings:
            continue
        selector = edge.accepted_record_selector or {}
        record_id = (
            semantic.record_id
            if edge.to_port == "semantic_artifact"
            else report_id
            if edge.to_port == "plan_verification_report"
            else cast(str, selector.get("record_id"))
        )
        position += 1
        bound_events.append(
            graph_event(
                "input_bound",
                {
                    "edge_id": edge.edge_id,
                    "to_node_id": replacement_id,
                    "to_port": edge.to_port,
                    "record_ids": [record_id],
                    "bound_at_position": position,
                    "record_bound_positions": {record_id: position},
                },
                position=position,
            )
        )
    final_projection = interim
    for event in bound_events:
        final_projection = reduce_event(final_projection, event)
    resolved = resolve_batch_decision_context(final_projection, replacement_id)
    assert resolved.plan_record_id == semantic.record_id
    assert resolved.plan_verification_record_id == report_id
    assert resolved.horizon_verification_record_id == "batch-core-passed"
    assert resolved.requirement_record_ids == ("requirement-record-2",)
    assert resolved.plan_requirement_alias_order == ("r1", "r2")
    final = compile_batch_decision(
        final_projection,
        node_id=replacement_id,
        decision_request_id="request-proceed-amended-api",
        base_graph_position=position,
        answer={"disposition": "proceed", "implementation_notes": "Finish the API."},
    )
    later_successor = next(
        op["node"]
        for op in final.ops
        if op.get("op") == "create_node"
        and op["node"].get("semantic_stage") == "successor_planning"
    )
    assert later_successor["planning_horizon"] == 3
    assert any(
        op.get("op") == "create_edge"
        and op.get("from_node_id") == verifier_id
        and op.get("to_node_id") == later_successor["node_id"]
        and op.get("to_port") == "plan_verification_report"
        for op in final.ops
    )
    submitted = apply_command(
        final_projection,
        [],
        "submit_patch",
        {
            "patch_id": final.patch_id,
            "base_graph_position": final.base_graph_position,
            "ops": list(final.ops),
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=position,
            proposed_by_node_id=replacement_id,
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert submitted[0].event_type == "graph_patch_accepted", submitted


def test_revise_plan_builds_full_superseding_plan_and_verification_gate() -> None:
    projection = build_projection(_two_batch_events(horizon=2))
    resolved = resolve_batch_decision_context(projection, "planner-plan")

    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-amend-api",
        base_graph_position=99,
        answer=_amendment_answer(),
    )

    assert compiled.disposition == "revise_plan"
    assert compiled.completion_state == "completed"
    assert len(compiled.output_records) == 2
    amended = compiled.output_records[1]
    assert amended.value.supersedes_record_id == resolved.plan_record_id
    prospective = cast(dict[str, Any], amended.value.content)
    assert prospective["batches"][0] == resolved.accepted_plan.batches[0].model_dump(
        mode="json", exclude_none=True
    )
    assert prospective["batches"][1]["key"] == "api"
    assert prospective["batches"][1]["requirements"] == ["r1"]
    assert prospective["batches"][1]["acceptance"] == [
        "The API exposes the accepted core.",
        "The API rejects unsupported input.",
    ]
    assert prospective["batches"][1]["depends_on"] == ["core"]
    assert prospective["batches"][1]["checks"] == [
        {
            "name": "unit",
            "command_definition": {"argv": ["pytest"]},
        },
        {
            "name": "api tests",
            "command_definition": {"argv": ["pytest", "tests/test_api.py"]},
        },
    ]
    assert prospective["batches"][1]["review_points"] == [
        "The API keeps the core contract.",
        "The public API remains backward compatible.",
    ]

    created = [op["node"] for op in compiled.ops if op.get("op") == "create_node"]
    assert not any(node.get("semantic_stage") == "effectful_batch" for node in created)
    verifier = next(node for node in created if node.get("semantic_stage") == "plan_verification")
    successor = next(
        node
        for node in created
        if node.get("semantic_stage") == "successor_planning" and node.get("role") == "planner"
    )
    assert verifier["accepted_plan_amendment_record_id"] == amended.record_id
    assert successor["accepted_plan_amendment_record_id"] == amended.record_id
    assert successor["planning_horizon"] == 2
    assert successor["reliable_plan_remaining_horizons"] == 1
    assert any(
        op.get("from_node_id") == verifier["node_id"]
        and op.get("to_node_id") == successor["node_id"]
        and op.get("accepted_record_selector", {}).get("outcome") == "passed"
        for op in compiled.ops
    )
    assert {"planner-plan", resolved.plan_record_id, resolved.plan_verification_record_id} <= set(
        compiled.read_set
    )
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
            current_graph_position=99,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert patch_events[0].event_type == "graph_patch_accepted", patch_events

    replay = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-amend-api",
        base_graph_position=99,
        answer=_amendment_answer(),
    )
    assert replay == compiled


@pytest.mark.parametrize(
    ("events", "mutate", "message"),
    [
        (
            _two_batch_events(horizon=2),
            lambda answer: answer["amendment"]["refinements"][0].update(batch="core"),
            "accepted prefix",
        ),
        (
            _two_batch_events(horizon=2),
            lambda answer: answer["amendment"]["refinements"][0].update(
                scope=["src/api.py", "src/new.py"]
            ),
            "scope",
        ),
        (
            _two_batch_events(horizon=2),
            lambda answer: answer["amendment"]["refinements"][0].update(depends_on=["missing"]),
            "unknown dependencies",
        ),
        (
            _two_batch_events(horizon=1),
            lambda answer: answer["amendment"].update(
                refinements=[],
                additional_batches=[
                    {
                        "key": "extra",
                        "objective": "Unauthorized extra work.",
                        "scope": ["src/api.py"],
                        "requirements": ["r1"],
                        "acceptance": ["Extra work passes."],
                        "checks": [{"name": "extra", "command_definition": {"argv": ["pytest"]}}],
                    }
                ],
            ),
            "patch budget",
        ),
        (
            _two_batch_events(horizon=2, patch_budget=3),
            lambda answer: answer["amendment"].update(
                refinements=[],
                additional_batches=[
                    {
                        "key": "extra",
                        "objective": "Work outside accepted scope.",
                        "scope": ["src/outside.py"],
                        "requirements": ["r1"],
                        "acceptance": ["Outside work passes."],
                        "checks": [{"name": "outside", "command_definition": {"argv": ["pytest"]}}],
                    }
                ],
            ),
            "authorized scope",
        ),
        (
            _two_batch_events(horizon=1),
            lambda answer: answer["amendment"]["refinements"][0].update(
                batch="core", scope=["src/core.py"], depends_on=["api"]
            ),
            "dependency cycle",
        ),
        (
            _two_batch_events(horizon=2, patch_budget=3),
            lambda answer: answer["amendment"].update(
                refinements=[],
                additional_batches=[
                    {
                        "key": "extra",
                        "objective": "Work with unbound authority.",
                        "scope": ["src/api.py"],
                        "requirements": ["r9"],
                        "acceptance": ["Unbound work passes."],
                        "checks": [{"name": "unbound", "command_definition": {"argv": ["pytest"]}}],
                    }
                ],
            ),
            "unknown requirement aliases",
        ),
    ],
)
def test_revise_plan_rejects_authority_weakening_without_effects(
    events: list[Any], mutate: Any, message: str
) -> None:
    projection = build_projection(events)
    answer = _amendment_answer()
    mutate(answer)

    with pytest.raises(ValueError, match=message):
        compile_batch_decision(
            projection,
            node_id="planner-plan",
            decision_request_id="request-rejected-amendment",
            base_graph_position=99,
            answer=answer,
        )


def test_revise_plan_adds_only_within_frozen_total_capacity() -> None:
    projection = build_projection(_two_batch_events(horizon=2, patch_budget=3))
    answer = _amendment_answer()
    answer["amendment"] = {
        "additional_batches": [
            {
                "key": "docs",
                "objective": "Document the accepted API.",
                "scope": ["src/api.py"],
                "requirements": ["r1"],
                "depends_on": ["api"],
                "acceptance": ["The accepted API is documented."],
                "checks": [{"name": "docs", "command_definition": {"argv": ["pytest"]}}],
            }
        ]
    }

    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-add-batch",
        base_graph_position=99,
        answer=answer,
    )

    amended = compiled.output_records[1]
    content = cast(dict[str, Any], amended.value.content)
    assert [batch["key"] for batch in content["batches"]] == ["core", "api", "docs"]
    successor = next(
        op["node"]
        for op in compiled.ops
        if op.get("op") == "create_node"
        and op["node"].get("semantic_stage") == "successor_planning"
        and op["node"].get("role") == "planner"
    )
    assert successor["planning_horizon"] == 2
    assert successor["reliable_plan_remaining_horizons"] == 2


@pytest.mark.parametrize("fields", [("objective",), ("scope",), ("objective", "scope")])
def test_revise_plan_rejects_unchanged_refinements(fields: tuple[str, ...]) -> None:
    projection = build_projection(_two_batch_events(horizon=2))
    resolved = resolve_batch_decision_context(projection, "planner-plan")
    batch = resolved.selected_batch.model_dump(mode="json")
    answer = _amendment_answer()
    answer["amendment"] = {
        "refinements": [{"batch": "api", **{field: batch[field] for field in fields}}]
    }
    with pytest.raises(ValueError, match="does not change"):
        compile_batch_decision(
            projection,
            node_id="planner-plan",
            decision_request_id="unchanged-refinement",
            base_graph_position=99,
            answer=answer,
        )


def test_revise_plan_accepts_unchanged_fields_with_an_actual_addition() -> None:
    projection = build_projection(_two_batch_events(horizon=2))
    resolved = resolve_batch_decision_context(projection, "planner-plan")
    answer = _amendment_answer()
    answer["amendment"] = {
        "refinements": [
            {
                "batch": "api",
                "objective": resolved.selected_batch.objective,
                "scope": list(resolved.selected_batch.scope),
                "acceptance": ["Invalid API input is rejected."],
            }
        ]
    }
    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="mixed-refinement",
        base_graph_position=99,
        answer=answer,
    )
    content = cast(dict[str, Any], compiled.semantic_records[0].value.content)
    assert content["batches"][1]["acceptance"] == [
        *resolved.selected_batch.acceptance,
        "Invalid API input is rejected.",
    ]


@pytest.mark.parametrize("actual_change", [False, True])
def test_revise_plan_treats_reordered_scope_as_unchanged(actual_change: bool) -> None:
    events = _two_batch_events(horizon=2)
    original_scope = ["src/api.py", "src/routes.py"]
    for index, event in enumerate(events):
        if event.payload.get("record_id") == "accepted-decision-plan":
            payload = deepcopy(event.payload)
            payload["value"]["content"]["batches"][1]["scope"] = original_scope
            events[index] = event.model_copy(update={"payload": payload})
    projection = build_projection(events)
    answer = _amendment_answer()
    refinement: dict[str, Any] = {"batch": "api", "scope": list(reversed(original_scope))}
    if actual_change:
        refinement["acceptance"] = ["Invalid API input is rejected."]
    answer["amendment"] = {"refinements": [refinement]}
    if not actual_change:
        with pytest.raises(ValueError, match="does not change"):
            compile_batch_decision(
                projection,
                node_id="planner-plan",
                decision_request_id="reordered-scope",
                base_graph_position=99,
                answer=answer,
            )
        return
    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="reordered-scope-addition",
        base_graph_position=99,
        answer=answer,
    )
    content = cast(dict[str, Any], compiled.semantic_records[0].value.content)
    assert content["batches"][1]["scope"] == original_scope
    assert "Invalid API input is rejected." in content["batches"][1]["acceptance"]


def test_blocked_decision_creates_existing_human_request_and_fails_lineage() -> None:
    projection = build_projection(_two_batch_events(horizon=1))
    answer = {
        "disposition": "blocked",
        "blocker": {
            "reason": "The owning team has not defined the public compatibility policy.",
            "needed_information": ["Confirm whether legacy payloads must remain accepted."],
            "evidence": ["e1"],
        },
    }

    compiled = compile_batch_decision(
        projection,
        node_id="planner-plan",
        decision_request_id="request-blocked",
        base_graph_position=99,
        answer=answer,
    )

    assert compiled.disposition == "blocked"
    assert compiled.completion_state == "failed"
    assert len(compiled.output_records) == 1
    created = [op["node"] for op in compiled.ops if op.get("op") == "create_node"]
    assert len(created) == 1
    gate = created[0]
    assert gate["kind"] == "human_gate"
    assert gate["decision_request"]["decision_type"] == "clarification"
    assert gate["decision_request"]["target_node_id"] == "planner-plan"
    assert not any(
        node.get("kind") in {"worker", "verifier", "check", "final_gate"}
        or node.get("semantic_stage") == "successor_planning"
        for node in created
    )

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
            current_graph_position=99,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert patch_events[0].event_type == "graph_patch_accepted", patch_events
    assert any(
        event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "decision_request"
        for event in patch_events
    )


def test_blocked_decision_rejects_unknown_evidence_alias() -> None:
    projection = build_projection(_two_batch_events(horizon=1))

    with pytest.raises(ValueError, match="evidence alias"):
        compile_batch_decision(
            projection,
            node_id="planner-plan",
            decision_request_id="request-blocked-bad-evidence",
            base_graph_position=99,
            answer={
                "disposition": "blocked",
                "blocker": {
                    "reason": "Missing policy.",
                    "needed_information": ["Provide the policy."],
                    "evidence": ["e9"],
                },
            },
        )
