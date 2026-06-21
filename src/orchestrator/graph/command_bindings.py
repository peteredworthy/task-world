"""Pure command-binding resolution for deterministic check nodes."""

from __future__ import annotations

from typing import Any, cast

from orchestrator.graph.models import EventEnvelope

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
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, dict):
            typed_snapshot = cast(dict[str, Any], snapshot)
            command = _hidden_oracle_from_dynamic_feature(typed_snapshot.get("dynamic_feature"))
            if command is not None:
                return command
        command = _hidden_oracle_from_dynamic_feature(event.payload.get("dynamic_feature"))
        if command is not None:
            return command
    return None


def _hidden_oracle_from_dynamic_feature(dynamic_feature: Any) -> str | None:
    if not isinstance(dynamic_feature, dict):
        return None
    command = cast(dict[str, Any], dynamic_feature).get("hidden_oracle_command")
    if isinstance(command, str) and command.strip():
        return command
    return None
