"""Event-backed regressions for flexible JSON projection fields."""

from copy import deepcopy

from orchestrator.graph import (
    FrozenMap,
    build_projection,
    projection_from_checkpoint,
    projection_to_checkpoint,
)
from tests.unit.graph_projection_behavior_cases import event


def _assert_plain_json(value: object) -> None:
    assert type(value) in {dict, list, str, int, float, bool, type(None)}
    if type(value) is dict:
        for key, child in value.items():
            assert type(key) is str
            _assert_plain_json(child)
    elif type(value) is list:
        for child in value:
            _assert_plain_json(child)


def _assert_deeply_immutable(value: object) -> None:
    if type(value) is FrozenMap:
        for key, child in value.items():
            assert type(key) is str
            _assert_deeply_immutable(child)
    elif type(value) is tuple:
        for child in value:
            _assert_deeply_immutable(child)
    else:
        assert type(value) in {str, int, float, bool, type(None)}


def test_approval_scope_round_trips_nested_json_through_checkpoint() -> None:
    scope = {"nested": [{"items": [1, True, None]}, "text"]}
    events = (
        event(
            "node_created",
            {"node_id": "gate-1", "kind": "gate", "state": "planned"},
            0,
        ),
        event(
            "approval_decision_recorded",
            {
                "record_id": "approval-1",
                "decision_type": "approval",
                "node_id": "gate-1",
                "decider": "controller",
                "decision": "approved",
                "scope": scope,
            },
            1,
        ),
    )

    projection = build_projection(list(events))
    checkpoint = projection_to_checkpoint(projection)
    checkpoint_scope = checkpoint["governance"]["approval_decisions_by_id"]["approval-1"]["scope"]
    _assert_plain_json(checkpoint_scope)

    restored = projection_from_checkpoint(deepcopy(checkpoint))
    restored_scope = restored.governance.approval_decisions_by_id["approval-1"].scope
    assert restored == projection
    _assert_deeply_immutable(restored_scope)


def test_oversight_decider_round_trips_nested_json_through_checkpoint() -> None:
    decider = {
        "actor": {"roles": ["operator", "reviewer"]},
        "chain": [{"trusted": True, "labels": ["human", "primary"]}],
    }
    events = (
        event(
            "node_created",
            {"node_id": "oversight-1", "kind": "oversight", "state": "planned"},
            0,
        ),
        event(
            "oversight_decision_recorded",
            {
                "record_id": "oversight-1",
                "decision_type": "oversight",
                "node_id": "oversight-1",
                "decider": decider,
                "decision": "accepted",
            },
            1,
        ),
    )

    projection = build_projection(list(events))
    checkpoint = projection_to_checkpoint(projection)
    checkpoint_decider = checkpoint["governance"]["oversight_decisions_by_id"]["oversight-1"][
        "decider"
    ]
    _assert_plain_json(checkpoint_decider)

    restored = projection_from_checkpoint(deepcopy(checkpoint))
    restored_decider = restored.governance.oversight_decisions_by_id["oversight-1"].decider
    assert restored == projection
    _assert_deeply_immutable(restored_decider)
