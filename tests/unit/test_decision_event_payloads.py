from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    OversightDecisionRecordedPayload,
)
from orchestrator.graph.commands.callbacks import RaiseAppealCommand, RecordDecisionCommand


@pytest.mark.parametrize(
    ("model", "valid"),
    [
        (
            AppealOpenedPayload,
            {"node_id": "a-1", "appealed_node_id": "n-1", "appeal_type": "invalid_test"},
        ),
        (
            ApprovalDecisionRecordedPayload,
            {"node_id": "g-1", "decision": "approved", "decider": "operator-1"},
        ),
        (
            AuthorityDecisionRecordedPayload,
            {"node_id": "r-1", "decision": "granted", "decider": "operator-1"},
        ),
        (
            OversightDecisionRecordedPayload,
            {
                "node_id": "a-1",
                "appealed_node_id": "n-1",
                "decision": "accepted",
                "decider": "operator-1",
            },
        ),
    ],
)
def test_decision_event_payloads_are_exact_strict_models(
    model: type, valid: dict[str, object]
) -> None:
    assert model.model_validate(valid).model_dump(mode="json", exclude_none=True) == valid
    for invalid in (
        {**valid, "unknown": 1},
        {key: value for key, value in valid.items() if key != next(iter(valid))},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(invalid)
    first = next(iter(valid))
    with pytest.raises(ValidationError):
        model.model_validate({**valid, first: 7})


@pytest.mark.parametrize(
    ("model", "legacy"),
    [
        (AppealOpenedPayload, {"node_id": "a", "membership": {"task_region_id": "t"}}),
        (ApprovalDecisionRecordedPayload, {"node_id": "g", "outcome": "accept"}),
        (AuthorityDecisionRecordedPayload, {"node_id": "r", "approved": True}),
        (OversightDecisionRecordedPayload, {"task_region_id": "t", "verdict": "failed"}),
    ],
)
def test_decision_event_payloads_reject_legacy_aliases(
    model: type, legacy: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(legacy)


@pytest.mark.parametrize(
    ("model", "valid", "required"),
    [
        (RaiseAppealCommand, {"node_id": "n-1", "appeal_type": "invalid_test"}, "node_id"),
        (
            RecordDecisionCommand,
            {
                "decision_type": "approval",
                "node_id": "g-1",
                "decision": "approved",
                "decider": "operator-1",
            },
            "node_id",
        ),
    ],
)
def test_decision_command_models_reject_missing_extra_and_mistyped_fields(
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


@pytest.mark.parametrize("decision", ["grant", "deny", "defer"])
def test_record_decision_command_rejects_decision_aliases(decision: str) -> None:
    with pytest.raises(ValidationError):
        RecordDecisionCommand.model_validate(
            {
                "decision_type": "authority",
                "node_id": "a-1",
                "decision": decision,
                "decider": "operator-1",
            }
        )


def test_task7_decision_commands_exhaustively_validate_declared_fields() -> None:
    cases = (
        (
            RaiseAppealCommand,
            {
                "node_id": "n",
                "appeal_type": "invalid_test",
                "appeal_node_id": "a",
                "oversight_node_id": "o",
                "candidate_id": "c",
                "task_region_id": "t",
                "lease_id": "l",
            },
            ("node_id", "appeal_type"),
            {
                "node_id": 1,
                "appeal_type": "other",
                "appeal_node_id": 1,
                "oversight_node_id": 1,
                "candidate_id": 1,
                "task_region_id": 1,
                "lease_id": 1,
            },
        ),
        (
            RecordDecisionCommand,
            {
                "decision_type": "approval",
                "node_id": "g",
                "decision": "approved",
                "decider": "human",
                "scope": {"region": "t"},
                "expires_at": "later",
                "reason": "safe",
                "record_id": "d",
            },
            ("decision_type", "node_id", "decision", "decider"),
            {
                "decision_type": "unknown",
                "node_id": 1,
                "decision": 1,
                "decider": object(),
                "scope": [],
                "expires_at": 1,
                "reason": 1,
                "record_id": 1,
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


@pytest.mark.parametrize(
    ("valid", "mistyped"),
    [
        (
            {
                "decision_type": "authority",
                "node_id": "a",
                "decision": "granted",
                "decider": "human",
                "scope": {"region": "t"},
                "expires_at": "later",
                "reason": "safe",
                "record_id": "d",
            },
            {
                "decision_type": "approval",
                "node_id": 1,
                "decision": "grant",
                "decider": object(),
                "scope": [],
                "expires_at": 1,
                "reason": 1,
                "record_id": 1,
            },
        ),
        (
            {
                "decision_type": "oversight",
                "node_id": "o",
                "decision": "accepted",
                "decider": "human",
                "scope": {"region": "t"},
                "expires_at": "later",
                "reason": "safe",
                "record_id": "d",
            },
            {
                "decision_type": "authority",
                "node_id": 1,
                "decision": "approved",
                "decider": object(),
                "scope": [],
                "expires_at": 1,
                "reason": 1,
                "record_id": 1,
            },
        ),
    ],
)
def test_record_decision_authority_and_oversight_variants_are_exact_strict_contracts(
    valid: dict[str, object], mistyped: dict[str, object]
) -> None:
    RecordDecisionCommand.model_validate(valid)
    for required in ("decision_type", "node_id", "decision", "decider"):
        with pytest.raises(ValidationError):
            RecordDecisionCommand.model_validate(
                {key: value for key, value in valid.items() if key != required}
            )
    with pytest.raises(ValidationError):
        RecordDecisionCommand.model_validate({**valid, "unknown": 1})
    for field, value in mistyped.items():
        with pytest.raises(ValidationError):
            RecordDecisionCommand.model_validate({**valid, field: value})
