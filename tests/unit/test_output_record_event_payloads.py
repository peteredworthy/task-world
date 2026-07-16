import pytest
from pydantic import ValidationError

from orchestrator.graph import OutputRecordAcceptedPayload


CANONICAL_RECORD = {
    "record_id": "candidate-record-1",
    "record_kind": "output",
    "record_type": "candidate",
    "producer_node_id": "worker-1",
    "port": "candidate",
    "schema": "ImplementationCandidate",
    "candidate_id": "candidate-1",
    "value": {"summary": "Implemented the requested change"},
}


def test_output_record_event_uses_a_typed_record() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(CANONICAL_RECORD)

    assert payload.root.record_id == CANONICAL_RECORD["record_id"]


def test_output_record_event_rejects_unknown_record_fields() -> None:
    with pytest.raises(ValidationError):
        OutputRecordAcceptedPayload.model_validate({**CANONICAL_RECORD, "legacy_value": "old"})
