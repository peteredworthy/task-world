#!/usr/bin/env python3
"""Fail-closed AST checks for graph payload architecture boundaries."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


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


@dataclass(frozen=True, order=True)
class ArchitectureDiagnostic:
    path: str
    line: int
    column: int
    category: str
    expression: str

    def render(self) -> str:
        return f"{self.category}: {self.path}:{self.line}:{self.column}: {self.expression}"


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


def _has_schema_generation_one_boundary(node: ast.AST, operator: type[ast.cmpop]) -> bool:
    return any(
        isinstance(child, ast.Compare)
        and isinstance(child.left, ast.Attribute)
        and child.left.attr == "schema_version"
        and len(child.ops) == 1
        and isinstance(child.ops[0], operator)
        and len(child.comparators) == 1
        and isinstance(child.comparators[0], ast.Constant)
        and child.comparators[0].value == 1
        for child in ast.walk(node)
    )


def _is_d3_legacy_replay_branch(
    branch: ast.If,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> bool:
    predicate = functions.get("_is_d3_legacy_record_replay_event")
    adapter = functions.get("reduce_d3_legacy_record_replay")
    if predicate is None or adapter is None:
        return False
    test_calls = {
        _call_name(call.func) for call in ast.walk(branch.test) if isinstance(call, ast.Call)
    }
    body_calls = {
        _call_name(call.func)
        for statement in branch.body
        for call in ast.walk(statement)
        if isinstance(call, ast.Call)
    }
    return (
        "_is_d3_legacy_record_replay_event" in test_calls
        and "reduce_d3_legacy_record_replay" in body_calls
        and _has_schema_generation_one_boundary(predicate, ast.Eq)
        and _has_schema_generation_one_boundary(adapter, ast.NotEq)
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
                    is_d3_legacy_replay = _is_d3_legacy_replay_branch(branch, functions)
                    if branch_events and not is_d3_legacy_replay:
                        found_converted_branch = True
                        diagnostics.append(_diagnostic(path, branch, "converted reducer branch"))
                    elif is_d3_legacy_replay:
                        found_converted_branch = True
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


def check_paths(
    paths: Sequence[Path], *, domain: str = "lifecycle"
) -> tuple[ArchitectureDiagnostic, ...]:
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
    parser.add_argument("--domain", default="lifecycle")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    paths = args.paths or [Path("src/orchestrator/graph"), Path("src/orchestrator/graph_runtime")]
    diagnostics = check_paths(paths, domain=args.domain)
    for diagnostic in diagnostics:
        print(diagnostic.render(), file=sys.stderr)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
