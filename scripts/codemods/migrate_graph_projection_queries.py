"""Compile authoritative GraphProjection inventory sites into anchored operation groups.

This is deliberately a compiler front end only: it never changes consumer source.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Literal

import libcst as cst
from libcst.metadata import MetadataWrapper, ParentNodeProvider, PositionProvider
from pydantic import BaseModel, ConfigDict

from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    DiagnosticCode,
    InventorySource,
    QueryMigrationManifest,
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
    parent = _transparent_parent(node, parents)
    if isinstance(parent, cst.Return):
        return "return"
    if isinstance(parent, cst.AssignTarget):
        return "assignment_target"
    if isinstance(parent, (cst.Assign, cst.AnnAssign, cst.AugAssign)):
        return "assignment_value"
    if isinstance(parent, cst.Del):
        return "deletion"
    if isinstance(parent, cst.For):
        return "iterable"
    if isinstance(parent, cst.Comparison):
        return "comparison_membership"
    if isinstance(parent, cst.Arg):
        return "call_argument"
    if isinstance(parent, cst.Call):
        return "call_receiver"
    if isinstance(parent, (cst.DictElement, cst.DictComp)):
        return "dict_element"
    if isinstance(parent, cst.Annotation):
        return "annotation"
    return "bare_expression"


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
    return "diagnostic"


def _node_candidates(
    module: cst.Module,
) -> tuple[
    dict[tuple[str, str], list[cst.CSTNode]],
    dict[cst.CSTNode, cst.CSTNode],
    dict[cst.CSTNode, object],
    dict[int, str],
]:
    wrapper = MetadataWrapper(module)
    parents = wrapper.resolve(ParentNodeProvider)
    positions = wrapper.resolve(PositionProvider)
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
    return candidates, parents, positions, qualified


def _source_map(sources: Iterable[SourceSnapshot]) -> dict[str, SourceSnapshot]:
    snapshots = tuple(sources)
    result = {source.relative_path: source for source in snapshots}
    if len(result) != len(snapshots):
        raise AnchorRefusedError("source snapshots contain duplicate paths")
    return result


def _expected_digest_map(inventory: AccessInventory) -> dict[str, str]:
    return {item.relative_path: item.digest for item in inventory.source_digests}


def _site_by_id(skeleton: QueryMigrationManifest) -> dict[str, object]:
    return {site.site_key: site for site in skeleton.unclassified_sites}


def compile_operation_stream(
    sources: Iterable[SourceSnapshot],
    inventory: AccessInventory,
    skeleton: QueryMigrationManifest,
    *,
    verify_digest: bool = True,
) -> OperationStream:
    """Anchor every authoritative occurrence and diagnostic exactly once in source snapshots."""
    if skeleton.baseline_revision != inventory.baseline_revision:
        raise AnchorRefusedError("inventory and skeleton baseline revisions differ")
    snapshots = _source_map(sources)
    expected_digests = _expected_digest_map(inventory)
    if verify_digest and not expected_digests:
        raise AnchorRefusedError("inventory has no source digests")
    for relative_path, expected_digest in expected_digests.items():
        source = snapshots.get(relative_path)
        if source is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        if verify_digest and source_digest(source.source) != expected_digest:
            raise AnchorRefusedError(f"digest mismatch: {relative_path}")

    diagnostics_by_path: dict[str, list[tuple[object, object, int, int]]] = defaultdict(list)
    diagnostics_by_path_raw: dict[str, list[object]] = defaultdict(list)
    for diagnostic in inventory.diagnostics:
        diagnostics_by_path_raw[diagnostic.relative_path].append(diagnostic)
    for relative_path, diagnostics in diagnostics_by_path_raw.items():
        snapshot = snapshots.get(relative_path)
        if snapshot is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        skeleton_by_pattern: dict[tuple[str, DiagnosticCode, str], list[object]] = defaultdict(list)
        for site in skeleton.unclassified_sites:
            if site.relative_path == relative_path and site.diagnostic_code is not None:
                skeleton_by_pattern[
                    (site.qualified_function, site.diagnostic_code, site.normalized_source_pattern)
                ].append(site)
        diagnostic_counts: dict[tuple[str, DiagnosticCode, str], int] = defaultdict(int)
        source_lines = snapshot.source.splitlines()
        for diagnostic in diagnostics:
            pattern = " ".join(source_lines[diagnostic.line - 1].strip().split())
            key = (diagnostic.qualified_function, diagnostic.code, pattern)
            ordinal = diagnostic_counts[key]
            diagnostic_counts[key] += 1
            candidates = skeleton_by_pattern[key]
            if ordinal >= len(candidates):
                raise AnchorRefusedError("missing diagnostic skeleton identity")
            diagnostics_by_path[relative_path].append(
                (diagnostic, candidates[ordinal], ordinal, len(candidates))
            )

    sites: list[MigrationSite] = []
    occurrences_by_path: dict[str, list[object]] = defaultdict(list)
    for occurrence in inventory.occurrences:
        occurrences_by_path[occurrence.relative_path].append(occurrence)
    for relative_path in sorted({*occurrences_by_path, *diagnostics_by_path}):
        snapshot = snapshots.get(relative_path)
        if snapshot is None:
            raise AnchorRefusedError(f"missing source snapshot: {relative_path}")
        module = cst.parse_module(snapshot.source)
        candidates, parents, positions, _ = _node_candidates(module)
        for occurrence in occurrences_by_path[relative_path]:
            key = (occurrence.qualified_function, occurrence.normalized_expression)
            nodes = candidates.get(key, [])
            located_nodes = [
                node
                for node in nodes
                if positions[node].start.line == occurrence.line
                and positions[node].start.column == occurrence.column
            ]
            expected_count = sum(
                item.qualified_function == occurrence.qualified_function
                and item.normalized_expression == occurrence.normalized_expression
                for item in occurrences_by_path[relative_path]
            )
            if len(located_nodes) == 1:
                node = located_nodes[0]
            elif len(nodes) != expected_count:
                raise AnchorRefusedError(f"ambiguous occurrence anchor: {occurrence.occurrence_id}")
            elif occurrence.same_expression_ordinal >= len(nodes):
                raise AnchorRefusedError(f"missing occurrence anchor: {occurrence.occurrence_id}")
            else:
                node = nodes[occurrence.same_expression_ordinal]
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
                    ordinal=occurrence.same_expression_ordinal,
                    source_digest=source_digest(snapshot.source),
                    locator=SourceLocator(line=position.line, column=position.column),
                    anchor=CstAnchorEvidence(
                        node_type=type(node).__name__,
                        normalized_expression=occurrence.normalized_expression,
                        same_expression_ordinal=occurrence.same_expression_ordinal,
                    ),
                    parent_shape=_parent_shape(node, parents),
                    operation_shape=_operation_shape(node, occurrence.kind),
                )
            )
        for diagnostic, skeleton_site, ordinal, expected_count in diagnostics_by_path[
            relative_path
        ]:
            pattern = skeleton_site.normalized_source_pattern
            matching_lines = [
                (index + 1, line)
                for index, line in enumerate(snapshot.source.splitlines())
                if " ".join(line.strip().split()) == pattern
            ]
            located = next((item for item in matching_lines if item[0] == diagnostic.line), None)
            if located is not None:
                line, _ = located
            elif len(matching_lines) == expected_count and ordinal < len(matching_lines):
                line, _ = matching_lines[ordinal]
            else:
                raise AnchorRefusedError(f"ambiguous diagnostic anchor: {skeleton_site.site_key}")
            nodes = [
                node
                for node, position in positions.items()
                if position.start.line == line and positions[node].start.column == diagnostic.column
            ]
            node = (
                min(nodes, key=lambda item: len(cst.Module([]).code_for_node(item)))
                if nodes
                else module
            )
            sites.append(
                MigrationSite(
                    origin="diagnostic",
                    original_site_id=skeleton_site.site_key,
                    relative_path=relative_path,
                    qualified_function=diagnostic.qualified_function,
                    access_kind=None,
                    old_field_name=None,
                    diagnostic_code=diagnostic.code,
                    normalized_expression=pattern,
                    ordinal=0,
                    source_digest=source_digest(snapshot.source),
                    locator=SourceLocator(line=line, column=diagnostic.column),
                    anchor=CstAnchorEvidence(
                        node_type=type(node).__name__,
                        normalized_expression=pattern,
                        same_expression_ordinal=0,
                    ),
                    parent_shape=_parent_shape(node, parents)
                    if node is not module
                    else "bare_expression",
                    operation_shape=_operation_shape(node, None),
                )
            )
    expected_ids = {item.occurrence_id for item in inventory.occurrences} | {
        item.site_key for item in skeleton.unclassified_sites if item.diagnostic_code is not None
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
