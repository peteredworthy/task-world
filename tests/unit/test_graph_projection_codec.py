"""Public checkpoint contracts for the immutable projection scaffold."""

from copy import deepcopy
from collections import UserDict
from math import inf, nan
from types import MappingProxyType
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    GraphProjection,
    FrozenMap,
    ProjectionCheckpointCodecError,
    build_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
)


class SerializationFailure(BaseModel):
    """A real Pydantic value whose serializer cannot produce JSON."""

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
                        "acceptance_identity": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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


def test_checkpoint_round_trip_preserves_ordinary_json_shape() -> None:
    checkpoint = projection_to_checkpoint(final_projection_fixture())

    assert type(checkpoint) is dict
    assert type(checkpoint["nodes"]) is dict
    assert type(checkpoint["scheduling"]["ready_node_ids"]) is list
    assert projection_from_checkpoint(checkpoint) == final_projection_fixture()


def test_checkpoint_round_trip_freezes_nested_oversight_scope_arrays() -> None:
    clock = FakeClock()
    actor = Actor(kind=ActorKind.CONTROLLER)
    projection = build_projection(
        [
            EventEnvelope(
                event_id="node-created-1",
                run_id="run-1",
                position=1,
                event_type="node_created",
                schema_version=1,
                actor=actor,
                timestamp=clock.now(),
                payload={"node_id": "oversight-1", "kind": "oversight", "state": "running"},
            ),
            EventEnvelope(
                event_id="oversight-decision-2",
                run_id="run-1",
                position=2,
                event_type="oversight_decision_recorded",
                schema_version=1,
                actor=actor,
                timestamp=clock.now(),
                payload={
                    "decision_type": "oversight",
                    "node_id": "oversight-1",
                    "decision": "rejected",
                    "decider": "operator",
                    "scope": {"items": ["original"]},
                },
            ),
        ]
    )
    checkpoint = projection_to_checkpoint(projection)

    assert projection_from_checkpoint(checkpoint) == projection


def test_checkpoint_round_trip_freezes_nested_authority_scope_arrays() -> None:
    clock = FakeClock()
    actor = Actor(kind=ActorKind.CONTROLLER)
    projection = build_projection(
        [
            EventEnvelope(
                event_id="node-created-1",
                run_id="run-1",
                position=1,
                event_type="node_created",
                schema_version=1,
                actor=actor,
                timestamp=clock.now(),
                payload={"node_id": "authority-1", "kind": "authority_request", "state": "running"},
            ),
            EventEnvelope(
                event_id="authority-decision-2",
                run_id="run-1",
                position=2,
                event_type="authority_decision_recorded",
                schema_version=1,
                actor=actor,
                timestamp=clock.now(),
                payload={
                    "decision_type": "authority",
                    "node_id": "authority-1",
                    "decision": "granted",
                    "decider": "operator",
                    "scope": {"tools": ["graph_write"]},
                },
            ),
        ]
    )
    checkpoint = projection_to_checkpoint(projection)

    restored = projection_from_checkpoint(checkpoint)

    assert restored == projection
    scope = restored.governance.authority_decisions_by_id["authority-decision-2"].scope
    assert isinstance(scope, FrozenMap)
    assert scope["tools"] == ("graph_write",)


@pytest.mark.parametrize("bad", ["1", True, inf])
def test_checkpoint_rejects_scalar_coercion(bad: object) -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    raw["usage"]["tokens_by_node"] = {"node-1": bad}

    with pytest.raises(ValidationError):
        projection_from_checkpoint(raw)


def test_checkpoint_rejects_non_dict_root_without_salvaging_it() -> None:
    with pytest.raises(ValidationError):
        projection_from_checkpoint([])


@pytest.mark.parametrize("missing_group", ["lifecycle", "topology", "usage"])
def test_checkpoint_rejects_missing_canonical_root_group(missing_group: str) -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    raw.pop(missing_group)

    with pytest.raises(ValidationError, match="root keys"):
        projection_from_checkpoint(raw)


@pytest.mark.parametrize("case", ["projection", "user-dict", "mapping-proxy"])
def test_checkpoint_rejects_model_or_non_exact_mapping_roots(case: str) -> None:
    root: object
    if case == "projection":
        root = final_projection_fixture()
    elif case == "user-dict":
        root = UserDict({})
    else:
        root = MappingProxyType({})

    with pytest.raises(ValidationError, match="exact JSON object"):
        projection_from_checkpoint(root)


@pytest.mark.parametrize("number", [nan, inf, -inf])
def test_checkpoint_rejects_all_nonfinite_numbers(number: float) -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    raw["usage"]["tokens_by_node"] = {"node-1": number}

    with pytest.raises(ValidationError, match="numbers must be finite"):
        projection_from_checkpoint(raw)


def test_checkpoint_writer_wraps_only_pydantic_serialization_errors() -> None:
    with pytest.raises(ProjectionCheckpointCodecError, match="serialization failed") as raised:
        projection_to_checkpoint(cast(GraphProjection, SerializationFailure(value=object())))

    assert isinstance(raised.value.__cause__, PydanticSerializationError)


def test_checkpoint_writer_propagates_unrelated_serialization_errors() -> None:
    with pytest.raises(RuntimeError, match="unrelated failure"):
        projection_to_checkpoint(
            cast(GraphProjection, UnrelatedSerializationFailure(value=object()))
        )


def test_checkpoint_rejects_unknown_or_malformed_sibling_without_defaulting() -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    before = deepcopy(raw)
    raw["usage"] = {"unknown": True}

    with pytest.raises(ValidationError):
        projection_from_checkpoint(raw)

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
    raw = projection_to_checkpoint(final_projection_fixture())
    raw["scheduling"]["ready_node_ids"] = replacement
    before = deepcopy(raw) if type(replacement) is not MappingProxyType else raw.copy()

    with pytest.raises(ValidationError):
        projection_from_checkpoint(raw)

    assert raw == before


def test_checkpoint_rejects_cyclic_json_before_model_validation() -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    cycle: list[object] = []
    cycle.append(cycle)
    raw["scheduling"]["ready_node_ids"] = cycle

    with pytest.raises(ValidationError, match="cycle"):
        projection_from_checkpoint(raw)


def test_checkpoint_rejects_json_nesting_deeper_than_the_transport_limit() -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    nested: list[object] = []
    cursor = nested
    for _ in range(101):
        child: list[object] = []
        cursor.append(child)
        cursor = child
    raw["scheduling"]["ready_node_ids"] = nested

    with pytest.raises(ValidationError, match="depth"):
        projection_from_checkpoint(raw)


def test_checkpoint_preserves_nested_json_arrays_as_immutable_field_values() -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    raw["topology"]["edges"]["edge-1"]["metadata"] = {"levels": [["one"], {"two": [2, 3]}]}

    projection = projection_from_checkpoint(raw)

    metadata = projection.topology.edges["edge-1"].metadata
    assert isinstance(metadata, FrozenMap)
    assert metadata["levels"] == (("one",), FrozenMap({"two": (2, 3)}))


def test_checkpoint_freezes_nested_callback_payload_arrays() -> None:
    raw = projection_to_checkpoint(final_projection_fixture())
    raw["execution"]["callback_events_by_key"]["node-1\u0000callback-1"]["payload"] = {
        "review_record_id": "review-record-1",
        "output_records": [
            {
                "record_id": "output-record-1",
                "value": {"graph_changes": [["path", "value"]]},
            }
        ],
    }

    projection = projection_from_checkpoint(raw)

    payload = projection.execution.callback_events_by_key["node-1\u0000callback-1"].payload
    assert isinstance(payload, FrozenMap)
    assert payload["output_records"] == (
        FrozenMap(
            {
                "record_id": "output-record-1",
                "value": FrozenMap({"graph_changes": (("path", "value"),)}),
            }
        ),
    )
