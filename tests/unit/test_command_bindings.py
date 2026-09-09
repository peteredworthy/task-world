"""Unit tests for check-node command-binding resolution."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    initial_projection,
    reduce_event,
)
from orchestrator.graph import (
    CheckCommandBindingError,
    resolve_check_command_definition,
    validate_check_command_binding,
)


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
    # Hidden-oracle and product acceptance commands are separate authorities.
    # An absent oracle must not silently acquire the acceptance command.
    events = [
        _dynamic_feature_event(
            {
                "hidden_oracle_command": "",
                "acceptance_command": "uv run pytest tests -q",
            }
        )
    ]

    oracle_definition = resolve_check_command_definition(dict(_ORACLE_BOUND_CHECK), events)
    acceptance_definition = resolve_check_command_definition(
        {
            "node_id": "check-acceptance",
            "kind": "check",
            "command_binding": "dynamic_feature_acceptance",
        },
        events,
    )

    assert oracle_definition is None
    assert acceptance_definition is not None
    assert acceptance_definition["cmd"] == "uv run pytest tests -q"
    assert acceptance_definition["source"] == "dynamic_feature_acceptance_binding"


def test_oracle_binding_unresolvable_without_any_command() -> None:
    events = [_dynamic_feature_event({"hidden_oracle_command": "", "acceptance_command": ""})]

    assert resolve_check_command_definition(dict(_ORACLE_BOUND_CHECK), events) is None


def test_oracle_binding_validation_reports_typed_actionable_configuration_error() -> None:
    events = [
        _dynamic_feature_event(
            {
                "hidden_oracle_command": "",
                "acceptance_command": "uv run pytest tests -q",
            }
        )
    ]

    with pytest.raises(CheckCommandBindingError, match="non-empty hidden_oracle_command"):
        validate_check_command_binding(dict(_ORACLE_BOUND_CHECK), events)


def test_oracle_binding_reads_immutable_durable_routine_snapshot() -> None:
    node = _dynamic_feature_event({})
    node = node.model_copy(
        update={
            "event_id": "routine-snapshot-node",
            "event_type": "node_created",
            "payload": {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
        }
    )
    record = node.model_copy(
        update={
            "event_id": "routine-snapshot-record",
            "position": 2,
            "event_type": "output_record_accepted",
            "payload": {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine",
                    "content_hash": "hash",
                    "step_count": 1,
                    "task_count": 1,
                    "dynamic_feature": {
                        "hidden_oracle_command": "uv run pytest tests/oracle -q",
                        "acceptance_command": "uv run pytest tests -q",
                    },
                },
            },
        }
    )
    projection = reduce_event(reduce_event(initial_projection(), node), record)

    definition = resolve_check_command_definition(
        dict(_ORACLE_BOUND_CHECK), [], projection=projection
    )

    assert definition is not None
    assert definition["cmd"] == "uv run pytest tests/oracle -q"


def test_empty_current_snapshot_does_not_fall_back_to_an_older_oracle() -> None:
    node = _dynamic_feature_event({}).model_copy(
        update={
            "event_type": "node_created",
            "payload": {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
        }
    )
    older = _dynamic_feature_event(
        {
            "hidden_oracle_command": "uv run pytest tests/oracle -q",
            "acceptance_command": "uv run pytest tests -q",
        }
    ).model_copy(
        update={
            "event_id": "older-routine-snapshot-record",
            "position": 2,
            "event_type": "output_record_accepted",
            "payload": {
                "record_id": "older-routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine",
                    "content_hash": "hash-old",
                    "step_count": 1,
                    "task_count": 1,
                    "dynamic_feature": {
                        "hidden_oracle_command": "uv run pytest tests/oracle -q",
                        "acceptance_command": "uv run pytest tests -q",
                    },
                },
            },
        }
    )
    current = older.model_copy(
        update={
            "event_id": "current-routine-snapshot-record",
            "position": 3,
            "payload": {
                **older.payload,
                "record_id": "current-routine-snapshot-record",
                "value": {
                    **older.payload["value"],
                    "content_hash": "hash-current",
                    "dynamic_feature": {
                        "hidden_oracle_command": "",
                        "acceptance_command": "uv run pytest tests -q",
                    },
                },
            },
        }
    )
    projection = reduce_event(
        reduce_event(reduce_event(initial_projection(), node), older), current
    )

    assert (
        resolve_check_command_definition(dict(_ORACLE_BOUND_CHECK), [], projection=projection)
        is None
    )


@pytest.mark.parametrize("argv", [["", "true"], ["   ", "true"]])
def test_blank_argv_first_token_is_not_executable(argv: list[str]) -> None:
    with pytest.raises(CheckCommandBindingError, match="non-empty argv or cmd"):
        validate_check_command_binding(
            {
                "node_id": "check-malformed",
                "kind": "check",
                "command_definition": {"argv": argv},
            },
            [],
        )


def test_command_alias_is_used_when_cmd_is_blank() -> None:
    definition = validate_check_command_binding(
        {
            "node_id": "check-command-alias",
            "kind": "check",
            "command_definition": {"cmd": "", "command": "printf alias"},
        },
        [],
    )

    assert definition == {"cmd": "", "command": "printf alias"}
