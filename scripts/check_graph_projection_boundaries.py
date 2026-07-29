"""Fail-closed source boundary checks for immutable GraphProjection storage."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict


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
_MUTABLE_METHODS = frozenset({"append", "clear", "extend", "pop", "setdefault", "update"})


class BoundaryViolation(BaseModel):
    """One deterministic source location that crosses the storage boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    line: int
    column: int
    code: str
    message: str


class _BoundaryVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, projection_names: frozenset[str]) -> None:
        self.relative_path = relative_path
        self.projection_names = projection_names
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

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            self.relative_path not in ALLOWED_STORAGE_READERS
            and isinstance(node.value, ast.Name)
            and node.value.id in self.projection_names
        ):
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
            isinstance(node.value, ast.Name)
            and node.value.id in self.projection_names
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
            and any(
                isinstance(child, ast.Name) and child.id in self.projection_names
                for child in ast.walk(node.func.value)
            )
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
                ("git", "-C", str(root), "ls-files", "--", "src/**/*.py"),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
    violations: list[BoundaryViolation] = []
    for path in sorted(selected):
        relative_path = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(), filename=relative_path)
        except SyntaxError as error:
            raise ValueError(
                f"cannot check malformed Python source {relative_path}: {error}"
            ) from error
        projection_names = frozenset(
            argument.arg
            for argument in ast.walk(tree)
            if isinstance(argument, ast.arg)
            and argument.annotation is not None
            and ast.unparse(argument.annotation).split(".")[-1] == "GraphProjection"
        )
        visitor = _BoundaryVisitor(relative_path, projection_names)
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
