import ast
from pathlib import Path


TESTS_ROOT = Path(__file__).parents[1]


def _is_repository_root(expression: ast.expr, root_names: set[str]) -> bool:
    if isinstance(expression, ast.Name):
        return expression.id in root_names
    if not isinstance(expression, ast.Subscript) or not isinstance(expression.slice, ast.Constant):
        return False
    if expression.slice.value != 2:
        return False
    parents = expression.value
    if not isinstance(parents, ast.Attribute) or parents.attr != "parents":
        return False
    path_call = parents.value
    return (
        isinstance(path_call, ast.Call)
        and isinstance(path_call.func, ast.Name)
        and path_call.func.id == "Path"
        and len(path_call.args) == 1
        and isinstance(path_call.args[0], ast.Name)
        and path_call.args[0].id == "__file__"
    )


def _is_slow_marker(expression: ast.expr) -> bool:
    return (
        isinstance(expression, ast.Attribute)
        and expression.attr == "slow"
        and isinstance(expression.value, ast.Attribute)
        and expression.value.attr == "mark"
        and isinstance(expression.value.value, ast.Name)
        and expression.value.value.id == "pytest"
    )


def _repository_root_names(tree: ast.Module) -> set[str]:
    root_names = set[str]()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not _is_repository_root_expression(statement.value):
            continue
        root_names.update(target.id for target in statement.targets if isinstance(target, ast.Name))
    return root_names


def _local_repository_root_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    root_names = set[str]()
    for statement in ast.walk(function):
        if not isinstance(statement, ast.Assign) or not _is_repository_root_expression(
            statement.value
        ):
            continue
        root_names.update(target.id for target in statement.targets if isinstance(target, ast.Name))
    return root_names


def _is_repository_root_expression(expression: ast.expr) -> bool:
    return _is_repository_root(expression, set())


def _test_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name.startswith("test_")
    ]


def _inventory_calls(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "inventory_repository"
    ]


def test_full_repository_inventory_scans_are_marked_slow() -> None:
    violations: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        module_root_names = _repository_root_names(tree)
        for function in _test_functions(tree):
            root_names = module_root_names | _local_repository_root_names(function)
            has_slow_marker = any(
                _is_slow_marker(decorator) for decorator in function.decorator_list
            )
            for call in _inventory_calls(function):
                if "tracked_paths" in {keyword.arg for keyword in call.keywords}:
                    continue
                if not call.args or not _is_repository_root(call.args[0], root_names):
                    continue
                if not has_slow_marker:
                    violations.append(f"{path}:{function.lineno}:{function.name}")

    assert not violations, "full repository inventory scans must be marked slow: " + ", ".join(
        violations
    )


def test_temp_repository_inventory_scans_are_not_forced_slow() -> None:
    forced_slow: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in _test_functions(tree):
            has_slow_marker = any(
                _is_slow_marker(decorator) for decorator in function.decorator_list
            )
            for call in _inventory_calls(function):
                if (
                    call.args
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == "tmp_path"
                ):
                    if has_slow_marker:
                        forced_slow.append(f"{path}:{function.lineno}:{function.name}")

    assert not forced_slow, (
        "temp repository inventory scans must remain default-fast: " + ", ".join(forced_slow)
    )
