import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    FakeClock,
    RequirementRevisionPayload,
    SequentialIdGenerator,
    SupportEvidencePayload,
    apply_command,
    build_projection,
    initial_projection,
)


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


def test_requirement_and_support_command_producers_match_typed_payload_json() -> None:
    revision_events = apply_command(
        initial_projection(),
        [],
        "record_requirement_revision",
        {
            "run_id": "run-1",
            "requirement_id": "R-1",
            "version_id": "R-1-v1",
            "classification": "initial",
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    revision = revision_events[0].payload
    assert revision == RequirementRevisionPayload.model_validate(revision).model_dump(mode="json")

    support_events = apply_command(
        build_projection(revision_events),
        revision_events,
        "record_support_evidence",
        {
            "run_id": "run-1",
            "support_id": "support-1",
            "evidence_id": "evidence-1",
            "requirement_id": "R-1",
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    support = support_events[0].payload
    assert support == SupportEvidencePayload.model_validate(support).model_dump(mode="json")
