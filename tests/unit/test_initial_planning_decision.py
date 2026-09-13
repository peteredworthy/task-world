"""Behavioral coverage for decision-v1 initial planning."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from orchestrator.config import RoutineConfig
from orchestrator.graph import (
    DECISION_PLAN_SCHEMA_ID,
    DiscoveryBrief,
    FakeClock,
    ImplementationPlan,
    PatchCommandContext,
    SequentialIdGenerator,
    apply_command,
    build_projection,
    compile_routine,
    compile_discovery_brief,
    node_kinds_view,
    node_payload_view,
    requirements_for_node_view,
    reduce_event,
    resolve_decision_applicability,
    resolve_discovery_brief_context,
    resolve_implementation_plan_context,
)
from orchestrator.graph_runtime import GraphDispatchContext
from orchestrator.graph_runtime.dispatch import _submission_contract
from orchestrator.graph_runtime.prompts import _prompt_for_node


def _decision_routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "dynamic-graph-feature",
            "name": "Decision planning",
            "agent_interaction_contract": "decision-v1",
            "semantic_artifact_schemas": [
                {
                    "schema_id": "custom.descriptive-plan",
                    "version": 1,
                    "semantic_role": "implementation_plan",
                    "json_schema": {
                        "type": "object",
                        "properties": {"checks": {"type": "array"}},
                    },
                }
            ],
            "steps": [
                {
                    "id": "plan",
                    "title": "Plan the supplied feature",
                    "kind": "planner",
                }
            ],
        }
    )


def _durable_initial_events() -> list[Any]:
    assignments = {
        role: {
            "runner_type": "codex_server",
            "model": "selected-model",
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
    compiled = compile_routine(
        _decision_routine(),
        FakeClock(),
        SequentialIdGenerator(),
        run_id="initial-decision",
        run_config={
            "feature_spec_path": "docs/spec.md",
            "feature_spec_content": "Implement the bounded parser feature.",
            "acceptance_command": "uv run pytest tests/unit/test_parser.py",
            "hidden_oracle_command": "",
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_selected_runner_type": "codex_server",
            "reliable_plan_model_assignments": {
                "arm_id": "initial-decision-test",
                **assignments,
            },
            "reliable_plan_one_horizon_authorized": True,
            "reliable_plan_remaining_horizons": 1,
        },
    )
    durable: list[Any] = []
    for position, item in enumerate(compiled, start=1):
        payload = dict(item.payload)
        if item.event_type == "output_record_accepted":
            payload["graph_position"] = position
        if item.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        durable.append(item.model_copy(update={"position": position, "payload": payload}))
    return durable


def _initial_context() -> GraphDispatchContext:
    events = _durable_initial_events()
    projection = build_projection(events)
    node_id = "planner-plan"
    node = node_payload_view(projection, node_id)
    assert node is not None
    return GraphDispatchContext(
        run_id="initial-decision",
        node_id=node_id,
        node_kind="planner",
        node_payload=node,
        requirements=requirements_for_node_view(projection, node_id),
        worktree_path="/tmp/decision-worktree",
        lease_id="lease-initial",
        lease_generation=1,
        execution_id="execution-initial",
        base_snapshot_id="snapshot-initial",
        dispatch_event_id="dispatch-initial",
        graph_projection=projection,
        graph_events=events,
    )


def _discovery_context() -> GraphDispatchContext:
    initial = _initial_context()
    compilation = compile_discovery_brief(
        initial.graph_projection,
        node_id=initial.node_id,
        decision_request_id="initial-request",
        base_graph_position=initial.graph_position,
        answer={
            "questions": ["Which existing parser seam should own the feature?"],
            "rationale": "Repository ownership still requires judgment.",
            "focus": ["docs/spec.md"],
        },
    )
    patch_events = apply_command(
        initial.graph_projection,
        [],
        "submit_patch",
        {
            "patch_id": compilation.patch_id,
            "base_graph_position": compilation.base_graph_position,
            "ops": list(compilation.ops),
        },
        PatchCommandContext(
            run_id=initial.run_id,
            current_graph_position=initial.graph_position,
            proposed_by_node_id=initial.node_id,
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert patch_events and patch_events[0].event_type == "graph_patch_accepted"
    projection = initial.graph_projection
    durable_patch_events: list[Any] = []
    for offset, event in enumerate(patch_events, start=1):
        position = initial.graph_position + offset
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        durable = event.model_copy(update={"position": position, "payload": payload})
        projection = reduce_event(projection, durable, enforce_relationships=True)
        durable_patch_events.append(durable)
    discovery_id = next(
        node_id
        for node_id in node_kinds_view(projection)
        if (node := node_payload_view(projection, node_id)) is not None
        and node.get("semantic_stage") == "discovery"
    )
    discovery = node_payload_view(projection, discovery_id)
    assert discovery is not None
    return GraphDispatchContext(
        run_id=initial.run_id,
        node_id=discovery_id,
        node_kind="worker",
        node_payload=discovery,
        requirements=requirements_for_node_view(projection, discovery_id),
        worktree_path="/tmp/decision-worktree",
        lease_id="lease-discovery",
        lease_generation=1,
        execution_id="execution-discovery",
        base_snapshot_id="snapshot-discovery",
        dispatch_event_id="dispatch-discovery",
        graph_projection=projection,
        graph_events=[*initial.graph_events, *durable_patch_events],
    )


def _valid_implementation_plan() -> dict[str, Any]:
    return {
        "summary": "Implement and validate the parser in one bounded batch.",
        "batches": [
            {
                "key": "parser",
                "objective": "Implement the bounded parser feature.",
                "scope": ["src/parser.py", "tests/unit/test_parser.py"],
                "requirements": ["r1"],
                "acceptance": ["The parser behavior satisfies the supplied specification."],
                "checks": [
                    {
                        "name": "parser unit tests",
                        "command_definition": {
                            "argv": ["uv", "run", "pytest", "tests/unit/test_parser.py"]
                        },
                    }
                ],
            }
        ],
    }


def _make_plan_cyclic(plan: dict[str, Any]) -> None:
    first = cast(dict[str, Any], plan["batches"][0])
    first["depends_on"] = ["tests"]
    plan["batches"].append(
        {
            **first,
            "key": "tests",
            "objective": "Add the bounded parser regression tests.",
            "depends_on": ["parser"],
        }
    )


def test_initial_planner_binds_the_controller_owned_requirement() -> None:
    context = _initial_context()

    assert context.requirements == [
        "dynamic_feature_acceptance: Feature specification at docs/spec.md must be "
        "satisfied. Acceptance command: uv run pytest tests/unit/test_parser.py"
    ]
    assert set(context.graph_projection.topology.input_bindings[context.node_id]) == {
        "routine_snapshot",
        "requirement_1",
    }


def test_initial_planner_uses_canonical_discovery_brief_packet_even_when_inputs_are_full() -> None:
    context = _initial_context()
    contract = _submission_contract(context)

    assert contract is not None
    assert contract.interaction_contract == "decision-v1"
    assert len(contract.outputs) == 1
    assert contract.outputs[0].port == "decision"
    assert contract.outputs[0].content_json_schema == DiscoveryBrief.model_json_schema(
        mode="validation"
    )

    prompt = _prompt_for_node(context)
    assert "What unresolved discovery questions and constraints" in prompt
    assert '"questions"' in prompt
    assert '"rationale"' in prompt
    assert '"focus"' in prompt
    assert "dynamic_feature_acceptance" in prompt
    assert "docs/spec.md" in prompt
    assert "construct_reliable_plan_region" not in prompt
    assert "submit_graph_patch" not in prompt


def test_discovery_uses_canonical_implementation_plan_with_frozen_authority() -> None:
    context = _discovery_context()
    applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
    resolved = resolve_implementation_plan_context(context.graph_projection, context.node_id)
    contract = _submission_contract(context)

    assert applicability is not None
    assert applicability.family == "implementation_plan"
    assert contract is not None
    assert contract.interaction_contract == "decision-v1"
    assert len(contract.outputs) == 1
    assert contract.outputs[0].port == "semantic_artifact"
    assert contract.outputs[0].semantic_schema_id == DECISION_PLAN_SCHEMA_ID
    assert contract.outputs[0].content_json_schema == ImplementationPlan.model_json_schema(
        mode="validation"
    )
    assert dict(resolved.requirement_aliases.object_items()) == {"r1": "dynamic_feature_acceptance"}
    assert [item.port for item in resolved.bound_inputs] == [
        "routine_snapshot",
        "requirement_1",
    ]
    assert resolved.hidden_oracle_available is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda plan: plan["batches"][0].update(requirements=["r2"]),
            "unknown requirement aliases",
        ),
        (
            lambda plan: plan["batches"][0].update(depends_on=["missing"]),
            "unknown dependencies",
        ),
        (_make_plan_cyclic, "dependency cycle"),
        (
            lambda plan: plan["batches"][0]["checks"][0].update(
                command_definition=None,
                command_binding="dynamic_feature_hidden_oracle",
            ),
            "unavailable check binding",
        ),
    ],
)
def test_discovery_plan_rejects_unbound_alias_dependency_and_check_choices(
    mutate: Any,
    message: str,
) -> None:
    context = _discovery_context()
    plan = _valid_implementation_plan()
    mutate(plan)

    with pytest.raises((ValidationError, ValueError), match=message):
        resolve_implementation_plan_context(
            context.graph_projection,
            context.node_id,
        ).validate_answer(plan)


def test_discovery_brief_compiles_exact_bound_inputs_into_complete_initial_topology() -> None:
    context = _initial_context()
    resolved = resolve_discovery_brief_context(context.graph_projection, context.node_id)
    answer = {
        "questions": ["Which existing parser seam should own the feature?"],
        "rationale": "Repository ownership still requires judgment.",
        "focus": ["docs/spec.md"],
    }

    first = compile_discovery_brief(
        context.graph_projection,
        node_id=context.node_id,
        decision_request_id="initial-request",
        base_graph_position=context.graph_position,
        answer=answer,
    )
    second = compile_discovery_brief(
        build_projection(context.graph_events),
        node_id=context.node_id,
        decision_request_id="initial-request",
        base_graph_position=context.graph_position,
        answer=answer,
    )

    assert first == second
    assert resolved.scope_choices == ("docs/spec.md",)
    assert dict(resolved.requirement_aliases.object_items()) == {"r1": "dynamic_feature_acceptance"}
    assert [item.port for item in resolved.bound_inputs] == [
        "routine_snapshot",
        "requirement_1",
    ]
    created = [op["node"] for op in first.ops if op["op"] == "create_node"]
    assert [node.get("semantic_stage") for node in created] == [
        "discovery",
        "plan_verification",
        "gap_planning",
    ]
    assert isinstance(created[0]["decision_successor_node_id"], str)
    assert created[0]["access_mode"] == "read_only"
    assert created[0]["scope"] == "docs/spec.md"
    assert created[0]["semantic_schema_id"] == DECISION_PLAN_SCHEMA_ID
    assert "Which existing parser seam" in created[0]["acceptance"][0]
    assert all(
        op["accepted_record_selector"]["record_id"] == "requirement-dynamic-feature-acceptance"
        for op in first.ops
        if op.get("op") == "create_edge" and str(op.get("to_port", "")).startswith("requirement_")
    )
    assert first.decision_record.value.family == "discovery_brief"
    assert first.decision_record.value.bound_input_record_ids == [
        "routine-snapshot-record",
        "requirement-dynamic-feature-acceptance",
    ]
    assert "node_id" not in first.decision_record.value.answer
    assert "requirement_ids" not in first.decision_record.value.answer
    assert "dynamic_feature_acceptance" in first.read_set
    assert "initial" in first.read_set


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (
            {
                "rationale": "A question was omitted.",
                "focus": ["docs/spec.md"],
            },
            "questions",
        ),
        (
            {
                "questions": ["Same?", "Same?"],
                "rationale": "Duplicate questions are ambiguous.",
            },
            "duplicates",
        ),
        (
            {
                "questions": ["Which seam?"],
                "rationale": "The focus must remain bounded.",
                "focus": ["../outside"],
            },
            "outside supplied scope",
        ),
        (
            {
                "questions": ["Which seam?"],
                "rationale": "Internal identity is controller-owned.",
                "node_id": "planner-picked",
            },
            "extra_forbidden",
        ),
    ],
)
def test_discovery_brief_rejects_missing_duplicate_unknown_and_internal_choices(
    answer: dict[str, Any], message: str
) -> None:
    context = _initial_context()

    with pytest.raises((ValidationError, ValueError), match=message):
        compile_discovery_brief(
            context.graph_projection,
            node_id=context.node_id,
            decision_request_id="invalid-initial-request",
            base_graph_position=context.graph_position,
            answer=answer,
        )
    (apply_command,)
