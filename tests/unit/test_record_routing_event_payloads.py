from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    failed_verification_candidate_ids_view,
    passed_verification_candidate_ids_view,
    verifier_verdicts_view,
    EVENT_PAYLOAD_MODELS,
    Actor,
    ActorKind,
    EventEnvelope,
    InputBoundPayload,
    RevisionCreatedPayload,
    VerificationOutcomePayload,
    initial_projection,
    reduce_event,
)


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


@pytest.mark.parametrize(
    ("event_type", "outcome"),
    [("verification_passed", "failed"), ("verification_failed", "passed")],
)
def test_verification_event_model_rejects_contradictory_outcome(
    event_type: str,
    outcome: str,
) -> None:
    with pytest.raises(ValidationError):
        EVENT_PAYLOAD_MODELS[event_type].model_validate(
            {
                "node_id": "verifier-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "record_id": "verification-1",
                "outcome": outcome,
                "value": {"outcome": outcome},
            }
        )


@pytest.mark.parametrize(
    ("event_type", "outcome", "value_outcome"),
    [
        ("verification_passed", "passed", "failed"),
        ("verification_failed", "failed", "passed"),
    ],
)
def test_verification_event_model_rejects_contradictory_nested_outcome(
    event_type: str,
    outcome: str,
    value_outcome: str,
) -> None:
    with pytest.raises(ValidationError):
        EVENT_PAYLOAD_MODELS[event_type].model_validate(
            {
                "node_id": "verifier-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "record_id": "verification-1",
                "outcome": outcome,
                "value": {"outcome": value_outcome},
            }
        )


@pytest.mark.parametrize(
    ("event_type", "outcome"),
    [("verification_passed", "failed"), ("verification_failed", "passed")],
)
def test_verification_replay_ignores_contradictory_outcome(
    event_type: str,
    outcome: str,
) -> None:
    event = EventEnvelope(
        event_id="event-1",
        run_id="run-1",
        position=1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "node_id": "verifier-1",
            "verifier_node_id": "verifier-1",
            "candidate_id": "candidate-1",
            "record_id": "verification-1",
            "outcome": outcome,
            "value": {"outcome": outcome},
        },
    )

    projection = reduce_event(initial_projection(), event)

    assert verifier_verdicts_view(projection) == {}
    assert passed_verification_candidate_ids_view(projection) == []
    assert failed_verification_candidate_ids_view(projection) == {}


def test_sparse_input_bound_serialization_preserves_explicit_empty_fields() -> None:
    """Producer sparsity omits defaults but keeps fields supplied intentionally."""
    required = {
        "edge_id": "edge-1",
        "to_node_id": "verifier-1",
        "to_port": "candidate_under_test",
        "record_ids": ["candidate-1"],
        "bound_at_position": 4,
    }
    implicit = InputBoundPayload.model_validate(required)
    explicit = InputBoundPayload.model_validate({**required, "record_bound_positions": {}})

    assert implicit.model_dump(mode="json", exclude_none=True, exclude_unset=True) == required
    assert explicit.model_dump(mode="json", exclude_none=True, exclude_unset=True) == {
        **required,
        "record_bound_positions": {},
    }


def test_revision_created_requires_typed_nodes() -> None:
    with pytest.raises(ValidationError):
        RevisionCreatedPayload.model_validate(
            {"node": {"node_id": "revision-1"}, "worker_node": {}, "verifier_node": {}}
        )
