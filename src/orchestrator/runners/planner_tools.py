"""Planner graph-tool authorization, ordering, and reliable-plan preflight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from jsonschema import Draft202012Validator, SchemaError

from orchestrator.graph import DEFAULT_NODE_CONTRACTS
from orchestrator.runners.errors import AgentConfigError

RELIABLE_PLAN_REQUIRED_TOOL_NAMES: tuple[str, ...] = (
    "create_discovery_region",
    "create_plan_verification",
    "create_successor_planner",
    "create_effectful_batch",
)

# This is the single stable ordering used by every graph-capable runner.  The
# reliable-plan macros intentionally retain their contract order as one block.
GRAPH_PLANNER_TOOL_ORDER: tuple[str, ...] = (
    "create_work_region",
    "create_corrective_region",
    "attach_verifier",
    "attach_check",
    "create_gap_planner",
    "create_join",
    "request_gate",
    "retire_or_supersede",
    *RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    "submit_graph_patch",
)
REGISTERED_GRAPH_PLANNER_TOOL_NAMES: frozenset[str] = frozenset(GRAPH_PLANNER_TOOL_ORDER)

_RELIABLE_PLAN_REQUIRED_SCHEMA_FIELDS: dict[str, frozenset[str]] = {
    "create_discovery_region": frozenset(
        {
            "patch_id",
            "base_graph_position",
            "region_id",
            "semantic_schema_id",
            "semantic_schema_version",
            "objective",
            "acceptance",
        }
    ),
    "create_plan_verification": frozenset(
        {
            "patch_id",
            "base_graph_position",
            "region_id",
            "artifact_source_node_id",
            "semantic_schema_id",
            "semantic_schema_version",
            "objective",
            "acceptance",
            "rubric",
        }
    ),
    "create_successor_planner": frozenset(
        {
            "patch_id",
            "base_graph_position",
            "region_id",
            "evidence_source_node_id",
            "evidence_source_port",
            "planning_horizon",
        }
    ),
    "create_effectful_batch": frozenset(
        {
            "patch_id",
            "base_graph_position",
            "region_id",
            "batch_id",
            "plan_source_node_id",
            "plan_verification_source_node_id",
            "semantic_schema_id",
            "semantic_schema_version",
            "objective",
            "acceptance",
            "checks",
            "rubric",
            "planning_horizon",
        }
    ),
}


class ReliablePlanToolPreflightError(AgentConfigError):
    """A reliable-plan planner cannot start with its required tool contract."""

    def __init__(
        self,
        *,
        missing_tools: Sequence[str] = (),
        invalid_tools: Mapping[str, str] | None = None,
    ) -> None:
        self.missing_tools = tuple(missing_tools)
        self.invalid_tools = dict(invalid_tools or {})
        details: list[str] = []
        if self.missing_tools:
            details.append(f"missing tools: {', '.join(self.missing_tools)}")
        if self.invalid_tools:
            rendered = ", ".join(
                f"{name} ({reason})" for name, reason in self.invalid_tools.items()
            )
            details.append(f"invalid tools: {rendered}")
        super().__init__(
            "reliable_plan",
            "planner tool preflight failed; " + "; ".join(details),
        )


def is_reliable_plan_planner(
    *, node_kind: str | None, node_payload: Mapping[str, Any] | None
) -> bool:
    """Return whether this is a bounded-horizon reliable-plan planner.

    Failure gap planners inherit the reliable-plan provenance carrier, but use
    the correction tool contract for their role. Requiring the four horizon
    construction macros from those nodes makes a valid correction impossible:
    the role-scoped catalog intentionally exposes ``create_corrective_region``
    instead. Root and successor planners retain the strict four-tool preflight.
    """
    payload = node_payload or {}
    return (
        node_kind == "planner"
        and payload.get("role") != "gap_planner"
        and isinstance(payload.get("reliable_plan_skeleton_id"), str)
    )


def resolve_graph_planner_tools(
    *,
    node_kind: str,
    node_role: str | None,
    available_tools: Sequence[str] | None,
) -> tuple[str, ...]:
    """Resolve explicit tools within node authorization in canonical order.

    An omitted routine allowlist preserves historical contract-default exposure.
    An explicit allowlist can only narrow that contract; it can never authorize
    a tool that the node contract does not already permit.
    """
    authorized = DEFAULT_NODE_CONTRACTS.allowed_tools_for(node_kind, node_role)
    requested = authorized if available_tools is None else frozenset(available_tools)
    return tuple(
        name for name in GRAPH_PLANNER_TOOL_ORDER if name in authorized and name in requested
    )


def resolve_dispatch_tools(
    *,
    node_kind: str,
    node_role: str | None,
    available_tools: Sequence[str] | None,
) -> tuple[str, ...]:
    """Resolve graph tools while preserving runner-specific optional tool names."""
    graph_tools = resolve_graph_planner_tools(
        node_kind=node_kind,
        node_role=node_role,
        available_tools=available_tools,
    )
    if available_tools is None:
        return graph_tools
    extras = tuple(
        dict.fromkeys(name for name in available_tools if name not in GRAPH_PLANNER_TOOL_ORDER)
    )
    return (*extras, *graph_tools)


def validate_reliable_plan_tool_names(tool_names: Sequence[str]) -> None:
    """Fail closed when a resolved reliable-plan catalog omits a macro."""
    exposed = frozenset(tool_names)
    missing = tuple(name for name in RELIABLE_PLAN_REQUIRED_TOOL_NAMES if name not in exposed)
    if missing:
        raise ReliablePlanToolPreflightError(missing_tools=missing)


def validate_reliable_plan_tool_specs(specs: Sequence[Mapping[str, Any]]) -> None:
    """Validate required concrete runner definitions and their JSON Schemas."""
    by_name: dict[str, Mapping[str, Any]] = {}
    for spec in specs:
        name = spec.get("name")
        if isinstance(name, str):
            by_name[name] = spec
    missing = tuple(name for name in RELIABLE_PLAN_REQUIRED_TOOL_NAMES if name not in by_name)
    invalid: dict[str, str] = {}
    for name in RELIABLE_PLAN_REQUIRED_TOOL_NAMES:
        spec = by_name.get(name)
        if spec is None:
            continue
        raw_schema = spec.get("inputSchema")
        if not isinstance(raw_schema, dict):
            invalid[name] = "inputSchema must be an object"
            continue
        schema = cast(dict[str, Any], raw_schema)
        if schema.get("type") != "object":
            invalid[name] = "inputSchema root type must be object"
            continue
        raw_properties = schema.get("properties")
        raw_required = schema.get("required")
        if not isinstance(raw_properties, dict):
            invalid[name] = "inputSchema properties must be an object"
            continue
        if not isinstance(raw_required, list):
            invalid[name] = "inputSchema required must be a string array"
            continue
        raw_required_values = cast(list[object], raw_required)
        if not all(isinstance(field, str) for field in raw_required_values):
            invalid[name] = "inputSchema required must be a string array"
            continue
        properties_map = cast(dict[str, Any], raw_properties)
        required_fields = cast(list[str], raw_required_values)
        properties = frozenset(properties_map)
        required = frozenset(required_fields)
        dangling_required = required - properties
        missing_required = _RELIABLE_PLAN_REQUIRED_SCHEMA_FIELDS[name] - required
        if dangling_required:
            invalid[name] = "required fields absent from properties: " + ", ".join(
                sorted(dangling_required)
            )
            continue
        if missing_required:
            invalid[name] = "missing required fields: " + ", ".join(sorted(missing_required))
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            invalid[name] = exc.message
    if missing or invalid:
        raise ReliablePlanToolPreflightError(missing_tools=missing, invalid_tools=invalid)
