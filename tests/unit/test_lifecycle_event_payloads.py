import pytest
from pydantic import ValidationError

from orchestrator.graph import CallbackAcceptedPayload, RunLifecycleChangedPayload


def test_lifecycle_payload_serializes_canonical_shape() -> None:
    raw = {
        "command_type": "start",
        "from_state": "queued",
        "to_state": "active",
        "trigger": "start_command_accepted",
    }
    assert (
        RunLifecycleChangedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"to_state": "active", "future_field": True},
        {"to_state": 7},
    ],
)
def test_lifecycle_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunLifecycleChangedPayload.model_validate(raw)


def test_callback_payload_distinguishes_omitted_from_explicit_null() -> None:
    omitted = CallbackAcceptedPayload.model_validate({"node_id": "worker-1"})
    explicit_null = CallbackAcceptedPayload.model_validate({"node_id": "worker-1", "payload": None})
    assert "payload" not in omitted.model_fields_set
    assert "payload" in explicit_null.model_fields_set
    assert explicit_null.model_dump(mode="json")["payload"] is None
