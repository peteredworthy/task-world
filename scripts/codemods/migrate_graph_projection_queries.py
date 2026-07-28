"""Compile authoritative GraphProjection inventory sites into anchored operation groups.

This is deliberately a compiler front end only: it never changes consumer source.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Literal

import libcst as cst
from libcst.metadata import (
    MetadataWrapper,
    ParentNodeProvider,
    PositionProvider,
    QualifiedName,
    QualifiedNameProvider,
)
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    DiagnosticCode,
    InventorySource,
    ProjectionCallContext,
    QueryMigrationManifest,
    disposition_site_key,
    occurrence_id,
    source_digest,
)


SourceSnapshot = InventorySource
SiteOrigin = Literal["occurrence", "diagnostic"]


class AnchorRefusedError(ValueError):
    """Raised when an inventory identity cannot be proved against a source snapshot."""


class SourceLocator(BaseModel):
    """The CST position selected for a mechanically anchored operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    line: int
    column: int


class CstAnchorEvidence(BaseModel):
    """Recomputed proof used to select one source occurrence without source policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    node_type: str
    normalized_expression: str
    same_expression_ordinal: int
    context: ProjectionCallContext | None = None


class MigrationSite(BaseModel):
    """One source-anchored migration operation derived from inventory identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    origin: SiteOrigin
    original_site_id: str
    relative_path: str
    qualified_function: str
    access_kind: AccessKind | None
    old_field_name: str | None
    diagnostic_code: DiagnosticCode | None
    normalized_expression: str
    ordinal: int
    source_digest: str
    locator: SourceLocator
    anchor: CstAnchorEvidence
    parent_shape: str
    operation_shape: str

    @property
    def shape_key(self) -> str:
        return "|".join(
            (
                self.access_kind.value if self.access_kind is not None else "-",
                self.old_field_name or "-",
                self.diagnostic_code.value if self.diagnostic_code is not None else "-",
                self.parent_shape,
                self.operation_shape,
            )
        )


class OperationStream(BaseModel):
    """Deterministic, source-free operation stream grouped only by structural shape."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sites: tuple[MigrationSite, ...]


class PlannedOperation(BaseModel):
    """One reviewed ledger disposition joined to anchored operation IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    disposition: Literal["query_transform", "approved_core", "projection_neutral"]
    reason: str
    consumed_site_ids: tuple[str, ...]
    shape_key: str

    @property
    def consumed_site_id_set(self) -> frozenset[str]:
        return frozenset(self.consumed_site_ids)

    @classmethod
    def _validate_consumed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("consumed_site_ids must be nonempty")
        if len(value) != len(frozenset(value)):
            raise ValueError("consumed_site_ids must not repeat a site")
        return value

    @field_validator("reason")
    @classmethod
    def _reason_is_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must be nonempty")
        return value

    _consumed_is_nonempty = field_validator("consumed_site_ids")(_validate_consumed)


class DispositionPlan(BaseModel):
    """Frozen exact-once compilation result for reviewed migration dispositions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operations: tuple[PlannedOperation, ...]
    deferred_site_ids: tuple[str, ...]
    pending_site_ids: tuple[str, ...]
    disposition_counts: tuple[tuple[str, int], ...]
    shape_group_counts: tuple[tuple[str, int], ...]
    rule_family_counts: tuple[tuple[str, int], ...] = ()
    symbol_origin_counts: tuple[tuple[str, int], ...] = ()

    @property
    def consumed_site_ids(self) -> frozenset[str]:
        return frozenset(
            site_id for operation in self.operations for site_id in operation.consumed_site_ids
        )

    @model_validator(mode="after")
    def _validate_total_partition(self) -> "DispositionPlan":
        consumed = [
            site_id for operation in self.operations for site_id in operation.consumed_site_ids
        ]
        if len(consumed) != len(frozenset(consumed)):
            raise ValueError("planned operation consumed-site sets overlap")
        deferred = set(self.deferred_site_ids)
        pending = set(self.pending_site_ids)
        if len(deferred) != len(self.deferred_site_ids) or len(pending) != len(
            self.pending_site_ids
        ):
            raise ValueError("deferred and pending site IDs must be unique")
        if deferred & pending or deferred & set(consumed) or pending & set(consumed):
            raise ValueError("plan partitions overlap")
        if not self.disposition_counts or not self.shape_group_counts:
            raise ValueError("derived plan counts must be nonempty")
        if self.disposition_counts != tuple(
            sorted(Counter(item.disposition for item in self.operations).items())
        ):
            raise ValueError("disposition counts do not match operations")
        if self.shape_group_counts != tuple(
            sorted(Counter(item.shape_key for item in self.operations).items())
        ):
            raise ValueError("shape counts do not match operations")
        return self


_GRAPH_ORIGIN = "orchestrator.graph"
_PROJECTION_FACTORIES = frozenset(
    {
        "orchestrator.graph.initial_projection",
        "orchestrator.graph.build_projection",
        "orchestrator.graph.reduce_event",
        "orchestrator.graph.projection_from_checkpoint",
        "orchestrator.graph_runtime.controller.rebuild_projection",
        "orchestrator.graph.projections.reduce_event",
    }
)
_PUBLIC_PROJECTION_ARGUMENT_POSITIONS = {
    "orchestrator.graph.callbacks.validate_callback": frozenset({1}),
    "orchestrator.graph.patch_validator.validate_patch": frozenset({3}),
    "orchestrator.graph.projections.final_invariant_blockers_for_events": frozenset({1}),
}


def _is_projection_factory(origin: str | None) -> bool:
    return origin in _PROJECTION_FACTORIES


def _resolved_qualified_names(
    node: cst.CSTNode, qualified_names: dict[cst.CSTNode, object]
) -> frozenset[QualifiedName]:
    value = qualified_names.get(node, frozenset())
    resolved = value() if callable(value) else value
    if not isinstance(resolved, set):
        return frozenset()
    return frozenset(item for item in resolved if isinstance(item, QualifiedName))


def _one_qualified_name(
    node: cst.CSTNode, qualified_names: dict[cst.CSTNode, object]
) -> QualifiedName | None:
    names = _resolved_qualified_names(node, qualified_names)
    return next(iter(names)) if len(names) == 1 else None


def _reanchor_context(
    node: cst.CSTNode,
    stored: ProjectionCallContext | None,
    qualified_names: dict[cst.CSTNode, object],
) -> ProjectionCallContext | None:
    """Revalidate stored collector context without discovering projection values."""
    if stored is None:
        return None
    if isinstance(node, cst.Param):
        annotation = node.annotation.annotation if node.annotation is not None else None
        name = _one_qualified_name(annotation, qualified_names) if annotation is not None else None
        origin = name.name if name is not None and name.source.name == "IMPORT" else None
        if stored.receiver_type_origin != origin:
            raise AnchorRefusedError("inventory type context does not match CST anchor")
        return stored
    direct_call = (
        node
        if isinstance(node, cst.Call)
        else node.value
        if isinstance(node, (cst.Assign, cst.AnnAssign, cst.Return))
        and isinstance(node.value, cst.Call)
        else None
    )
    calls = [direct_call] if direct_call is not None else []
    if isinstance(node, cst.Comparison):

        class CallVisitor(cst.CSTVisitor):
            def visit_Call(self, call: cst.Call) -> None:
                calls.append(call)

        node.visit(CallVisitor())
    if not calls:
        if stored.callee_origin is not None or stored.projection_role != "receiver":
            raise AnchorRefusedError("inventory call context does not match CST anchor")
        return stored
    matching_calls = []
    for call in calls:
        name = _one_qualified_name(call.func, qualified_names)
        origin = name.name if name is not None and name.source.name == "IMPORT" else None
        if origin == stored.callee_origin:
            matching_calls.append(call)
    if len(matching_calls) != 1:
        raise AnchorRefusedError(
            "inventory callee context does not match CST anchor: "
            f"{stored.callee_origin!r} at {cst.Module([]).code_for_node(node).strip()!r}"
        )
    call = matching_calls[0]
    if stored.projection_role == "receiver":
        return stored
    elif stored.projection_role == "positional":
        positional_arguments = [
            argument for argument in call.args if argument.keyword is None and not argument.star
        ]
        if (
            stored.positional_index is None
            or stored.positional_index >= len(positional_arguments)
            or any(
                argument.star == "*"
                for argument in call.args[
                    : call.args.index(positional_arguments[stored.positional_index])
                ]
            )
        ):
            raise AnchorRefusedError("inventory positional context does not match CST anchor")
    elif stored.projection_role == "keyword":
        if not any(
            argument.keyword is not None and argument.keyword.value == stored.keyword_name
            for argument in call.args
        ):
            raise AnchorRefusedError("inventory keyword context does not match CST anchor")
    elif stored.projection_role == "ambiguous" and not any(
        argument.star == "*" for argument in call.args
    ):
        raise AnchorRefusedError("inventory ambiguous context does not match CST anchor")
    return stored


def plan_reviewed_dispositions(
    stream: OperationStream, manifest: QueryMigrationManifest
) -> DispositionPlan:
    """Compile reviewed ledger records to exact-once in-memory operations.

    This boundary deliberately uses ledger identities only to reconcile them to
    the already-anchored stream; it selects no transformation policy.
    """
    stream_by_id = {site.original_site_id: site for site in stream.sites}
    if len(stream_by_id) != len(stream.sites):
        raise AnchorRefusedError("duplicate anchored operation-stream site identity")
    reviewed_ids = {item.site_key for item in manifest.dispositions}
    missing = reviewed_ids - stream_by_id.keys()
    if missing:
        raise AnchorRefusedError(f"reviewed disposition has no anchored site: {sorted(missing)!r}")
    operations: list[PlannedOperation] = []
    for disposition in sorted(manifest.dispositions, key=lambda item: item.site_key):
        site = stream_by_id[disposition.site_key]
        if disposition.disposition == "rejected":
            raise AnchorRefusedError(
                f"reviewed disposition is not compilable: {disposition.disposition}"
            )
        operations.append(
            PlannedOperation(
                disposition=disposition.disposition,
                reason=disposition.reason,
                consumed_site_ids=(site.original_site_id,),
                shape_key=site.shape_key,
            )
        )
    deferred = tuple(sorted(site.site_key for site in manifest.unclassified_sites))
    pending = tuple(sorted(set(stream_by_id) - reviewed_ids - set(deferred)))
    if (
        len(deferred) != 349
        or any(site.domain != "test_fixture" for site in manifest.unclassified_sites)
        or any(site_id not in stream_by_id for site_id in deferred)
        or reviewed_ids & set(deferred)
        or len(pending) != 100
        or set(stream_by_id) != reviewed_ids | set(deferred) | set(pending)
    ):
        raise AnchorRefusedError("deferred fixture ledger does not match anchored stream")
    disposition_counts = tuple(sorted(Counter(item.disposition for item in operations).items()))
    shape_group_counts = tuple(sorted(Counter(item.shape_key for item in operations).items()))
    if disposition_counts != (
        ("approved_core", 80),
        ("projection_neutral", 73),
        ("query_transform", 201),
    ):
        raise AnchorRefusedError("reviewed disposition checkpoint counts do not match")
    return DispositionPlan(
        operations=tuple(operations),
        deferred_site_ids=deferred,
        pending_site_ids=pending,
        disposition_counts=disposition_counts,
        shape_group_counts=shape_group_counts,
    )


def _neutral_rule(site: MigrationSite) -> tuple[str, str] | None:
    """Return one finite structural rule and its proven origin, or fail closed."""
    anchor = site.anchor
    context = anchor.context
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
        and context is not None
        and context.receiver_type_origin
        in {
            "orchestrator.graph.GraphProjection",
            "orchestrator.graph._commands.GraphProjection",
            "orchestrator.graph.projections.GraphProjection",
        }
    ):
        return "typed_projection_binding", context.receiver_type_origin
    if (
        site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
        and context is not None
        and _is_projection_factory(context.callee_origin)
    ):
        return "typed_projector_binding", context.callee_origin
    if (
        context is not None
        and context.receiver_type_origin is not None
        and context.physical_old_field_name is not None
        and context.physical_access_kind is not None
    ):
        return "physical_projection_access", context.physical_access_kind.value
    if (
        context is not None
        and context.callee_origin is not None
        and context.callee_origin.startswith(f"{_GRAPH_ORIGIN}.")
        and (
            context.projection_role == "receiver"
            or context.keyword_name == "projection"
            or context.positional_index == 0
            or context.positional_index
            in _PUBLIC_PROJECTION_ARGUMENT_POSITIONS.get(context.callee_origin, frozenset())
        )
    ):
        return "public_graph_call", context.callee_origin
    if context is not None and _is_projection_factory(context.callee_origin):
        return "projector_fixture_flow", context.callee_origin
    return None


def plan_structural_dispositions(
    stream: OperationStream, manifest: QueryMigrationManifest
) -> DispositionPlan:
    """Close unchanged dispositions through imported-origin and CST argument evidence."""
    initial = plan_reviewed_dispositions(stream, manifest)
    by_id = {site.original_site_id: site for site in stream.sites}
    operations: list[PlannedOperation] = []
    rule_records: list[tuple[str, str]] = []

    for operation in initial.operations:
        site_id = operation.consumed_site_ids[0]
        site = by_id[site_id]
        if operation.disposition == "approved_core":
            if site.relative_path not in {
                "src/orchestrator/graph/projection_models.py",
                "src/orchestrator/graph/projection_collections.py",
                "src/orchestrator/graph/projection_queries.py",
                "src/orchestrator/graph/projection_codec.py",
                "src/orchestrator/graph/projections.py",
            } or (
                site.access_kind is None
                and site.anchor.context is not None
                and site.anchor.context.callee_origin is not None
            ):
                raise AnchorRefusedError(
                    "approved core is not an allowlisted physical storage operation"
                )
            operations.append(operation)
            continue
        if operation.disposition != "projection_neutral":
            operations.append(operation)
            continue
        rule = _neutral_rule(site)
        if rule is None:
            raise AnchorRefusedError(
                f"reviewed projection-neutral site has no structural rule: {site_id}"
            )
        family, origin = rule
        operations.append(operation.model_copy(update={"reason": f"structural:{family}:{origin}"}))
        rule_records.append(rule)

    for site_id in initial.pending_site_ids:
        site = by_id[site_id]
        rule = _neutral_rule(site)
        if rule is None:
            raise AnchorRefusedError(f"pending site has no structural neutral rule: {site_id}")
        family, origin = rule
        operations.append(
            PlannedOperation(
                disposition="projection_neutral",
                reason=f"structural:{family}:{origin}",
                consumed_site_ids=(site_id,),
                shape_key=site.shape_key,
            )
        )
        rule_records.append(rule)

    operations.sort(key=lambda operation: operation.consumed_site_ids)
    disposition_counts = tuple(sorted(Counter(item.disposition for item in operations).items()))
    shape_group_counts = tuple(sorted(Counter(item.shape_key for item in operations).items()))
    rule_family_counts = tuple(sorted(Counter(family for family, _ in rule_records).items()))
    symbol_origin_counts = tuple(sorted(Counter(origin for _, origin in rule_records).items()))
    if (
        disposition_counts
        != (("approved_core", 80), ("projection_neutral", 173), ("query_transform", 201))
        or len(initial.deferred_site_ids) != 349
        or len(operations) + len(initial.deferred_site_ids) != 803
        or len(rule_records) != 173
    ):
        raise AnchorRefusedError(
            "structural disposition partition does not match the approved counts"
        )
    return DispositionPlan(
        operations=tuple(operations),
        deferred_site_ids=initial.deferred_site_ids,
        pending_site_ids=(),
        disposition_counts=disposition_counts,
        shape_group_counts=shape_group_counts,
        rule_family_counts=rule_family_counts,
        symbol_origin_counts=symbol_origin_counts,
    )


def _refuse_unknown_shape(node: cst.CSTNode) -> AnchorRefusedError:
    return AnchorRefusedError(f"unknown structural shape: {type(node).__name__}")


def _normalized_node(node: cst.CSTNode) -> str | None:
    try:
        return ast.unparse(ast.parse(cst.Module([]).code_for_node(node)))
    except SyntaxError:
        return None


def _qualified_functions(module: cst.Module) -> dict[int, str]:
    names: dict[int, str] = {}

    class Visitor(cst.CSTVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def on_visit(self, node: cst.CSTNode) -> bool:
            names[id(node)] = ".".join(self.stack) or "<module>"
            if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
                self.stack.append(node.name.value)
            return True

        def on_leave(self, original_node: cst.CSTNode) -> None:
            if isinstance(original_node, (cst.FunctionDef, cst.ClassDef)):
                self.stack.pop()

    module.visit(Visitor())
    return names


def _transparent_parent(node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]) -> cst.CSTNode:
    parent = parents[node]
    while isinstance(parent, (cst.Expr, cst.SimpleStatementLine, cst.ParenthesizedWhitespace)):
        parent = parents[parent]
    return parent


def _parent_shape(node: cst.CSTNode, parents: dict[cst.CSTNode, cst.CSTNode]) -> str:
    if isinstance(node, cst.Del):
        return "deletion"
    parent = parents[node]
    if isinstance(parent, (cst.Expr, cst.SimpleStatementLine)):
        return "bare_expression"
    parent = _transparent_parent(node, parents)
    if isinstance(parent, cst.Return):
        return "return"
    if isinstance(parent, cst.AssignTarget):
        return "assignment_target"
    if isinstance(parent, (cst.Assign, cst.AnnAssign, cst.AugAssign)):
        return "assignment_value"
    if isinstance(parent, cst.Del):
        return "deletion"
    if isinstance(parent, (cst.For, cst.CompFor)):
        return "iterable"
    if isinstance(parent, (cst.If, cst.While, cst.Assert)):
        return "condition"
    if isinstance(parent, (cst.Comparison, cst.ComparisonTarget)):
        return "comparison_membership"
    if isinstance(parent, cst.Arg):
        return "call_argument"
    if isinstance(parent, cst.Call):
        return "call_receiver"
    if isinstance(parent, cst.Attribute):
        return "attribute_receiver"
    if isinstance(parent, cst.Subscript):
        return "nested_receiver"
    if isinstance(parent, (cst.DictElement, cst.DictComp)):
        return "dict_element"
    if isinstance(parent, cst.Annotation):
        return "annotation"
    if isinstance(parent, cst.Parameters):
        return "typed_parameter"
    if isinstance(parent, (cst.BooleanOperation, cst.IfExp, cst.UnaryOperation)):
        return "boolean_expression"
    if isinstance(parent, (cst.Tuple, cst.List, cst.Set, cst.Element)):
        return "collection_element"
    if isinstance(parent, (cst.Await, cst.Yield)):
        return "yield_await"
    raise _refuse_unknown_shape(parent)


def _operation_shape(node: cst.CSTNode, access_kind: AccessKind | None) -> str:
    if access_kind is not None:
        if access_kind is AccessKind.MEMBERSHIP:
            return "membership"
        if access_kind in {AccessKind.ITEMS, AccessKind.VALUES, AccessKind.KEYS}:
            return f"{access_kind.value}_iteration"
        if access_kind in {AccessKind.DIRECT_ASSIGNMENT, AccessKind.NESTED_ASSIGNMENT}:
            return "assignment"
        if access_kind is AccessKind.APPEND_EXTEND:
            return "append_extend"
        if access_kind is AccessKind.DELETE_POP:
            return "deletion"
        if access_kind is AccessKind.FIXTURE_CONSTRUCTION:
            return "fixture_construction"
        if access_kind is AccessKind.UNTYPED_ESCAPE:
            return "typed_pass_through"
        if access_kind is AccessKind.GET:
            return "map_get"
        if access_kind is AccessKind.LITERAL_SUBSCRIPT_READ:
            return "subscript_read"
        return access_kind.value
    if isinstance(node, cst.Call):
        return "call"
    if isinstance(node, cst.Comparison):
        return "comparison"
    raise _refuse_unknown_shape(node)


def _diagnostic_operation_shape(node: cst.CSTNode, code: DiagnosticCode) -> str:
    if isinstance(node, cst.Call):
        if isinstance(node.func, cst.Attribute):
            if node.func.attr.value == "get" and isinstance(node.func.value, cst.Subscript):
                return "nested_get"
            if node.func.attr.value in {
                "items",
                "values",
                "keys",
                "update",
                "append",
                "extend",
                "pop",
                "setdefault",
            }:
                return node.func.attr.value
        return "call"
    if isinstance(node, cst.Comparison):
        return "comparison"
    if isinstance(node, cst.Del):
        return "deletion"
    if isinstance(node, cst.Subscript):
        return "subscript"
    if isinstance(
        node, (cst.Param, cst.Name, cst.AnnAssign, cst.Assign, cst.FunctionDef, cst.Return)
    ):
        return "typed_pass_through"
    raise AnchorRefusedError(f"unknown diagnostic operation: {code.value}:{type(node).__name__}")


def _node_candidates(
    module: cst.Module,
) -> tuple[
    dict[tuple[str, str], list[cst.CSTNode]],
    dict[cst.CSTNode, cst.CSTNode],
    dict[cst.CSTNode, object],
    dict[int, str],
    dict[cst.CSTNode, object],
]:
    wrapper = MetadataWrapper(module)
    metadata = wrapper.resolve_many((ParentNodeProvider, PositionProvider))
    parents = metadata[ParentNodeProvider]
    positions = metadata[PositionProvider]
    qualified = _qualified_functions(wrapper.module)
    candidates: dict[tuple[str, str], list[cst.CSTNode]] = defaultdict(list)

    class Visitor(cst.CSTVisitor):
        def on_visit(self, node: cst.CSTNode) -> bool:
            if not isinstance(node, (cst.BaseExpression, cst.Del)):
                return True
            expression = _normalized_node(node)
            if expression is not None:
                candidates[(qualified[id(node)], expression)].append(node)
            return True

    wrapper.visit(Visitor())
    for nodes in candidates.values():
        nodes.sort(key=lambda node: (positions[node].start.line, positions[node].start.column))
    return (
        candidates,
        parents,
        positions,
        qualified,
        wrapper.resolve(QualifiedNameProvider),
    )


def _source_map(sources: Iterable[SourceSnapshot]) -> dict[str, SourceSnapshot]:
    snapshots = tuple(sources)
    result = {source.relative_path: source for source in snapshots}
    if len(result) != len(snapshots):
        raise AnchorRefusedError("source snapshots contain duplicate paths")
    return result


def _expected_digest_map(inventory: AccessInventory) -> dict[str, str]:
    return {item.relative_path: item.digest for item in inventory.source_digests}


def _skeleton_sites(skeleton: QueryMigrationManifest) -> dict[str, object]:
    return {site.site_key: site for site in (*skeleton.dispositions, *skeleton.unclassified_sites)}


def _matches_access_kind(
    node: cst.CSTNode,
    kind: AccessKind,
    parents: dict[cst.CSTNode, cst.CSTNode],
) -> bool:
    parent = parents[node]
    if kind is AccessKind.DELETE_POP:
        return isinstance(node, (cst.Del, cst.Call))
    if kind in {AccessKind.DIRECT_ASSIGNMENT, AccessKind.NESTED_ASSIGNMENT}:
        return isinstance(parent, cst.AssignTarget) or (
            isinstance(parent, cst.AnnAssign) and parent.target is node
        )
    if kind is AccessKind.MEMBERSHIP:
        return isinstance(node, cst.Comparison)
    if kind is AccessKind.DIRECT_ITERATION:
        return isinstance(parent, (cst.For, cst.CompFor))
    if kind in {
        AccessKind.GET,
        AccessKind.ITEMS,
        AccessKind.VALUES,
        AccessKind.KEYS,
        AccessKind.SETDEFAULT,
    }:
        return isinstance(node, cst.Call)
    if kind in {AccessKind.APPEND_EXTEND, AccessKind.FIXTURE_CONSTRUCTION, AccessKind.UNPACK_CAST}:
        return isinstance(node, cst.Call)
    return isinstance(node, cst.BaseExpression)


def _scope_lines(
    module: cst.Module,
    positions: dict[cst.CSTNode, object],
    qualified: dict[int, str],
) -> dict[int, str]:
    ranges = [
        (
            position.start.line,
            position.end.line,
            ".".join(part for part in (qualified[id(node)], node.name.value) if part != "<module>")
            or node.name.value,
        )
        for node, position in positions.items()
        if isinstance(node, cst.FunctionDef)
    ]
    return {
        line: max(
            (item for item in ranges if item[0] <= line <= item[1]),
            key=lambda item: item[0],
            default=(0, 0, "<module>"),
        )[2]
        for line in range(1, len(module.code.splitlines()) + 1)
    }


def _diagnostic_node(
    nodes: list[cst.CSTNode], source_node_type: str, normalized_cst_expression: str
) -> cst.CSTNode:
    matching = [
        node
        for node in nodes
        if type(node).__name__ == source_node_type
        and (_normalized_node(node) or cst.Module([]).code_for_node(node).strip())
        == normalized_cst_expression
    ]
    if len(matching) != 1:
        raise AnchorRefusedError("ambiguous diagnostic CST anchor")
    return matching[0]


def _anchor_evidence(
    node: cst.CSTNode,
    *,
    normalized_expression: str,
    ordinal: int,
    stored_context: ProjectionCallContext | None,
    qualified_names: dict[cst.CSTNode, object],
) -> CstAnchorEvidence:
    return CstAnchorEvidence(
        node_type=type(node).__name__,
        normalized_expression=normalized_expression,
        same_expression_ordinal=ordinal,
        context=_reanchor_context(node, stored_context, qualified_names),
    )


def compile_operation_stream(
    sources: Iterable[SourceSnapshot],
    inventory: AccessInventory,
    skeleton: QueryMigrationManifest,
) -> OperationStream:
    """Anchor every authoritative occurrence and diagnostic exactly once in source snapshots."""
    if skeleton.baseline_revision != inventory.baseline_revision:
        raise AnchorRefusedError("inventory and skeleton baseline revisions differ")
    snapshots = _source_map(sources)
    expected_digests = _expected_digest_map(inventory)
    if not expected_digests:
        raise AnchorRefusedError("inventory has no source digests")
    for relative_path, expected_digest in expected_digests.items():
        source = snapshots.get(relative_path)
        if source is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        if source_digest(source.source) != expected_digest:
            raise AnchorRefusedError(f"digest mismatch: {relative_path}")

    skeleton_by_id = _skeleton_sites(skeleton)
    diagnostics_by_path: dict[str, list[object]] = defaultdict(list)
    diagnostics_by_path_raw: dict[str, list[object]] = defaultdict(list)
    for diagnostic in inventory.diagnostics:
        diagnostics_by_path_raw[diagnostic.relative_path].append(diagnostic)
    for relative_path, diagnostics in diagnostics_by_path_raw.items():
        diagnostics_by_path[relative_path].extend(diagnostics)

    sites: list[MigrationSite] = []
    occurrences_by_path: dict[str, list[object]] = defaultdict(list)
    for occurrence in inventory.occurrences:
        occurrences_by_path[occurrence.relative_path].append(occurrence)
    for relative_path in sorted({*occurrences_by_path, *diagnostics_by_path}):
        snapshot = snapshots.get(relative_path)
        if snapshot is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        module = cst.parse_module(snapshot.source)
        candidates, parents, positions, qualified, qualified_names = _node_candidates(module)
        scope_lines = _scope_lines(module, positions, qualified)
        for occurrence in occurrences_by_path[relative_path]:
            key = (occurrence.qualified_function, occurrence.normalized_expression)
            matching_occurrences = tuple(
                item
                for item in occurrences_by_path[relative_path]
                if item.qualified_function == occurrence.qualified_function
                and item.normalized_expression == occurrence.normalized_expression
            )
            nodes = [
                node
                for node in candidates.get(key, [])
                if any(
                    _matches_access_kind(node, item.kind, parents) for item in matching_occurrences
                )
            ]
            expected_count = len(matching_occurrences)
            if len(nodes) != expected_count:
                raise AnchorRefusedError(f"ambiguous occurrence anchor: {occurrence.occurrence_id}")
            identities = {
                occurrence_id(
                    inventory.baseline_revision,
                    relative_path,
                    occurrence.qualified_function,
                    occurrence.normalized_expression,
                    ordinal,
                ): node
                for ordinal, node in enumerate(nodes)
            }
            if occurrence.occurrence_id not in identities:
                raise AnchorRefusedError(f"identity mismatch: {occurrence.occurrence_id}")
            node = identities[occurrence.occurrence_id]
            skeleton_site = skeleton_by_id.get(occurrence.occurrence_id)
            if skeleton_site is None or skeleton_site.site_key != occurrence.occurrence_id:
                raise AnchorRefusedError(
                    f"missing occurrence skeleton identity: {occurrence.occurrence_id}"
                )
            position = positions[node].start
            if _normalized_node(node) != occurrence.normalized_expression:
                raise AnchorRefusedError(f"identity mismatch: {occurrence.occurrence_id}")
            sites.append(
                MigrationSite(
                    origin="occurrence",
                    original_site_id=occurrence.occurrence_id,
                    relative_path=relative_path,
                    qualified_function=occurrence.qualified_function,
                    access_kind=occurrence.kind,
                    old_field_name=occurrence.old_field_name,
                    diagnostic_code=None,
                    normalized_expression=occurrence.normalized_expression,
                    ordinal=next(
                        ordinal for ordinal, candidate in enumerate(nodes) if candidate is node
                    ),
                    source_digest=source_digest(snapshot.source),
                    locator=SourceLocator(line=position.line, column=position.column),
                    anchor=_anchor_evidence(
                        node,
                        normalized_expression=occurrence.normalized_expression,
                        ordinal=next(
                            ordinal for ordinal, candidate in enumerate(nodes) if candidate is node
                        ),
                        stored_context=occurrence.context,
                        qualified_names=qualified_names,
                    ),
                    parent_shape=_parent_shape(node, parents),
                    operation_shape=_operation_shape(node, occurrence.kind),
                )
            )
        for diagnostic in diagnostics_by_path[relative_path]:
            pattern = diagnostic.normalized_source_pattern
            matching_lines = {
                index + 1
                for index, line in enumerate(snapshot.source.splitlines())
                if " ".join(line.strip().split()) == pattern
                and scope_lines.get(index + 1) == diagnostic.qualified_function
            }
            group = [
                item
                for item in diagnostics_by_path[relative_path]
                if item.qualified_function == diagnostic.qualified_function
                and item.code is diagnostic.code
                and item.normalized_source_pattern == pattern
            ]
            signatures = {(item.source_node_type, item.normalized_cst_expression) for item in group}
            nodes_by_signature = {
                signature: [
                    node
                    for node, position in positions.items()
                    if position.start.line in matching_lines
                    and type(node).__name__ == signature[0]
                    and (_normalized_node(node) or cst.Module([]).code_for_node(node).strip())
                    == signature[1]
                ]
                for signature in signatures
            }
            for signature, nodes_for_signature in nodes_by_signature.items():
                expected_count = sum(
                    item.source_node_type == signature[0]
                    and item.normalized_cst_expression == signature[1]
                    for item in group
                )
                if len(nodes_for_signature) != expected_count:
                    raise AnchorRefusedError("ambiguous diagnostic anchor")
            signature = (diagnostic.source_node_type, diagnostic.normalized_cst_expression)
            all_nodes = sorted(
                (candidate for values in nodes_by_signature.values() for candidate in values),
                key=lambda candidate: (
                    positions[candidate].start.line,
                    positions[candidate].start.column,
                    type(candidate).__name__,
                ),
            )
            if diagnostic.same_pattern_ordinal >= len(all_nodes):
                raise AnchorRefusedError("missing diagnostic CST anchor")
            ordinal = diagnostic.same_pattern_ordinal
            node = all_nodes[ordinal]
            if (
                type(node).__name__ != signature[0]
                or (_normalized_node(node) or cst.Module([]).code_for_node(node).strip())
                != signature[1]
            ):
                raise AnchorRefusedError("diagnostic identity mismatch")
            diagnostic_key = disposition_site_key(
                baseline_revision=inventory.baseline_revision,
                relative_path=relative_path,
                qualified_function=diagnostic.qualified_function,
                normalized_source_pattern=pattern,
                diagnostic_code=diagnostic.code,
                same_pattern_ordinal=ordinal,
            )
            skeleton_site = skeleton_by_id.get(diagnostic_key)
            if skeleton_site is None or skeleton_site.site_key != diagnostic_key:
                raise AnchorRefusedError("missing diagnostic skeleton identity")
            line = positions[node].start.line
            nodes = [node]
            if len(nodes) != 1:
                raise AnchorRefusedError("ambiguous diagnostic CST anchor")
            node = _diagnostic_node(
                nodes, diagnostic.source_node_type, diagnostic.normalized_cst_expression
            )
            sites.append(
                MigrationSite(
                    origin="diagnostic",
                    original_site_id=diagnostic_key,
                    relative_path=relative_path,
                    qualified_function=diagnostic.qualified_function,
                    access_kind=None,
                    old_field_name=None,
                    diagnostic_code=diagnostic.code,
                    normalized_expression=pattern,
                    ordinal=ordinal,
                    source_digest=source_digest(snapshot.source),
                    locator=SourceLocator(line=line, column=diagnostic.column),
                    anchor=_anchor_evidence(
                        node,
                        normalized_expression=(
                            _normalized_node(node) or cst.Module([]).code_for_node(node).strip()
                        ),
                        ordinal=ordinal,
                        stored_context=diagnostic.context,
                        qualified_names=qualified_names,
                    ),
                    parent_shape=_parent_shape(node, parents),
                    operation_shape=_diagnostic_operation_shape(node, diagnostic.code),
                )
            )
    expected_ids = {item.occurrence_id for item in inventory.occurrences} | {
        item.site_key for item in skeleton_by_id.values() if item.diagnostic_code is not None
    }
    actual_ids = {site.original_site_id for site in sites}
    if actual_ids != expected_ids or len(sites) != len(expected_ids):
        raise AnchorRefusedError(
            "operation stream does not adapt every inventory site exactly once"
        )
    return OperationStream(
        sites=tuple(
            sorted(
                sites,
                key=lambda site: (
                    site.relative_path,
                    site.locator.line,
                    site.locator.column,
                    site.original_site_id,
                ),
            )
        )
    )


def shape_summary(stream: OperationStream) -> dict[str, int]:
    """Return deterministic structural grouping counts without site or source policy."""
    return dict(sorted(Counter(site.shape_key for site in stream.sites).items()))
