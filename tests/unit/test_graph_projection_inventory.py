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
BASELINE_REVISION = "49e3f3bb03502530e52abb7304c5a31ecc5d4340"


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


def test_manifest_records_approved_baseline_and_normative_exceptions() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    fields = {field.old_name: field for field in manifest.fields}

    assert manifest.baseline_revision == BASELINE_REVISION
    assert fields["file_state_records"].new_path == "records.by_id"
    assert fields["open_proposal_blockers"].new_path is None
    assert fields["open_proposal_blockers"].disposition == "removed"
    assert fields["node_creation_payloads"].new_path == "nodes"
    assert fields["node_creation_payloads"].disposition == "removed"


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
