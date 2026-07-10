#!/usr/bin/env python3
"""Formatting-preserving mechanical cutover harness for W5 payload domains.

The migration table contains symbol routing only.  Payload fields, types, and
runtime schemas remain owned by the domain implementation.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import libcst as cst
from libcst import metadata
from libcst.helpers import get_full_name_for_node


@dataclass(frozen=True)
class SymbolRelocation:
    symbol: str
    source_path: str
    target_path: str


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
class CatalogInjection:
    callable_name: str
    argument_name: str = "catalog"


@dataclass(frozen=True)
class DomainMigration:
    domain: str
    paths: tuple[str, ...]
    relocations: tuple[SymbolRelocation, ...] = ()
    event_routes: tuple[EventRoute, ...] = ()
    command_routes: tuple[CommandRoute, ...] = ()
    import_routes: tuple[ImportRoute, ...] = ()
    catalog_injections: tuple[CatalogInjection, ...] = ()
    report_dynamic_emissions: bool = False
    allowlist_names: tuple[str, ...] = (
        "GRAPH_PROJECTION_PAYLOAD_FIELDS",
        "LIGHT_GRAPH_PAYLOAD_FIELDS",
        "SUMMARY_REBUILD_PAYLOAD_FIELDS",
        "NODE_DETAIL_PAYLOAD_FIELDS",
    )


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

    def __init__(self, migration: DomainMigration, path: str) -> None:
        self.migration = migration
        self.path = path
        self.changes = 0
        self.diagnostics: list[CodemodDiagnostic] = []
        self._events = {route.event_name: route for route in migration.event_routes}
        self._commands = {route.command_name: route for route in migration.command_routes}
        self._handlers = {route.handler: route for route in migration.command_routes}
        self._imports = {route.old_module: route for route in migration.import_routes}
        self._injections = {route.callable_name: route for route in migration.catalog_injections}

    def _touch_metadata(self, node: cst.CSTNode) -> metadata.CodeRange:
        position = self.get_metadata(metadata.PositionProvider, node)
        self.get_metadata(metadata.QualifiedNameProvider, node, set())
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
        route = self._handlers.get(original_node.name.value)
        if route is None:
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
        if not isinstance(original_node.func, cst.Name) or original_node.func.value != "make_event":
            return None
        position = self._touch_metadata(original_node.func)
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
        callable_name: str | None = None
        if isinstance(original_node.func, cst.Name):
            callable_name = original_node.func.value
        elif isinstance(original_node.func, cst.Attribute):
            callable_name = original_node.func.attr.value
        route = self._injections.get(callable_name or "")
        if route is None:
            return None
        self._touch_metadata(original_node.func)
        if any(
            argument.keyword is not None and argument.keyword.value == route.argument_name
            for argument in original_node.args
        ):
            return None
        self.changes += 1
        return updated_node.with_changes(
            args=(
                *updated_node.args,
                cst.Arg(
                    cst.Name(route.argument_name),
                    keyword=cst.Name(route.argument_name),
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
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
        if name in self.migration.allowlist_names:
            self.changes += 1
            return cst.RemoveFromParent()
        if name != "COMMAND_HANDLERS" or not isinstance(assignment.value, cst.Dict):
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
        elements = tuple(
            cst.Element(cst.Name(route.specification), comma=cst.Comma()) for route in routes
        )
        specification_assignment = cst.Assign(
            targets=(cst.AssignTarget(cst.Name("COMMAND_SPECIFICATIONS")),),
            value=cst.Tuple(elements),
        )
        self.changes += 1
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


class _RemoveRelocations(cst.CSTTransformer):
    def __init__(self, symbols: set[str]) -> None:
        self.symbols = symbols
        self.removed: dict[str, cst.ClassDef | cst.FunctionDef] = {}

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        if original_node.name.value not in self.symbols:
            return updated_node
        self.removed[original_node.name.value] = updated_node
        return cst.RemoveFromParent()

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        if original_node.name.value not in self.symbols:
            return updated_node
        self.removed[original_node.name.value] = updated_node
        return cst.RemoveFromParent()


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


class StrictPayloadCutoverCodemod:
    """Apply one domain's mechanically safe LibCST transformations."""

    def __init__(self, migration: DomainMigration) -> None:
        self.migration = migration

    def transform_source(self, source: str, path: str = "<memory>") -> TransformResult:
        module = cst.parse_module(source)
        transformer = _MechanicalTransformer(self.migration, path)
        transformed = metadata.MetadataWrapper(module).visit(transformer)
        return TransformResult(
            source=transformed.code,
            diagnostics=tuple(sorted(transformer.diagnostics)),
            changes=transformer.changes,
        )

    def transform_files(self, sources: Mapping[str, str]) -> FileTransformResult:
        working = dict(sources)
        relocation_changes = 0
        by_source: dict[str, list[SymbolRelocation]] = {}
        for relocation in self.migration.relocations:
            by_source.setdefault(relocation.source_path, []).append(relocation)
        moved: dict[str, cst.ClassDef | cst.FunctionDef] = {}
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
            remover = _RemoveRelocations({item.symbol for item in relocations})
            module = original_module.visit(remover)
            if header_symbol in remover.removed:
                moved_node = remover.removed[header_symbol]
                remover.removed[header_symbol] = moved_node.with_changes(
                    leading_lines=(*original_module.header, *moved_node.leading_lines)
                )
                module = module.with_changes(header=())
            working[source_path] = module.code
            moved.update(remover.removed)
            relocation_changes += len(remover.removed)
        by_target: dict[str, list[SymbolRelocation]] = {}
        for relocation in self.migration.relocations:
            if relocation.symbol in moved:
                by_target.setdefault(relocation.target_path, []).append(relocation)
        for target_path, relocations in by_target.items():
            if target_path not in working:
                continue
            module = cst.parse_module(working[target_path])
            existing = {
                statement.name.value
                for statement in module.body
                if isinstance(statement, (cst.ClassDef, cst.FunctionDef))
            }
            additions = [moved[item.symbol] for item in relocations if item.symbol not in existing]
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

        diagnostics: list[CodemodDiagnostic] = []
        changes = relocation_changes
        for path in sorted(working):
            result = self.transform_source(working[path], path)
            working[path] = result.source
            diagnostics.extend(result.diagnostics)
            changes += result.changes
        return FileTransformResult(working, tuple(sorted(diagnostics)), changes)


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
    catalog_injections=(CatalogInjection("GraphController"),),
)

DOMAIN_MIGRATIONS: dict[str, DomainMigration] = {
    VERTICAL_SLICE_MIGRATION.domain: VERTICAL_SLICE_MIGRATION,
    "lifecycle": DomainMigration(
        domain="lifecycle",
        paths=(
            "src/orchestrator/graph/_commands.py",
            "src/orchestrator/graph/commands/__init__.py",
            "src/orchestrator/graph_runtime/controller.py",
        ),
        event_routes=VERTICAL_SLICE_MIGRATION.event_routes,
        command_routes=VERTICAL_SLICE_MIGRATION.command_routes,
        catalog_injections=VERTICAL_SLICE_MIGRATION.catalog_injections,
    ),
}


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
        return MigrationRunResult(0, diffs + diagnostics)
    if mode == "assert-clean":
        output = diffs + diagnostics
        return MigrationRunResult(1 if output else 0, output)
    if mode != "apply":
        raise ValueError(f"unknown migration mode: {mode}")
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
