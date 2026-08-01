import ast
from collections import deque
from collections.abc import MutableMapping
from pathlib import Path
import subprocess
from typing import Annotated, Literal

import pytest
import yaml
from pydantic import ConfigDict, create_model

from scripts.check_graph_projection_boundaries import (
    ALLOWED_STORAGE_READERS,
    check_projection_boundaries,
    projection_annotation_violations,
    projection_event_dispatch_types,
    projected_record_owner_paths,
    has_projection_provenance_seed,
)
from scripts.graph_projection_boundary_provenance import projection_provenance
from orchestrator.graph import (
    CANONICAL_EVENT_TYPES,
    FrozenMap,
    PROJECTION_NEUTRAL_EVENT_TYPES,
    GraphProjection,
    ProjectedCandidateRecord,
    ProjectionModel,
    RecordStore,
)


_ROOT = Path(__file__).parents[2]
_GRAPH_ROOT = _ROOT / "src/orchestrator/graph"


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


def test_boundary_guard_rejects_relative_external_graph_submodule_import(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text("from ..graph.projection_queries import run_state\n")

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [item.code for item in violations] == ["forbidden_graph_submodule_import"]


def test_boundary_guard_rejects_relative_external_graph_public_import(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text("from ..graph import run_state\n")

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [item.code for item in violations] == ["forbidden_graph_submodule_import"]


def test_boundary_guard_rejects_relative_graph_package_import(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text("from .. import graph as graph_api\n")

    violations = check_projection_boundaries(tmp_path, paths=(source,))

    assert [item.code for item in violations] == ["forbidden_graph_submodule_import"]


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


def test_permanent_boundary_guard_does_not_import_migration_inventory() -> None:
    source = (_ROOT / "scripts/check_graph_projection_boundaries.py").read_text()

    assert "graph_projection_inventory" not in source


def test_boundary_provenance_has_no_migration_bookkeeping_vocabulary() -> None:
    source = (_ROOT / "scripts/graph_projection_boundary_provenance.py").read_text()

    for retired_name in (
        "baseline_revision",
        "occurrence_id",
        "graph_projection_manifest",
        "MigrationDisposition",
    ):
        assert retired_name not in source
    assert not any(
        forbidden in source.lower()
        for forbidden in ("libcst", "yaml", "manifest", "disposition", "codemod")
    )


def test_boundary_provenance_uses_exact_origins_and_dotted_imports(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """import foreign
import orchestrator.graph
import orchestrator.graph_runtime.controller

def rejected(value: foreign.GraphProjection, controller: foreign.GraphController) -> None:
    value["no"]
    controller.read_projection()["no"]

def accepted(projection: orchestrator.graph.GraphProjection) -> None:
    projection["yes"]
    orchestrator.graph_runtime.controller.rebuild_projection([])["yes"]
"""
    )

    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (10, "legacy_projection_subscript"),
        (11, "legacy_projection_subscript"),
    ]


def test_boundary_provenance_traverses_class_methods_and_isolates_binders(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

class Holder:
    projection: GraphProjection

    def read(self, projection: GraphProjection, *args: object, **kwargs: object) -> None:
        projection["method"]
        self.projection["field"]
        for projection in args:
            projection["for"]
        (lambda projection: projection["lambda"])(None)
        match None:
            case projection:
                projection["match"]
"""
    )

    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (7, "legacy_projection_subscript"),
        (8, "legacy_projection_subscript"),
    ]


def test_boundary_provenance_branch_kills_and_keeps_possible_aliases() -> None:
    source = """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object, condition: bool) -> None:
    alias = projection
    if condition:
        alias = other
    else:
        alias = other
    alias["killed"]
    if condition:
        alias = projection
    alias["possible"]
"""

    facts = projection_provenance(source, relative_path="src/orchestrator/runtime/consumer.py")

    assert [
        (item.line, item.expression, item.certainty) for item in facts if item.line in {9, 12}
    ] == [
        (12, "alias['possible']", "possible"),
        (12, "alias", "possible"),
    ]


def test_boundary_provenance_preserves_colliding_expression_facts() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection) -> None:
    projection.records.by_id["record"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert [(item.expression, item.certainty) for item in facts if item.line == 4] == [
        ("projection.records.by_id['record']", "definite"),
        ("projection.records.by_id", "definite"),
        ("projection.records", "definite"),
        ("projection", "definite"),
    ]


def test_boundary_provenance_match_includes_no_match_and_exhaustive_paths() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object, value: object) -> None:
    alias = projection
    match value:
        case "matched":
            alias = other
    alias["no-match"]
    match value:
        case _:
            alias = other
    alias["exhaustive-kill"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert [(item.line, item.expression, item.certainty) for item in facts if item.line == 8] == [
        (8, "alias['no-match']", "possible"),
        (8, "alias", "possible"),
    ]
    assert not [item for item in facts if item.expression == "alias['exhaustive-kill']"]


def test_boundary_provenance_match_captures_shadow_guards_and_bodies() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(
    projection: GraphProjection,
    match_star: GraphProjection,
    match_rest: GraphProjection,
    nested: GraphProjection,
    klass: GraphProjection,
    mapping: GraphProjection,
    alternate: GraphProjection,
    value: object,
) -> None:
    match value:
        case "literal" if projection["unshadowed-guard"]:
            pass
        case [*match_star] if match_star["star-guard"]:
            match_star["star-body"]
        case {"rest": item, **match_rest} if match_rest["rest-guard"]:
            match_rest["rest-body"]
        case {"items": [nested]} if nested["nested-guard"]:
            nested["nested-body"]
        case Point(klass) if klass["class-guard"]:
            klass["class-body"]
        case {"item": mapping} if mapping["mapping-guard"]:
            mapping["mapping-body"]
        case (Point(alternate) | Other(alternate)) if alternate["or-guard"]:
            alternate["or-body"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert [
        (item.expression, item.certainty)
        for item in facts
        if item.expression == "projection['unshadowed-guard']"
    ] == [("projection['unshadowed-guard']", "definite")]
    assert not [
        item
        for item in facts
        if item.expression.endswith(("-guard']", "-body']"))
        and item.expression != "projection['unshadowed-guard']"
    ]


def test_boundary_provenance_try_keeps_successful_projection_with_handlers() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object) -> None:
    alias = other
    try:
        alias = projection
    except RuntimeError:
        alias = other
    alias["try-success"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert [(item.expression, item.certainty) for item in facts if item.line == 9] == [
        ("alias['try-success']", "possible"),
        ("alias", "possible"),
    ]


def test_boundary_provenance_try_applies_else_then_finally_to_each_path() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object) -> None:
    alias = projection
    try:
        pass
    except RuntimeError:
        alias = other
    else:
        alias = other
    finally:
        preserved = alias
    preserved["else-finally-kill"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert not [item for item in facts if item.expression == "preserved['else-finally-kill']"]


def test_boundary_provenance_try_finally_propagates_every_outgoing_path() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object) -> None:
    alias = other
    try:
        alias = projection
    except RuntimeError:
        alias = other
    finally:
        preserved = alias
    preserved["finally-propagates"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert [(item.expression, item.certainty) for item in facts if item.line == 11] == [
        ("preserved['finally-propagates']", "possible"),
        ("preserved", "possible"),
    ]


def test_boundary_provenance_resolves_only_exact_imported_dotted_origins() -> None:
    facts = projection_provenance(
        """import orchestrator.graph
import orchestrator.graph as graph
import orchestrator.graph_runtime.controller
import orchestrator.graph_runtime.controller as controller
from orchestrator.graph import GraphProjection as Projection, initial_projection, reduce_event
from orchestrator.graph_runtime.controller import rebuild_projection as rebuild

def accepted(value: Projection, dotted: orchestrator.graph.GraphProjection) -> None:
    value["parameter"]
    dotted["dotted-annotation"]
    orchestrator.graph.initial_projection()["root-import"]
    graph.build_projection([])["module-alias"]
    orchestrator.graph_runtime.controller.rebuild_projection([])["controller-import"]
    controller.rebuild_projection([])["controller-alias"]
    initial_projection()["from-import"]
    reduce_event(None, None)["from-reduce-import"]
    rebuild([])["from-controller-import"]

def rejected(
    unimported: unknown.graph.GraphProjection,
    foreign: foreign.GraphProjection,
) -> None:
    unimported["unimported-annotation"]
    foreign["foreign-annotation"]
    unknown.graph.initial_projection()["unimported-call"]
    foreign.initial_projection()["foreign-call"]

def shadowed(orchestrator: object, graph: object, controller: object) -> None:
    orchestrator.graph.initial_projection()["root-shadow"]
    graph.initial_projection()["module-shadow"]
    controller.rebuild_projection([])["controller-shadow"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {item.expression for item in facts if item.expression.endswith("]")} == {
        "value['parameter']",
        "dotted['dotted-annotation']",
        "orchestrator.graph.initial_projection()['root-import']",
        "graph.build_projection([])['module-alias']",
        "orchestrator.graph_runtime.controller.rebuild_projection([])['controller-import']",
        "controller.rebuild_projection([])['controller-alias']",
        "initial_projection()['from-import']",
        "reduce_event(None, None)['from-reduce-import']",
        "rebuild([])['from-controller-import']",
    }


def test_boundary_provenance_seeds_exactly_typed_variadics() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection as Projection

def accepted(*args: Projection, **kwargs: Projection) -> None:
    args["typed-vararg"]
    kwargs["typed-kwarg"]

def rejected(*args: object, **kwargs: foreign.GraphProjection) -> None:
    args["untyped-vararg"]
    kwargs["foreign-kwarg"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {item.expression for item in facts if item.expression.endswith("]")} == {
        "args['typed-vararg']",
        "kwargs['typed-kwarg']",
    }


def test_boundary_provenance_applies_walrus_augassign_and_delete_bindings() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object) -> None:
    (alias := projection)["walrus-set"]
    alias["after-set"]
    (alias := other)["walrus-kill"]
    alias["after-kill"]
    alias = projection
    alias += other
    alias["after-augassign"]
    alias = projection
    alias["item"] += 1
    alias["after-subscript-augassign"]
    alias = projection
    del alias["item"]
    alias["after-subscript-delete"]
    alias = projection
    del alias
    alias["after-delete"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {item.expression for item in facts if item.expression.endswith("]")} == {
        "(alias := projection)['walrus-set']",
        "alias['after-set']",
        "alias['item']",
        "alias['after-subscript-augassign']",
        "alias['after-subscript-delete']",
    }


def test_boundary_provenance_clears_and_restores_typed_field_provenance() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection

class Holder:
    projection: GraphProjection

    def read(self, projection: GraphProjection, other: object) -> None:
        self.projection = projection
        self.projection["field-set"]
        self.projection += other
        self.projection["field-augassign"]
        self.projection = projection
        self.projection = other
        self.projection["field-cleared"]
        self.projection = projection
        self.projection["field-restored"]
        del self.projection
        self.projection["field-deleted"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {item.expression for item in facts if item.expression.endswith("]")} == {
        "self.projection['field-set']",
        "self.projection['field-restored']",
    }


def test_boundary_provenance_named_expressions_follow_order_and_short_circuit(
    tmp_path: Path,
) -> None:
    source_text = """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object, condition: bool) -> None:
    (alias := projection)["set"]
    (alias := other)["kill"]
    alias["after-kill"]
    condition and (alias := projection)
    alias["short-circuit"]
"""
    facts = projection_provenance(source_text, relative_path="src/orchestrator/runtime/consumer.py")

    assert [
        (item.expression, item.certainty) for item in facts if item.expression.endswith("]")
    ] == [
        ("(alias := projection)['set']", "definite"),
        ("alias['short-circuit']", "possible"),
    ]

    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(source_text)
    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (4, "legacy_projection_subscript"),
        (8, "legacy_projection_subscript"),
    ]


def test_boundary_provenance_try_receives_intermediate_raised_state_and_finally_paths() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection, GraphDispatchContext

def read(projection: GraphProjection, other: object, condition: bool) -> None:
    context: GraphDispatchContext
    try:
        context.graph_projection = projection
        context.graph_projection = other
    except RuntimeError:
        handler = context.graph_projection
    else:
        normal = context.graph_projection
    finally:
        final = context.graph_projection
    handler["handler"]
    normal["else-only"]
    final["finally"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {
        (item.expression, item.certainty) for item in facts if item.expression.endswith("]")
    } == {
        ("handler['handler']", "possible"),
        ("final['finally']", "possible"),
    }


def test_boundary_provenance_joins_typed_receiver_and_field_runtime_state() -> None:
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection, GraphDispatchContext

def read(projection: GraphProjection, other: object, condition: bool) -> None:
    if condition:
        context: GraphDispatchContext
        context.graph_projection = projection
    else:
        context: GraphDispatchContext
        context.graph_projection = other
    context.graph_projection["possible-field"]
    context.graph_projection = projection
    context.graph_projection["restored-field"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {
        (item.expression, item.certainty) for item in facts if item.expression.endswith("]")
    } == {
        ("context.graph_projection['possible-field']", "possible"),
        ("context.graph_projection['restored-field']", "definite"),
    }


def test_boundary_provenance_requires_exact_module_subtree_imports_and_rejects_rebinding() -> None:
    facts = projection_provenance(
        """import orchestrator.graph
import orchestrator.graph_runtime.controller

def read() -> None:
    orchestrator.graph.initial_projection()["graph"]
    orchestrator.graph_runtime.controller.rebuild_projection([])["runtime"]
    orchestrator = object()
    orchestrator.graph.initial_projection()["rebound"]

def sibling() -> None:
    import orchestrator.graph
    orchestrator.graph_runtime.controller.rebuild_projection([])["sibling"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {item.expression for item in facts if item.expression.endswith("]")} == {
        "orchestrator.graph.initial_projection()['graph']",
        "orchestrator.graph_runtime.controller.rebuild_projection([])['runtime']",
    }


def test_boundary_provenance_mutating_attribute_or_subscript_keeps_receiver_but_kills_field() -> (
    None
):
    facts = projection_provenance(
        """from orchestrator.graph import GraphProjection, GraphDispatchContext

def read(projection: GraphProjection, other: object, context: GraphDispatchContext) -> None:
    alias = projection
    alias["item"] += 1
    alias["after-subscript"]
    context.graph_projection = projection
    context.graph_projection += other
    context.graph_projection["after-field-kill"]
    context.graph_projection = projection
    context.graph_projection["after-field-restore"]
    del alias["item"]
    alias["after-delete"]
""",
        relative_path="src/orchestrator/runtime/consumer.py",
    )

    assert {item.expression for item in facts if item.expression.endswith("]")} == {
        "alias['item']",
        "alias['after-subscript']",
        "context.graph_projection['after-field-restore']",
        "alias['after-delete']",
    }


def test_boundary_guard_traverses_executable_class_body(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection, initial_projection

class Holder:
    projection: GraphProjection = initial_projection()
    projection["class"]
    projection.records.by_id.update({})
"""
    )

    assert [item.code for item in check_projection_boundaries(tmp_path, paths=(source,))] == [
        "legacy_projection_subscript",
        "forbidden_grouped_storage_access",
        "mutable_projection_operation",
    ]


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


def test_boundary_guard_retains_pre_kill_try_exception_provenance(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def may_raise() -> None:
    pass

def read(projection: GraphProjection, other: object) -> None:
    alias = projection
    try:
        may_raise()
        alias = other
    except RuntimeError:
        alias["handler"]
    finally:
        alias["final"]
"""
    )

    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (12, "legacy_projection_subscript"),
        (14, "legacy_projection_subscript"),
    ]


def test_boundary_guard_retains_pre_kill_typed_field_exception_provenance(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphDispatchContext, GraphProjection

def may_raise() -> None:
    pass

def read(context: GraphDispatchContext, projection: GraphProjection, other: object) -> None:
    try:
        context.graph_projection = projection
        may_raise()
        context.graph_projection = other
    except RuntimeError:
        context.graph_projection["handler"]
    finally:
        context.graph_projection["final"]
"""
    )

    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (12, "legacy_projection_subscript"),
        (14, "legacy_projection_subscript"),
    ]


def test_boundary_guard_does_not_emit_provenance_after_return_or_raise(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def returned(projection: GraphProjection) -> None:
    return
    projection["after-return"]

def raised(projection: GraphProjection) -> None:
    raise RuntimeError()
    projection["after-raise"]
"""
    )

    assert not check_projection_boundaries(tmp_path, paths=(source,))


def test_boundary_guard_finally_replaces_normal_and_raised_outcomes(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def may_raise() -> None:
    pass

def killed(projection: GraphProjection, other: object) -> None:
    alias = projection
    try:
        may_raise()
    except RuntimeError:
        pass
    finally:
        alias = other
    alias["after-kill"]

def restored(other: object, projection: GraphProjection) -> None:
    alias = other
    try:
        may_raise()
    except RuntimeError:
        pass
    finally:
        alias = projection
    alias["after-set"]
"""
    )

    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (24, "legacy_projection_subscript"),
    ]


def test_boundary_guard_joins_loop_zero_continue_and_break_paths(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/runtime/consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from orchestrator.graph import GraphProjection

def read(projection: GraphProjection, other: object, values: list[bool]) -> None:
    alias = other
    for value in values:
        if value:
            alias = projection
            continue
        alias = projection
        break
    alias["after-loop"]
"""
    )

    assert [
        (item.line, item.code) for item in check_projection_boundaries(tmp_path, paths=(source,))
    ] == [
        (11, "legacy_projection_subscript"),
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


def test_graph_projection_has_no_legacy_typeddict_or_clone_helper() -> None:
    projection_model_source = (_GRAPH_ROOT / "projection_models.py").read_text()
    projection_source = (_GRAPH_ROOT / "projections.py").read_text()

    assert "TypedDict" not in projection_model_source
    assert "_clone_projection" not in projection_source


def test_graph_projection_root_groups_are_exact() -> None:
    assert tuple(GraphProjection.model_fields) == (
        "lifecycle",
        "nodes",
        "tasks",
        "topology",
        "records",
        "scheduling",
        "planning",
        "verification",
        "governance",
        "requirements",
        "execution",
        "usage",
    )


def test_projection_annotation_guard_accepts_only_recursive_immutable_forms() -> None:
    class ImmutableChild(ProjectionModel):
        value: Annotated[tuple[Literal["ready"], ...], "metadata"] = ()

    class ImmutableRoot(ProjectionModel):
        child: ImmutableChild = ImmutableChild()
        index: FrozenMap[str, frozenset[str]] = FrozenMap()

    assert not projection_annotation_violations(ImmutableRoot)
    assert not projection_annotation_violations(GraphProjection)


def test_projection_annotation_guard_does_not_trust_recursive_alias_by_identity() -> None:
    checker_tree = ast.parse((_ROOT / "scripts/check_graph_projection_boundaries.py").read_text())
    graph_imports = {
        alias.name
        for node in ast.walk(checker_tree)
        if isinstance(node, ast.ImportFrom) and node.module == "orchestrator.graph"
        for alias in node.names
    }

    assert "FrozenJsonValue" not in graph_imports


@pytest.mark.parametrize("annotation", (deque[str], MutableMapping[str, str], dict[str, str]))
def test_projection_annotation_guard_rejects_mutable_or_unknown_containers(
    annotation: object,
) -> None:
    MutableRoot = create_model("MutableRoot", __base__=ProjectionModel, value=(annotation, ...))

    assert projection_annotation_violations(MutableRoot)


def test_projection_annotation_guard_rejects_mutable_custom_class() -> None:
    class MutableCustom:
        value: str

    class MutableRoot(ProjectionModel):
        model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
        value: MutableCustom

    assert projection_annotation_violations(MutableRoot)


def test_projection_annotation_guard_rejects_recursive_generic_alias_mutation() -> None:
    type MutableRecursive[Value] = Value | MutableRecursive[list[Value]]

    class MutableRoot(ProjectionModel):
        model_config = ConfigDict(frozen=True, defer_build=True)
        value: MutableRecursive[str]

    assert projection_annotation_violations(MutableRoot)


def test_projected_record_owner_guard_allows_only_record_store_by_id() -> None:
    assert projected_record_owner_paths(GraphProjection) == frozenset({"records.by_id"})
    assert RecordStore.model_fields["by_id"].annotation is not None


def test_projected_record_owner_guard_rejects_concrete_duplicate_owner() -> None:
    class DuplicateOwner(ProjectionModel):
        records: FrozenMap[str, ProjectedCandidateRecord] = FrozenMap()

    assert projected_record_owner_paths(DuplicateOwner) == frozenset({"records"})


def test_projected_record_owner_guard_checks_frozen_map_keys() -> None:
    class DuplicateKeyOwner(ProjectionModel):
        records: FrozenMap[ProjectedCandidateRecord, str] = FrozenMap()

    assert projected_record_owner_paths(DuplicateKeyOwner) == frozenset({"records.key"})


def test_projected_record_owner_guard_expands_specialized_pep695_aliases() -> None:
    type OwnerAlias[Record] = FrozenMap[str, Record]

    class DuplicateAliasOwner(ProjectionModel):
        records: OwnerAlias[ProjectedCandidateRecord] = FrozenMap()

    assert projected_record_owner_paths(DuplicateAliasOwner) == frozenset({"records"})


def test_projected_record_owner_guard_checks_recursive_generic_alias_arguments() -> None:
    type RecursiveOwner[Value] = Value | RecursiveOwner[ProjectedCandidateRecord]

    class DuplicateRecursiveOwner(ProjectionModel):
        model_config = ConfigDict(frozen=True, defer_build=True)
        records: RecursiveOwner[str]

    assert projected_record_owner_paths(DuplicateRecursiveOwner) == frozenset({"records"})


def test_event_dispatch_guard_respects_branch_constraints() -> None:
    source = """
def reduce_event(state, event):
    if event.event_type == "handled":
        return reduce_family(state, event)
    return state

def reduce_family(state, event):
    if event.event_type in {"family_a", "family_b"}:
        return state
    return state

def unrelated():
    return "unrelated_canonical_event"
"""

    assert projection_event_dispatch_types(source) == frozenset({"handled"})


def test_event_dispatch_guard_ignores_nested_function_literals() -> None:
    source = """
def reduce_event(state, event):
    if event.event_type == "handled":
        return state

    def nested():
        if event.event_type == "nested_only":
            return state

    return state
"""

    assert projection_event_dispatch_types(source) == frozenset({"handled"})


def test_event_dispatch_guard_ignores_helper_calls_without_dispatch_outcome() -> None:
    source = """
def reduce_event(state, event):
    inspect_event(event)
    if event.event_type == "handled":
        return state
    return state

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset({"handled"})


def test_event_dispatch_guard_ignores_statically_unreachable_returns() -> None:
    source = """
def reduce_event(state, event):
    if event.event_type == "handled":
        return state
    if event.event_type == "unreachable":
        if False:
            return state
    raise ValueError
"""

    assert projection_event_dispatch_types(source) == frozenset({"handled"})


def test_event_dispatch_guard_ignores_statements_after_terminal_outcome() -> None:
    source = """
def reduce_event(state, event):
    raise ValueError
    if event.event_type == "after_raise":
        return state
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_counts_only_literals_with_returning_paths() -> None:
    source = """
def reduce_event(state, event):
    if event.event_type in {"partial_a", "partial_b"}:
        if event.event_type == "partial_a":
            return state
    raise ValueError
"""

    assert projection_event_dispatch_types(source) == frozenset({"partial_a"})


def test_event_dispatch_guard_ignores_chained_event_comparisons() -> None:
    source = """
def reduce_event(state, event):
    if event.event_type == "node_created" == "edge_created":
        return state
    raise ValueError
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_discarded_calls_inside_return_expression() -> None:
    source = """
def reduce_event(state, event):
    return (inspect_event(event), state)[1]

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_negative_index_discarded_calls() -> None:
    source = """
def reduce_event(state, event):
    return (inspect_event(event), state)[-1]

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


@pytest.mark.parametrize("index_setup", ("index = 1", "index = dynamic_index"))
def test_event_dispatch_guard_fails_closed_for_unknown_sequence_index(
    index_setup: str,
) -> None:
    source = f"""
def reduce_event(state, event, dynamic_index):
    {index_setup}
    return (inspect_event(event), state)[index]

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_statically_unselected_expressions() -> None:
    source = """
def reduce_event(state, event):
    return state if True else inspect_event(event)

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_statically_short_circuited_calls() -> None:
    source = """
def reduce_event(state, event):
    return True or inspect_event(event)

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_unselected_mapping_values() -> None:
    source = """
def reduce_event(state, event):
    return {"kept": state, "discarded": inspect_event(event)}["kept"]

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


@pytest.mark.parametrize(
    "wrapper",
    (
        "ignore(inspect_event(event), state)",
        "(lambda ignored, state: state)(inspect_event(event), state)",
        "_finalize_projection(inspect_event(event), state)",
    ),
)
def test_event_dispatch_guard_ignores_discarded_call_arguments(wrapper: str) -> None:
    source = f"""
def reduce_event(state, event):
    return {wrapper}

def ignore(value, state):
    return state

def _finalize_projection(value, state):
    return state

def inspect_event(event):
    if event.event_type == "observed_only":
        return "diagnostic"
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_overwritten_helper_results() -> None:
    source = """
def reduce_event(state, event):
    result = reduce_family(state, event)
    result = None
    if result is not None:
        return result
    raise ValueError

def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


@pytest.mark.parametrize(
    "overwrite",
    (
        "if True:\n        result = None",
        "if condition:\n        result = None\n    else:\n        result = None",
    ),
)
def test_event_dispatch_guard_ignores_results_overwritten_on_every_branch(
    overwrite: str,
) -> None:
    source = f"""
def reduce_event(state, event, condition):
    result = reduce_family(state, event)
    {overwrite}
    if result is not None:
        return result
    raise ValueError

def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


@pytest.mark.parametrize(
    ("signature", "binding"),
    (
        ("state, event, reduce_family", ""),
        ("state, event", "reduce_family = always_raises"),
    ),
)
def test_event_dispatch_guard_ignores_shadowed_top_level_helpers(
    signature: str,
    binding: str,
) -> None:
    source = f"""
def reduce_event({signature}):
    {binding}
    result = reduce_family(state, event)
    if result is not None:
        return result
    raise ValueError

def always_raises(state, event):
    raise ValueError

def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_rebound_module_helpers() -> None:
    source = """
def reduce_event(state, event):
    result = reduce_family(state, event)
    if result is not None:
        return result
    raise ValueError

def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None

def always_raises(state, event):
    raise ValueError

reduce_family = always_raises
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_decorated_helpers() -> None:
    source = """
def replace_with_raising(function):
    return always_raises

def reduce_event(state, event):
    result = reduce_family(state, event)
    if result is not None:
        return result
    raise ValueError

@replace_with_raising
def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None

def always_raises(state, event):
    raise ValueError
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_chained_result_comparisons() -> None:
    source = """
def reduce_event(state, event):
    result = reduce_family(state, event)
    if result is not None is False:
        return result
    raise ValueError

def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_event_dispatch_guard_ignores_pattern_capture_shadowing() -> None:
    source = """
def reduce_event(state, event, value):
    match value:
        case reduce_family:
            pass
    result = reduce_family(state, event)
    if result is not None:
        return result
    raise ValueError

def reduce_family(state, event):
    if event.event_type == "ghost":
        return state
    return None
"""

    assert projection_event_dispatch_types(source) == frozenset()


def test_actual_event_dispatch_and_projection_neutral_events_cover_canonical_events() -> None:
    projection_source = (_GRAPH_ROOT / "projections.py").read_text()

    assert CANONICAL_EVENT_TYPES == (
        projection_event_dispatch_types(projection_source) | PROJECTION_NEUTRAL_EVENT_TYPES
    )


def test_graph_projection_boundary_hook_is_permanent_and_exact() -> None:
    repositories = yaml.safe_load((_ROOT / ".pre-commit-config.yaml").read_text())["repos"]
    local_repository = next(
        repository for repository in repositories if repository["repo"] == "local"
    )
    boundary_hooks = [
        hook for hook in local_repository["hooks"] if hook["id"] == "graph-projection-boundaries"
    ]

    assert boundary_hooks == [
        {
            "id": "graph-projection-boundaries",
            "name": "graph-projection-boundaries",
            "entry": "uv run python scripts/check_graph_projection_boundaries.py",
            "language": "system",
            "pass_filenames": False,
        }
    ]
