from pathlib import Path

from pydantic import ValidationError
import pytest

from orchestrator.graph import (
    GraphProjection,
    NodeCreationProjection,
    initial_projection,
    resource_claims_for_node,
)
from scripts.graph_projection_inventory import load_manifest


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
