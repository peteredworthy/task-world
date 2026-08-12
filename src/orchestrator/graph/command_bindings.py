"""Pure command-binding resolution for deterministic check nodes."""

from __future__ import annotations

from collections.abc import Mapping
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
    *,
    projection: Any | None = None,
) -> bool:
    """Resolve an executable check command into the node payload when possible."""

    if node_payload.get("kind") != "check" or "command_definition" in node_payload:
        return False
    command_definition = resolve_check_command_definition(
        node_payload,
        events,
        projection=projection,
    )
    if command_definition is None:
        return False
    node_payload["command_definition"] = command_definition
    return True


def resolve_check_command_definition(
    node_payload: dict[str, Any],
    events: list[EventEnvelope],
    *,
    projection: Any | None = None,
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
        command = _dynamic_feature_hidden_oracle_command(events, projection=projection)
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
    *,
    projection: Any | None = None,
) -> bool:
    """Return True when dynamic oracle binding resolves to acceptance_command."""

    if node_payload.get("command_binding") != "dynamic_feature_hidden_oracle":
        return False
    dynamic_features = _projected_dynamic_features(projection)
    for dynamic_feature in dynamic_features:
        if _dynamic_feature_uses_acceptance_fallback(dynamic_feature):
            return True
    for event in reversed(events):
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, dict):
            dynamic_feature = cast(dict[str, Any], snapshot).get("dynamic_feature")
            if _dynamic_feature_uses_acceptance_fallback(dynamic_feature):
                return True
        if _dynamic_feature_uses_acceptance_fallback(event.payload.get("dynamic_feature")):
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


def _dynamic_feature_hidden_oracle_command(
    events: list[EventEnvelope], *, projection: Any | None = None
) -> str | None:
    for dynamic_feature in _projected_dynamic_features(projection):
        command = _hidden_oracle_from_dynamic_feature(dynamic_feature)
        if command is not None:
            return command
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


def _projected_dynamic_features(projection: Any | None) -> tuple[object, ...]:
    """Read dynamic-feature inputs from the durable immutable snapshot.

    ``FrozenMap`` is a Mapping, not a dict.  Keep this boundary structural so
    command resolution does not thaw or mutate checkpoint-owned values.
    """
    if projection is None:
        return ()
    records = getattr(getattr(projection, "records", None), "by_id", None)
    if not isinstance(records, Mapping):
        return ()
    typed_records = cast(Mapping[str, Any], records)
    latest = getattr(getattr(projection, "planning", None), "latest_routine_snapshot", None)
    latest_record_id = getattr(latest, "record_id", None)
    record_ids: tuple[str, ...] = (
        (latest_record_id,) if isinstance(latest_record_id, str) else tuple(typed_records)
    )
    values: list[object] = []
    for record_id in record_ids:
        record = typed_records.get(record_id)
        if record is None or getattr(record, "record_type", None) != "routine_snapshot":
            continue
        snapshot = getattr(record, "value", None)
        dynamic_feature = getattr(snapshot, "dynamic_feature", None)
        if dynamic_feature is not None:
            values.append(dynamic_feature)
    return tuple(values)


def _hidden_oracle_from_dynamic_feature(dynamic_feature: Any) -> str | None:
    if not isinstance(dynamic_feature, Mapping):
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
    if not isinstance(dynamic_feature, Mapping):
        return False
    typed = cast(dict[str, Any], dynamic_feature)
    hidden = typed.get("hidden_oracle_command")
    if isinstance(hidden, str) and hidden.strip():
        return False
    fallback = typed.get("acceptance_command")
    return isinstance(fallback, str) and bool(fallback.strip())
