import pytest
from pydantic import ValidationError

from orchestrator.graph import InputBoundPayload, RevisionCreatedPayload, VerificationOutcomePayload


def test_input_bound_requires_canonical_routing_fields() -> None:
    with pytest.raises(ValidationError):
        InputBoundPayload.model_validate({"input": "candidate", "record_ids": ["r-1"]})


def test_verification_outcome_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        VerificationOutcomePayload.model_validate(
            {
                "node_id": "verifier-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "record_id": "verification-1",
                "outcome": "passed",
                "value": {"outcome": "passed"},
                "legacy_outcome": "passed",
            }
        )


def test_revision_created_requires_typed_nodes() -> None:
    with pytest.raises(ValidationError):
        RevisionCreatedPayload.model_validate(
            {"node": {"node_id": "revision-1"}, "worker_node": {}, "verifier_node": {}}
        )
