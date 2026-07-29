"""Strict decision and record command payload coverage."""

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    EvaluateJoinCommand,
    GatekeeperVerdictCommandRow,
    RaiseAppealCommand,
    RecordDecisionCommand,
    RecordRequirementRevisionCommand,
    RecordSupportEvidenceCommand,
)


@pytest.mark.parametrize(
    ("decision_type", "decision"),
    [
        ("approval", "defer"),
        ("authority", "grant"),
        ("authority", "deny"),
        ("oversight", "approved"),
    ],
)
def test_decision_rejects_noncanonical_values(decision_type: str, decision: str) -> None:
    with pytest.raises(ValidationError):
        RecordDecisionCommand.model_validate(
            {
                "decision_type": decision_type,
                "node_id": "gate-1",
                "decision": decision,
                "decider": "operator",
            }
        )


@pytest.mark.parametrize("alias", ["approved", "outcome", "verdict", "decider_actor"])
def test_decision_rejects_alias_fields(alias: str) -> None:
    with pytest.raises(ValidationError):
        RecordDecisionCommand.model_validate(
            {
                "decision_type": "approval",
                "node_id": "gate-1",
                "decision": "approved",
                "decider": "operator",
                alias: True,
            }
        )


def test_raise_appeal_requires_node_id() -> None:
    with pytest.raises(ValidationError):
        RaiseAppealCommand.model_validate({"appeal_type": "invalid_test"})


@pytest.mark.parametrize("value", [True, "1"])
def test_gatekeeper_row_rejects_coerced_token_counts(value: object) -> None:
    with pytest.raises(ValidationError):
        GatekeeperVerdictCommandRow.model_validate(
            {"path": "secret.txt", "classification": "secret", "gen_ai_usage_input_tokens": value}
        )


def test_requirement_revision_rejects_version_alias() -> None:
    with pytest.raises(ValidationError):
        RecordRequirementRevisionCommand.model_validate(
            {"requirement_id": "R-1", "requirement_version_id": "R-1.v1"}
        )


def test_support_evidence_rejects_version_alias() -> None:
    with pytest.raises(ValidationError):
        RecordSupportEvidenceCommand.model_validate(
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "version_id": "R-1.v1",
            }
        )


def test_lease_scoped_evaluation_requires_complete_lease_pair() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        EvaluateJoinCommand.model_validate({"node_id": "join-1", "lease_id": "lease-1"})
