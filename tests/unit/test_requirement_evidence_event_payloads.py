import pytest
from pydantic import ValidationError

from orchestrator.graph import RequirementRevisionPayload, SupportEvidencePayload


def test_requirement_payload_serializes_canonical_shape() -> None:
    raw = {
        "requirement_id": "R-1",
        "version_id": "R-1-v2",
        "revision_id": "revision-2",
        "revision_index": 2,
        "requires_authority": True,
    }
    assert (
        RequirementRevisionPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"requirement_id": "R-1", "future_field": True},
        {"requirement_id": "R-1", "revision_index": "2"},
    ],
)
def test_requirement_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RequirementRevisionPayload.model_validate(raw)


def test_support_evidence_uses_canonical_ids() -> None:
    raw = {
        "support_id": "support-1",
        "requirement_id": "R-1",
        "requirement_version_id": "R-1-v2",
        "status": "active",
    }
    assert (
        SupportEvidencePayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )
