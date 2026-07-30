"""Referential-integrity contracts for immutable projection checkpoints."""

from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal, cast, get_args, get_origin

import pytest
from pydantic import StrictStr

from orchestrator.graph import (
    PROJECTED_RECORD_TYPES,
    ImmutableGraphProjection,
    ProjectionModel,
    ProjectedRecord,
    ProjectionCheckpointIntegrityError,
    ProjectionRelationPolicyError,
    ProjectionRelationResolverDispatcher,
    RelationPolicy,
    discover_projection_identifier_paths,
    immutable_projection_from_checkpoint,
    immutable_projection_to_checkpoint,
    load_projection_relation_policy,
    projection_relation_policy_catalog,
    projection_record_relation_policy_catalog,
    projection_relation_policy_gaps,
    projection_relation_resolver_call_sites,
    projection_relation_validation_paths,
)
from orchestrator.graph.projection_collections import FrozenJsonValue, FrozenMap
from tests.unit.test_graph_projection_codec import final_projection_fixture


type RecursiveDiscoveryAlias = RecursiveDiscoveryAlias | FrozenJsonValue


class RecursiveDiscoveryValue(ProjectionModel):
    parent: "RecursiveDiscoveryValue | None" = None
    linked_node_id: StrictStr | None = None


class DiscoveryFixture(ProjectionModel):
    nested: FrozenMap[StrictStr, FrozenMap[StrictStr, RecursiveDiscoveryValue]]
    record_ids_by_node: FrozenMap[StrictStr, tuple[StrictStr, ...]]
    session_id_by_node: FrozenMap[StrictStr, StrictStr]
    region_label_by_node: FrozenMap[StrictStr, StrictStr]
    ports: FrozenMap[StrictStr, StrictStr]
    heterogeneous: tuple[StrictStr, RecursiveDiscoveryValue, FrozenJsonValue]
    opaque: FrozenJsonValue
    recursive_alias: RecursiveDiscoveryAlias


class NestedRecordIndexDiscoveryFixture(ProjectionModel):
    ids_by_node_port: FrozenMap[StrictStr, FrozenMap[StrictStr, tuple[StrictStr, ...]]]


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


@pytest.mark.parametrize(
    ("section", "field", "replacement", "expected_path", "expected_reason"),
    [
        (
            "topology",
            "input_bindings",
            {"missing-node": {}},
            "topology.input_bindings.missing-node",
            "references missing node 'missing-node'",
        ),
        (
            "usage",
            "tokens_by_node",
            {"missing-node": 1},
            "usage.tokens_by_node.missing-node",
            "references missing node 'missing-node'",
        ),
        (
            "verification",
            "passed_results_by_record_id",
            {
                "missing-record": {
                    "record_id": "missing-record",
                    "node_id": "node-1",
                    "candidate_id": "candidate-1",
                    "task_region_id": "task-1",
                }
            },
            "verification.passed_results_by_record_id.missing-record",
            "references missing record 'missing-record'",
        ),
        (
            "verification",
            "failed_candidate_ids",
            {"missing-candidate": True},
            "verification.failed_candidate_ids.missing-candidate",
            "references missing candidate 'missing-candidate'",
        ),
    ],
)
def test_represented_map_keys_preserve_concrete_reference_diagnostics(
    section: str,
    field: str,
    replacement: object,
    expected_path: str,
    expected_reason: str,
) -> None:
    raw = _checkpoint()
    container = cast(dict[str, object], raw[section])
    container[field] = replacement

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        immutable_projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[expected_path] == (
        expected_reason
    )


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


def test_identifier_path_discovery_exactly_matches_reviewed_grouped_and_record_policies() -> None:
    union, metadata = get_args(ProjectedRecord)
    assert get_origin(ProjectedRecord) is Annotated
    assert metadata
    assert set(get_args(union)) == set(PROJECTED_RECORD_TYPES)

    catalog = projection_relation_policy_catalog()
    record_catalog = projection_record_relation_policy_catalog()
    discovered = discover_projection_identifier_paths(ImmutableGraphProjection)

    assert discovered == set(catalog) | set(record_catalog)
    assert projection_relation_policy_gaps(ImmutableGraphProjection) == frozenset()
    assert {
        "records.by_id.*.value.artifact_id",
        "records.by_id.*.base_snapshot_id",
        "records.by_id.*.patch_bundle_id",
        "records.by_id.*.value.execution_id",
        "records.by_id.*.value.command_id",
        "records.by_id.*.git.commit_sha",
    } <= set(record_catalog)
    resolver_paths = {
        path
        for policy_catalog in (catalog, record_catalog)
        for path, policy in policy_catalog.items()
        if policy.validation == "resolver"
    }
    assert resolver_paths == projection_relation_validation_paths()
    assert all(
        policy.validation == policy.family
        for policy_catalog in (catalog, record_catalog)
        for policy in policy_catalog.values()
        if policy.family in {"external", "derived"}
    )
    assert all(
        policy.rationale.strip()
        for policy in catalog.values()
        if policy.family in {"external", "derived"}
    )


def test_identifier_path_parity_reports_a_new_identifier_field_without_policy() -> None:
    class ProjectionWithUnreviewedIdentifier(ProjectionModel):
        new_integration_id: StrictStr

    assert projection_relation_policy_gaps(ProjectionWithUnreviewedIdentifier) == frozenset(
        {"new_integration_id"}
    )


def test_identifier_policy_keeps_external_and_derived_identifier_families_explicit() -> None:
    catalog = projection_relation_policy_catalog()
    record_catalog = projection_record_relation_policy_catalog()

    assert catalog["nodes.*.spec.command_definition_id"].family == "external"
    assert "command definition" in catalog["nodes.*.spec.command_definition_id"].rationale
    assert catalog["nodes.*.key"].family == "derived"
    assert "node map key" in catalog["nodes.*.key"].rationale
    assert record_catalog["records.by_id.*.git.ref"].family == "external"
    assert "git" in record_catalog["records.by_id.*.git.ref"].rationale
    assert record_catalog["records.by_id.*.value.source"].family == "external"
    assert "external" in record_catalog["records.by_id.*.value.source"].rationale


def test_identifier_discovery_observes_roles_without_treating_structural_keys_as_ids() -> None:
    assert discover_projection_identifier_paths(DiscoveryFixture) == {
        "nested.*.*.linked_node_id",
        "record_ids_by_node.*.key",
        "record_ids_by_node.*.value.*",
        "session_id_by_node.*.key",
        "session_id_by_node.*.value",
        "region_label_by_node.*.key",
        "heterogeneous.*.linked_node_id",
    }


def test_identifier_discovery_includes_nested_ids_by_node_port_values_not_port_keys() -> None:
    assert discover_projection_identifier_paths(NestedRecordIndexDiscoveryFixture) == {
        "ids_by_node_port.*.key",
        "ids_by_node_port.*.value.*.value.*",
    }


def test_relation_resolver_dispatcher_requires_a_matching_resolver_policy() -> None:
    policy = next(
        item
        for item in projection_relation_policy_catalog().values()
        if item.validation == "resolver" and item.family == "node"
    )
    dispatcher = ProjectionRelationResolverDispatcher(
        policies={policy.path: policy},
        validation_paths=frozenset({policy.path}),
        resolve_node=lambda value, path: None,
        resolve_task=lambda value, path: None,
        resolve_record=lambda value, path: None,
        resolve_candidate=lambda value, path: None,
        resolve_requirement=lambda value, path: None,
        resolve_revision=lambda value, path: None,
        resolve_support=lambda value, path: None,
        resolve_lease=lambda value, path: None,
        resolve_cleanup=lambda value, path: None,
        resolve_edge=lambda value, path: None,
        resolve_session=lambda value, path: None,
    )

    dispatcher.resolve(policy.path, "node", "nodes.node-1.runtime.node_id", "node-1")
    with pytest.raises(ValueError, match="unknown relation policy"):
        dispatcher.resolve("unknown.path", "node", "unknown.path", "node-1")
    with pytest.raises(ValueError, match="expects family 'node'"):
        dispatcher.resolve(policy.path, "task", "nodes.node-1.runtime.node_id", "node-1")


def test_relation_resolver_dispatcher_rejects_policy_outside_explicit_validation_paths() -> None:
    policy = next(
        item
        for item in projection_relation_policy_catalog().values()
        if item.validation == "resolver" and item.family == "node"
    )
    dispatcher = ProjectionRelationResolverDispatcher(
        policies={policy.path: policy},
        validation_paths=frozenset(),
        resolve_node=lambda value, path: None,
        resolve_task=lambda value, path: None,
        resolve_record=lambda value, path: None,
        resolve_candidate=lambda value, path: None,
        resolve_requirement=lambda value, path: None,
        resolve_revision=lambda value, path: None,
        resolve_support=lambda value, path: None,
        resolve_lease=lambda value, path: None,
        resolve_cleanup=lambda value, path: None,
        resolve_edge=lambda value, path: None,
        resolve_session=lambda value, path: None,
    )

    with pytest.raises(ValueError, match="not an explicit validation path"):
        dispatcher.resolve(policy.path, "node", "nodes.node-1.runtime.node_id", "node-1")


class _ResolverCalls:
    def __init__(self) -> None:
        self.values: list[tuple[str | None, str]] = []

    def __call__(self, value: str | None, path: str) -> None:
        self.values.append((value, path))


def _runtime_dispatcher(
    policies: dict[str, RelationPolicy],
    validation_paths: frozenset[str],
    calls: _ResolverCalls,
) -> ProjectionRelationResolverDispatcher:
    return ProjectionRelationResolverDispatcher(
        policies=policies,
        validation_paths=validation_paths,
        resolve_node=calls,
        resolve_task=calls,
        resolve_record=calls,
        resolve_candidate=calls,
        resolve_requirement=calls,
        resolve_revision=calls,
        resolve_support=calls,
        resolve_lease=calls,
        resolve_cleanup=calls,
        resolve_edge=calls,
        resolve_session=calls,
    )


def test_runtime_dispatcher_rejects_unknown_path_without_calling_resolver() -> None:
    policy = projection_relation_policy_catalog()["nodes.*.spec.node_id"]
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher({policy.path: policy}, frozenset({policy.path}), calls)

    with pytest.raises(ProjectionRelationPolicyError) as raised:
        dispatcher.resolve_runtime("node", "nodes.node-1.unknown_id", "node-1")

    assert str(raised.value) == (
        "expected one relation policy for runtime path 'nodes.node-1.unknown_id', found []"
    )
    assert calls.values == []


def test_runtime_dispatcher_rejects_ambiguous_path_without_calling_resolver() -> None:
    catalog = projection_relation_policy_catalog()
    paths = (
        "planning.successor_by_node.*.key",
        "planning.successor_by_node.*.value",
    )
    policies = {path: catalog[path] for path in paths}
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher(policies, frozenset(paths), calls)

    with pytest.raises(ProjectionRelationPolicyError) as raised:
        dispatcher.resolve_runtime("node", "planning.successor_by_node.node-1", "node-2")

    assert str(raised.value) == (
        "expected one relation policy for runtime path "
        "'planning.successor_by_node.node-1', found "
        "['planning.successor_by_node.*.key', 'planning.successor_by_node.*.value']"
    )
    assert calls.values == []


@pytest.mark.parametrize(
    ("policy_path", "family", "validation_paths", "message"),
    [
        (
            "nodes.*.spec.node_id",
            "task",
            frozenset({"nodes.*.spec.node_id"}),
            "relation policy 'nodes.*.spec.node_id' expects family 'node', got 'task'",
        ),
        (
            "nodes.*.spec.command_definition_id",
            "node",
            frozenset(),
            "relation policy 'nodes.*.spec.command_definition_id' is not a resolver policy",
        ),
        (
            "nodes.*.key",
            "node",
            frozenset(),
            "relation policy 'nodes.*.key' is not a resolver policy",
        ),
        (
            "nodes.*.spec.node_id",
            "node",
            frozenset(),
            "relation policy 'nodes.*.spec.node_id' is not an explicit validation path",
        ),
    ],
)
def test_runtime_dispatcher_enforces_matched_policy_before_calling_resolver(
    policy_path: str,
    family: Literal["node", "task"],
    validation_paths: frozenset[str],
    message: str,
) -> None:
    policy = projection_relation_policy_catalog()[policy_path]
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher({policy.path: policy}, validation_paths, calls)
    diagnostic_path = policy_path.replace("*", "node-1").removesuffix(".key")

    with pytest.raises(ProjectionRelationPolicyError) as raised:
        dispatcher.resolve_runtime(family, diagnostic_path, "node-1")

    assert str(raised.value) == message
    assert calls.values == []


def test_represented_map_keys_are_resolver_policies() -> None:
    catalog = projection_relation_policy_catalog()
    expected = {
        "execution.environment_failures_by_task.*.key": "task",
        "governance.approval_decisions_by_node.*.key": "node",
        "governance.authority_decisions_by_node.*.key": "node",
        "governance.configured_gates_by_task.*.key": "task",
        "governance.decision_requests_by_node.*.key": "node",
        "governance.gate_decisions_by_task.*.key": "task",
        "governance.node_gate_decisions.*.key": "node",
        "governance.oversight_decisions_by_node.*.key": "node",
        "governance.pending_appeals_by_node.*.key": "node",
        "planning.accepted_patch_ids_by_node.*.key": "node",
        "planning.generation_by_node.*.key": "node",
        "planning.latest_no_successor_patch_id_by_node.*.key": "node",
        "planning.no_successor_patch_ids_by_node.*.key": "node",
        "planning.region_label_by_node.*.key": "node",
        "planning.session_id_by_node.*.key": "node",
        "planning.successor_by_node.*.key": "node",
        "topology.input_bindings.*.key": "node",
        "usage.recorded_keys.*.key": "node",
        "usage.tokens_by_node.*.key": "node",
        "verification.check_results_by_node.*.key": "node",
        "verification.failed_candidate_ids.*.key": "candidate",
        "verification.failed_results_by_record_id.*.key": "record",
        "verification.invalid_test_blocks_by_task.*.key": "task",
        "verification.passed_results_by_record_id.*.key": "record",
        "verification.recovery_nodes_by_record_id.*.key": "record",
        "verification.verdicts_by_node.*.key": "node",
    }

    assert {path: policy.family for path, policy in catalog.items() if path in expected} == expected
    assert all(catalog[path].validation == "resolver" for path in expected)
    assert expected.keys() <= projection_relation_validation_paths()


def test_resolver_call_site_tokens_exactly_cover_static_resolver_policies() -> None:
    catalog = projection_relation_policy_catalog() | projection_record_relation_policy_catalog()
    expected = {path for path, policy in catalog.items() if policy.validation == "resolver"}

    assert projection_relation_resolver_call_sites() == frozenset(expected)


def test_relation_policy_is_a_packaged_graph_resource() -> None:
    resource = files("orchestrator.graph").joinpath("_projection_relation_policy.yaml")

    assert resource.is_file()
    assert "policies:" in resource.read_text(encoding="utf-8")


def _write_policy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """policies:
  - {path: nodes.*.spec.node_id, scope: grouped, family: node, rationale: canonical node, validation: resolver}
  - {path: nodes.*.spec.node_id, scope: grouped, family: node, rationale: duplicate node, validation: resolver}
validation_paths: [nodes.*.spec.node_id]
""",
            "duplicate policy path",
        ),
        (
            """policies:
  - {path: tasks.*.key, scope: grouped, family: derived, rationale: task map key, validation: derived}
  - {path: nodes.*.key, scope: grouped, family: derived, rationale: node map key, validation: derived}
validation_paths: []
""",
            "policies must be sorted",
        ),
        (
            """policies:
  - {path: nodes.*.key, scope: grouped, family: derived, rationale: node map key, validation: derived, surprise: true}
validation_paths: []
""",
            "Extra inputs are not permitted",
        ),
        (
            """policies:
  - {path: nodes.*.spec.node_id, scope: grouped, family: node, rationale: unknown external classification, validation: external}
validation_paths: []
""",
            "external validation must use external family",
        ),
        (
            """policies:
  - {path: "nodes.[bad]", scope: grouped, family: node, rationale: malformed path, validation: resolver}
validation_paths: ["nodes.[bad]"]
""",
            "String should match pattern",
        ),
        (
            """policies:
  - {path: nodes.*.spec.node_id, scope: grouped, family: node, rationale: canonical node, validation: resolver}
  - {path: tasks.*.key, scope: grouped, family: derived, rationale: task map key, validation: derived}
validation_paths: [nodes.*.spec.node_id, nodes.*.spec.node_id]
""",
            "duplicate validation path",
        ),
        (
            """policies:
  - {path: nodes.*.spec.node_id, scope: grouped, family: node, rationale: canonical node, validation: resolver}
  - {path: tasks.*.key, scope: grouped, family: derived, rationale: task map key, validation: derived}
validation_paths: [tasks.*.key, nodes.*.spec.node_id]
""",
            "validation paths must be sorted",
        ),
    ],
)
def test_static_relation_policy_loader_rejects_invalid_checked_data(
    tmp_path: Path, body: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load_projection_relation_policy(_write_policy(tmp_path, body))
