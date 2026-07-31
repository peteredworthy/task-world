"""Referential-integrity contracts for immutable projection checkpoints."""

from copy import deepcopy
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args, get_origin

import pytest
from pydantic import BaseModel, StrictStr

import orchestrator.graph as graph
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    PROJECTED_RECORD_TYPES,
    GraphProjection,
    ProjectionModel,
    ProjectedRecord,
    ProjectionCheckpointIntegrityError,
    ProjectionRelationPolicyError,
    ProjectionRelationResolverDispatcher,
    RelationPolicy,
    build_projection,
    discover_projection_identifier_paths,
    projection_from_checkpoint,
    projection_to_checkpoint,
    load_projection_relation_policy,
    projection_relation_policy_catalog,
    projection_record_relation_policy_catalog,
    projection_relation_policy_gaps,
    projection_relation_validation_paths,
    validate_projection_integrity,
    map_delete,
    map_set,
)
from orchestrator.graph import FrozenJsonValue, FrozenMap
from tests.unit.test_graph_projection_codec import final_projection_fixture
from tests.unit.test_output_record_event_payloads import OUTPUT_RECORD_CASES


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
    return projection_to_checkpoint(final_projection_fixture())


def test_checkpoint_round_trip_accepts_lease_observed_without_grant() -> None:
    event = EventEnvelope(
        event_id="lease-suspended-1",
        run_id="run-1",
        position=1,
        event_type="lease_suspended",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload={"lease_id": "lease-1"},
    )
    projection = build_projection([event])
    checkpoint = projection_to_checkpoint(projection)

    assert checkpoint["execution"]["leases"] == {
        "lease-1": {"lease_id": "lease-1", "state": "suspended"}
    }
    assert projection_from_checkpoint(checkpoint) == projection


@pytest.mark.parametrize("case", ("non-ready", "duplicate", "missing", "out-of-order"))
def test_checkpoint_ready_index_must_exactly_match_canonical_ready_nodes(case: str) -> None:
    raw = _checkpoint()
    nodes = cast(dict[str, Any], raw["nodes"])
    scheduling = cast(dict[str, Any], raw["scheduling"])
    if case == "non-ready":
        nodes["node-1"]["runtime"]["state"] = "planned"
    elif case == "duplicate":
        scheduling["ready_node_ids"] = ["node-1", "node-1"]
    elif case == "missing":
        scheduling["ready_node_ids"] = []
    else:
        nodes["node-2"]["runtime"] = {"state": "ready"}
        scheduling["ready_node_ids"] = ["node-2", "node-1"]

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        projection_from_checkpoint(raw)

    assert any(
        diagnostic.path == "scheduling.ready_node_ids"
        and diagnostic.reason == "must exactly match ready nodes in canonical order"
        for diagnostic in raised.value.diagnostics
    )


def test_relation_call_site_alias_is_not_public_integrity_evidence() -> None:
    assert not hasattr(graph, "projection_relation_resolver_call_sites")


def complete_projection_fixture() -> GraphProjection:
    """A valid checkpoint containing every concrete projected-record visitor type."""
    raw = _checkpoint()
    records = cast(dict[str, Any], raw["records"])
    by_id: dict[str, dict[str, Any]] = {}
    for record_type, source in OUTPUT_RECORD_CASES.items():
        if record_type in {"gap_classification", "gap_plan"}:
            continue
        item = deepcopy(source)
        item["producer_node_id"] = "node-1"
        if item["record_type"] == "authority_request_record":
            item["value"]["target_region_id"] = "task-1"
            item["value"]["target_node_id"] = "node-1"
        if item["record_type"] == "requirement_record":
            item["value"].update(id="requirement-1", version="revision-1")
        if item["record_type"] == "classified_gap":
            item["value"]["task_region_id"] = "task-1"
        by_id[item["record_id"]] = item
    by_id = dict(sorted(by_id.items()))
    records["by_id"] = by_id
    ids_by_port: dict[str, list[str]] = {}
    for record_id, item in by_id.items():
        ids_by_port.setdefault(item["port"], []).append(record_id)
    records["ids_by_node_port"] = {
        "node-1": {port: sorted(ids) for port, ids in ids_by_port.items()}
    }
    records["summaries_by_id"] = {
        record_id: {
            "record_id": record_id,
            "record_type": item["record_type"],
            "record_kind": item["record_kind"],
            "schema": item["schema"],
            "producer_node_id": "node-1",
            "producer_port": item["port"],
        }
        for record_id, item in by_id.items()
    }

    record_id_by_type = {item["record_type"]: record_id for record_id, item in by_id.items()}
    referenced_record_id = record_id_by_type["file_state"]
    for item in by_id.values():
        record_type = item["record_type"]
        if record_type in {"analysis_summary", "artifact_reference", "join_result"}:
            item["value"]["source_record_ids"] = [referenced_record_id]
        if record_type == "candidate":
            item.update(
                file_state_record_id=referenced_record_id,
                file_state_record_ids=[referenced_record_id],
                supersedes_task_region_id="task-1",
                supersedes_task_region_ids=["task-1"],
            )
            item["value"].update(
                file_state_record_id=referenced_record_id,
                file_state_record_ids=[referenced_record_id],
                requirements_addressed=["requirement-1"],
            )
        if record_type == "check_result":
            item.update(
                candidate_record_id=referenced_record_id,
                candidate_record_ids=[referenced_record_id],
                file_state_record_ids=[referenced_record_id],
                verification_report_record_ids=[referenced_record_id],
                evaluated_record_ids=[referenced_record_id],
            )
            item["value"].update(
                candidate_record_ids=[referenced_record_id],
                cited_record_id=referenced_record_id,
                evaluated_record_ids=[referenced_record_id],
                file_state_record_ids=[referenced_record_id],
                reused_verification_record_id=referenced_record_id,
                verification_report_record_ids=[referenced_record_id],
            )
        if record_type == "file_state":
            item.update(
                candidate_id="candidate-1",
                cleanup_id="cleanup-1",
                superseded_by_record_id=referenced_record_id,
                supersedes_record_id=referenced_record_id,
                acceptance_identity="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        if record_type == "failure_record":
            item["value"]["lease_id"] = "lease-1"
        if record_type == "graph_patch_proposal":
            item["value"].update(
                proposed_by_node_id="node-1", rationale_record_id=referenced_record_id
            )
        if record_type == "requirement_record":
            item["value"]["supersedes"] = "revision-0"
        if record_type == "verification_report":
            item.update(
                candidate_record_id=referenced_record_id,
                candidate_record_ids=[referenced_record_id],
                file_state_record_ids=[referenced_record_id],
                evaluated_record_ids=[referenced_record_id],
            )
            item["value"]["grades"] = [{"requirement_id": "requirement-1", "grade": "A"}]
    node = cast(dict[str, Any], cast(dict[str, Any], raw["nodes"])["node-1"])
    cast(dict[str, Any], raw["nodes"])["gate-1"] = {
        "spec": {"node_id": "gate-1", "creation_position": 3, "task_region_id": "task-1"}
    }
    node["runtime"] = {
        "state": "ready",
        "candidate_id": "candidate-1",
        "failed_candidate_id": "candidate-1",
    }
    node["spec"].update(
        task_region_id="task-1",
        authority_request={
            "requested_authority": ["graph_write"],
            "target_node_id": "node-1",
            "target_region_id": "task-1",
            "reason": "fixture",
        },
        decision_request={
            "decision_type": "fixture",
            "options": ["continue"],
            "consequence_summary": "fixture",
            "target_node_id": "node-1",
            "target_region_id": "task-1",
        },
        authority_request_record_id=record_id_by_type["authority_request_record"],
    )
    cast(dict[str, Any], raw["tasks"])["task-1"]["candidates"][0]["supersedes_task_region_ids"] = [
        "task-1"
    ]
    cast(dict[str, Any], raw["topology"])["input_bindings"] = {
        "node-2": {
            "input": {
                "edge_id": "edge-1",
                "to_node_id": "node-2",
                "to_port": "input",
                "record_ids": [referenced_record_id],
                "record_bound_positions": {referenced_record_id: 1},
                "bound_at_position": 1,
                "supersedes_record_id": referenced_record_id,
            }
        }
    }
    cast(dict[str, Any], raw["topology"])["input_binding_port_order"] = {"node-2": ["input"]}
    cast(dict[str, Any], raw["planning"]).update(
        successor_by_node={"node-1": "node-2"},
        accepted_patch_ids_by_node={"node-1": [referenced_record_id]},
        no_successor_patch_ids_by_node={"node-1": [referenced_record_id]},
        latest_no_successor_patch_id_by_node={"node-1": referenced_record_id},
        latest_routine_snapshot={
            "record_id": referenced_record_id,
            "producer_node_id": "node-1",
            "port": "file_state",
        },
        generation_by_node={"node-1": 1},
        region_label_by_node={"node-1": "region"},
    )
    cast(dict[str, Any], raw["verification"]).update(
        failed_results_by_record_id={
            referenced_record_id: {
                "record_id": referenced_record_id,
                "node_id": "node-1",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
            }
        },
        failed_candidate_ids={"candidate-1": True},
        recovery_nodes_by_record_id={
            referenced_record_id: [{"node_id": "node-1", "recovery_reason": "fixture"}]
        },
    )
    revisions = cast(dict[str, Any], cast(dict[str, Any], raw["requirements"])["revisions_by_id"])
    revisions["revision-0"] = {
        "requirement_id": "requirement-1",
        "version_id": "revision-0",
        "change_classification": "initial",
        "requires_authority": False,
        "position": 0,
        "validation_strengthening": False,
    }
    revisions["revision-1"]["previous_version_id"] = "revision-0"
    cast(dict[str, Any], raw["governance"]).update(
        pending_appeals_by_node={"node-1": True},
        node_gate_decisions={"node-1": True},
        configured_gates_by_task={"task-1": {"gate-1": True}},
        gate_decisions_by_task={"task-1": {"gate-1": True}},
        approval_decisions_by_id={
            "approval-1": {
                "node_id": "node-1",
                "decision": "approved",
                "task_region_id": "task-1",
                "appeal_node_id": "node-1",
            }
        },
        approval_decision_id_by_node={"node-1": "approval-1"},
        authority_decisions_by_id={
            "authority-1": {
                "node_id": "node-1",
                "decision": "granted",
                "task_region_id": "task-1",
                "appeal_node_id": "node-1",
            }
        },
        authority_decision_id_by_node={"node-1": "authority-1"},
        oversight_decisions_by_id={
            "oversight-1": {
                "node_id": "node-1",
                "decision": "accepted",
                "position": 1,
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
                "appeal_node_id": "node-1",
                "appealed_node_id": "node-1",
            }
        },
        oversight_decision_id_by_node={"node-1": "oversight-1"},
        decision_requests_by_node={
            "node-1": {
                "decision_type": "fixture",
                "options": ["continue"],
                "consequence_summary": "fixture",
                "target_node_id": "node-1",
                "target_region_id": "task-1",
            }
        },
        authority_revision_blockers={
            "revision-1": {
                "kind": "fixture",
                "reason": "fixture",
                "node_id": "node-1",
                "edge_id": "edge-1",
                "from_node_id": "node-1",
                "proposal_id": referenced_record_id,
                "requirement_id": "requirement-1",
                "revision_id": "revision-1",
                "support_ids": ["support-1"],
                "task_region_id": "task-1",
            }
        },
    )
    cast(dict[str, Any], raw["usage"]).update(
        tokens_by_node={"node-1": 1}, recorded_keys={"node-1": True}
    )

    def replace_record_one(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                replace_record_one(key): replace_record_one(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [replace_record_one(item) for item in value]
        return "file-state-1" if value == "record-1" else value

    return GraphProjection.model_validate(replace_record_one(raw))


COMPLETE_PROJECTION_FIXTURE = complete_projection_fixture()
COMPLETE_PROJECTION_CHECKPOINT = projection_to_checkpoint(COMPLETE_PROJECTION_FIXTURE)


@dataclass(frozen=True)
class ResolverOutcomeCase:
    policy_path: str
    family: str
    concrete_path: str
    location: tuple[str | int, ...]
    map_key: bool = False
    consistency_reason: str | None = None


def _projection_child(value: object, part: str | int) -> object:
    if isinstance(value, BaseModel):
        assert isinstance(part, str)
        return getattr(value, part)
    if isinstance(value, FrozenMap):
        assert isinstance(part, str)
        return value[part]
    assert isinstance(value, tuple)
    assert isinstance(part, int)
    return value[part]


def _projection_value_at(value: object, location: tuple[str | int, ...]) -> object:
    for part in location:
        value = _projection_child(value, part)
    return value


def _projection_replace_child(value: object, part: str | int, child: object) -> object:
    if isinstance(value, BaseModel):
        assert isinstance(part, str)
        return value.model_copy(update={part: child})
    if isinstance(value, FrozenMap):
        assert isinstance(part, str)
        return map_set(value, part, child)
    assert isinstance(value, tuple)
    assert isinstance(part, int)
    return (*value[:part], child, *value[part + 1 :])


def _projection_replace(
    value: object,
    location: tuple[str | int, ...],
    replacement: str,
    *,
    rename_key: bool,
) -> object:
    part = location[0]
    if len(location) == 1:
        if rename_key:
            assert isinstance(value, FrozenMap)
            assert isinstance(part, str)
            return map_set(map_delete(value, part), replacement, value[part])
        return _projection_replace_child(value, part, replacement)
    child = _projection_replace(
        _projection_child(value, part), location[1:], replacement, rename_key=rename_key
    )
    return _projection_replace_child(value, part, child)


def _resolver_locations(
    value: object,
    segments: tuple[str, ...],
    location: tuple[str | int, ...] = (),
) -> list[tuple[tuple[str | int, ...], bool]]:
    if not segments:
        if isinstance(value, str):
            return [(location, False)]
        if isinstance(value, (list, tuple)):
            return [
                (location + (index,), False)
                for index, item in enumerate(value)
                if isinstance(item, str)
            ]
        if isinstance(value, dict):
            return [
                found
                for key, item in value.items()
                for found in _resolver_locations(item, (), location + (key,))
            ]
        return []
    segment, remaining = segments[0], segments[1:]
    if segment == "key" and not remaining:
        return [(location, True)]
    if segment == "value" and isinstance(value, dict) and segment in value:
        return _resolver_locations(value[segment], remaining, location + (segment,))
    if segment == "value":
        return _resolver_locations(value, remaining, location)
    if segment == "*":
        if isinstance(value, dict):
            return [
                found
                for key, item in value.items()
                for found in _resolver_locations(item, remaining, location + (key,))
            ]
        if isinstance(value, list):
            return [
                found
                for index, item in enumerate(value)
                for found in _resolver_locations(item, remaining, location + (index,))
            ]
        return []
    if isinstance(value, dict) and segment in value:
        return _resolver_locations(value[segment], remaining, location + (segment,))
    return []


def _concrete_path(location: tuple[str | int, ...]) -> str:
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else ("." if path else "") + part
    return path


def _consistency_reason(policy_path: str, location: tuple[str | int, ...]) -> str | None:
    map_key_fields = {
        "nodes.*.spec.node_id",
        "records.by_id.*.record_id",
        "requirements.revisions_by_id.*.version_id",
        "requirements.support_by_id.*.support_id",
        "topology.edges.*.edge_id",
        "execution.leases.*.lease_id",
        "execution.cleanup_requests_by_id.*.cleanup_id",
        "verification.check_results_by_node.*.node_id",
        "verification.failed_results_by_record_id.*.record_id",
        "verification.passed_results_by_record_id.*.record_id",
    }
    if policy_path in map_key_fields:
        key = location[1] if policy_path == "nodes.*.spec.node_id" else location[2]
        return f"must equal map key {key!r}"
    if policy_path == "topology.input_bindings.*.*.to_node_id":
        return f"must equal outer node key {location[2]!r}"
    if policy_path == "execution.environment_failures_by_task.*.task_region_id":
        return f"must equal outer task key {location[2]!r}"
    return None


def _resolver_outcome_cases() -> tuple[ResolverOutcomeCase, ...]:
    raw = COMPLETE_PROJECTION_CHECKPOINT
    catalog = projection_relation_policy_catalog() | projection_record_relation_policy_catalog()
    cases: list[ResolverOutcomeCase] = []
    for policy_path, policy in catalog.items():
        if policy.validation != "resolver":
            continue
        locations = _resolver_locations(raw, tuple(policy_path.split(".")))
        assert locations, f"resolver policy has no populated fixture location: {policy_path}"
        locations.sort(key=lambda item: _concrete_path(item[0]))
        if policy.scope == "record":
            by_record_type: dict[str, tuple[tuple[str | int, ...], bool]] = {}
            records = cast(dict[str, Any], raw["records"])["by_id"]
            for location in locations:
                record_id = cast(str, location[0][2])
                by_record_type.setdefault(records[record_id]["record_type"], location)
            locations = list(by_record_type.values())
        else:
            locations = locations[:1]
        cases.extend(
            ResolverOutcomeCase(
                policy_path=policy_path,
                family=policy.family,
                concrete_path=_concrete_path(location),
                location=location,
                map_key=map_key,
                consistency_reason=_consistency_reason(policy_path, location),
            )
            for location, map_key in locations
        )
    return tuple(sorted(cases, key=lambda case: (case.policy_path, case.concrete_path)))


RESOLVER_OUTCOME_CASES = _resolver_outcome_cases()


def test_complete_fixture_exercises_every_concrete_projected_record_visitor() -> None:
    projection = COMPLETE_PROJECTION_FIXTURE

    validate_projection_integrity(projection)

    assert {type(item) for item in projection.records.by_id.values()} == set(PROJECTED_RECORD_TYPES)


def _multi_edge_projection(edge_order: tuple[str, ...]) -> GraphProjection:
    raw = _checkpoint()
    topology = cast(dict[str, Any], raw["topology"])
    edge_values = {
        "edge-1": topology["edges"]["edge-1"],
        "edge-2": {
            "edge_id": "edge-2",
            "from_node_id": "node-1",
            "from_port": "verification",
            "to_node_id": "node-2",
            "to_port": "secondary",
        },
    }
    topology["edges"] = {edge_id: edge_values[edge_id] for edge_id in edge_order}
    topology["inbound_edge_ids"] = {"node-2": ["edge-2", "edge-1"]}
    topology["outbound_edge_ids"] = {"node-1": ["edge-2", "edge-1"]}
    return GraphProjection.model_validate(raw)


def test_topology_adjacency_integrity_is_independent_of_edge_map_layout() -> None:
    first = _multi_edge_projection(("edge-1", "edge-2"))
    second = _multi_edge_projection(("edge-2", "edge-1"))

    validate_projection_integrity(first)
    validate_projection_integrity(second)


def test_record_indexes_preserve_replay_order_independent_of_record_map_layout() -> None:
    raw: dict[str, Any] = {
        "nodes": {"node-1": {"spec": {"node_id": "node-1", "creation_position": 1}}},
        "tasks": {"task-1": {"state": "active"}},
        "records": {
            "by_id": {
                "z-record": {
                    "record_id": "z-record",
                    "record_type": "file_state",
                    "producer_node_id": "node-1",
                    "task_region_id": "task-1",
                    "acceptance_identity": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "a-record": {
                    "record_id": "a-record",
                    "record_type": "file_state",
                    "producer_node_id": "node-1",
                    "task_region_id": "task-1",
                    "acceptance_identity": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            },
            "ids_by_node_port": {"node-1": {"file_state": ["z-record", "a-record"]}},
            "summaries_by_id": {
                record_id: {
                    "record_id": record_id,
                    "record_type": "file_state",
                    "record_kind": "file_state",
                    "schema": "FileStateRecord",
                    "producer_node_id": "node-1",
                    "producer_port": "file_state",
                }
                for record_id in ("z-record", "a-record")
            },
        },
    }

    projection = GraphProjection.model_validate(raw)

    validate_projection_integrity(projection)
    assert projection.records.ids_by_node_port["node-1"]["file_state"] == (
        "z-record",
        "a-record",
    )


@pytest.mark.parametrize(
    ("record_ids", "expected_path", "expected_reason"),
    [
        (
            ["record-1", "record-1"],
            "records.ids_by_node_port.node-1.file_state[1]",
            "duplicates record ID 'record-1' first listed at records.ids_by_node_port.node-1.file_state[0]",
        ),
        (
            [],
            "records.ids_by_node_port.node-1.file_state",
            "must exactly contain record IDs for its node and port",
        ),
        (
            ["record-1", "missing-record"],
            "records.ids_by_node_port.node-1.file_state",
            "must exactly contain record IDs for its node and port",
        ),
    ],
)
def test_record_indexes_reject_duplicate_missing_and_extra_record_ids(
    record_ids: list[str], expected_path: str, expected_reason: str
) -> None:
    raw = _checkpoint()
    cast(dict[str, Any], raw["records"])["ids_by_node_port"] = {
        "node-1": {"file_state": record_ids}
    }

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        validate_projection_integrity(GraphProjection.model_validate(raw))

    assert (expected_path, expected_reason) in {
        (diagnostic.path, diagnostic.reason) for diagnostic in raised.value.diagnostics
    }


def test_record_indexes_reject_existing_node_without_canonical_indexes() -> None:
    raw = _checkpoint()
    cast(dict[str, Any], raw["records"])["ids_by_node_port"]["node-2"] = {}

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        validate_projection_integrity(GraphProjection.model_validate(raw))

    assert (
        "records.ids_by_node_port.node-2",
        "is not a canonical record index node key",
    ) in {(item.path, item.reason) for item in raised.value.diagnostics}


@pytest.mark.parametrize(
    ("edge_ids", "expected"),
    [
        (
            ["edge-2", "edge-2", "edge-1"],
            {
                (
                    "topology.inbound_edge_ids.node-2[1]",
                    "duplicates edge ID 'edge-2' first listed at "
                    "topology.inbound_edge_ids.node-2[0]",
                )
            },
        ),
        (
            ["edge-2"],
            {
                (
                    "topology.inbound_edge_ids.node-2",
                    "must exactly contain edge IDs targeting node 'node-2'",
                )
            },
        ),
        (
            ["edge-2", "edge-1", "missing-edge"],
            {
                (
                    "topology.inbound_edge_ids.node-2[2]",
                    "references missing edge 'missing-edge'",
                ),
                (
                    "topology.inbound_edge_ids.node-2",
                    "must exactly contain edge IDs targeting node 'node-2'",
                ),
            },
        ),
    ],
)
def test_topology_adjacency_rejects_duplicate_missing_and_extra_edge_ids(
    edge_ids: list[str], expected: set[tuple[str, str]]
) -> None:
    raw = projection_to_checkpoint(_multi_edge_projection(("edge-1", "edge-2")))
    cast(dict[str, Any], raw["topology"])["inbound_edge_ids"] = {"node-2": edge_ids}
    malformed = GraphProjection.model_validate(raw)

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        validate_projection_integrity(malformed)

    assert expected == {
        (diagnostic.path, diagnostic.reason) for diagnostic in raised.value.diagnostics
    }


def test_topology_adjacency_reports_the_same_invalid_id_at_each_tuple_location() -> None:
    raw = projection_to_checkpoint(_multi_edge_projection(("edge-1", "edge-2")))
    cast(dict[str, Any], raw["topology"])["inbound_edge_ids"] = {
        "node-1": ["missing-edge"],
        "node-2": ["edge-2", "edge-1", "missing-edge"],
    }
    malformed = GraphProjection.model_validate(raw)

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        validate_projection_integrity(malformed)

    missing = {
        (diagnostic.path, diagnostic.reason)
        for diagnostic in raised.value.diagnostics
        if diagnostic.reason == "references missing edge 'missing-edge'"
    }
    assert missing == {
        (
            "topology.inbound_edge_ids.node-1[0]",
            "references missing edge 'missing-edge'",
        ),
        (
            "topology.inbound_edge_ids.node-2[2]",
            "references missing edge 'missing-edge'",
        ),
    }


def test_public_resolver_outcome_cases_exactly_cover_static_resolver_policies() -> None:
    catalog = projection_relation_policy_catalog() | projection_record_relation_policy_catalog()

    assert {case.policy_path for case in RESOLVER_OUTCOME_CASES} == {
        path for path, policy in catalog.items() if policy.validation == "resolver"
    }


@pytest.mark.parametrize(
    "case",
    RESOLVER_OUTCOME_CASES,
    ids=lambda case: f"{case.policy_path}:{case.concrete_path}",
)
def test_every_static_resolver_policy_has_an_exact_public_failure_outcome(
    case: ResolverOutcomeCase,
) -> None:
    original = COMPLETE_PROJECTION_FIXTURE
    original_value = _projection_value_at(original, case.location)
    missing = f"missing-{case.family}-6b2"
    if case.map_key:
        expected_path = _concrete_path((*case.location[:-1], missing))
    else:
        expected_path = (
            f"{case.policy_path}.{missing}"
            if case.policy_path in {"topology.inbound_edge_ids", "topology.outbound_edge_ids"}
            else case.concrete_path
        )
    malformed = cast(
        GraphProjection,
        _projection_replace(original, case.location, missing, rename_key=case.map_key),
    )
    kind = {
        "revision": "requirement revision",
        "cleanup": "cleanup request",
    }.get(case.family, case.family)

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        validate_projection_integrity(malformed)

    assert (expected_path, f"references missing {kind} {missing!r}") in {
        (diagnostic.path, diagnostic.reason) for diagnostic in raised.value.diagnostics
    }
    if case.consistency_reason is not None:
        assert (expected_path, case.consistency_reason) in {
            (diagnostic.path, diagnostic.reason) for diagnostic in raised.value.diagnostics
        }
    assert _projection_value_at(original, case.location) == original_value


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
        projection_from_checkpoint(raw)

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
        projection_from_checkpoint(raw)

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
        projection_from_checkpoint(raw)

    diagnostics = raised.value.diagnostics
    assert tuple(diagnostic.path for diagnostic in diagnostics) == tuple(
        sorted(diagnostic.path for diagnostic in diagnostics)
    )
    assert {diagnostic.path for diagnostic in diagnostics} >= {
        "nodes.node-1.spec.node_id",
        "topology.edges.edge-1.to_node_id",
    }
    assert raw == before


def test_node_runtime_candidate_may_name_a_planned_output_before_acceptance() -> None:
    raw = _checkpoint()
    nodes = cast(dict[str, object], raw["nodes"])
    node = cast(dict[str, object], nodes["node-1"])
    runtime = cast(dict[str, object], node.setdefault("runtime", {}))
    runtime["candidate_id"] = "planned-candidate"

    assert (
        projection_from_checkpoint(raw).nodes["node-1"].runtime.candidate_id == "planned-candidate"
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

    assert projection_from_checkpoint(raw).records.by_id["candidate-record-1"].record_id == (
        "candidate-record-1"
    )


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
        projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[
        "records.by_id.candidate-record-1.candidate_id"
    ] == "must resolve to a candidate for task 'task-2'"


@pytest.mark.parametrize(
    ("mutate", "expected_path", "expected_reason"),
    [
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
        projection_from_checkpoint(raw)

    assert {item.path: item.reason for item in raised.value.diagnostics}[
        expected_path
    ] == expected_reason


def test_oversight_candidate_may_reference_candidate_for_its_task() -> None:
    raw = _checkpoint()
    governance = cast(dict[str, Any], raw["governance"])
    governance["oversight_decisions_by_id"] = {
        "oversight-1": {
            "node_id": "node-1",
            "decision": "accepted",
            "position": 1,
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
        }
    }
    governance["oversight_decision_id_by_node"] = {"node-1": "oversight-1"}

    validate_projection_integrity(GraphProjection.model_validate(raw))


@pytest.mark.parametrize(
    ("field", "aliases", "expected_reason"),
    [
        (
            "approval_decision_id_by_node",
            {"node-1": "missing-decision"},
            "references missing approval decision 'missing-decision'",
        ),
        (
            "authority_decision_id_by_node",
            {"node-2": "authority-1"},
            "must reference a decision for its node",
        ),
        (
            "oversight_decision_id_by_node",
            {"missing-node": "oversight-1"},
            "references missing node 'missing-node'",
        ),
    ],
)
def test_decision_aliases_require_an_existing_same_node_canonical_decision(
    field: str, aliases: dict[str, str], expected_reason: str
) -> None:
    raw = deepcopy(COMPLETE_PROJECTION_CHECKPOINT)
    cast(dict[str, Any], raw["governance"])[field] = aliases

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        projection_from_checkpoint(raw)

    path = f"governance.{field}.{next(iter(aliases))}"
    assert {item.path: item.reason for item in raised.value.diagnostics}[path] == expected_reason


@pytest.mark.parametrize(
    ("candidate_id", "duplicate", "expected_reason"),
    [
        ("missing-candidate", False, "references missing candidate 'missing-candidate'"),
        (
            "candidate-1",
            True,
            "references ambiguous candidate 'candidate-1': "
            "tasks.task-1.candidates[0].candidate_id, "
            "tasks.task-2.candidates[0].candidate_id",
        ),
        ("candidate-1", False, "must resolve to a candidate for task 'task-2'"),
    ],
)
def test_oversight_candidate_rejects_missing_ambiguous_or_cross_task_candidate(
    candidate_id: str, duplicate: bool, expected_reason: str
) -> None:
    raw = _checkpoint()
    tasks = cast(dict[str, Any], raw["tasks"])
    tasks["task-2"] = {
        "state": "active",
        "candidates": (
            [{"candidate_id": "candidate-1", "attempt_number": 2, "position": 2}]
            if duplicate
            else []
        ),
    }
    governance = cast(dict[str, Any], raw["governance"])
    governance["oversight_decisions_by_id"] = {
        "oversight-1": {
            "node_id": "node-1",
            "decision": "accepted",
            "position": 1,
            "task_region_id": "task-1"
            if duplicate or candidate_id.startswith("missing")
            else "task-2",
            "candidate_id": candidate_id,
        }
    }
    governance["oversight_decision_id_by_node"] = {"node-1": "oversight-1"}

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        validate_projection_integrity(GraphProjection.model_validate(raw))

    reason = {item.path: item.reason for item in raised.value.diagnostics}[
        "governance.oversight_decisions_by_id.oversight-1.candidate_id"
    ]
    assert reason == expected_reason


def test_checkpoint_round_trip_accepts_grade_for_static_routine_requirement() -> None:
    raw = _checkpoint()
    records = cast(dict[str, Any], raw["records"])
    by_id = cast(dict[str, Any], records["by_id"])
    by_id["routine-requirement-record"] = {
        "record_id": "routine-requirement-record",
        "record_type": "requirement_record",
        "record_kind": "graph_record",
        "producer_node_id": "node-1",
        "port": "requirement",
        "schema": "RequirementRecord",
        "value": {
            "id": "req-1",
            "text": "A static routine requirement",
            "source": "routine",
            "version": "initial",
        },
    }
    by_id["verification-report-record"] = {
        "record_id": "verification-report-record",
        "record_type": "verification_report",
        "record_kind": "verification",
        "producer_node_id": "node-1",
        "candidate_id": "candidate-1",
        "task_region_id": "task-1",
        "outcome": "passed",
        "value": {
            "outcome": "passed",
            "grades": [{"requirement_id": "req-1", "grade": "A"}],
        },
    }
    cast(dict[str, Any], records["ids_by_node_port"])["node-1"].update(
        {
            "requirement": ["routine-requirement-record"],
            "verification_report": ["verification-report-record"],
        }
    )
    cast(dict[str, Any], records["summaries_by_id"]).update(
        {
            "routine-requirement-record": {
                "record_id": "routine-requirement-record",
                "record_type": "requirement_record",
                "record_kind": "graph_record",
                "schema": "RequirementRecord",
                "producer_node_id": "node-1",
                "producer_port": "requirement",
            },
            "verification-report-record": {
                "record_id": "verification-report-record",
                "record_type": "verification_report",
                "record_kind": "verification",
                "schema": "VerificationReport",
                "producer_node_id": "node-1",
                "producer_port": "verification_report",
            },
        }
    )

    assert projection_from_checkpoint(raw) == GraphProjection.model_validate(raw)


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
        projection_from_checkpoint(raw)

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
        projection_from_checkpoint(raw)

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
            "nodes.node-1.spec.authority_request_record_id",
            "missing-authority-record",
            "nodes.node-1.spec.authority_request_record_id",
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
        projection_from_checkpoint(raw)

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
            "execution.callback_events_by_key.node-1\0callback-1.idempotency_key",
            "other-callback",
            "execution.callback_events_by_key.node-1\0callback-1.idempotency_key",
            "must form composite map key 'node-1\\x00callback-1'",
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
        projection_from_checkpoint(raw)

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
    discovered = discover_projection_identifier_paths(GraphProjection)

    non_graph_identifier_policies = {"usage.recorded_keys.*.key"}
    assert discovered == (set(catalog) | set(record_catalog)) - non_graph_identifier_policies
    assert projection_relation_policy_gaps(GraphProjection) == frozenset()
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
        "record_ids_by_node.*.*",
        "session_id_by_node.*.key",
        "session_id_by_node.*.value",
        "region_label_by_node.*.key",
        "heterogeneous.*.linked_node_id",
    }


def test_identifier_discovery_includes_nested_ids_by_node_port_values_not_port_keys() -> None:
    assert discover_projection_identifier_paths(NestedRecordIndexDiscoveryFixture) == {
        "ids_by_node_port.*.key",
        "ids_by_node_port.*.*.key",
        "ids_by_node_port.*.*.*",
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


def test_runtime_dispatcher_rejects_appended_segment_for_scalar_policy() -> None:
    policy = projection_relation_policy_catalog()["nodes.*.spec.node_id"]
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher({policy.path: policy}, frozenset({policy.path}), calls)

    dispatcher.resolve_runtime("node", "nodes.node-1.spec.node_id", "node-1")

    assert calls.values == [("node-1", "nodes.node-1.spec.node_id")]
    with pytest.raises(ProjectionRelationPolicyError) as raised:
        dispatcher.resolve_runtime("node", "nodes.node-1.spec.node_id.extra", "node-2")
    assert str(raised.value) == (
        "expected one relation policy for runtime path 'nodes.node-1.spec.node_id.extra', found []"
    )
    assert calls.values == [("node-1", "nodes.node-1.spec.node_id")]


@pytest.mark.parametrize(
    ("policy_path", "family", "diagnostic_path", "map_role"),
    [
        ("nodes.*.spec.node_id", "node", "nodes.node.with[brackets].spec.node_id", None),
        (
            "verification.passed_candidate_ids.*",
            "candidate",
            "verification.passed_candidate_ids[0]",
            None,
        ),
        (
            "records.by_id.*.record_id",
            "record",
            "records.by_id.record.with[brackets].record_id",
            None,
        ),
        (
            "topology.edges.*.edge_id",
            "edge",
            "topology.edges.edge.with[brackets].edge_id",
            None,
        ),
        (
            "planning.sessions.*.current_node_id",
            "node",
            "planning.sessions.session.with[brackets].current_node_id",
            None,
        ),
    ],
)
def test_runtime_dispatcher_preserves_dotted_and_bracketed_identifiers(
    policy_path: str,
    family: str,
    diagnostic_path: str,
    map_role: Literal["key", "value"] | None,
) -> None:
    catalog = projection_relation_policy_catalog() | projection_record_relation_policy_catalog()
    policy = catalog[policy_path]
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher({policy_path: policy}, frozenset({policy_path}), calls)

    dispatcher.resolve_runtime(
        cast(Any, family), diagnostic_path, "represented-id", map_role=map_role
    )

    assert calls.values == [("represented-id", diagnostic_path)]


def test_runtime_dispatcher_matches_explicit_collection_member_wildcard() -> None:
    catalog = projection_relation_policy_catalog()
    policies = {
        path: catalog[path]
        for path in (
            "scheduling.ready_node_ids.*",
            "topology.input_bindings.*.*.record_ids.*",
        )
    }
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher(policies, frozenset(policies), calls)

    dispatcher.resolve_runtime("node", "scheduling.ready_node_ids[0]", "node-1")
    dispatcher.resolve_runtime(
        "record", "topology.input_bindings.node-1.input.record_ids[0]", "record-1"
    )

    assert calls.values == [
        ("node-1", "scheduling.ready_node_ids[0]"),
        ("record-1", "topology.input_bindings.node-1.input.record_ids[0]"),
    ]


def test_runtime_dispatcher_rejects_map_path_without_explicit_role() -> None:
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
        "'planning.successor_by_node.node-1', found []"
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
        dispatcher.resolve_runtime(
            family,
            diagnostic_path,
            "node-1",
            map_role="key" if policy_path.endswith(".key") else None,
        )

    assert str(raised.value) == message
    assert calls.values == []


@pytest.mark.parametrize(
    ("policy_path", "family", "diagnostic_path"),
    [
        (
            "records.by_id.*.value.requirements_addressed.*",
            "requirement",
            "records.by_id.record-1.value.requirements_addressed[0]",
        ),
        (
            "records.by_id.*.value.version",
            "revision",
            "records.by_id.record-1.value.version",
        ),
        (
            "governance.authority_revision_blockers.*.support_ids.*",
            "support",
            "governance.authority_revision_blockers.blocker-1.support_ids[0]",
        ),
        (
            "records.by_id.*.value.lease_id",
            "lease",
            "records.by_id.record-1.value.lease_id",
        ),
        (
            "records.by_id.*.cleanup_id",
            "cleanup",
            "records.by_id.record-1.cleanup_id",
        ),
        (
            "governance.authority_revision_blockers.*.edge_id",
            "edge",
            "governance.authority_revision_blockers.blocker-1.edge_id",
        ),
        (
            "execution.leases.*.session_id",
            "session",
            "execution.leases.lease-1.session_id",
        ),
    ],
)
def test_remaining_represented_families_dispatch_and_fail_closed_on_wrong_family(
    policy_path: str,
    family: Literal["requirement", "revision", "support", "lease", "cleanup", "edge", "session"],
    diagnostic_path: str,
) -> None:
    catalog = projection_relation_policy_catalog() | projection_record_relation_policy_catalog()
    policy = catalog[policy_path]
    calls = _ResolverCalls()
    dispatcher = _runtime_dispatcher({policy_path: policy}, frozenset({policy_path}), calls)

    dispatcher.resolve_runtime(family, diagnostic_path, "represented-id")

    assert calls.values == [("represented-id", diagnostic_path)]
    with pytest.raises(ProjectionRelationPolicyError, match=f"expects family '{family}'"):
        dispatcher.resolve_runtime("node", diagnostic_path, "represented-id")
    assert calls.values == [("represented-id", diagnostic_path)]


def test_represented_map_keys_are_resolver_policies() -> None:
    catalog = projection_relation_policy_catalog()
    expected = {
        "execution.cleanup_requests_by_id.*.key": "cleanup",
        "execution.environment_failures_by_task.*.key": "task",
        "execution.leases.*.key": "lease",
        "governance.approval_decision_id_by_node.*.key": "node",
        "governance.authority_decision_id_by_node.*.key": "node",
        "governance.configured_gates_by_task.*.key": "task",
        "governance.decision_requests_by_node.*.key": "node",
        "governance.gate_decisions_by_task.*.key": "task",
        "governance.node_gate_decisions.*.key": "node",
        "governance.oversight_decision_id_by_node.*.key": "node",
        "governance.pending_appeals_by_node.*.key": "node",
        "planning.accepted_patch_ids_by_node.*.key": "node",
        "planning.generation_by_node.*.key": "node",
        "planning.latest_no_successor_patch_id_by_node.*.key": "node",
        "planning.no_successor_patch_ids_by_node.*.key": "node",
        "planning.region_label_by_node.*.key": "node",
        "planning.session_id_by_node.*.key": "node",
        "planning.successor_by_node.*.key": "node",
        "requirements.active_version_id_by_requirement.*.key": "requirement",
        "requirements.revisions_by_id.*.key": "revision",
        "requirements.support_by_id.*.key": "support",
        "topology.edges.*.key": "edge",
        "topology.input_bindings.*.key": "node",
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
    recorded_keys_policy = catalog["usage.recorded_keys.*.key"]
    assert recorded_keys_policy.family == "external"
    assert recorded_keys_policy.validation == "external"
    assert "node-usage" in recorded_keys_policy.rationale
    assert "usage.recorded_keys.*.key" not in projection_relation_validation_paths()


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


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        (None, "must contain a lowercase 64-character SHA-256 acceptance identity"),
        ("A" * 64, "must contain a lowercase 64-character SHA-256 acceptance identity"),
        ("a" * 63, "must contain a lowercase 64-character SHA-256 acceptance identity"),
    ],
)
def test_checkpoint_file_state_records_require_valid_acceptance_identity(
    identity: str | None, reason: str
) -> None:
    raw = _checkpoint()
    record = cast(dict[str, Any], cast(dict[str, Any], raw["records"])["by_id"])["record-1"]
    if identity is None:
        record.pop("acceptance_identity")
    else:
        record["acceptance_identity"] = identity

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        projection_from_checkpoint(raw)

    assert any(
        diagnostic.path == "records.by_id.record-1.acceptance_identity"
        and diagnostic.reason == reason
        for diagnostic in raised.value.diagnostics
    )


@pytest.mark.parametrize(
    ("order", "reason"),
    [
        (None, "must have an input-binding port order entry"),
        (["input", "input"], "must not repeat input-binding ports"),
        (["other"], "must exactly contain input-binding ports for its node"),
    ],
)
def test_checkpoint_input_binding_port_order_closes_over_binding_nodes(
    order: list[str] | None, reason: str
) -> None:
    raw = projection_to_checkpoint(complete_projection_fixture())
    topology = cast(dict[str, Any], raw["topology"])
    port_order = cast(dict[str, Any], topology["input_binding_port_order"])
    if order is None:
        port_order.pop("node-2")
    else:
        port_order["node-2"] = order

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        projection_from_checkpoint(raw)

    assert any(
        diagnostic.path == "topology.input_binding_port_order.node-2"
        and diagnostic.reason == reason
        for diagnostic in raised.value.diagnostics
    )


def test_checkpoint_rejects_orphan_input_binding_port_order_entry() -> None:
    raw = _checkpoint()
    topology = cast(dict[str, Any], raw["topology"])
    topology["input_binding_port_order"] = {"node-1": ["orphan"]}

    with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
        projection_from_checkpoint(raw)

    assert any(
        diagnostic.path == "topology.input_binding_port_order.node-1"
        and diagnostic.reason == "is not a canonical input-binding key"
        for diagnostic in raised.value.diagnostics
    )
