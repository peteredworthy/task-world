from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.graph import RequirementRevisionPayload, SupportEvidencePayload
from orchestrator.graph.commands.callbacks import (
    RecordRequirementRevisionCommand,
    RecordSupportEvidenceCommand,
)


@pytest.mark.parametrize(
    ("model", "valid"),
    [
        (
            RequirementRevisionPayload,
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v1",
                "classification": "initial",
                "active": True,
            },
        ),
        (
            SupportEvidencePayload,
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
                "status": "active",
            },
        ),
    ],
)
def test_requirement_event_payloads_are_exact_strict_models(
    model: type, valid: dict[str, object]
) -> None:
    assert model.model_validate(valid).model_dump(mode="json", exclude_none=True) == valid
    with pytest.raises(ValidationError):
        model.model_validate({**valid, "unknown": 1})
    with pytest.raises(ValidationError):
        model.model_validate(
            {key: value for index, (key, value) in enumerate(valid.items()) if index}
        )
    first = next(iter(valid))
    with pytest.raises(ValidationError):
        model.model_validate({**valid, first: 7})


@pytest.mark.parametrize(
    ("model", "legacy"),
    [
        (RequirementRevisionPayload, {"id": "R-1", "requirement_version_id": "v1"}),
        (SupportEvidencePayload, {"edge_id": "S-1", "evidence_id": "E-1", "version_id": "v1"}),
    ],
)
def test_requirement_event_payloads_reject_legacy_aliases(
    model: type, legacy: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(legacy)


@pytest.mark.parametrize(
    ("model", "valid", "required"),
    [
        (
            RecordRequirementRevisionCommand,
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
            "requirement_id",
        ),
        (
            RecordSupportEvidenceCommand,
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "status": "active",
            },
            "support_id",
        ),
    ],
)
def test_requirement_command_models_reject_missing_extra_and_mistyped_fields(
    model: type, valid: dict[str, object], required: str
) -> None:
    model.model_validate(valid)
    for invalid in (
        {key: value for key, value in valid.items() if key != required},
        {**valid, "unknown": 1},
        {**valid, required: 7},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(invalid)


def test_record_support_evidence_command_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        RecordSupportEvidenceCommand.model_validate(
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "status": "unknown",
            }
        )


def test_task7_requirement_commands_exhaustively_validate_declared_fields() -> None:
    cases = (
        (
            RecordRequirementRevisionCommand,
            {
                "requirement_id": "R",
                "version_id": "v1",
                "record_id": "RR",
                "classification": "semantic",
                "change_classification": "semantic",
                "requires_authority": True,
                "new_behavior": False,
                "behavior_change": True,
                "semantic_change": True,
                "validation_strengthening": False,
                "active": True,
                "previous_version_id": "v0",
            },
            ("requirement_id", "version_id"),
            {
                "requirement_id": 1,
                "version_id": 1,
                "record_id": 1,
                "classification": 1,
                "change_classification": 1,
                "requires_authority": "yes",
                "new_behavior": 1,
                "behavior_change": 1,
                "semantic_change": 1,
                "validation_strengthening": 1,
                "active": 1,
                "previous_version_id": 1,
            },
        ),
        (
            RecordSupportEvidenceCommand,
            {
                "support_id": "S",
                "evidence_id": "E",
                "requirement_id": "R",
                "requirement_version_id": "v1",
                "status": "active",
                "stale_reason": "old",
                "confidence": "high",
            },
            ("support_id", "evidence_id", "requirement_id"),
            {
                "support_id": 1,
                "evidence_id": 1,
                "requirement_id": 1,
                "requirement_version_id": 1,
                "status": "unknown",
                "stale_reason": 1,
                "confidence": 1,
            },
        ),
    )
    for model, valid, required, mistyped in cases:
        model.model_validate(valid)
        invalids = [
            {key: value for key, value in valid.items() if key != field} for field in required
        ]
        invalids.append({**valid, "unknown": 1})
        invalids.extend({**valid, field: value} for field, value in mistyped.items())
        for invalid in invalids:
            with pytest.raises(ValidationError):
                model.model_validate(invalid)
