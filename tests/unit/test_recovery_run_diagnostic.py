"""Pure tests for the recovery diagnostic example."""

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError


_SPEC = importlib.util.spec_from_file_location(
    "run_diagnostic", Path("examples/recovery/run_diagnostic.py")
)
assert _SPEC and _SPEC.loader
diagnostic = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(diagnostic)


def _event(event_type: str, position: int, reason: str, node_id: str = "check command") -> dict:
    return {
        "event_id": f"event-{position}",
        "position": position,
        "event_type": event_type,
        "payload": {"node_id": node_id, "new_state": "failed", "reason": reason},
    }


def test_original_cause_is_earliest_and_summary_is_preserved() -> None:
    result = diagnostic.build_diagnostic(
        {
            "id": "run-1",
            "status": "paused",
            "pause_reason": "gate_blocked",
            "last_error": "graph node failed",
        },
        {"node_states": {"z": "failed", "check command": "failed", "a": "completed"}},
        (
            {
                "run_id": "run-1",
                "node_id": "check command",
                "callback_history": [
                    _event(
                        "agent_died", 486, "check command_definition requires non-empty argv or cmd"
                    )
                ],
                "events": [_event("node_state_changed", 500, "later wrapper")],
            },
        ),
    )
    assert [failure.node_id for failure in result.failures] == ["check command", "z"]
    assert result.failures[0].reason == "check command_definition requires non-empty argv or cmd"
    assert result.failures[0].event_position == 486
    assert result.summary_error == "graph node failed"
    assert result.failures[1].reason is None
    assert "node:z" in result.unavailable


def test_duplicate_overlap_is_deduplicated() -> None:
    event = _event("agent_died", 12, "cause", "n")
    detail = {"run_id": "run-2", "node_id": "n", "callback_history": [event], "events": [event]}
    result = diagnostic.build_diagnostic(
        {"id": "run-2", "status": "failed"}, {"node_states": {"n": "failed"}}, (detail,)
    )
    assert result.failures[0].model_dump() == {
        "node_id": "n",
        "reason": "cause",
        "event_position": 12,
    }
    assert result.unavailable == ()


@pytest.mark.parametrize(
    "graph",
    [
        {},
        {"node_states": None},
        {"node_states": []},
        {"node_states": {"node": 1}},
    ],
)
def test_missing_or_malformed_node_states_fails_strict_boundary(graph: dict) -> None:
    with pytest.raises(ValidationError):
        diagnostic.build_diagnostic({"id": "run-1", "status": "failed"}, graph, ())


def test_present_empty_node_states_is_valid_complete_evidence() -> None:
    result = diagnostic.build_diagnostic(
        {"id": "run-1", "status": "completed"}, {"node_states": {}}, ()
    )
    assert result.failures == ()
    assert result.unavailable == ()


def test_wrong_run_and_malformed_node_boundaries_raise_typed_errors() -> None:
    with pytest.raises(ValueError):
        diagnostic.build_diagnostic(
            {"id": "run-1", "status": "failed"},
            {"node_states": {"n": "failed"}},
            ({"run_id": "other", "node_id": "n"},),
        )
    with pytest.raises(ValidationError):
        diagnostic.build_diagnostic(
            {"id": "run-1", "status": "failed"},
            {"node_states": {"n": "failed"}},
            ({"run_id": "run-1", "node_id": "n", "events": "bad"},),
        )
