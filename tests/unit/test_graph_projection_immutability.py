"""RED contracts for deeply immutable graph projection generations."""

from collections.abc import Mapping
from datetime import datetime, timezone
from operator import delitem, setitem
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EVENT_PAYLOAD_MODELS,
    EventEnvelope,
    GraphProjection,
    PatchEnvelope,
    ProjectionModel,
    build_projection,
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
)


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "graph"
ROOT_GROUPS = (
    "lifecycle",
    "nodes",
    "tasks",
    "topology",
    "records",
    "scheduling",
    "planning",
    "verification",
    "governance",
    "requirements",
    "execution",
    "usage",
)


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"immutability-{position}",
        run_id="immutability-run",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        payload=payload,
    )


REPRESENTATIVE_EVENT_CASES = (
    (
        "lifecycle",
        _event(
            "run_lifecycle_changed",
            {
                "command_type": "start",
                "from_state": "queued",
                "to_state": "active",
                "trigger": "test",
            },
            0,
        ),
        {"lifecycle"},
    ),
    (
        "node",
        _event("node_created", {"node_id": "node-1", "kind": "worker", "state": "planned"}, 1),
        {"nodes"},
    ),
    (
        "task-and-record",
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "attempt_number": 1,
                "value": {"summary": "candidate"},
            },
            2,
        ),
        {"records", "tasks"},
    ),
    (
        "topology",
        _event(
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "source-1",
                "from_port": "output",
                "to_node_id": "target-1",
                "to_port": "input",
            },
            3,
        ),
        {"topology"},
    ),
    (
        "planning",
        _event(
            "graph_patch_accepted",
            {"patch_id": "patch-1", "proposed_by_node_id": "planner-1"},
            4,
        ),
        {"planning", "governance"},
    ),
    (
        "verification",
        _event(
            "verification_passed",
            {
                "node_id": "verifier-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "record_id": "verification-1",
                "outcome": "passed",
                "evidence": [],
                "value": {"outcome": "passed", "grades": []},
            },
            5,
        ),
        {"verification"},
    ),
    (
        "governance",
        _event(
            "approval_decision_recorded",
            {
                "decision_type": "approval",
                "node_id": "gate-1",
                "decision": "approved",
                "decider": "controller",
            },
            6,
        ),
        {"governance"},
    ),
    (
        "requirements",
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "requirement-1", "version_id": "requirement-1.v1"},
            7,
        ),
        {"requirements"},
    ),
    (
        "execution",
        _event(
            "lease_granted",
            {"lease_id": "lease-1", "node_id": "worker-1"},
            8,
        ),
        {"execution"},
    ),
    (
        "usage",
        _event(
            "node_usage_recorded",
            {
                "node_id": "worker-1",
                "node_kind": "worker",
                "execution_id": "execution-1",
                "usage_index": 0,
                "usage_count": 1,
                "usage_key": "execution-1:0",
                "model": "test-model",
                "gen_ai_usage_input_tokens": 2,
                "gen_ai_usage_output_tokens": 3,
            },
            9,
        ),
        {"usage"},
    ),
)

REPRESENTATIVE_EVENTS = tuple(
    pytest.param(*case, id=case[0]) for case in REPRESENTATIVE_EVENT_CASES
)


def test_representative_reductions_leave_input_generation_unchanged() -> None:
    for name, event, _changed_groups in REPRESENTATIVE_EVENT_CASES:
        before = initial_projection()
        before_checkpoint = projection_to_checkpoint(before)

        reduce_event(before, event)

        assert projection_to_checkpoint(before) == before_checkpoint, name


@pytest.mark.parametrize("name,event,changed_groups", REPRESENTATIVE_EVENTS)
def test_persistent_updates_share_unchanged_groups_and_replace_changed_groups(
    name: str,
    event: EventEnvelope,
    changed_groups: set[str],
) -> None:
    before = initial_projection()
    after = reduce_event(before, event)

    assert after is not before, name
    for group_name in ROOT_GROUPS:
        before_group = getattr(before, group_name)
        after_group = getattr(after, group_name)
        if group_name in changed_groups:
            assert after_group is not before_group, f"{name}: {group_name} was not replaced"
        else:
            assert after_group is before_group, f"{name}: {group_name} was copied"


def test_changed_node_entity_is_replaced_while_unchanged_node_is_shared() -> None:
    initial = initial_projection()
    with_two_nodes = reduce_event(
        reduce_event(
            initial,
            _event(
                "node_created",
                {"node_id": "node-1", "kind": "worker", "state": "planned"},
                20,
            ),
        ),
        _event(
            "node_created",
            {"node_id": "node-2", "kind": "worker", "state": "planned"},
            21,
        ),
    )

    updated = reduce_event(
        with_two_nodes,
        _event(
            "node_state_changed",
            {"node_id": "node-1", "new_state": "ready", "trigger": "test"},
            22,
        ),
    )

    updated_entities = _mapping_containing_key(updated, "node-1")
    previous_entities = _mapping_containing_key(with_two_nodes, "node-1")
    assert updated_entities is not previous_entities
    assert updated_entities["node-1"] is not previous_entities["node-1"]
    assert updated_entities["node-2"] is previous_entities["node-2"]


def _mapping_containing_key(model: BaseModel, key: str) -> Mapping[str, object]:
    for field_name in type(model).model_fields:
        value = getattr(model, field_name)
        if isinstance(value, Mapping) and key in value:
            return value
    raise AssertionError(f"no mapping field contains {key!r}")


def _event_model_types() -> tuple[type[BaseModel], ...]:
    return tuple({EventEnvelope, PatchEnvelope, *EVENT_PAYLOAD_MODELS.values()})


def _assert_deeply_immutable(value: object, path: str, seen: set[int]) -> None:
    if id(value) in seen:
        return
    seen.add(id(value))

    event_models = _event_model_types()
    if isinstance(value, event_models):
        raise AssertionError(f"event/transport model reachable at {path}: {type(value).__name__}")
    if isinstance(value, (dict, list, set)):
        raise AssertionError(f"mutable container reachable at {path}: {type(value).__name__}")

    if isinstance(value, BaseModel):
        fields = tuple(type(value).model_fields)
        if fields:
            with pytest.raises((AttributeError, TypeError, ValidationError)):
                setattr(value, fields[0], getattr(value, fields[0]))
        for field_name in fields:
            _assert_deeply_immutable(getattr(value, field_name), f"{path}.{field_name}", seen)
        return

    if isinstance(value, Mapping):
        with pytest.raises((AttributeError, TypeError)):
            setitem(value, "__immutability_probe__", value)
        with pytest.raises((AttributeError, KeyError, TypeError)):
            delitem(value, "__immutability_probe__")
        with pytest.raises((AttributeError, TypeError)):
            getattr(value, "update")({"__immutability_probe__": value})
        for key, child in value.items():
            _assert_deeply_immutable(key, f"{path}.<key>", seen)
            _assert_deeply_immutable(child, f"{path}[{key!r}]", seen)
        return

    if isinstance(value, tuple):
        if value:
            with pytest.raises(TypeError):
                setitem(value, 0, value[0])
        for index, child in enumerate(value):
            _assert_deeply_immutable(child, f"{path}[{index}]", seen)


def test_final_projection_has_no_reachable_mutability_or_transport_models() -> None:
    stream = [event for _, event, _changed_groups in REPRESENTATIVE_EVENT_CASES]
    projection: GraphProjection = build_projection(stream)

    _assert_deeply_immutable(projection, "projection", set())


def test_public_projection_model_is_frozen() -> None:
    projection = initial_projection()

    assert isinstance(projection, ProjectionModel)
    field_name = next(iter(type(projection).model_fields))
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        setattr(projection, field_name, getattr(projection, field_name))
