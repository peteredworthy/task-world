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
_PROJECTION_TYPE_ORIGINS = frozenset(
    {
        "orchestrator.graph.GraphController",
        "orchestrator.graph.GraphEventStore",
        "orchestrator.graph.GraphDispatchContext",
        "orchestrator.graph.GraphProjectionCheckpoint",
    }
)


class ProjectionProvenanceFact(BaseModel):
    """One source-ordered expression with approved projection provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    line: int
    column: int
    expression: str
    certainty: Literal["definite", "possible"]


@dataclass
class _FlowState:
    """Finite forward state for the boundary collector.

    Every mapping is runtime state and therefore participates in joins.  Class
    declarations are discovered separately and copied into function entries.
    """

    origins: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, Literal["definite", "possible"]] = field(default_factory=dict)
    receiver_types: dict[str, str] = field(default_factory=dict)
    fields: dict[str, frozenset[str]] = field(default_factory=dict)
    possible_fields: dict[str, frozenset[str]] = field(default_factory=dict)
    field_types: dict[str, frozenset[str]] = field(default_factory=dict)
    functions: dict[str, str] = field(default_factory=dict)

    def copy(self) -> _FlowState:
        return _FlowState(
            dict(self.origins),
            dict(self.aliases),
            dict(self.receiver_types),
            dict(self.fields),
            dict(self.possible_fields),
            dict(self.field_types),
            dict(self.functions),
        )


# Kept as a private spelling during the transition of individual transfer
# helpers; all states constructed by the collector are `_FlowState` instances.
_Scope = _FlowState


@dataclass
class _Outcomes:
    """Explicit control paths emitted by one statement transfer."""

    normal: list[_FlowState] = field(default_factory=list)
    raised: list[_FlowState] = field(default_factory=list)
    returned: list[_FlowState] = field(default_factory=list)
    broken: list[_FlowState] = field(default_factory=list)
    continued: list[_FlowState] = field(default_factory=list)


def _target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for child in node.elts for name in _target_names(child))
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return ()


def _pattern_capture_names(pattern: ast.pattern) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(pattern):
        if isinstance(node, ast.MatchAs) and node.name is not None:
            names.append(node.name)
        elif isinstance(node, ast.MatchStar) and node.name is not None:
            names.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            names.append(node.rest)
    return tuple(names)


def _is_unconditional_pattern(pattern: ast.pattern) -> bool:
    return isinstance(pattern, ast.MatchAs) and pattern.pattern is None


class ProjectionProvenanceCollector:
    """Resolve only the finite origins that can reach storage-boundary checks."""

    def __init__(self, source: str, relative_path: str) -> None:
        self.source = source
        self.relative_path = relative_path
        self.source_lines = source.splitlines()
        self.facts: dict[tuple[int, int, str], ProjectionProvenanceFact] = {}
        self._function_depth = 0

    def visit(self, tree: ast.Module) -> None:
        self._evaluate_block(tree.body, _FlowState())

    def _position(self, node: ast.AST) -> tuple[int, int]:
        line = self.source_lines[node.lineno - 1]
        return node.lineno, len(line.encode("utf-8")[: node.col_offset].decode("utf-8"))

    def _record(self, node: ast.expr, certainty: Literal["definite", "possible"]) -> None:
        line, column = self._position(node)
        expression = ast.unparse(node)
        self.facts[(line, column, expression)] = ProjectionProvenanceFact(
            line=line,
            column=column,
            expression=expression,
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
                previous = (
                    scope.origins.get(name)
                    if item.asname is None and self._function_depth == 0
                    else None
                )
                self._clear(name, scope)
                if item.name in {
                    "orchestrator.graph",
                    "orchestrator.graph_runtime.controller",
                }:
                    scope.origins[name] = (
                        item.name if previous is None else f"{previous}|{item.name}"
                    )
            return
        module = self._import_module(node)
        for item in node.names:
            if item.name == "*":
                continue
            name = item.asname or item.name
            self._clear(name, scope)
            if module is not None:
                origin = f"{module}.{item.name}"
                if (
                    origin
                    in GRAPH_PROJECTION_TYPES | PROJECTION_FUNCTIONS | _PROJECTION_TYPE_ORIGINS
                ):
                    scope.origins[name] = origin
                elif origin == "orchestrator.graph.projections.GraphProjection":
                    # The import boundary reports this forbidden spelling; retain
                    # projection facts so it cannot hide storage violations.
                    scope.origins[name] = "orchestrator.graph.GraphProjection"

    @staticmethod
    def _clear(name: str, scope: _Scope) -> None:
        scope.origins.pop(name, None)
        scope.aliases.pop(name, None)
        scope.receiver_types.pop(name, None)
        scope.fields.pop(name, None)
        scope.possible_fields.pop(name, None)
        scope.field_types.pop(name, None)
        scope.functions.pop(name, None)

    def _origin(self, node: ast.expr, scope: _Scope) -> str | None:
        if isinstance(node, ast.Name):
            return scope.origins.get(node.id)
        if isinstance(node, ast.Attribute):
            prefix = self._origin(node.value, scope)
            if prefix is None:
                return None
            approved = GRAPH_PROJECTION_TYPES | PROJECTION_FUNCTIONS | _PROJECTION_TYPE_ORIGINS
            candidates: list[str] = []
            for imported in prefix.split("|"):
                if isinstance(node.value, ast.Name) and imported.startswith(
                    f"{node.value.id}.{node.attr}"
                ):
                    candidate = f"{node.value.id}.{node.attr}"
                else:
                    candidate = (
                        imported
                        if imported.rpartition(".")[2] == node.attr
                        else f"{imported}.{node.attr}"
                    )
                # The candidate must stay beneath the *actual imported path*;
                # sharing the `orchestrator` root never authorizes a sibling.
                if any(
                    (
                        imported == candidate
                        or imported.startswith(f"{candidate}.")
                        or candidate.startswith(f"{imported}.")
                    )
                    and (origin == candidate or origin.startswith(f"{candidate}."))
                    for origin in approved
                ):
                    candidates.append(candidate)
            return "|".join(candidates) or None
        return None

    def _annotation(self, node: ast.expr | None, scope: _Scope) -> str | None:
        if node is None:
            return None
        origin = self._origin(node, scope)
        if origin in GRAPH_PROJECTION_TYPES:
            return "GraphProjection"
        if origin in _PROJECTION_TYPE_ORIGINS:
            return origin.rpartition(".")[2]
        if isinstance(node, ast.Name):
            return (
                scope.receiver_types.get(node.id) or scope.origins.get(node.id) or node.id
                if node.id in scope.fields
                else None
            )
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
        if isinstance(node, ast.NamedExpr):
            return self._certainty(node.value, scope)
        if isinstance(node, ast.Await):
            return self._certainty(node.value, scope)
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.attr in scope.fields.get(
                node.value.id, frozenset()
            ):
                return (
                    "possible"
                    if node.attr in scope.possible_fields.get(node.value.id, frozenset())
                    else "definite"
                )
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

    @staticmethod
    def _field_is_declared(receiver: str, field_name: str, scope: _Scope) -> bool:
        return field_name in scope.field_types.get(receiver, frozenset())

    def _set_field_alias(
        self, receiver: str, field_name: str, value: ast.expr | None, scope: _Scope
    ) -> bool:
        if not self._field_is_declared(receiver, field_name, scope):
            return False
        fields = scope.fields.get(receiver, frozenset())
        if value is not None and self._certainty(value, scope) is not None:
            scope.fields[receiver] = fields | frozenset({field_name})
            possible = scope.possible_fields.get(receiver, frozenset())
            certainty = self._certainty(value, scope)
            scope.possible_fields[receiver] = (
                possible | frozenset({field_name})
                if certainty == "possible"
                else possible - frozenset({field_name})
            )
        else:
            scope.fields[receiver] = fields - frozenset({field_name})
            scope.possible_fields[receiver] = scope.possible_fields.get(
                receiver, frozenset()
            ) - frozenset({field_name})
        return True

    def _kill_target(self, target: ast.expr, scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            self._clear(target.id, scope)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            if not self._set_field_alias(target.value.id, target.attr, None, scope):
                self._clear(target.value.id, scope)

    @staticmethod
    def _replace_state(target: _FlowState, source: _FlowState) -> None:
        target.origins = source.origins
        target.aliases = source.aliases
        target.receiver_types = source.receiver_types
        target.fields = source.fields
        target.possible_fields = source.possible_fields
        target.field_types = source.field_types
        target.functions = source.functions

    def _join_states(self, states: list[_FlowState]) -> _FlowState:
        if not states:
            return _FlowState()
        return self._merge(states[0], tuple(states))

    def _join_outcomes(self, outcomes: list[_Outcomes]) -> _Outcomes:
        result = _Outcomes()
        for name in ("normal", "raised", "returned", "broken", "continued"):
            states = [state for outcome in outcomes for state in getattr(outcome, name)]
            if states:
                setattr(result, name, [self._join_states(states)])
        return result

    def _expression_children(self, node: ast.expr) -> tuple[ast.expr, ...]:
        """Return evaluated children in Python evaluation order.

        This deliberately enumerates expression families rather than using
        ``ast.iter_child_nodes``: suites are statement transfers, never an
        incidental side effect of a generic AST walk.
        """
        if isinstance(node, ast.Attribute):
            return (node.value,)
        if isinstance(node, ast.Subscript):
            return (node.value, node.slice)
        if isinstance(node, ast.Await | ast.UnaryOp):
            return (node.value if isinstance(node, ast.Await) else node.operand,)
        if isinstance(node, ast.BinOp | ast.Compare):
            if isinstance(node, ast.BinOp):
                return (node.left, node.right)
            return (node.left, *node.comparators)
        if isinstance(node, ast.Call):
            return (node.func, *node.args, *(keyword.value for keyword in node.keywords))
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return tuple(node.elts)
        if isinstance(node, ast.Dict):
            return tuple(
                item for pair in zip(node.keys, node.values, strict=True) for item in pair if item
            )
        if isinstance(node, ast.JoinedStr):
            return tuple(
                value.value for value in node.values if isinstance(value, ast.FormattedValue)
            )
        if isinstance(node, ast.FormattedValue):
            return (node.value, *(() if node.format_spec is None else (node.format_spec,)))
        if isinstance(node, ast.Starred):
            return (node.value,)
        return ()

    def _evaluate_expression(self, node: ast.expr | None, state: _FlowState) -> _Outcomes:
        if node is None:
            return _Outcomes(normal=[state])
        if isinstance(node, ast.NamedExpr):
            value = self._evaluate_expression(node.value, state)
            normal: list[_FlowState] = []
            for current in value.normal:
                if isinstance(node.target, ast.Name):
                    self._set_alias(node.target.id, node.value, current)
                certainty = self._certainty(node, current)
                if certainty is not None:
                    self._record(node, certainty)
                normal.append(current)
            return _Outcomes(normal=normal, raised=value.raised)
        if isinstance(node, ast.BoolOp):
            current = self._evaluate_expression(node.values[0], state)
            raised = list(current.raised)
            normal = current.normal
            for value in node.values[1:]:
                next_normal: list[_FlowState] = []
                for prior in normal:
                    next_normal.append(prior.copy())  # short-circuit path
                    evaluated = self._evaluate_expression(value, prior)
                    next_normal.extend(evaluated.normal)
                    raised.extend(evaluated.raised)
                normal = [self._join_states(next_normal)] if next_normal else []
            for current_state in normal:
                certainty = self._certainty(node, current_state)
                if certainty is not None:
                    self._record(node, certainty)
            return _Outcomes(normal=normal, raised=raised)
        if isinstance(node, ast.IfExp):
            test = self._evaluate_expression(node.test, state)
            outcomes = [_Outcomes(raised=test.raised)]
            for current in test.normal:
                outcomes.extend(
                    (
                        self._evaluate_expression(node.body, current.copy()),
                        self._evaluate_expression(node.orelse, current.copy()),
                    )
                )
            return self._join_outcomes(outcomes)
        current = _Outcomes(normal=[state])
        for child in self._expression_children(node):
            next_outcomes: list[_Outcomes] = []
            for prior in current.normal:
                next_outcomes.append(self._evaluate_expression(child, prior))
            current = self._join_outcomes([_Outcomes(raised=current.raised), *next_outcomes])
        for current_state in current.normal:
            certainty = self._certainty(node, current_state)
            if certainty is not None:
                self._record(node, certainty)
            # Any evaluated operation can throw after all preceding child effects.
            current.raised.append(current_state.copy())
        return current

    def _assign_value(self, node: ast.Assign | ast.AnnAssign, state: _FlowState) -> None:
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                if self._set_field_alias(target.value.id, target.attr, value, state):
                    continue
                self._clear(target.value.id, state)
                continue
            for name in _target_names(target):
                annotation = (
                    self._annotation(node.annotation, state)
                    if isinstance(node, ast.AnnAssign)
                    else None
                )
                local_return = (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in state.functions
                )
                if (
                    isinstance(node, ast.AnnAssign) and annotation != "GraphProjection"
                ) or local_return:
                    self._clear(name, state)
                else:
                    self._set_alias(name, value, state)
                if annotation == "GraphProjection":
                    state.aliases[name] = "definite"
                if annotation in {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS):
                    state.receiver_types[name] = annotation
                    fields = state.field_types.get(
                        annotation, PROJECTION_FIELDS.get(annotation, frozenset())
                    )
                    state.field_types[name] = fields
                    state.fields[name] = fields
                typed = self._typed_producer(value, state)
                if typed is not None:
                    state.receiver_types[name] = typed
                    fields = state.field_types.get(typed, PROJECTION_FIELDS.get(typed, frozenset()))
                    state.field_types[name] = fields
                    state.fields[name] = fields

    def _evaluate_block(self, statements: list[ast.stmt], state: _FlowState) -> _Outcomes:
        result = _Outcomes(normal=[state])
        for statement in statements:
            following: list[_Outcomes] = []
            for current in result.normal:
                following.append(self._evaluate_statement(statement, current))
            transferred = self._join_outcomes(following)
            result = _Outcomes(
                normal=transferred.normal,
                raised=[*result.raised, *transferred.raised],
                returned=[*result.returned, *transferred.returned],
                broken=[*result.broken, *transferred.broken],
                continued=[*result.continued, *transferred.continued],
            )
        return self._join_outcomes([result])

    def _evaluate_statement(self, node: ast.stmt, state: _FlowState) -> _Outcomes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._bind_import(node, state)
            return _Outcomes(normal=[state])
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = self._evaluate_expression(node.value, state)
            normal = []
            raised = list(value.raised)
            for current in value.normal:
                for target in node.targets if isinstance(node, ast.Assign) else (node.target,):
                    target_outcome = self._evaluate_expression(target, current)
                    raised.extend(target_outcome.raised)
                    for target_state in target_outcome.normal:
                        self._assign_value(node, target_state)
                        normal.append(target_state)
                        raised.append(target_state.copy())
            return self._join_outcomes([_Outcomes(normal=normal, raised=raised)])
        if isinstance(node, ast.AugAssign):
            target = self._evaluate_expression(node.target, state)
            outcomes: list[_Outcomes] = [_Outcomes(raised=target.raised)]
            for current in target.normal:
                value = self._evaluate_expression(node.value, current)
                for result in value.normal:
                    self._kill_target(node.target, result)
                    value.raised.append(result.copy())
                outcomes.append(value)
            return self._join_outcomes(outcomes)
        if isinstance(node, ast.Delete):
            current = _Outcomes(normal=[state])
            for target in node.targets:
                next_outcomes = []
                for prior in current.normal:
                    evaluated = self._evaluate_expression(target, prior)
                    for result in evaluated.normal:
                        self._kill_target(target, result)
                    next_outcomes.append(evaluated)
                current = self._join_outcomes([_Outcomes(raised=current.raised), *next_outcomes])
            return current
        if isinstance(node, ast.Return):
            value = self._evaluate_expression(node.value, state)
            return _Outcomes(raised=value.raised, returned=value.normal)
        if isinstance(node, ast.Raise):
            value = self._evaluate_expression(node.exc, state)
            return _Outcomes(raised=[*value.raised, *value.normal])
        if isinstance(node, ast.Break):
            return _Outcomes(broken=[state])
        if isinstance(node, ast.Continue):
            return _Outcomes(continued=[state])
        if isinstance(node, ast.If):
            test = self._evaluate_expression(node.test, state)
            branches = [_Outcomes(raised=test.raised)]
            for current in test.normal:
                branches.extend(
                    (
                        self._evaluate_block(node.body, current.copy()),
                        self._evaluate_block(node.orelse, current.copy()),
                    )
                )
            return self._join_outcomes(branches)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            iterator = self._evaluate_expression(
                node.iter if isinstance(node, (ast.For, ast.AsyncFor)) else node.test, state
            )
            branches = [_Outcomes(normal=iterator.normal, raised=iterator.raised)]
            for current in iterator.normal:
                body_state = current.copy()
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    for name in _target_names(node.target):
                        self._clear(name, body_state)
                body = self._evaluate_block(node.body, body_state)
                # zero iteration, completed iteration, break, and continue all reach the join.
                branches.append(
                    _Outcomes(
                        normal=[current.copy(), *body.normal, *body.broken, *body.continued],
                        raised=body.raised,
                        returned=body.returned,
                    )
                )
            joined = self._join_outcomes(branches)
            if node.orelse:
                else_outcomes = [
                    self._evaluate_block(node.orelse, current) for current in joined.normal
                ]
                joined = self._join_outcomes(
                    [_Outcomes(raised=joined.raised, returned=joined.returned), *else_outcomes]
                )
            return joined
        if isinstance(node, ast.Match):
            subject = self._evaluate_expression(node.subject, state)
            branches: list[_Outcomes] = [_Outcomes(raised=subject.raised)]
            unconditional = False
            for current in subject.normal:
                for case in node.cases:
                    case_state = current.copy()
                    for name in _pattern_capture_names(case.pattern):
                        self._clear(name, case_state)
                    guard = self._evaluate_expression(case.guard, case_state)
                    branches.append(_Outcomes(raised=guard.raised))
                    branches.extend(
                        self._evaluate_block(case.body, guarded) for guarded in guard.normal
                    )
                    unconditional |= case.guard is None and _is_unconditional_pattern(case.pattern)
                if not unconditional:
                    branches.append(_Outcomes(normal=[current.copy()]))
            return self._join_outcomes(branches)
        if isinstance(node, (ast.Try, ast.TryStar)):
            body = self._evaluate_block(node.body, state.copy())
            outgoing: list[_Outcomes] = []
            if body.normal:
                outgoing.extend(
                    self._evaluate_block(node.orelse, current) for current in body.normal
                )
            for handler in node.handlers:
                for raised in body.raised:
                    handler_state = raised.copy()
                    if handler.name is not None:
                        self._clear(handler.name, handler_state)
                    outgoing.append(self._evaluate_block(handler.body, handler_state))
            if not node.handlers:
                outgoing.append(_Outcomes(raised=body.raised))
            joined = self._join_outcomes(
                [
                    *outgoing,
                    _Outcomes(returned=body.returned, broken=body.broken, continued=body.continued),
                ]
            )
            if not node.finalbody:
                return joined
            final_outcomes: list[_Outcomes] = []
            for kind in ("normal", "raised", "returned", "broken", "continued"):
                for current in getattr(joined, kind):
                    final = self._evaluate_block(node.finalbody, current.copy())
                    final_outcomes.append(
                        _Outcomes(
                            normal=final.normal if kind == "normal" else [],
                            raised=[*final.raised, *(final.normal if kind == "raised" else [])],
                            returned=[
                                *final.returned,
                                *(final.normal if kind == "returned" else []),
                            ],
                            broken=[*final.broken, *(final.normal if kind == "broken" else [])],
                            continued=[
                                *final.continued,
                                *(final.normal if kind == "continued" else []),
                            ],
                        )
                    )
            return self._join_outcomes(final_outcomes)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._function(node, state)
            return _Outcomes(normal=[state])
        if isinstance(node, ast.ClassDef):
            self._class(node, state)
            return _Outcomes(normal=[state])
        if isinstance(node, ast.Expr):
            return self._evaluate_expression(node.value, state)
        return _Outcomes(normal=[state])

    def _visit_expr(self, node: ast.AST | None, scope: _Scope) -> None:
        if node is None:
            return
        if isinstance(node, ast.NamedExpr):
            self._visit_expr(node.value, scope)
            if isinstance(node.target, ast.Name):
                self._set_alias(node.target.id, node.value, scope)
            certainty = self._certainty(node, scope)
            if certainty is not None:
                self._record(node, certainty)
            return
        if isinstance(node, ast.BoolOp):
            self._visit_expr(node.values[0], scope)
            running = scope.copy()
            for value in node.values[1:]:
                executed = running.copy()
                self._visit_expr(value, executed)
                # The RHS of a non-constant short-circuit operator may not run.
                running = self._merge(running, (running.copy(), executed))
            scope.origins = running.origins
            scope.aliases = running.aliases
            scope.receiver_types = running.receiver_types
            scope.fields = running.fields
            scope.possible_fields = running.possible_fields
            scope.field_types = running.field_types
            scope.functions = running.functions
            certainty = self._certainty(node, scope)
            if certainty is not None:
                self._record(node, certainty)
            return
        if isinstance(node, ast.IfExp):
            self._visit_expr(node.test, scope)
            body = scope.copy()
            otherwise = scope.copy()
            self._visit_expr(node.body, body)
            self._visit_expr(node.orelse, otherwise)
            merged = self._merge(scope, (body, otherwise))
            scope.origins = merged.origins
            scope.aliases = merged.aliases
            scope.receiver_types = merged.receiver_types
            scope.fields = merged.fields
            scope.possible_fields = merged.possible_fields
            scope.field_types = merged.field_types
            scope.functions = merged.functions
            return
        if isinstance(node, ast.expr):
            certainty = self._certainty(node, scope)
            if certainty is not None:
                self._record(node, certainty)
        if isinstance(node, ast.Lambda):
            local = scope.copy()
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                self._clear(argument.arg, local)
            if node.args.vararg is not None:
                self._clear(node.args.vararg.arg, local)
            if node.args.kwarg is not None:
                self._clear(node.args.kwarg.arg, local)
            self._visit_expr(node.body, local)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            local = scope.copy()
            for generator in node.generators:
                self._visit_expr(generator.iter, local)
                for name in _target_names(generator.target):
                    self._clear(name, local)
                for condition in generator.ifs:
                    self._visit_expr(condition, local)
            self._visit_expr(node.elt, local)
            return
        if isinstance(node, ast.DictComp):
            local = scope.copy()
            for generator in node.generators:
                self._visit_expr(generator.iter, local)
                for name in _target_names(generator.target):
                    self._clear(name, local)
                for condition in generator.ifs:
                    self._visit_expr(condition, local)
            self._visit_expr(node.key, local)
            self._visit_expr(node.value, local)
            return
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
                if self._set_field_alias(target.value.id, target.attr, value, scope):
                    continue
                self._clear(target.value.id, scope)
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
                if (
                    isinstance(node, ast.AnnAssign)
                    and annotation != "GraphProjection"
                    or local_return
                ):
                    self._clear(name, scope)
                else:
                    self._set_alias(name, value, scope)
                if annotation == "GraphProjection":
                    scope.aliases[name] = "definite"
                if annotation in {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS):
                    scope.receiver_types[name] = annotation
                    fields = scope.field_types.get(
                        annotation, PROJECTION_FIELDS.get(annotation, frozenset())
                    )
                    scope.field_types[name] = fields
                    scope.fields[name] = fields
                typed = self._typed_producer(value, scope)
                if typed is not None:
                    scope.receiver_types[name] = typed
                    fields = scope.field_types.get(typed, PROJECTION_FIELDS.get(typed, frozenset()))
                    scope.field_types[name] = fields
                    scope.fields[name] = fields

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
        """Join all finite runtime bindings, not only projection aliases."""
        merged = before.copy()
        names = set(before.aliases).union(*(set(branch.aliases) for branch in branches))
        for name in names:
            values = [branch.aliases.get(name) for branch in branches]
            if all(value == "definite" for value in values):
                merged.aliases[name] = "definite"
            elif any(value is not None for value in values):
                merged.aliases[name] = "possible"
            else:
                merged.aliases.pop(name, None)
        for attribute in ("origins", "receiver_types", "field_types", "functions"):
            target = getattr(merged, attribute)
            target.clear()
            keys = set().union(*(set(getattr(branch, attribute)) for branch in branches))
            for key in keys:
                values = [getattr(branch, attribute).get(key) for branch in branches]
                if values[0] is not None and all(value == values[0] for value in values):
                    target[key] = values[0]
        field_keys = set().union(*(set(branch.fields) for branch in branches))
        merged.fields.clear()
        merged.possible_fields.clear()
        for receiver in field_keys:
            values = [branch.fields.get(receiver, frozenset()) for branch in branches]
            present = frozenset().union(*values)
            if present:
                merged.fields[receiver] = present
                definite = frozenset.intersection(*values)
                explicit_possible = frozenset().union(
                    *(branch.possible_fields.get(receiver, frozenset()) for branch in branches)
                )
                merged.possible_fields[receiver] = (present - definite) | explicit_possible
        return merged

    def _function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        scope: _Scope,
        class_name: str | None = None,
    ) -> None:
        self._clear(node.name, scope)
        if not node.decorator_list:
            scope.functions[node.name] = self._annotation(node.returns, scope) or ""
        local = scope.copy()
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        for argument in arguments:
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
                fields = scope.field_types.get(
                    annotation, PROJECTION_FIELDS.get(annotation, frozenset())
                )
                local.field_types[argument.arg] = fields
                local.fields[argument.arg] = fields
        if class_name is not None and node.args.args:
            receiver = node.args.args[0].arg
            fields = scope.field_types.get(class_name, frozenset())
            local.receiver_types[receiver] = class_name
            local.field_types[receiver] = fields
            local.fields[receiver] = fields
        self._function_depth += 1
        try:
            self._evaluate_block(node.body, local)
        finally:
            self._function_depth -= 1

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
            scope.field_types[node.name] = frozenset(fields)
            scope.fields[node.name] = frozenset(fields)
        class_scope = scope.copy()
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(child, class_scope, node.name)
            else:
                outcomes = self._evaluate_block([child], class_scope)
                if outcomes.normal:
                    self._replace_state(class_scope, outcomes.normal[0])

    def _visit_block(self, statements: list[ast.stmt], scope: _Scope) -> _Scope:
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._bind_import(statement, scope)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self._assign(statement, scope)
            elif isinstance(statement, ast.AugAssign):
                self._visit_expr(statement.target, scope)
                self._visit_expr(statement.value, scope)
                self._kill_target(statement.target, scope)
            elif isinstance(statement, ast.Delete):
                for target in statement.targets:
                    self._visit_expr(target, scope)
                    self._kill_target(target, scope)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(statement, scope)
            elif isinstance(statement, ast.ClassDef):
                self._class(statement, scope)
            elif isinstance(statement, ast.If):
                self._visit_expr(statement.test, scope)
                body = self._visit_block(statement.body, scope.copy())
                otherwise = self._visit_block(statement.orelse, scope.copy())
                scope = self._merge(scope, (body, otherwise))
            elif isinstance(statement, (ast.For, ast.AsyncFor)):
                self._visit_expr(statement.iter, scope)
                body_scope = scope.copy()
                for name in _target_names(statement.target):
                    self._clear(name, body_scope)
                body = self._visit_block(statement.body, body_scope)
                otherwise = self._visit_block(statement.orelse, scope.copy())
                scope = self._merge(scope, (body, otherwise))
            elif isinstance(statement, ast.Match):
                self._visit_expr(statement.subject, scope)
                branches: list[_Scope] = []
                has_unconditional_case = False
                for case in statement.cases:
                    case_scope = scope.copy()
                    for name in _pattern_capture_names(case.pattern):
                        self._clear(name, case_scope)
                    self._visit_expr(case.guard, case_scope)
                    branches.append(self._visit_block(case.body, case_scope))
                    has_unconditional_case |= case.guard is None and _is_unconditional_pattern(
                        case.pattern
                    )
                if branches:
                    if not has_unconditional_case:
                        branches.append(scope.copy())
                    scope = self._merge(scope, tuple(branches))
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                body_scope = scope.copy()
                for item in statement.items:
                    self._visit_expr(item.context_expr, scope)
                    if item.optional_vars is not None:
                        for name in _target_names(item.optional_vars):
                            self._clear(name, body_scope)
                scope = self._merge(scope, (self._visit_block(statement.body, body_scope),))
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                try_scope = self._visit_block(statement.body, scope.copy())
                successful_scope = self._visit_block(statement.orelse, try_scope.copy())
                handler_input = self._merge(scope, (scope.copy(), try_scope))
                branches = [successful_scope]
                for handler in statement.handlers:
                    handler_scope = handler_input.copy()
                    if handler.name is not None:
                        self._clear(handler.name, handler_scope)
                    branches.append(self._visit_block(handler.body, handler_scope))
                if statement.finalbody:
                    branches = [
                        self._visit_block(statement.finalbody, branch.copy()) for branch in branches
                    ]
                scope = self._merge(scope, tuple(branches))
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
    return tuple(
        sorted(
            collector.facts.values(),
            key=lambda item: (item.line, item.column, -len(item.expression), item.expression),
        )
    )


def projection_provenance_seed_tokens() -> frozenset[str]:
    """Return the finite token set that can start approved provenance."""
    origins = (*GRAPH_PROJECTION_TYPES, *PROJECTION_FUNCTIONS)
    typed_names = {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS)
    return frozenset({*(origin.rpartition(".")[2] for origin in origins), *typed_names})
