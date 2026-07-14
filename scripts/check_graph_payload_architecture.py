#!/usr/bin/env python3
"""Fail-closed AST checks for graph payload architecture boundaries."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
    "topology": frozenset({"seed_compiled_events"}),
    "leases": frozenset({"schedule_tick", "reconcile"}),
    "records": frozenset({"evaluate_join", "evaluate_final_gate"}),
    "patches": frozenset({"submit_patch"}),
    "decisions": frozenset({"raise_appeal", "record_decision"}),
    "requirements": frozenset({"record_requirement_revision", "record_support_evidence"}),
    "file_state": frozenset({"record_gatekeeper_verdicts", "record_cleanup_applied"}),
}
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
    "topology": frozenset(
        {
            "node_created",
            "node_state_changed",
            "node_retired",
            "node_ready",
            "node_deferred",
            "node_authority_changed",
            "plan_region_marked_suspect",
            "edge_created",
            "input_bound",
            "session_state_changed",
            "dead_input_detected",
            "revision_created",
        }
    ),
    "leases": frozenset(
        {"lease_granted", "lease_renewed", "lease_released", "lease_revoked", "lease_expired"}
    ),
    "records": frozenset({"output_record_accepted", "verification_passed", "verification_failed"}),
    "patches": frozenset({"graph_patch_accepted", "graph_patch_rejected"}),
    "decisions": frozenset(
        {
            "appeal_opened",
            "approval_decision_recorded",
            "authority_decision_recorded",
            "oversight_decision_recorded",
        }
    ),
    "requirements": frozenset({"requirement_revision_recorded", "support_evidence_recorded"}),
    "file_state": frozenset(
        {
            "file_state_accepted",
            "file_state_rejected",
            "gatekeeper_verdict_recorded",
            "gatekeeper_cost_recorded",
            "cleanup_requested",
            "cleanup_applied",
        }
    ),
}

_RETIRED_GRAPH_PAYLOAD_NAMES = frozenset(
    {
        "LegacyEventPayload",
        "_D3_LEGACY_RECORD_EVENT_TYPES",
        "source_schema_version",
    }
)
_RETIRED_D_SERIES_MAPPING_METHODS = frozenset({"__getitem__", "get", "items"})


@dataclass(frozen=True, order=True)
class ArchitectureDiagnostic:
    path: str
    line: int
    column: int
    category: str
    expression: str

    @property
    def rule(self) -> str:
        return self.category

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.category}: {self.expression}"


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _strings(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _converted_handler(
    function: ast.FunctionDef | ast.AsyncFunctionDef, command_names: frozenset[str]
) -> bool:
    return any(
        function.name
        in {
            f"handle_{name}",
            f"handle_{name}_command",
            f"apply_{name}",
            f"_apply_{name}",
        }
        for name in command_names
    )


def _raw_payload_function(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return any(
        argument.arg in {"payload", "command"}
        and argument.annotation is not None
        and (
            "dict[" in ast.unparse(argument.annotation) or ast.unparse(argument.annotation) == "Any"
        )
        for argument in function.args.args
    )


def _diagnostic(path: Path, node: ast.AST, category: str) -> ArchitectureDiagnostic:
    return ArchitectureDiagnostic(
        str(path), node.lineno, node.col_offset, category, ast.unparse(node)
    )


def _temporary_marker_belongs_to_domain(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    command_names: frozenset[str],
    event_names: frozenset[str],
) -> bool:
    known_events = frozenset().union(*DOMAIN_EVENT_NAMES.values())
    referenced_events = _strings(function).intersection(known_events)
    if referenced_events:
        return bool(referenced_events.intersection(event_names))
    domain_tokens = {
        token
        for name in (*command_names, *event_names)
        for token in name.split("_")
        if len(token) > 3
    }
    return any(token in function.name for token in domain_tokens)


def _scan_file(path: Path, domain: str) -> list[ArchitectureDiagnostic]:
    command_names = DOMAIN_COMMAND_NAMES.get(domain.casefold())
    event_names = DOMAIN_EVENT_NAMES.get(domain.casefold())
    if command_names is None or event_names is None:
        return []
    tree = ast.parse(path.read_text(), filename=str(path))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    diagnostics: list[ArchitectureDiagnostic] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "temporary_unconverted_" in node.name and _temporary_marker_belongs_to_domain(
                node, command_names, event_names
            ):
                diagnostics.append(_diagnostic(path, node, "temporary unconverted marker"))
            calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
            dumps_model = any(
                isinstance(call.func, ast.Attribute) and call.func.attr == "model_dump"
                for call in calls
            )
            delegated = [
                call
                for call in calls
                if (
                    (_call_name(call.func) or "").startswith(("_raw", "_renamed_raw", "_legacy"))
                    or (
                        (called := functions.get(_call_name(call.func) or "")) is not None
                        and called is not node
                        and _raw_payload_function(called)
                    )
                )
            ]
            if (
                dumps_model
                and delegated
                and (
                    _converted_handler(node, command_names) or "temporary_unconverted_" in node.name
                )
            ):
                diagnostics.append(_diagnostic(path, delegated[0], "strict model delegation"))
            elif _converted_handler(node, command_names) and delegated:
                diagnostics.append(_diagnostic(path, delegated[0], "delegated raw handler"))
            if node.name == "reduce_event":
                found_converted_branch = False
                for branch in (child for child in ast.walk(node) if isinstance(child, ast.If)):
                    branch_events = _strings(branch.test).intersection(event_names)
                    if branch_events:
                        found_converted_branch = True
                        diagnostics.append(_diagnostic(path, branch, "converted reducer branch"))
                if not found_converted_branch and _strings(node).intersection(event_names):
                    diagnostics.append(_diagnostic(path, node, "converted reducer branch"))
                reducer_calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
                validation = next(
                    (
                        call
                        for call in reducer_calls
                        if isinstance(call.func, ast.Attribute)
                        and call.func.attr == "model_validate"
                    ),
                    None,
                )
                if validation is not None:
                    diagnostics.append(_diagnostic(path, validation, "central reducer validation"))
                payload_get = next(
                    (
                        call
                        for call in reducer_calls
                        if isinstance(call.func, ast.Attribute)
                        and call.func.attr == "get"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "payload"
                    ),
                    None,
                )
                if payload_get is not None:
                    diagnostics.append(_diagnostic(path, payload_get, "converted payload.get"))
            if node.name == "apply_command":
                for branch in (child for child in ast.walk(node) if isinstance(child, ast.If)):
                    if _strings(branch.test).intersection(command_names) and any(
                        isinstance(child, ast.Compare)
                        and any(
                            isinstance(comparator, ast.Constant) and comparator.value is None
                            for comparator in child.comparators
                        )
                        for child in ast.walk(branch.test)
                    ):
                        diagnostics.append(
                            _diagnostic(path, branch, "raw converted command bypass")
                        )
        if isinstance(node, ast.Call) and _call_name(node.func) == "future_command_effects":
            diagnostics.append(_diagnostic(path, node, "implicit future effects"))
    return diagnostics


def _strict_cutover_diagnostics(path: Path) -> list[ArchitectureDiagnostic]:
    """Reject retired generation-1 carriers and mapping compatibility seams."""
    tree = ast.parse(path.read_text(), filename=str(path))
    diagnostics: list[ArchitectureDiagnostic] = []
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    command_result_functions = {"handle_command"}
    while True:
        function_aliases = {
            target.id: value.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and (value := node.value) is not None
            and isinstance(value, ast.Name)
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        aliases_changed = True
        while aliases_changed:
            aliases_changed = False
            for alias, target in tuple(function_aliases.items()):
                resolved = function_aliases.get(target, target)
                if resolved != target:
                    function_aliases[alias] = resolved
                    aliases_changed = True

        def call_returns_command_result(value: ast.expr, callable_aliases: set[str]) -> bool:
            call = value.value if isinstance(value, ast.Await) else value
            return isinstance(call, ast.Call) and (
                _call_name(call.func) in command_result_functions
                or (isinstance(call.func, ast.Name) and call.func.id in callable_aliases)
            )

        wrappers: set[str] = set()
        for name, function in functions.items():
            callable_aliases = {
                alias
                for alias, target in function_aliases.items()
                if target in command_result_functions
            }
            result_names: set[str] = set()
            changed = True
            while changed:
                changed = False
                for child in ast.walk(function):
                    if not isinstance(child, (ast.Assign, ast.AnnAssign)) or child.value is None:
                        continue
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    if (
                        isinstance(child.value, ast.Attribute)
                        and child.value.attr == "handle_command"
                    ):
                        for target in targets:
                            if isinstance(target, ast.Name) and target.id not in callable_aliases:
                                callable_aliases.add(target.id)
                                changed = True
                    if call_returns_command_result(child.value, callable_aliases) or (
                        isinstance(child.value, ast.Name) and child.value.id in result_names
                    ):
                        for target in targets:
                            if isinstance(target, ast.Name) and target.id not in result_names:
                                result_names.add(target.id)
                                changed = True
            if any(
                isinstance(child, ast.Return)
                and child.value is not None
                and (
                    call_returns_command_result(child.value, callable_aliases)
                    or isinstance(child.value, ast.Name)
                    and child.value.id in result_names
                )
                for child in ast.walk(function)
            ):
                wrappers.add(name)
        if wrappers <= command_result_functions:
            break
        command_result_functions.update(wrappers)

    def is_strict_model_name(node: ast.expr) -> bool:
        name = _call_name(node)
        return name is not None and (name.endswith("Payload") or name.startswith("Strict"))

    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        arguments = (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
        parameter_aliases = {
            argument.arg
            for argument in arguments
            if argument.annotation is not None and is_strict_model_name(argument.annotation)
        }
        aliases = set(parameter_aliases)
        strict_event_names = {
            argument.arg
            for argument in arguments
            if argument.annotation is not None
            and ast.unparse(argument.annotation) == "HydratedEvent"
        }
        strict_event_collections = {
            argument.arg
            for argument in arguments
            if argument.annotation is not None
            and "HydratedEvent" in ast.unparse(argument.annotation)
            and "EventEnvelope" not in ast.unparse(argument.annotation)
            and ast.unparse(argument.annotation) != "HydratedEvent"
        }
        command_result_names: set[str] = set()
        payload_sequences: set[str] = set()
        callable_aliases: set[str] = set()

        def assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            return {target.id for target in targets if isinstance(target, ast.Name)}

        def is_command_result(value: ast.expr) -> bool:
            return (
                isinstance(value, ast.Await)
                and isinstance(value.value, ast.Call)
                and (
                    _call_name(value.value.func) in command_result_functions
                    or isinstance(value.value.func, ast.Name)
                    and value.value.func.id in callable_aliases
                )
            )

        changed = True
        while changed:
            changed = False
            for node in ast.walk(function):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                if isinstance(node.value, ast.Attribute) and node.value.attr == "handle_command":
                    before = len(callable_aliases)
                    callable_aliases.update(assigned_names(node))
                    changed = changed or len(callable_aliases) != before
                if is_command_result(node.value):
                    before = len(command_result_names)
                    command_result_names.update(assigned_names(node))
                    changed = changed or len(command_result_names) != before

        def is_result_events(node: ast.expr) -> bool:
            return (
                isinstance(node, ast.Attribute)
                and node.attr == "events"
                and isinstance(node.value, ast.Name)
                and node.value.id in command_result_names
            )

        def is_strict_event_collection(node: ast.expr) -> bool:
            if isinstance(node, ast.Name):
                return node.id in strict_event_collections
            return (
                isinstance(node, ast.Call)
                and _call_name(node.func) == "reversed"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in strict_event_collections
            )

        for node in ast.walk(function):
            if isinstance(node, (ast.For, ast.comprehension)) and (
                is_result_events(node.iter) or is_strict_event_collection(node.iter)
            ):
                if isinstance(node.target, ast.Name):
                    strict_event_names.add(node.target.id)

        def is_strict_event_expression(node: ast.expr) -> bool:
            if isinstance(node, ast.Name):
                return node.id in strict_event_names
            if not (
                isinstance(node, ast.Call)
                and _call_name(node.func) == "next"
                and node.args
                and isinstance(node.args[0], ast.GeneratorExp)
            ):
                return False
            return is_strict_event_expression(node.args[0].elt)

        for node in ast.walk(function):
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and node.value is not None
                and is_strict_event_expression(node.value)
            ):
                strict_event_names.update(assigned_names(node))

        def is_strict_payload_expression(node: ast.expr) -> bool:
            if isinstance(node, ast.Name):
                return node.id in aliases
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "payload"
                and isinstance(node.value, ast.Name)
            ):
                return node.value.id in strict_event_names
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to_json"
            ):
                return is_strict_payload_expression(node.func.value)
            return (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id in payload_sequences
            )

        def is_event_payload_json_expression(node: ast.expr) -> bool:
            return (
                isinstance(node, ast.Call)
                and _call_name(node.func) == "event_payload_json"
                and len(node.args) == 1
                and is_strict_event_expression(node.args[0])
            )

        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and _call_name(node.func) == "isinstance"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and is_strict_model_name(node.args[1])
            ):
                aliases.add(node.args[0].id)
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and (value := node.value) is not None
                and isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr in {"model_validate", "model_validate_json"}
                and is_strict_model_name(value.func.value)
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                aliases.update(target.id for target in targets if isinstance(target, ast.Name))
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                is_parameter_json_adapter = (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "to_json"
                    and isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id in parameter_aliases
                )
                if (
                    is_strict_payload_expression(node.value)
                    or is_event_payload_json_expression(node.value)
                ) and not is_parameter_json_adapter:
                    aliases.update(assigned_names(node))
                if isinstance(node.value, ast.ListComp) and is_strict_payload_expression(
                    node.value.elt
                ):
                    payload_sequences.update(assigned_names(node))
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _RETIRED_D_SERIES_MAPPING_METHODS
                and is_strict_payload_expression(node.func.value)
            ):
                diagnostics.append(_diagnostic(path, node, "W5RAW_PAYLOAD_READ"))
            elif isinstance(node, ast.Subscript) and is_strict_payload_expression(node.value):
                diagnostics.append(_diagnostic(path, node, "W5RAW_PAYLOAD_READ"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) == "EventEnvelope":
            diagnostics.append(_diagnostic(path, node, "W5RAW_EVENT_ENVELOPE_CONSTRUCTION"))
        if isinstance(node, ast.Name) and node.id in _RETIRED_GRAPH_PAYLOAD_NAMES:
            diagnostics.append(_diagnostic(path, node, "retired graph payload compatibility"))
        if isinstance(node, ast.ClassDef) and node.name == "LegacyEventPayload":
            diagnostics.append(_diagnostic(path, node, "retired graph payload compatibility"))
        if isinstance(node, ast.ClassDef) and node.name in {"StrictPayload", "LegacyEventPayload"}:
            for member in node.body:
                if (
                    isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name in _RETIRED_D_SERIES_MAPPING_METHODS
                ):
                    diagnostics.append(_diagnostic(path, member, "retired D-series mapping method"))
    return diagnostics


def check_paths(
    paths: Sequence[Path], *, domain: str | None = None
) -> tuple[ArchitectureDiagnostic, ...]:
    if domain is None:
        from scripts.w5_payload_ast_inventory import scan_graph_payload_architecture

        report = scan_graph_payload_architecture(paths)
        diagnostics = [
            ArchitectureDiagnostic(fact.path, fact.line, fact.column, fact.rule, fact.expression)
            for fact in report.architecture_facts
        ]
        diagnostics.extend(
            ArchitectureDiagnostic(
                site.path,
                site.line,
                site.column,
                "W5UNCLASSIFIED_DYNAMIC_SITE",
                site.expression,
            )
            for site in (*report.dynamic_event_sites, *report.dynamic_command_sites)
            if site.classification == "unresolved"
        )
        expanded = [
            candidate
            for path in paths
            for candidate in (path.rglob("*.py") if path.is_dir() else [path])
        ]
        for path in expanded:
            diagnostics.extend(_strict_cutover_diagnostics(path))
        return tuple(sorted(set(diagnostics)))
    expanded: list[Path] = []
    for path in paths:
        expanded.extend(path.rglob("*.py") if path.is_dir() else [path])
    diagnostics = [
        diagnostic
        for path in sorted(set(expanded), key=str)
        for diagnostic in _scan_file(path, domain)
    ]
    return tuple(sorted(set(diagnostics)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    paths = args.paths or [
        Path("src/orchestrator/graph"),
        Path("src/orchestrator/graph_runtime"),
        Path("src/orchestrator/api"),
        Path("src/orchestrator/db"),
        Path("src/orchestrator/workflow"),
    ]
    diagnostics = check_paths(paths, domain=args.domain)
    for diagnostic in diagnostics:
        print(diagnostic.render(), file=sys.stderr)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
