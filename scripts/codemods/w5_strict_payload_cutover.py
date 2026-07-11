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
        self._commands = {route.command_name: route for route in migration.command_routes}
        self._handlers = {route.handler: route for route in migration.command_routes}
        self._imports = {route.old_module: route for route in migration.import_routes}
        self._catalog_injections = migration.catalog_injections
        self._allowlist_consumers = {
            consumer.function_name: consumer for consumer in migration.allowlist_consumers
        }
        self._blocked_allowlists = blocked_allowlists

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
        if not imported.issubset(route.symbols):
            # The containing statement splits mixed imports after child visits.
            return updated_node
        self.changes += 1
        return updated_node.with_changes(module=cst.parse_expression(route.new_module))

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.BaseStatement:
        consumer = self._allowlist_consumers.get(original_node.name.value)
        if consumer is not None:
            resolved_names = self._resolved_names(original_node.name)
            scope = self.get_metadata(metadata.ScopeProvider, original_node.name)
            expected_names = consumer.qualified_names or (consumer.function_name,)
            if not resolved_names.intersection(expected_names) or not isinstance(
                scope, GlobalScope
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
        if not resolved_names.intersection(self.migration.event_factory_qualified_names):
            return None
        if not original_node.args:
            return None
        event_name = _simple_string(original_node.args[0].value)
        if event_name is None:
            if self.migration.report_dynamic_emissions:
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
        if len(routes) != 1:
            return None
        route = routes[0]
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
                        else cst.Name(name),
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

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        event = self._event_replacement(original_node, updated_node)
        if event is not None:
            return event
        injection = self._inject_catalog(original_node, updated_node)
        return injection if injection is not None else updated_node

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.BaseStatement | cst.RemovalSentinel:
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
        initial_diagnostics.extend(
            CodemodDiagnostic(
                path,
                1,
                0,
                "W5UNQUALIFIED_CATALOG_ROUTE",
                f"catalog injection {route.callable_name} requires qualified_names",
            )
            for route in self.migration.catalog_injections
            if not route.qualified_names
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
        command_route_names = {route.command_name for route in self.migration.command_routes}
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
        if noncanonical_specifications:
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
                continue
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
        "topology": DomainMigration(
            domain="topology",
            target_module="src/orchestrator/graph/events/topology.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/schedule.py",
                "src/orchestrator/graph/compiler.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
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
            report_dynamic_emissions=True,
        ),
        "leases": DomainMigration(
            domain="leases",
            target_module="src/orchestrator/graph/events/leases.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/schedule.py",
                "src/orchestrator/graph/commands/lease_bridge.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
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
            report_dynamic_emissions=True,
        ),
        "records": DomainMigration(
            domain="records",
            target_module="src/orchestrator/graph/events/records.py",
            paths=(
                "src/orchestrator/graph/_commands.py",
                "src/orchestrator/graph/commands/__init__.py",
                "src/orchestrator/graph/commands/records.py",
                "src/orchestrator/graph/models.py",
                "src/orchestrator/graph/projections.py",
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
    if migration.domain == "lifecycle":
        discovered = tuple(
            str(path.relative_to(root))
            for base in (root / "src", root / "tests")
            for path in base.rglob("*.py")
            if "GraphController(" in path.read_text()
        )
        migration = replace(migration, paths=tuple(dict.fromkeys((*migration.paths, *discovered))))
    target_paths = {item.target_path for item in migration.relocations}
    original = {}
    for item in migration.paths:
        path = root / item
        if path.is_file():
            original[item] = path.read_text()
        elif item in target_paths:
            original[item] = ""
    result = StrictPayloadCutoverCodemod(migration).transform_files(original)
    diffs = "".join(
        _diff(path, original[path], result.sources[path])
        for path in sorted(original)
        if original[path] != result.sources[path]
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
    for relative_path, transformed in result.sources.items():
        path = root / relative_path
        current = path.read_text() if path.exists() else ""
        if current != transformed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(transformed)
    return MigrationRunResult(0, diffs + diagnostics)


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
