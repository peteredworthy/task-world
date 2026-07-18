"""Keep the graph package exports equal to their repository consumers."""

import ast
from importlib import import_module
from pathlib import Path


_ROOT = Path(__file__).parents[2]
_GRAPH_INIT = _ROOT / "src/orchestrator/graph/__init__.py"


def _public_graph_consumers() -> set[str]:
    consumers: set[str] = set()
    for source_root in (_ROOT / "src", _ROOT / "tests"):
        for path in source_root.rglob("*.py"):
            if path == _GRAPH_INIT:
                continue
            tree = ast.parse(path.read_text())
            graph_aliases = {
                alias.asname
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
                if alias.name == "orchestrator.graph" and alias.asname is not None
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "orchestrator.graph":
                    consumers.update(alias.name for alias in node.names)
                elif (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in graph_aliases
                ):
                    consumers.add(node.attr)
    return consumers


def test_graph_public_exports_equal_repository_consumers() -> None:
    graph = import_module("orchestrator.graph")

    assert _public_graph_consumers() == set(graph.__all__)
