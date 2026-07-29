"""Fail-closed source boundary checks for immutable GraphProjection storage."""

from __future__ import annotations

import ast
import os
import subprocess
import tokenize
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pydantic import BaseModel, ConfigDict

if __package__:
    from scripts.graph_projection_inventory import (
        ProjectionProvenanceFact,
        projection_provenance,
        projection_provenance_seed_tokens,
    )
else:
    from graph_projection_inventory import (
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
_MUTABLE_METHODS = frozenset(
    {
        "__delitem__",
        "__iadd__",
        "__ior__",
        "__isub__",
        "__setitem__",
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)


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
        self.provenance = {(item.line, item.column): item for item in provenance}
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
        return (node.lineno, column) in self.provenance

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (
            node.module
            and node.module.startswith("orchestrator.graph.")
            and not self.relative_path.startswith("src/orchestrator/graph/")
        ):
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
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
