#!/usr/bin/env python3
"""Formatting-preserving mechanical cutover harness for W5 payload domains.

The migration table contains symbol routing only.  Payload fields, types, and
runtime schemas remain owned by the domain implementation.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import difflib
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import libcst as cst
from libcst import metadata
from libcst.helpers import get_full_name_for_node
from libcst.metadata.scope_provider import GlobalScope


@dataclass(frozen=True)
class SymbolRelocation:
    symbol: str
    source_path: str
    target_path: str
    source_module: str | None = None
    dependency_closure: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventRoute:
    event_name: str
    payload_class: str
    specification: str


@dataclass(frozen=True)
class CommandRoute:
    command_name: str
    handler: str
    specification: str
    payload_class: str


@dataclass(frozen=True)
class ImportRoute:
    old_module: str
    new_module: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class RequiredImport:
    path: str
    module: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class CatalogInjection:
    callable_name: str
    argument_name: str = "catalog"
    qualified_names: tuple[str, ...] = ()
    additional_arguments: tuple[str, ...] = ()
    factory_arguments: bool = False
    test_only_unqualified: bool = False


@dataclass(frozen=True)
class AllowlistConsumer:
    function_name: str
    replacement_expression: str
    qualified_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainMigration:
    domain: str
    paths: tuple[str, ...]
    target_module: str | None = None
    relocations: tuple[SymbolRelocation, ...] = ()
    event_routes: tuple[EventRoute, ...] = ()
    command_routes: tuple[CommandRoute, ...] = ()
    import_routes: tuple[ImportRoute, ...] = ()
    required_imports: tuple[RequiredImport, ...] = ()
    catalog_injections: tuple[CatalogInjection, ...] = ()
    event_factory_qualified_names: tuple[str, ...] = ()
    allowlist_consumers: tuple[AllowlistConsumer, ...] = ()
    report_dynamic_emissions: bool = False
    allowlist_names: tuple[str, ...] = ()
    remove_functions: tuple[str, ...] = ()
    allowed_allowlist_owners: tuple[str, ...] = ()
    transform_commands: bool = True


@dataclass(frozen=True, order=True)
class CodemodDiagnostic:
    path: str
    line: int
    column: int
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.code} {self.message}"


@dataclass(frozen=True)
class TransformResult:
    source: str
    diagnostics: tuple[CodemodDiagnostic, ...]
    changes: int


@dataclass(frozen=True)
class FileTransformResult:
    sources: dict[str, str]
    diagnostics: tuple[CodemodDiagnostic, ...]
    changes: int


@dataclass(frozen=True)
class MigrationRunResult:
    exit_code: int
    output: str


def _simple_string(value: cst.BaseExpression) -> str | None:
    if not isinstance(value, cst.SimpleString):
        return None
    evaluated = value.evaluated_value
    return evaluated if isinstance(evaluated, str) else None


def _assigned_name(node: cst.Assign | cst.AnnAssign) -> str | None:
    if isinstance(node, cst.AnnAssign):
        return node.target.value if isinstance(node.target, cst.Name) else None
    if len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Name):
        return None
    return node.targets[0].target.value


def _is_nested_record_payload(node: cst.BaseExpression) -> bool:
    if not isinstance(node, cst.Dict):
        return False
    for element in node.elements:
        if isinstance(element, cst.DictElement) and _simple_string(element.key) == "record":
            return True
    return False


def _dict_elements_by_key(node: cst.Dict) -> dict[str, cst.DictElement]:
    elements: dict[str, cst.DictElement] = {}
    for element in node.elements:
        if isinstance(element, cst.DictElement):
            key = _simple_string(element.key)
            if key is not None:
                elements[key] = element
    return elements


def _append_missing_dict_fields(
    node: cst.Dict, additions: tuple[tuple[str, cst.BaseExpression], ...]
) -> cst.Dict:
    existing = _dict_elements_by_key(node)
    return node.with_changes(
        elements=(
            *node.elements,
            *(
                cst.DictElement(cst.SimpleString(f'"{key}"'), value)
                for key, value in additions
                if key not in existing
            ),
        )
    )


def _complete_sparse_check_result_record_payload(
    node: cst.BaseExpression,
) -> cst.BaseExpression | None:
    if not isinstance(node, cst.Dict):
        return None
    outer = _dict_elements_by_key(node)
    record_element = outer.get("record")
    if record_element is None or not isinstance(record_element.value, cst.Dict):
        return None
    record = record_element.value
    fields = _dict_elements_by_key(record)
    record_type = fields.get("record_type")
    value_field = fields.get("value")
    if (
        record_type is None
        or _simple_string(record_type.value) != "check_result"
        or (value_field is not None and not isinstance(value_field.value, cst.Dict))
    ):
        return None
    value = value_field.value if value_field is not None else cst.Dict(elements=())
    value_fields = _dict_elements_by_key(value)
    status_field = value_fields.get("status") or fields.get("status")
    status = (
        status_field.value
        if status_field is not None
        and _simple_string(status_field.value) in {"passed", "failed", "timeout"}
        else cst.SimpleString('"passed"')
    )
    completed_value = _append_missing_dict_fields(
        _append_missing_dict_fields(value, (("status", status),)),
        (
            ("classification", status),
            ("command_id", cst.SimpleString('"check-test"')),
            ("command_text", cst.SimpleString('"test"')),
            ("command", cst.Dict(elements=())),
            ("worktree_path", cst.SimpleString('"/repo"')),
            ("base_snapshot_id", cst.SimpleString('"S0"')),
            ("execution_id", cst.SimpleString('"exec-test"')),
            ("duration_ms", cst.Integer("0")),
            ("stdout", cst.SimpleString('""')),
            ("stderr", cst.SimpleString('""')),
            ("stdout_truncated", cst.Name("False")),
            ("stderr_truncated", cst.Name("False")),
            ("timeout_seconds", cst.Integer("60")),
            ("environment_policy", cst.Dict(elements=())),
        ),
    )
    completed_record = _append_missing_dict_fields(
        record,
        (
            ("schema", cst.SimpleString('"CheckResult"')),
            ("attempt_number", cst.Integer("1")),
        ),
    )
    completed_record = completed_record.with_changes(
        elements=tuple(
            element
            for element in completed_record.elements
            if not (
                isinstance(element, cst.DictElement)
                and (
                    (
                        _simple_string(element.key) == "candidate_id"
                        and _simple_string(element.value) == "candidate-test"
                    )
                    or _simple_string(element.key) == "status"
                )
            )
        )
    )
    completed_record_fields = _dict_elements_by_key(completed_record)
    completed_value_field = completed_record_fields.get("value")
    if completed_value_field is None:
        completed_record = _append_missing_dict_fields(
            completed_record, (("value", completed_value),)
        )
    else:
        completed_record = completed_record.with_changes(
            elements=tuple(
                element.with_changes(value=completed_value)
                if element is completed_value_field
                else element
                for element in completed_record.elements
            )
        )
    if completed_record.deep_equals(record):
        return None
    return node.with_changes(
        elements=tuple(
            element.with_changes(value=completed_record) if element is record_element else element
            for element in node.elements
        )
    )


def _complete_sparse_candidate_record_payload(
    node: cst.BaseExpression,
) -> cst.BaseExpression | None:
    if not isinstance(node, cst.Dict):
        return None
    outer = _dict_elements_by_key(node)
    record_element = outer.get("record")
    if record_element is None or not isinstance(record_element.value, cst.Dict):
        return None
    record = record_element.value
    fields = _dict_elements_by_key(record)
    record_type_field = fields.get("record_type")
    value_field = fields.get("value")
    if record_type_field is not None and _simple_string(record_type_field.value) == "candidate":
        completed_record = _append_missing_dict_fields(
            record,
            (("schema", cst.SimpleString('"ImplementationCandidate"')),),
        )
        record_id_field = fields.get("record_id")
        if "candidate_id" not in fields and record_id_field is not None:
            completed_record = _append_missing_dict_fields(
                completed_record, (("candidate_id", record_id_field.value),)
            )
        if value_field is None:
            completed_record = _append_missing_dict_fields(
                completed_record,
                (
                    (
                        "value",
                        cst.Dict(
                            elements=(
                                cst.DictElement(
                                    cst.SimpleString('"summary"'),
                                    cst.SimpleString('"test candidate"'),
                                ),
                            )
                        ),
                    ),
                ),
            )
        elif isinstance(value_field.value, cst.Dict) and "summary" not in _dict_elements_by_key(
            value_field.value
        ):
            completed_value = value_field.value.with_changes(
                elements=(
                    cst.DictElement(
                        cst.SimpleString('"summary"'), cst.SimpleString('"test candidate"')
                    ),
                    *value_field.value.elements,
                )
            )
            completed_record = completed_record.with_changes(
                elements=tuple(
                    element.with_changes(value=completed_value)
                    if element is value_field
                    else element
                    for element in completed_record.elements
                )
            )
        completed_fields = _dict_elements_by_key(completed_record)
        singular_supersedes = completed_fields.get("supersedes_task_region_id")
        if singular_supersedes is not None:
            completed_record = completed_record.with_changes(
                elements=tuple(
                    element.with_changes(
                        key=cst.SimpleString('"supersedes_task_region_ids"'),
                        value=cst.List(elements=(cst.Element(singular_supersedes.value),)),
                    )
                    if element is singular_supersedes
                    else element
                    for element in completed_record.elements
                )
            )
        if completed_record.deep_equals(record):
            return None
        return node.with_changes(
            elements=tuple(
                element.with_changes(value=completed_record)
                if element is record_element
                else element
                for element in node.elements
            )
        )
    candidate_id = fields.get("candidate_id")
    record_kind = fields.get("record_kind")
    port = fields.get("port")
    if (
        candidate_id is None
        or "record_type" in fields
        or (record_kind is not None and _simple_string(record_kind.value) not in {None, "output"})
        or (port is not None and _simple_string(port.value) not in {None, "candidate"})
        or any(key in fields for key in ("verdict", "outcome", "grades"))
    ):
        return None
    value = fields.get("value")
    if value is None:
        value_elements: list[cst.DictElement] = [
            cst.DictElement(cst.SimpleString('"summary"'), cst.SimpleString('"test candidate"'))
        ]
        file_state_ids = fields.get("file_state_record_ids")
        if file_state_ids is not None:
            value_elements.append(
                cst.DictElement(cst.SimpleString('"file_state_record_ids"'), file_state_ids.value)
            )
        value_expression: cst.BaseExpression = cst.Dict(elements=tuple(value_elements))
    elif isinstance(value.value, cst.Dict) and "summary" not in _dict_elements_by_key(value.value):
        value_expression = value.value.with_changes(
            elements=(
                cst.DictElement(
                    cst.SimpleString('"summary"'), cst.SimpleString('"test candidate"')
                ),
                *value.value.elements,
            )
        )
    else:
        value_expression = value.value
    prefix = (
        cst.DictElement(cst.SimpleString('"record_id"'), candidate_id.value),
        cst.DictElement(cst.SimpleString('"record_kind"'), cst.SimpleString('"output"')),
        cst.DictElement(cst.SimpleString('"record_type"'), cst.SimpleString('"candidate"')),
        cst.DictElement(
            cst.SimpleString('"producer_node_id"'),
            fields.get(
                "producer_node_id",
                cst.DictElement(
                    cst.SimpleString('"producer_node_id"'), cst.SimpleString('"worker-test"')
                ),
            ).value,
        ),
        cst.DictElement(cst.SimpleString('"port"'), cst.SimpleString('"candidate"')),
        cst.DictElement(
            cst.SimpleString('"schema"'), cst.SimpleString('"ImplementationCandidate"')
        ),
        cst.DictElement(cst.SimpleString('"value"'), value_expression),
    )
    replaced_keys = {
        "record_id",
        "record_kind",
        "record_type",
        "producer_node_id",
        "port",
        "schema",
        "value",
    }
    remaining = tuple(
        element
        for element in record.elements
        if not isinstance(element, cst.DictElement)
        or _simple_string(element.key) not in replaced_keys
    )
    replaced_record = record.with_changes(elements=(*prefix, *remaining))
    return node.with_changes(
        elements=tuple(
            element.with_changes(value=replaced_record) if element is record_element else element
            for element in node.elements
        )
    )


def _complete_task3_strict_record_payload(
    node: cst.BaseExpression,
) -> cst.BaseExpression | None:
    if not isinstance(node, cst.Dict):
        return None
    outer = _dict_elements_by_key(node)
    record_element = outer.get("record")
    if record_element is None or not isinstance(record_element.value, cst.Dict):
        return None
    record = record_element.value
    fields = _dict_elements_by_key(record)
    record_type = _simple_string(fields["record_type"].value) if "record_type" in fields else None
    record_kind = _simple_string(fields["record_kind"].value) if "record_kind" in fields else None

    if (
        _simple_string(fields["port"].value) if "port" in fields else None
    ) == "authority_request_record" and record_type != "authority_request_record":
        completed_record = record.with_changes(
            elements=tuple(
                element.with_changes(value=cst.SimpleString('"authority_request_record"'))
                if isinstance(element, cst.DictElement)
                and _simple_string(element.key) == "record_type"
                else element
                for element in record.elements
            )
        )
    elif record_type == "routine_snapshot":
        value_field = fields.get("value")
        value = value_field.value if value_field is not None else cst.Dict(elements=())
        if not isinstance(value, cst.Dict):
            return None
        completed_value = _append_missing_dict_fields(
            value,
            (
                ("routine_id", cst.SimpleString('"routine-1"')),
                ("name", cst.SimpleString('"Test Routine"')),
                ("content_hash", cst.SimpleString('"test-content-hash"')),
                ("step_count", cst.Integer("1")),
                ("task_count", cst.Integer("1")),
            ),
        )
        completed_record = _append_missing_dict_fields(record, (("value", completed_value),))
        completed_fields = _dict_elements_by_key(completed_record)
        if value_field is not None:
            current_value = completed_fields["value"]
            completed_record = completed_record.with_changes(
                elements=tuple(
                    element.with_changes(value=completed_value)
                    if element is current_value
                    else element
                    for element in completed_record.elements
                )
            )
        kind_field = _dict_elements_by_key(completed_record).get("record_kind")
        if kind_field is not None and _simple_string(kind_field.value) != "graph_record":
            completed_record = completed_record.with_changes(
                elements=tuple(
                    element.with_changes(value=cst.SimpleString('"graph_record"'))
                    if element is kind_field
                    else element
                    for element in completed_record.elements
                )
            )
    elif record_kind == "verification" and record_type in {None, "verification_report"}:
        verdict_field = fields.get("verdict")
        outcome_field = fields.get("outcome")
        value_field = fields.get("value")
        value = value_field.value if value_field is not None else cst.Dict(elements=())
        value_fields = _dict_elements_by_key(value) if isinstance(value, cst.Dict) else {}
        value_outcome_field = value_fields.get("outcome")
        outcome = next(
            (
                field.value
                for field in (outcome_field, value_outcome_field, verdict_field)
                if field is not None and _simple_string(field.value) in {"passed", "failed"}
            ),
            cst.SimpleString('"passed"'),
        )
        completed_value = (
            _append_missing_dict_fields(
                value,
                (("outcome", outcome), ("grades", cst.List(elements=()))),
            )
            if isinstance(value, cst.Dict)
            else value
        )
        completed_record = _append_missing_dict_fields(
            record.with_changes(
                elements=tuple(
                    element.with_changes(value=completed_value)
                    if element is value_field
                    else element
                    for element in record.elements
                )
            ),
            (
                ("record_type", cst.SimpleString('"verification_report"')),
                ("schema", cst.SimpleString('"VerificationReport"')),
                ("outcome", outcome),
                ("value", completed_value),
            ),
        )
    elif record_type == "candidate" and "schema" not in fields:
        record_id_field = fields.get("record_id")
        additions: list[tuple[str, cst.BaseExpression]] = [
            ("schema", cst.SimpleString('"ImplementationCandidate"'))
        ]
        if "candidate_id" not in fields and record_id_field is not None:
            additions.append(("candidate_id", record_id_field.value))
        completed_record = _append_missing_dict_fields(record, tuple(additions))
    elif record_type == "recovery_plan" and record_kind != "output":
        completed_record = record.with_changes(
            elements=tuple(
                element.with_changes(value=cst.SimpleString('"output"'))
                if isinstance(element, cst.DictElement)
                and _simple_string(element.key) == "record_kind"
                else element
                for element in record.elements
            )
        )
    elif record_type == "failure_record":
        completed_record = record.with_changes(
            elements=tuple(
                element.with_changes(value=cst.SimpleString('"graph_record"'))
                if isinstance(element, cst.DictElement)
                and _simple_string(element.key) == "record_kind"
                else element
                for element in record.elements
                if not (
                    isinstance(element, cst.DictElement)
                    and _simple_string(element.key) == "task_region_id"
                )
            )
        )
    else:
        return None

    if completed_record.deep_equals(record):
        return None
    return node.with_changes(
        elements=tuple(
            element.with_changes(value=completed_record) if element is record_element else element
            for element in node.elements
        )
    )


def _task3_routine_snapshot_record(node: cst.BaseExpression) -> cst.Dict | None:
    if not isinstance(node, cst.Dict):
        return None
    fields = _dict_elements_by_key(node)
    node_id = fields.get("node_id")
    snapshot = fields.get("snapshot")
    if (
        node_id is None
        or _simple_string(node_id.value) != "routine-snapshot"
        or snapshot is None
        or not isinstance(snapshot.value, cst.Dict)
    ):
        return None
    value = _append_missing_dict_fields(
        snapshot.value,
        (
            ("routine_id", cst.SimpleString('"routine-1"')),
            ("name", cst.SimpleString('"Test Routine"')),
            ("content_hash", cst.SimpleString('"test-content-hash"')),
            ("step_count", cst.Integer("1")),
            ("task_count", cst.Integer("1")),
        ),
    )
    record = cst.Dict(
        elements=(
            cst.DictElement(
                cst.SimpleString('"record_id"'), cst.SimpleString('"routine-snapshot-record"')
            ),
            cst.DictElement(cst.SimpleString('"record_kind"'), cst.SimpleString('"graph_record"')),
            cst.DictElement(
                cst.SimpleString('"record_type"'), cst.SimpleString('"routine_snapshot"')
            ),
            cst.DictElement(cst.SimpleString('"producer_node_id"'), node_id.value),
            cst.DictElement(cst.SimpleString('"port"'), cst.SimpleString('"routine_snapshot"')),
            cst.DictElement(cst.SimpleString('"schema"'), cst.SimpleString('"RoutineSnapshot"')),
            cst.DictElement(cst.SimpleString('"value"'), value),
        )
    )
    return cst.Dict(elements=(cst.DictElement(cst.SimpleString('"record"'), record),))


class _EventPayloadToRecord(cst.CSTTransformer):
    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if (
            isinstance(original_node.value, cst.Name)
            and original_node.value.value == "event"
            and original_node.attr.value == "payload"
        ):
            return cst.Subscript(
                value=updated_node,
                slice=(
                    cst.SubscriptElement(
                        slice=cst.Index(value=cst.SimpleString('"record"')),
                    ),
                ),
            )
        return updated_node


class _MechanicalTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (
        metadata.PositionProvider,
        metadata.QualifiedNameProvider,
        metadata.ScopeProvider,
    )

    def __init__(
        self,
        migration: DomainMigration,
        path: str,
        existing_command_specs: tuple[str, ...],
        will_compose_command_specs: bool,
        blocked_command_specs: bool,
        blocked_allowlists: frozenset[str],
        initial_diagnostics: tuple[CodemodDiagnostic, ...],
    ) -> None:
        self.migration = migration
        self.path = path
        self.changes = 0
        self.diagnostics = list(initial_diagnostics)
        self._existing_command_specs = existing_command_specs
        self._will_compose_command_specs = will_compose_command_specs
        self._blocked_command_specs = blocked_command_specs
        self._composed_command_specs = False
        self._events = {route.event_name: route for route in migration.event_routes}
        command_routes = migration.command_routes if migration.transform_commands else ()
        self._commands = {route.command_name: route for route in command_routes}
        self._handlers = {route.handler: route for route in command_routes}
        self._imports = {route.old_module: route for route in migration.import_routes}
        self._catalog_injections = migration.catalog_injections
        self._allowlist_consumers = {
            consumer.function_name: consumer for consumer in migration.allowlist_consumers
        }
        self._blocked_allowlists = blocked_allowlists
        self._function_stack: list[str] = []
        self._class_stack: list[str] = []
        self._functions_needing_catalog: set[str] = set()

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._class_stack.append(node.name.value)

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.BaseStatement:
        self._class_stack.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._function_stack.append(node.name.value)

    def _resolved_names(self, node: cst.CSTNode) -> frozenset[str]:
        return frozenset(
            qualified.name
            for qualified in self.get_metadata(metadata.QualifiedNameProvider, node, set())
        )

    def _touch_metadata(self, node: cst.CSTNode) -> metadata.CodeRange:
        position = self.get_metadata(metadata.PositionProvider, node)
        self._resolved_names(node)
        self.get_metadata(metadata.ScopeProvider, node)
        return position

    @staticmethod
    def _is_indexed_output_payload(node: cst.BaseExpression) -> bool:
        return (
            isinstance(node, cst.Attribute)
            and node.attr.value == "payload"
            and isinstance(node.value, cst.Subscript)
            and isinstance(node.value.value, cst.Name)
            and node.value.value.value in {"output", "decision_events"}
        )

    @staticmethod
    def _record_payload(node: cst.BaseExpression) -> cst.Subscript:
        return cst.Subscript(
            value=node,
            slice=(
                cst.SubscriptElement(
                    slice=cst.Index(value=cst.SimpleString('"record"')),
                ),
            ),
        )

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.BaseSmallStatement:
        record_fixture_names = {
            "accepted_record",
            "candidate_record",
            "decision",
            "join_result",
            "request_record",
        }
        if (
            self.migration.domain in {"records", "task3_fixtures"}
            and self.path.endswith(
                (
                    "tests/unit/test_graph_commands.py",
                    "src/orchestrator/graph/scenario.py",
                    "src/orchestrator/graph_runtime/controller.py",
                )
            )
            and len(original_node.targets) == 1
            and isinstance(original_node.targets[0].target, cst.Name)
            and original_node.targets[0].target.value in record_fixture_names
            and self._is_indexed_output_payload(original_node.value)
        ):
            self.changes += 1
            return updated_node.with_changes(value=self._record_payload(updated_node.value))
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith("tests/unit/test_graph_commands.py")
            and len(original_node.targets) == 1
            and isinstance(original_node.targets[0].target, cst.Name)
            and original_node.targets[0].target.value == "accepted_record"
            and isinstance(original_node.value, cst.Call)
            and isinstance(original_node.value.func, cst.Name)
            and original_node.value.func.value == "next"
            and 'event.payload["record"]' not in cst.Module([]).code_for_node(original_node.value)
        ):
            transformed = updated_node.value.visit(_EventPayloadToRecord())
            if not transformed.deep_equals(updated_node.value):
                self.changes += 1
                return updated_node.with_changes(value=transformed)
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith("tests/integration/test_graph_event_store.py")
            and len(original_node.targets) == 1
            and isinstance(original_node.targets[0].target, cst.Name)
            and original_node.targets[0].target.value
            in {
                "candidate",
                "verification",
                "check_result",
                "decision_request",
                "authority_request",
                "failure",
                "recovery_plan",
                "run_context",
                "routine_snapshot",
                "artifact_reference",
            }
            and isinstance(original_node.value, cst.Attribute)
            and original_node.value.attr.value == "payload"
            and isinstance(original_node.value.value, cst.Subscript)
            and isinstance(original_node.value.value.value, cst.Name)
            and original_node.value.value.value.value == "stored"
        ):
            self.changes += 1
            return updated_node.with_changes(value=self._record_payload(updated_node.value))
        return updated_node

    def leave_Comparison(
        self, original_node: cst.Comparison, updated_node: cst.Comparison
    ) -> cst.BaseExpression:
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith("tests/integration/test_graph_event_store.py")
            and isinstance(original_node.left, cst.Subscript)
            and isinstance(original_node.left.value, cst.Name)
            and original_node.left.value.value == "check_result"
            and len(original_node.left.slice) == 1
            and isinstance(original_node.left.slice[0].slice, cst.Index)
            and _simple_string(original_node.left.slice[0].slice.value) == "payload"
            and len(updated_node.comparisons) == 1
            and isinstance(updated_node.comparisons[0].operator, cst.Equal)
            and isinstance(updated_node.comparisons[0].comparator, cst.Dict)
        ):
            expected = _append_missing_dict_fields(
                updated_node.comparisons[0].comparator,
                (
                    ("command_text", cst.SimpleString('"test"')),
                    ("command", cst.Dict(elements=())),
                    ("worktree_path", cst.SimpleString('"/repo"')),
                    ("base_snapshot_id", cst.SimpleString('"S0"')),
                    ("execution_id", cst.SimpleString('"exec-test"')),
                    ("duration_ms", cst.Integer("0")),
                    ("stdout", cst.SimpleString('""')),
                    ("stderr", cst.SimpleString('""')),
                    ("stdout_truncated", cst.Name("False")),
                    ("stderr_truncated", cst.Name("False")),
                    ("timeout_seconds", cst.Integer("60")),
                    ("environment_policy", cst.Dict(elements=())),
                ),
            )
            if not expected.deep_equals(updated_node.comparisons[0].comparator):
                self.changes += 1
                return updated_node.with_changes(
                    comparisons=(updated_node.comparisons[0].with_changes(comparator=expected),)
                )
        if (
            self.migration.domain in {"records", "task3_fixtures"}
            and self.path.endswith("tests/unit/test_graph_commands.py")
            and self._is_indexed_output_payload(original_node.left)
            and len(original_node.comparisons) == 1
            and isinstance(original_node.comparisons[0].operator, cst.Equal)
            and isinstance(original_node.comparisons[0].comparator, cst.Dict)
        ):
            keys = {
                _simple_string(element.key)
                for element in original_node.comparisons[0].comparator.elements
                if isinstance(element, cst.DictElement)
            }
            if {"record_id", "record_kind", "record_type"}.issubset(keys):
                self.changes += 1
                return updated_node.with_changes(left=self._record_payload(updated_node.left))
        return updated_node

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.BaseExpression:
        record_only_fields = {
            "record_type",
            "producer_node_id",
            "port",
            "schema",
            "value",
            "provenance",
        }
        if (
            self.migration.domain in {"records", "task3_fixtures"}
            and self.path.endswith("tests/unit/test_graph_commands.py")
            and self._is_indexed_output_payload(original_node.value)
            and len(original_node.slice) == 1
            and isinstance(original_node.slice[0].slice, cst.Index)
            and _simple_string(original_node.slice[0].slice.value) in record_only_fields
        ):
            self.changes += 1
            return updated_node.with_changes(value=self._record_payload(updated_node.value))
        return updated_node

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.BaseSmallStatement:
        module_name = get_full_name_for_node(original_node.module)
        route = self._imports.get(module_name or "")
        if route is None or isinstance(original_node.names, cst.ImportStar):
            return updated_node
        imported = {
            alias.name.value for alias in original_node.names if isinstance(alias.name, cst.Name)
        }
        if not imported.intersection(route.symbols):
            return updated_node
        if route.old_module == route.new_module:
            remaining = tuple(
                alias
                for alias in original_node.names
                if not (isinstance(alias.name, cst.Name) and alias.name.value in route.symbols)
            )
            self.changes += 1
            if not remaining:
                return cst.RemoveFromParent()
            return updated_node.with_changes(names=remaining)
        if not imported.issubset(route.symbols):
            # The containing statement splits mixed imports after child visits.
            return updated_node
        self.changes += 1
        return updated_node.with_changes(module=cst.parse_expression(route.new_module))

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.BaseStatement:
        function_name = self._function_stack.pop()
        if (
            self.migration.domain == "catalog_injection"
            and self.path.startswith("tests/")
            and (
                function_name in {"create_service", "_create_service"}
                or function_name.endswith("service_factory")
            )
        ):
            kwonly = tuple(
                parameter
                for parameter in updated_node.params.kwonly_params
                if parameter.name.value != "catalog"
            )
            if kwonly != updated_node.params.kwonly_params:
                self.changes += 1
                return updated_node.with_changes(
                    params=updated_node.params.with_changes(
                        kwonly_params=kwonly,
                        star_arg=(
                            updated_node.params.star_arg if kwonly else cst.MaybeSentinel.DEFAULT
                        ),
                    )
                )
        all_parameters = (*updated_node.params.params, *updated_node.params.kwonly_params)
        existing = {parameter.name.value for parameter in all_parameters}
        if self.migration.domain == "catalog_injection" and (
            function_name in self._functions_needing_catalog or "catalog" in existing
        ):
            if "catalog" not in existing and function_name != "create_app":
                self.changes += 1
                return updated_node.with_changes(
                    params=updated_node.params.with_changes(
                        kwonly_params=(
                            *updated_node.params.kwonly_params,
                            cst.Param(
                                cst.Name("catalog"),
                                annotation=cst.Annotation(cst.Name("GraphCatalog")),
                            ),
                        )
                    )
                )
            if "catalog" in existing:
                changed = False
                kwonly = []
                for parameter in updated_node.params.kwonly_params:
                    if parameter.name.value == "catalog" and parameter.annotation is None:
                        parameter = parameter.with_changes(
                            annotation=cst.Annotation(cst.Name("GraphCatalog"))
                        )
                        changed = True
                    kwonly.append(parameter)
                if changed:
                    self.changes += 1
                    return updated_node.with_changes(
                        params=updated_node.params.with_changes(kwonly_params=tuple(kwonly))
                    )
        if original_node.name.value in self.migration.remove_functions:
            self.changes += 1
            return cst.RemoveFromParent()
        consumer = self._allowlist_consumers.get(original_node.name.value)
        if consumer is not None:
            resolved_names = self._resolved_names(original_node.name)
            scope = self.get_metadata(metadata.ScopeProvider, original_node.name)
            expected_names = consumer.qualified_names or (consumer.function_name,)
            if self.migration.domain != "complete_reads" and (
                not resolved_names.intersection(expected_names)
                or not isinstance(scope, GlobalScope)
            ):
                consumer = None
        if consumer is not None:
            self.changes += 1
            return updated_node.with_changes(
                body=cst.IndentedBlock(
                    body=(
                        cst.SimpleStatementLine(
                            body=(
                                cst.Return(cst.parse_expression(consumer.replacement_expression)),
                            )
                        ),
                    )
                )
            )
        route = self._handlers.get(original_node.name.value)
        if route is None:
            return updated_node
        resolved_names = self._resolved_names(original_node.name)
        scope = self.get_metadata(metadata.ScopeProvider, original_node.name)
        if route.handler not in resolved_names or not isinstance(scope, GlobalScope):
            return updated_node
        changed = False
        parameters: list[cst.Param] = []
        for parameter in updated_node.params.params:
            if parameter.name.value in {"payload", "command"} and (
                parameter.annotation is None
                or not (
                    isinstance(parameter.annotation.annotation, cst.Name)
                    and parameter.annotation.annotation.value == route.payload_class
                )
            ):
                parameter = parameter.with_changes(
                    annotation=cst.Annotation(cst.Name(route.payload_class))
                )
                changed = True
            parameters.append(parameter)
        if not changed:
            return updated_node
        self.changes += 1
        return updated_node.with_changes(
            params=updated_node.params.with_changes(params=tuple(parameters))
        )

    def _event_replacement(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.Call | None:
        if not isinstance(original_node.func, (cst.Name, cst.Attribute)):
            return None
        if (
            self.path.startswith("tests/")
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "EventEnvelope"
        ):
            return None
        if isinstance(original_node.func, cst.Name) and original_node.func.value == "EventEnvelope":
            arguments = {
                argument.keyword.value: argument
                for argument in updated_node.args
                if argument.keyword is not None
            }
            event_type = arguments.get("event_type")
            event_name = _simple_string(event_type.value) if event_type is not None else None
            route = self._events.get(event_name or "")
            payload = arguments.get("payload")
            if route is not None and payload is not None:
                metadata_arguments: list[cst.Arg] = []
                for name in (
                    "event_id",
                    "run_id",
                    "position",
                    "event_type",
                    "actor",
                    "causation_id",
                    "correlation_id",
                    "timestamp",
                ):
                    argument = arguments.get(name)
                    if argument is not None:
                        metadata_arguments.append(argument)
                schema = arguments.get("schema_version")
                if schema is not None:
                    metadata_arguments.append(
                        schema.with_changes(keyword=cst.Name("payload_schema_generation"))
                    )
                self.changes += 1
                return cst.Call(
                    func=cst.Attribute(cst.Name(route.specification), cst.Name("create")),
                    args=(
                        cst.Arg(cst.Call(cst.Name("EventMetadata"), tuple(metadata_arguments))),
                        cst.Arg(
                            cst.Call(
                                cst.Attribute(
                                    cst.Name(route.payload_class), cst.Name("model_validate")
                                ),
                                (cst.Arg(payload.value),),
                            )
                        ),
                    ),
                )
        position = self._touch_metadata(original_node.func)
        resolved_names = self._resolved_names(original_node.func)
        direct_legacy_factory = (
            isinstance(original_node.func, cst.Name)
            and original_node.func.value == "make_event"
            and self.migration.domain in {"leases", "patches"}
        )
        if not direct_legacy_factory and not resolved_names.intersection(
            self.migration.event_factory_qualified_names
        ):
            return None
        if not original_node.args:
            return None
        event_name = _simple_string(original_node.args[0].value)
        if event_name is None:
            if self.migration.report_dynamic_emissions and not direct_legacy_factory:
                self.diagnostics.append(
                    CodemodDiagnostic(
                        self.path,
                        position.start.line,
                        position.start.column,
                        "W5AMBIGUOUS_EVENT",
                        "dynamic make_event name requires domain semantics",
                    )
                )
            return None
        route = self._events.get(event_name)
        if route is None or len(updated_node.args) < 2:
            return None
        payload = updated_node.args[1].value
        if (
            isinstance(payload, cst.Call)
            and isinstance(payload.func, cst.Attribute)
            and payload.func.attr.value == "model_dump"
            and isinstance(payload.func.value, cst.Call)
            and isinstance(payload.func.value.func, cst.Attribute)
            and payload.func.value.func.attr.value == "model_validate"
        ):
            payload = payload.func.value
        self.changes += 1
        replacement_arg = updated_node.args[1].with_changes(value=payload)
        if self.migration.domain == "topology":
            return updated_node.with_changes(
                func=cst.Name("typed_topology_event"),
                args=(
                    cst.Arg(updated_node.func),
                    updated_node.args[0],
                    updated_node.args[1].with_changes(value=payload),
                ),
            )
        if self.migration.domain in {"leases", "patches"}:
            return cst.Call(
                func=cst.Name("make_strict_event"),
                args=(
                    cst.Arg(updated_node.func),
                    cst.Arg(cst.Name(route.specification)),
                    replacement_arg,
                ),
            )
        return updated_node.with_changes(
            func=cst.Attribute(cst.Name(route.specification), cst.Name("create")),
            args=(replacement_arg,),
        )

    def _inject_catalog(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call | None:
        self._touch_metadata(original_node.func)
        resolved_names = self._resolved_names(original_node.func)
        routes = [
            route
            for route in self._catalog_injections
            if route.qualified_names and bool(resolved_names.intersection(route.qualified_names))
        ]
        if (
            not routes
            and self.migration.domain == "catalog_injection"
            and self.path.startswith("tests/")
        ):
            callable_name = (
                original_node.func.value
                if isinstance(original_node.func, cst.Name)
                else original_node.func.attr.value
                if isinstance(original_node.func, cst.Attribute)
                else None
            )
            routes = [
                route for route in self._catalog_injections if route.callable_name == callable_name
            ]
        if len(routes) != 1:
            return None
        route = routes[0]
        if route.callable_name == "GraphEventStore" and len(original_node.args) >= 2:
            return None
        if route.callable_name == "build_graph_command_dependencies" and original_node.args:
            return None
        argument_names = (route.argument_name, *route.additional_arguments)
        existing_names = {
            argument.keyword.value
            for argument in original_node.args
            if argument.keyword is not None
        }
        missing_names = tuple(name for name in argument_names if name not in existing_names)
        if not missing_names:
            return None
        self.changes += 1
        return updated_node.with_changes(
            args=(
                *updated_node.args,
                *(
                    cst.Arg(
                        (
                            cst.Call(cst.Name("build_graph_catalog"))
                            if name == "catalog"
                            else cst.Attribute(
                                cst.Call(cst.Name("build_graph_command_dependencies")),
                                cst.Name("future_effects"),
                            )
                        )
                        if route.factory_arguments
                        or (self.path.startswith("tests/") and name in {"catalog", "graph_catalog"})
                        else (
                            cst.Attribute(cst.Name("self"), cst.Name("_catalog"))
                            if name == "catalog" and self._class_stack
                            else cst.Name(name)
                        ),
                        keyword=cst.Name(name),
                        equal=cst.AssignEqual(
                            whitespace_before=cst.SimpleWhitespace(""),
                            whitespace_after=cst.SimpleWhitespace(""),
                        ),
                    )
                    for name in missing_names
                ),
            )
        )

    def _complete_lease_fixture(self, updated_node: cst.Call) -> cst.Call | None:
        """Make literal lease event and scheduling test seeds fully strict."""

        if self.migration.domain != "leases" or not self.path.startswith("tests/"):
            return None
        if not isinstance(updated_node.func, cst.Name) or updated_node.func.value not in {
            "_event",
            "_graph_event",
            "append_event",
        }:
            return None
        event_index = next(
            (
                index
                for index, argument in enumerate(updated_node.args)
                if _simple_string(argument.value)
                in {
                    "lease_granted",
                    "lease_renewed",
                    "lease_released",
                    "lease_revoked",
                    "lease_expired",
                }
            ),
            None,
        )
        if event_index is None or len(updated_node.args) <= event_index + 1:
            return None
        payload_argument = updated_node.args[event_index + 1]
        if not isinstance(payload_argument.value, cst.Dict):
            return None
        event_type = _simple_string(updated_node.args[event_index].value)
        additions_by_event = {
            "lease_granted": (
                ("lease_id", cst.SimpleString('"lease-test"')),
                ("node_id", cst.SimpleString('"node-test"')),
                ("generation", cst.Integer("0")),
                ("execution_id", cst.SimpleString('"exec-1"')),
                ("base_snapshot_id", cst.SimpleString('"S0"')),
                ("expires_at", cst.SimpleString('"2026-01-01T00:05:00+00:00"')),
                ("resource_claims", cst.List(elements=())),
            ),
            "lease_renewed": (
                ("lease_id", cst.SimpleString('"lease-test"')),
                ("node_id", cst.SimpleString('"node-test"')),
                ("generation", cst.Integer("0")),
                ("execution_id", cst.SimpleString('"exec-test"')),
                ("observed_at", cst.SimpleString('"2026-01-01T00:00:00+00:00"')),
                ("expires_at", cst.SimpleString('"2026-01-01T00:05:00+00:00"')),
            ),
            "lease_released": (
                ("lease_id", cst.SimpleString('"lease-test"')),
                ("node_id", cst.SimpleString('"node-test"')),
                ("generation", cst.Integer("0")),
            ),
            "lease_revoked": (
                ("lease_id", cst.SimpleString('"lease-test"')),
                ("node_id", cst.SimpleString('"node-test"')),
                ("generation", cst.Integer("0")),
                ("execution_id", cst.SimpleString('"exec-test"')),
                ("trigger", cst.SimpleString('"test_revocation"')),
                ("reason", cst.SimpleString('"test_revocation"')),
            ),
            "lease_expired": (
                ("lease_id", cst.SimpleString('"lease-test"')),
                ("node_id", cst.SimpleString('"node-test"')),
                ("generation", cst.Integer("0")),
                ("execution_id", cst.SimpleString('"exec-test"')),
                ("expires_at", cst.SimpleString('"2026-01-01T00:00:00+00:00"')),
                ("reason", cst.SimpleString('"test_expiry"')),
            ),
        }
        completed = _append_missing_dict_fields(
            payload_argument.value, additions_by_event.get(event_type, ())
        )
        if event_type == "lease_granted":
            lease_id = next(
                (
                    _simple_string(element.value)
                    for element in completed.elements
                    if element is not None and _simple_string(element.key) == "lease_id"
                ),
                None,
            )
            inferred_execution_id = (
                f"exec-{lease_id.removeprefix('lease-')}" if lease_id is not None else "exec-1"
            )
            completed = completed.with_changes(
                elements=tuple(
                    element.with_changes(value=cst.SimpleString(f'"{inferred_execution_id}"'))
                    if element is not None
                    and _simple_string(element.key) == "execution_id"
                    and _simple_string(element.value) in {"exec-test", "exec-1"}
                    else element
                    for element in completed.elements
                )
            )
        if completed == payload_argument.value:
            return None
        self.changes += 1
        return updated_node.with_changes(
            args=(
                *updated_node.args[: event_index + 1],
                payload_argument.with_changes(value=completed),
                *updated_node.args[event_index + 2 :],
            )
        )

    def _complete_schedule_fixture(self, updated_node: cst.Call) -> cst.Call | None:
        if self.migration.domain != "leases" or not self.path.startswith("tests/"):
            return None
        command_index = next(
            (
                index
                for index, argument in enumerate(updated_node.args)
                if _simple_string(argument.value) == "schedule_tick"
            ),
            None,
        )
        if command_index is None or len(updated_node.args) <= command_index + 1:
            return None
        payload_argument = updated_node.args[command_index + 1]
        if not isinstance(payload_argument.value, cst.Dict):
            return None
        completed = _append_missing_dict_fields(
            payload_argument.value,
            (
                ("lease_seconds", cst.Integer("300")),
                ("max_grants", cst.Integer("10")),
            ),
        )
        if completed == payload_argument.value:
            return None
        self.changes += 1
        return updated_node.with_changes(
            args=(
                *updated_node.args[: command_index + 1],
                payload_argument.with_changes(value=completed),
                *updated_node.args[command_index + 2 :],
            )
        )

    def _complete_patch_fixture(self, updated_node: cst.Call) -> cst.Call | None:
        if self.migration.domain != "patches" or not self.path.startswith("tests/"):
            return None
        if not isinstance(updated_node.func, cst.Name) or updated_node.func.value not in {
            "_event",
            "_graph_event",
            "append_event",
        }:
            return None
        event_index = next(
            (
                index
                for index, argument in enumerate(updated_node.args)
                if _simple_string(argument.value)
                in {"graph_patch_accepted", "graph_patch_rejected"}
            ),
            None,
        )
        if event_index is None or len(updated_node.args) <= event_index + 1:
            return None
        payload_argument = updated_node.args[event_index + 1]
        if not isinstance(payload_argument.value, cst.Dict):
            return None
        event_type = _simple_string(updated_node.args[event_index].value)
        additions = (
            ("patch_id", cst.SimpleString('"patch-test"')),
            ("base_graph_position", cst.UnaryOperation(cst.Minus(), cst.Integer("1"))),
            ("actor_role", cst.SimpleString('"planner"')),
            ("proposed_by_node_id", cst.SimpleString('"planner-test"')),
        )
        if event_type == "graph_patch_accepted":
            additions = (*additions, ("successor_planner_node_ids", cst.List(elements=())))
        else:
            additions = (*additions, ("reason", cst.SimpleString('"test_rejection"')))
        completed = _append_missing_dict_fields(payload_argument.value, additions)
        if completed == payload_argument.value:
            return None
        self.changes += 1
        return updated_node.with_changes(
            args=(
                *updated_node.args[: event_index + 1],
                payload_argument.with_changes(value=completed),
                *updated_node.args[event_index + 2 :],
            )
        )

    def _complete_submit_patch_fixture(self, updated_node: cst.Call) -> cst.Call | None:
        if self.migration.domain != "patches" or not self.path.startswith("tests/"):
            return None
        command_index = next(
            (
                index
                for index, argument in enumerate(updated_node.args)
                if _simple_string(argument.value) == "submit_patch"
            ),
            None,
        )
        if command_index is None or len(updated_node.args) <= command_index + 1:
            return None
        payload_argument = updated_node.args[command_index + 1]
        if not isinstance(payload_argument.value, cst.Dict):
            return None
        completed = _append_missing_dict_fields(
            payload_argument.value,
            (("actor_role", cst.SimpleString('"planner"')),),
        )
        if completed == payload_argument.value:
            return None
        self.changes += 1
        return updated_node.with_changes(
            args=(
                *updated_node.args[: command_index + 1],
                payload_argument.with_changes(value=completed),
                *updated_node.args[command_index + 2 :],
            )
        )

    def leave_DictComp(
        self, original_node: cst.DictComp, updated_node: cst.DictComp
    ) -> cst.BaseExpression:
        normalized = "".join(cst.Module(body=()).code_for_node(original_node).split())
        if self.migration.domain == "patches" and self.path.endswith(
            "src/orchestrator/graph_runtime/controller.py"
        ):
            if normalized == (
                '{key:valueforkey,valueindict(payloador{}).items()ifkey!="run_id"and'
                '(command_type=="submit_patch"orkey!="actor_role")}'
            ):
                return updated_node
            self.changes += 1
            return cst.parse_expression(
                "{key: value for key, value in dict(payload or {}).items() "
                'if key != "run_id" and (command_type == "submit_patch" or key != "actor_role")}'
            )
        if (
            self.migration.domain == "patches"
            and self.path.endswith(
                ("tests/unit/test_graph_commands.py", "src/orchestrator/graph/scenario.py")
            )
            and normalized
            in {
                '{key:valueforkey,valueinraw_payload.items()ifkeynotin{"run_id","actor_role"}}',
                '{key:valueforkey,valueincommand_payload.items()ifkeynotin{"run_id","actor_role"}}',
                '{key:valueforkey,valueindict(payloador{}).items()ifkeynotin{"run_id","actor_role"}}',
            }
        ):
            self.changes += 1
            payload_source = (
                "command_payload"
                if "command_payload.items()" in normalized
                else "dict(payload or {})"
                if "dict(payloador{}).items()" in normalized
                else "raw_payload"
            )
            return cst.parse_expression(
                f"{{key: value for key, value in {payload_source}.items() "
                'if key != "run_id" and (command_type == "submit_patch" or key != "actor_role")}'
            )
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        if (
            self.migration.domain == "catalog_injection"
            and not self.path.endswith("src/orchestrator/api/app.py")
            and not self.path.endswith("src/orchestrator/cli/main.py")
            and not self.path.startswith("tests/")
            and self._resolved_names(original_node.func).intersection(
                {
                    "orchestrator.graph.build_graph_catalog",
                    "orchestrator.graph.catalog.build_graph_catalog",
                }
            )
        ):
            self.changes += 1
            if self._function_stack and not self._class_stack:
                self._functions_needing_catalog.add(self._function_stack[-1])
            if self._class_stack:
                return cst.Attribute(cst.Name("self"), cst.Name("_catalog"))
            return cst.Name("catalog")
        if (
            self.migration.domain == "catalog_cutover"
            and self.path.startswith(("src/orchestrator/graph/", "src/orchestrator/graph_runtime/"))
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "apply_command"
            and len(original_node.args) == 8
        ):
            positional = [argument for argument in updated_node.args if argument.keyword is None]
            keywords = {
                argument.keyword.value: argument
                for argument in updated_node.args
                if argument.keyword is not None
            }
            catalog = keywords.get("catalog")
            context = keywords.get("context")
            if (
                len(positional) == 6
                and catalog is not None
                and context is not None
                and len(keywords) == 2
            ):
                self.changes += 1
                return updated_node.with_changes(
                    args=(
                        cst.Arg(catalog.value),
                        *positional[:4],
                        cst.Arg(context.value),
                    )
                )
        completed_lease_fixture = self._complete_lease_fixture(updated_node)
        if completed_lease_fixture is not None:
            return completed_lease_fixture
        completed_patch_fixture = self._complete_patch_fixture(updated_node)
        if completed_patch_fixture is not None:
            return completed_patch_fixture
        completed_submit_patch_fixture = self._complete_submit_patch_fixture(updated_node)
        if completed_submit_patch_fixture is not None:
            return completed_submit_patch_fixture
        completed_schedule_fixture = self._complete_schedule_fixture(updated_node)
        if completed_schedule_fixture is not None:
            return completed_schedule_fixture
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith(
                (
                    "tests/integration/test_graph_event_store.py",
                    "tests/integration/test_graph_read_models.py",
                    "tests/integration/test_graph_node_detail_read_models.py",
                )
            )
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "_event"
            and len(updated_node.args) >= 4
            and _simple_string(updated_node.args[2].value) == "output_record_accepted"
            and isinstance(updated_node.args[3].value, cst.Dict)
        ):
            record = updated_node.args[3].value
            if _is_nested_record_payload(record):
                completed_record = record
                changed = False
                for complete in (
                    _complete_task3_strict_record_payload,
                    _complete_sparse_check_result_record_payload,
                    _complete_sparse_candidate_record_payload,
                ):
                    completed = complete(completed_record)
                    if completed is not None:
                        completed_record = completed
                        changed = True
                if not changed:
                    return updated_node
                self.changes += 1
                return updated_node.with_changes(
                    args=(
                        *updated_node.args[:3],
                        updated_node.args[3].with_changes(value=completed_record),
                        *updated_node.args[4:],
                    )
                )
            fields = _dict_elements_by_key(record)
            schema = (
                _simple_string(fields.get("schema").value)
                if fields.get("schema") is not None
                else None
            )
            port = (
                _simple_string(fields.get("port").value) if fields.get("port") is not None else None
            )
            record_types = {
                "candidate": "candidate",
                "verification_report": "verification_report",
                "check_result": "check_result",
                "decision_request": "decision_request",
                "authority_request_record": "authority_request_record",
                "failure_record": "failure_record",
                "recovery_plan": "recovery_plan",
                "run_context": "run_context",
                "snapshot": "routine_snapshot",
                "artifact": "artifact_reference",
            }
            additions: list[tuple[str, cst.BaseExpression]] = []
            record_type = record_types.get(port or "")
            if record_type is not None:
                additions.append(("record_type", cst.SimpleString(f'"{record_type}"')))
            record_id = fields.get("record_id")
            if schema == "ImplementationCandidate" and record_id is not None:
                if record_type is None:
                    additions.append(("record_type", cst.SimpleString('"candidate"')))
                additions.append(("candidate_id", record_id.value))
            if schema is None and port == "result":
                additions.append(("schema", cst.SimpleString('"OutputRecord"')))
            if schema == "CheckResult":
                additions.append(("task_region_id", cst.SimpleString('"task-test"')))
            completed_record = _append_missing_dict_fields(record, tuple(additions))
            nested: cst.BaseExpression = cst.Dict(
                elements=(cst.DictElement(cst.SimpleString('"record"'), completed_record),)
            )
            for complete in (
                _complete_task3_strict_record_payload,
                _complete_sparse_check_result_record_payload,
                _complete_sparse_candidate_record_payload,
            ):
                completed = complete(nested)
                if completed is not None:
                    nested = completed
            self.changes += 1
            return updated_node.with_changes(
                args=(
                    *updated_node.args[:3],
                    updated_node.args[3].with_changes(value=nested),
                    *updated_node.args[4:],
                )
            )
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith("tests/unit/test_graph_planner_packet.py")
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "_event"
            and len(updated_node.args) >= 2
            and _simple_string(updated_node.args[0].value) == "session_state_changed"
            and isinstance(updated_node.args[1].value, cst.Dict)
            and not any(
                isinstance(element, cst.DictElement)
                and _simple_string(element.key) == "lease_generation"
                for element in updated_node.args[1].value.elements
            )
        ):
            payload = updated_node.args[1].value
            self.changes += 1
            completed = payload.with_changes(
                elements=(
                    cst.DictElement(
                        cst.SimpleString('"lease_generation"'),
                        cst.Integer("3"),
                    ),
                    *payload.elements,
                )
            )
            return updated_node.with_changes(
                args=(
                    updated_node.args[0],
                    updated_node.args[1].with_changes(value=completed),
                    *updated_node.args[2:],
                )
            )
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith(
                (
                    "tests/integration/test_graph_default_carrier.py",
                    "tests/integration/test_graph_dynamic_e2e.py",
                )
            )
            and isinstance(original_node.func, cst.Attribute)
            and original_node.func.attr.value == "get"
            and isinstance(original_node.func.value, cst.Attribute)
            and isinstance(original_node.func.value.value, cst.Name)
            and original_node.func.value.value.value == "event"
            and original_node.func.value.attr.value == "payload"
            and updated_node.args
            and _simple_string(updated_node.args[0].value) in {"record_type", "value"}
        ):
            self.changes += 1
            return updated_node.with_changes(
                func=updated_node.func.with_changes(
                    value=cst.Subscript(
                        value=updated_node.func.value,
                        slice=(
                            cst.SubscriptElement(
                                slice=cst.Index(value=cst.SimpleString('"record"')),
                            ),
                        ),
                    )
                )
            )
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith(
                (
                    "tests/unit/test_graph_planner.py",
                    "tests/unit/test_graph_planner_packet.py",
                )
            )
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "_event"
            and len(updated_node.args) >= 2
            and _simple_string(updated_node.args[0].value) == "node_created"
        ):
            payload = _task3_routine_snapshot_record(updated_node.args[1].value)
            if payload is not None:
                self.changes += 1
                return updated_node.with_changes(
                    args=(
                        updated_node.args[0].with_changes(
                            value=cst.SimpleString('"output_record_accepted"')
                        ),
                        updated_node.args[1].with_changes(value=payload),
                        *updated_node.args[2:],
                    )
                )
        if (
            self.migration.domain == "task3_fixtures"
            and self.path.endswith(
                (
                    "tests/unit/test_graph_commands.py",
                    "tests/unit/test_graph_planner_packet.py",
                )
            )
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "_event"
            and len(updated_node.args) >= 2
            and _simple_string(updated_node.args[0].value) == "input_bound"
            and isinstance(updated_node.args[1].value, cst.Dict)
        ):
            payload = updated_node.args[1].value
            keyed = {
                _simple_string(element.key): element
                for element in payload.elements
                if isinstance(element, cst.DictElement)
            }
            additions: list[cst.DictElement] = []
            if "edge_id" not in keyed:
                to_node = keyed.get("to_node_id")
                to_port = keyed.get("to_port")
                node_value = _simple_string(to_node.value) if to_node is not None else None
                port_value = _simple_string(to_port.value) if to_port is not None else None
                if node_value is not None and port_value is not None:
                    additions.append(
                        cst.DictElement(
                            cst.SimpleString('"edge_id"'),
                            cst.SimpleString(f'"edge-{node_value}-{port_value}"'),
                        )
                    )
            if "bound_at_position" not in keyed:
                additions.append(
                    cst.DictElement(cst.SimpleString('"bound_at_position"'), cst.Integer("0"))
                )
            if "record_ids" not in keyed:
                additions.append(
                    cst.DictElement(cst.SimpleString('"record_ids"'), cst.List(elements=()))
                )
            if additions:
                self.changes += len(additions)
                completed = payload.with_changes(elements=(*additions, *payload.elements))
                return updated_node.with_changes(
                    args=(
                        updated_node.args[0],
                        updated_node.args[1].with_changes(value=completed),
                        *updated_node.args[2:],
                    )
                )
        if (
            self.migration.domain in {"records", "task3_fixtures"}
            and (
                (
                    isinstance(original_node.func, cst.Name)
                    and original_node.func.value in {"make_event", "_event"}
                )
                or (
                    isinstance(original_node.func, cst.Attribute)
                    and original_node.func.attr.value == "_event"
                )
            )
            and len(updated_node.args) >= 2
            and _simple_string(updated_node.args[0].value) == "output_record_accepted"
        ):
            payload = updated_node.args[1].value
            if self.migration.domain == "task3_fixtures":
                completed_task3_record = _complete_task3_strict_record_payload(payload)
                if completed_task3_record is not None:
                    self.changes += 1
                    return updated_node.with_changes(
                        args=(
                            updated_node.args[0],
                            updated_node.args[1].with_changes(value=completed_task3_record),
                            *updated_node.args[2:],
                        )
                    )
            completed_check_result = _complete_sparse_check_result_record_payload(payload)
            if completed_check_result is not None:
                self.changes += 1
                return updated_node.with_changes(
                    args=(
                        updated_node.args[0],
                        updated_node.args[1].with_changes(value=completed_check_result),
                        *updated_node.args[2:],
                    )
                )
            completed_candidate = _complete_sparse_candidate_record_payload(payload)
            if completed_candidate is not None:
                self.changes += 1
                return updated_node.with_changes(
                    args=(
                        updated_node.args[0],
                        updated_node.args[1].with_changes(value=completed_candidate),
                        *updated_node.args[2:],
                    )
                )
            if self.migration.domain == "records":
                completed_record = _complete_task3_strict_record_payload(payload)
                if completed_record is not None:
                    self.changes += 1
                    return updated_node.with_changes(
                        args=(
                            updated_node.args[0],
                            updated_node.args[1].with_changes(value=completed_record),
                            *updated_node.args[2:],
                        )
                    )
            if not _is_nested_record_payload(payload):
                if (
                    self.migration.domain == "records"
                    and isinstance(original_node.func, cst.Name)
                    and original_node.func.value == "make_event"
                ):
                    self.changes += 1
                    nested = cst.Dict(
                        elements=(
                            cst.DictElement(
                                key=cst.SimpleString('"record"'),
                                value=updated_node.args[1].value,
                            ),
                        )
                    )
                    return cst.Call(
                        func=cst.Name("make_strict_event"),
                        args=(
                            cst.Arg(cst.Name("make_event")),
                            cst.Arg(cst.Name("OUTPUT_RECORD_ACCEPTED")),
                            cst.Arg(nested),
                        ),
                    )
                self.changes += 1
                nested = cst.Dict(
                    elements=(
                        cst.DictElement(
                            key=cst.SimpleString('"record"'),
                            value=payload,
                        ),
                    )
                )
                return updated_node.with_changes(
                    args=(
                        updated_node.args[0],
                        updated_node.args[1].with_changes(value=nested),
                        *updated_node.args[2:],
                    )
                )
            if (
                self.migration.domain == "records"
                and isinstance(original_node.func, cst.Name)
                and original_node.func.value == "make_event"
            ):
                self.changes += 1
                return cst.Call(
                    func=cst.Name("make_strict_event"),
                    args=(
                        cst.Arg(cst.Name("make_event")),
                        cst.Arg(cst.Name("OUTPUT_RECORD_ACCEPTED")),
                        updated_node.args[1],
                    ),
                )
        if self.migration.domain == "records" and isinstance(original_node.func, cst.Name):
            if original_node.func.value == "EventEnvelope":
                keywords = {
                    arg.keyword.value: arg for arg in updated_node.args if arg.keyword is not None
                }
                event_type = keywords.get("event_type")
                payload = keywords.get("payload")
                if (
                    event_type is not None
                    and _simple_string(event_type.value) == "output_record_accepted"
                    and payload is not None
                ):
                    if _is_nested_record_payload(payload.value):
                        return updated_node
                    self.changes += 1
                    nested = cst.Dict(
                        elements=(
                            cst.DictElement(
                                key=cst.SimpleString('"record"'),
                                value=payload.value,
                            ),
                        )
                    )
                    return updated_node.with_changes(
                        args=tuple(
                            arg.with_changes(value=nested)
                            if arg.keyword is not None and arg.keyword.value == "payload"
                            else arg
                            for arg in updated_node.args
                        )
                    )
                if (
                    event_type is not None
                    and payload is not None
                    and isinstance(event_type.value, cst.Name)
                    and isinstance(payload.value, cst.Name)
                    and payload.value.value == "payload"
                ):
                    self.changes += 1
                    nested = cst.parse_expression(
                        '{"record": payload} if event_type == "output_record_accepted" and not (isinstance(payload, dict) and "record" in payload) else payload'
                    )
                    return updated_node.with_changes(
                        args=tuple(
                            arg.with_changes(value=nested)
                            if arg.keyword is not None and arg.keyword.value == "payload"
                            else arg
                            for arg in updated_node.args
                        )
                    )
                if (
                    event_type is not None
                    and payload is not None
                    and isinstance(event_type.value, cst.Name)
                    and isinstance(payload.value, cst.IfExp)
                    and isinstance(payload.value.test, cst.Comparison)
                ):
                    self.changes += 1
                    nested = cst.parse_expression(
                        '{"record": payload} if event_type == "output_record_accepted" and not (isinstance(payload, dict) and "record" in payload) else payload'
                    )
                    return updated_node.with_changes(
                        args=tuple(
                            arg.with_changes(value=nested)
                            if arg.keyword is not None and arg.keyword.value == "payload"
                            else arg
                            for arg in updated_node.args
                        )
                    )
        if (
            self.migration.domain == "complete_reads"
            and isinstance(original_node.func, cst.Name)
            and original_node.func.value == "_node_detail_light_event"
            and len(updated_node.args) == 1
        ):
            self.changes += 1
            return updated_node.args[0].value
        event = self._event_replacement(original_node, updated_node)
        if event is not None:
            return event
        injection = self._inject_catalog(original_node, updated_node)
        if (
            injection is not None
            and self.migration.domain == "catalog_injection"
            and self._function_stack
            and not self._class_stack
            and not self.path.startswith("tests/")
        ):
            self._functions_needing_catalog.add(self._function_stack[-1])
        return injection if injection is not None else updated_node

    def leave_Arg(self, original_node: cst.Arg, updated_node: cst.Arg) -> cst.Arg:
        if (
            self.migration.domain == "catalog_injection"
            and self.path.startswith("tests/")
            and original_node.keyword is not None
            and original_node.keyword.value == "graph_catalog"
            and isinstance(original_node.value, cst.Name)
            and original_node.value.value in {"graph_catalog", "catalog"}
        ):
            self.changes += 1
            return updated_node.with_changes(value=cst.Call(cst.Name("build_graph_catalog")))
        return updated_node

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        if (
            self.migration.domain == "patches"
            and self.path == "tests/graph_command_support.py"
            and cst.Module(body=()).code_for_node(original_node).strip()
            == 'actor_role = raw_payload.pop("actor_role", None)'
        ):
            self.changes += 1
            return cst.FlattenSentinel(
                (
                    cst.parse_statement('actor_role = raw_payload.get("actor_role")\n'),
                    cst.parse_statement(
                        'if command_type != "submit_patch":\n'
                        '    raw_payload.pop("actor_role", None)\n'
                    ),
                )
            )
        if len(original_node.body) == 1 and isinstance(original_node.body[0], cst.ImportFrom):
            original_import = original_node.body[0]
            module_name = get_full_name_for_node(original_import.module)
            route = self._imports.get(module_name or "")
            if route is not None and not isinstance(original_import.names, cst.ImportStar):
                selected = [
                    alias
                    for alias in original_import.names
                    if isinstance(alias.name, cst.Name) and alias.name.value in route.symbols
                ]
                remaining = [alias for alias in original_import.names if alias not in selected]
                if selected and remaining:
                    if route.old_module == route.new_module:
                        self.changes += 1
                        return updated_node.with_changes(
                            body=(original_import.with_changes(names=tuple(remaining)),)
                        )

                    def aliases(
                        values: list[cst.ImportAlias],
                    ) -> tuple[cst.ImportAlias, ...]:
                        if original_import.lpar:
                            return tuple(values)
                        return tuple(
                            cst.ImportAlias(
                                name=item.name,
                                asname=item.asname,
                                comma=(
                                    cst.Comma()
                                    if index < len(values) - 1
                                    else cst.MaybeSentinel.DEFAULT
                                ),
                            )
                            for index, item in enumerate(values)
                        )

                    old_import = original_import.with_changes(names=aliases(remaining))
                    new_import = original_import.with_changes(
                        module=cst.parse_expression(route.new_module),
                        names=aliases(selected),
                    )
                    self.changes += 1
                    return cst.FlattenSentinel(
                        (
                            updated_node.with_changes(body=(old_import,)),
                            cst.SimpleStatementLine(body=(new_import,)),
                        )
                    )
        if len(original_node.body) != 1 or not isinstance(
            original_node.body[0], (cst.Assign, cst.AnnAssign)
        ):
            return updated_node
        assignment = original_node.body[0]
        name = _assigned_name(assignment)
        if name == "_LIFECYCLE_EVENT_PAYLOAD_MODELS" and isinstance(assignment.value, cst.Dict):
            remaining = tuple(
                element
                for element in assignment.value.elements
                if element is not None and _simple_string(element.key) not in self._events
            )
            if len(remaining) != len(assignment.value.elements):
                self.changes += 1
                replacement = assignment.with_changes(
                    value=assignment.value.with_changes(elements=remaining)
                )
                return updated_node.with_changes(body=(replacement,))
        if name in {"COMMAND_HANDLERS", "_UNCONVERTED_W5_BRIDGE", "COMMAND_SPECIFICATIONS"}:
            target = (
                assignment.target
                if isinstance(assignment, cst.AnnAssign)
                else assignment.targets[0].target
            )
            scope = self.get_metadata(metadata.ScopeProvider, target)
            if not isinstance(scope, GlobalScope):
                return updated_node
            if self._blocked_command_specs:
                return updated_node
        if name == "COMMAND_SPECIFICATIONS" and self._will_compose_command_specs:
            self.changes += 1
            return cst.RemoveFromParent()
        if name in self.migration.allowlist_names:
            if name in self._blocked_allowlists:
                return updated_node
            self.changes += 1
            return cst.RemoveFromParent()
        if name not in {"COMMAND_HANDLERS", "_UNCONVERTED_W5_BRIDGE"} or not isinstance(
            assignment.value, cst.Dict
        ):
            return updated_node
        routes: list[CommandRoute] = []
        remaining_elements: list[cst.DictElement] = []
        for element in assignment.value.elements:
            if element is None or isinstance(element, cst.StarredDictElement):
                return updated_node
            command_name = _simple_string(element.key)
            route = self._commands.get(command_name or "")
            if route is None:
                remaining_elements.append(element)
            else:
                routes.append(route)
        if not routes:
            return updated_node
        specification_names = list(self._existing_command_specs)
        specification_names.extend(
            route.specification
            for route in routes
            if route.specification not in specification_names
        )
        elements = tuple(
            cst.Element(
                cst.Name(specification),
                comma=cst.Comma(
                    whitespace_after=(
                        cst.SimpleWhitespace(" ")
                        if index < len(specification_names) - 1
                        else cst.SimpleWhitespace("")
                    )
                ),
            )
            for index, specification in enumerate(specification_names)
        )
        specification_assignment = cst.Assign(
            targets=(cst.AssignTarget(cst.Name("COMMAND_SPECIFICATIONS")),),
            value=cst.Tuple(elements),
        )
        self.changes += 1
        self._composed_command_specs = True
        specification_line = updated_node.with_changes(body=(specification_assignment,))
        if not remaining_elements:
            return specification_line
        normalized_remaining = tuple(
            element.with_changes(
                comma=cst.Comma(
                    whitespace_after=cst.ParenthesizedWhitespace(
                        first_line=cst.TrailingWhitespace(),
                        indent=True,
                        last_line=cst.SimpleWhitespace("    "),
                    )
                )
            )
            for element in remaining_elements
        )
        handlers_assignment = updated_node.body[0].with_changes(
            value=assignment.value.with_changes(elements=normalized_remaining)
        )
        return cst.FlattenSentinel(
            (
                updated_node.with_changes(body=(handlers_assignment,)),
                specification_line,
            )
        )


class _AddExports(cst.CSTTransformer):
    def __init__(self, symbols: Iterable[str]) -> None:
        self.symbols = tuple(symbols)

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.BaseSmallStatement:
        if _assigned_name(original_node) != "__all__" or not isinstance(
            original_node.value, (cst.List, cst.Tuple)
        ):
            return updated_node
        existing = {
            value
            for element in original_node.value.elements
            if element is not None and (value := _simple_string(element.value)) is not None
        }
        additions = [symbol for symbol in self.symbols if symbol not in existing]
        if not additions:
            return updated_node
        elements = [*updated_node.value.elements]
        elements.extend(cst.Element(cst.SimpleString(f'"{symbol}"')) for symbol in additions)
        return updated_node.with_changes(
            value=updated_node.value.with_changes(elements=tuple(elements))
        )


class _RemoveExports(cst.CSTTransformer):
    def __init__(self, symbols: Iterable[str]) -> None:
        self.symbols = frozenset(symbols)

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        if len(original_node.body) != 1 or not isinstance(
            original_node.body[0], (cst.Assign, cst.AnnAssign)
        ):
            return updated_node
        assignment = original_node.body[0]
        if _assigned_name(assignment) != "__all__" or not isinstance(
            assignment.value, (cst.List, cst.Tuple)
        ):
            return updated_node
        elements = tuple(
            element
            for element in assignment.value.elements
            if element is not None and _simple_string(element.value) not in self.symbols
        )
        if not elements:
            return cst.RemoveFromParent()
        replacement = updated_node.body[0].with_changes(
            value=assignment.value.with_changes(elements=elements)
        )
        return updated_node.with_changes(body=(replacement,))


class _NameCollector(cst.CSTVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: cst.Name) -> None:
        self.names.add(node.value)


def _imported_names(statement: cst.BaseStatement) -> frozenset[str]:
    if not isinstance(statement, cst.SimpleStatementLine) or len(statement.body) != 1:
        return frozenset()
    item = statement.body[0]
    if isinstance(item, cst.ImportFrom) and not isinstance(item.names, cst.ImportStar):
        return frozenset(
            alias.asname.name.value
            if alias.asname is not None
            else get_full_name_for_node(alias.name).split(".")[-1]
            for alias in item.names
        )
    if isinstance(item, cst.Import):
        return frozenset(
            alias.asname.name.value
            if alias.asname is not None
            else get_full_name_for_node(alias.name).split(".")[0]
            for alias in item.names
        )
    return frozenset()


class StrictPayloadCutoverCodemod:
    """Apply one domain's mechanically safe LibCST transformations."""

    def __init__(self, migration: DomainMigration) -> None:
        self.migration = migration

    def transform_source(self, source: str, path: str = "<memory>") -> TransformResult:
        module = cst.parse_module(source)
        tree = ast.parse(source, filename=path)
        ast_parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                ast_parents[child] = parent
        configured_consumers = {
            qualified_name
            for consumer in self.migration.allowlist_consumers
            for qualified_name in (consumer.qualified_names or (consumer.function_name,))
        }
        blocked_allowlists: set[str] = set()
        initial_diagnostics: list[CodemodDiagnostic] = []
        if self.migration.domain == "catalog_cutover":
            initial_diagnostics.extend(_catalog_cutover_diagnostics(tree, path, ast_parents))
        initial_diagnostics.extend(
            CodemodDiagnostic(
                path,
                1,
                0,
                "W5UNQUALIFIED_CATALOG_ROUTE",
                f"catalog injection {route.callable_name} requires qualified_names",
            )
            for route in self.migration.catalog_injections
            if not route.qualified_names and not route.test_only_unqualified
        )
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in self.migration.allowlist_names
            ):
                continue
            current: ast.AST = node
            owner_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
            while current in ast_parents:
                current = ast_parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner_node = current
                    break
            owner: str | None = None
            if owner_node is not None:
                classes: list[str] = []
                current = owner_node
                while current in ast_parents:
                    current = ast_parents[current]
                    if isinstance(current, ast.ClassDef):
                        classes.append(current.name)
                owner = ".".join((*reversed(classes), owner_node.name))
            if owner in self.migration.allowed_allowlist_owners or (
                owner is None and path.endswith("graph_runtime/store.py")
            ):
                continue
            if owner in configured_consumers:
                continue
            blocked_allowlists.add(node.id)
            initial_diagnostics.append(
                CodemodDiagnostic(
                    path,
                    node.lineno,
                    node.col_offset,
                    "W5ALLOWLIST_REFERENCE",
                    f"unconfigured consumer of {node.id}",
                )
            )
        existing_command_specs: tuple[str, ...] = ()
        specification_assignments: list[cst.Assign | cst.AnnAssign] = []
        noncanonical_specifications = False
        specification_assignment_lines = [
            node.lineno
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "COMMAND_SPECIFICATIONS"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
        ]
        command_route_names = {
            route.command_name
            for route in self.migration.command_routes
            if self.migration.transform_commands
        }
        will_compose_command_specs = False
        for statement in module.body:
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for item in statement.body:
                if (
                    isinstance(item, (cst.Assign, cst.AnnAssign))
                    and _assigned_name(item) == "COMMAND_SPECIFICATIONS"
                ):
                    specification_assignments.append(item)
                    canonical = isinstance(item.value, cst.Tuple) and all(
                        element is not None
                        and isinstance(element, cst.Element)
                        and isinstance(element.value, cst.Name)
                        for element in item.value.elements
                    )
                    if canonical and isinstance(item.value, cst.Tuple):
                        existing_command_specs = tuple(
                            element.value.value
                            for element in item.value.elements
                            if element is not None
                            and isinstance(element, cst.Element)
                            and isinstance(element.value, cst.Name)
                        )
                    else:
                        noncanonical_specifications = True
                if (
                    isinstance(item, (cst.Assign, cst.AnnAssign))
                    and _assigned_name(item) in {"COMMAND_HANDLERS", "_UNCONVERTED_W5_BRIDGE"}
                    and isinstance(item.value, cst.Dict)
                ):
                    will_compose_command_specs = any(
                        element is not None
                        and not isinstance(element, cst.StarredDictElement)
                        and _simple_string(element.key) in command_route_names
                        for element in item.value.elements
                    )
        if len(specification_assignments) > 1:
            initial_diagnostics.extend(
                CodemodDiagnostic(
                    path,
                    line,
                    0,
                    "W5DUPLICATE_COMMAND_SPECIFICATIONS",
                    "multiple COMMAND_SPECIFICATIONS assignments cannot be composed safely",
                )
                for line in specification_assignment_lines
            )
        if (
            noncanonical_specifications
            and self.migration.domain != "catalog_cutover"
            and self.migration.command_routes
        ):
            initial_diagnostics.extend(
                CodemodDiagnostic(
                    path,
                    line,
                    0,
                    "W5NONCANONICAL_COMMAND_SPECIFICATIONS",
                    "COMMAND_SPECIFICATIONS must be a tuple of bare specification names",
                )
                for line in specification_assignment_lines
            )
            will_compose_command_specs = False
        transformer = _MechanicalTransformer(
            self.migration,
            path,
            existing_command_specs,
            will_compose_command_specs,
            noncanonical_specifications or len(specification_assignments) > 1,
            frozenset(blocked_allowlists),
            tuple(initial_diagnostics),
        )
        transformed = metadata.MetadataWrapper(module).visit(transformer)
        return TransformResult(
            source=transformed.code,
            diagnostics=tuple(sorted(transformer.diagnostics)),
            changes=transformer.changes,
        )

    def transform_files(self, sources: Mapping[str, str]) -> FileTransformResult:
        working = dict(sources)
        diagnostics: list[CodemodDiagnostic] = []
        relocation_targets = {relocation.target_path for relocation in self.migration.relocations}
        for path in self.migration.paths:
            if path not in working and path not in relocation_targets:
                diagnostics.append(
                    CodemodDiagnostic(
                        path,
                        1,
                        0,
                        "W5MISSING_FILE",
                        f"configured path does not exist: {path}",
                    )
                )
        relocation_changes = 0
        relocation_by_symbol = {
            relocation.symbol: relocation for relocation in self.migration.relocations
        }
        by_source: dict[str, list[SymbolRelocation]] = {}
        for relocation in self.migration.relocations:
            by_source.setdefault(relocation.source_path, []).append(relocation)
        moved: dict[str, cst.BaseStatement] = {}
        target_imports: dict[str, list[cst.BaseStatement]] = {}
        for source_path, relocations in by_source.items():
            if source_path not in working:
                continue
            original_module = cst.parse_module(working[source_path])
            header_symbol = (
                original_module.body[0].name.value
                if original_module.body
                and isinstance(original_module.body[0], (cst.ClassDef, cst.FunctionDef))
                and original_module.header
                else None
            )
            relocation_symbols = {
                name for item in relocations for name in (item.symbol, *item.dependency_closure)
            }
            removed = {
                statement.name.value: statement
                for statement in original_module.body
                if isinstance(statement, (cst.ClassDef, cst.FunctionDef))
                and statement.name.value in relocation_symbols
            }
            removed.update(
                {
                    name: statement
                    for statement in original_module.body
                    if isinstance(statement, cst.SimpleStatementLine)
                    and len(statement.body) == 1
                    and isinstance(statement.body[0], (cst.Assign, cst.AnnAssign))
                    and (name := _assigned_name(statement.body[0])) in relocation_symbols
                }
            )
            for relocation in relocations:
                remaining_code = "\n".join(
                    original_module.code_for_node(statement)
                    for statement in original_module.body
                    if statement
                    not in {
                        removed.get(name)
                        for name in (relocation.symbol, *relocation.dependency_closure)
                    }
                )
                remaining_tree = ast.parse(remaining_code)
                remaining_loads = {
                    node.id
                    for node in ast.walk(remaining_tree)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                }
                shared = sorted(remaining_loads.intersection(relocation.dependency_closure))
                if shared:
                    diagnostics.append(
                        CodemodDiagnostic(
                            source_path,
                            1,
                            0,
                            "W5SHARED_RELOCATION_DEPENDENCY",
                            f"{relocation.symbol} declares shared dependencies {shared}",
                        )
                    )
            module = original_module.with_changes(
                body=tuple(
                    statement
                    for statement in original_module.body
                    if not (
                        (
                            isinstance(statement, (cst.ClassDef, cst.FunctionDef))
                            and statement.name.value in relocation_symbols
                        )
                        or (
                            isinstance(statement, cst.SimpleStatementLine)
                            and len(statement.body) == 1
                            and isinstance(statement.body[0], (cst.Assign, cst.AnnAssign))
                            and _assigned_name(statement.body[0]) in relocation_symbols
                        )
                    )
                )
            )
            top_level_names = {
                statement.name.value
                for statement in original_module.body
                if isinstance(statement, (cst.ClassDef, cst.FunctionDef))
            }
            for statement in original_module.body:
                if not isinstance(statement, cst.SimpleStatementLine):
                    continue
                top_level_names.update(
                    name
                    for item in statement.body
                    if isinstance(item, (cst.Assign, cst.AnnAssign))
                    and (name := _assigned_name(item)) is not None
                )
            if header_symbol in removed:
                moved_node = removed[header_symbol]
                removed[header_symbol] = moved_node.with_changes(
                    leading_lines=(*original_module.header, *moved_node.leading_lines)
                )
                module = module.with_changes(header=())
            module = module.visit(_RemoveExports(item.symbol for item in relocations))
            for relocation in relocations:
                closure_nodes = [
                    removed[name]
                    for name in (*relocation.dependency_closure, relocation.symbol)
                    if name in removed
                ]
                moved_node = removed.get(relocation.symbol)
                if moved_node is None:
                    continue
                collector = _NameCollector()
                for node in closure_nodes:
                    node.visit(collector)
                target_imports.setdefault(relocation.target_path, []).extend(
                    statement
                    for statement in original_module.body
                    if _imported_names(statement).intersection(collector.names)
                )
                moved_tree = ast.parse(
                    "\n".join(original_module.code_for_node(node) for node in closure_nodes)
                )
                loaded_names = {
                    node.id
                    for node in ast.walk(moved_tree)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                }
                for dependency in sorted(loaded_names.intersection(relocation_by_symbol)):
                    dependency_relocation = relocation_by_symbol[dependency]
                    if dependency_relocation.target_path == relocation.target_path:
                        continue
                    module_name = dependency_relocation.target_path.removesuffix(".py").replace(
                        "/", "."
                    )
                    if module_name.startswith("src."):
                        module_name = module_name.removeprefix("src.")
                    target_imports.setdefault(relocation.target_path, []).append(
                        cst.parse_statement(f"from {module_name} import {dependency}\n")
                    )
                local_dependencies = sorted(
                    loaded_names.intersection(top_level_names)
                    - relocation_symbols
                    - set(dir(builtins))
                )
                if local_dependencies and relocation.source_module is None:
                    diagnostics.append(
                        CodemodDiagnostic(
                            source_path,
                            moved_node.name.start.line if hasattr(moved_node.name, "start") else 1,
                            0,
                            "W5UNRESOLVED_RELOCATION_DEPENDENCY",
                            f"{relocation.symbol} requires local symbols {local_dependencies}",
                        )
                    )
                elif local_dependencies:
                    target_imports.setdefault(relocation.target_path, []).append(
                        cst.parse_statement(
                            f"from {relocation.source_module} import "
                            + ", ".join(local_dependencies)
                            + "\n"
                        )
                    )
            working[source_path] = module.code
            moved.update(removed)
            relocation_changes += len(removed)
            for relocation in relocations:
                if relocation.symbol not in removed:
                    target_source = working.get(relocation.target_path, "")
                    target_has_symbol = any(
                        isinstance(statement, (cst.ClassDef, cst.FunctionDef))
                        and statement.name.value == relocation.symbol
                        for statement in cst.parse_module(target_source).body
                    )
                    if target_has_symbol:
                        continue
                    diagnostics.append(
                        CodemodDiagnostic(
                            source_path,
                            1,
                            0,
                            "W5MISSING_SYMBOL",
                            f"expected relocation symbol {relocation.symbol}",
                        )
                    )
        by_target: dict[str, list[SymbolRelocation]] = {}
        for relocation in self.migration.relocations:
            if relocation.symbol in moved:
                by_target.setdefault(relocation.target_path, []).append(relocation)
        for target_path, relocations in by_target.items():
            if target_path not in working:
                working[target_path] = ""
            module = cst.parse_module(working[target_path])
            existing_import_code = {
                module.code_for_node(statement)
                for statement in module.body
                if _imported_names(statement)
            }
            imports: list[cst.BaseStatement] = []
            for statement in target_imports.get(target_path, []):
                import_code = module.code_for_node(statement)
                if import_code in existing_import_code:
                    continue
                existing_import_code.add(import_code)
                imports.append(statement)
            if imports:
                insertion_index = 0
                if (
                    module.body
                    and isinstance(module.body[0], cst.SimpleStatementLine)
                    and len(module.body[0].body) == 1
                    and isinstance(module.body[0].body[0], cst.Expr)
                    and isinstance(module.body[0].body[0].value, cst.SimpleString)
                ):
                    insertion_index = 1
                while insertion_index < len(module.body):
                    statement = module.body[insertion_index]
                    if not (
                        isinstance(statement, cst.SimpleStatementLine)
                        and len(statement.body) == 1
                        and isinstance(statement.body[0], cst.ImportFrom)
                        and get_full_name_for_node(statement.body[0].module) == "__future__"
                    ):
                        break
                    insertion_index += 1
                module = module.with_changes(
                    body=(
                        *module.body[:insertion_index],
                        *imports,
                        *module.body[insertion_index:],
                    )
                )
            existing = {
                statement.name.value
                for statement in module.body
                if isinstance(statement, (cst.ClassDef, cst.FunctionDef))
            }
            additions = [
                moved[name]
                for item in relocations
                for name in (*item.dependency_closure, item.symbol)
                if name in moved and name not in existing
            ]
            has_exports = any(
                isinstance(statement, cst.SimpleStatementLine)
                and any(
                    isinstance(item, cst.Assign) and _assigned_name(item) == "__all__"
                    for item in statement.body
                )
                for statement in module.body
            )
            if not has_exports:
                export = cst.parse_statement(
                    "__all__ = [" + ", ".join(f'"{item.symbol}"' for item in relocations) + "]\n"
                )
                module = module.with_changes(body=(*module.body, export))
            module = module.with_changes(body=(*module.body, *additions))
            module = module.visit(_AddExports(item.symbol for item in relocations))
            module = module.with_changes(has_trailing_newline=True)
            working[target_path] = module.code

        changes = relocation_changes
        for path in sorted(working):
            if self.migration.domain == "records" and path.endswith((".yaml", ".yml")):
                transformed_yaml = re.sub(
                    r"(output_record_accepted:\s*)\{(?!\s*record\s*:)([^{}]*)\}",
                    r"\1{record: {\2}}",
                    working[path],
                )
                if transformed_yaml != working[path]:
                    changes += 1
                    working[path] = transformed_yaml
                continue
            result = self.transform_source(working[path], path)
            dynamic_imports = (
                (
                    RequiredImport(
                        path,
                        "orchestrator.graph",
                        ("build_graph_catalog", "build_graph_command_dependencies"),
                    ),
                )
                if "GraphController(" in working[path]
                else ()
            )
            transformed, import_changes = _ensure_required_imports(
                result.source,
                tuple(item for item in self.migration.required_imports if item.path == path)
                + dynamic_imports,
            )
            working[path] = transformed
            diagnostics.extend(result.diagnostics)
            changes += result.changes + import_changes
        if self.migration.domain == "lifecycle":
            forbidden = {
                "temporary_unconverted_lifecycle": "W5TASK2_LEGACY_POLICY",
                "temporary_unconverted_callback": "W5TASK2_LEGACY_POLICY",
                "temporary_unconverted_acknowledge": "W5TASK2_LEGACY_POLICY",
                "command.model_dump": "W5TASK2_COMMAND_DUMP",
                "compact-replay": "W5TASK2_TOLERANT_DEFAULT",
                "generation-1-replay": "W5TASK2_TOLERANT_DEFAULT",
            }
            for path, source in working.items():
                if not path.startswith("src/"):
                    continue
                for pattern, code in forbidden.items():
                    if pattern in source:
                        diagnostics.append(CodemodDiagnostic(path, 1, 0, code, pattern))
        return FileTransformResult(working, tuple(sorted(diagnostics)), changes)


def _ensure_required_imports(
    source: str, required_imports: tuple[RequiredImport, ...]
) -> tuple[str, int]:
    if not required_imports:
        return source, 0
    module = cst.parse_module(source)
    syntax_tree = ast.parse(source)
    referenced_names = {
        node.id
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    additions: list[cst.BaseStatement] = []
    changes = 0
    for required in required_imports:
        imported: set[str] = set()
        for statement in module.body:
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for item in statement.body:
                if not isinstance(item, cst.ImportFrom) or isinstance(item.names, cst.ImportStar):
                    continue
                if get_full_name_for_node(item.module) != required.module:
                    continue
                imported.update(
                    alias.name.value for alias in item.names if isinstance(alias.name, cst.Name)
                )
        missing = tuple(
            symbol
            for symbol in required.symbols
            if symbol in referenced_names and symbol not in imported
        )
        if not missing:
            continue
        additions.append(
            cst.parse_statement(f"from {required.module} import {', '.join(missing)}\n")
        )
        changes += 1
    if not additions:
        return source, 0
    insertion_index = 0
    if (
        module.body
        and isinstance(module.body[0], cst.SimpleStatementLine)
        and len(module.body[0].body) == 1
        and isinstance(module.body[0].body[0], cst.Expr)
        and isinstance(module.body[0].body[0].value, cst.SimpleString)
    ):
        insertion_index = 1
    while insertion_index < len(module.body):
        statement = module.body[insertion_index]
        if not (
            isinstance(statement, cst.SimpleStatementLine)
            and all(isinstance(item, (cst.Import, cst.ImportFrom)) for item in statement.body)
        ):
            break
        insertion_index += 1
    module = module.with_changes(
        body=(*module.body[:insertion_index], *additions, *module.body[insertion_index:])
    )
    return module.code, changes


def _catalog_cutover_diagnostics(
    tree: ast.Module, path: str, parents: Mapping[ast.AST, ast.AST]
) -> tuple[CodemodDiagnostic, ...]:
    """Find current-path dispatch fallbacks and central hand-built spec tuples.

    Replay is explicitly isolated in ``reduce_legacy_event``; no broader
    name/path exemption is permitted because it could hide a live fallback.
    """

    diagnostics: list[CodemodDiagnostic] = []
    central_commands = path.endswith("src/orchestrator/graph/commands/__init__.py")
    for node in ast.walk(tree):
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
            diagnostics.append(
                CodemodDiagnostic(
                    path,
                    node.lineno,
                    node.col_offset,
                    "W5CENTRAL_COMMAND_SPEC_ENUMERATION",
                    "central COMMAND_SPECIFICATIONS must compose domain tuples",
                )
            )
        if not isinstance(node, ast.If) or _is_legacy_replay_node(node, parents):
            continue
        if _is_catalog_membership_test(node.test) and any(
            _is_apply_command_call(child) for child in ast.walk(node)
        ):
            diagnostics.append(
                CodemodDiagnostic(
                    path,
                    node.lineno,
                    node.col_offset,
                    "W5CATALOG_FALLBACK_DISPATCH",
                    "catalog-membership dispatch must not fall back to legacy apply_command",
                )
            )
    return tuple(diagnostics)


def _is_catalog_membership_test(node: ast.expr) -> bool:
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


def _is_legacy_replay_node(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name == "reduce_legacy_event"
    return False


VERTICAL_SLICE_MIGRATION = DomainMigration(
    domain="vertical_slice",
    paths=(
        "src/orchestrator/graph/_commands.py",
        "src/orchestrator/graph/__init__.py",
        "src/orchestrator/graph/commands/__init__.py",
        "src/orchestrator/graph/commands/lifecycle.py",
        "src/orchestrator/graph/events/lifecycle.py",
        "src/orchestrator/graph/models.py",
        "src/orchestrator/graph_runtime/controller.py",
    ),
    relocations=(
        SymbolRelocation(
            "HeartbeatRecordedPayload",
            "src/orchestrator/graph/models.py",
            "src/orchestrator/graph/events/lifecycle.py",
            "orchestrator.graph.models",
        ),
    ),
    event_routes=(
        EventRoute("heartbeat_recorded", "HeartbeatRecordedPayload", "HEARTBEAT_RECORDED"),
    ),
    command_routes=(
        CommandRoute(
            "record_heartbeat",
            "handle_record_heartbeat",
            "RECORD_HEARTBEAT",
            "RecordHeartbeatCommand",
        ),
    ),
    import_routes=(
        ImportRoute(
            "orchestrator.graph.models",
            "orchestrator.graph.events.lifecycle",
            ("HeartbeatRecordedPayload",),
        ),
    ),
    required_imports=(
        RequiredImport(
            "src/orchestrator/graph/_commands.py",
            "orchestrator.graph.events.lifecycle",
            ("HEARTBEAT_RECORDED",),
        ),
        RequiredImport(
            "src/orchestrator/graph/commands/__init__.py",
            "orchestrator.graph.commands.lifecycle",
            ("RECORD_HEARTBEAT",),
        ),
    ),
    catalog_injections=(
        CatalogInjection(
            "GraphController",
            qualified_names=(
                "orchestrator.graph_runtime.GraphController",
                "orchestrator.graph_runtime.controller.GraphController",
            ),
            additional_arguments=("future_effects",),
            factory_arguments=True,
        ),
    ),
    event_factory_qualified_names=("_apply_record_heartbeat.<locals>.make_event",),
)

DOMAIN_MIGRATIONS: dict[str, DomainMigration] = {
    VERTICAL_SLICE_MIGRATION.domain: VERTICAL_SLICE_MIGRATION,
    "lifecycle": DomainMigration(
        domain="lifecycle",
        paths=(
            "src/orchestrator/graph/_commands.py",
            "src/orchestrator/graph/__init__.py",
            "src/orchestrator/graph/commands/__init__.py",
            "src/orchestrator/graph/commands/lifecycle.py",
            "src/orchestrator/graph/commands/callbacks.py",
            "src/orchestrator/graph/events/lifecycle.py",
            "src/orchestrator/graph/models.py",
            "src/orchestrator/graph/callbacks.py",
            "src/orchestrator/graph_runtime/controller.py",
            "src/orchestrator/graph_runtime/outbox.py",
        ),
        relocations=(
            SymbolRelocation(
                "build_agent_died_effects",
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/lifecycle.py",
                "orchestrator.graph._commands",
            ),
        )
        + tuple(
            SymbolRelocation(
                symbol,
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/events/lifecycle.py",
                "orchestrator.graph.models",
            )
            for symbol in (
                "RunLifecycleChangedPayload",
                "CommandRejectedPayload",
                "CallbackAcceptedPayload",
                "CallbackRejectedPayload",
                "CallbackDuplicateReturnedPayload",
                "RuntimeRetryScheduledPayload",
                "AgentDiedPayload",
            )
        ),
        event_routes=(
            EventRoute(
                "run_lifecycle_changed", "RunLifecycleChangedPayload", "RUN_LIFECYCLE_CHANGED"
            ),
            EventRoute("command_rejected", "CommandRejectedPayload", "COMMAND_REJECTED"),
            EventRoute("callback_accepted", "CallbackAcceptedPayload", "CALLBACK_ACCEPTED"),
            EventRoute(
                "callback_rejected_stale", "CallbackRejectedPayload", "CALLBACK_REJECTED_STALE"
            ),
            EventRoute(
                "callback_rejected_conflict",
                "CallbackRejectedPayload",
                "CALLBACK_REJECTED_CONFLICT",
            ),
            EventRoute(
                "callback_duplicate_returned",
                "CallbackDuplicateReturnedPayload",
                "CALLBACK_DUPLICATE_RETURNED",
            ),
            EventRoute(
                "runtime_retry_scheduled", "RuntimeRetryScheduledPayload", "RUNTIME_RETRY_SCHEDULED"
            ),
            EventRoute("heartbeat_recorded", "HeartbeatRecordedPayload", "HEARTBEAT_RECORDED"),
            EventRoute("agent_died", "AgentDiedPayload", "AGENT_DIED"),
            EventRoute(
                "agent_dispatch_requested",
                "AgentDispatchRequestedPayload",
                "AGENT_DISPATCH_REQUESTED",
            ),
        ),
        command_routes=(
            CommandRoute("accept_run", "handle_accept_run", "ACCEPT_RUN", "EmptyLifecycleCommand"),
            CommandRoute("start", "handle_start", "START", "EmptyLifecycleCommand"),
            CommandRoute("pause", "handle_pause", "PAUSE", "EmptyLifecycleCommand"),
            CommandRoute("resume", "handle_resume", "RESUME", "EmptyLifecycleCommand"),
            CommandRoute("cancel", "handle_cancel", "CANCEL", "EmptyLifecycleCommand"),
            CommandRoute("complete", "handle_complete", "COMPLETE", "EmptyLifecycleCommand"),
            CommandRoute("fail", "handle_fail", "FAIL", "FailCommand"),
            CommandRoute(
                "record_heartbeat",
                "handle_record_heartbeat",
                "RECORD_HEARTBEAT",
                "RecordHeartbeatCommand",
            ),
            CommandRoute(
                "agent_died", "handle_agent_died", "AGENT_DIED_COMMAND", "AgentDiedCommand"
            ),
            CommandRoute(
                "acknowledge_start",
                "handle_acknowledge_start",
                "ACKNOWLEDGE_START",
                "AcknowledgeStartCommand",
            ),
            CommandRoute(
                "submit_callback",
                "handle_submit_callback",
                "SUBMIT_CALLBACK",
                "SubmitCallbackCommand",
            ),
        ),
        import_routes=(
            ImportRoute(
                "orchestrator.graph.models",
                "orchestrator.graph.events.lifecycle",
                (
                    "RunLifecycleChangedPayload",
                    "CommandRejectedPayload",
                    "CallbackAcceptedPayload",
                    "CallbackRejectedPayload",
                    "CallbackDuplicateReturnedPayload",
                    "RuntimeRetryScheduledPayload",
                    "AgentDiedPayload",
                ),
            ),
        ),
        catalog_injections=VERTICAL_SLICE_MIGRATION.catalog_injections,
        event_factory_qualified_names=tuple(
            f"{owner}.<locals>.make_event"
            for owner in (
                "apply_command",
                "_apply_lifecycle_command",
                "_apply_callback_command",
                "_apply_patch_command",
                "_no_successor_recovery_terminal_failure_events",
                "build_agent_died_effects",
                "_lifecycle_event",
                "_command_rejected",
            )
        ),
        report_dynamic_emissions=True,
        required_imports=(
            RequiredImport(
                "src/orchestrator/graph/_commands.py",
                "orchestrator.graph.events.lifecycle",
                (
                    "RUN_LIFECYCLE_CHANGED",
                    "COMMAND_REJECTED",
                    "CALLBACK_ACCEPTED",
                    "CALLBACK_REJECTED_STALE",
                    "CALLBACK_REJECTED_CONFLICT",
                    "CALLBACK_DUPLICATE_RETURNED",
                    "RUNTIME_RETRY_SCHEDULED",
                    "AGENT_DIED",
                ),
            ),
            RequiredImport(
                "src/orchestrator/graph/commands/__init__.py",
                "orchestrator.graph.commands.lifecycle",
                (
                    "ACCEPT_RUN",
                    "START",
                    "PAUSE",
                    "RESUME",
                    "CANCEL",
                    "COMPLETE",
                    "FAIL",
                    "AGENT_DIED_COMMAND",
                ),
            ),
            RequiredImport(
                "src/orchestrator/graph/commands/__init__.py",
                "orchestrator.graph.commands.callbacks",
                ("SUBMIT_CALLBACK", "ACKNOWLEDGE_START"),
            ),
            RequiredImport(
                "src/orchestrator/graph_runtime/controller.py",
                "orchestrator.graph.events.lifecycle",
                ("AGENT_DISPATCH_REQUESTED", "AgentDispatchRequestedPayload"),
            ),
            RequiredImport(
                "src/orchestrator/graph_runtime/controller.py",
                "orchestrator.graph.specifications",
                ("EventMetadata",),
            ),
        ),
    ),
}

DOMAIN_MIGRATIONS.update(
    {
        "catalog_injection": DomainMigration(
            domain="catalog_injection",
            paths=(
                "src/orchestrator/api/app.py",
                "src/orchestrator/api/deps.py",
                "src/orchestrator/api/routers/graph.py",
                "src/orchestrator/api/presenters/evidence_digest.py",
                "src/orchestrator/cli/runs.py",
                "src/orchestrator/cli/main.py",
                "src/orchestrator/graph_runtime/controller.py",
                "src/orchestrator/graph_runtime/store.py",
                "src/orchestrator/graph_runtime/dispatch.py",
                "src/orchestrator/graph_runtime/recovery.py",
                "src/orchestrator/graph_runtime/seeding.py",
                "src/orchestrator/graph_runtime/prompts.py",
                "src/orchestrator/graph_runtime/errors.py",
                "src/orchestrator/graph_runtime/__init__.py",
                "src/orchestrator/workflow/service.py",
                "src/orchestrator/workflow/graph_driver.py",
                "tests/integration/test_graph_event_store.py",
                "tests/integration/test_graph_api.py",
            ),
            catalog_injections=(
                CatalogInjection(
                    "GraphEventStore",
                    qualified_names=(
                        "GraphDispatchExecutor",
                        "orchestrator.graph_runtime.GraphEventStore",
                        "orchestrator.graph_runtime.store.GraphEventStore",
                    ),
                ),
                CatalogInjection(
                    "GraphController",
                    qualified_names=(
                        "WorkflowService",
                        "orchestrator.graph_runtime.GraphController",
                        "orchestrator.graph_runtime.controller.GraphController",
                    ),
                    additional_arguments=("future_effects",),
                ),
                CatalogInjection(
                    "compile_routine",
                    qualified_names=(
                        "GraphRunDriver",
                        "orchestrator.graph.compile_routine",
                        "orchestrator.graph.compiler.compile_routine",
                    ),
                ),
                CatalogInjection(
                    "seed_run",
                    qualified_names=(
                        "recover",
                        "orchestrator.graph_runtime.seed_run",
                        "orchestrator.graph_runtime.seeding.seed_run",
                    ),
                ),
                CatalogInjection(
                    "GraphDispatchExecutor",
                    qualified_names=(
                        "orchestrator.graph_runtime.GraphDispatchExecutor",
                        "orchestrator.graph_runtime.dispatch.GraphDispatchExecutor",
                    ),
                ),
                CatalogInjection(
                    "build_graph_command_dependencies",
                    qualified_names=(
                        "orchestrator.graph.build_graph_command_dependencies",
                        "orchestrator.graph.composition.build_graph_command_dependencies",
                    ),
                ),
                CatalogInjection(
                    "build_run_evidence_digest_response",
                    qualified_names=(
                        "orchestrator.api.build_run_evidence_digest_response",
                        "orchestrator.api.presenters.evidence_digest.build_run_evidence_digest_response",
                    ),
                ),
                CatalogInjection(
                    "WorkflowService",
                    argument_name="graph_catalog",
                    qualified_names=(
                        "orchestrator.workflow.WorkflowService",
                        "orchestrator.workflow.service.WorkflowService",
                    ),
                ),
                CatalogInjection(
                    "GraphRunDriver",
                    qualified_names=(
                        "orchestrator.workflow.GraphRunDriver",
                        "orchestrator.workflow.graph_driver.GraphRunDriver",
                    ),
                ),
                CatalogInjection(
                    "recover",
                    qualified_names=(
                        "orchestrator.graph_runtime.recover",
                        "orchestrator.graph_runtime.recovery.recover",
                    ),
                ),
                *(
                    CatalogInjection(
                        name,
                        qualified_names=(name, f"orchestrator.api.routers.graph.{name}"),
                    )
                    for name in (
                        "build_graph_projection_response",
                        "build_graph_topology_response",
                        "build_final_invariant_blockers_response",
                        "build_graph_regions_response",
                        "build_scheduler_view_response",
                        "build_decision_view_response",
                        "build_file_state_report_response",
                        "build_node_detail_response",
                    )
                ),
                CatalogInjection(
                    "_requirements_for_node",
                    qualified_names=(
                        "_requirements_for_node",
                        "orchestrator.graph_runtime.dispatch._requirements_for_node",
                    ),
                ),
                CatalogInjection(
                    "_planner_packet",
                    qualified_names=(
                        "_planner_packet",
                        "orchestrator.graph_runtime.prompts._planner_packet",
                    ),
                ),
                CatalogInjection(
                    "_prompt_for_node",
                    qualified_names=(
                        "_prompt_for_node",
                        "_prompts._prompt_for_node",
                        "orchestrator.graph_runtime.prompts._prompt_for_node",
                    ),
                ),
                CatalogInjection(
                    "_packet_for_prompt_summary",
                    qualified_names=(
                        "_packet_for_prompt_summary",
                        "orchestrator.graph_runtime.prompts._packet_for_prompt_summary",
                    ),
                ),
                CatalogInjection(
                    "_prompt_summary_for_node",
                    qualified_names=(
                        "_prompt_summary_for_node",
                        "_prompts._prompt_summary_for_node",
                        "orchestrator.graph_runtime.prompts._prompt_summary_for_node",
                    ),
                ),
                CatalogInjection(
                    "_run_ids",
                    qualified_names=("_run_ids", "orchestrator.graph_runtime.recovery._run_ids"),
                ),
                CatalogInjection(
                    "_snapshot_from_events",
                    qualified_names=(
                        "_snapshot_from_events",
                        "orchestrator.workflow.graph_driver._snapshot_from_events",
                    ),
                ),
                *(
                    CatalogInjection(name, test_only_unqualified=True)
                    for name in (
                        "_seed_graph_run",
                        "_seed_control_topology_graph_run",
                        "_seed_callback_lifecycle_graph_run",
                        "_seed_rejected_patch_graph_run",
                        "_seed_worker_verifier_cycle",
                        "_rebuild_projection",
                    )
                ),
            ),
            required_imports=tuple(
                RequiredImport(path, "orchestrator.graph", ("GraphCatalog",))
                for path in (
                    "src/orchestrator/api/__init__.py",
                    "src/orchestrator/api/deps.py",
                    "src/orchestrator/api/routers/graph.py",
                    "src/orchestrator/graph_runtime/dispatch.py",
                    "src/orchestrator/graph_runtime/recovery.py",
                    "src/orchestrator/graph_runtime/seeding.py",
                    "src/orchestrator/graph_runtime/prompts.py",
                    "src/orchestrator/workflow/service.py",
                    "src/orchestrator/workflow/graph_driver.py",
                )
            ),
            transform_commands=False,
        ),
        "catalog_cutover": DomainMigration(
            domain="catalog_cutover",
            paths=(
                "src/orchestrator/graph/catalog.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/events/__init__.py",
                "src/orchestrator/graph/projections.py",
                "src/orchestrator/graph_runtime/controller.py",
            ),
            # Catalog composition and strict-vs-history routing are semantic
            # ownership decisions.  The codemod deliberately makes no edits
            # here; --assert-clean proves no reviewed mechanical route remains.
            transform_commands=False,
        ),
        "complete_reads": DomainMigration(
            domain="complete_reads",
            paths=(
                "src/orchestrator/graph/projections.py",
                "src/orchestrator/graph/__init__.py",
                "src/orchestrator/graph_runtime/store.py",
            ),
            import_routes=(
                ImportRoute(
                    "orchestrator.graph.projections",
                    "orchestrator.graph.projections",
                    ("GRAPH_PROJECTION_PAYLOAD_FIELDS",),
                ),
                ImportRoute(
                    "orchestrator.graph",
                    "orchestrator.graph",
                    ("Actor", "ActorKind", "GRAPH_PROJECTION_PAYLOAD_FIELDS"),
                ),
            ),
            allowlist_names=(
                "GRAPH_PROJECTION_PAYLOAD_FIELDS",
                "LIGHT_GRAPH_PAYLOAD_FIELDS",
                "SUMMARY_REBUILD_PAYLOAD_FIELDS",
                "NODE_DETAIL_PAYLOAD_FIELDS",
            ),
            allowlist_consumers=(
                AllowlistConsumer(
                    "read_run_light",
                    "await self.read_run(run_id, from_position)",
                ),
                AllowlistConsumer(
                    "read_run_summary_rebuild",
                    "await self.read_run(run_id, from_position)",
                ),
                AllowlistConsumer(
                    "read_run_projection",
                    "await self.read_run(run_id, from_position)",
                ),
                AllowlistConsumer(
                    "read_run_node_detail",
                    "await self.read_run(run_id, from_position)",
                ),
            ),
            remove_functions=(
                "_read_run_extracting_fields",
                "_node_detail_light_event",
                "_json_extract_payload_value",
                "_json_extract_value",
            ),
            allowed_allowlist_owners=(
                "GraphEventStore.read_run_light",
                "GraphEventStore.read_run_summary_rebuild",
                "GraphEventStore.read_run_projection",
                "GraphEventStore.read_run_node_detail",
                "GraphEventStore._read_run_extracting_fields",
                "_node_detail_rows_for_events",
                "_apply_node_detail_events",
                "_has_missing_preexisting_node_reference",
                "_node_detail_light_event",
            ),
        ),
        "task3_fixtures": DomainMigration(
            domain="task3_fixtures",
            paths=(
                "tests/unit/test_graph_commands.py",
                "tests/unit/test_graph_planner.py",
                "tests/unit/test_graph_planner_packet.py",
                "tests/integration/test_graph_event_store.py",
                "tests/integration/test_graph_read_models.py",
                "tests/integration/test_graph_node_detail_read_models.py",
                "tests/integration/test_graph_default_carrier.py",
                "tests/integration/test_graph_dynamic_e2e.py",
            ),
            transform_commands=False,
        ),
        "topology": DomainMigration(
            domain="topology",
            target_module="src/orchestrator/graph/events/topology.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/callbacks.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/lifecycle.py",
                "src/orchestrator/graph/commands/schedule.py",
                "src/orchestrator/graph/commands/callbacks.py",
                "src/orchestrator/graph/commands/lifecycle.py",
                "src/orchestrator/graph/compiler.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
                "src/orchestrator/graph/events/topology.py",
                "src/orchestrator/graph/__init__.py",
            ),
            relocations=tuple(
                SymbolRelocation(
                    symbol,
                    "src/orchestrator/graph/models.py",
                    "src/orchestrator/graph/events/topology.py",
                    "orchestrator.graph.models",
                )
                for symbol in (
                    "NodeCreatedPayload",
                    "NodeStateChangedPayload",
                    "NodeRetiredPayload",
                    "NodeReadyPayload",
                    "NodeDeferredPayload",
                    "NodeAuthorityChangedPayload",
                    "NodeSuspectPayload",
                    "PlannerSessionStateChangedPayload",
                    "DeadInputDetectedPayload",
                )
            ),
            import_routes=(
                ImportRoute(
                    "orchestrator.graph.models",
                    "orchestrator.graph.events.topology",
                    (
                        "NodeCreatedPayload",
                        "NodeStateChangedPayload",
                        "NodeRetiredPayload",
                        "NodeReadyPayload",
                        "NodeDeferredPayload",
                        "NodeAuthorityChangedPayload",
                        "NodeSuspectPayload",
                        "PlannerSessionStateChangedPayload",
                        "DeadInputDetectedPayload",
                    ),
                ),
            ),
            event_routes=(
                EventRoute("node_created", "NodeCreatedPayload", "NODE_CREATED"),
                EventRoute("node_state_changed", "NodeStateChangedPayload", "NODE_STATE_CHANGED"),
                EventRoute("node_retired", "NodeRetiredPayload", "NODE_RETIRED"),
                EventRoute("node_ready", "NodeReadyPayload", "NODE_READY"),
                EventRoute("node_deferred", "NodeDeferredPayload", "NODE_DEFERRED"),
                EventRoute(
                    "node_authority_changed",
                    "NodeAuthorityChangedPayload",
                    "NODE_AUTHORITY_CHANGED",
                ),
                EventRoute(
                    "plan_region_marked_suspect", "NodeSuspectPayload", "PLAN_REGION_MARKED_SUSPECT"
                ),
                EventRoute("edge_created", "EdgeCreatedPayload", "EDGE_CREATED"),
                EventRoute("input_bound", "InputBoundPayload", "INPUT_BOUND"),
                EventRoute(
                    "session_state_changed",
                    "PlannerSessionStateChangedPayload",
                    "SESSION_STATE_CHANGED",
                ),
                EventRoute(
                    "dead_input_detected", "DeadInputDetectedPayload", "DEAD_INPUT_DETECTED"
                ),
                EventRoute("revision_created", "RevisionCreatedPayload", "REVISION_CREATED"),
            ),
            command_routes=(
                CommandRoute(
                    "seed_compiled_events",
                    "handle_seed_compiled_events",
                    "SEED_COMPILED_EVENTS",
                    "SeedCompiledEventsCommand",
                ),
            ),
            required_imports=(
                RequiredImport(
                    "src/orchestrator/graph/_commands.py",
                    "orchestrator.graph.events.records",
                    ("OUTPUT_RECORD_ACCEPTED",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph._commands",
                    ("make_strict_event",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph.events.records",
                    ("OUTPUT_RECORD_ACCEPTED",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/__init__.py",
                    "orchestrator.graph.events.topology",
                    ("SEED_COMPILED_EVENTS",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/schedule.py",
                    "orchestrator.graph.events.topology",
                    ("SeedCompiledEventsCommand",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/callbacks.py",
                    "orchestrator.graph._commands",
                    ("typed_topology_event",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph._commands",
                    ("typed_topology_event",),
                ),
            ),
            event_factory_qualified_names=tuple(
                f"{owner}.<locals>.make_event"
                for owner in (
                    "_event_factory",
                    "apply_command",
                    "_apply_lifecycle_command",
                    "_apply_callback_command",
                    "_apply_patch_command",
                    "_patch_op_events",
                    "handle_submit_callback",
                    "handle_acknowledge_start",
                    "handle_agent_died",
                )
            ),
            report_dynamic_emissions=False,
        ),
        "leases": DomainMigration(
            domain="leases",
            target_module="src/orchestrator/graph/events/leases.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/callbacks.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/lifecycle.py",
                "src/orchestrator/graph/commands/schedule.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
                "tests/integration/test_graph_api.py",
                "tests/integration/test_graph_controller_transactions.py",
                "tests/integration/test_graph_decisions_api.py",
                "tests/integration/test_graph_event_store.py",
                "tests/integration/test_graph_file_state_boundary.py",
                "tests/integration/test_graph_fr06_acceptance.py",
                "tests/integration/test_graph_fr08_acceptance.py",
                "tests/integration/test_graph_fr09_acceptance.py",
                "tests/integration/test_graph_fr10_acceptance.py",
                "tests/integration/test_graph_fr11_acceptance.py",
                "tests/integration/test_graph_fr12_acceptance.py",
                "tests/integration/test_graph_fr15_acceptance.py",
                "tests/integration/test_graph_fr16_acceptance.py",
                "tests/integration/test_graph_fr17_acceptance.py",
                "tests/integration/test_graph_gatekeeper_flow.py",
                "tests/integration/test_graph_node_detail_read_models.py",
                "tests/integration/test_graph_outbox_crash_points.py",
                "tests/integration/test_graph_parent_child_flow.py",
                "tests/integration/test_graph_planner_flow.py",
                "tests/integration/test_graph_planner_session_flow.py",
                "tests/integration/test_graph_read_models.py",
                "tests/integration/test_graph_routine_compile.py",
                "tests/integration/test_graph_run_driver.py",
                "tests/integration/test_graph_run_start_routing.py",
                "tests/integration/test_graph_runner_e2e.py",
                "tests/integration/test_graph_scheduler_api.py",
                "tests/integration/test_graph_startup_recovery.py",
                "tests/unit/test_callbacks.py",
                "tests/unit/test_graph_commands.py",
                "tests/unit/test_graph_compiler.py",
                "tests/unit/test_graph_driver_logic.py",
                "tests/unit/test_graph_models.py",
                "tests/unit/test_graph_parent_child_translation.py",
                "tests/unit/test_graph_payload_framework.py",
                "tests/unit/test_graph_planner.py",
                "tests/unit/test_graph_planner_session.py",
                "tests/unit/test_graph_projections.py",
                "tests/unit/test_graph_scheduler_view.py",
                "tests/unit/test_lease_event_payloads.py",
                "tests/unit/test_lifecycle_event_payloads.py",
                "tests/unit/test_patch_validator.py",
                "tests/unit/test_planner_session_event_payloads.py",
                "tests/unit/test_signal_consumer.py",
                "tests/unit/test_w5_payload_ast_inventory.py",
                "tests/unit/test_w5_strict_payload_codemod.py",
            ),
            event_routes=(
                EventRoute("lease_granted", "LeaseGrantedPayload", "LEASE_GRANTED"),
                EventRoute("lease_renewed", "LeaseRenewedPayload", "LEASE_RENEWED"),
                EventRoute("lease_released", "LeaseReleasedPayload", "LEASE_RELEASED"),
                EventRoute("lease_revoked", "LeaseRevokedPayload", "LEASE_REVOKED"),
                EventRoute("lease_expired", "LeaseExpiredPayload", "LEASE_EXPIRED"),
            ),
            command_routes=(
                CommandRoute(
                    "schedule_tick", "handle_schedule_tick", "SCHEDULE_TICK", "ScheduleTickCommand"
                ),
                CommandRoute("reconcile", "handle_reconcile", "RECONCILE", "ReconcileCommand"),
            ),
            required_imports=(
                RequiredImport(
                    "src/orchestrator/graph/_commands.py",
                    "orchestrator.graph.events.leases",
                    (
                        "LEASE_EXPIRED",
                        "LEASE_GRANTED",
                        "LEASE_RELEASED",
                        "LEASE_RENEWED",
                        "LEASE_REVOKED",
                    ),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/callbacks.py",
                    "orchestrator.graph.events.leases",
                    ("LEASE_RELEASED",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/callbacks.py",
                    "orchestrator.graph._commands",
                    ("make_strict_event",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph.events.leases",
                    ("LEASE_REVOKED",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph._commands",
                    ("make_strict_event",),
                ),
            ),
            report_dynamic_emissions=True,
        ),
        "records": DomainMigration(
            domain="records",
            transform_commands=False,
            target_module="src/orchestrator/graph/events/records.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/compiler.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/records.py",
                "src/orchestrator/graph/commands/lifecycle.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
                "tests/integration/test_graph_api.py",
                "tests/integration/test_graph_decisions_api.py",
                "tests/integration/test_graph_default_carrier.py",
                "tests/integration/test_graph_dynamic_e2e.py",
                "tests/integration/test_graph_event_store.py",
                "tests/integration/test_graph_fr01_fr13_fr18_acceptance.py",
                "tests/integration/test_graph_fr03_acceptance.py",
                "tests/integration/test_graph_fr06_acceptance.py",
                "tests/integration/test_graph_fr07_acceptance.py",
                "tests/integration/test_graph_fr08_acceptance.py",
                "tests/integration/test_graph_fr09_acceptance.py",
                "tests/integration/test_graph_fr12_acceptance.py",
                "tests/integration/test_graph_fr14_final_gate_acceptance.py",
                "tests/integration/test_graph_fr15_acceptance.py",
                "tests/integration/test_graph_fr17_acceptance.py",
                "tests/integration/test_graph_node_detail_read_models.py",
                "tests/integration/test_graph_outbox_crash_points.py",
                "tests/integration/test_graph_read_models.py",
                "tests/integration/test_graph_routine_compile.py",
                "tests/integration/test_graph_run_driver.py",
                "tests/integration/test_run_evidence_digest_api.py",
                "tests/unit/test_command_bindings.py",
                "tests/unit/test_graph_api_projection.py",
                "tests/unit/test_graph_commands.py",
                "tests/unit/test_graph_compiler.py",
                "tests/unit/test_graph_decision_view.py",
                "tests/unit/test_graph_dispatch_on_output.py",
                "tests/unit/test_graph_planner_packet.py",
                "tests/unit/test_graph_projections.py",
                "tests/unit/test_run_evidence_digest_presenter.py",
                "tests/fixtures/graph/invariants.yaml",
                "tests/fixtures/graph/node_lifecycle_appeal.yaml",
                "tests/fixtures/graph/node_lifecycle_worker.yaml",
                "tests/fixtures/graph/task_projection.yaml",
            ),
            event_routes=(
                EventRoute(
                    "output_record_accepted",
                    "OutputRecordAcceptedPayload",
                    "OUTPUT_RECORD_ACCEPTED",
                ),
                EventRoute(
                    "verification_passed", "VerificationOutcomePayload", "VERIFICATION_PASSED"
                ),
                EventRoute(
                    "verification_failed", "VerificationOutcomePayload", "VERIFICATION_FAILED"
                ),
            ),
            command_routes=(
                CommandRoute(
                    "evaluate_join", "handle_evaluate_join", "EVALUATE_JOIN", "EvaluateJoinCommand"
                ),
                CommandRoute(
                    "evaluate_final_gate",
                    "handle_evaluate_final_gate",
                    "EVALUATE_FINAL_GATE",
                    "EvaluateFinalGateCommand",
                ),
            ),
            required_imports=(
                RequiredImport(
                    "src/orchestrator/graph/_commands.py",
                    "orchestrator.graph.events.records",
                    ("OUTPUT_RECORD_ACCEPTED",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph._commands",
                    ("make_strict_event",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/commands/lifecycle.py",
                    "orchestrator.graph.events.records",
                    ("OUTPUT_RECORD_ACCEPTED",),
                ),
                RequiredImport(
                    "src/orchestrator/graph/_commands.py",
                    "orchestrator.graph.events.patches",
                    ("GRAPH_PATCH_ACCEPTED", "GRAPH_PATCH_REJECTED"),
                ),
            ),
            report_dynamic_emissions=True,
        ),
        "patches": DomainMigration(
            domain="patches",
            target_module="src/orchestrator/graph/events/patches.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/patches.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
                "src/orchestrator/graph/scenario.py",
                "src/orchestrator/graph_runtime/controller.py",
                "tests/graph_command_support.py",
                "tests/integration/test_api_activity.py",
                "tests/integration/test_graph_api.py",
                "tests/integration/test_graph_dynamic_e2e.py",
                "tests/integration/test_graph_event_store.py",
                "tests/integration/test_graph_fr01_fr13_fr18_acceptance.py",
                "tests/integration/test_graph_fr02_acceptance.py",
                "tests/integration/test_graph_fr03_acceptance.py",
                "tests/integration/test_graph_fr06_acceptance.py",
                "tests/integration/test_graph_fr07_acceptance.py",
                "tests/integration/test_graph_fr08_acceptance.py",
                "tests/integration/test_graph_fr09_acceptance.py",
                "tests/integration/test_graph_fr16_acceptance.py",
                "tests/integration/test_graph_fr17_acceptance.py",
                "tests/integration/test_graph_parent_child_flow.py",
                "tests/integration/test_graph_planner_flow.py",
                "tests/integration/test_graph_planner_session_flow.py",
                "tests/integration/test_graph_read_models.py",
                "tests/unit/test_compare_carriers.py",
                "tests/unit/test_graph_api_projection.py",
                "tests/unit/test_graph_commands.py",
                "tests/unit/test_graph_macros.py",
                "tests/unit/test_graph_models.py",
                "tests/unit/test_graph_parent_child_translation.py",
                "tests/unit/test_graph_planner.py",
                "tests/unit/test_graph_planner_packet.py",
                "tests/unit/test_graph_planner_session.py",
                "tests/unit/test_graph_projections.py",
                "tests/unit/test_lifecycle_event_payloads.py",
                "tests/unit/test_node_created_event_payloads.py",
                "tests/unit/test_patch_event_payloads.py",
                "tests/unit/test_w5_strict_payload_codemod.py",
            ),
            event_routes=(
                EventRoute(
                    "graph_patch_accepted", "GraphPatchAcceptedPayload", "GRAPH_PATCH_ACCEPTED"
                ),
                EventRoute(
                    "graph_patch_rejected", "GraphPatchRejectedPayload", "GRAPH_PATCH_REJECTED"
                ),
            ),
            command_routes=(
                CommandRoute(
                    "submit_patch", "handle_submit_patch", "SUBMIT_PATCH", "SubmitPatchCommand"
                ),
            ),
            report_dynamic_emissions=True,
        ),
        "decisions": DomainMigration(
            domain="decisions",
            target_module="src/orchestrator/graph/events/decisions.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/callbacks.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
            ),
            event_routes=(
                EventRoute("appeal_opened", "AppealOpenedPayload", "APPEAL_OPENED"),
                EventRoute(
                    "approval_decision_recorded",
                    "ApprovalDecisionRecordedPayload",
                    "APPROVAL_DECISION_RECORDED",
                ),
                EventRoute(
                    "authority_decision_recorded",
                    "AuthorityDecisionRecordedPayload",
                    "AUTHORITY_DECISION_RECORDED",
                ),
                EventRoute(
                    "oversight_decision_recorded",
                    "OversightDecisionRecordedPayload",
                    "OVERSIGHT_DECISION_RECORDED",
                ),
            ),
            command_routes=(
                CommandRoute(
                    "raise_appeal", "handle_raise_appeal", "RAISE_APPEAL", "RaiseAppealCommand"
                ),
                CommandRoute(
                    "record_decision",
                    "handle_record_decision",
                    "RECORD_DECISION",
                    "RecordDecisionCommand",
                ),
            ),
            report_dynamic_emissions=True,
        ),
        "requirements": DomainMigration(
            domain="requirements",
            target_module="src/orchestrator/graph/events/requirements.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/callbacks.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
            ),
            event_routes=(
                EventRoute(
                    "requirement_revision_recorded",
                    "RequirementRevisionPayload",
                    "REQUIREMENT_REVISION_RECORDED",
                ),
                EventRoute(
                    "support_evidence_recorded",
                    "SupportEvidencePayload",
                    "SUPPORT_EVIDENCE_RECORDED",
                ),
            ),
            command_routes=(
                CommandRoute(
                    "record_requirement_revision",
                    "handle_record_requirement_revision",
                    "RECORD_REQUIREMENT_REVISION",
                    "RecordRequirementRevisionCommand",
                ),
                CommandRoute(
                    "record_support_evidence",
                    "handle_record_support_evidence",
                    "RECORD_SUPPORT_EVIDENCE",
                    "RecordSupportEvidenceCommand",
                ),
            ),
            report_dynamic_emissions=True,
        ),
        "file_state": DomainMigration(
            domain="file_state",
            target_module="src/orchestrator/graph/events/file_state.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/callbacks.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
            ),
            event_routes=(
                EventRoute(
                    "file_state_accepted", "FileStateAcceptedPayload", "FILE_STATE_ACCEPTED"
                ),
                EventRoute(
                    "file_state_rejected", "FileStateRejectedPayload", "FILE_STATE_REJECTED"
                ),
                EventRoute(
                    "gatekeeper_verdict_recorded",
                    "GatekeeperVerdictRecordedPayload",
                    "GATEKEEPER_VERDICT_RECORDED",
                ),
                EventRoute(
                    "gatekeeper_cost_recorded",
                    "GatekeeperCostRecordedPayload",
                    "GATEKEEPER_COST_RECORDED",
                ),
                EventRoute("cleanup_requested", "CleanupRequestedPayload", "CLEANUP_REQUESTED"),
                EventRoute("cleanup_applied", "CleanupAppliedPayload", "CLEANUP_APPLIED"),
            ),
            command_routes=(
                CommandRoute(
                    "record_gatekeeper_verdicts",
                    "handle_record_gatekeeper_verdicts",
                    "RECORD_GATEKEEPER_VERDICTS",
                    "RecordGatekeeperVerdictsCommand",
                ),
                CommandRoute(
                    "record_cleanup_applied",
                    "handle_record_cleanup_applied",
                    "RECORD_CLEANUP_APPLIED",
                    "RecordCleanupAppliedCommand",
                ),
            ),
            report_dynamic_emissions=True,
        ),
    }
)


def _diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def run_migration(migration: DomainMigration, root: Path, mode: str) -> MigrationRunResult:
    if migration.domain == "catalog_injection":
        target_names = tuple(route.callable_name for route in migration.catalog_injections)
        production_paths = tuple(
            str(path.relative_to(root)) for path in (root / "src" / "orchestrator").rglob("*.py")
        )
        discovered = tuple(
            str(path.relative_to(root))
            for path in (root / "tests").rglob("*.py")
            if path.name not in {"signal_helpers.py", "test_run_evidence_digest_api.py"}
            and any(f"{name}(" in path.read_text() for name in target_names)
        )
        discovered_functions = {
            node.name
            for path in discovered
            for node in ast.walk(ast.parse((root / path).read_text()))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                argument.arg == "catalog" for argument in (*node.args.args, *node.args.kwonlyargs)
            )
            and node.name not in {"create_service", "_create_service"}
            and not node.name.startswith("__")
            and not node.name.endswith("service_factory")
        }
        migration = replace(
            migration,
            paths=tuple(dict.fromkeys((*migration.paths, *production_paths, *discovered))),
            required_imports=(
                *migration.required_imports,
                *(
                    RequiredImport(
                        path,
                        "orchestrator.graph",
                        ("GraphCatalog", "build_graph_catalog"),
                    )
                    for path in discovered
                ),
            ),
            catalog_injections=(
                *migration.catalog_injections,
                *(
                    CatalogInjection(name, qualified_names=(name,))
                    for name in sorted(discovered_functions)
                    if name not in {route.callable_name for route in migration.catalog_injections}
                ),
            ),
        )
    if migration.domain == "lifecycle":
        discovered = tuple(
            str(path.relative_to(root))
            for base in (root / "src", root / "tests")
            for path in base.rglob("*.py")
            if "GraphController(" in path.read_text()
        )
        migration = replace(migration, paths=tuple(dict.fromkeys((*migration.paths, *discovered))))
    if migration.domain == "leases":
        migration = replace(
            migration,
            paths=tuple(
                dict.fromkeys(
                    (
                        *migration.paths,
                        *(
                            str(path.relative_to(root))
                            for path in (root / "tests/fixtures/graph").glob("*.yaml")
                        ),
                    )
                )
            ),
        )
    target_paths = {item.target_path for item in migration.relocations}
    original = {}
    for item in migration.paths:
        path = root / item
        if path.is_file():
            original[item] = path.read_text()
        elif item in target_paths:
            original[item] = ""
    python_sources = {path: source for path, source in original.items() if path.endswith(".py")}
    yaml_sources = {path: source for path, source in original.items() if path.endswith(".yaml")}
    python_migration = (
        replace(migration, paths=tuple(python_sources))
        if migration.domain == "leases"
        else migration
    )
    sources = (
        {**python_sources, **yaml_sources} if migration.domain == "records" else python_sources
    )
    result = StrictPayloadCutoverCodemod(python_migration).transform_files(sources)
    transformed_sources = dict(result.sources)
    if migration.domain == "leases":
        transformed_sources.update(
            {path: _complete_lease_yaml_fixtures(source) for path, source in yaml_sources.items()}
        )
    diffs = "".join(
        _diff(path, original[path], transformed_sources[path])
        for path in sorted(original)
        if original[path] != transformed_sources[path]
    )
    diagnostics = "\n".join(item.render() for item in result.diagnostics)
    if diagnostics:
        diagnostics += "\n"
    if mode == "dry-run":
        return MigrationRunResult(1 if diagnostics else 0, diffs + diagnostics)
    if mode == "assert-clean":
        output = diffs + diagnostics
        return MigrationRunResult(1 if output else 0, output)
    if mode != "apply":
        raise ValueError(f"unknown migration mode: {mode}")
    if diagnostics:
        return MigrationRunResult(1, diffs + diagnostics)
    for relative_path, transformed in transformed_sources.items():
        path = root / relative_path
        current = path.read_text() if path.exists() else ""
        if current != transformed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(transformed)
    return MigrationRunResult(0, diffs + diagnostics)


def _complete_lease_yaml_fixtures(source: str) -> str:
    section: str | None = None
    output: list[str] = []
    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("given_events:"):
            section = "given_events"
        elif stripped.startswith(("when_command:", "then_events:", "then_projection:")):
            section = None
        if section == "given_events" and "lease_granted: {" in line:
            marker = line.index("lease_granted: {")
            body_start = line.index("{", marker) + 1
            depth = 1
            body_end = body_start
            while body_end < len(line) and depth:
                if line[body_end] == "{":
                    depth += 1
                elif line[body_end] == "}":
                    depth -= 1
                body_end += 1
            if depth == 0:
                body = line[body_start : body_end - 1]
                lease_match = re.search(r"lease_id:\s*([^, }]+)", body)
                lease_id = lease_match.group(1) if lease_match is not None else "lease-test"
                additions = (
                    ("generation", "0"),
                    ("execution_id", f"exec-{lease_id.removeprefix('lease-')}"),
                    ("base_snapshot_id", "S0"),
                    ("expires_at", "2026-01-01T00:05:00+00:00"),
                    ("resource_claims", "[]"),
                )
                for key, value in additions:
                    if re.search(rf"(?:^|,\s*){re.escape(key)}:", body) is None:
                        body += f", {key}: {value}"
                line = line[:body_start] + body + line[body_end - 1 :]
        if section == "given_events":
            for event_type, additions in (
                ("lease_released", (("generation", "1"),)),
                (
                    "lease_revoked",
                    (
                        ("generation", "1"),
                        ("execution_id", "exec-1"),
                        ("trigger", "test_revocation"),
                        ("reason", "fixture_revocation"),
                    ),
                ),
            ):
                match = re.search(rf"{event_type}: \{{(?P<body>[^}}]*)\}}", line)
                if match is None:
                    continue
                body = match.group("body")
                for key, value in additions:
                    if re.search(rf"(?:^|,\s*){re.escape(key)}:", body) is None:
                        body += f", {key}: {value}"
                line = line[: match.start("body")] + body + line[match.end("body") :]
        if "schedule_tick: {" in line:
            match = re.search(r"schedule_tick: \{(?P<body>[^}]*)\}", line)
            if match is not None:
                body = match.group("body")
                if "lease_seconds:" not in body:
                    body += ", lease_seconds: 300"
                if "max_grants:" not in body:
                    body += ", max_grants: 10"
                line = line[: match.start("body")] + body + line[match.end("body") :]
        output.append(line)
    return "".join(output)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, choices=sorted(DOMAIN_MIGRATIONS))
    parser.add_argument("--root", type=Path, default=Path("."), help=argparse.SUPPRESS)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--assert-clean", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "dry-run" if args.dry_run else "apply" if args.apply else "assert-clean"
    result = run_migration(DOMAIN_MIGRATIONS[args.domain], args.root, mode)
    sys.stdout.write(result.output)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
