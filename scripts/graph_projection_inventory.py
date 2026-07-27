"""Strict ownership-manifest loading and bounded access collection."""

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Literal

import libcst as cst
from libcst.metadata import MetadataWrapper, ParentNodeProvider, PositionProvider
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


class AccessOccurrence(BaseModel):
    """One supported access to a manifest-owned legacy projection field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrence_id: str
    relative_path: str
    qualified_function: str
    normalized_expression: str
    same_expression_ordinal: int
    old_field_name: str | None
    kind: AccessKind
    line: int
    column: int
    ordering_sensitivity_disposition: str


class InventoryDiagnostic(BaseModel):
    """A fail-closed source construct that requires manual migration first."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    line: int
    column: int
    code: str
    message: str


class SourceInventory(BaseModel):
    """Deterministic collection result for one source file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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
    METADATA_DEPENDENCIES = (PositionProvider, ParentNodeProvider)

    def __init__(
        self, relative_path: str, baseline_revision: str, fields: dict[str, FieldOwnership]
    ) -> None:
        self.relative_path = relative_path
        self.baseline_revision = baseline_revision
        self.fields = fields
        self.function_names: list[str] = []
        self.aliases: list[set[str]] = []
        self.records: list[tuple[str, str, str | None, AccessKind, int, int]] = []
        self.diagnostics: list[tuple[str, str, int, int]] = []
        self.handled: set[int] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.function_names.append(node.name.value)
        seeds = {
            parameter.name.value
            for parameter in (
                *node.params.posonly_params,
                *node.params.params,
                *node.params.kwonly_params,
            )
            if parameter.annotation is not None
            and _name(parameter.annotation.annotation) == "GraphProjection"
        }
        self.aliases.append(seeds)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.aliases.pop()
        self.function_names.pop()

    def _tracked(self, node: cst.BaseExpression) -> bool:
        return bool(self.aliases) and isinstance(node, cst.Name) and node.value in self.aliases[-1]

    def _expression(self, node: cst.CSTNode) -> str:
        return cst.Module([]).code_for_node(node).strip()

    def _record(self, kind: AccessKind, field: str | None, node: cst.CSTNode) -> None:
        qualified = ".".join(self.function_names) if self.function_names else "<module>"
        position = self.get_metadata(PositionProvider, node).start
        self.records.append(
            (qualified, self._expression(node), field, kind, position.line, position.column)
        )

    def _diagnostic(self, code: str, message: str, node: cst.CSTNode) -> None:
        position = self.get_metadata(PositionProvider, node).start
        self.diagnostics.append((code, message, position.line, position.column))

    def _field_from_subscript(self, node: cst.Subscript) -> str | None:
        if not self._tracked(node.value):
            return None
        if len(node.slice) != 1 or not isinstance(node.slice[0].slice, cst.Index):
            self._diagnostic("computed_key", "projection key must be one literal string", node)
            return None
        field = _literal_key(node.slice[0].slice.value)
        if field is None:
            self._diagnostic("computed_key", "projection key must be one literal string", node)
        elif field not in self.fields:
            self._diagnostic("unknown_field", f"unknown projection field: {field}", node)
        return field if field in self.fields else None

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if not self.aliases or not isinstance(node.target, cst.Name):
            return
        if _name(node.annotation.annotation) == "GraphProjection":
            self.aliases[-1].add(node.target.value)

    def visit_Assign(self, node: cst.Assign) -> None:
        if (
            not self.aliases
            or len(node.targets) != 1
            or not isinstance(node.targets[0].target, cst.Name)
        ):
            return
        target = node.targets[0].target.value
        if self._tracked(node.value):
            self.aliases[-1].add(target)
        else:
            self.aliases[-1].discard(target)

    def visit_Call(self, node: cst.Call) -> None:
        if _name(node.func) == "getattr" and node.args and self._tracked(node.args[0].value):
            self._diagnostic("reflection", "getattr on GraphProjection is unsupported", node)
            return
        if _name(node.func) == "dict" and node.args and self._tracked(node.args[0].value):
            self._diagnostic("projection_unpacking", "dict(GraphProjection) is unsupported", node)
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
                field = None
                if method in {"get", "setdefault", "pop"}:
                    if not node.args:
                        self._diagnostic(
                            "unsupported_call", f"projection.{method} requires a literal key", node
                        )
                        return
                    field = _literal_key(node.args[0].value)
                    if field is None:
                        self._diagnostic(
                            "computed_key", "projection key must be a literal string", node
                        )
                        return
                    if field not in self.fields:
                        self._diagnostic(
                            "unknown_field", f"unknown projection field: {field}", node
                        )
                        return
                kind = AccessKind.DELETE_POP if method == "pop" else AccessKind(method)
                self._record(kind, field, node)
                self.handled.add(id(node))
                return
            if self._tracked(receiver):
                self._diagnostic("unsupported_call", f"projection.{method} is unsupported", node)
                return
            if isinstance(receiver, cst.Subscript) and method in {"append", "extend"}:
                field = self._field_from_subscript(receiver)
                if field is not None:
                    self._record("append_extend", field, node)
                    self.handled.add(id(receiver))
                return
        if (
            _name(node.func) == "cast"
            and len(node.args) >= 2
            and isinstance(node.args[1].value, cst.Subscript)
        ):
            field = self._field_from_subscript(node.args[1].value)
            if field is not None:
                self._record("unpack_cast", field, node)
                self.handled.add(id(node.args[1].value))
            return
        if _name(node.func) == "GraphProjection":
            for argument in node.args:
                if argument.keyword is not None:
                    field = argument.keyword.value
                    if field in self.fields:
                        self._record("fixture_construction", field, node)
                    else:
                        self._diagnostic(
                            "unknown_field", f"unknown projection field: {field}", argument
                        )
            return
        for argument in node.args:
            if self._tracked(argument.value):
                self._record("untyped_escape", None, node)

    def visit_StarredElement(self, node: cst.StarredElement) -> None:
        if self._tracked(node.value):
            self._diagnostic(
                "projection_unpacking", "unpacking GraphProjection is unsupported", node
            )

    def visit_StarredDictElement(self, node: cst.StarredDictElement) -> None:
        if self._tracked(node.value):
            self._diagnostic(
                "projection_unpacking", "unpacking GraphProjection is unsupported", node
            )

    def visit_Comparison(self, node: cst.Comparison) -> None:
        if len(node.comparisons) != 1:
            return
        target = node.comparisons[0]
        if isinstance(target.operator, cst.In) and self._tracked(target.comparator):
            field = _literal_key(node.left)
            if field is None:
                self._diagnostic(
                    "computed_key", "projection membership requires a literal string", node
                )
            elif field not in self.fields:
                self._diagnostic("unknown_field", f"unknown projection field: {field}", node)
            else:
                self._record("membership", field, node)

    def visit_For(self, node: cst.For) -> None:
        if self._tracked(node.iter):
            self._record("direct_iteration", None, node.iter)

    def visit_Del(self, node: cst.Del) -> None:
        if isinstance(node.target, cst.Subscript):
            field = self._field_from_subscript(node.target)
            if field is not None:
                self._record("delete_pop", field, node)
                self.handled.add(id(node.target))

    def visit_Subscript(self, node: cst.Subscript) -> None:
        if id(node) in self.handled:
            return
        field = self._field_from_subscript(node)
        if field is None:
            return
        parent = self.get_metadata(ParentNodeProvider, node)
        if isinstance(parent, cst.AssignTarget) or isinstance(parent, cst.AnnAssign):
            self._record("direct_assignment", field, node)
        elif isinstance(parent, cst.Subscript):
            grandparent = self.get_metadata(ParentNodeProvider, parent)
            if isinstance(grandparent, cst.AssignTarget):
                self._record("nested_assignment", field, parent)
        elif isinstance(parent, cst.Assign) and isinstance(
            parent.targets[0].target, (cst.Tuple, cst.List)
        ):
            self._record("unpack_cast", field, node)
        else:
            self._record("literal_subscript_read", field, node)

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
                    code="parse_error",
                    message=str(error),
                ),
            ),
        )
    collector = _Collector(relative_path, baseline_revision, _manifest_fields())
    MetadataWrapper(module).visit(collector)
    return collector.result()
