"""Keep the graph package's explicit public surface complete and exact."""

import ast
from importlib import import_module
from pathlib import Path

from orchestrator.graph import (
    ProjectionCheckpointCodecError,
    ProjectionIntegrityDiagnostic,
    accepted_output_records_by_node_port_view,
    node_state,
    run_state,
    task_state,
    validate_projection_integrity,
)


_ROOT = Path(__file__).parents[2]
_GRAPH_INIT = _ROOT / "src/orchestrator/graph/__init__.py"


def _declared_graph_api() -> set[str]:
    names: set[str] = set()
    for node in ast.parse(_GRAPH_INIT.read_text()).body:
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
    return {name for name in names if not name.startswith("_")}


def _public_graph_consumers() -> set[str]:
    consumers: set[str] = set()
    for source_root in (_ROOT / "src", _ROOT / "scripts"):
        for path in source_root.rglob("*.py"):
            if path == _GRAPH_INIT:
                continue
            consumers.update(_graph_consumers(path.read_text()))
    return consumers


def _graph_consumers(source: str) -> set[str]:
    tree = ast.parse(source)
    graph_aliases: set[str] = set()
    uses_qualified_graph = False
    consumers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name != "orchestrator.graph":
                    continue
                if alias.asname is None:
                    uses_qualified_graph = True
                else:
                    graph_aliases.add(alias.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "orchestrator":
            graph_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "graph"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "orchestrator.graph":
            consumers.update(alias.name for alias in node.names)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if isinstance(node.value, ast.Name) and node.value.id in graph_aliases:
            consumers.add(node.attr)
        elif (
            uses_qualified_graph
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "orchestrator"
            and node.value.attr == "graph"
        ):
            consumers.add(node.attr)
    return consumers


def test_graph_public_exports_are_exact_and_cover_application_consumers() -> None:
    graph = import_module("orchestrator.graph")

    assert _declared_graph_api() == set(graph.__all__)
    assert _public_graph_consumers() <= _declared_graph_api()
    assert len(graph.__all__) == len(set(graph.__all__))


def test_graph_public_consumer_inventory_excludes_test_only_imports() -> None:
    assert "ProjectionIntegrityDiagnostic" not in _public_graph_consumers()


def test_graph_public_consumer_inventory_handles_module_import_forms() -> None:
    source = """
import orchestrator.graph
import orchestrator.graph as graph_alias
from orchestrator import graph as package_graph

orchestrator.graph.run_state(projection)
graph_alias.task_state(projection, task_id)
package_graph.node_state(projection, node_id)
"""

    assert _graph_consumers(source) == {"node_state", "run_state", "task_state"}


def test_temporary_checkpoint_integrity_api_is_public() -> None:
    assert issubclass(ProjectionCheckpointCodecError, ValueError)
    assert ProjectionIntegrityDiagnostic(path="projection", reason="invalid").path == "projection"
    assert callable(validate_projection_integrity)


def test_projection_queries_are_available_only_from_the_graph_public_api() -> None:
    graph = import_module("orchestrator.graph")

    assert {
        "accepted_output_records_by_node_port_view",
        "node_state",
        "run_state",
        "task_state",
    } <= set(graph.__all__)
    assert (
        graph.accepted_output_records_by_node_port_view is accepted_output_records_by_node_port_view
    )
    assert graph.node_state is node_state
    assert graph.run_state is run_state
    assert graph.task_state is task_state
