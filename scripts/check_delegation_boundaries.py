#!/usr/bin/env python3
"""Enforce delegation-state write boundaries.

Delegation facts are coordination state, not general run state. This check
blocks the concrete classes of mistakes that make fan-out/super-parent
coordination unsafe:

- fan-out child update paths must not write run.oversight_state
- fan-out child update paths must not call broad RunRepository.save(...)
- code must not subscript raw .oversight_state directly
- delegation/parent coordination JSON fields must only be assigned inside
  approved coordination boundaries

To suppress a line, add:  # noqa: delegation-boundary
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path


FORBIDDEN_CHILD_PATH_FUNCTIONS = {
    "update_child_task_state",
    "start_fan_out_child_task",
    "_execute_fan_out_child",
}

RAW_OVERSIGHT_ALLOWED_SUFFIXES = {
    "src/orchestrator/workflow/delegation/coordinator.py",
    "src/orchestrator/workflow/oversight.py",
    "src/orchestrator/workflow/oversight_facts.py",
    "src/orchestrator/workflow/oversight_projection.py",
    "src/orchestrator/workflow/parent_oversight.py",
}


def load_coordination_keys() -> frozenset[str]:
    """Load workflow-owned coordination fact keys without importing workflow package APIs."""
    project_root = Path(__file__).resolve().parent.parent
    if not (project_root / "pyproject.toml").exists():
        raise RuntimeError("Could not resolve project root from script location")
    facts_path = project_root / "src/orchestrator/workflow/oversight_facts.py"
    spec = importlib.util.spec_from_file_location("_orchestrator_oversight_facts", facts_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load oversight facts from {facts_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.COORDINATION_OVERSIGHT_FACT_KEYS)


COORDINATION_KEYS = load_coordination_keys()

DELEGATION_KEY_ASSIGNMENT_ALLOWED_SUFFIXES = {
    "src/orchestrator/db/access/repositories.py",
    "src/orchestrator/workflow/oversight.py",
    "src/orchestrator/workflow/oversight_facts.py",
    "src/orchestrator/workflow/oversight_projection.py",
    "src/orchestrator/workflow/parent_oversight.py",
}


def find_project_root_from_script() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    if not (project_root / "pyproject.toml").exists():
        raise RuntimeError("Could not resolve project root from script location")
    return project_root


def rel_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def suppressed_lines(source: str) -> set[int]:
    return {
        lineno
        for lineno, line in enumerate(source.splitlines(), start=1)
        if "# noqa: delegation-boundary" in line
    }


def current_function(function_stack: list[str]) -> str | None:
    return function_stack[-1] if function_stack else None


def is_oversight_attr(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "oversight_state"


def is_run_repository_save_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "save"
        and isinstance(func.value, (ast.Attribute, ast.Name))
    )


def is_coordination_key_subscript(node: ast.Subscript) -> bool:
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value in COORDINATION_KEYS
    return False


def dict_literal_coordination_keys(node: ast.AST) -> set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    keys: set[str] = set()
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            if key.value in COORDINATION_KEYS:
                keys.add(key.value)
    return keys


def is_allowed_coordination_assignment(rel: str) -> bool:
    return (
        rel.startswith("src/orchestrator/workflow/delegation/")
        or rel in DELEGATION_KEY_ASSIGNMENT_ALLOWED_SUFFIXES
    )


def is_allowed_oversight_assignment(rel: str) -> bool:
    return (
        rel.startswith("src/orchestrator/workflow/delegation/")
        or rel in RAW_OVERSIGHT_ALLOWED_SUFFIXES
        or rel in DELEGATION_KEY_ASSIGNMENT_ALLOWED_SUFFIXES
    )


class DelegationBoundaryVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path, project_root: Path, source: str) -> None:
        self.filepath = filepath
        self.rel = rel_path(filepath, project_root)
        self.suppressed = suppressed_lines(source)
        self.function_stack: list[str] = []
        self.violations: list[str] = []

    def _violate(self, node: ast.AST, message: str) -> None:
        lineno = getattr(node, "lineno", 0)
        if lineno in self.suppressed:
            return
        self.violations.append(f"{self.filepath}:{lineno}: {message}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_assignment(node, node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_assignment(node, [node.target])
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_assignment(node, [node.target])
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if current_function(
            self.function_stack
        ) in FORBIDDEN_CHILD_PATH_FUNCTIONS and is_run_repository_save_call(node):
            self._violate(
                node,
                "fan-out child paths must not call broad RunRepository.save(); "
                "use targeted task/event writes only",
            )
        self._check_coordination_mutation_call(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if is_oversight_attr(node.value):
            self._violate(
                node,
                "do not subscript raw .oversight_state; use typed delegation/projection helpers",
            )
        self.generic_visit(node)

    def _check_assignment(self, node: ast.AST, targets: list[ast.AST]) -> None:
        for target in targets:
            if is_oversight_attr(target):
                if current_function(self.function_stack) in FORBIDDEN_CHILD_PATH_FUNCTIONS:
                    self._violate(
                        node,
                        "fan-out child paths must not write run.oversight_state; "
                        "parent aggregation owns delegated-state writes",
                    )
                elif not is_allowed_oversight_assignment(self.rel):
                    self._violate(
                        node,
                        "run.oversight_state assignments may only occur inside approved "
                        "projection/coordinator boundaries",
                    )
            if (
                isinstance(target, ast.Subscript)
                and is_coordination_key_subscript(target)
                and not is_allowed_coordination_assignment(self.rel)
            ):
                self._violate(
                    node,
                    "coordination JSON keys may only be assigned inside approved boundaries",
                )

    def _check_coordination_mutation_call(self, node: ast.Call) -> None:
        if is_allowed_coordination_assignment(self.rel):
            return
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "update":
            for arg in node.args:
                if dict_literal_coordination_keys(arg):
                    self._violate(
                        node,
                        "coordination JSON keys may only be updated inside approved boundaries",
                    )
                    return
            for keyword in node.keywords:
                if keyword.arg in COORDINATION_KEYS:
                    self._violate(
                        node,
                        "coordination JSON keys may only be updated inside approved boundaries",
                    )
                    return
        if isinstance(func, ast.Attribute) and func.attr == "append":
            value = func.value
            if isinstance(value, ast.Subscript) and is_coordination_key_subscript(value):
                self._violate(
                    node,
                    "coordination JSON lists may only be appended inside approved boundaries",
                )
                return
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "setdefault"
                and value.args
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
                and value.args[0].value in COORDINATION_KEYS
            ):
                self._violate(
                    node,
                    "coordination JSON lists may only be appended inside approved boundaries",
                )


def check_file(filepath: Path, project_root: Path) -> list[str]:
    if filepath.suffix != ".py" or not filepath.exists():
        return []
    rel = rel_path(filepath, project_root)
    if rel.startswith("tests/"):
        return []

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (OSError, SyntaxError):
        return []

    visitor = DelegationBoundaryVisitor(filepath, project_root, source)
    visitor.visit(tree)
    return visitor.violations


def main(paths: list[str]) -> int:
    project_root = find_project_root_from_script()
    if not paths:
        paths = [str(project_root / "src")]

    files: list[Path] = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        else:
            files.append(path)

    violations: list[str] = []
    for filepath in files:
        violations.extend(check_file(filepath, project_root))

    if violations:
        print("Delegation boundary violations found:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
