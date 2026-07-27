from pathlib import Path

from pydantic import ValidationError
import pytest

from orchestrator.graph import (
    GraphProjection,
    NodeCreationProjection,
    initial_projection,
    resource_claims_for_node,
)
from scripts.graph_projection_inventory import collect_source, load_manifest, occurrence_id


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

    assert not inventory.diagnostics
    assert len(inventory.occurrences) == 19
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
        "untyped_escape",
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
    projection.get("run_state", None)
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
