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


def test_final_audit_citations_preserve_bound_batch_order() -> None:
    def candidate(batch: int) -> dict[str, Any]:
        return {
            "record_id": f"candidate-batch-{batch}",
            "record_kind": "output",
            "record_type": "candidate",
            "producer_node_id": f"worker-batch-{batch}",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": f"candidate-batch-{batch}",
            "value": {"summary": f"candidate {batch}"},
        }

    def file_state(batch: int) -> dict[str, Any]:
        return {
            "record_id": f"file-state-batch-{batch}",
            "record_kind": "file_state",
            "producer_node_id": f"worker-batch-{batch}",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": f"snapshot-{batch}",
            "base_snapshot_id": "routine-snapshot",
            "verdict": "captured",
        }

    def report(batch: int) -> dict[str, Any]:
        candidate_id = f"candidate-batch-{batch}"
        return {
            "record_id": f"verification-batch-{batch}",
            "record_kind": "verification",
            "record_type": "verification_report",
            "producer_node_id": f"verifier-batch-{batch}",
            "port": "verification_report",
            "schema": "VerificationReport",
            "candidate_id": candidate_id,
            "candidate_record_ids": [candidate_id],
            "file_state_record_ids": [f"file-state-batch-{batch}"],
            "task_region_id": f"batch-{batch}",
            "outcome": "passed",
            "value": {"outcome": "passed", "grades": []},
            "evaluated_record_ids": [candidate_id, f"file-state-batch-{batch}"],
        }

    events = [
        _event("output_record_accepted", candidate(2), 1),
        _event("file_state_accepted", file_state(2), 2),
        _event("output_record_accepted", report(2), 3),
        _event("output_record_accepted", candidate(1), 4),
        _event("file_state_accepted", file_state(1), 5),
        _event("output_record_accepted", report(1), 6),
        _event(
            "input_bound",
            {
                "to_node_id": "final-audit",
                "to_port": "verification_report_batch_1",
                "record_ids": ["verification-batch-1"],
            },
            7,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "final-audit",
                "to_port": "verification_report_batch_2",
                "record_ids": ["verification-batch-2"],
            },
            8,
        ),
    ]
    context = GraphDispatchContext(
        run_id="run-final-audit-order",
        node_id="final-audit",
        node_kind="verifier",
        node_role="verifier",
        node_payload={
            "node_id": "final-audit",
            "kind": "verifier",
            "role": "verifier",
            "semantic_stage": "final_audit",
            "task_region_id": "batch-2",
            "objective": "Audit both accepted batches.",
            "acceptance": ["Both batch reports pass."],
            "rubric": ["All accepted batches are covered."],
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-final-audit",
        lease_generation=1,
        execution_id="exec-final-audit",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-final-audit",
        graph_projection=_projection(events),
        graph_events=events,
    )

    packet = _packet(render_graph_node_prompt(context))
    citations = packet["evaluated_record_citations"]

    assert citations["verification_report_record_ids"] == [
        "verification-batch-1",
        "verification-batch-2",
    ]
    assert citations["candidate_record_ids"] == ["candidate-batch-1", "candidate-batch-2"]
    assert citations["file_state_record_ids"] == [
        "file-state-batch-1",
        "file-state-batch-2",
    ]
    assert packet["candidate_id"] == "candidate-batch-1"
    assert packet["candidate_evidence"] == {
        "bound_candidate_or_artifact_record_ids": [
            "candidate-batch-1",
            "candidate-batch-2",
        ]
    }
    cited_records = {record["record_id"]: record for record in packet["cited_evidence_records"]}
    assert cited_records["candidate-batch-1"]["record_payload"]["value"] == {
        "summary": "candidate 1"
    }
    assert cited_records["candidate-batch-2"]["record_payload"]["value"] == {
        "summary": "candidate 2"
    }
    assert cited_records["file-state-batch-1"]["record_payload"]["verdict"] == "captured"
    assert cited_records["file-state-batch-2"]["record_payload"]["verdict"] == "captured"


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
