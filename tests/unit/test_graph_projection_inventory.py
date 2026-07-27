from pathlib import Path
import subprocess

from pydantic import ValidationError
import pytest

from orchestrator.graph import (
    GraphProjection,
    NodeCreationProjection,
    initial_projection,
    resource_claims_for_node,
)
from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    AccessOccurrence,
    DiagnosticCode,
    InventoryDiagnostic,
    collect_source,
    diagnostic_artifact,
    diagnostic_report,
    inventory_paths,
    inventory_repository,
    load_manifest,
    occurrence_id,
)


MANIFEST_PATH = Path(__file__).parents[2] / "scripts/codemods/graph_projection_manifest.yaml"
DESIGN_PATH = (
    Path(__file__).parents[2]
    / "docs/superpowers/specs/2026-07-26-immutable-graph-projection-design.md"
)
BASELINE_REVISION = "49e3f3bb03502530e52abb7304c5a31ecc5d4340"
DISPOSITION_CATEGORIES = {
    "Canonical": "canonical",
    "Canonical aggregate": "canonical",
    "Canonical decision state": "canonical",
    "Canonical entity": "canonical",
    "Canonical entity field": "canonical",
    "Canonical entity store": "canonical",
    "Canonical planner state": "canonical",
    "Canonical projected file-state record": "canonical",
    "Canonical relation": "canonical",
    "Derived latest-value index": "derived",
    "Derived ordered index": "derived",
    "Derived set index": "derived",
    "Idempotency set index": "index",
    "Materialized secondary index": "index",
    "Remove dormant checkpoint-only state with no event producer": "removed",
    "Remove duplicate payload after projection": "removed",
    "Remove duplicate payload index": "removed",
    "Remove duplicate payload wrapper": "removed",
    "Secondary ID index": "index",
    "Secondary ordered ID index": "index",
}


def _normative_ownership() -> list[tuple[str, str | None, str]]:
    rows: list[tuple[str, str | None, str]] = []
    in_table = False
    for line in DESIGN_PATH.read_text().splitlines():
        if line == "### Normative Field Ownership":
            in_table = True
        elif in_table and line.startswith("## "):
            break
        elif in_table and line.startswith("| `"):
            old_name, new_path, disposition = [cell.strip() for cell in line.strip("|").split("|")]
            rows.append(
                (
                    old_name.strip("`"),
                    None if new_path == "None" else new_path.strip("`"),
                    DISPOSITION_CATEGORIES[disposition],
                )
            )
    return rows


def test_manifest_covers_every_projection_field_exactly_once() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    old_fields = set(GraphProjection.__annotations__)

    assert len(old_fields) == 73
    assert len(manifest.fields) == 73
    assert {field.old_name for field in manifest.fields} == old_fields


def test_manifest_assigns_every_node_creation_field() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.node_creation_fields == frozenset(NodeCreationProjection.model_fields)


def test_manifest_gives_every_node_creation_field_one_destination_or_removal() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    assignments = {
        assignment.field_name: assignment for assignment in manifest.node_creation_ownership
    }

    assert set(assignments) == set(NodeCreationProjection.model_fields)
    assert all(
        (assignment.new_path is None) != (assignment.removal_reason is None)
        for assignment in assignments.values()
    )


def test_manifest_records_approved_baseline() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.baseline_revision == BASELINE_REVISION


def test_manifest_matches_complete_ordered_normative_ownership_table() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert [
        (field.old_name, field.new_path, field.disposition) for field in manifest.fields
    ] == _normative_ownership()


def test_manifest_models_forbid_extra_fields(tmp_path: Path) -> None:
    manifest = MANIFEST_PATH.read_text()
    path = tmp_path / "manifest.yaml"
    path.write_text(f"{manifest}\nunknown: true\n")

    with pytest.raises(ValidationError, match="extra_forbidden"):
        load_manifest(path)


def test_node_creation_assignment_requires_destination_or_removal(tmp_path: Path) -> None:
    manifest = MANIFEST_PATH.read_text().replace(
        '{field_name: node_id, new_path: "nodes.*.spec.node_id"}',
        "{field_name: node_id, new_path: null, removal_reason: null}",
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(manifest)

    with pytest.raises(ValidationError, match="destination or removal reason"):
        load_manifest(path)


def test_manifest_rejects_duplicate_node_creation_ownership(tmp_path: Path) -> None:
    assignment = '  - {field_name: node_id, new_path: "nodes.*.spec.node_id"}'
    manifest = MANIFEST_PATH.read_text().replace(assignment, f"{assignment}\n{assignment}")
    path = tmp_path / "manifest.yaml"
    path.write_text(manifest)

    with pytest.raises(ValidationError, match="duplicate node creation ownership"):
        load_manifest(path)


def test_manifest_rejects_node_creation_field_mismatch(tmp_path: Path) -> None:
    manifest = MANIFEST_PATH.read_text().replace(
        "node_creation_fields:\n  - node_id",
        "node_creation_fields:\n  - unexpected_field",
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(manifest)

    with pytest.raises(ValidationError, match="node creation fields and ownership differ"):
        load_manifest(path)


def test_resource_claim_query_returns_an_immutable_sequence() -> None:
    projection = initial_projection()
    claim = NodeCreationProjection(
        node_id="worker-1",
        position=1,
        resource_claims=[{"mode": "read", "scope": "repo"}],
    ).resource_claims[0]
    projection["node_resource_claims"]["worker-1"] = [claim]

    assert resource_claims_for_node(projection, "worker-1") == (claim,)
    assert resource_claims_for_node(projection, "missing") == ()


def test_collect_source_classifies_supported_projection_accesses() -> None:
    inventory = collect_source(
        """
from typing import cast

def access(projection: GraphProjection) -> None:
    alias = projection
    read = alias["run_state"]
    gotten = projection.get("run_state")
    member = "run_state" in projection
    not_member = "run_state" not in projection
    keys = projection.keys()
    values = projection.values()
    items = projection.items()
    for value in projection:
        pass
    projection["run_state"] = "active"
    projection["node_states"]["node"] = "active"
    projection.setdefault("node_states", {})
    projection["ready_nodes"].append("node")
    projection["ready_nodes"].extend(("other",))
    del projection["run_state"]
    projection.pop("run_state")
    first, second = projection["ready_nodes"]
    converted = cast(dict[str, str], projection["node_states"])
    consume(projection)

def fixture() -> GraphProjection:
    return GraphProjection(run_state="active")
""",
        relative_path="sample.py",
        baseline_revision="baseline",
    )

    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]
    assert len(inventory.occurrences) == 18
    assert {occurrence.kind for occurrence in inventory.occurrences} == {
        "literal_subscript_read",
        "get",
        "membership",
        "keys",
        "values",
        "items",
        "direct_iteration",
        "direct_assignment",
        "nested_assignment",
        "setdefault",
        "append_extend",
        "delete_pop",
        "unpack_cast",
        "fixture_construction",
    }
    assert [occurrence.kind for occurrence in inventory.occurrences].count("append_extend") == 2
    assert all(
        occurrence.qualified_function in {"access", "fixture"}
        for occurrence in inventory.occurrences
    )
    assert all(
        occurrence.ordering_sensitivity_disposition
        in {
            "not_applicable",
            "insensitive",
            "sorted",
            "explicit_index",
        }
        for occurrence in inventory.occurrences
    )


def test_collect_source_rejects_invalid_or_ambiguous_accesses() -> None:
    computed = collect_source(
        "def read(projection: GraphProjection, key: str):\n    return projection[key]\n",
        relative_path="computed.py",
        baseline_revision="baseline",
    )
    unknown = collect_source(
        'def read(projection: GraphProjection):\n    return projection["unknown"]\n',
        relative_path="unknown.py",
        baseline_revision="baseline",
    )
    invalid = collect_source(
        "def broken(:\n",
        relative_path="invalid.py",
        baseline_revision="baseline",
    )

    assert [diagnostic.code for diagnostic in computed.diagnostics] == ["computed_key"]
    assert [diagnostic.code for diagnostic in unknown.diagnostics] == ["unknown_field"]
    assert [diagnostic.code for diagnostic in invalid.diagnostics] == ["parse_error"]
    assert not invalid.occurrences


def test_collect_source_tracks_only_direct_local_aliases() -> None:
    inventory = collect_source(
        """
def aliases(projection: GraphProjection) -> None:
    alias = projection
    alias["run_state"]
    alias = {}
    alias["node_states"]

def separate() -> None:
    alias["run_state"]
""",
        relative_path="aliases.py",
        baseline_revision="baseline",
    )

    assert [occurrence.old_field_name for occurrence in inventory.occurrences] == ["run_state"]
    assert not inventory.diagnostics


def test_occurrence_identity_ignores_positions_and_uses_deterministic_ordinals() -> None:
    first = collect_source(
        'def read(projection: GraphProjection):\n    projection["run_state"]\n    projection["run_state"]\n',
        relative_path="identity.py",
        baseline_revision="baseline",
    )
    shifted = collect_source(
        'def read(projection: GraphProjection):\n\n\n    projection["run_state"]\n    projection["run_state"]\n',
        relative_path="identity.py",
        baseline_revision="baseline",
    )

    assert [item.occurrence_id for item in first.occurrences] == [
        item.occurrence_id for item in shifted.occurrences
    ]
    assert [item.same_expression_ordinal for item in first.occurrences] == [0, 1]
    assert first.occurrences[0].occurrence_id == occurrence_id(
        "baseline", "identity.py", "read", "projection['run_state']", 0
    )


def test_collect_source_rejects_reflection_unpacking_and_unsupported_calls() -> None:
    inventory = collect_source(
        """
def rejected(projection: GraphProjection) -> None:
    getattr(projection, "run_state")
    dict(projection)
    projection.clear()
    {**projection}
""",
        relative_path="rejected.py",
        baseline_revision="baseline",
    )

    assert [diagnostic.code for diagnostic in inventory.diagnostics] == [
        "reflection",
        "projection_unpacking",
        "unsupported_call",
        "projection_unpacking",
    ]


def test_collect_source_diagnoses_every_unrecognized_tracked_argument() -> None:
    inventory = collect_source(
        """
def rejected(projection: GraphProjection) -> None:
    consumer(projection)
""",
        relative_path="calls.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]
    assert (
        inventory.diagnostics[0].remediation
        == "replace the dynamic call with a typed projection query"
    )


def test_collect_source_requires_a_qualified_recognized_cast_symbol() -> None:
    inventory = collect_source(
        """
def rejected(projection: GraphProjection) -> None:
    cast(dict[str, str], projection["node_states"])
""",
        relative_path="unqualified-cast.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]


def test_inventory_paths_uses_exact_qualified_producers_and_fields_with_shadowing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "producer.py"
    source.write_text(
        """
from orchestrator.graph import GraphController, GraphDispatchContext, GraphEventStore, GraphProjection, GraphProjectionCheckpoint

class Checkpoint:
    projection: GraphProjection

async def use(
    controller: GraphController,
    store: GraphEventStore,
    checkpoint: GraphProjectionCheckpoint,
    run_id: str,
) -> None:
    first = await controller.read_projection(run_id)
    first["run_state"]
    second, _, _ = await store.load_projection_with_tail(run_id)
    second["node_states"]
    checkpoint.projection["ready_nodes"]

async def shadow(controller: object, store: object, checkpoint: object, run_id: str) -> None:
    first = await controller.read_projection(run_id)
    first["run_state"]
    second, _, _ = await store.load_projection_with_tail(run_id)
    second["node_states"]
    checkpoint.projection["ready_nodes"]
"""
    )
    manifest = load_manifest(MANIFEST_PATH)

    inventory = inventory_paths((source,), manifest, root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("use", "run_state"),
        ("use", "node_states"),
        ("use", "ready_nodes"),
    ]
    assert not inventory.diagnostics


def test_collect_source_rejects_reflection_and_callable_annotation_escapes() -> None:
    inventory = collect_source(
        """
from typing import Any, Callable

def rejected(projection: GraphProjection) -> None:
    setattr(projection, "run_state", "active")
    vars(projection)
    projection.__dict__
    escape: Callable[..., object] = projection
    unknown: Any = projection
""",
        relative_path="escapes.py",
        baseline_revision="baseline",
    )

    assert [item.code for item in inventory.diagnostics] == [
        "reflection",
        "reflection",
        "reflection",
        "unsupported_binding",
        "unsupported_binding",
    ]


def test_diagnostic_report_is_sorted_and_includes_code_counts() -> None:
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(),
        diagnostics=(
            InventoryDiagnostic(
                relative_path="z.py",
                qualified_function="z",
                line=2,
                column=0,
                code=DiagnosticCode.UNSUPPORTED_CALL,
                message="z",
                remediation="stored call remediation",
            ),
            InventoryDiagnostic(
                relative_path="a.py",
                qualified_function="a",
                line=1,
                column=0,
                code=DiagnosticCode.REFLECTION,
                message="a",
                remediation="stored reflection remediation",
            ),
        ),
    )

    assert diagnostic_report(inventory) == (
        "Unresolved GraphProjection flows: 2\n"
        "reflection: 1\n"
        "unsupported_call: 1\n"
        "\n"
        "a.py:1:0: a: reflection: a; stored reflection remediation\n"
        "z.py:2:0: z: unsupported_call: z; stored call remediation\n"
    )


def test_collect_source_fails_closed_for_unsupported_bindings_and_construction() -> None:
    inventory = collect_source(
        """
def bindings(projection: GraphProjection) -> None:
    first = second = projection
    left, right = projection
    projection, other = other, projection
    built = GraphProjection("active")
    built = GraphProjection(**{"run_state": "active"})
    for projection in ():
        pass
    value = (projection := {})
""",
        relative_path="bindings.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_construction",
        "unsupported_construction",
        "unsupported_binding",
        "unsupported_binding",
    ]


def test_collect_source_uses_class_qualified_scopes_and_isolates_aliases() -> None:
    inventory = collect_source(
        """
class Worker:
    def method(self, projection: GraphProjection) -> None:
        alias = projection
        alias["run_state"]
        def nested() -> None:
            alias["node_states"]
        values = [alias["node_states"] for alias in ()]
        callback = lambda: alias["ready_nodes"]
""",
        relative_path="scopes.py",
        baseline_revision="baseline",
    )

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("Worker.method", "run_state")
    ]


def test_normalized_expression_ignores_formatting_comments_quotes_and_lines() -> None:
    first = collect_source(
        'def read(projection: GraphProjection):\n    return projection["run_state"]\n',
        relative_path="normal.py",
        baseline_revision="baseline",
    )
    second = collect_source(
        "def read(projection: GraphProjection):\n\n    return projection [ # comment\n        'run_state' ]\n",
        relative_path="normal.py",
        baseline_revision="baseline",
    )

    assert first.occurrences[0].normalized_expression == second.occurrences[0].normalized_expression
    assert first.occurrences[0].occurrence_id == second.occurrences[0].occurrence_id


def test_collect_source_rejects_remaining_binding_and_call_shapes() -> None:
    inventory = collect_source(
        """
def invalid(projection: GraphProjection) -> None:
    consume(*projection)
    consume(**projection)
    projection.get("run_state", None, "extra")
    projection.keys(extra=True)
    projection["ready_nodes"].append("node", "other")
    typed: object = projection
    typed += projection
    for left, projection in ():
        pass
    with context() as projection:
        pass
    try:
        pass
    except ValueError as projection:
        pass
""",
        relative_path="invalid_shapes.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert len(inventory.diagnostics) == 10
    assert {item.code for item in inventory.diagnostics} >= {
        "unsupported_binding",
        "projection_unpacking",
        "unsupported_call",
    }


def test_collect_source_ignores_unrelated_chains_and_rejects_projection_chains() -> None:
    inventory = collect_source(
        """
def comparisons(projection: GraphProjection) -> None:
    unrelated = 1 < 2 < 3
    involved = "run_state" in projection == projection
    subscript_involved = projection["node_states"] < 2 < 3
""",
        relative_path="comparisons.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_comparison",
        "unsupported_comparison",
    ]


def test_collect_source_seeds_zero_parameter_local_and_variadic_annotations() -> None:
    inventory = collect_source(
        """
def local() -> None:
    projection: GraphProjection
    projection["run_state"]

def variadic(*args: GraphProjection, **kwargs: GraphProjection) -> None:
    args["node_states"]
    kwargs["ready_nodes"]
""",
        relative_path="seeds.py",
        baseline_revision="baseline",
    )

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("local", "run_state"),
        ("variadic", "node_states"),
        ("variadic", "ready_nodes"),
    ]


def test_collect_source_rejects_subscript_methods_outside_append_extend() -> None:
    inventory = collect_source(
        """
def methods(projection: GraphProjection) -> None:
    projection["node_states"].update({})
    projection["ready_nodes"].clear()
    projection["run_state"].replace("a", "b")
""",
        relative_path="methods.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_call",
        "unsupported_call",
        "unsupported_call",
    ]


def test_collect_source_removes_aliases_after_unsupported_rebinding() -> None:
    inventory = collect_source(
        """
def rebindings(projection: GraphProjection) -> None:
    augmented = projection
    augmented += other
    augmented["run_state"]
    contextual = projection
    with context() as contextual:
        pass
    contextual["node_states"]
    exceptional = projection
    try:
        pass
    except ValueError as exceptional:
        pass
    exceptional["ready_nodes"]
""",
        relative_path="rebindings.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
    ]


def test_collect_source_uses_lexical_qualified_function_identity() -> None:
    inventory = collect_source(
        """
def outer() -> None:
    class Nested:
        def method(projection: GraphProjection) -> None:
            projection["run_state"]

class Nested:
    def outer() -> None:
        def method(projection: GraphProjection) -> None:
            projection["node_states"]
""",
        relative_path="lexical_scopes.py",
        baseline_revision="baseline",
    )

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("Nested.outer.method", "node_states"),
        ("outer.Nested.method", "run_state"),
    ]


def test_collect_source_only_diagnoses_methods_on_tracked_field_subscripts() -> None:
    inventory = collect_source(
        """
def methods(projection: GraphProjection, mapping: dict[str, object]) -> None:
    mapping["key"].update({})
    mapping["key"].clear()
    projection["node_states"].update({})
""",
        relative_path="tracked_methods.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]


def test_collect_source_classifies_deep_projection_subscripts_once() -> None:
    inventory = collect_source(
        """
def nested(projection: GraphProjection) -> None:
    read = projection["node_states"]["node"]
    projection["node_states"]["node"]["status"] = "active"
""",
        relative_path="deep.py",
        baseline_revision="baseline",
    )

    assert [
        (item.kind, item.old_field_name, item.normalized_expression)
        for item in inventory.occurrences
    ] == [
        ("literal_subscript_read", "node_states", "projection['node_states']['node']"),
        (
            "nested_assignment",
            "node_states",
            "projection['node_states']['node']['status']",
        ),
    ]


def test_collect_source_keeps_rhs_tracking_until_rebinding_is_applied() -> None:
    inventory = collect_source(
        """
def assignments(projection: GraphProjection) -> None:
    alias = projection
    alias = alias["run_state"]
    alias["node_states"]
    typed: object = projection["ready_nodes"]
""",
        relative_path="rhs.py",
        baseline_revision="baseline",
    )

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("literal_subscript_read", "run_state"),
        ("literal_subscript_read", "ready_nodes"),
    ]
    assert not inventory.diagnostics


def test_collect_source_forgets_historical_alias_after_normal_rebinding() -> None:
    inventory = collect_source(
        """
def rebindings(projection: GraphProjection) -> None:
    alias = projection
    alias = object()
    for alias in ():
        pass
    with context() as alias:
        pass
    try:
        pass
    except ValueError as alias:
        pass
""",
        relative_path="normal_rebinding.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert not inventory.diagnostics


def test_collect_source_enforces_exact_call_shapes_and_tracks_constructor_escapes() -> None:
    inventory = collect_source(
        """
from typing import cast

def calls(projection: GraphProjection) -> None:
    cast(dict[str, object], projection["node_states"], str)
    projection()
    GraphProjection(run_state=projection)
""",
        relative_path="calls.py",
        baseline_revision="baseline",
    )

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("fixture_construction", "run_state"),
        ("untyped_escape", None),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_call",
        "unsupported_call",
    ]


def test_collect_source_diagnoses_only_projection_comparisons_and_compfor_iteration() -> None:
    inventory = collect_source(
        """
def comparisons(projection: GraphProjection) -> None:
    unrelated = 1 == 2
    simple = projection["run_state"] == "active"
    chained = projection.get("node_states") < 2 < 3
    values = [value for value in projection]
""",
        relative_path="comparison.py",
        baseline_revision="baseline",
    )

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("direct_iteration", None),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_comparison",
        "unsupported_comparison",
    ]


def test_collect_source_uses_execution_scope_for_definition_metadata() -> None:
    inventory = collect_source(
        """
def outer(projection: GraphProjection) -> None:
    @projection["run_state"]
    def decorated() -> projection["node_states"]:
        pass

    def defaulted(value=projection["ready_nodes"]) -> None:
        pass
""",
        relative_path="definition_metadata.py",
        baseline_revision="baseline",
    )

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("outer", "run_state"),
        ("outer", "node_states"),
        ("outer", "ready_nodes"),
    ]


def test_inventory_models_are_strict_frozen_and_enum_typed() -> None:
    occurrence = AccessOccurrence(
        occurrence_id="id",
        relative_path="source.py",
        qualified_function="f",
        normalized_expression="projection['run_state']",
        same_expression_ordinal=0,
        old_field_name="run_state",
        kind=AccessKind.LITERAL_SUBSCRIPT_READ,
        line=1,
        column=0,
        ordering_sensitivity_disposition="insensitive",
    )
    diagnostic = InventoryDiagnostic(
        relative_path="source.py",
        line=1,
        column=0,
        code=DiagnosticCode.UNSUPPORTED_CALL,
        message="unsupported",
    )

    assert occurrence.kind is AccessKind.LITERAL_SUBSCRIPT_READ
    assert diagnostic.code is DiagnosticCode.UNSUPPORTED_CALL
    with pytest.raises(ValidationError):
        AccessOccurrence.model_validate({**occurrence.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        occurrence.line = 2


def test_collect_source_sorts_by_every_documented_sort_tuple_component() -> None:
    inventory = collect_source(
        """
def beta(projection: GraphProjection) -> None:
    projection["ready_nodes"]

def alpha(projection: GraphProjection) -> None:
    projection["node_states"]
    projection["run_state"]
""",
        relative_path="sorting.py",
        baseline_revision="baseline",
    )

    assert [
        (
            item.relative_path,
            item.qualified_function,
            item.line,
            item.column,
            item.kind,
        )
        for item in inventory.occurrences
    ] == sorted(
        (
            item.relative_path,
            item.qualified_function,
            item.line,
            item.column,
            item.kind,
        )
        for item in inventory.occurrences
    )


def test_collect_source_diagnoses_augmented_projection_mutation_without_child_reads() -> None:
    inventory = collect_source(
        """
def mutations(projection: GraphProjection, value: object) -> None:
    projection["run_state"] += value
    projection["node_states"]["node"] += value
    projection["node_states"]["node"]["status"] += value
""",
        relative_path="augmented.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_mutation",
        "unsupported_mutation",
        "unsupported_mutation",
    ]


def test_collect_source_classifies_nested_delete_without_emitting_a_read() -> None:
    inventory = collect_source(
        """
def deletes(projection: GraphProjection) -> None:
    del projection["run_state"]
    del projection["node_states"]["node"]
""",
        relative_path="delete.py",
        baseline_revision="baseline",
    )

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("delete_pop", "run_state"),
        ("delete_pop", "node_states"),
    ]
    assert not inventory.diagnostics


def test_collect_source_supports_one_and_two_argument_get_and_pop_calls() -> None:
    inventory = collect_source(
        """
def calls(projection: GraphProjection) -> None:
    projection.get("run_state")
    projection.get("run_state", None)
    projection.pop("node_states")
    projection.pop("node_states", None)
    projection.get("run_state", None, "extra")
    projection.pop("node_states", None, "extra")
""",
        relative_path="get-pop.py",
        baseline_revision="baseline",
    )

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("get", "run_state"),
        ("get", "run_state"),
        ("delete_pop", "node_states"),
        ("delete_pop", "node_states"),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_call",
        "unsupported_call",
    ]


def test_collect_source_handles_calls_on_get_values_fail_closed() -> None:
    inventory = collect_source(
        """
def methods(projection: GraphProjection) -> None:
    projection.get("ready_nodes").append("node")
    projection.get("node_states", {}).update({})
""",
        relative_path="get-methods.py",
        baseline_revision="baseline",
    )

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("append_extend", "ready_nodes"),
    ]
    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]


def test_collect_source_rejects_direct_and_deep_projection_value_invocation() -> None:
    inventory = collect_source(
        """
def calls(projection: GraphProjection) -> None:
    projection.get("run_state")()
    projection["run_state"]()
    projection["node_states"]["node"]()
    projection.get("node_states")["node"]()
""",
        relative_path="value-calls.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_call",
        "unsupported_call",
        "unsupported_call",
        "unsupported_call",
    ]


def test_collect_source_fails_closed_for_destructured_projection_targets() -> None:
    inventory = collect_source(
        """
def targets(projection: GraphProjection) -> None:
    projection["run_state"], other = values
    first, projection["node_states"]["node"] = values
    projection["ready_nodes"], alias = projection
    del projection["ready_nodes"], projection["node_states"]["node"]
""",
        relative_path="destructured-targets.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_mutation",
        "unsupported_mutation",
    ]


@pytest.mark.parametrize(
    "method_call",
    [
        'projection.get("run_state")()',
        'projection.pop("run_state")()',
        'projection.setdefault("run_state", None)()',
        "projection.keys()()",
        "projection.values()()",
        "projection.items()()",
        'projection["ready_nodes"].append("node")()',
        'projection["ready_nodes"].extend(("node",))()',
        'projection.get("ready_nodes").append("node")()',
        'projection.get("ready_nodes").extend(("node",))()',
    ],
)
def test_collect_source_rejects_invocation_of_every_supported_method_result(
    method_call: str,
) -> None:
    inventory = collect_source(
        f"""
def calls(projection: GraphProjection) -> None:
    {method_call}
""",
        relative_path="method-result-calls.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]


def test_collect_source_diagnoses_starred_projection_subscript_targets() -> None:
    inventory = collect_source(
        """
def targets(projection: GraphProjection) -> None:
    first, *projection["node_states"]["node"] = values
""",
        relative_path="starred-projection-target.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_binding"]


def test_collect_source_clears_alias_after_starred_destructured_rebinding() -> None:
    inventory = collect_source(
        """
def aliases(projection: GraphProjection) -> None:
    alias = projection
    first, *alias = values
    alias["run_state"]
""",
        relative_path="starred-alias-target.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_binding"]


@pytest.mark.parametrize(
    "target",
    [
        'projection["run_state"], alias',
        'projection["run_state"], *alias',
    ],
)
def test_collect_source_clears_alias_independently_of_projection_target_diagnostic(
    target: str,
) -> None:
    inventory = collect_source(
        f"""
def aliases(projection: GraphProjection) -> None:
    alias = projection
    {target} = values
    alias["run_state"]
""",
        relative_path="mixed-starred-alias-target.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_binding"]


@pytest.mark.parametrize(
    "expression",
    [
        "projection.keys().clear()",
        'projection.setdefault("run_state", None).update({})',
        'projection.pop("run_state").method()',
        'projection.get("node_states")["node"].update({})',
    ],
)
def test_collect_source_rejects_calls_on_chained_projection_method_results(
    expression: str,
) -> None:
    inventory = collect_source(
        f"""
def calls(projection: GraphProjection) -> None:
    {expression}
""",
        relative_path="chained-method-result-calls.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_call"]


@pytest.mark.parametrize(
    ("expression", "diagnostic_code"),
    [
        ('projection["unknown"]["nested"]', "unknown_field"),
        ('projection[unknown]["nested"]', "computed_key"),
    ],
)
def test_collect_source_deduplicates_invalid_deep_subscript_diagnostics(
    expression: str, diagnostic_code: str
) -> None:
    inventory = collect_source(
        f"""
def reads(projection: GraphProjection, unknown: str) -> None:
    {expression}
""",
        relative_path="invalid-deep-subscript.py",
        baseline_revision="baseline",
    )

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [diagnostic_code]


def test_inventory_paths_follows_known_returns_pass_through_and_context_flow(
    tmp_path: Path,
) -> None:
    source = tmp_path / "flow.py"
    source.write_text(
        """
from orchestrator.graph import GraphDispatchContext, GraphProjection, initial_projection

def make() -> GraphProjection:
    return initial_projection()

def pass_through(projection: GraphProjection) -> GraphProjection:
    return projection

def read() -> None:
    projection = pass_through(make())
    projection["run_state"]

def dispatch(context: GraphDispatchContext) -> None:
    context.graph_projection = make()
    context.graph_projection["node_states"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("dispatch", "node_states"),
        ("read", "run_state"),
    ]
    assert not inventory.diagnostics


def test_inventory_paths_tracks_annotated_attributes_and_rejects_any_callbacks_and_imports(
    tmp_path: Path,
) -> None:
    source = tmp_path / "escapes.py"
    source.write_text(
        """
from external import projection_alias
from typing import Any, cast
from orchestrator.graph import GraphProjection

class Holder:
    projection: GraphProjection

def read(holder: Holder, projection: GraphProjection, callback: object) -> None:
    holder.projection = projection
    holder.projection["ready_nodes"]
    cast(dict[str, str], projection["node_states"])
    any_value: Any = projection
    callback(projection)
    projection_alias["run_state"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.kind, item.old_field_name) for item in inventory.occurrences] == [
        ("literal_subscript_read", "ready_nodes"),
        ("unpack_cast", "node_states"),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_call",
    ]
    assert [item.qualified_function for item in inventory.diagnostics] == ["read", "read"]
    assert all(item.remediation for item in inventory.diagnostics)


def test_inventory_paths_uses_typed_constructor_and_checkpoint_provenance(tmp_path: Path) -> None:
    source = tmp_path / "provenance.py"
    source.write_text(
        """
from orchestrator.graph import GraphDispatchContext, GraphProjection, GraphProjectionCheckpoint, initial_projection

def read(checkpoint: GraphProjectionCheckpoint) -> None:
    checkpoint.projection["run_state"]

def dispatch() -> None:
    context = GraphDispatchContext(graph_projection=initial_projection())
    context.graph_projection["node_states"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("dispatch", "node_states"),
        ("read", "run_state"),
    ]


def test_inventory_paths_does_not_diagnose_ordinary_imported_subscripts(tmp_path: Path) -> None:
    source = tmp_path / "generic.py"
    source.write_text("from typing import List\n\ndef read() -> None:\n    List[int]\n")

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert not inventory.diagnostics


def test_inventory_repository_excludes_generated_and_sorts_files(tmp_path: Path) -> None:
    for relative_path in (
        "src/z.py",
        "tests/a.py",
        "scripts/b.py",
        "vendor/ignored.py",
        "worktrees/ignored.py",
        ".venv/ignored.py",
        "src/__pycache__/ignored.py",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "from orchestrator.graph import GraphProjection\n\n"
            'def read(projection: GraphProjection):\n    projection["run_state"]\n'
        )

    inventory = inventory_repository(
        tmp_path,
        load_manifest(MANIFEST_PATH),
        tracked_paths=tuple(
            tmp_path / relative_path
            for relative_path in (
                "src/z.py",
                "tests/a.py",
                "scripts/b.py",
                "vendor/ignored.py",
                "worktrees/ignored.py",
                ".venv/ignored.py",
                "src/__pycache__/ignored.py",
            )
        ),
    )

    assert [item.relative_path for item in inventory.occurrences] == [
        "scripts/b.py",
        "src/z.py",
        "tests/a.py",
    ]
    assert AccessInventory.model_config.get("frozen") is True


def test_real_repository_inventory_reports_production_projection_flows() -> None:
    root = Path(__file__).parents[2]
    inventory = inventory_repository(
        root,
        load_manifest(MANIFEST_PATH),
        tracked_paths=(
            root / "src/orchestrator/graph_runtime/recovery.py",
            root / "src/orchestrator/graph_runtime/store.py",
        ),
    )
    report = diagnostic_report(inventory)

    assert any(
        item.relative_path == "src/orchestrator/graph_runtime/recovery.py"
        and item.qualified_function == "reconcile_graph"
        and item.code is DiagnosticCode.UNSUPPORTED_COMPARISON
        for item in inventory.diagnostics
    )
    assert inventory.diagnostics
    assert all(
        item.relative_path
        and item.qualified_function
        and item.message
        and item.remediation
        and f"{item.relative_path}:{item.line}:{item.column}:" in report
        for item in inventory.diagnostics
    )


def test_inventory_paths_does_not_parse_detached_attribute_fragments(tmp_path: Path) -> None:
    source = tmp_path / "ordinary.py"
    source.write_text('def ordinary(values: list[str]) -> str:\n    return ",".join(values)\n')

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert not inventory.diagnostics


def test_inventory_paths_enforces_provenance_first_symbols_and_bounded_escapes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "provenance.py"
    source.write_text(
        """
import typing as t
from typing import Any as Dynamic, Callable as Callback, cast as typed_cast
from orchestrator.graph import GraphProjection as Projection

class Holder:
    projection: Projection

def passthrough(value: Projection) -> Projection:
    return value

def unresolved(value: Projection):
    return value

def use(holder: Holder, projection: Projection, callback: Callback[..., object]) -> None:
    holder.projection = projection
    holder.projection["run_state"]
    holder.projection = object()
    holder.projection["node_states"]
    holder.projection = projection
    holder = Holder()
    holder.projection["ready_nodes"]
    accepted = passthrough(projection)
    accepted["run_state"]
    typed_cast(dict[str, str], projection["node_states"])
    t.cast(dict[str, str], projection["ready_nodes"])
    dynamic: Dynamic = projection
    callback(projection)
    old: object = object()
    old = projection
    nested = [projection, (projection,), {"projection": projection}, {projection}]
    return unresolved(projection)
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH))

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("use", "run_state"),
        ("use", "run_state"),
        ("use", "node_states"),
        ("use", "ready_nodes"),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_call",
        "unsupported_binding",
        "unsupported_binding",
    ]


def test_inventory_repository_default_provider_covers_tracked_required_sites_and_excludes_untracked(
    tmp_path: Path,
) -> None:
    for relative_path in (
        "src/prompts.py",
        "src/dispatch.py",
        "src/recovery.py",
        "src/store.py",
        "untracked.py",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "from orchestrator.graph import GraphProjection\n\n"
            'def read(projection: GraphProjection):\n    projection["run_state"]\n'
        )
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "add", "src/prompts.py", "src/dispatch.py", "src/recovery.py", "src/store.py"),
        cwd=tmp_path,
        check=True,
    )

    inventory = inventory_repository(tmp_path, load_manifest(MANIFEST_PATH))

    assert [item.relative_path for item in inventory.occurrences] == [
        "src/dispatch.py",
        "src/prompts.py",
        "src/recovery.py",
        "src/store.py",
    ]


@pytest.mark.timeout(120)
def test_default_tracked_provider_reports_real_prompt_dispatch_recovery_and_store_sites() -> None:
    root = Path(__file__).parents[2]

    inventory = inventory_repository(root, load_manifest(MANIFEST_PATH))

    diagnosed_paths = {item.relative_path for item in inventory.diagnostics}
    assert {
        "src/orchestrator/graph_runtime/prompts.py",
        "src/orchestrator/graph_runtime/dispatch.py",
        "src/orchestrator/graph_runtime/recovery.py",
        "src/orchestrator/graph_runtime/store.py",
    } <= diagnosed_paths
    assert all("worktrees/" not in path and "vendor/" not in path for path in diagnosed_paths)


def test_inventory_requires_approved_origins_and_exact_projection_parameter_binding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "adversarial.py"
    source.write_text(
        """
from foreign import GraphProjection, GraphController, cast
from orchestrator.graph import GraphProjection as Projection
from typing import cast as typed_cast

def foreign(value: GraphProjection) -> None:
    value["run_state"]

def accepted(value: Projection, other: object) -> None:
    value["node_states"]

def object_parameter(value: object) -> None:
    pass

def reordered(other: object, value: Projection) -> None:
    value["ready_nodes"]

def shadows(value: Projection) -> None:
    typed_cast = lambda kind, item: item
    typed_cast(dict[str, str], value["node_states"])
    GraphController = object
    controller: GraphController = GraphController()
    controller.read_projection()["run_state"]
    GraphProjection = object
    GraphProjection(run_state=value)

def calls(value: Projection) -> None:
    accepted(value, object())
    reordered(value=value, other=object())
    object_parameter(value)
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("accepted", "node_states"),
        ("reordered", "ready_nodes"),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_call",
        "unsupported_call",
        "unsupported_call",
    ]


def test_inventory_reports_one_outer_recursive_collection_escape_at_every_boundary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collections.py"
    source.write_text(
        """
from orchestrator.graph import GraphProjection

def sink(value: object) -> None:
    pass

def returns(value: GraphProjection) -> object:
    return [{"value": (value,)}]

def boundaries(value: GraphProjection) -> None:
    plain = [{"value": (value,)}]
    annotated: object = [{"value": (value,)}]
    sink([{"value": (value,)}])
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.code) for item in inventory.diagnostics] == [
        ("returns", "unsupported_binding"),
        ("boundaries", "unsupported_binding"),
        ("boundaries", "unsupported_binding"),
        ("boundaries", "unsupported_call"),
    ]


@pytest.mark.timeout(120)
def test_checked_in_diagnostic_artifact_exactly_matches_full_repository_report() -> None:
    root = Path(__file__).parents[2]
    inventory = inventory_repository(root, load_manifest(MANIFEST_PATH))

    assert (
        diagnostic_artifact(inventory)
        == (root / "docs/graph-projection-inventory-diagnostics.md").read_text()
    )


def test_inventory_paths_resolves_only_unshadowed_exact_local_producers(tmp_path: Path) -> None:
    source = tmp_path / "local_producers.py"
    source.write_text(
        """
from orchestrator.graph import GraphProjection, initial_projection

def producer() -> GraphProjection:
    return initial_projection()

def accepted() -> None:
    first = producer()
    second = initial_projection()
    first["run_state"]
    second["node_states"]

def parameter_shadow(producer: object) -> None:
    producer()["ready_nodes"]

def assignment_shadow() -> None:
    producer = lambda: object()
    producer()["ready_nodes"]

def nested_definition_shadow() -> None:
    def producer() -> object:
        return object()
    producer()["ready_nodes"]

def imported_shadow() -> None:
    from foreign import producer
    producer()["ready_nodes"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("accepted", "run_state"),
        ("accepted", "node_states"),
    ]


def test_inventory_paths_normalizes_annotations_and_clears_local_receiver_types(
    tmp_path: Path,
) -> None:
    source = tmp_path / "annotations.py"
    source.write_text(
        """
import typing as t
from orchestrator.graph import GraphDispatchContext, GraphProjection, GraphProjectionCheckpoint, initial_projection

def make() -> GraphProjection | None:
    return initial_projection()

def use() -> None:
    context: GraphDispatchContext
    checkpoint: GraphProjectionCheckpoint
    context.graph_projection = make()
    checkpoint.projection = make()
    context.graph_projection["run_state"]
    checkpoint.projection["node_states"]
    context = object()
    checkpoint = object()
    context.graph_projection["ready_nodes"]
    checkpoint.projection["ready_nodes"]
    delayed_any: t.Any
    delayed_callable: t.Callable[..., object]
    delayed_object: object
    delayed_any = make()
    delayed_callable = make()
    delayed_object = make()
    projection = initial_projection()
    t.cast(dict[str, str], projection["run_state"])
    t = object()
    t.cast(dict[str, str], projection["node_states"])
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("use", "run_state"),
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_call",
    ]


def test_repository_mode_requires_explicit_approved_projection_origins(tmp_path: Path) -> None:
    source = tmp_path / "origins.py"
    source.write_text(
        """
def unapproved(value: GraphProjection) -> None:
    value["run_state"]

GraphProjection = object

def shadowed(value: GraphProjection) -> None:
    value["node_states"]
"""
    )

    inventory = inventory_repository(
        tmp_path,
        load_manifest(MANIFEST_PATH),
        tracked_paths=(source,),
    )

    assert not inventory.occurrences
    assert not inventory.diagnostics


def test_inventory_paths_enforces_exact_annotations_and_resolved_graph_module_symbols(
    tmp_path: Path,
) -> None:
    source = tmp_path / "remaining_task_1c.py"
    source.write_text(
        """
import orchestrator.graph as graph
from external import GraphProjection as ForeignProjection

module_projection: graph.GraphProjection = graph.initial_projection()
module_projection["run_state"]

class LocalHolder:
    projection: graph.GraphProjection

def exact_producer() -> graph.GraphProjection:
    return graph.initial_projection()

def container_producer() -> list[graph.GraphProjection]:
    return [graph.initial_projection()]

def sink(value: graph.GraphProjection) -> None:
    pass

def use() -> None:
    produced = exact_producer()
    produced["node_states"]
    container = container_producer()
    container["ready_nodes"]
    union: graph.GraphProjection | None = graph.initial_projection()
    union["ready_nodes"]
    boxed: list[graph.GraphProjection] = [graph.initial_projection()]
    context: graph.GraphDispatchContext
    context.graph_projection = graph.initial_projection()
    context.graph_projection["run_state"]
    context = object()
    context.graph_projection["ready_nodes"]
    holder: LocalHolder
    holder.projection = graph.initial_projection()
    holder.projection["node_states"]
    holder.projection = object()
    holder.projection["ready_nodes"]
    constructed = graph.GraphDispatchContext(graph_projection=graph.initial_projection())
    constructed.graph_projection["run_state"]
    sink = lambda value: None
    sink(produced)

def foreign(value: ForeignProjection) -> None:
    value["run_state"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("<module>", "run_state"),
        ("use", "node_states"),
        ("use", "run_state"),
        ("use", "node_states"),
        ("use", "run_state"),
    ]
    assert [item.qualified_function for item in inventory.diagnostics] == [
        "container_producer",
        "use",
        "use",
        "use",
        "foreign",
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_call",
        "unsupported_binding",
    ]


def test_inventory_paths_uses_effective_module_bindings_for_producers(tmp_path: Path) -> None:
    source = tmp_path / "effective_bindings.py"
    source.write_text(
        """
from orchestrator.graph import GraphProjection, initial_projection

def local_projection() -> GraphProjection:
    return initial_projection()

def initial_projection() -> object:
    return object()

from foreign import replacement as local_projection

def use() -> None:
    initial_projection()["run_state"]
    local_projection()["node_states"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert not inventory.diagnostics


def test_inventory_paths_marks_all_nested_projection_annotations_as_escapes(tmp_path: Path) -> None:
    source = tmp_path / "nested_annotations.py"
    source.write_text(
        """
from collections.abc import Callable, Mapping
from orchestrator.graph import GraphProjection, initial_projection

def use() -> None:
    dictionary: dict[str, GraphProjection] = initial_projection()
    tupled: tuple[str, GraphProjection] = initial_projection()
    mapped: Mapping[str, tuple[str, GraphProjection]] = initial_projection()
    callback: Callable[[GraphProjection], None] = initial_projection()
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
    ]


def test_inventory_paths_tracks_module_receiver_and_binding_tables(tmp_path: Path) -> None:
    source = tmp_path / "module_receivers.py"
    source.write_text(
        """
from orchestrator.graph import GraphDispatchContext, GraphProjectionCheckpoint, initial_projection

context: GraphDispatchContext
checkpoint: GraphProjectionCheckpoint
context.graph_projection = initial_projection()
checkpoint.projection = initial_projection()
context.graph_projection["run_state"]
checkpoint.projection["node_states"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("<module>", "run_state"),
        ("<module>", "node_states"),
    ]
    assert not inventory.diagnostics


def test_inventory_paths_keeps_typed_constructor_receiver_for_field_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "constructor_receiver.py"
    source.write_text(
        """
from orchestrator.graph import GraphDispatchContext, initial_projection

def use() -> None:
    context = GraphDispatchContext(graph_projection=initial_projection())
    context.graph_projection = initial_projection()
    context.graph_projection["run_state"]
    context = object()
    context.graph_projection["node_states"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("use", "run_state"),
    ]
    assert not inventory.diagnostics


def test_inventory_paths_marks_reserved_local_foreign_projection_import_unresolved(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unresolved_reserved_name.py"
    source.write_text(
        """
from foreign import Something as GraphProjection

def use(value: GraphProjection) -> None:
    value["run_state"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert [item.code for item in inventory.diagnostics] == ["unsupported_binding"]


def test_inventory_paths_uses_declaration_time_annotation_provenance(tmp_path: Path) -> None:
    source = tmp_path / "declaration_provenance.py"
    source.write_text(
        """
from orchestrator.graph import GraphProjection as Projection, initial_projection

module_value: Projection = initial_projection()
module_value["node_states"]

class Holder:
    projection: Projection

def approved_before_rebind(value: Projection) -> Projection:
    value["run_state"]
    return value

Projection = object

def rebound_before_annotation(value: Projection) -> Projection:
    value["node_states"]
    return value

from orchestrator.graph import GraphProjection as LaterProjection

def approved_after_import(value: LaterProjection) -> LaterProjection:
    value["ready_nodes"]
    return value

def read_holder(holder: Holder) -> None:
    holder.projection["run_state"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("<module>", "node_states"),
        ("approved_after_import", "ready_nodes"),
        ("approved_before_rebind", "run_state"),
        ("read_holder", "run_state"),
    ]
    assert not inventory.diagnostics


def test_inventory_paths_diagnoses_nested_function_local_unresolved_projection_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "local_unresolved_import.py"
    source.write_text(
        """
def outer() -> None:
    from foreign import ExternalProjection as GraphProjection

    def nested(value: GraphProjection) -> None:
        value["run_state"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert [item.qualified_function for item in inventory.diagnostics] == ["outer.nested"]
    assert [item.code for item in inventory.diagnostics] == ["unsupported_binding"]


def test_repository_inventory_uses_character_columns_for_non_ascii_declaration_facts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/non_ascii_declaration.py"
    source.parent.mkdir()
    source.write_text(
        """
from orchestrator.graph import GraphProjection as Projection

def before_rebind(é: Projection) -> None:
    é["run_state"]

Projection = object
"""
    )

    inventory = inventory_repository(
        tmp_path,
        load_manifest(MANIFEST_PATH),
        tracked_paths=(source,),
    )

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("before_rebind", "run_state")
    ]
    assert not inventory.diagnostics


def test_inventory_paths_uses_source_ordered_compound_statement_declarations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "compound_declarations.py"
    source.write_text(
        """
if True:
    from orchestrator.graph import GraphProjection as IfProjection

def after_if(value: IfProjection) -> None:
    value["run_state"]

try:
    from orchestrator.graph import GraphProjection as TryProjection
except ImportError:
    pass

def after_try(value: TryProjection) -> None:
    value["node_states"]

with object():
    from orchestrator.graph import GraphProjection as WithProjection

def after_with(value: WithProjection) -> None:
    value["ready_nodes"]

for _ in ():
    from orchestrator.graph import GraphProjection as ForProjection

def after_for(value: ForProjection) -> None:
    value["edges"]

while False:
    from orchestrator.graph import GraphProjection as WhileProjection

def after_while(value: WhileProjection) -> None:
    value["leases"]

match 1:
    case _:
        from orchestrator.graph import GraphProjection as MatchProjection

def after_match(value: MatchProjection) -> None:
    value["node_states"]

if True:
    import foreign.GraphProjection as ForeignProjection

def foreign(value: ForeignProjection) -> None:
    value["run_state"]

if True:
    import foreign as GraphProjection

def foreign_alias(value: GraphProjection) -> None:
    value["run_state"]

if True:
    import foreign.GraphProjection

def foreign_module(value: foreign.GraphProjection) -> None:
    value["run_state"]
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert [(item.qualified_function, item.old_field_name) for item in inventory.occurrences] == [
        ("after_for", "edges"),
        ("after_if", "run_state"),
        ("after_match", "node_states"),
        ("after_try", "node_states"),
        ("after_while", "leases"),
        ("after_with", "ready_nodes"),
    ]
    assert [item.qualified_function for item in inventory.diagnostics] == [
        "foreign",
        "foreign_alias",
        "foreign_module",
    ]
    assert [item.code for item in inventory.diagnostics] == [
        "unsupported_binding",
        "unsupported_binding",
        "unsupported_binding",
    ]


def test_inventory_paths_fails_closed_for_foreign_modules_parameter_shadows_and_missing_args(
    tmp_path: Path,
) -> None:
    source = tmp_path / "final_task_1c_boundaries.py"
    source.write_text(
        """
import foreign
import foreign as foreign_alias
from orchestrator.graph import GraphProjection

def foreign_module(value: foreign.GraphProjection) -> None:
    value["run_state"]

def foreign_module_alias(value: foreign_alias.GraphProjection) -> None:
    value["node_states"]

def outer(GraphProjection: object) -> None:
    def nested(value: GraphProjection) -> None:
        value["ready_nodes"]

def accepts(value: GraphProjection, required: object) -> None:
    pass

def calls(projection: GraphProjection) -> None:
    accepts(projection)
"""
    )

    inventory = inventory_paths((source,), load_manifest(MANIFEST_PATH), root=tmp_path)

    assert not inventory.occurrences
    assert [(item.qualified_function, item.code) for item in inventory.diagnostics] == [
        ("foreign_module", "unsupported_binding"),
        ("foreign_module_alias", "unsupported_binding"),
        ("calls", "unsupported_call"),
    ]
