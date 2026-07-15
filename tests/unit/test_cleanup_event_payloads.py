import pytest
from pydantic import ValidationError

from orchestrator.graph import CleanupAppliedPayload, CleanupRequestedPayload


def test_cleanup_payload_serializes_canonical_shape() -> None:
    raw = {
        "cleanup_id": "cleanup-1",
        "snapshot_id": "snapshot-1",
        "paths": ["tmp/output.txt"],
        "authority": "controller",
    }
    assert (
        CleanupRequestedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"cleanup_id": "cleanup-1", "future_field": True},
        {"cleanup_id": "cleanup-1", "paths": [3]},
    ],
)
def test_cleanup_payload_rejects_unknown_and_wrong_typed_fields(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CleanupRequestedPayload.model_validate(raw)


def test_cleanup_applied_boolean_is_strict() -> None:
    with pytest.raises(ValidationError):
        CleanupAppliedPayload.model_validate({"cleanup_id": "cleanup-1", "deleted_snapshot_ref": 1})
