import pytest
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    FakeClock,
    OversightDecisionRecordedPayload,
    SequentialIdGenerator,
    build_projection,
)
from tests.unit.graph_test_utils import apply_command, command_context
from tests.unit.graph_test_utils import event


def test_decision_payload_serializes_canonical_membership_fields() -> None:
    raw = {
        "decision_type": "oversight",
        "node_id": "gate-1",
        "decision": "accepted",
        "task_region_id": "task-1",
        "candidate_id": "candidate-1",
        "decider": "controller",
    }
    assert (
        OversightDecisionRecordedPayload.model_validate(raw).model_dump(
            mode="json", exclude_unset=True
        )
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"decision": "approved", "future_field": True},
        {"decision": "approved", "approved": "yes"},
    ],
)
def test_decision_payload_rejects_unknown_and_wrong_typed_fields(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ApprovalDecisionRecordedPayload.model_validate(raw)


@pytest.mark.parametrize(
    ("model", "raw"),
    [
        (ApprovalDecisionRecordedPayload, {"outcome": "approved"}),
        (ApprovalDecisionRecordedPayload, {"approved": True}),
        (AuthorityDecisionRecordedPayload, {"approved": True}),
        (OversightDecisionRecordedPayload, {"verdict": "accepted"}),
    ],
)
def test_decision_payload_rejects_replay_aliases(
    model: type[BaseModel], raw: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(raw)


@pytest.mark.parametrize(
    ("model", "decision"),
    [
        (ApprovalDecisionRecordedPayload, "accept"),
        (AuthorityDecisionRecordedPayload, "grant"),
        (OversightDecisionRecordedPayload, "approved"),
    ],
)
def test_decision_payload_rejects_noncanonical_decision_literals(
    model: type[BaseModel], decision: str
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"decision": decision})


def test_decision_command_producer_matches_canonical_payload_json() -> None:
    events = [
        event(
            "node_created",
            {"node_id": "gate-1", "kind": "gate", "state": "ready"},
            position=1,
        )
    ]
    emitted = apply_command(
        build_projection(events),
        events,
        "record_decision",
        {
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "approved",
            "decider": "operator-1",
        },
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )
    payload = next(
        item.payload for item in emitted if item.event_type == "approval_decision_recorded"
    )

    assert payload == ApprovalDecisionRecordedPayload.model_validate(payload).model_dump(
        mode="json"
    )
