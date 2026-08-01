"""AST-only provenance facts used by the permanent projection boundary guard."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


GRAPH_PROJECTION_TYPES = frozenset({"orchestrator.graph.GraphProjection"})
PROJECTION_FUNCTIONS = frozenset(
    {
        "orchestrator.graph.initial_projection",
        "orchestrator.graph.build_projection",
        "orchestrator.graph.reduce_event",
        "orchestrator.graph_runtime.controller.rebuild_projection",
    }
)
PROJECTION_METHODS = {
    ("GraphController", "read_projection"): "value",
    ("GraphEventStore", "load_projection_with_tail"): "first_tuple_item",
    ("GraphEventStore", "read_projection_checkpoint"): "GraphProjectionCheckpoint",
}
PROJECTION_FIELDS = {
    "GraphDispatchContext": frozenset({"graph_projection"}),
    "GraphProjectionCheckpoint": frozenset({"projection"}),
}


class ProjectionProvenanceFact(BaseModel):
    """One source-ordered expression with approved projection provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    line: int
    column: int
    expression: str
    certainty: Literal["definite", "possible"]


@dataclass
class _Scope:
    origins: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, Literal["definite", "possible"]] = field(default_factory=dict)
    receiver_types: dict[str, str] = field(default_factory=dict)
    fields: dict[str, frozenset[str]] = field(default_factory=dict)
    functions: dict[str, str] = field(default_factory=dict)

    def copy(self) -> _Scope:
        return _Scope(
            dict(self.origins),
            dict(self.aliases),
            dict(self.receiver_types),
            dict(self.fields),
            dict(self.functions),
        )


def _target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for child in node.elts for name in _target_names(child))
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return ()


class ProjectionProvenanceCollector:
    """Resolve only the finite origins that can reach storage-boundary checks."""

    def __init__(self, source: str, relative_path: str) -> None:
        self.source = source
        self.relative_path = relative_path
        self.source_lines = source.splitlines()
        self.facts: dict[tuple[int, int], ProjectionProvenanceFact] = {}

    def visit(self, tree: ast.Module) -> None:
        self._visit_block(tree.body, _Scope())

    def _position(self, node: ast.AST) -> tuple[int, int]:
        line = self.source_lines[node.lineno - 1]
        return node.lineno, len(line.encode("utf-8")[: node.col_offset].decode("utf-8"))

    def _record(self, node: ast.expr, certainty: Literal["definite", "possible"]) -> None:
        line, column = self._position(node)
        self.facts[(line, column)] = ProjectionProvenanceFact(
            line=line,
            column=column,
            expression=ast.unparse(node),
            certainty=certainty,
        )

    def _import_module(self, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return node.module
        path = Path(self.relative_path)
        if path.suffix != ".py" or path.parts[:1] != ("src",):
            return None
        package = path.with_suffix("").parts[1:-1]
        if node.level > len(package):
            return None
        return ".".join(
            (*package[: len(package) - node.level + 1], *(node.module or "").split("."))
        ).rstrip(".")

    def _bind_import(self, node: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        if isinstance(node, ast.Import):
            for item in node.names:
                name = item.asname or item.name.split(".")[0]
                self._clear(name, scope)
                if item.name in {"orchestrator.graph", "orchestrator.graph_runtime"}:
                    scope.origins[name] = item.name
            return
        module = self._import_module(node)
        for item in node.names:
            if item.name == "*":
                continue
            name = item.asname or item.name
            self._clear(name, scope)
            if module is not None:
                origin = f"{module}.{item.name}"
                if origin in GRAPH_PROJECTION_TYPES | PROJECTION_FUNCTIONS or origin.rpartition(
                    "."
                )[2] in {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS):
                    scope.origins[name] = origin

    @staticmethod
    def _clear(name: str, scope: _Scope) -> None:
        scope.origins.pop(name, None)
        scope.aliases.pop(name, None)
        scope.receiver_types.pop(name, None)
        scope.fields.pop(name, None)
        scope.functions.pop(name, None)

    def _origin(self, node: ast.expr, scope: _Scope) -> str | None:
        if isinstance(node, ast.Name):
            return scope.origins.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            prefix = scope.origins.get(node.value.id)
            return f"{prefix}.{node.attr}" if prefix else None
        return None

    def _annotation(self, node: ast.expr | None, scope: _Scope) -> str | None:
        if node is None:
            return None
        origin = self._origin(node, scope)
        if origin in GRAPH_PROJECTION_TYPES:
            return "GraphProjection"
        if origin is not None:
            return origin.rpartition(".")[2]
        if isinstance(node, ast.Name):
            return scope.receiver_types.get(node.id) or scope.origins.get(node.id, node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            members = {self._annotation(node.left, scope), self._annotation(node.right, scope)}
            return (
                "GraphProjection"
                if "GraphProjection" in members
                else next(iter(members - {None}), None)
            )
        return None

    def _certainty(self, node: ast.expr, scope: _Scope) -> Literal["definite", "possible"] | None:
        if isinstance(node, ast.Name):
            return scope.aliases.get(node.id)
        if isinstance(node, ast.Await):
            return self._certainty(node.value, scope)
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.attr in scope.fields.get(
                node.value.id, frozenset()
            ):
                return "definite"
            return self._certainty(node.value, scope)
        if isinstance(node, ast.Subscript):
            return self._certainty(node.value, scope)
        if not isinstance(node, ast.Call):
            return None
        origin = self._origin(node.func, scope)
        if origin in PROJECTION_FUNCTIONS:
            return "definite"
        if (
            isinstance(node.func, ast.Name)
            and scope.functions.get(node.func.id) == "GraphProjection"
        ):
            return "definite"
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            receiver = scope.receiver_types.get(node.func.value.id)
            shape = PROJECTION_METHODS.get((receiver or "", node.func.attr))
            if shape == "value":
                return "definite"
        return None

    def _visit_expr(self, node: ast.AST | None, scope: _Scope) -> None:
        if node is None:
            return
        if isinstance(node, ast.expr):
            certainty = self._certainty(node, scope)
            if certainty is not None:
                self._record(node, certainty)
        for child in ast.iter_child_nodes(node):
            self._visit_expr(child, scope)

    def _set_alias(self, name: str, value: ast.expr | None, scope: _Scope) -> None:
        self._clear(name, scope)
        if value is not None and (certainty := self._certainty(value, scope)) is not None:
            scope.aliases[name] = certainty

    def _assign(self, node: ast.Assign | ast.AnnAssign, scope: _Scope) -> None:
        value = node.value
        self._visit_expr(value, scope)
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        for target in targets:
            self._visit_expr(target, scope)
        if (
            isinstance(node, ast.Assign)
            and len(targets) == 1
            and isinstance(targets[0], (ast.Tuple, ast.List))
            and isinstance(value, (ast.Call, ast.Await))
        ):
            call = value.value if isinstance(value, ast.Await) else value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
            ):
                receiver = scope.receiver_types.get(call.func.value.id)
                if (
                    PROJECTION_METHODS.get((receiver or "", call.func.attr)) == "first_tuple_item"
                    and targets[0].elts
                ):
                    first = targets[0].elts[0]
                    if isinstance(first, ast.Name):
                        self._clear(first.id, scope)
                        scope.aliases[first.id] = "definite"
                    return
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                if (
                    target.attr in scope.fields.get(target.value.id, frozenset())
                    and value is not None
                ):
                    if self._certainty(value, scope) is not None:
                        scope.fields[target.value.id] = scope.fields[target.value.id] | frozenset(
                            {target.attr}
                        )
                continue
            for name in _target_names(target):
                annotation = (
                    self._annotation(node.annotation, scope)
                    if isinstance(node, ast.AnnAssign)
                    else None
                )
                local_return = (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in scope.functions
                )
                if annotation not in {None, "GraphProjection"} or local_return:
                    self._clear(name, scope)
                else:
                    self._set_alias(name, value, scope)
                if annotation == "GraphProjection":
                    scope.aliases[name] = "definite"
                if annotation in {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS):
                    scope.receiver_types[name] = annotation
                    scope.fields[name] = PROJECTION_FIELDS.get(annotation, frozenset())
                typed = self._typed_producer(value, scope)
                if typed is not None:
                    scope.receiver_types[name] = typed
                    scope.fields[name] = PROJECTION_FIELDS.get(typed, frozenset())

    def _typed_producer(self, value: ast.expr | None, scope: _Scope) -> str | None:
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
            return None
        if not isinstance(value.func.value, ast.Name):
            return None
        receiver = scope.receiver_types.get(value.func.value.id)
        shape = PROJECTION_METHODS.get((receiver or "", value.func.attr))
        return shape if shape in PROJECTION_FIELDS else None

    def _merge(self, before: _Scope, branches: tuple[_Scope, ...]) -> _Scope:
        merged = before.copy()
        names = set().union(*(set(branch.aliases) for branch in branches))
        for name in names:
            values = [branch.aliases.get(name) for branch in branches]
            if all(value == "definite" for value in values):
                merged.aliases[name] = "definite"
            elif any(value is not None for value in values):
                merged.aliases[name] = "possible"
            else:
                merged.aliases.pop(name, None)
        return merged

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: _Scope) -> None:
        self._clear(node.name, scope)
        if not node.decorator_list:
            scope.functions[node.name] = self._annotation(node.returns, scope) or ""
        local = scope.copy()
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            self._clear(argument.arg, local)
            annotation = self._annotation(argument.annotation, scope)
            if annotation == "GraphProjection":
                local.aliases[argument.arg] = "definite"
            elif annotation in (
                {name for name, _ in PROJECTION_METHODS}
                | set(PROJECTION_FIELDS)
                | set(scope.fields)
            ):
                local.receiver_types[argument.arg] = annotation
                local.fields[argument.arg] = scope.fields.get(
                    annotation, PROJECTION_FIELDS.get(annotation, frozenset())
                )
        self._visit_block(node.body, local)

    def _class(self, node: ast.ClassDef, scope: _Scope) -> None:
        fields = {
            child.target.id
            for child in node.body
            if isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and self._annotation(child.annotation, scope) == "GraphProjection"
        }
        self._clear(node.name, scope)
        if fields:
            scope.fields[node.name] = frozenset(fields)

    def _visit_block(self, statements: list[ast.stmt], scope: _Scope) -> _Scope:
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._bind_import(statement, scope)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self._assign(statement, scope)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(statement, scope)
            elif isinstance(statement, ast.ClassDef):
                self._class(statement, scope)
            elif isinstance(statement, ast.If):
                self._visit_expr(statement.test, scope)
                body = self._visit_block(statement.body, scope.copy())
                otherwise = self._visit_block(statement.orelse, scope.copy())
                scope = self._merge(scope, (body, otherwise))
            else:
                self._visit_expr(statement, scope)
                nested = [
                    self._visit_block(block, scope.copy())
                    for block in self._nested_blocks(statement)
                ]
                if nested:
                    scope = self._merge(scope, tuple(nested))
        return scope

    @staticmethod
    def _nested_blocks(statement: ast.stmt) -> tuple[list[ast.stmt], ...]:
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            return statement.body, statement.orelse
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            return (statement.body,)
        if isinstance(statement, (ast.Try, ast.TryStar)):
            return (
                statement.body,
                *(item.body for item in statement.handlers),
                statement.orelse,
                statement.finalbody,
            )
        if isinstance(statement, ast.Match):
            return tuple(case.body for case in statement.cases)
        return ()


def projection_provenance(
    source: str, *, relative_path: str
) -> tuple[ProjectionProvenanceFact, ...]:
    """Return source-positioned facts from the permanent, fail-closed collector."""
    tree = ast.parse(source, filename=relative_path)
    collector = ProjectionProvenanceCollector(source, relative_path)
    collector.visit(tree)
    return tuple(sorted(collector.facts.values(), key=lambda item: (item.line, item.column)))


def projection_provenance_seed_tokens() -> frozenset[str]:
    """Return the finite token set that can start approved provenance."""
    origins = (*GRAPH_PROJECTION_TYPES, *PROJECTION_FUNCTIONS)
    typed_names = {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS)
    return frozenset({*(origin.rpartition(".")[2] for origin in origins), *typed_names})
