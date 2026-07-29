from pathlib import Path
import subprocess

import pytest

from scripts.check_graph_projection_boundaries import (
    ALLOWED_STORAGE_READERS,
    check_projection_boundaries,
    has_projection_provenance_seed,
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


def test_boundary_guard_tracks_constructed_alias_and_attribute_projections(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """import orchestrator.graph.projections
from orchestrator.graph import GraphProjection, initial_projection

class Holder:
    projection: GraphProjection

def read(holder: Holder) -> None:
    local: GraphProjection = initial_projection()
    alias = local
    holder.projection.lifecycle.run_state = "active"
    alias.records.by_id.remove("record")
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [violation.code for violation in violations] == [
        "forbidden_graph_submodule_import",
        "forbidden_grouped_storage_access",
        "forbidden_grouped_storage_access",
        "mutable_projection_operation",
    ]


def test_boundary_guard_default_scans_every_tracked_python_file(tmp_path: Path) -> None:
    source = tmp_path / "tests/unit/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection) -> None:
    projection["run_state"]
"""
    )
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "tests/unit/consumer.py"), cwd=tmp_path, check=True)

    violations = check_projection_boundaries(tmp_path)

    assert [violation.code for violation in violations] == ["legacy_projection_subscript"]


def test_boundary_guard_uses_source_order_and_lexical_provenance(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection, initial_projection

def read() -> None:
    alias["before"]
    alias = initial_projection()
    alias["after"]

def isolated() -> None:
    alias["separate"]
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [(item.line, item.code) for item in violations] == [
        (6, "legacy_projection_subscript"),
    ]


def test_boundary_guard_rejects_nested_storage_mutations_and_mutating_dunders(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def mutate(projection: GraphProjection, key: str) -> None:
    projection["nodes"][key] = {}
    del projection["nodes"][key]
    projection["nodes"][key] += 1
    projection.records.by_id.update({})
    projection.__setitem__(key, {})
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert any(item.code == "dynamic_projection_access" for item in violations)
    assert sum(item.code == "mutable_projection_operation" for item in violations) >= 5
    assert any(item.code == "forbidden_grouped_storage_access" for item in violations)


def test_boundary_guard_ignores_unrelated_values_and_public_query_calls(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection, run_state

def read(projection: GraphProjection, mapping: dict[str, object]) -> None:
    run_state(projection)
    mapping["nodes"].update({})
    mapping.records.by_id.remove("record")
"""
    )

    assert not check_projection_boundaries(tmp_path, paths=(source,))


def test_boundary_guard_rejects_both_external_graph_submodule_import_forms(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """import orchestrator.graph.projections as projections
from orchestrator.graph.projection_queries import run_state
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [item.code for item in violations] == [
        "forbidden_graph_submodule_import",
        "forbidden_graph_submodule_import",
    ]


def test_boundary_guard_applies_only_the_exact_physical_storage_allowlist(tmp_path: Path) -> None:
    allowed = tmp_path / "src/orchestrator/graph/projection_models.py"
    near_miss = tmp_path / "src/orchestrator/graph/projection_models_extra.py"
    for source in (allowed, near_miss):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection) -> None:
    projection["run_state"]
    projection.lifecycle.run_state
"""
        )

    assert not check_projection_boundaries(tmp_path, paths=(allowed,))
    assert check_projection_boundaries(tmp_path, paths=(near_miss,))


def test_boundary_guard_fails_closed_for_malformed_source(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text("def broken(:\n")

    try:
        check_projection_boundaries(tmp_path, paths=(source,))
    except ValueError as error:
        assert "cannot check malformed Python source" in str(error)
    else:
        raise AssertionError("malformed source must fail closed")


def test_boundary_guard_resolves_only_approved_unshadowed_producers(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection, initial_projection

def local() -> GraphProjection:
    return initial_projection()

def accepted() -> None:
    local()["run_state"]

def shadowed(initial_projection: object) -> None:
    initial_projection()["run_state"]
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [(item.line, item.code) for item in violations] == [
        (7, "legacy_projection_subscript"),
    ]


def test_boundary_provenance_candidate_selection_uses_only_collector_seed_origins() -> None:
    assert not has_projection_provenance_seed(
        """def mutate(values: dict[str, object]) -> None:
    values[\"nodes\"].update({})
    values.pop(\"stale\", None)
"""
    )

    sources_with_supported_collector_seeds = (
        "from orchestrator.graph import GraphProjection as Projection\nvalue: Projection\n",
        "from orchestrator.graph import initial_projection as build\nvalue = build()\n",
        "from orchestrator.graph import build_projection as build\nvalue = build()\n",
        "from orchestrator.graph import reduce_event as reduce\nvalue = reduce()\n",
        "from orchestrator.graph_runtime.controller import rebuild_projection as rebuild\nvalue = rebuild()\n",
        "from orchestrator.graph import GraphController\ncontroller: GraphController\n",
        "from orchestrator.graph import GraphEventStore\nstore: GraphEventStore\n",
        "from orchestrator.graph import GraphDispatchContext as Context\ncontext: Context\n",
        "from orchestrator.graph import GraphProjectionCheckpoint as Checkpoint\ncheckpoint: Checkpoint\n",
    )

    assert all(
        has_projection_provenance_seed(source) for source in sources_with_supported_collector_seeds
    )


def test_boundary_guard_tracks_direct_awaited_producer_access(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphController

async def read(controller: GraphController) -> None:
    (await controller.read_projection())["run_state"]
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [(item.line, item.code) for item in violations] == [
        (4, "legacy_projection_subscript"),
    ]


def test_boundary_guard_tracks_possible_alias_nested_and_grouped_mutations(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def mutate(projection: GraphProjection, other: object, condition: bool, key: str) -> None:
    if condition:
        alias = projection
    else:
        alias = other
    alias["nodes"][key] = {}
    alias.records.by_id.update({})
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [(item.line, item.code) for item in violations] == [
        (8, "dynamic_projection_access"),
        (8, "legacy_projection_subscript"),
        (8, "mutable_projection_operation"),
        (9, "forbidden_grouped_storage_access"),
        (9, "mutable_projection_operation"),
    ]


@pytest.mark.parametrize(
    "method",
    (
        "clear",
        "pop",
        "popitem",
        "setdefault",
        "update",
        "append",
        "extend",
        "insert",
        "remove",
        "reverse",
        "sort",
        "add",
        "difference_update",
        "discard",
        "intersection_update",
        "symmetric_difference_update",
        "__setitem__",
        "__delitem__",
        "__setattr__",
        "__delattr__",
        "__iadd__",
        "__imul__",
        "__ior__",
        "__iand__",
        "__ixor__",
        "__isub__",
    ),
)
def test_boundary_guard_rejects_complete_explicit_mutator_policy(
    tmp_path: Path, method: str
) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        f"""from orchestrator.graph import GraphProjection

def mutate(projection: GraphProjection) -> None:
    projection.records.by_id.{method}()
"""
    )

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert any(item.code == "mutable_projection_operation" for item in violations)
