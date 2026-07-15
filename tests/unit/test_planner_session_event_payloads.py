import pytest
from pydantic import ValidationError

from orchestrator.graph import PlannerSessionStateChangedPayload, build_projection
from tests.unit.graph_test_utils import event


def test_planner_session_payload_serializes_canonical_shape() -> None:
    raw = {
        "session_id": "session-1",
        "state": "attached",
        "node_id": "planner-1",
        "lease_generation": 2,
        "carryover_record_id": "record-1",
    }
    assert (
        PlannerSessionStateChangedPayload.model_validate(raw).model_dump(
            mode="json", exclude_unset=True
        )
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"session_id": "session-1", "state": "attached", "future_field": True},
        {"session_id": "session-1", "state": "attached", "lease_generation": "2"},
    ],
)
def test_planner_session_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PlannerSessionStateChangedPayload.model_validate(raw)


def test_planner_session_reducer_preserves_explicit_null_carryover() -> None:
    projection = build_projection(
        [
            event(
                "session_state_changed",
                {"session_id": "session-1", "state": "attached", "carryover_record_id": None},
            )
        ]
    )
    assert projection["planner_session_carryovers"]["session-1"] is None
