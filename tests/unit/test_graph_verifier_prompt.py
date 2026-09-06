from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjection,
    initial_projection,
    reduce_event,
)
from orchestrator.graph_runtime import GraphDispatchContext, render_graph_node_prompt
from tests.unit.graph_test_utils import canonical_event_payload


_INCIDENT_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures/graph/ca8faa94_plan_verifier.json"


def _incident_fixture() -> dict[str, Any]:
    return json.loads(_INCIDENT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{position}",
        run_id="run-plan-verifier-incident",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SCHEDULER),
        causation_id="incident-regression",
        correlation_id=None,
        timestamp=datetime(2026, 9, 6, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def _projection(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _incident_context(*, rubric: list[Any] | None = None) -> GraphDispatchContext:
    fixture = _incident_fixture()
    artifact = fixture["artifact"]
    requirement = fixture["requirement"]
    artifact_id = artifact["record_id"]
    requirement_record_id = requirement["record_id"]
    events = [
        _event(
            "output_record_accepted",
            artifact,
            1,
        ),
        _event(
            "output_record_accepted",
            requirement,
            2,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-plan-description-first",
                "to_port": "semantic_artifact",
                "record_ids": [artifact_id],
            },
            3,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-plan-description-first",
                "to_port": "requirement_1",
                "record_ids": [requirement_record_id],
            },
            4,
        ),
    ]
    node_payload = dict(fixture["node"])
    if rubric is not None:
        node_payload["rubric"] = rubric
    return GraphDispatchContext(
        run_id="run-plan-verifier-incident",
        node_id="verifier-plan-description-first",
        node_kind="verifier",
        node_role="verifier",
        node_payload=node_payload,
        requirements=[f"{requirement['value']['id']}: {requirement['value']['text']}"],
        worktree_path="/tmp/worktree",
        lease_id="lease-plan-verifier",
        lease_generation=1,
        execution_id="exec-plan-verifier",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-plan-verifier",
        graph_projection=_projection(events),
        graph_events=events,
    )


def _packet(prompt: str) -> dict[str, Any]:
    marker = "Verifier context packet:\n"
    return json.loads(prompt.split(marker, maxsplit=1)[1])


def test_plan_verifier_without_authored_rubric_gets_complete_stage_contract() -> None:
    fixture = _incident_fixture()
    prompt = render_graph_node_prompt(_incident_context())
    packet = _packet(prompt)

    assert packet["node_id"] == "verifier-plan-description-first"
    assert packet["task_region_id"] == "description-first-work-plan-region"
    assert packet["semantic_stage"] == "plan_verification"
    assert packet["semantic_schema_id"] == "reliable-plan-implementation-plan"
    assert packet["semantic_schema_version"] == 1
    assert packet["objective"] == (
        "Independently verify the discovery artifact against the feature specification and "
        "the reliable-plan contract before any effectful implementation work is scheduled."
    )
    assert packet["acceptance_obligations"] == [
        "The discovery artifact covers the typed work-plan contract, requirement provenance, "
        "trusted runtime context, deterministic compilation, atomic validation, and required "
        "safeguards.",
        "The discovery artifact is suitable input for successor planning.",
    ]
    assert [item.split(":", maxsplit=1)[0] for item in packet["rubric"]] == [
        "Coverage",
        "Feasibility",
        "Obligations",
        "Evidence",
        "Downstream implementation plan",
    ]
    assert packet["candidate_id"] == (
        "semantic-artifact-exec-34522d387f504b62a3c18e8c8fa33ac8-semantic_artifact"
    )
    assert packet["candidate_evidence"] == {
        "bound_candidate_or_artifact_record_ids": [
            "semantic-artifact-exec-34522d387f504b62a3c18e8c8fa33ac8-semantic_artifact"
        ]
    }
    assert packet["requirement_evidence"] == {
        "bound_requirement_ids": ["dynamic_feature_acceptance"],
        "resolved_requirements": [
            f"dynamic_feature_acceptance: {fixture['requirement']['value']['text']}"
        ],
        "bound_requirement_record_ids": ["requirement-dynamic-feature-acceptance"],
    }
    declared_requirement_id = packet["requirement_evidence"]["bound_requirement_ids"][0]
    bound_requirement_record_id = packet["requirement_evidence"]["bound_requirement_record_ids"][0]
    assert declared_requirement_id != bound_requirement_record_id
    assert (
        packet["bound_records"]["requirement_1"][0]["record_payload"]["value"]["id"]
        == declared_requirement_id
    )
    assert (
        packet["bound_records"]["requirement_1"][0]["record_payload"]["value"]["text"]
        == fixture["requirement"]["value"]["text"]
    )
    assert (
        packet["bound_records"]["semantic_artifact"][0]["record_payload"]["value"]["content"]
        == fixture["artifact"]["value"]["content"]
    )
    assert packet["evaluated_record_citations"]["candidate_record_ids"] == [
        "semantic-artifact-exec-34522d387f504b62a3c18e8c8fa33ac8-semantic_artifact"
    ]
    assert packet["evaluated_record_citations"]["evaluated_record_ids"] == [
        "requirement-dynamic-feature-acceptance",
        "semantic-artifact-exec-34522d387f504b62a3c18e8c8fa33ac8-semantic_artifact",
    ]
    assert packet["bound_records"]["semantic_artifact"][0]["record_id"] == (
        "semantic-artifact-exec-34522d387f504b62a3c18e8c8fa33ac8-semantic_artifact"
    )
    assert packet["bound_records"]["requirement_1"][0]["record_id"] == (
        "requirement-dynamic-feature-acceptance"
    )
    assert "Perform an independent review" in prompt
    assert "Do not require completed implementation or completed downstream tests." in prompt


def test_plan_verifier_preserves_an_authored_rubric_exactly() -> None:
    authored = [{"id": "plan-coverage", "text": "Every accepted obligation maps to a plan step."}]

    packet = _packet(render_graph_node_prompt(_incident_context(rubric=authored)))

    assert packet["rubric"] == authored


@pytest.mark.parametrize(
    ("missing_field", "invalid_value"),
    [
        ("objective", ""),
        ("acceptance", []),
    ],
)
def test_plan_verifier_rejects_incomplete_stage_contract_before_prompt_dispatch(
    missing_field: str,
    invalid_value: str | list[str],
) -> None:
    context = _incident_context()
    context.node_payload[missing_field] = invalid_value

    with pytest.raises(
        ValueError,
        match=rf"missing or empty fields: {missing_field}",
    ):
        render_graph_node_prompt(context)
