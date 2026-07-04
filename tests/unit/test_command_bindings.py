"""Unit tests for check-node command-binding resolution."""

from __future__ import annotations

from typing import Any

from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph.command_bindings import resolve_check_command_definition


def _dynamic_feature_event(dynamic_feature: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id="event-run-context",
        run_id="run-1",
        position=1,
        event_type="output_record_accepted",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload={"dynamic_feature": dynamic_feature},
    )


_ORACLE_BOUND_CHECK: dict[str, Any] = {
    "node_id": "check-final",
    "kind": "check",
    "command_binding": "dynamic_feature_hidden_oracle",
}


def test_oracle_binding_resolves_hidden_oracle_when_configured() -> None:
    events = [
        _dynamic_feature_event(
            {
                "hidden_oracle_command": "uv run pytest tests/oracle -q",
                "acceptance_command": "uv run pytest tests -q",
            }
        )
    ]

    definition = resolve_check_command_definition(dict(_ORACLE_BOUND_CHECK), events)

    assert definition is not None
    assert definition["cmd"] == "uv run pytest tests/oracle -q"


def test_oracle_binding_falls_back_to_acceptance_command() -> None:
    # hidden_oracle_command is an optional routine input defaulting to "" —
    # the final-invariant check must still resolve to the acceptance command
    # instead of failing non-retryable at dispatch (2bed8f2f incident).
    events = [
        _dynamic_feature_event(
            {
                "hidden_oracle_command": "",
                "acceptance_command": "uv run pytest tests -q",
            }
        )
    ]

    definition = resolve_check_command_definition(dict(_ORACLE_BOUND_CHECK), events)

    assert definition is not None
    assert definition["cmd"] == "uv run pytest tests -q"


def test_oracle_binding_unresolvable_without_any_command() -> None:
    events = [_dynamic_feature_event({"hidden_oracle_command": "", "acceptance_command": ""})]

    assert resolve_check_command_definition(dict(_ORACLE_BOUND_CHECK), events) is None
