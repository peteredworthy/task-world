import pytest
from pydantic import ValidationError

from orchestrator.graph import ApprovalDecisionRecordedPayload, OversightDecisionRecordedPayload


def test_decision_payload_serializes_canonical_membership_fields() -> None:
    raw = {
        "decision_type": "oversight",
        "node_id": "gate-1",
        "decision": "accepted",
        "task_region_id": "task-1",
        "candidate_id": "candidate-1",
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
