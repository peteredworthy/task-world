"""Composition-owned dependencies for graph command execution."""

from dataclasses import dataclass

from orchestrator.graph.catalog import GraphCatalog


@dataclass(frozen=True)
class GraphCommandDependencies:
    """The immutable dependency bundle consumed by graph command runtimes."""

    catalog: GraphCatalog


def build_graph_command_dependencies(
    catalog: GraphCatalog,
) -> GraphCommandDependencies:
    """Compose the production graph kernel at the graph module boundary."""

    return GraphCommandDependencies(
        catalog=catalog,
    )


__all__ = ["GraphCommandDependencies", "build_graph_command_dependencies"]
