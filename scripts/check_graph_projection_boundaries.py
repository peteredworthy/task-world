"""Fail-closed source boundary checks for immutable GraphProjection storage."""

from __future__ import annotations

import ast
import os
import subprocess
import tokenize
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import UnionType
from typing import Annotated, Literal, TypeAliasType, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict

from orchestrator.graph import (
    CANONICAL_EVENT_TYPES,
    PROJECTION_NEUTRAL_EVENT_TYPES,
    FrozenMap,
    GraphProjection,
    ProjectedRecordBase,
    ProjectionModel,
)

if __package__:
    from scripts.graph_projection_boundary_provenance import (
        ProjectionProvenanceFact,
        projection_provenance,
        projection_provenance_seed_tokens,
    )
else:
    from graph_projection_boundary_provenance import (
        ProjectionProvenanceFact,
        projection_provenance,
        projection_provenance_seed_tokens,
    )


ALLOWED_STORAGE_READERS = frozenset(
    {
        "src/orchestrator/graph/projection_models.py",
        "src/orchestrator/graph/projection_collections.py",
        "src/orchestrator/graph/projection_queries.py",
        "src/orchestrator/graph/projection_codec.py",
        "src/orchestrator/graph/projections.py",
    }
)

_GROUPED_STORAGE_NAMES = frozenset(
    {
        "lifecycle",
        "nodes",
        "tasks",
        "execution",
        "scheduling",
        "records",
        "topology",
        "governance",
        "verification",
        "planning",
        "requirements",
        "usage",
    }
)
_MAPPING_MUTABLE_METHODS = frozenset({"clear", "pop", "popitem", "setdefault", "update"})
_SEQUENCE_MUTABLE_METHODS = frozenset(
    {"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort"}
)
_SET_MUTABLE_METHODS = frozenset(
    {
        "add",
        "clear",
        "difference_update",
        "discard",
        "intersection_update",
        "pop",
        "remove",
        "symmetric_difference_update",
        "update",
    }
)
_INPLACE_DUNDER_MUTABLE_METHODS = frozenset(
    {
        "__setitem__",
        "__delitem__",
        "__setattr__",
        "__delattr__",
        "__iadd__",
        "__imul__",
        "__ior__",
        "__iand__",
        "__ixor__",
        "__isub__",
    }
)
_MUTABLE_METHODS = frozenset().union(
    _MAPPING_MUTABLE_METHODS,
    _SEQUENCE_MUTABLE_METHODS,
    _SET_MUTABLE_METHODS,
    _INPLACE_DUNDER_MUTABLE_METHODS,
)
_IMMUTABLE_SCALARS = frozenset({str, int, float, bool, bytes, type(None)})
_PUBLIC_PROJECTION_STAR_IMPORT_MODULES = frozenset(
    {
        "orchestrator.graph",
        "orchestrator.graph_runtime.controller",
    }
)


def projection_annotation_violations(root: type[ProjectionModel]) -> tuple[str, ...]:
    """Return paths whose reachable annotations are not explicitly immutable."""
    violations: list[str] = []
    active_aliases: set[TypeAliasType] = set()
    missing = object()

    def visit(
        annotation: object,
        path: str,
        active_models: frozenset[type[ProjectionModel]],
        substitutions: tuple[tuple[object, object], ...] = (),
    ) -> None:
        replacement = next(
            (value for parameter, value in reversed(substitutions) if annotation is parameter),
            missing,
        )
        if replacement is not missing:
            visit(replacement, path, active_models, substitutions)
            return
        if isinstance(annotation, TypeAliasType):
            if annotation in active_aliases:
                return
            active_aliases.add(annotation)
            try:
                visit(annotation.__value__, path, active_models, substitutions)
            finally:
                active_aliases.remove(annotation)
            return
        origin = get_origin(annotation)
        arguments = get_args(annotation)
        if isinstance(origin, TypeAliasType):
            if origin in active_aliases:
                for argument in arguments:
                    visit(argument, path, active_models, substitutions)
                return
            active_aliases.add(origin)
            try:
                parameters = tuple(origin.__type_params__)
                visit(
                    origin.__value__,
                    path,
                    active_models,
                    (*substitutions, *zip(parameters, arguments, strict=True)),
                )
            finally:
                active_aliases.remove(origin)
        elif origin is Annotated:
            visit(arguments[0], path, active_models, substitutions)
        elif origin in (Union, UnionType):
            for member in arguments:
                visit(member, path, active_models, substitutions)
        elif origin in (tuple, frozenset):
            for member in arguments:
                if member is not Ellipsis:
                    visit(member, path, active_models, substitutions)
        elif origin is FrozenMap:
            if len(arguments) != 2:
                violations.append(f"{path}: FrozenMap requires key and value annotations")
                return
            visit(arguments[0], f"{path}.key", active_models, substitutions)
            visit(arguments[1], f"{path}.value", active_models, substitutions)
        elif annotation in _IMMUTABLE_SCALARS:
            return
        elif origin is Literal:
            if any(type(value) not in _IMMUTABLE_SCALARS for value in arguments):
                violations.append(f"{path}: Literal contains a non-scalar value")
        elif isinstance(annotation, type) and issubclass(annotation, ProjectionModel):
            if annotation.model_config.get("frozen") is not True:
                violations.append(f"{path}: projection model {annotation.__name__} is not frozen")
            if annotation in active_models:
                return
            hints = get_type_hints(annotation, include_extras=True)
            for field_name in annotation.model_fields:
                visit(
                    hints[field_name],
                    f"{path}.{field_name}" if path else field_name,
                    active_models | {annotation},
                    substitutions,
                )
        else:
            violations.append(f"{path}: unsupported mutable or unknown annotation {annotation!r}")

    visit(root, "", frozenset())
    return tuple(violations)


def projected_record_owner_paths(root: type[ProjectionModel]) -> frozenset[str]:
    """Return every reachable projection path whose annotation owns a full record."""
    owners: set[str] = set()
    active_aliases: set[TypeAliasType] = set()
    missing = object()

    def visit(
        annotation: object,
        path: str,
        active_models: frozenset[type[ProjectionModel]],
        substitutions: tuple[tuple[object, object], ...] = (),
    ) -> None:
        replacement = next(
            (value for parameter, value in reversed(substitutions) if annotation is parameter),
            missing,
        )
        if replacement is not missing:
            visit(replacement, path, active_models, substitutions)
            return
        if isinstance(annotation, TypeAliasType):
            if annotation in active_aliases:
                return
            active_aliases.add(annotation)
            try:
                visit(annotation.__value__, path, active_models, substitutions)
            finally:
                active_aliases.remove(annotation)
            return
        origin = get_origin(annotation)
        arguments = get_args(annotation)
        if isinstance(origin, TypeAliasType):
            if origin in active_aliases:
                for argument in arguments:
                    visit(argument, path, active_models, substitutions)
                return
            active_aliases.add(origin)
            try:
                parameters = tuple(origin.__type_params__)
                visit(
                    origin.__value__,
                    path,
                    active_models,
                    (*substitutions, *zip(parameters, arguments, strict=True)),
                )
            finally:
                active_aliases.remove(origin)
        elif origin is Annotated:
            visit(arguments[0], path, active_models, substitutions)
        elif origin in (Union, UnionType, tuple, frozenset):
            for member in arguments:
                if member is not Ellipsis:
                    visit(member, path, active_models, substitutions)
        elif origin is FrozenMap:
            if len(arguments) == 2:
                visit(arguments[0], f"{path}.key", active_models, substitutions)
                visit(arguments[1], path, active_models, substitutions)
        elif isinstance(annotation, type) and issubclass(annotation, ProjectedRecordBase):
            owners.add(path)
        elif isinstance(annotation, type) and issubclass(annotation, ProjectionModel):
            if annotation in active_models:
                return
            hints = get_type_hints(annotation, include_extras=True)
            for field_name in annotation.model_fields:
                visit(
                    hints[field_name],
                    f"{path}.{field_name}" if path else field_name,
                    active_models | {annotation},
                    substitutions,
                )

    visit(root, "", frozenset())
    return frozenset(owners)


def projection_event_dispatch_types(source: str) -> frozenset[str]:
    """Return event names with reachable, successful ``reduce_event`` branches."""
    tree = ast.parse(source)

    def statement_bindings(node: ast.AST) -> frozenset[str]:
        bindings = {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
        }
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                bindings.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                bindings.update(alias.asname or alias.name for alias in child.names)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.add(child.name)
            elif isinstance(child, ast.ExceptHandler) and child.name is not None:
                bindings.add(child.name)
            elif isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name is not None:
                bindings.add(child.name)
            elif isinstance(child, ast.MatchMapping) and child.rest is not None:
                bindings.add(child.rest)
        return frozenset(bindings)

    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list:
                functions.pop(node.name, None)
            else:
                functions[node.name] = node
            continue
        for binding in statement_bindings(node):
            functions.pop(binding, None)
    dispatched: set[str] = set()
    Constraint = tuple[frozenset[str] | None, frozenset[str]]
    visited: set[tuple[str, Constraint]] = set()

    def is_event_type(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "event_type"
            and isinstance(node.value, ast.Name)
            and node.value.id == "event"
        )

    def test_values(test: ast.AST) -> frozenset[str]:
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or len(test.comparators) != 1
            or not is_event_type(test.left)
        ):
            return frozenset()
        values: set[str] = set()
        for operator, comparator in zip(test.ops, test.comparators, strict=True):
            if isinstance(operator, ast.Eq) and isinstance(comparator, ast.Constant):
                if isinstance(comparator.value, str):
                    values.add(comparator.value)
            elif isinstance(operator, ast.In) and isinstance(comparator, (ast.Set, ast.Tuple)):
                values.update(
                    element.value
                    for element in comparator.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                )
        return frozenset(values)

    def matching(values: frozenset[str], constraint: Constraint) -> frozenset[str]:
        included, excluded = constraint
        matched = values - excluded
        return matched if included is None else matched & included

    def constrained(constraint: Constraint, values: frozenset[str]) -> Constraint:
        included, excluded = constraint
        available = values if included is None else included & values
        return available - excluded, frozenset()

    def excluding(constraint: Constraint, values: frozenset[str]) -> Constraint:
        included, excluded = constraint
        if included is None:
            return None, excluded | values
        return included - values, excluded

    def dispatch_outcomes(statements: list[ast.stmt], constraint: Constraint) -> frozenset[str]:
        outcomes = frozenset({"fallthrough"})
        for statement in statements:
            if "fallthrough" not in outcomes:
                break
            terminal = outcomes - {"fallthrough"}
            statement_outcomes = frozenset({"fallthrough"})
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                pass
            elif isinstance(statement, ast.Return):
                successful = not (
                    statement.value is None
                    or isinstance(statement.value, ast.Constant)
                    and statement.value.value is None
                )
                statement_outcomes = frozenset({"success" if successful else "failure"})
            elif isinstance(statement, ast.Raise):
                statement_outcomes = frozenset({"failure"})
            elif isinstance(statement, ast.If):
                if isinstance(statement.test, ast.Constant):
                    selected = statement.body if bool(statement.test.value) else statement.orelse
                    statement_outcomes = dispatch_outcomes(selected, constraint)
                else:
                    values = test_values(statement.test)
                    if values:
                        branch_outcomes: set[str] = set()
                        body_constraint = constrained(constraint, values)
                        if matching(values, constraint):
                            branch_outcomes.update(
                                dispatch_outcomes(statement.body, body_constraint)
                            )
                        included, excluded = constraint
                        unmatched = None if included is None else (included - excluded) - values
                        if unmatched is None or unmatched:
                            branch_outcomes.update(
                                dispatch_outcomes(
                                    statement.orelse,
                                    excluding(constraint, values),
                                )
                            )
                        statement_outcomes = frozenset(branch_outcomes)
                    else:
                        statement_outcomes = dispatch_outcomes(
                            statement.body, constraint
                        ) | dispatch_outcomes(statement.orelse, constraint)
            outcomes = terminal | statement_outcomes
        return outcomes

    def always_dispatches(statements: list[ast.stmt], constraint: Constraint) -> bool:
        return dispatch_outcomes(statements, constraint) == frozenset({"success"})

    def tested_non_none_name(statement: ast.stmt) -> str | None:
        if not isinstance(statement, ast.If) or not always_dispatches(
            statement.body, (None, frozenset())
        ):
            return None
        test = statement.test
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or len(test.comparators) != 1
            or not isinstance(test.left, ast.Name)
        ):
            return None
        if any(
            isinstance(operator, (ast.IsNot, ast.NotEq))
            and isinstance(comparator, ast.Constant)
            and comparator.value is None
            for operator, comparator in zip(test.ops, test.comparators, strict=True)
        ):
            return test.left.id
        return None

    def assigned_names(statement: ast.stmt) -> frozenset[str]:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets.extend(statement.targets)
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            targets.append(statement.target)
        elif isinstance(statement, ast.Delete):
            targets.extend(statement.targets)

        def target_names(target: ast.expr) -> tuple[str, ...]:
            if isinstance(target, ast.Name):
                return (target.id,)
            if isinstance(target, (ast.Tuple, ast.List)):
                return tuple(name for element in target.elts for name in target_names(element))
            return ()

        return frozenset(name for target in targets for name in target_names(target))

    def called_helpers(expression: ast.AST, shadowed_names: frozenset[str]) -> tuple[str, ...]:
        helpers: list[str] = []

        def literal_index(node: ast.expr) -> int | None:
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                return node.value
            if (
                isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)
                and isinstance(node.operand.value, int)
            ):
                return -node.operand.value
            return None

        def visit_expression(node: ast.AST) -> None:
            if isinstance(
                node, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
            ):
                return
            if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Constant):
                visit_expression(node.body if bool(node.test.value) else node.orelse)
                return
            if isinstance(node, ast.Subscript) and isinstance(node.value, (ast.Tuple, ast.List)):
                index = literal_index(node.slice)
                if index is None:
                    return
                if -len(node.value.elts) <= index < len(node.value.elts):
                    visit_expression(node.value.elts[index])
                return
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id not in shadowed_names
                    and any(
                        isinstance(argument, ast.Name) and argument.id == "event"
                        for argument in node.args
                    )
                ):
                    helpers.append(node.func.id)
                return

        visit_expression(expression)
        return tuple(helpers)

    def visit_statements(
        statements: list[ast.stmt], constraint: Constraint, shadowed_names: frozenset[str]
    ) -> None:
        current = constraint
        for index, statement in enumerate(statements):
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(statement, ast.If):
                if isinstance(statement.test, ast.Constant):
                    selected = statement.body if bool(statement.test.value) else statement.orelse
                    visit_statements(selected, current, shadowed_names)
                    if always_dispatches(selected, current):
                        return
                    continue
                values = test_values(statement.test)
                body_constraint = constrained(current, values) if values else current
                body_always_dispatches = values and always_dispatches(
                    statement.body, body_constraint
                )
                if body_always_dispatches:
                    dispatched.update(matching(values, current))
                visit_statements(statement.body, body_constraint, shadowed_names)
                else_constraint = excluding(current, values) if values else current
                visit_statements(statement.orelse, else_constraint, shadowed_names)
                if always_dispatches([statement], current):
                    return
                if body_always_dispatches:
                    current = else_constraint
                continue
            expressions: list[ast.AST] = []
            if isinstance(statement, ast.Return) and statement.value is not None:
                expressions.append(statement.value)
            elif (
                isinstance(statement, (ast.Assign, ast.AnnAssign))
                and statement.value is not None
                and index + 1 < len(statements)
                and tested_non_none_name(statements[index + 1]) in assigned_names(statement)
            ):
                expressions.append(statement.value)
            for expression in expressions:
                for helper_name in called_helpers(expression, shadowed_names):
                    visit_function(helper_name, current)
            if isinstance(statement, (ast.Return, ast.Raise)):
                return

    def visit_function(name: str, constraint: Constraint) -> None:
        key = (name, constraint)
        if key in visited or name not in functions:
            return
        visited.add(key)
        function = functions[name]
        shadowed_names = {
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
        }
        for node in ast.walk(function):
            if isinstance(node, ast.Import):
                shadowed_names.update(
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                shadowed_names.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node is not function:
                    shadowed_names.add(node.name)
            elif isinstance(node, ast.ExceptHandler) and node.name is not None:
                shadowed_names.add(node.name)
            elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name is not None:
                shadowed_names.add(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest is not None:
                shadowed_names.add(node.rest)
        shadowed_names.update(
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        )
        if function.args.vararg is not None:
            shadowed_names.add(function.args.vararg.arg)
        if function.args.kwarg is not None:
            shadowed_names.add(function.args.kwarg.arg)
        visit_statements(function.body, constraint, frozenset(shadowed_names))

    visit_function("reduce_event", (None, frozenset()))
    return frozenset(dispatched)


def projection_contract_violations(root: Path) -> tuple[str, ...]:
    """Return fail-closed immutable GraphProjection contract violations."""
    model_source = (root / "src/orchestrator/graph/projection_models.py").read_text()
    projection_source = (root / "src/orchestrator/graph/projections.py").read_text()
    violations = list(projection_annotation_violations(GraphProjection))
    if "TypedDict" in model_source:
        violations.append("projection_models.py retains a legacy TypedDict projection")
    if "_clone_projection" in projection_source:
        violations.append("projections.py retains _clone_projection")
    record_owners = projected_record_owner_paths(GraphProjection)
    if record_owners != frozenset({"records.by_id"}):
        violations.append(
            f"projected record owners must be records.by_id, found {sorted(record_owners)}"
        )
    dispatched = projection_event_dispatch_types(projection_source)
    if CANONICAL_EVENT_TYPES != dispatched | PROJECTION_NEUTRAL_EVENT_TYPES:
        violations.append(
            "canonical event dispatch mismatch: "
            f"missing={sorted(CANONICAL_EVENT_TYPES - dispatched - PROJECTION_NEUTRAL_EVENT_TYPES)}, "
            f"unexpected={sorted(dispatched | PROJECTION_NEUTRAL_EVENT_TYPES - CANONICAL_EVENT_TYPES)}"
        )
    return tuple(violations)


def has_projection_provenance_seed(source: str) -> bool:
    """Return whether source can contain a collector-approved provenance origin.

    This conservative lexical planner intentionally accepts shadowed or otherwise
    unusable origin names. It rejects only files with no finite origin from which
    the collector can establish GraphProjection provenance.
    """
    try:
        names = {
            token.string
            for token in tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__)
            if token.type == tokenize.NAME
        }
    except (StopIteration, tokenize.TokenError):
        return True
    return bool(names & projection_provenance_seed_tokens())


def _collect_projection_provenance(
    source_and_path: tuple[str, str],
) -> tuple[ProjectionProvenanceFact, ...]:
    """Collect one independent source's provenance in a worker process."""
    source, relative_path = source_and_path
    return projection_provenance(source, relative_path=relative_path)


class BoundaryViolation(BaseModel):
    """One deterministic source location that crosses the storage boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    line: int
    column: int
    code: str
    message: str


class _BoundaryVisitor(ast.NodeVisitor):
    def __init__(
        self,
        relative_path: str,
        source: str,
        provenance: tuple[ProjectionProvenanceFact, ...],
    ) -> None:
        self.relative_path = relative_path
        self.source_lines = source.splitlines()
        self.provenance = {(item.line, item.column, item.expression) for item in provenance}
        self.violations: list[BoundaryViolation] = []

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self.violations.append(
            BoundaryViolation(
                relative_path=self.relative_path,
                line=node.lineno,
                column=node.col_offset,
                code=code,
                message=message,
            )
        )

    def _is_projection(self, node: ast.expr) -> bool:
        if node.lineno > len(self.source_lines):
            return False
        column = len(
            self.source_lines[node.lineno - 1].encode("utf-8")[: node.col_offset].decode("utf-8")
        )
        return (node.lineno, column, ast.unparse(node)) in self.provenance

    def _resolved_import_module(self, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        source_parts = Path(self.relative_path).parts
        try:
            source_root = source_parts.index("src")
        except ValueError:
            return node.module or ""
        package_parts = source_parts[source_root + 1 : -1]
        retained = len(package_parts) - (node.level - 1)
        if retained < 0:
            return node.module or ""
        imported_parts = tuple((node.module or "").split(".")) if node.module else ()
        return ".".join((*package_parts[:retained], *imported_parts))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = self._resolved_import_module(node)
        if module in _PUBLIC_PROJECTION_STAR_IMPORT_MODULES and any(
            imported.name == "*" for imported in node.names
        ):
            self._add(
                node,
                "projection_public_star_import",
                "projection-producing public modules must not be star imported",
            )
        forbidden_graph_import = module.startswith("orchestrator.graph.") or (
            node.level > 0 and module == "orchestrator.graph"
        )
        if node.level > 0:
            imported_modules = {
                f"{module}.{imported.name}" if module else imported.name for imported in node.names
            }
            forbidden_graph_import = forbidden_graph_import or any(
                imported == "orchestrator.graph" or imported.startswith("orchestrator.graph.")
                for imported in imported_modules
            )
        if forbidden_graph_import and not self.relative_path.startswith("src/orchestrator/graph/"):
            self._add(
                node,
                "forbidden_graph_submodule_import",
                "external modules must import graph symbols through orchestrator.graph",
            )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if not self.relative_path.startswith("src/orchestrator/graph/") and any(
            imported.name.startswith("orchestrator.graph.") for imported in node.names
        ):
            self._add(
                node,
                "forbidden_graph_submodule_import",
                "external modules must import graph symbols through orchestrator.graph",
            )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self.relative_path not in ALLOWED_STORAGE_READERS and self._is_projection(node.value):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                self._add(
                    node,
                    "legacy_projection_subscript",
                    "literal GraphProjection subscripts are forbidden outside storage internals",
                )
            else:
                self._add(
                    node,
                    "dynamic_projection_access",
                    "dynamic GraphProjection access is forbidden",
                )
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self._add(
                    node,
                    "mutable_projection_operation",
                    "GraphProjection storage is immutable",
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            self._is_projection(node.value)
            and node.attr in _GROUPED_STORAGE_NAMES
            and self.relative_path not in ALLOWED_STORAGE_READERS
        ):
            self._add(
                node,
                "forbidden_grouped_storage_access",
                "grouped GraphProjection storage is restricted to the exact allowlist",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self.relative_path not in ALLOWED_STORAGE_READERS
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTABLE_METHODS
            and self._is_projection(node.func.value)
        ):
            self._add(
                node,
                "mutable_projection_operation",
                "GraphProjection storage is immutable",
            )
        self.generic_visit(node)


def check_projection_boundaries(
    root: Path, *, paths: tuple[Path, ...] | None = None
) -> tuple[BoundaryViolation, ...]:
    """Return all forbidden boundary crossings in tracked Python source files."""
    selected = paths
    if selected is None:
        selected = tuple(
            root / relative_path
            for relative_path in subprocess.run(
                ("git", "-C", str(root), "ls-files", "--", "*.py"),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
    parsed_sources: list[tuple[str, str, ast.Module, bool]] = []
    for path in sorted(selected):
        relative_path = path.relative_to(root).as_posix()
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as error:
            raise ValueError(
                f"cannot check malformed Python source {relative_path}: {error}"
            ) from error
        has_storage_shaped_operation = any(
            isinstance(node, ast.Subscript)
            or isinstance(node, ast.Attribute)
            and node.attr in _GROUPED_STORAGE_NAMES
            or isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTABLE_METHODS
            for node in ast.walk(tree)
        )
        needs_provenance = has_storage_shaped_operation and has_projection_provenance_seed(source)
        parsed_sources.append((relative_path, source, tree, needs_provenance))

    provenance_inputs = tuple(
        (source, relative_path)
        for relative_path, source, _, needs_provenance in parsed_sources
        if needs_provenance
    )
    if len(provenance_inputs) < 4:
        provenance = tuple(map(_collect_projection_provenance, provenance_inputs))
    else:
        worker_count = min(8, len(provenance_inputs), os.cpu_count() or 1)
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            provenance = tuple(executor.map(_collect_projection_provenance, provenance_inputs))
    provenance_by_path = {
        relative_path: facts
        for (_, relative_path), facts in zip(provenance_inputs, provenance, strict=True)
    }

    violations: list[BoundaryViolation] = []
    for relative_path, source, tree, _ in parsed_sources:
        visitor = _BoundaryVisitor(
            relative_path,
            source,
            provenance_by_path.get(relative_path, ()),
        )
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return tuple(
        sorted(violations, key=lambda item: (item.relative_path, item.line, item.column, item.code))
    )


def main() -> int:
    """Print all boundary crossings and return nonzero when any exist."""
    root = Path(__file__).parents[1]
    violations = check_projection_boundaries(root)
    for violation in violations:
        print(
            f"{violation.relative_path}:{violation.line}:{violation.column}: "
            f"{violation.code}: {violation.message}"
        )
    contract_violations = projection_contract_violations(root)
    for violation in contract_violations:
        print(f"graph-projection-contract: {violation}")
    return 1 if violations or contract_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
