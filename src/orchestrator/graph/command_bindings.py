"""Pure command-binding resolution for deterministic check nodes."""

from __future__ import annotations

from typing import Any, cast

from orchestrator.graph.events.records import OutputRecordAcceptedPayload
from orchestrator.graph.models import EventEnvelope, RoutineSnapshotRecord

KNOWN_CHECK_COMMAND_BINDINGS = frozenset({"dynamic_feature_hidden_oracle"})


def is_known_check_command_binding(value: Any) -> bool:
    return isinstance(value, str) and value in KNOWN_CHECK_COMMAND_BINDINGS


def check_command_reference(node_payload: dict[str, Any]) -> Any | None:
    """Return a command handle that satisfies check scheduling preconditions."""

    command_definition = node_payload.get("command_definition")
    if isinstance(command_definition, dict):
        return dict(cast(dict[str, Any], command_definition))
    command_definition_id = node_payload.get("command_definition_id")
    if isinstance(command_definition_id, str):
        return command_definition_id

    hidden_oracle_command = node_payload.get("hidden_oracle_command")
    if isinstance(hidden_oracle_command, str) and hidden_oracle_command.strip():
        return _shell_command_definition(
            node_payload,
            hidden_oracle_command,
            source="planner_patch_hidden_oracle",
        )

    command_binding = node_payload.get("command_binding")
    if is_known_check_command_binding(command_binding):
        return {
            "id": str(node_payload.get("node_id", "bound_check")),
            "command_binding": command_binding,
            "source": f"{command_binding}_binding",
            "deferred": True,
        }
    return None


def canonicalize_check_command_definition(
    node_payload: dict[str, Any],
    events: list[EventEnvelope],
) -> bool:
    """Resolve an executable check command into the node payload when possible."""

    if node_payload.get("kind") != "check" or "command_definition" in node_payload:
        return False
    command_definition = resolve_check_command_definition(node_payload, events)
    if command_definition is None:
        return False
    node_payload["command_definition"] = command_definition
    return True


def resolve_check_command_definition(
    node_payload: dict[str, Any],
    events: list[EventEnvelope],
) -> dict[str, Any] | None:
    """Resolve a check node's concrete executable command definition."""

    command_definition = node_payload.get("command_definition")
    if isinstance(command_definition, dict):
        return dict(cast(dict[str, Any], command_definition))

    hidden_oracle_command = node_payload.get("hidden_oracle_command")
    if isinstance(hidden_oracle_command, str) and hidden_oracle_command.strip():
        return _shell_command_definition(
            node_payload,
            hidden_oracle_command,
            source="planner_patch_hidden_oracle",
        )

    command_binding = node_payload.get("command_binding")
    if command_binding == "dynamic_feature_hidden_oracle":
        command = _dynamic_feature_hidden_oracle_command(events)
        if command is not None:
            return _shell_command_definition(
                node_payload,
                command,
                source="dynamic_feature_hidden_oracle_binding",
            )
    return None


def check_command_uses_acceptance_fallback(
    node_payload: dict[str, Any],
    events: list[EventEnvelope],
) -> bool:
    """Return True when dynamic oracle binding resolves to acceptance_command."""

    if node_payload.get("command_binding") != "dynamic_feature_hidden_oracle":
        return False
    for event in reversed(events):
        dynamic_feature = _dynamic_feature_from_routine_snapshot(event)
        if _dynamic_feature_uses_acceptance_fallback(dynamic_feature):
            return True
    return False


def _shell_command_definition(
    node_payload: dict[str, Any],
    command: str,
    *,
    source: str,
) -> dict[str, Any]:
    return {
        "id": str(node_payload.get("node_id", "planner_patch_check")),
        "cmd": command,
        "must": True,
        "source": source,
    }


def _dynamic_feature_hidden_oracle_command(events: list[EventEnvelope]) -> str | None:
    for event in reversed(events):
        command = _hidden_oracle_from_dynamic_feature(_dynamic_feature_from_routine_snapshot(event))
        if command is not None:
            return command
    return None


def _dynamic_feature_from_routine_snapshot(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type != "output_record_accepted":
        return None
    accepted = OutputRecordAcceptedPayload.model_validate(event.payload)
    record = accepted.record
    if not isinstance(record, RoutineSnapshotRecord):
        return None
    dynamic_feature = record.value.dynamic_feature
    return dynamic_feature if isinstance(dynamic_feature, dict) else None


def _hidden_oracle_from_dynamic_feature(dynamic_feature: Any) -> str | None:
    if not isinstance(dynamic_feature, dict):
        return None
    typed = cast(dict[str, Any], dynamic_feature)
    command = typed.get("hidden_oracle_command")
    if isinstance(command, str) and command.strip():
        return command
    # hidden_oracle_command is an optional routine input (defaults to "").
    # Planners are instructed to bind final-invariant checks to this binding,
    # so when no hidden oracle is configured the check must still resolve —
    # fall back to the run's acceptance command rather than leaving the node
    # unresolvable (a non-retryable runtime failure at dispatch).
    fallback = typed.get("acceptance_command")
    if isinstance(fallback, str) and fallback.strip():
        return fallback
    return None


def _dynamic_feature_uses_acceptance_fallback(dynamic_feature: Any) -> bool:
    if not isinstance(dynamic_feature, dict):
        return False
    typed = cast(dict[str, Any], dynamic_feature)
    hidden = typed.get("hidden_oracle_command")
    if isinstance(hidden, str) and hidden.strip():
        return False
    fallback = typed.get("acceptance_command")
    return isinstance(fallback, str) and bool(fallback.strip())
