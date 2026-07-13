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
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence, cast, get_args

# Direct script execution places ``scripts/`` rather than the repository root
# on sys.path, so make the sibling checker importable in both supported modes.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_graph_payload_architecture import (
    DOMAIN_COMMAND_NAMES as ARCHITECTURE_DOMAIN_COMMAND_NAMES,
    DOMAIN_EVENT_NAMES as ARCHITECTURE_DOMAIN_EVENT_NAMES,
    ArchitectureDiagnostic,
    check_paths,
)


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

DOMAIN_EVENT_NAMES.update(ARCHITECTURE_DOMAIN_EVENT_NAMES)
DOMAIN_COMMAND_NAMES.update(ARCHITECTURE_DOMAIN_COMMAND_NAMES)
DOMAIN_EVENT_NAMES["catalog_cutover"] = BASELINE_EVENT_NAMES
DOMAIN_COMMAND_NAMES["catalog_cutover"] = frozenset(BASELINE_COMMAND_NAMES)

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


@dataclass(frozen=True, order=True)
class CatalogCutoverSite(SourceSite):
    classification: str
    expression: str


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
    catalog_cutover_sites: tuple[CatalogCutoverSite, ...] = ()
    architecture_diagnostics: tuple[ArchitectureDiagnostic, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not (
            self.raw_producers
            or self.raw_handler_boundaries
            or self.compatibility_models
            or self.allowlists
            or self.partial_payload_consumers
            or self.catalog_cutover_sites
            or self.architecture_diagnostics
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
        diagnostics.extend(
            f"catalog cutover: {site.path}:{site.line}:{site.column}: "
            f"{site.classification} ({site.expression})"
            for site in self.catalog_cutover_sites
        )
        diagnostics.extend(site.render() for site in self.architecture_diagnostics)
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
    catalog_cutover_sites: tuple[CatalogCutoverSite, ...] = ()
    scanned_paths: tuple[Path, ...] = ()

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
        typed_event_names = {
            name
            for site in self.dynamic_event_sites
            if site.classification == "typed_specification"
            for name in site.resolved_values
        }
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
        catalog_cutover_sites = self.catalog_cutover_sites if needle == "catalog_cutover" else ()
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
                            if site.classification != "typed_specification"
                            and (
                                site.classification
                                not in {
                                    "unconverted_bridge",
                                    "unconverted_event_registry",
                                }
                                or bool(typed_event_names.intersection(site.resolved_values))
                            )
                        ),
                    ),
                    key=lambda site: (site.path, site.line, site.column),
                )
            ),
            raw_handler_boundaries=handlers,
            compatibility_models=models,
            allowlists=allowlists,
            partial_payload_consumers=partial_consumers,
            catalog_cutover_sites=catalog_cutover_sites,
            architecture_diagnostics=check_paths(self.scanned_paths, domain=domain),
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
            "catalog_cutover_sites": _records(self.catalog_cutover_sites),
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


_STRICT_SPEC_EVENT_NAMES = {
    "LEASE_GRANTED": "lease_granted",
    "LEASE_RENEWED": "lease_renewed",
    "LEASE_RELEASED": "lease_released",
    "LEASE_REVOKED": "lease_revoked",
    "LEASE_EXPIRED": "lease_expired",
    "GRAPH_PATCH_ACCEPTED": "graph_patch_accepted",
    "GRAPH_PATCH_REJECTED": "graph_patch_rejected",
}


def _specification_name_argument(call: ast.Call) -> ast.expr | None:
    keyword = next((item.value for item in call.keywords if item.arg == "name"), None)
    if keyword is not None:
        return keyword
    return call.args[0] if call.args else None


def _dynamic_classification(
    call: ast.Call,
    expression: ast.expr,
    parsed: _ParsedFile,
) -> tuple[str, tuple[str, ...]]:
    owner = _owner_function(call, parsed)
    owner_name = owner.name if owner is not None else ""
    if (
        isinstance(expression, ast.Attribute)
        and expression.attr == "name"
        and isinstance(expression.value, ast.Name)
        and expression.value.id == "specification"
    ):
        return "typed_specification_dispatch", ()
    if (
        isinstance(expression, ast.Attribute)
        and expression.attr == "event_type"
        and isinstance(expression.value, ast.Attribute)
        and expression.value.attr == "metadata"
        and isinstance(expression.value.value, ast.Name)
        and expression.value.value.id == "event"
        and owner_name != "_to_legacy_envelope"
    ):
        return "typed_specification_dispatch", ()
    if (
        isinstance(expression, ast.Attribute)
        and expression.attr == "event_type"
        and isinstance(expression.value, ast.Name)
        and expression.value.id == "metadata"
        and owner_name.startswith("reduce_typed_")
    ):
        return "typed_specification_dispatch", ()
    if owner_name == "typed_topology_event":
        return "typed_specification", _resolve_parameter(
            expression, owner, parsed.calls, owner_name
        )
    if owner_name == "_to_legacy_envelope":
        return "typed_event_serialization", ()
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


def _catalog_cutover_sites(parsed: _ParsedFile) -> tuple[CatalogCutoverSite, ...]:
    """Independently inventory live catalog fallback and central spec defects."""

    sites: list[CatalogCutoverSite] = []
    central_commands = parsed.path.as_posix().endswith(
        "src/orchestrator/graph/commands/__init__.py"
    )
    for node in ast.walk(parsed.tree):
        if (
            isinstance(node, ast.Call)
            and _is_apply_command_call(node)
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "projection"
            and any(keyword.arg == "catalog" for keyword in node.keywords)
            and not _inside_reduce_legacy_event(node, parsed)
        ):
            sites.append(
                CatalogCutoverSite(
                    str(parsed.path),
                    node.lineno,
                    node.col_offset,
                    "legacy_apply_command",
                    ast.unparse(node),
                )
            )
        if (
            central_commands
            and isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "COMMAND_SPECIFICATIONS"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
            and isinstance(node.value, ast.Tuple)
            and node.value.elts
            and all(isinstance(element, ast.Name) for element in node.value.elts)
        ):
            sites.append(
                CatalogCutoverSite(
                    str(parsed.path),
                    node.lineno,
                    node.col_offset,
                    "central_command_spec_enumeration",
                    ast.unparse(node.value),
                )
            )
        if not isinstance(node, ast.If) or _inside_reduce_legacy_event(node, parsed):
            continue
        if _catalog_membership_test(node.test) and any(
            _is_apply_command_call(child) for child in ast.walk(node)
        ):
            sites.append(
                CatalogCutoverSite(
                    str(parsed.path),
                    node.lineno,
                    node.col_offset,
                    "catalog_membership_fallback_dispatch",
                    ast.unparse(node.test),
                )
            )
    return tuple(sites)


def _catalog_membership_test(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.In, ast.NotIn))
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Attribute)
        and node.comparators[0].attr == "command_specs"
    )


def _is_apply_command_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "apply_command"
    )


def _inside_reduce_legacy_event(node: ast.AST, parsed: _ParsedFile) -> bool:
    current = node
    while current in parsed.parents:
        current = parsed.parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name == "reduce_legacy_event"
    return False


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
    catalog_cutover_sites: list[CatalogCutoverSite] = []
    command_names: set[str] = set()
    typed_command_names: set[str] = set()
    bridge_handlers: list[CommandHandler] = []

    for parsed in parsed_files:
        catalog_cutover_sites.extend(_catalog_cutover_sites(parsed))
        for node in ast.walk(parsed.tree):
            if isinstance(node, ast.Call):
                if _call_name(node.func) == "_make_strict_event" and len(node.args) >= 2:
                    specification = node.args[1]
                    if isinstance(specification, ast.Name) and (
                        event_name := _STRICT_SPEC_EVENT_NAMES.get(specification.id)
                    ):
                        dynamic_sites.append(
                            DynamicSite(
                                str(parsed.path),
                                node.lineno,
                                node.col_offset,
                                specification.id,
                                "typed_specification",
                                (event_name,),
                            )
                        )
                    continue
                specification_name = _specification_name_argument(node)
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
                    values = _literal_strings(specification_name)
                    command_names.update(values)
                    typed_command_names.update(values)
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
                if any(name.endswith("_EVENT_PAYLOAD_MODELS") for name in names) and isinstance(
                    value, ast.Dict
                ):
                    for key in value.keys:
                        if key is None:
                            continue
                        values = _literal_strings(key)
                        if values:
                            dynamic_sites.append(
                                DynamicSite(
                                    str(parsed.path),
                                    key.lineno,
                                    key.col_offset,
                                    ast.unparse(key),
                                    "unconverted_event_registry",
                                    values,
                                )
                            )
                if "_UNCONVERTED_W5_BRIDGE" in names and isinstance(value, ast.Dict):
                    for key, handler in zip(value.keys, value.values, strict=True):
                        if key is None:
                            continue
                        values = _literal_strings(key)
                        command_names.update(values)
                        bridge_handlers.extend(
                            CommandHandler(
                                str(parsed.path),
                                handler.lineno,
                                handler.col_offset,
                                command_name,
                                ast.unparse(handler),
                                _handler_annotation(handler, parsed.functions),
                            )
                            for command_name in values
                        )
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

    handlers.extend(
        handler for handler in bridge_handlers if handler.command_name in typed_command_names
    )
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
        catalog_cutover_sites=tuple(sorted(catalog_cutover_sites)),
        scanned_paths=tuple(parsed.path for parsed in parsed_files),
    )


# ---------------------------------------------------------------------------
# Consumer-side scan (W5 Task 3.5 prep tooling)
#
# The producer scan above inventories event construction and reducer routing.
# The consumer scan below finds code that *reads* converted strict payloads
# with a stale shape: flat dict reads of nested record fields, test seeds that
# no longer validate against the catalog specification, and attribute reads
# that are not declared model fields.
# ---------------------------------------------------------------------------

CONSUMER_DOMAIN_EVENT_NAMES: dict[str, frozenset[str]] = {
    "records": frozenset({"output_record_accepted"}),
}

CONSUMER_FAILING_CLASSIFICATIONS = frozenset(
    {"flat_shape_read", "invalid_seed", "unknown_attribute_read"}
)

CONSUMER_REPORT_CLASSIFICATIONS = (
    "flat_shape_read",
    "invalid_seed",
    "unverifiable_seed",
    "unknown_attribute_read",
)

_SEED_FACTORY_NAMES = frozenset({"EventEnvelope", "make_event", "_event"})
_MAX_SNIPPET_LENGTH = 110


class UnknownConsumerDomainError(ValueError):
    """Raised when a consumer scan names a domain with no event table."""


@dataclass(frozen=True, order=True)
class ConsumerSite(SourceSite):
    event: str
    classification: str
    snippet: str


@dataclass(frozen=True)
class ConsumerSchema:
    """Catalog-derived shape facts used to classify consumer-side payload use."""

    event_names: frozenset[str]
    declared_fields: dict[str, frozenset[str]]
    nested_record_fields: dict[str, frozenset[str]]
    payload_class_events: dict[str, str]
    payload_classes: dict[str, Any]


@lru_cache(maxsize=1)
def _cached_catalog() -> Any:
    from orchestrator.graph.catalog import build_graph_catalog

    return build_graph_catalog()


def _payload_model_variants(annotation: Any, base_model: type) -> tuple[type, ...]:
    candidates = get_args(annotation)
    if candidates:
        return tuple(
            variant
            for candidate in candidates
            for variant in _payload_model_variants(candidate, base_model)
        )
    if isinstance(annotation, type) and issubclass(annotation, base_model):
        return (annotation,)
    return ()


@lru_cache(maxsize=1)
def _consumer_schema() -> ConsumerSchema:
    from pydantic import BaseModel

    catalog = _cached_catalog()
    declared: dict[str, frozenset[str]] = {}
    nested: dict[str, frozenset[str]] = {}
    class_events: dict[str, str] = {}
    classes: dict[str, Any] = {}
    for event_name, specification in catalog.event_specs.items():
        payload_type = specification.payload_type
        declared_fields: set[str] = set()
        nested_fields: set[str] = set()
        for field_name, model_field in payload_type.model_fields.items():
            declared_fields.add(field_name)
            if model_field.alias is not None:
                declared_fields.add(model_field.alias)
            for variant in _payload_model_variants(model_field.annotation, BaseModel):
                for nested_name, nested_field in variant.model_fields.items():
                    nested_fields.add(nested_name)
                    if nested_field.alias is not None:
                        nested_fields.add(nested_field.alias)
        declared[event_name] = frozenset(declared_fields)
        nested[event_name] = frozenset(nested_fields)
        class_events.setdefault(payload_type.__name__, event_name)
        classes.setdefault(payload_type.__name__, payload_type)
    return ConsumerSchema(
        event_names=frozenset(catalog.event_specs),
        declared_fields=declared,
        nested_record_fields=nested,
        payload_class_events=class_events,
        payload_classes=classes,
    )


def consumer_domain_event_names(domain: str | None) -> frozenset[str]:
    """Resolve a consumer scan domain to the converted event names it covers."""

    schema = _consumer_schema()
    if domain is None:
        return schema.event_names
    needle = domain.casefold()
    names = CONSUMER_DOMAIN_EVENT_NAMES.get(needle, DOMAIN_EVENT_NAMES.get(needle))
    if names is None:
        raise UnknownConsumerDomainError(domain)
    return frozenset(names) & schema.event_names


def _seed_validation_error(event_name: str, payload: dict[str, Any]) -> str | None:
    """Validate one statically-known seed payload exactly as append would."""

    from datetime import UTC, datetime

    from orchestrator.graph import Actor, ActorKind, EventEnvelope
    from orchestrator.graph_runtime import (
        InvalidGraphEventPayloadError,
        stored_graph_event,
        validate_catalog_event_payload,
    )

    try:
        envelope = EventEnvelope(
            event_id="w5-consumer-scan",
            run_id="w5-consumer-scan",
            position=-1,
            event_type=event_name,
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            payload=payload,
        )
        stored = stored_graph_event(envelope, run_id="w5-consumer-scan", position=1)
        validate_catalog_event_payload(_cached_catalog(), stored)
    except (InvalidGraphEventPayloadError, ValueError, TypeError) as error:
        return str(error).splitlines()[0]
    return None


@dataclass
class _ConsumerScope:
    referenced_events: set[str] = field(default_factory=set)
    payload_reads: list[ast.AST] = field(default_factory=list)
    event_payload_names: set[str] = field(default_factory=set)
    record_dict_names: set[str] = field(default_factory=set)
    typed_variables: dict[str, str] = field(default_factory=dict)
    typed_expressions: dict[str, str] = field(default_factory=dict)
    attribute_reads: list[ast.Attribute] = field(default_factory=list)


def _consumer_payload_base(node: ast.expr, scope: _ConsumerScope) -> bool:
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "payload"
        and isinstance(node.value, ast.Name)
        and node.value.id in {"event", "graph_event"}
    ):
        return True
    if isinstance(node, ast.Name) and node.id in scope.event_payload_names:
        return True
    if isinstance(node, ast.Subscript):
        return (
            _literal_strings(node.slice) == ("payload",)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"event", "graph_event"}
        )
    return False


def _consumer_payload_read(node: ast.AST, scope: _ConsumerScope) -> str | None:
    if isinstance(node, ast.Subscript) and _consumer_payload_base(node.value, scope):
        fields = _literal_strings(node.slice)
        if fields:
            return fields[0]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _consumer_payload_base(node.func.value, scope)
        and node.args
    ):
        fields = _literal_strings(node.args[0])
        if fields:
            return fields[0]
    return None


def _read_base_expression(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Subscript):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.value
    return None


def _is_bare_string_statement(node: ast.Constant, parsed: _ParsedFile) -> bool:
    return isinstance(parsed.parents.get(node), ast.Expr)


def _annotation_class_name(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return None


def _track_isinstance_guard(
    call: ast.Call,
    scope: _ConsumerScope,
    schema: ConsumerSchema,
) -> None:
    if not (isinstance(call.func, ast.Name) and call.func.id == "isinstance"):
        return
    if len(call.args) != 2:
        return
    guarded, class_expr = call.args
    class_exprs = class_expr.elts if isinstance(class_expr, ast.Tuple) else [class_expr]
    for candidate in class_exprs:
        class_name = _annotation_class_name(candidate)
        if class_name is not None and class_name in schema.payload_class_events:
            scope.typed_expressions[ast.unparse(guarded)] = class_name
            if isinstance(guarded, ast.Name):
                scope.typed_variables.setdefault(guarded.id, class_name)


def _model_validate_class_name(value: ast.expr) -> str | None:
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr in {"model_validate", "model_validate_json"}
    ):
        return None
    owner = value.func.value
    if isinstance(owner, ast.Name):
        return owner.id
    if isinstance(owner, ast.Attribute):
        return owner.attr
    return None


def _expression_extracts_record(value: ast.expr) -> bool:
    for child in ast.walk(value):
        if isinstance(child, ast.Attribute) and child.attr in {"record", "model_dump"}:
            return True
        if isinstance(child, ast.Subscript) and _literal_strings(child.slice) == ("record",):
            return True
    return False


def _track_consumer_assignment(
    node: ast.Assign | ast.AnnAssign,
    scope: _ConsumerScope,
    schema: ConsumerSchema,
) -> None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = [target.id for target in targets if isinstance(target, ast.Name)]
    if not names:
        return
    if isinstance(node, ast.AnnAssign):
        class_name = _annotation_class_name(node.annotation)
        if class_name is not None and class_name in schema.payload_class_events:
            for name in names:
                scope.typed_variables[name] = class_name
    value = node.value
    if value is None:
        return
    if _consumer_payload_base(value, scope):
        scope.event_payload_names.update(names)
        return
    class_name = _model_validate_class_name(value)
    if class_name is not None and class_name in schema.payload_class_events:
        for name in names:
            scope.typed_variables[name] = class_name
            scope.record_dict_names.discard(name)
        return
    if _expression_extracts_record(value):
        for name in names:
            scope.record_dict_names.add(name)
            scope.typed_variables.pop(name, None)


def _consumer_snippet(node: ast.AST) -> str:
    text = ast.unparse(node)
    if len(text) > _MAX_SNIPPET_LENGTH:
        return text[: _MAX_SNIPPET_LENGTH - 3] + "..."
    return text


def _consumer_site(
    parsed: _ParsedFile,
    node: ast.AST,
    event_name: str,
    classification: str,
    detail: str | None = None,
) -> ConsumerSite:
    snippet = _consumer_snippet(node)
    if detail:
        snippet = f"{snippet} -- {detail}"
    return ConsumerSite(
        str(parsed.path),
        node.lineno,
        node.col_offset,
        event_name,
        classification,
        snippet,
    )


def _record_wrapping_helper_names(parsed: _ParsedFile) -> frozenset[str]:
    names: set[str] = set()
    for name, function in parsed.functions.items():
        if name not in _SEED_FACTORY_NAMES:
            continue
        for child in ast.walk(function):
            if isinstance(child, ast.Dict) and any(
                key is not None and _literal_strings(key) == ("record",) for key in child.keys
            ):
                names.add(name)
                break
    return frozenset(names)


def _seed_call_parts(
    call: ast.Call,
    factory_name: str,
    schema: ConsumerSchema,
) -> tuple[str | None, ast.expr | None]:
    payload_expr = next((kw.value for kw in call.keywords if kw.arg == "payload"), None)
    if factory_name == "EventEnvelope":
        event_expr = next((kw.value for kw in call.keywords if kw.arg == "event_type"), None)
        if event_expr is None and len(call.args) > 3:
            event_expr = call.args[3]
        event_values = _literal_strings(event_expr) if event_expr is not None else ()
        event_name = event_values[0] if len(event_values) == 1 else None
        return event_name, payload_expr
    event_name = None
    event_index = -1
    for index, argument in enumerate(call.args):
        values = _literal_strings(argument)
        if len(values) == 1 and values[0] in schema.event_names:
            event_name = values[0]
            event_index = index
            break
    if event_name is None:
        return None, payload_expr
    if payload_expr is None:
        remaining = [
            argument
            for argument in call.args[event_index + 1 :]
            if not isinstance(argument, ast.Starred)
        ]
        payload_expr = next(
            (argument for argument in remaining if isinstance(argument, ast.Dict)),
            remaining[0] if remaining else None,
        )
    return event_name, payload_expr


def _uses_explicit_invalid_payload_escape(call: ast.Call, parsed: _ParsedFile) -> bool:
    """Whether a seed is deliberately persisted through the corruption boundary."""

    current: ast.AST = call
    while current in parsed.parents:
        current = parsed.parents[current]
        if not isinstance(current, ast.Call) or _call_name(current.func) != "append_events":
            continue
        return any(
            keyword.arg == "allow_invalid_payloads"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in current.keywords
        )
    return False


def _consumer_seed_site(
    call: ast.Call,
    parsed: _ParsedFile,
    schema: ConsumerSchema,
    requested: frozenset[str],
    wrapping_helpers: frozenset[str],
) -> ConsumerSite | None:
    factory_name = _call_name(call.func)
    if factory_name not in _SEED_FACTORY_NAMES:
        return None
    event_name, payload_expr = _seed_call_parts(call, factory_name, schema)
    if event_name is None or event_name not in requested or payload_expr is None:
        return None
    if _uses_explicit_invalid_payload_escape(call, parsed):
        return None
    try:
        literal = ast.literal_eval(payload_expr)
    except (ValueError, TypeError, SyntaxError):
        return _consumer_site(parsed, call, event_name, "unverifiable_seed")
    if not isinstance(literal, dict):
        return _consumer_site(
            parsed, call, event_name, "invalid_seed", "payload literal is not an object"
        )
    typed_literal = cast(dict[str, Any], literal)
    error = _seed_validation_error(event_name, typed_literal)
    if error is None:
        return None
    if factory_name in wrapping_helpers and "record" not in typed_literal:
        wrapped_error = _seed_validation_error(event_name, {"record": typed_literal})
        if wrapped_error is None:
            return None
    return _consumer_site(parsed, call, event_name, "invalid_seed", error)


def _is_declared_payload_attribute(payload_type: Any, attribute: str) -> bool:
    if attribute in payload_type.model_fields:
        return True
    if any(model_field.alias == attribute for model_field in payload_type.model_fields.values()):
        return True
    return hasattr(payload_type, attribute)


def _event_type_condition(test: ast.expr) -> tuple[str, str] | None:
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
        and isinstance(test.left, ast.Attribute)
        and test.left.attr == "event_type"
        and isinstance(test.left.value, ast.Name)
        and test.left.value.id in {"event", "graph_event"}
    ):
        return None
    values = _literal_strings(test.comparators[0])
    if len(values) != 1:
        return None
    if isinstance(test.ops[0], ast.Eq):
        return ("equals", values[0])
    if isinstance(test.ops[0], ast.NotEq):
        return ("not_equals", values[0])
    return None


def _event_type_conditions(test: ast.expr) -> tuple[tuple[str, str], ...]:
    direct = _event_type_condition(test)
    if direct is not None:
        return (direct,)
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return tuple(
            condition for value in test.values for condition in _event_type_conditions(value)
        )
    return ()


def _events_for_consumer_node(
    parsed: _ParsedFile,
    node: ast.AST,
    events: set[str],
) -> set[str]:
    """Narrow a shared reducer scope to enclosing event-type branches."""

    narrowed = set(events)
    narrowed_by_event_type = False
    child = node
    while (parent := parsed.parents.get(child)) is not None:
        if isinstance(parent, ast.If):
            condition = _event_type_condition(parent.test)
            if condition is not None:
                relation, event_name = condition
                in_body = child in parent.body
                in_orelse = child in parent.orelse
                if in_body:
                    narrowed_by_event_type = True
                    if relation == "equals":
                        narrowed.intersection_update({event_name})
                    else:
                        narrowed.discard(event_name)
                elif in_orelse:
                    narrowed_by_event_type = True
                    if relation == "equals":
                        narrowed.discard(event_name)
                    else:
                        narrowed.intersection_update({event_name})
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
            for relation, event_name in _event_type_conditions(parent):
                narrowed_by_event_type = True
                if relation == "equals":
                    narrowed.intersection_update({event_name})
                else:
                    narrowed.discard(event_name)
        child = parent
    return narrowed if narrowed_by_event_type else set()


def _classify_consumer_scope(
    parsed: _ParsedFile,
    scope: _ConsumerScope,
    schema: ConsumerSchema,
    requested: frozenset[str],
) -> list[ConsumerSite]:
    sites: list[ConsumerSite] = []
    events = scope.referenced_events & requested
    for node in scope.payload_reads:
        field_name = _consumer_payload_read(node, scope)
        if field_name is None:
            continue
        base = _read_base_expression(node)
        if isinstance(base, ast.Name) and base.id in scope.record_dict_names:
            continue
        for event_name in sorted(_events_for_consumer_node(parsed, node, events)):
            if field_name in schema.declared_fields[event_name]:
                continue
            if field_name in schema.nested_record_fields[event_name]:
                sites.append(_consumer_site(parsed, node, event_name, "flat_shape_read"))
    for attribute in scope.attribute_reads:
        class_name = None
        if isinstance(attribute.value, ast.Name):
            class_name = scope.typed_variables.get(attribute.value.id)
        if class_name is None and scope.typed_expressions:
            class_name = scope.typed_expressions.get(ast.unparse(attribute.value))
        if class_name is None:
            continue
        event_name = schema.payload_class_events[class_name]
        if event_name not in requested:
            continue
        payload_type = schema.payload_classes[class_name]
        if _is_declared_payload_attribute(payload_type, attribute.attr):
            continue
        sites.append(_consumer_site(parsed, attribute, event_name, "unknown_attribute_read"))
    return sites


def _consumer_sites_for_file(
    parsed: _ParsedFile,
    schema: ConsumerSchema,
    requested: frozenset[str],
) -> list[ConsumerSite]:
    scopes: dict[ast.AST | None, _ConsumerScope] = {}

    def scope_for(node: ast.AST) -> _ConsumerScope:
        return scopes.setdefault(_owner_function(node, parsed), _ConsumerScope())

    wrapping_helpers = _record_wrapping_helper_names(parsed)
    sites: list[ConsumerSite] = []
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in schema.event_names and not _is_bare_string_statement(node, parsed):
                scope_for(node).referenced_events.add(node.value)
        elif isinstance(node, ast.Call):
            scope_for(node).payload_reads.append(node)
            _track_isinstance_guard(node, scope_for(node), schema)
            seed = _consumer_seed_site(node, parsed, schema, requested, wrapping_helpers)
            if seed is not None:
                sites.append(seed)
        elif isinstance(node, ast.Subscript):
            scope_for(node).payload_reads.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            _track_consumer_assignment(node, scope_for(node), schema)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = scopes.setdefault(node, _ConsumerScope())
            arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            for argument in arguments:
                class_name = _annotation_class_name(argument.annotation)
                if class_name is not None and class_name in schema.payload_class_events:
                    scope.typed_variables[argument.arg] = class_name
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            scope_for(node).attribute_reads.append(node)
    for scope in scopes.values():
        sites.extend(_classify_consumer_scope(parsed, scope, schema, requested))
    return sites


def scan_payload_consumers(
    paths: Sequence[Path],
    event_names: Iterable[str] | None = None,
) -> tuple[ConsumerSite, ...]:
    """Scan consumer-side payload usage for converted catalog-owned events."""

    schema = _consumer_schema()
    requested = (
        schema.event_names if event_names is None else frozenset(event_names) & schema.event_names
    )
    expanded: list[Path] = []
    for path in paths:
        expanded.extend(path.rglob("*.py") if path.is_dir() else [path])
    sites: list[ConsumerSite] = []
    for path in sorted(set(expanded), key=str):
        parsed = _parse(path)
        sites.extend(_consumer_sites_for_file(parsed, schema, requested))
    return tuple(sorted(set(sites)))


def render_consumer_report(
    sites: Sequence[ConsumerSite],
    event_names: Iterable[str],
) -> str:
    counts: dict[str, int] = {name: 0 for name in CONSUMER_REPORT_CLASSIFICATIONS}
    for site in sites:
        counts[site.classification] = counts.get(site.classification, 0) + 1
    lines = [
        f"Consumer payload scan ({len(sites)} sites) for events: "
        + (", ".join(sorted(event_names)) or "<none>"),
        "Counts: "
        + ", ".join(f"{name}={counts.get(name, 0)}" for name in CONSUMER_REPORT_CLASSIFICATIONS),
    ]
    lines.extend(
        f"{site.path}:{site.line}:{site.column} {site.event} {site.classification} {site.snippet}"
        for site in sites
    )
    return "\n".join(lines) + "\n"


def _default_consumer_paths() -> tuple[Path, ...]:
    return (Path("src/orchestrator"), Path("tests"))


def _run_consumer_scan(args: argparse.Namespace) -> int:
    domain = args.check_consumers or args.domain
    try:
        event_names = consumer_domain_event_names(domain)
    except UnknownConsumerDomainError as error:
        print(f"unknown consumer domain: {error}", file=sys.stderr)
        return 2
    paths = tuple(args.paths) or _default_consumer_paths()
    sites = scan_payload_consumers(paths, event_names)
    if args.consumer_report:
        rendered = render_consumer_report(sites, event_names)
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            args.output.write_text(rendered)
    if args.check_consumers:
        failing = [
            site for site in sites if site.classification in CONSUMER_FAILING_CLASSIFICATIONS
        ]
        for site in failing:
            print(
                f"{site.path}:{site.line}:{site.column} {site.event} "
                f"{site.classification}: {site.snippet}",
                file=sys.stderr,
            )
        return 1 if failing else 0
    return 0


def _default_paths() -> tuple[Path, ...]:
    return (Path("src/orchestrator/graph"), Path("src/orchestrator/graph_runtime"))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--check-domain")
    parser.add_argument("--consumer-report", action="store_true")
    parser.add_argument("--domain")
    parser.add_argument("--check-consumers", metavar="NAME")
    parser.add_argument("paths", nargs="*", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.consumer_report or args.check_consumers:
        return _run_consumer_scan(args)
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
