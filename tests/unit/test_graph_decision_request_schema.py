"""Pure validation matrix for the graph decision HTTP request contract."""

import pytest
from pydantic import ValidationError

from orchestrator.api.routers.graph import RecordGraphDecisionRequest


_VALID = {
    "decision_type": "approval",
    "node_id": "gate-1",
    "decision": "approved",
    "decider": {"kind": "human", "id": "alice"},
}


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", ""),
        ("node_id", "n" * 201),
        ("decision", ""),
        ("decision", "a" * 65),
        ("record_id", ""),
        ("record_id", "r" * 201),
        ("rationale_record_id", ""),
        ("rationale_record_id", "r" * 201),
        ("decider", {"kind": ""}),
    ],
)
def test_record_decision_request_rejects_invalid_field_constraints(
    field: str, value: object
) -> None:
    payload = {**_VALID, field: value}
    with pytest.raises(ValidationError):
        RecordGraphDecisionRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("decision_type", "decision"),
    [("approval", "defer"), ("authority", "grant"), ("authority", "deny")],
)
def test_record_decision_request_rejects_removed_decision_aliases(
    decision_type: str, decision: str
) -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        RecordGraphDecisionRequest.model_validate(
            {
                **_VALID,
                "decision_type": decision_type,
                "node_id": "authority-1" if decision_type == "authority" else "gate-1",
                "decision": decision,
            }
        )
