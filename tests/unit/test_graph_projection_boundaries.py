from pathlib import Path

from scripts.check_graph_projection_boundaries import (
    ALLOWED_STORAGE_READERS,
    check_projection_boundaries,
)


def test_boundary_guard_rejects_legacy_access_mutation_and_submodule_import(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph.projections import GraphProjection

def read(projection: GraphProjection, key: str) -> None:
    projection["run_state"]
    projection[key]
    projection["node_states"] = {}
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert ALLOWED_STORAGE_READERS == frozenset(
        {
            "src/orchestrator/graph/projection_models.py",
            "src/orchestrator/graph/projection_collections.py",
            "src/orchestrator/graph/projection_queries.py",
            "src/orchestrator/graph/projection_codec.py",
            "src/orchestrator/graph/projections.py",
        }
    )
    assert [violation.code for violation in violations] == [
        "forbidden_graph_submodule_import",
        "legacy_projection_subscript",
        "dynamic_projection_access",
        "legacy_projection_subscript",
        "mutable_projection_operation",
    ]
