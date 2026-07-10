from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    EventEnvelope,
    FakeClock,
    OversightDecisionRecordedPayload,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    reduce_event,
)


def test_appeal_opened_payload_normalizes_membership_and_patch_extras() -> None:
    payload = AppealOpenedPayload.model_validate(
        {
            "node_id": "appeal-1",
            "membership": {"task_region_id": "task-1", "candidate_id": "candidate-1"},
            "legacy": 1,
        }
    )

    assert payload.task_region_id == "task-1"
    assert payload.candidate_id == "candidate-1"
    assert payload.extra == {"legacy": 1}


def test_decision_payloads_normalize_legacy_outcome_verdict_and_approved() -> None:
    approval = ApprovalDecisionRecordedPayload.model_validate(
        {"node_id": "gate-1", "outcome": "accept"}
    )
    authority = AuthorityDecisionRecordedPayload.model_validate(
        {"node_id": "authority-1", "approved": True}
    )
    oversight = OversightDecisionRecordedPayload.model_validate(
        {"node_id": "appeal-1", "verdict": "failed"}
    )

    assert approval.decision == "approved"
    assert authority.decision == "granted"
    assert oversight.verdict == "failed"
    assert oversight.decision is None


def test_decision_payloads_preserve_opaque_decider_scope_and_unknown_extra() -> None:
    decider = ["human", {"id": "operator-1"}]
    scope = {"regions": ["task-1"], "policy": {"name": "review"}}

    payload = OversightDecisionRecordedPayload.model_validate(
        {
            "task_region_id": "task-1",
            "verdict": "failed",
            "decider": decider,
            "scope": scope,
            "legacy": 1,
        }
    )

    assert payload.node_id is None
    assert payload.verdict == "failed"
    assert payload.decider == decider
    assert payload.scope == scope
    assert payload.extra == {"legacy": 1}


def test_decision_reducers_preserve_legacy_appeal_and_invalid_test_behavior() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "appeal_opened",
            {
                "node_id": "appealed-node",
                "membership": {"task_region_id": "task-1", "candidate_id": "candidate-1"},
                "appeal_type": "invalid_test",
            },
            position=1,
        ),
    )
    projection = reduce_event(
        projection,
        _event(
            "oversight_decision_recorded",
            {
                "node_id": "oversight-1",
                "appealed_node_id": "appealed-node",
                "membership": {"task_region_id": "task-1", "candidate_id": "candidate-1"},
                "appeal_type": "invalid_test",
                "approved": True,
            },
            position=2,
        ),
    )

    assert projection["node_pending_appeals"] == {"appealed-node": False}
    assert projection["invalid_test_blocks"]["task-1"].accepted is True


def test_oversight_reducer_uses_recognized_legacy_alias_after_obsolete_decision() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "oversight_decision_recorded",
            {
                "decision": "obsolete",
                "outcome": "approved",
                "task_region_id": "t",
                "appeal_type": "invalid_test",
            },
            position=1,
        ),
    )

    assert projection["invalid_test_blocks"]["t"].accepted is True


def test_decision_producers_emit_typed_payloads() -> None:
    appeal_events = apply_command(
        initial_projection(),
        [],
        "raise_appeal",
        {"run_id": "run-1", "node_id": "failed-1", "appeal_type": "invalid_test"},
        FakeClock(),
        SequentialIdGenerator(),
    )
    appeal = AppealOpenedPayload.model_validate(appeal_events[0].payload)
    assert appeal.appealed_node_id == "failed-1"

    events = [
        _event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "ready"}, position=1)
    ]
    output = apply_command(
        _project(events),
        events,
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "approved",
            "decider": "operator-1",
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    payload = ApprovalDecisionRecordedPayload.model_validate(output[0].payload)
    assert payload.decision == "approved"
    assert payload.extra == {}


def test_sparse_oversight_decision_without_node_id_remains_replayable() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "oversight_decision_recorded",
            {"task_region_id": "task-1", "verdict": "failed", "legacy": 1},
            position=1,
        ),
    )

    assert projection["oversight_decisions"] == {}


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
