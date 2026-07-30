"""Referential-integrity contracts for immutable projection checkpoints."""

from copy import deepcopy
from typing import cast

import pytest

from orchestrator.graph import (
    ProjectionCheckpointIntegrityError,
    immutable_projection_from_checkpoint,
    immutable_projection_to_checkpoint,
)
from tests.unit.test_graph_projection_codec import final_projection_fixture


def _checkpoint() -> dict[str, object]:
    return immutable_projection_to_checkpoint(final_projection_fixture())


@pytest.mark.parametrize(
    ("path", "replacement", "expected_path"),
    [
        ("nodes.node-1.spec.node_id", "other-node", "nodes.node-1.spec.node_id"),
        (
            "records.ids_by_node_port.node-1.file_state",
            ["missing-record"],
            "records.ids_by_node_port.node-1.file_state[0]",
        ),
        (
            "records.summaries_by_id.record-1.record_type",
            "candidate",
            "records.summaries_by_id.record-1.record_type",
        ),
        ("topology.edges.edge-1.to_node_id", "missing-node", "topology.edges.edge-1.to_node_id"),
        ("topology.inbound_edge_ids.node-2", [], "topology.inbound_edge_ids.node-2"),
        ("scheduling.ready_node_ids", ["missing-node"], "scheduling.ready_node_ids[0]"),
        (
            "planning.session_id_by_node.node-1",
            "missing-session",
            "planning.session_id_by_node.node-1",
        ),
        ("nodes.node-1.spec.task_region_id", "missing-task", "nodes.node-1.spec.task_region_id"),
        (
            "topology.input_bindings",
            {
                "node-2": {
                    "input": {
                        "to_node_id": "node-2",
                        "to_port": "input",
                        "record_ids": ["missing-record"],
                        "bound_at_position": 1,
                    }
                }
            },
            "topology.input_bindings.node-2.input.record_ids[0]",
        ),
        (
            "verification.invalid_test_blocks_by_task",
            {"missing-task": {"position": 1}},
            "verification.invalid_test_blocks_by_task.missing-task",
        ),
        (
            "governance.pending_appeals_by_node",
            {"missing-node": True},
            "governance.pending_appeals_by_node.missing-node",
        ),
        (
            "requirements.active_version_id_by_requirement",
            {"requirement-1": "missing-version"},
            "requirements.active_version_id_by_requirement.requirement-1",
        ),
        (
            "execution.leases",
            {"lease-1": {"lease_id": "lease-1", "state": "active", "node_id": "missing-node"}},
            "execution.leases.lease-1.node_id",
        ),
    ],
)
def test_checkpoint_reports_each_independent_invalid_reference(
    path: str, replacement: object, expected_path: str
) -> None:
    raw = _checkpoint()
    cursor: object = raw
    parts = path.split(".")
    for part in parts[:-1]:
        assert isinstance(cursor, dict)
        cursor = cursor[part]
    assert isinstance(cursor, dict)
    cursor[parts[-1]] = replacement

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert expected_path in {diagnostic.path for diagnostic in raised.value.diagnostics}


def test_integrity_reports_sorted_complete_diagnostics_without_repairing_input() -> None:
    raw = _checkpoint()
    nodes = cast(dict[str, object], raw["nodes"])
    node = cast(dict[str, object], nodes["node-1"])
    cast(dict[str, object], node["spec"])["node_id"] = "wrong"
    topology = cast(dict[str, object], raw["topology"])
    edges = cast(dict[str, object], topology["edges"])
    cast(dict[str, object], edges["edge-1"])["to_node_id"] = "missing"
    before = deepcopy(raw)

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    diagnostics = raised.value.diagnostics
    assert tuple(diagnostic.path for diagnostic in diagnostics) == tuple(
        sorted(diagnostic.path for diagnostic in diagnostics)
    )
    assert {diagnostic.path for diagnostic in diagnostics} >= {
        "nodes.node-1.spec.node_id",
        "topology.edges.edge-1.to_node_id",
    }
    assert raw == before


def test_node_runtime_candidate_resolves_to_candidate_entity_not_record() -> None:
    raw = _checkpoint()
    tasks = cast(dict[str, object], raw["tasks"])
    task = cast(dict[str, object], tasks["task-1"])
    task["candidates"] = [{"candidate_id": "candidate-1", "attempt_number": 1, "position": 1}]
    nodes = cast(dict[str, object], raw["nodes"])
    node = cast(dict[str, object], nodes["node-1"])
    cast(dict[str, object], node["runtime"])["candidate_id"] = "candidate-1"

    assert (
        immutable_projection_from_checkpoint(raw).nodes["node-1"].runtime.candidate_id
        == "candidate-1"
    )


def test_secondary_indexes_reject_extra_empty_keys() -> None:
    raw = _checkpoint()
    records = cast(dict[str, object], raw["records"])
    indexes = cast(dict[str, object], records["ids_by_node_port"])
    cast(dict[str, object], indexes["node-1"])["unused"] = []
    topology = cast(dict[str, object], raw["topology"])
    cast(dict[str, object], topology["inbound_edge_ids"])["node-1"] = []

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert {diagnostic.path for diagnostic in raised.value.diagnostics} >= {
        "records.ids_by_node_port.node-1.unused",
        "topology.inbound_edge_ids.node-1",
    }
