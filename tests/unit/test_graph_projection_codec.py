"""Focused tests for the disposable projection checkpoint contract."""

from copy import deepcopy
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from orchestrator.graph import (
    GraphProjection,
    ProjectionCheckpointCodecError,
    PROJECTION_CHECKPOINT_SCHEMA_VERSION,
    projection_from_checkpoint,
    projection_to_checkpoint,
)


class SerializationFailure(BaseModel):
    value: object

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise PydanticSerializationError("real serializer failure")


class UnrelatedSerializationFailure(BaseModel):
    value: object

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("unrelated failure")


def final_projection_fixture() -> GraphProjection:
    return GraphProjection.model_validate(
        {
            "nodes": {
                "node-1": {
                    "spec": {"node_id": "node-1", "creation_position": 1},
                    "runtime": {"state": "ready"},
                },
                "node-2": {"spec": {"node_id": "node-2", "creation_position": 2}},
            },
            "tasks": {
                "task-1": {
                    "state": "active",
                    "candidates": [
                        {
                            "candidate_id": "candidate-1",
                            "attempt_number": 1,
                            "position": 1,
                            "file_state_record_ids": ["record-1"],
                        }
                    ],
                }
            },
            "topology": {
                "edges": {
                    "edge-1": {
                        "edge_id": "edge-1",
                        "from_node_id": "node-1",
                        "from_port": "file_state",
                        "to_node_id": "node-2",
                        "to_port": "input",
                    }
                },
                "inbound_edge_ids": {"node-2": ("edge-1",)},
                "outbound_edge_ids": {"node-1": ("edge-1",)},
            },
            "records": {
                "by_id": {
                    "record-1": {
                        "record_id": "record-1",
                        "record_type": "file_state",
                        "producer_node_id": "node-1",
                        "task_region_id": "task-1",
                        "cleanup_id": "cleanup-1",
                        "acceptance_identity": "a" * 64,
                    }
                },
                "ids_by_node_port": {"node-1": {"file_state": ("record-1",)}},
                "summaries_by_id": {
                    "record-1": {
                        "record_id": "record-1",
                        "record_type": "file_state",
                        "record_kind": "file_state",
                        "schema": "FileStateRecord",
                        "producer_node_id": "node-1",
                        "producer_port": "file_state",
                    }
                },
            },
            "scheduling": {"ready_node_ids": ("node-1",)},
            "planning": {
                "session_id_by_node": {"node-1": "session-1"},
                "sessions": {
                    "session-1": {"current_node_id": "node-1", "carryover_record_id": "record-1"}
                },
            },
            "verification": {
                "verdicts_by_node": {
                    "node-1": {"candidate_id": "candidate-1", "verdict": "passed", "position": 1}
                },
                "passed_results_by_record_id": {
                    "record-1": {
                        "record_id": "record-1",
                        "node_id": "node-1",
                        "candidate_id": "candidate-1",
                        "task_region_id": "task-1",
                    }
                },
                "passed_candidate_ids": ["candidate-1"],
                "check_results_by_node": {
                    "node-1": {
                        "node_id": "node-1",
                        "status": "passed",
                        "position": 1,
                        "task_region_id": "task-1",
                        "record_id": "record-1",
                        "candidate_record_ids": ["record-1"],
                        "file_state_record_ids": ["record-1"],
                        "evaluated_record_ids": ["record-1"],
                    }
                },
                "invalid_test_blocks_by_task": {
                    "task-1": {"position": 1, "candidate_id": "candidate-1"}
                },
            },
            "requirements": {
                "revisions_by_id": {
                    "revision-1": {
                        "requirement_id": "requirement-1",
                        "version_id": "revision-1",
                        "change_classification": "initial",
                        "requires_authority": False,
                        "position": 1,
                        "validation_strengthening": False,
                    }
                },
                "active_version_id_by_requirement": {"requirement-1": "revision-1"},
                "support_by_id": {
                    "support-1": {
                        "support_id": "support-1",
                        "evidence_id": "record-1",
                        "requirement_id": "requirement-1",
                        "requirement_version_id": "revision-1",
                        "status": "fresh",
                        "position": 1,
                    }
                },
            },
            "execution": {
                "lease_ids_in_grant_order": ["lease-1"],
                "leases": {
                    "lease-1": {
                        "lease_id": "lease-1",
                        "state": "active",
                        "node_id": "node-1",
                        "task_region_id": "task-1",
                        "session_id": "session-1",
                    }
                },
                "environment_failures_by_task": {
                    "task-1": {
                        "position": 1,
                        "node_id": "node-1",
                        "task_region_id": "task-1",
                        "record_id": "record-1",
                    }
                },
                "callback_events_by_key": {
                    "node-1\u0000callback-1": {
                        "event_type": "callback_accepted",
                        "node_id": "node-1",
                        "idempotency_key": "callback-1",
                        "outcome": "accepted",
                    }
                },
                "cleanup_requests_by_id": {
                    "cleanup-1": {
                        "cleanup_id": "cleanup-1",
                        "position": 1,
                        "file_state_record_id": "record-1",
                        "producer_node_id": "node-1",
                    }
                },
                "applied_cleanup_ids": {"cleanup-1": True},
            },
        }
    )


def test_valid_round_trip_has_only_the_disposable_contract() -> None:
    checkpoint = projection_to_checkpoint(final_projection_fixture(), position=23)

    assert set(checkpoint) == {"schema_version", "position", "state", "checksum"}
    assert checkpoint["schema_version"] == PROJECTION_CHECKPOINT_SCHEMA_VERSION
    assert checkpoint["position"] == 23
    assert projection_from_checkpoint(checkpoint) == final_projection_fixture()


def test_round_trip_preserves_immutable_nested_json() -> None:
    projection = final_projection_fixture()
    checkpoint = projection_to_checkpoint(projection, position=1)
    restored = projection_from_checkpoint(checkpoint)

    assert restored == projection
    assert restored.topology.edges["edge-1"].edge_id == "edge-1"


def test_checksum_covers_envelope_and_state() -> None:
    checkpoint = projection_to_checkpoint(final_projection_fixture(), position=4)
    checkpoint["position"] = 5

    with pytest.raises(ValueError, match="checksum"):
        projection_from_checkpoint(checkpoint)


def test_corrupt_state_is_rejected_without_salvage() -> None:
    checkpoint = projection_to_checkpoint(final_projection_fixture(), position=4)
    corrupted = deepcopy(checkpoint)
    corrupted["state"] = []

    with pytest.raises(ValidationError):
        projection_from_checkpoint(corrupted)


def test_schema_mismatch_is_rejected() -> None:
    checkpoint = projection_to_checkpoint(final_projection_fixture(), position=4)
    checkpoint["schema_version"] = PROJECTION_CHECKPOINT_SCHEMA_VERSION - 1

    with pytest.raises(ValueError, match="unsupported projection checkpoint schema"):
        projection_from_checkpoint(checkpoint)


def test_writer_wraps_only_pydantic_serialization_errors() -> None:
    with pytest.raises(ProjectionCheckpointCodecError, match="serialization failed"):
        projection_to_checkpoint(cast(GraphProjection, SerializationFailure(value=object())))


def test_writer_propagates_unrelated_serialization_errors() -> None:
    with pytest.raises(RuntimeError, match="unrelated failure"):
        projection_to_checkpoint(
            cast(GraphProjection, UnrelatedSerializationFailure(value=object()))
        )
