"""Strict ownership-manifest loading and bounded access collection."""

import ast
import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Literal

import libcst as cst
from libcst.metadata import MetadataWrapper, ParentNodeProvider, PositionProvider, ScopeProvider
from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml


class FieldOwnership(BaseModel):
    """The approved destination and migration policy for one flat field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    old_name: str
    new_path: str | None
    group: str | None
    disposition: Literal["canonical", "index", "derived", "removed"]
    value_type: str
    default_policy: str
    merge_policy: str
    ordering: Literal["not_applicable", "insensitive", "sorted", "explicit_index"]
    checkpoint_policy: Literal["canonical", "id_only", "derived", "omitted"]
    public_output_keys: tuple[str, ...] = ()


class NodeCreationFieldOwnership(BaseModel):
    """The explicit destination or removal of one node-creation field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str
    new_path: str | None = None
    removal_reason: str | None = None

    @model_validator(mode="after")
    def has_exactly_one_disposition(self) -> "NodeCreationFieldOwnership":
        if (self.new_path is None) == (self.removal_reason is None):
            message = "node creation field requires one destination or removal reason"
            raise ValueError(message)
        return self


class ProjectionMigrationManifest(BaseModel):
    """Validated ownership manifest for the complete flat projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_revision: str
    fields: tuple[FieldOwnership, ...] = Field(min_length=73, max_length=73)
    node_creation_fields: frozenset[str]
    node_creation_ownership: tuple[NodeCreationFieldOwnership, ...]

    @model_validator(mode="after")
    def node_creation_ownership_is_complete(self) -> "ProjectionMigrationManifest":
        ownership_fields = tuple(ownership.field_name for ownership in self.node_creation_ownership)
        if len(ownership_fields) != len(frozenset(ownership_fields)):
            raise ValueError("duplicate node creation ownership")
        if frozenset(ownership_fields) != self.node_creation_fields:
            raise ValueError("node creation fields and ownership differ")
        return self


def load_manifest(path: Path) -> ProjectionMigrationManifest:
    """Load and strictly validate a projection migration manifest."""
    return ProjectionMigrationManifest.model_validate(yaml.safe_load(path.read_text()))


class AccessKind(StrEnum):
    """Supported legacy GraphProjection access families."""

    LITERAL_SUBSCRIPT_READ = "literal_subscript_read"
    GET = "get"
    MEMBERSHIP = "membership"
    KEYS = "keys"
    VALUES = "values"
    ITEMS = "items"
    DIRECT_ITERATION = "direct_iteration"
    DIRECT_ASSIGNMENT = "direct_assignment"
    NESTED_ASSIGNMENT = "nested_assignment"
    SETDEFAULT = "setdefault"
    APPEND_EXTEND = "append_extend"
    DELETE_POP = "delete_pop"
    UNPACK_CAST = "unpack_cast"
    FIXTURE_CONSTRUCTION = "fixture_construction"
    UNTYPED_ESCAPE = "untyped_escape"


class DiagnosticCode(StrEnum):
    COMPUTED_KEY = "computed_key"
    UNKNOWN_FIELD = "unknown_field"
    PARSE_ERROR = "parse_error"
    REFLECTION = "reflection"
    PROJECTION_UNPACKING = "projection_unpacking"
    UNSUPPORTED_CALL = "unsupported_call"
    UNSUPPORTED_BINDING = "unsupported_binding"
    UNSUPPORTED_CONSTRUCTION = "unsupported_construction"
    UNSUPPORTED_COMPARISON = "unsupported_comparison"


class AccessOccurrence(BaseModel):
    """One supported access to a manifest-owned legacy projection field."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    occurrence_id: str
    relative_path: str
    qualified_function: str
    normalized_expression: str
    same_expression_ordinal: int
    old_field_name: str | None
    kind: AccessKind
    line: int
    column: int
    ordering_sensitivity_disposition: Literal[
        "not_applicable", "insensitive", "sorted", "explicit_index"
    ]


class InventoryDiagnostic(BaseModel):
    """A fail-closed source construct that requires manual migration first."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    line: int
    column: int
    code: DiagnosticCode
    message: str


class SourceInventory(BaseModel):
    """Deterministic collection result for one source file."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    baseline_revision: str
    occurrences: tuple[AccessOccurrence, ...]
    diagnostics: tuple[InventoryDiagnostic, ...]


def occurrence_id(
    baseline_revision: str,
    relative_path: str,
    qualified_function: str,
    normalized_expression: str,
    same_expression_ordinal: int,
) -> str:
    """Create position-independent identity for an inventory occurrence."""
    payload = "\0".join(
        (
            baseline_revision,
            relative_path,
            qualified_function,
            normalized_expression,
            str(same_expression_ordinal),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _manifest_fields() -> dict[str, FieldOwnership]:
    manifest_path = Path(__file__).parent / "codemods" / "graph_projection_manifest.yaml"
    return {field.old_name: field for field in load_manifest(manifest_path).fields}


def _name(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return node.attr.value
    return None


def _literal_key(node: cst.BaseExpression) -> str | None:
    if not isinstance(node, cst.SimpleString):
        return None
    value = cst.parse_expression(node.value)
    if isinstance(value, cst.SimpleString):
        return value.evaluated_value
    return None


class _Collector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider, ParentNodeProvider, ScopeProvider)

    def __init__(
        self, relative_path: str, baseline_revision: str, fields: dict[str, FieldOwnership]
    ) -> None:
        self.relative_path = relative_path
        self.baseline_revision = baseline_revision
        self.fields = fields
        self.lexical_names: list[str] = []
        self.aliases: dict[int, set[str]] = {}
        self.known_aliases: dict[int, set[str]] = {}
        self.records: list[tuple[str, str, str | None, AccessKind, int, int]] = []
        self.diagnostics: list[tuple[str, str, int, int]] = []
        self.handled: set[int] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.lexical_names.append(node.name.value)
        variadic = tuple(
            parameter
            for parameter in (node.params.star_arg, node.params.star_kwarg)
            if isinstance(parameter, cst.Param)
        )
        seeds = {
            parameter.name.value
            for parameter in (
                *node.params.posonly_params,
                *node.params.params,
                *node.params.kwonly_params,
                *variadic,
            )
            if parameter.annotation is not None
            and _name(parameter.annotation.annotation) == "GraphProjection"
        }
        scope_id = id(self.get_metadata(ScopeProvider, node.body))
        self.aliases[scope_id] = seeds
        self.known_aliases[scope_id] = set(seeds)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.lexical_names.pop()

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.lexical_names.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self.lexical_names.pop()

    def _tracked(self, node: cst.BaseExpression) -> bool:
        if not isinstance(node, cst.Name):
            return False
        return node.value in self.aliases.get(id(self.get_metadata(ScopeProvider, node)), set())

    def _known_alias(self, node: cst.Name) -> bool:
        return node.value in self.known_aliases.get(
            id(self.get_metadata(ScopeProvider, node)), set()
        )

    def _projection_operand(self, node: cst.BaseExpression) -> bool:
        return self._tracked(node) or (
            isinstance(node, cst.Subscript) and self._tracked(node.value)
        )

    def _target_names(self, node: cst.BaseAssignTargetExpression) -> tuple[cst.Name, ...]:
        if isinstance(node, cst.Name):
            return (node,)
        if isinstance(node, (cst.Tuple, cst.List)):
            return tuple(
                name
                for element in node.elements
                if element is not None
                for name in self._target_names(element.value)
            )
        return ()

    def _expression(self, node: cst.CSTNode) -> str:
        return ast.unparse(ast.parse(cst.Module([]).code_for_node(node)))

    def _record(self, kind: AccessKind, field: str | None, node: cst.CSTNode) -> None:
        qualified = ".".join(self.lexical_names) or "<module>"
        position = self.get_metadata(PositionProvider, node).start
        self.records.append(
            (qualified, self._expression(node), field, kind, position.line, position.column)
        )

    def _diagnostic(self, code: DiagnosticCode, message: str, node: cst.CSTNode) -> None:
        position = self.get_metadata(PositionProvider, node).start
        self.diagnostics.append((code, message, position.line, position.column))

    def _field_from_subscript(self, node: cst.Subscript) -> str | None:
        if not self._tracked(node.value):
            return None
        if len(node.slice) != 1 or not isinstance(node.slice[0].slice, cst.Index):
            self._diagnostic(
                DiagnosticCode.COMPUTED_KEY, "projection key must be one literal string", node
            )
            return None
        field = _literal_key(node.slice[0].slice.value)
        if field is None:
            self._diagnostic(
                DiagnosticCode.COMPUTED_KEY, "projection key must be one literal string", node
            )
        elif field not in self.fields:
            self._diagnostic(
                DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
            )
        return field if field in self.fields else None

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if not isinstance(node.target, cst.Name):
            if node.value is not None and self._tracked(node.value):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "unsupported projection binding", node
                )
            return
        scope = self.aliases.get(id(self.get_metadata(ScopeProvider, node.target)))
        if scope is None:
            return
        if _name(node.annotation.annotation) == "GraphProjection":
            scope.add(node.target.value)
            self.known_aliases.setdefault(
                id(self.get_metadata(ScopeProvider, node.target)), set()
            ).add(node.target.value)
        else:
            if node.value is not None and self._tracked(node.value):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING,
                    "annotated assignment loses projection type",
                    node,
                )
            scope.discard(node.target.value)

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        if (isinstance(node.target, cst.Name) and self._known_alias(node.target)) or self._tracked(
            node.value
        ):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING, "augmented projection binding", node
            )
            if isinstance(node.target, cst.Name):
                self.aliases.get(id(self.get_metadata(ScopeProvider, node.target)), set()).discard(
                    node.target.value
                )

    def visit_Assign(self, node: cst.Assign) -> None:
        if len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Name):
            target_names = tuple(
                name for target in node.targets for name in self._target_names(target.target)
            )
            if self._tracked(node.value) or any(self._known_alias(name) for name in target_names):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "unsupported projection binding", node
                )
                for name in target_names:
                    self.aliases.get(id(self.get_metadata(ScopeProvider, name)), set()).discard(
                        name.value
                    )
            return
        target = node.targets[0].target.value
        scope = self.aliases.get(id(self.get_metadata(ScopeProvider, node.targets[0].target)))
        if scope is None:
            return
        if self._tracked(node.value):
            scope.add(target)
            self.known_aliases.setdefault(
                id(self.get_metadata(ScopeProvider, node.targets[0].target)), set()
            ).add(target)
        else:
            scope.discard(target)

    def visit_For(self, node: cst.For) -> None:
        for target in self._target_names(node.target):
            scope = self.aliases.get(id(self.get_metadata(ScopeProvider, target)))
            if scope is not None and self._known_alias(target):
                scope.discard(target.value)
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "loop rebinds projection alias", node
                )
        if self._tracked(node.iter):
            self._record(AccessKind.DIRECT_ITERATION, None, node.iter)

    def visit_NamedExpr(self, node: cst.NamedExpr) -> None:
        if isinstance(node.target, cst.Name):
            scope = self.aliases.get(id(self.get_metadata(ScopeProvider, node.target)))
            if scope is not None and self._known_alias(node.target):
                scope.discard(node.target.value)
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING,
                    "assignment expression rebinds projection alias",
                    node,
                )

    def visit_With(self, node: cst.With) -> None:
        for item in node.items:
            if item.asname is not None and self._known_alias(item.asname.name):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_BINDING, "with target rebinds projection alias", node
                )
                self.aliases.get(
                    id(self.get_metadata(ScopeProvider, item.asname.name)), set()
                ).discard(item.asname.name.value)

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        if node.name is not None and self._known_alias(node.name.name):
            self._diagnostic(
                DiagnosticCode.UNSUPPORTED_BINDING,
                "exception target rebinds projection alias",
                node,
            )
            self.aliases.get(id(self.get_metadata(ScopeProvider, node.name.name)), set()).discard(
                node.name.name.value
            )

    def visit_Call(self, node: cst.Call) -> None:
        if any(
            argument.star in {"*", "**"} and self._tracked(argument.value) for argument in node.args
        ):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING,
                "unpacking GraphProjection is unsupported",
                node,
            )
            return
        if _name(node.func) == "getattr" and node.args and self._tracked(node.args[0].value):
            self._diagnostic(
                DiagnosticCode.REFLECTION, "getattr on GraphProjection is unsupported", node
            )
            return
        if _name(node.func) == "dict" and node.args and self._tracked(node.args[0].value):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING, "dict(GraphProjection) is unsupported", node
            )
            return
        if isinstance(node.func, cst.Attribute):
            method = node.func.attr.value
            receiver = node.func.value
            if self._tracked(receiver) and method in {
                "get",
                "keys",
                "values",
                "items",
                "setdefault",
                "pop",
            }:
                if not self._valid_method_shape(method, node.args):
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"invalid projection.{method} call shape",
                        node,
                    )
                    self.handled.add(id(receiver))
                    return
                field = None
                if method in {"get", "setdefault", "pop"}:
                    if not node.args:
                        self._diagnostic(
                            DiagnosticCode.UNSUPPORTED_CALL,
                            f"projection.{method} requires a literal key",
                            node,
                        )
                        return
                    field = _literal_key(node.args[0].value)
                    if field is None:
                        self._diagnostic(
                            DiagnosticCode.COMPUTED_KEY,
                            "projection key must be a literal string",
                            node,
                        )
                        return
                    if field not in self.fields:
                        self._diagnostic(
                            DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
                        )
                        return
                kind = AccessKind.DELETE_POP if method == "pop" else AccessKind(method)
                self._record(kind, field, node)
                self.handled.add(id(node))
                return
            if self._tracked(receiver):
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_CALL, f"projection.{method} is unsupported", node
                )
                return
            if isinstance(receiver, cst.Subscript):
                field = self._field_from_subscript(receiver)
                self.handled.add(id(receiver))
                if method not in {"append", "extend"}:
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"projection field method {method} is unsupported",
                        node,
                    )
                elif not self._valid_method_shape(method, node.args):
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CALL,
                        f"invalid projection.{method} call shape",
                        node,
                    )
                elif field is not None:
                    self._record(AccessKind.APPEND_EXTEND, field, node)
                return
        if (
            _name(node.func) == "cast"
            and len(node.args) >= 2
            and isinstance(node.args[1].value, cst.Subscript)
        ):
            field = self._field_from_subscript(node.args[1].value)
            if field is not None:
                self._record(AccessKind.UNPACK_CAST, field, node)
                self.handled.add(id(node.args[1].value))
            return
        if _name(node.func) == "GraphProjection":
            for argument in node.args:
                if argument.keyword is not None:
                    field = argument.keyword.value
                    if field in self.fields:
                        self._record(AccessKind.FIXTURE_CONSTRUCTION, field, node)
                    else:
                        self._diagnostic(
                            DiagnosticCode.UNKNOWN_FIELD,
                            f"unknown projection field: {field}",
                            argument,
                        )
                else:
                    self._diagnostic(
                        DiagnosticCode.UNSUPPORTED_CONSTRUCTION,
                        "GraphProjection construction must use literal keyword fields",
                        argument,
                    )
            return
        for argument in node.args:
            if self._tracked(argument.value):
                self._record(AccessKind.UNTYPED_ESCAPE, None, node)

    @staticmethod
    def _valid_method_shape(method: str, args: tuple[cst.Arg, ...]) -> bool:
        if any(argument.star or argument.keyword is not None for argument in args):
            return False
        arities = {
            "keys": {0},
            "values": {0},
            "items": {0},
            "get": {1},
            "pop": {1},
            "setdefault": {1, 2},
            "append": {1},
            "extend": {1},
        }
        return len(args) in arities[method]

    def visit_StarredElement(self, node: cst.StarredElement) -> None:
        if self._tracked(node.value):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING,
                "unpacking GraphProjection is unsupported",
                node,
            )

    def visit_StarredDictElement(self, node: cst.StarredDictElement) -> None:
        if self._tracked(node.value):
            self._diagnostic(
                DiagnosticCode.PROJECTION_UNPACKING,
                "unpacking GraphProjection is unsupported",
                node,
            )

    def visit_Comparison(self, node: cst.Comparison) -> None:
        if len(node.comparisons) != 1:
            operands = (node.left, *(comparison.comparator for comparison in node.comparisons))
            projection_operands = tuple(
                operand for operand in operands if self._projection_operand(operand)
            )
            if projection_operands:
                self._diagnostic(
                    DiagnosticCode.UNSUPPORTED_COMPARISON,
                    "chained projection comparison is unsupported",
                    node,
                )
                for operand in projection_operands:
                    if isinstance(operand, cst.Subscript):
                        self.handled.add(id(operand))
            return
        target = node.comparisons[0]
        if isinstance(target.operator, (cst.In, cst.NotIn)) and self._tracked(target.comparator):
            field = _literal_key(node.left)
            if field is None:
                self._diagnostic(
                    DiagnosticCode.COMPUTED_KEY,
                    "projection membership requires a literal string",
                    node,
                )
            elif field not in self.fields:
                self._diagnostic(
                    DiagnosticCode.UNKNOWN_FIELD, f"unknown projection field: {field}", node
                )
            else:
                self._record(AccessKind.MEMBERSHIP, field, node)

    def visit_Del(self, node: cst.Del) -> None:
        if isinstance(node.target, cst.Subscript):
            field = self._field_from_subscript(node.target)
            if field is not None:
                self._record(AccessKind.DELETE_POP, field, node)
                self.handled.add(id(node.target))

    def visit_Subscript(self, node: cst.Subscript) -> None:
        if id(node) in self.handled:
            return
        field = self._field_from_subscript(node)
        if field is None:
            return
        parent = self.get_metadata(ParentNodeProvider, node)
        if isinstance(parent, cst.AssignTarget) or isinstance(parent, cst.AnnAssign):
            self._record(AccessKind.DIRECT_ASSIGNMENT, field, node)
        elif isinstance(parent, cst.Subscript):
            grandparent = self.get_metadata(ParentNodeProvider, parent)
            if isinstance(grandparent, cst.AssignTarget):
                self._record(AccessKind.NESTED_ASSIGNMENT, field, parent)
        elif isinstance(parent, cst.Assign) and isinstance(
            parent.targets[0].target, (cst.Tuple, cst.List)
        ):
            self._record(AccessKind.UNPACK_CAST, field, node)
        else:
            self._record(AccessKind.LITERAL_SUBSCRIPT_READ, field, node)

    def result(self) -> SourceInventory:
        counted: dict[tuple[str, str], int] = {}
        occurrences: list[AccessOccurrence] = []
        for qualified, expression, field, kind, line, column in self.records:
            key = (qualified, expression)
            ordinal = counted.get(key, 0)
            counted[key] = ordinal + 1
            occurrences.append(
                AccessOccurrence(
                    occurrence_id=occurrence_id(
                        self.baseline_revision, self.relative_path, qualified, expression, ordinal
                    ),
                    relative_path=self.relative_path,
                    qualified_function=qualified,
                    normalized_expression=expression,
                    same_expression_ordinal=ordinal,
                    old_field_name=field,
                    kind=kind,
                    line=line,
                    column=column,
                    ordering_sensitivity_disposition=self.fields[field].ordering
                    if field
                    else "not_applicable",
                )
            )
        diagnostics = tuple(
            InventoryDiagnostic(
                relative_path=self.relative_path,
                line=line,
                column=column,
                code=code,
                message=message,
            )
            for code, message, line, column in self.diagnostics
        )
        return SourceInventory(
            relative_path=self.relative_path,
            baseline_revision=self.baseline_revision,
            occurrences=tuple(
                sorted(
                    occurrences,
                    key=lambda item: (
                        item.relative_path,
                        item.qualified_function,
                        item.line,
                        item.column,
                        item.kind,
                    ),
                )
            ),
            diagnostics=tuple(
                sorted(
                    diagnostics,
                    key=lambda item: (item.relative_path, item.line, item.column, item.code),
                )
            ),
        )


def collect_source(source: str, *, relative_path: str, baseline_revision: str) -> SourceInventory:
    """Collect supported GraphProjection accesses from one source string.

    Syntax outside the bounded supported family produces diagnostics instead of a partial claim.
    """
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as error:
        return SourceInventory(
            relative_path=relative_path,
            baseline_revision=baseline_revision,
            occurrences=(),
            diagnostics=(
                InventoryDiagnostic(
                    relative_path=relative_path,
                    line=error.raw_line,
                    column=error.raw_column,
                    code=DiagnosticCode.PARSE_ERROR,
                    message=str(error),
                ),
            ),
        )
    collector = _Collector(relative_path, baseline_revision, _manifest_fields())
    MetadataWrapper(module).visit(collector)
    return collector.result()
