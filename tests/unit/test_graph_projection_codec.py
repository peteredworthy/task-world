"""Public checkpoint contracts for the immutable projection scaffold."""

from copy import deepcopy
from collections import UserDict
from math import inf
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    ImmutableGraphProjection,
    FrozenMap,
    immutable_projection_from_checkpoint,
    immutable_projection_to_checkpoint,
)


def final_projection_fixture() -> ImmutableGraphProjection:
    return ImmutableGraphProjection.model_validate(
        {
            "nodes": {
                "node-1": {"spec": {"node_id": "node-1", "creation_position": 1}},
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
                    "callback-1": {
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


def test_checkpoint_round_trip_preserves_ordinary_json_shape() -> None:
    checkpoint = immutable_projection_to_checkpoint(final_projection_fixture())

    assert type(checkpoint) is dict
    assert type(checkpoint["nodes"]) is dict
    assert type(checkpoint["scheduling"]["ready_node_ids"]) is list
    assert immutable_projection_from_checkpoint(checkpoint) == final_projection_fixture()


@pytest.mark.parametrize("bad", ["1", True, inf])
def test_checkpoint_rejects_scalar_coercion(bad: object) -> None:
    raw = immutable_projection_to_checkpoint(final_projection_fixture())
    raw["usage"]["tokens_by_node"] = {"node-1": bad}

    with pytest.raises(ValidationError):
        immutable_projection_from_checkpoint(raw)


def test_checkpoint_rejects_non_dict_root_without_salvaging_it() -> None:
    with pytest.raises(ValidationError):
        immutable_projection_from_checkpoint([])


def test_checkpoint_rejects_unknown_or_malformed_sibling_without_defaulting() -> None:
    raw = immutable_projection_to_checkpoint(final_projection_fixture())
    before = deepcopy(raw)
    raw["usage"] = {"unknown": True}

    with pytest.raises(ValidationError):
        immutable_projection_from_checkpoint(raw)

    assert raw != before


@pytest.mark.parametrize(
    "replacement",
    [
        ("node-1",),
        FrozenMap({"node-1": 1}),
        UserDict({"node-1": 1}),
        MappingProxyType({"node-1": 1}),
        {1: "node-1"},
        inf,
    ],
)
def test_checkpoint_rejects_noncanonical_nested_json_values_without_mutating_input(
    replacement: object,
) -> None:
    raw = immutable_projection_to_checkpoint(final_projection_fixture())
    raw["scheduling"]["ready_node_ids"] = replacement
    before = deepcopy(raw) if type(replacement) is not MappingProxyType else raw.copy()

    with pytest.raises(ValidationError):
        immutable_projection_from_checkpoint(raw)

    assert raw == before


def test_checkpoint_rejects_cyclic_json_before_model_validation() -> None:
    raw = immutable_projection_to_checkpoint(final_projection_fixture())
    cycle: list[object] = []
    cycle.append(cycle)
    raw["scheduling"]["ready_node_ids"] = cycle

    with pytest.raises(ValidationError, match="cycle"):
        immutable_projection_from_checkpoint(raw)
