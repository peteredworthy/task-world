"""Referential-integrity contracts for immutable projection checkpoints."""

from copy import deepcopy
from typing import Annotated, cast, get_args, get_origin

import pytest

from orchestrator.graph import (
    PROJECTED_RECORD_TYPES,
    ProjectedRecord,
    ProjectionCheckpointIntegrityError,
    immutable_projection_from_checkpoint,
    immutable_projection_to_checkpoint,
    projection_relation_policy_catalog,
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


def test_matching_candidate_record_is_a_reference_to_the_task_candidate() -> None:
    raw = _checkpoint()
    records = cast(dict[str, object], raw["records"])
    by_id = cast(dict[str, object], records["by_id"])
    by_id["candidate-record-1"] = {
        "record_id": "candidate-record-1",
        "record_type": "candidate",
        "record_kind": "output",
        "producer_node_id": "node-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": "candidate-1",
        "task_region_id": "task-1",
        "value": {"summary": "candidate"},
    }
    cast(dict[str, object], records["ids_by_node_port"])["node-1"]["candidate"] = [
        "candidate-record-1"
    ]
    cast(dict[str, object], records["summaries_by_id"])["candidate-record-1"] = {
        "record_id": "candidate-record-1",
        "record_type": "candidate",
        "record_kind": "output",
        "schema": "ImplementationCandidate",
        "producer_node_id": "node-1",
        "producer_port": "candidate",
    }

    assert immutable_projection_from_checkpoint(raw).records.by_id[
        "candidate-record-1"
    ].record_id == ("candidate-record-1")


def test_candidate_record_must_reference_the_canonical_candidates_task() -> None:
    raw = _checkpoint()
    records = cast(dict[str, object], raw["records"])
    by_id = cast(dict[str, object], records["by_id"])
    by_id["candidate-record-1"] = {
        "record_id": "candidate-record-1",
        "record_type": "candidate",
        "record_kind": "output",
        "producer_node_id": "node-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": "candidate-1",
        "task_region_id": "task-2",
        "value": {"summary": "candidate"},
    }
    tasks = cast(dict[str, object], raw["tasks"])
    tasks["task-2"] = {"state": "active"}
    cast(dict[str, object], records["ids_by_node_port"])["node-1"]["candidate"] = [
        "candidate-record-1"
    ]
    cast(dict[str, object], records["summaries_by_id"])["candidate-record-1"] = {
        "record_id": "candidate-record-1",
        "record_type": "candidate",
        "record_kind": "output",
        "schema": "ImplementationCandidate",
        "producer_node_id": "node-1",
        "producer_port": "candidate",
    }

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[
        "records.by_id.candidate-record-1.candidate_id"
    ] == "must resolve to a candidate for task 'task-2'"


@pytest.mark.parametrize(
    ("mutate", "expected_path", "expected_reason"),
    [
        (
            lambda raw: cast(dict[str, object], raw["nodes"])["node-1"]["runtime"].update(
                {"candidate_id": "missing-candidate"}
            ),
            "nodes.node-1.runtime.candidate_id",
            "references missing candidate 'missing-candidate'",
        ),
        (
            lambda raw: cast(dict[str, object], raw["tasks"])["task-2"].update(
                {
                    "candidates": [
                        {"candidate_id": "candidate-1", "attempt_number": 2, "position": 2}
                    ]
                }
            ),
            "tasks.task-2.candidates[0].candidate_id",
            "duplicates canonical candidate 'candidate-1' declared at tasks.task-1.candidates[0].candidate_id",
        ),
    ],
)
def test_candidate_relations_resolve_only_to_unique_task_candidates(
    mutate: object, expected_path: str, expected_reason: str
) -> None:
    raw = _checkpoint()
    if expected_path.startswith("tasks.task-2"):
        cast(dict[str, object], raw["tasks"])["task-2"] = {"state": "active"}
    cast(object, mutate)(raw)

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[
        expected_path
    ] == expected_reason


@pytest.mark.parametrize(
    ("mutate", "expected_path", "expected_reason"),
    [
        (
            lambda raw: cast(dict[str, object], raw["requirements"])["revisions_by_id"].update(
                {
                    "revision-2": {
                        "requirement_id": "requirement-2",
                        "version_id": "revision-2",
                        "previous_version_id": "revision-1",
                        "change_classification": "revision",
                        "requires_authority": False,
                        "position": 2,
                        "validation_strengthening": False,
                    }
                }
            ),
            "requirements.revisions_by_id.revision-2.previous_version_id",
            "must reference a revision for the same requirement",
        ),
        (
            lambda raw: cast(dict[str, object], raw["records"])["by_id"]["record-2"].update(
                {
                    "record_id": "record-2",
                    "record_type": "verification_report",
                    "record_kind": "verification",
                    "producer_node_id": "node-1",
                    "candidate_id": "candidate-1",
                    "outcome": "passed",
                    "value": {
                        "outcome": "passed",
                        "grades": [{"requirement_id": "missing", "grade": "A"}],
                    },
                }
            ),
            "records.by_id.record-2.value.grades[0].requirement_id",
            "references missing requirement 'missing'",
        ),
    ],
)
def test_requirement_relations_enforce_parent_identity_and_grade_membership(
    mutate: object, expected_path: str, expected_reason: str
) -> None:
    raw = _checkpoint()
    if expected_path.startswith("records.by_id.record-2"):
        records = cast(dict[str, object], raw["records"])
        cast(dict[str, object], records["by_id"])["record-2"] = {}
        cast(dict[str, object], records["ids_by_node_port"])["node-1"]["verification_report"] = [
            "record-2"
        ]
        cast(dict[str, object], records["summaries_by_id"])["record-2"] = {
            "record_id": "record-2",
            "record_type": "verification_report",
            "record_kind": "verification",
            "schema": "VerificationReport",
            "producer_node_id": "node-1",
            "producer_port": "verification_report",
        }
    cast(object, mutate)(raw)

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[
        expected_path
    ] == expected_reason


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


@pytest.mark.parametrize(
    ("path", "value", "expected_path", "expected_reason"),
    [
        (
            "records.by_id.record-1.cleanup_id",
            "missing-cleanup",
            "records.by_id.record-1.cleanup_id",
            "references missing cleanup request 'missing-cleanup'",
        ),
        (
            "nodes.node-1.spec.authority_request_record",
            {
                "record_id": "missing-authority-record",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "node-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["graph_write"],
                    "target_node_id": "node-2",
                    "reason": "needed",
                },
            },
            "nodes.node-1.spec.authority_request_record.record_id",
            "references missing record 'missing-authority-record'",
        ),
    ],
)
def test_integrity_validates_record_and_node_envelope_cross_family_references(
    path: str, value: object, expected_path: str, expected_reason: str
) -> None:
    raw = _checkpoint()
    cursor: object = raw
    parts = path.split(".")
    for part in parts[:-1]:
        assert isinstance(cursor, dict)
        cursor = cursor[part]
    assert isinstance(cursor, dict)
    cursor[parts[-1]] = value

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    diagnostics = {item.path: item.reason for item in raised.value.diagnostics}
    assert diagnostics[expected_path] == expected_reason


@pytest.mark.parametrize(
    ("path", "replacement", "expected_path", "expected_reason"),
    [
        (
            "tasks.task-1.candidates",
            [
                {
                    "candidate_id": "candidate-1",
                    "attempt_number": 1,
                    "position": 1,
                    "file_state_record_ids": ["missing"],
                }
            ],
            "tasks.task-1.candidates[0].file_state_record_ids[0]",
            "references missing record 'missing'",
        ),
        (
            "verification.verdicts_by_node.node-1.candidate_id",
            "missing-candidate",
            "verification.verdicts_by_node.node-1.candidate_id",
            "references missing candidate 'missing-candidate'",
        ),
        (
            "verification.check_results_by_node.node-1.evaluated_record_ids",
            ["missing-record"],
            "verification.check_results_by_node.node-1.evaluated_record_ids[0]",
            "references missing record 'missing-record'",
        ),
        (
            "planning.sessions.session-1.carryover_record_id",
            "missing-record",
            "planning.sessions.session-1.carryover_record_id",
            "references missing record 'missing-record'",
        ),
        (
            "requirements.support_by_id.support-1.evidence_id",
            "missing-record",
            "requirements.support_by_id.support-1.evidence_id",
            "references missing record 'missing-record'",
        ),
        (
            "execution.leases.lease-1.session_id",
            "missing-session",
            "execution.leases.lease-1.session_id",
            "references missing session 'missing-session'",
        ),
        (
            "execution.environment_failures_by_task.task-1.task_region_id",
            "task-2",
            "execution.environment_failures_by_task.task-1.task_region_id",
            "must equal outer task key 'task-1'",
        ),
        (
            "execution.callback_events_by_key.callback-1.idempotency_key",
            "other-callback",
            "execution.callback_events_by_key.callback-1.idempotency_key",
            "must equal map key 'callback-1'",
        ),
    ],
)
def test_integrity_reports_exact_cross_family_relation_diagnostics(
    path: str, replacement: object, expected_path: str, expected_reason: str
) -> None:
    raw = _checkpoint()
    cursor: object = raw
    parts = path.split(".")
    for part in parts[:-1]:
        assert isinstance(cursor, dict)
        cursor = cursor[part]
    assert isinstance(cursor, dict)
    cursor[parts[-1]] = replacement
    if path == "execution.environment_failures_by_task.task-1.task_region_id":
        cast(dict[str, object], raw["tasks"])["task-2"] = {"state": "active"}

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[
        expected_path
    ] == expected_reason


def test_public_relation_catalog_covers_each_concrete_record_and_reviewed_id_family() -> None:
    union, metadata = get_args(ProjectedRecord)
    assert get_origin(ProjectedRecord) is Annotated
    assert metadata
    assert set(get_args(union)) == set(PROJECTED_RECORD_TYPES)

    catalog = projection_relation_policy_catalog()
    assert {
        "records.*.git.ref",
        "records.*.value.command_id",
        "records.*.value.execution_id",
        "execution.callback_events_by_key.*.idempotency_key",
        "governance.authority_revision_blockers.*.support_ids",
        "planning.sessions.*.carryover_record_id",
        "topology.input_bindings.*.*.record_ids",
        "verification.*_results_by_record_id.*.record_id",
    } <= set(catalog)
    assert set(catalog.values()) >= {
        "node",
        "task",
        "record",
        "candidate",
        "revision",
        "support",
        "lease",
        "cleanup",
        "edge",
        "session",
        "external",
    }
