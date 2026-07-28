import ast
from dataclasses import dataclass
from pathlib import Path

import pytest


TESTS_ROOT = Path(__file__).parents[1]
MIGRATION_MARKER = "graph_projection_migration"
SLOW_MARKER = "slow"


@dataclass(frozen=True)
class _InventoryCall:
    call: ast.Call
    function_name: str
    markers: frozenset[str]


@dataclass(frozen=True)
class _RepositoryScan:
    calls: tuple[_InventoryCall, ...]
    full_root_violations: tuple[str, ...]
    migration_marker_violations: tuple[str, ...]
    temp_root_slow_calls: tuple[str, ...]


class _InventoryCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.module_markers: set[str] = set()
        self.assignments: list[tuple[tuple[str, ...], ast.expr]] = []
        self.calls: list[_InventoryCall] = []
        self.marker_declarations: list[tuple[str, frozenset[str]]] = []
        self._function_stack: list[tuple[str | None, frozenset[str]]] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._function_stack and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            self.module_markers.update(_marker_names(node.value))
        self.assignments.append((_assignment_names(node.targets), node.value))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self._function_stack and isinstance(node.target, ast.Name):
            if node.target.id == "pytestmark" and node.value is not None:
                self.module_markers.update(_marker_names(node.value))
        if node.value is not None:
            self.assignments.append((_assignment_names((node.target,)), node.value))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent_name, parent_markers = (
            self._function_stack[-1] if self._function_stack else (None, frozenset())
        )
        if node.name.startswith("test_"):
            function_name = node.name
        elif parent_name is not None:
            function_name = parent_name
        else:
            function_name = node.name
        declared_markers = frozenset(_marker_names_from_decorators(node.decorator_list))
        self.marker_declarations.append((node.name, declared_markers))
        markers = parent_markers | declared_markers
        self._function_stack.append((function_name, markers))
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        function_name, markers = (
            self._function_stack[-1] if self._function_stack else (None, frozenset())
        )
        if function_name is not None and _is_inventory_callable(node.func):
            self.calls.append(_InventoryCall(node, function_name, markers))
        self.generic_visit(node)


def _assignment_names(targets: tuple[ast.expr, ...] | list[ast.expr]) -> tuple[str, ...]:
    return tuple(target.id for target in targets if isinstance(target, ast.Name))


def _marker_names(expression: ast.expr) -> set[str]:
    if isinstance(expression, (ast.List, ast.Set, ast.Tuple)):
        names: set[str] = set()
        for element in expression.elts:
            names.update(_marker_names(element))
        return names
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Attribute)
        and expression.value.attr == "mark"
        and isinstance(expression.value.value, ast.Name)
        and expression.value.value.id == "pytest"
    ):
        return {expression.attr}
    return set()


def _marker_names_from_decorators(decorators: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for decorator in decorators:
        names.update(_marker_names(decorator))
    return names


def _is_inventory_callable(expression: ast.expr) -> bool:
    return (isinstance(expression, ast.Name) and expression.id == "inventory_repository") or (
        isinstance(expression, ast.Attribute) and expression.attr == "inventory_repository"
    )


def _unwrap_resolve(expression: ast.expr) -> ast.expr:
    while (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "resolve"
        and not expression.args
        and not expression.keywords
    ):
        expression = expression.func.value
    return expression


def _is_repository_root(expression: ast.expr, root_names: set[str]) -> bool:
    expression = _unwrap_resolve(expression)
    if isinstance(expression, ast.Name):
        return expression.id in root_names
    if not isinstance(expression, ast.Subscript) or not isinstance(expression.slice, ast.Constant):
        return False
    if expression.slice.value != 2:
        return False
    parents = expression.value
    if not isinstance(parents, ast.Attribute) or parents.attr != "parents":
        return False
    path_call = _unwrap_resolve(parents.value)
    return (
        isinstance(path_call, ast.Call)
        and isinstance(path_call.func, ast.Name)
        and path_call.func.id == "Path"
        and len(path_call.args) == 1
        and isinstance(path_call.args[0], ast.Name)
        and path_call.args[0].id == "__file__"
        and not path_call.keywords
    )


def _repository_root_names(assignments: list[tuple[tuple[str, ...], ast.expr]]) -> set[str]:
    root_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for names, expression in assignments:
            if _is_repository_root(expression, root_names):
                before = len(root_names)
                root_names.update(names)
                changed |= len(root_names) != before
    return root_names


def _root_argument(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    return next((keyword.value for keyword in call.keywords if keyword.arg == "root"), None)


def _has_bounded_tracked_paths(call: ast.Call) -> bool:
    keyword = next((keyword for keyword in call.keywords if keyword.arg == "tracked_paths"), None)
    if keyword is None:
        return False
    return isinstance(keyword.value, (ast.List, ast.Set, ast.Tuple)) and all(
        not isinstance(element, (ast.Starred, ast.ListComp, ast.SetComp, ast.GeneratorExp))
        for element in keyword.value.elts
    )


def _scan_tree(tree: ast.Module) -> _RepositoryScan:
    visitor = _InventoryCallVisitor()
    visitor.visit(tree)
    root_names = _repository_root_names(visitor.assignments)
    calls = tuple(
        _InventoryCall(
            call.call, call.function_name, call.markers | frozenset(visitor.module_markers)
        )
        for call in visitor.calls
    )
    full_root_violations: list[str] = []
    migration_marker_violations = [
        function_name
        for function_name, markers in visitor.marker_declarations
        if MIGRATION_MARKER in markers and SLOW_MARKER not in markers
    ]
    if MIGRATION_MARKER in visitor.module_markers and SLOW_MARKER not in visitor.module_markers:
        migration_marker_violations.append("<module>")
    temp_root_slow_calls: list[str] = []
    for call in calls:
        markers = call.markers
        location = f"{call.function_name}:{call.call.lineno}"
        if MIGRATION_MARKER in markers and SLOW_MARKER not in markers:
            migration_marker_violations.append(location)
        root_argument = _root_argument(call.call)
        if root_argument is None or not _is_repository_root(root_argument, root_names):
            if isinstance(root_argument, ast.Name) and root_argument.id == "tmp_path":
                if SLOW_MARKER in markers:
                    temp_root_slow_calls.append(location)
            continue
        if _has_bounded_tracked_paths(call.call):
            continue
        if not {MIGRATION_MARKER, SLOW_MARKER} <= markers:
            full_root_violations.append(location)
    return _RepositoryScan(
        calls=calls,
        full_root_violations=tuple(full_root_violations),
        migration_marker_violations=tuple(migration_marker_violations),
        temp_root_slow_calls=tuple(temp_root_slow_calls),
    )


def _scan_repository_tests() -> _RepositoryScan:
    scans = [
        _scan_tree(ast.parse(path.read_text(), filename=str(path)))
        for path in sorted(TESTS_ROOT.rglob("test_*.py"))
    ]
    return _RepositoryScan(
        calls=tuple(call for scan in scans for call in scan.calls),
        full_root_violations=tuple(
            location for scan in scans for location in scan.full_root_violations
        ),
        migration_marker_violations=tuple(
            location for scan in scans for location in scan.migration_marker_violations
        ),
        temp_root_slow_calls=tuple(
            location for scan in scans for location in scan.temp_root_slow_calls
        ),
    )


@pytest.fixture(scope="module")
def repository_scan() -> _RepositoryScan:
    return _scan_repository_tests()


def test_full_repository_inventory_scans_are_marked_slow_and_migration_scoped(
    repository_scan: _RepositoryScan,
) -> None:
    assert not repository_scan.full_root_violations, (
        "full repository inventory scans must use both markers: "
        + ", ".join(repository_scan.full_root_violations)
    )


def test_migration_marker_always_implies_slow(repository_scan: _RepositoryScan) -> None:
    assert not repository_scan.migration_marker_violations


def test_temp_repository_inventory_scans_are_not_forced_slow(
    repository_scan: _RepositoryScan,
) -> None:
    assert not repository_scan.temp_root_slow_calls


def test_marker_guard_finds_qualified_keyword_alias_nested_and_unknown_scans() -> None:
    tree = ast.parse(
        """
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parents[2]
ALIAS = ROOT.resolve()

def test_live_scan() -> None:
    def helper() -> None:
        inventory.inventory_repository(root=ALIAS)
        inventory_repository(root=ALIAS, tracked_paths=unknown_paths)
"""
    )

    scan = _scan_tree(tree)
    assert len(scan.calls) == 2
    assert len(scan.full_root_violations) == 2
