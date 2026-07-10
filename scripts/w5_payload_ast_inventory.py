#!/usr/bin/env python3
"""Deterministic AST inventory for the W5 strict payload migration.

This module discovers syntax and symbol routing only.  It deliberately does not
describe payload fields or define any runtime schema.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


BASELINE_EVENT_NAMES = frozenset(
    {
        "agent_died",
        "agent_dispatch_requested",
        "appeal_opened",
        "approval_decision_recorded",
        "authority_decision_recorded",
        "callback_accepted",
        "callback_duplicate_returned",
        "callback_rejected_conflict",
        "callback_rejected_stale",
        "cleanup_applied",
        "cleanup_requested",
        "command_rejected",
        "dead_input_detected",
        "edge_created",
        "file_state_accepted",
        "file_state_rejected",
        "gatekeeper_cost_recorded",
        "gatekeeper_verdict_recorded",
        "graph_patch_accepted",
        "graph_patch_rejected",
        "heartbeat_recorded",
        "input_bound",
        "lease_expired",
        "lease_granted",
        "lease_released",
        "lease_renewed",
        "lease_revoked",
        "node_authority_changed",
        "node_created",
        "node_deferred",
        "node_ready",
        "node_retired",
        "node_state_changed",
        "output_record_accepted",
        "oversight_decision_recorded",
        "plan_region_marked_suspect",
        "requirement_revision_recorded",
        "revision_created",
        "run_lifecycle_changed",
        "runtime_retry_scheduled",
        "session_state_changed",
        "support_evidence_recorded",
        "verification_failed",
        "verification_passed",
    }
)

BASELINE_COMMAND_NAMES = (
    "accept_run",
    "start",
    "pause",
    "resume",
    "cancel",
    "complete",
    "fail",
    "seed_compiled_events",
    "submit_callback",
    "submit_patch",
    "schedule_tick",
    "reconcile",
    "acknowledge_start",
    "agent_died",
    "record_heartbeat",
    "raise_appeal",
    "record_decision",
    "record_gatekeeper_verdicts",
    "record_requirement_revision",
    "record_support_evidence",
    "evaluate_join",
    "evaluate_final_gate",
    "record_cleanup_applied",
)

ALLOWLIST_NAMES = frozenset(
    {
        "GRAPH_PROJECTION_PAYLOAD_FIELDS",
        "LIGHT_GRAPH_PAYLOAD_FIELDS",
        "SUMMARY_REBUILD_PAYLOAD_FIELDS",
        "NODE_DETAIL_PAYLOAD_FIELDS",
    }
)

DOMAIN_EVENT_NAMES: dict[str, frozenset[str]] = {
    "vertical_slice": frozenset({"heartbeat_recorded"}),
    "lifecycle": frozenset(
        {
            "run_lifecycle_changed",
            "command_rejected",
            "callback_accepted",
            "callback_rejected_stale",
            "callback_rejected_conflict",
            "callback_duplicate_returned",
            "runtime_retry_scheduled",
            "heartbeat_recorded",
            "agent_died",
            "agent_dispatch_requested",
        }
    ),
}

DOMAIN_COMMAND_NAMES: dict[str, frozenset[str]] = {
    "vertical_slice": frozenset({"record_heartbeat"}),
    "lifecycle": frozenset(
        {
            "accept_run",
            "start",
            "pause",
            "resume",
            "cancel",
            "complete",
            "fail",
            "record_heartbeat",
            "agent_died",
            "acknowledge_start",
            "submit_callback",
        }
    ),
}

DOMAIN_COMPATIBILITY_MODEL_NAMES: dict[str, frozenset[str]] = {
    "vertical_slice": frozenset({"HeartbeatRecordedPayload", "LifecycleEventPayloadBase"}),
    "lifecycle": frozenset({"HeartbeatRecordedPayload", "LifecycleEventPayloadBase"}),
}


@dataclass(frozen=True, order=True)
class SourceSite:
    path: str
    line: int
    column: int


@dataclass(frozen=True, order=True)
class DynamicSite(SourceSite):
    expression: str
    classification: str = "unresolved"
    resolved_values: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class RawPayloadRead(SourceSite):
    field: str
    expression: str


@dataclass(frozen=True, order=True)
class PayloadModel(SourceSite):
    name: str
    bases: tuple[str, ...]
    declared_fields: tuple[str, ...]
    configuration: tuple[str, ...]
    before_validators: tuple[str, ...]


@dataclass(frozen=True, order=True)
class CommandHandler(SourceSite):
    command_name: str
    handler_expression: str
    payload_annotation: str | None


@dataclass(frozen=True, order=True)
class NamedSite(SourceSite):
    name: str


@dataclass(frozen=True)
class DomainInventory:
    """A deterministic domain-filtered view of an inventory report."""

    domain: str
    event_names: tuple[str, ...]
    command_names: tuple[str, ...]
    raw_producers: tuple[SourceSite | DynamicSite, ...]
    raw_handler_boundaries: tuple[CommandHandler, ...]
    compatibility_models: tuple[PayloadModel, ...]
    allowlists: tuple[NamedSite, ...]
    partial_payload_consumers: tuple[SourceSite, ...]

    @property
    def is_clean(self) -> bool:
        return not (
            self.raw_producers
            or self.raw_handler_boundaries
            or self.compatibility_models
            or self.allowlists
            or self.partial_payload_consumers
        )

    def remaining_diagnostics(self) -> tuple[str, ...]:
        diagnostics: list[str] = []
        diagnostics.extend(
            f"raw producer: {site.path}:{site.line}:{site.column}: "
            f"{getattr(site, 'name', getattr(site, 'expression', 'event construction'))}"
            for site in self.raw_producers
        )
        diagnostics.extend(
            f"raw handler boundary: {site.path}:{site.line}:{site.column}: "
            f"{site.command_name} -> {site.handler_expression} ({site.payload_annotation})"
            for site in self.raw_handler_boundaries
        )
        diagnostics.extend(
            f"compatibility model: {site.path}:{site.line}:{site.column}: {site.name}"
            for site in self.compatibility_models
        )
        diagnostics.extend(
            f"allowlist: {site.path}:{site.line}:{site.column}: {site.name}"
            for site in self.allowlists
        )
        diagnostics.extend(
            f"partial payload consumer: {site.path}:{site.line}:{site.column}: "
            "allowlist-based extraction"
            for site in self.partial_payload_consumers
        )
        return tuple(diagnostics)


@dataclass(frozen=True)
class InventoryReport:
    literal_event_names: frozenset[str]
    literal_event_sites: tuple[NamedSite, ...]
    nonproduction_event_sites: tuple[NamedSite | DynamicSite, ...]
    dynamic_event_sites: tuple[DynamicSite, ...]
    command_names: tuple[str, ...]
    dynamic_command_sites: tuple[DynamicSite, ...]
    raw_payload_reads: tuple[RawPayloadRead, ...]
    payload_models: tuple[PayloadModel, ...]
    command_handlers: tuple[CommandHandler, ...]
    allowlists: tuple[NamedSite, ...]
    partial_payload_consumers: tuple[SourceSite, ...]

    @property
    def produced_event_names(self) -> frozenset[str]:
        fixture_literals = {
            site.name for site in self.nonproduction_event_sites if isinstance(site, NamedSite)
        }
        resolved = {
            name
            for site in self.dynamic_event_sites
            if site.classification != "scenario_fixture"
            for name in site.resolved_values
        }
        return (self.literal_event_names - fixture_literals) | resolved

    def for_domain(self, domain: str) -> DomainInventory:
        needle = domain.casefold()
        domain_events = DOMAIN_EVENT_NAMES.get(needle)
        domain_commands = DOMAIN_COMMAND_NAMES.get(needle)
        domain_models = DOMAIN_COMPATIBILITY_MODEL_NAMES.get(needle, frozenset())
        if needle == "vertical_slice" and not any(
            model.name == "HeartbeatRecordedPayload"
            and ("LifecycleEventPayloadBase" in model.bases or model.before_validators)
            for model in self.payload_models
        ):
            domain_models = domain_models - {"LifecycleEventPayloadBase"}

        def relevant(value: Any) -> bool:
            return needle in str(value).casefold()

        literal_sites = (
            tuple(
                site
                for site in self.literal_event_sites
                if site.name in domain_events
                if domain_events is not None
            )
            if domain_events is not None
            else tuple(site for site in self.literal_event_sites if relevant(site))
        )
        dynamic_sites = (
            tuple(
                site
                for site in self.dynamic_event_sites
                if domain_events is not None and domain_events.intersection(site.resolved_values)
            )
            if domain_events is not None
            else tuple(site for site in self.dynamic_event_sites if relevant(site))
        )
        handlers = tuple(
            site
            for site in self.command_handlers
            if (
                site.command_name in domain_commands
                if domain_commands is not None
                else relevant(site)
            )
            and (
                site.payload_annotation is None
                or "dict[" in site.payload_annotation
                or "Any" in site.payload_annotation
            )
        )
        models = tuple(
            site
            for site in self.payload_models
            if (
                site.name in domain_models
                if needle in DOMAIN_COMPATIBILITY_MODEL_NAMES
                else relevant(site)
            )
            and (
                site.name == "LifecycleEventPayloadBase"
                or site.before_validators
                or any(
                    "extra='ignore'" in config or 'extra="ignore"' in config
                    for config in site.configuration
                )
                or any(
                    base in {"GraphEventPayloadBase", "LifecycleEventPayloadBase"}
                    for base in site.bases
                )
            )
        )
        allowlists = tuple(site for site in self.allowlists if relevant(site))
        partial_consumers = tuple(site for site in self.partial_payload_consumers if relevant(site))
        event_names = tuple(
            sorted(
                {site.name for site in literal_sites}
                | {name for site in dynamic_sites for name in site.resolved_values}
            )
        )
        command_names = tuple(
            sorted(
                site.command_name
                for site in self.command_handlers
                if (
                    site.command_name in domain_commands
                    if domain_commands is not None
                    else relevant(site.command_name)
                )
            )
        )
        return DomainInventory(
            domain=domain,
            event_names=event_names,
            command_names=command_names,
            raw_producers=tuple(
                sorted(
                    (
                        *literal_sites,
                        *(
                            site
                            for site in dynamic_sites
                            if site.classification
                            not in {"typed_specification", "unconverted_bridge"}
                        ),
                    ),
                    key=lambda site: (site.path, site.line, site.column),
                )
            ),
            raw_handler_boundaries=handlers,
            compatibility_models=models,
            allowlists=allowlists,
            partial_payload_consumers=partial_consumers,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "literal_event_names": sorted(self.literal_event_names),
            "produced_event_names": sorted(self.produced_event_names),
            "literal_event_sites": _records(self.literal_event_sites),
            "nonproduction_event_sites": _records(self.nonproduction_event_sites),
            "dynamic_event_sites": _records(self.dynamic_event_sites),
            "command_names": list(self.command_names),
            "dynamic_command_sites": _records(self.dynamic_command_sites),
            "raw_payload_reads": _records(self.raw_payload_reads),
            "payload_models": _records(self.payload_models),
            "command_handlers": _records(self.command_handlers),
            "allowlists": _records(self.allowlists),
            "partial_payload_consumers": _records(self.partial_payload_consumers),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def to_text(self) -> str:
        lines = [
            f"Produced event names ({len(self.produced_event_names)}):",
            *[f"  {name}" for name in sorted(self.produced_event_names)],
            f"Command names ({len(self.command_names)}):",
            *[f"  {name}" for name in self.command_names],
            f"Dynamic event sites ({len(self.dynamic_event_sites)}):",
        ]
        lines.extend(
            f"  {site.path}:{site.line}:{site.column} {site.expression} [{site.classification}]"
            for site in self.dynamic_event_sites
        )
        return "\n".join(lines) + "\n"


def _records(records: Iterable[Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for record in records:
        item = asdict(record)
        for key, value in item.items():
            if isinstance(value, tuple):
                item[key] = list(value)
        values.append(item)
    return values


@dataclass
class _ParsedFile:
    path: Path
    tree: ast.Module
    parents: dict[ast.AST, ast.AST]
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    calls: dict[str, list[ast.Call]]
    imports: dict[str, str]


def _parse(path: Path) -> _ParsedFile:
    tree = ast.parse(path.read_text(), filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    calls: dict[str, list[ast.Call]] = {}
    imports: dict[str, str] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[parent.name] = parent
        if isinstance(parent, ast.ImportFrom) and parent.module is not None:
            for alias in parent.names:
                imports[alias.asname or alias.name] = f"{parent.module}.{alias.name}"
        if isinstance(parent, ast.Import):
            for alias in parent.names:
                imports[alias.asname or alias.name.split(".")[0]] = alias.name
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            imports.pop(node.name, None)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            key = _scoped_call_key(node, parents)
            if key is not None:
                calls.setdefault(key, []).append(node)
    return _ParsedFile(path, tree, parents, functions, calls, imports)


def _enclosing_classes(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> tuple[str, ...]:
    classes: list[str] = []
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.ClassDef):
            classes.append(current.name)
    return tuple(reversed(classes))


def _scoped_call_key(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if not isinstance(call.func, ast.Attribute):
        return None
    if isinstance(call.func.value, ast.Name):
        if call.func.value.id in {"self", "cls"}:
            classes = _enclosing_classes(call, parents)
            return ".".join((*classes, call.func.attr))
        return f"{call.func.value.id}.{call.func.attr}"
    return call.func.attr


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _owner_function(
    node: ast.AST, parsed: _ParsedFile
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = node
    while current in parsed.parents:
        current = parsed.parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _literal_strings(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return tuple(sorted({value for item in node.elts for value in _literal_strings(item)}))
    if isinstance(node, ast.IfExp):
        return tuple(sorted(set(_literal_strings(node.body) + _literal_strings(node.orelse))))
    return ()


def _resolve_parameter(
    expression: ast.expr,
    owner: ast.FunctionDef | ast.AsyncFunctionDef | None,
    all_calls: dict[str, list[ast.Call]],
    owner_key: str,
) -> tuple[str, ...]:
    direct = _literal_strings(expression)
    if direct:
        return direct
    if owner is None or not isinstance(expression, ast.Name):
        return ()
    assigned_values: set[str] = set()
    for candidate in ast.walk(owner):
        if isinstance(candidate, (ast.Assign, ast.AnnAssign)):
            targets = candidate.targets if isinstance(candidate, ast.Assign) else [candidate.target]
            if (
                any(
                    isinstance(target, ast.Name) and target.id == expression.id
                    for target in targets
                )
                and candidate.value is not None
            ):
                assigned_values.update(_literal_strings(candidate.value))
    if assigned_values:
        return tuple(sorted(assigned_values))
    parameters = [*owner.args.posonlyargs, *owner.args.args]
    parameter_names = [parameter.arg for parameter in parameters]
    if expression.id not in parameter_names:
        return ()
    index = parameter_names.index(expression.id)
    if parameter_names and parameter_names[0] in {"self", "cls"}:
        index -= 1
    values: set[str] = set()
    for call in all_calls.get(owner_key, []):
        argument: ast.expr | None = call.args[index] if index < len(call.args) else None
        if argument is None:
            argument = next((kw.value for kw in call.keywords if kw.arg == expression.id), None)
        if argument is not None:
            values.update(_literal_strings(argument))
    return tuple(sorted(values))


def _site(path: Path, node: ast.AST) -> SourceSite:
    located = node.target if isinstance(node, ast.comprehension) else node
    return SourceSite(str(path), located.lineno, located.col_offset)


def _qualified_call_name(node: ast.expr, imports: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return imports.get(node.id)
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and current.id in imports:
            return ".".join((imports[current.id], *reversed(parts)))
    return None


def _event_argument(call: ast.Call, parsed: _ParsedFile) -> ast.expr | None:
    name = _call_name(call.func)
    qualified_name = _qualified_call_name(call.func, parsed.imports)
    if qualified_name in {
        "orchestrator.graph.EventEnvelope",
        "orchestrator.graph.models.EventEnvelope",
    }:
        keyword = next((kw.value for kw in call.keywords if kw.arg == "event_type"), None)
        if keyword is not None:
            return keyword
        return call.args[3] if len(call.args) > 3 else None
    if name == "make_event":
        return call.args[0] if call.args else None
    return None


def _dynamic_classification(
    call: ast.Call,
    expression: ast.expr,
    parsed: _ParsedFile,
) -> tuple[str, tuple[str, ...]]:
    owner = _owner_function(call, parsed)
    owner_name = owner.name if owner is not None else ""
    if owner_name in {"make_event", "event_factory"}:
        return "generic_factory_definition", ()
    owner_key = (
        owner_name
        if owner is None
        else ".".join((*_enclosing_classes(owner, parsed.parents), owner_name))
    )
    values = _resolve_parameter(expression, owner, parsed.calls, owner_key)
    if values:
        return "resolved_finite", values
    if _call_name(call.func) == "EventEnvelope":
        reads_stored_event_type = any(
            isinstance(candidate, ast.Subscript)
            and _literal_strings(candidate.slice) == ("event_type",)
            for candidate in ast.walk(expression)
        )
        if reads_stored_event_type or owner_name in {
            "read",
            "read_from",
            "load",
            "hydrate",
        }:
            return "stored_event_hydration", ()
    return "unresolved", ()


def _decorator_is_before_validator(decorator: ast.expr) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    if _call_name(decorator.func) not in {"model_validator", "root_validator"}:
        return False
    return any(
        keyword.arg in {"mode", "pre"}
        and (keyword.value.value == "before" if isinstance(keyword.value, ast.Constant) else False)
        for keyword in decorator.keywords
    ) or any(
        keyword.arg == "pre"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in decorator.keywords
    )


def _payload_model(path: Path, node: ast.ClassDef) -> PayloadModel | None:
    bases = tuple(ast.unparse(base) for base in node.bases)
    if not (node.name.endswith("Payload") or any("BaseModel" in base for base in bases)):
        return None
    fields = tuple(
        child.target.id
        for child in node.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    )
    configurations = tuple(
        ast.unparse(child.value)
        for child in node.body
        if isinstance(child, (ast.Assign, ast.AnnAssign))
        and any(
            target.id == "model_config"
            for target in (child.targets if isinstance(child, ast.Assign) else [child.target])
            if isinstance(target, ast.Name)
        )
        and child.value is not None
    )
    validators = tuple(
        child.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_decorator_is_before_validator(item) for item in child.decorator_list)
    )
    return PayloadModel(
        str(path),
        node.lineno,
        node.col_offset,
        node.name,
        bases,
        fields,
        configurations,
        validators,
    )


def _payload_base(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "payload"


def _raw_payload_read(path: Path, node: ast.AST) -> RawPayloadRead | None:
    if isinstance(node, ast.Subscript) and _payload_base(node.value):
        fields = _literal_strings(node.slice)
        if fields:
            return RawPayloadRead(
                str(path), node.lineno, node.col_offset, fields[0], ast.unparse(node)
            )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _payload_base(node.func.value)
        and node.args
    ):
        fields = _literal_strings(node.args[0])
        if fields:
            return RawPayloadRead(
                str(path), node.lineno, node.col_offset, fields[0], ast.unparse(node)
            )
    return None


def _handler_annotation(
    handler: ast.expr, functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
) -> str | None:
    name = _call_name(handler)
    function = functions.get(name or "")
    if function is None:
        return None
    for argument in function.args.args:
        if argument.arg in {"payload", "command"} and argument.annotation is not None:
            return ast.unparse(argument.annotation)
    return None


def scan_graph_payload_architecture(paths: Sequence[Path]) -> InventoryReport:
    """Scan Python files and return a stable structural payload inventory."""

    expanded: list[Path] = []
    for path in paths:
        expanded.extend(path.rglob("*.py") if path.is_dir() else [path])
    parsed_files = [_parse(path) for path in sorted(set(expanded), key=lambda p: str(p))]
    literal_sites: list[NamedSite] = []
    nonproduction_sites: list[NamedSite | DynamicSite] = []
    dynamic_sites: list[DynamicSite] = []
    dynamic_commands: list[DynamicSite] = []
    raw_reads: list[RawPayloadRead] = []
    models: list[PayloadModel] = []
    handlers: list[CommandHandler] = []
    allowlists: list[NamedSite] = []
    partial_consumers: list[SourceSite] = []
    command_names: set[str] = set()

    for parsed in parsed_files:
        for node in ast.walk(parsed.tree):
            if isinstance(node, ast.Call):
                specification_name = next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "name"),
                    None,
                )
                if _call_name(node.func) == "EventSpecification" and specification_name:
                    values = _literal_strings(specification_name)
                    if values:
                        dynamic_sites.append(
                            DynamicSite(
                                str(parsed.path),
                                node.lineno,
                                node.col_offset,
                                ast.unparse(specification_name),
                                "typed_specification",
                                values,
                            )
                        )
                elif _call_name(node.func) == "CommandSpecification" and specification_name:
                    command_names.update(_literal_strings(specification_name))
                if _call_name(node.func) == "emit_unconverted_event" and node.args:
                    values = _literal_strings(node.args[0])
                    if values:
                        dynamic_sites.append(
                            DynamicSite(
                                str(parsed.path),
                                node.lineno,
                                node.col_offset,
                                ast.unparse(node.args[0]),
                                "unconverted_bridge",
                                values,
                            )
                        )
                argument = _event_argument(node, parsed)
                if argument is not None:
                    values = _literal_strings(argument)
                    if values:
                        new_sites = [
                            NamedSite(str(parsed.path), node.lineno, node.col_offset, value)
                            for value in values
                        ]
                        literal_sites.extend(new_sites)
                        if parsed.path.name == "scenario.py":
                            nonproduction_sites.extend(new_sites)
                    else:
                        classification, resolved = _dynamic_classification(node, argument, parsed)
                        dynamic_site = DynamicSite(
                            str(parsed.path),
                            node.lineno,
                            node.col_offset,
                            ast.unparse(argument),
                            (
                                "scenario_fixture"
                                if parsed.path.name == "scenario.py"
                                else classification
                            ),
                            resolved,
                        )
                        dynamic_sites.append(dynamic_site)
                        if parsed.path.name == "scenario.py":
                            nonproduction_sites.append(dynamic_site)
                read = _raw_payload_read(parsed.path, node)
                if read is not None:
                    raw_reads.append(read)
            elif isinstance(node, ast.Subscript):
                read = _raw_payload_read(parsed.path, node)
                if read is not None:
                    raw_reads.append(read)
            elif isinstance(node, ast.ClassDef):
                model = _payload_model(parsed.path, node)
                if model is not None:
                    models.append(model)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                for name in names:
                    if name in ALLOWLIST_NAMES:
                        allowlists.append(
                            NamedSite(str(parsed.path), node.lineno, node.col_offset, name)
                        )
                value = node.value
                if "_UNCONVERTED_W5_BRIDGE" in names and isinstance(value, ast.Dict):
                    for key in value.keys:
                        if key is not None:
                            command_names.update(_literal_strings(key))
                if "COMMAND_HANDLERS" in names and isinstance(value, ast.Dict):
                    for key, handler in zip(value.keys, value.values, strict=True):
                        values = _literal_strings(key) if key is not None else ()
                        if values:
                            for command_name in values:
                                command_names.add(command_name)
                                handlers.append(
                                    CommandHandler(
                                        str(parsed.path),
                                        handler.lineno,
                                        handler.col_offset,
                                        command_name,
                                        ast.unparse(handler),
                                        _handler_annotation(handler, parsed.functions),
                                    )
                                )
                        elif key is not None:
                            dynamic_commands.append(
                                DynamicSite(
                                    str(parsed.path),
                                    key.lineno,
                                    key.col_offset,
                                    ast.unparse(key),
                                )
                            )
            if isinstance(node, ast.comprehension) and any(
                isinstance(child, ast.Name) and child.id in ALLOWLIST_NAMES
                for child in ast.walk(node)
            ):
                partial_consumers.append(_site(parsed.path, node))

    literal_names = frozenset(site.name for site in literal_sites)
    return InventoryReport(
        literal_event_names=literal_names,
        literal_event_sites=tuple(sorted(literal_sites)),
        nonproduction_event_sites=tuple(
            sorted(
                nonproduction_sites,
                key=lambda site: (site.path, site.line, site.column),
            )
        ),
        dynamic_event_sites=tuple(sorted(dynamic_sites)),
        command_names=tuple(sorted(command_names)),
        dynamic_command_sites=tuple(sorted(dynamic_commands)),
        raw_payload_reads=tuple(sorted(set(raw_reads))),
        payload_models=tuple(sorted(models)),
        command_handlers=tuple(sorted(handlers)),
        allowlists=tuple(sorted(allowlists)),
        partial_payload_consumers=tuple(sorted(set(partial_consumers))),
    )


def _default_paths() -> tuple[Path, ...]:
    return (Path("src/orchestrator/graph"), Path("src/orchestrator/graph_runtime"))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--check-domain")
    parser.add_argument("paths", nargs="*", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = scan_graph_payload_architecture(args.paths or _default_paths())
    rendered = report.to_json() if args.format == "json" else report.to_text()
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.write_text(rendered)

    errors: list[str] = []
    if args.check_baseline:
        missing_events = sorted(BASELINE_EVENT_NAMES - report.produced_event_names)
        extra_events = sorted(report.produced_event_names - BASELINE_EVENT_NAMES)
        missing_commands = sorted(set(BASELINE_COMMAND_NAMES) - set(report.command_names))
        extra_commands = sorted(set(report.command_names) - set(BASELINE_COMMAND_NAMES))
        if missing_events or extra_events:
            errors.append(
                f"event baseline mismatch: missing={missing_events}, extra={extra_events}"
            )
        if missing_commands or extra_commands:
            errors.append(
                f"command baseline mismatch: missing={missing_commands}, extra={extra_commands}"
            )
        unclassified = [
            f"{site.path}:{site.line}:{site.column} {site.expression}"
            for site in report.dynamic_event_sites
            if site.classification == "unresolved"
        ]
        if unclassified:
            errors.append(f"unclassified dynamic event sites: {unclassified}")
    if args.check_domain:
        domain = report.for_domain(args.check_domain)
        if not domain.is_clean:
            errors.extend(domain.remaining_diagnostics())
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
