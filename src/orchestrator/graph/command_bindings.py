"""Pure command-binding resolution for deterministic check nodes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from orchestrator.graph.models import EventEnvelope

KNOWN_CHECK_COMMAND_BINDINGS = frozenset(
    {"dynamic_feature_acceptance", "dynamic_feature_hidden_oracle"}
)
CheckInvocation = tuple[str | list[str], str, bool]
CheckCommandBindingCode = Literal[
    "unavailable_command_binding",
    "invalid_command_definition",
]


def check_command_definition_tool_schema() -> dict[str, Any]:
    """Describe the executable command shapes accepted by check dispatch."""
    argv_schema = {
        "type": "array",
        "prefixItems": [
            {
                "type": "string",
                "pattern": r"\S",
                "description": "Executable name; must contain non-whitespace text.",
            }
        ],
        "items": {"type": "string"},
        "minItems": 1,
    }
    shell_command_schema = {"type": "string", "pattern": r"\S"}
    return {
        "type": "object",
        "description": (
            "One executable command using non-empty argv, cmd, or command. Optional id and "
            "positive timeout_seconds metadata are supported."
        ),
        "properties": {
            "argv": {
                "description": (
                    "Argument-vector command. Used only when it is a non-empty string array "
                    "whose executable contains non-whitespace text."
                ),
            },
            "cmd": {
                "description": "Shell command fallback; must contain non-whitespace text.",
            },
            "command": {
                "description": "Legacy shell command fallback; must contain non-whitespace text.",
            },
            "id": {"type": "string", "minLength": 1},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        },
        "anyOf": [
            {"properties": {"argv": argv_schema}, "required": ["argv"]},
            {"properties": {"cmd": shell_command_schema}, "required": ["cmd"]},
            {
                "properties": {"command": shell_command_schema},
                "required": ["command"],
            },
        ],
        # Existing command records may carry controller-owned metadata beyond
        # the executable fields. Dispatch ignores unknown keys, so the public
        # schema advertises the supported core without rejecting extensions.
        "additionalProperties": True,
    }


class CheckCommandBindingError(ValueError):
    """Raised when a known check binding has no executable command available."""

    def __init__(
        self,
        *,
        node_id: Any,
        binding: str,
        detail: str | None = None,
        code: CheckCommandBindingCode = "unavailable_command_binding",
    ) -> None:
        self.node_id = node_id if isinstance(node_id, str) and node_id else None
        self.binding = binding
        self.code: CheckCommandBindingCode = code
        self.safe_message = (
            "Command definitions require a non-empty argv, cmd, or command value."
            if code == "invalid_command_definition"
            else "The check command binding is unavailable; provide a concrete command_definition."
        )
        node_detail = f" for node {self.node_id}" if self.node_id is not None else ""
        if detail is not None:
            reason = detail
        elif binding == "dynamic_feature_hidden_oracle":
            reason = (
                "requires a non-empty hidden_oracle_command in the routine snapshot; "
                "configure hidden_oracle_command or submit a concrete command_definition"
            )
        elif binding == "dynamic_feature_acceptance":
            reason = (
                "requires a non-empty acceptance_command in the routine snapshot; "
                "configure acceptance_command or submit a concrete command_definition"
            )
        else:
            reason = "has no executable command definition"
        super().__init__(f"check command binding {binding!r} unavailable{node_detail}: {reason}")


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


def validate_check_command_binding(
    node_payload: dict[str, Any],
    events: list[EventEnvelope],
    *,
    projection: Any | None = None,
) -> dict[str, Any] | None:
    """Validate and return the executable command for a check node.

    Concrete command definitions are retained verbatim.  Known dynamic
    bindings must resolve from the authoritative snapshot before acceptance;
    an unresolved binding is a configuration error rather than a deferred
    executable node.  Unknown bindings remain the responsibility of the
    structural node validator.
    """

    command_definition = node_payload.get("command_definition")
    if isinstance(command_definition, dict):
        definition = dict(cast(dict[str, Any], command_definition))
        if _has_executable_command(definition):
            return definition
        deferred_binding = definition.get("command_binding") or node_payload.get("command_binding")
        if is_known_check_command_binding(deferred_binding):
            node_for_resolution = {
                key: value for key, value in node_payload.items() if key != "command_definition"
            }
            node_for_resolution["command_binding"] = deferred_binding
            resolved = resolve_check_command_definition(
                node_for_resolution,
                events,
                projection=projection,
            )
            if resolved is not None:
                return resolved
            raise CheckCommandBindingError(
                node_id=node_payload.get("node_id"),
                binding=cast(str, deferred_binding),
            )
        raise CheckCommandBindingError(
            node_id=node_payload.get("node_id"),
            binding="command_definition",
            detail="requires non-empty argv or cmd; provide an executable command definition",
            code="invalid_command_definition",
        )

    command_binding = node_payload.get("command_binding")
    if not is_known_check_command_binding(command_binding):
        return None

    resolved = resolve_check_command_definition(
        node_payload,
        events,
        projection=projection,
    )
    if resolved is None:
        raise CheckCommandBindingError(
            node_id=node_payload.get("node_id"),
            binding=cast(str, command_binding),
        )
    return resolved


def has_dynamic_feature_context(
    events: list[EventEnvelope], *, projection: Any | None = None
) -> bool:
    """Return whether authoritative dynamic-feature inputs are present."""

    if _projected_dynamic_features(projection):
        return True
    for event in events:
        if isinstance(event.payload.get("dynamic_feature"), Mapping):
            return True
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, Mapping) and isinstance(
            cast(Mapping[str, Any], snapshot).get("dynamic_feature"), Mapping
        ):
            return True
    return False


def check_command_invocation(command_definition: Mapping[str, Any]) -> CheckInvocation | None:
    """Parse one command definition using the dispatcher's exact precedence."""

    argv = command_definition.get("argv")
    if isinstance(argv, list) and argv:
        parts = cast(list[Any], argv)
        if (
            all(isinstance(part, str) for part in parts)
            and isinstance(parts[0], str)
            and bool(parts[0].strip())
        ):
            typed_argv = cast(list[str], parts)
            return typed_argv, " ".join(typed_argv), False
    for key in ("cmd", "command"):
        value = command_definition.get(key)
        if isinstance(value, str) and value.strip():
            return value, value, True
    return None


def _has_executable_command(command_definition: Mapping[str, Any]) -> bool:
    return check_command_invocation(command_definition) is not None


def resolve_check_command_definition(
    node_payload: dict[str, Any],
    events: list[EventEnvelope],
    *,
    projection: Any | None = None,
) -> dict[str, Any] | None:
    """Resolve a check node's concrete executable command definition."""

    command_definition = node_payload.get("command_definition")
    if isinstance(command_definition, dict):
        definition = dict(cast(dict[str, Any], command_definition))
        if _has_executable_command(definition):
            return definition
        deferred_binding = definition.get("command_binding") or node_payload.get("command_binding")
        if is_known_check_command_binding(deferred_binding):
            node_payload = {
                key: value for key, value in node_payload.items() if key != "command_definition"
            }
            node_payload["command_binding"] = deferred_binding
        else:
            return definition

    hidden_oracle_command = node_payload.get("hidden_oracle_command")
    if isinstance(hidden_oracle_command, str) and hidden_oracle_command.strip():
        return _shell_command_definition(
            node_payload,
            hidden_oracle_command,
            source="planner_patch_hidden_oracle",
        )

    command_binding = node_payload.get("command_binding")
    if command_binding == "dynamic_feature_acceptance":
        command = _dynamic_feature_acceptance_command(events, projection=projection)
        if command is not None:
            return _shell_command_definition(
                node_payload,
                command,
                source="dynamic_feature_acceptance_binding",
            )
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
    if dynamic_features:
        return any(
            _dynamic_feature_uses_acceptance_fallback(dynamic_feature)
            for dynamic_feature in dynamic_features
        )
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
    projected_features = _projected_dynamic_features(projection)
    for dynamic_feature in projected_features:
        command = _hidden_oracle_from_dynamic_feature(dynamic_feature)
        if command is not None:
            return command
    if projected_features:
        return None
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


def _dynamic_feature_acceptance_command(
    events: list[EventEnvelope], *, projection: Any | None = None
) -> str | None:
    projected_features = _projected_dynamic_features(projection)
    for dynamic_feature in projected_features:
        command = _acceptance_from_dynamic_feature(dynamic_feature)
        if command is not None:
            return command
    if projected_features:
        return None
    for event in reversed(events):
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, dict):
            typed_snapshot = cast(dict[str, Any], snapshot)
            command = _acceptance_from_dynamic_feature(typed_snapshot.get("dynamic_feature"))
            if command is not None:
                return command
        command = _acceptance_from_dynamic_feature(event.payload.get("dynamic_feature"))
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
    return None


def _acceptance_from_dynamic_feature(dynamic_feature: Any) -> str | None:
    if not isinstance(dynamic_feature, Mapping):
        return None
    command = cast(dict[str, Any], dynamic_feature).get("acceptance_command")
    if isinstance(command, str) and command.strip():
        return command
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
