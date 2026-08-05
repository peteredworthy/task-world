"""Pure archival query contracts that cap collections before row persistence."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    build_projection,
    iter_archival_final_invariant_blockers,
    iter_archival_graph_topology_entries,
    iter_final_invariant_blockers,
    project_final_invariant_blockers,
)
from tests.unit.graph_test_utils import canonical_event_payload


def _event(position: int, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"archival-query-{position}",
        run_id="archival-query-run",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def test_archival_topology_caps_binding_collections_before_payload_construction() -> None:
    record_ids = [f"candidate-{index:04d}" for index in range(251)]
    specs: list[tuple[str, dict[str, Any]]] = [
        (
            "node_created",
            {"node_id": "producer", "kind": "worker", "state": "completed"},
        ),
        (
            "node_created",
            {"node_id": "consumer", "kind": "verifier", "state": "completed"},
        ),
        (
            "edge_created",
            {
                "edge_id": "large-binding",
                "from_node_id": "producer",
                "from_port": "candidate",
                "to_node_id": "consumer",
                "to_port": "candidate_under_test",
                "required": True,
                "dependency_type": "input_binding",
                "binding_policy": "bind_all",
            },
        ),
        *[
            (
                "output_record_accepted",
                {
                    "record_id": record_id,
                    "record_kind": "output",
                    "record_type": "candidate",
                    "producer_node_id": "producer",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": record_id,
                    "value": {"summary": record_id},
                },
            )
            for record_id in record_ids
        ],
        (
            "input_bound",
            {
                "edge_id": "large-binding",
                "to_node_id": "consumer",
                "to_port": "candidate_under_test",
                "record_ids": record_ids,
                "bound_at_position": 254,
                "binding_policy": "bind_all",
            },
        ),
    ]
    projection = build_projection(
        [
            _event(position, event_type, payload)
            for position, (event_type, payload) in enumerate(specs, 1)
        ]
    )

    entries = iter_archival_graph_topology_entries(projection, collection_limit=7)
    assert isinstance(entries, Iterator)
    edge = next(payload for kind, _, payload in entries if kind == "edge")

    assert edge["binding"]["record_ids"] == record_ids[:7]
    assert [record["record_id"] for record in edge["bound_records"]] == record_ids[:7]
    assert edge["binding"]["record_bound_positions"] == {
        record_id: 254 for record_id in record_ids[:7]
    }
    fields = edge["_graph_archival_read_contract"]["fields"]
    for path in (
        "$.binding.record_ids",
        "$.binding.record_bound_positions",
        "$.bound_records",
    ):
        assert fields[path] == {
            "revision": 1,
            "owner": "topology",
            "truncated": True,
            "total_known": 251,
            "next_cursor": record_ids[6],
            "original_bytes": None,
            "sha256": None,
        }


def test_final_blocker_generator_preserves_parity_and_archival_support_prefix() -> None:
    support_ids = [f"support-{index:04d}" for index in range(251)]
    specs: list[tuple[str, dict[str, Any]]] = [
        (
            "node_created",
            {
                "node_id": "check-pending",
                "kind": "check",
                "state": "planned",
                "task_region_id": "region-1",
            },
        ),
        (
            "requirement_revision_recorded",
            {
                "requirement_id": "R-large",
                "version_id": "R-large.v1",
                "classification": "initial",
            },
        ),
        *[
            (
                "support_evidence_recorded",
                {
                    "support_id": support_id,
                    "evidence_id": f"evidence-{index:04d}",
                    "requirement_id": "R-large",
                    "requirement_version_id": "R-large.v1",
                    "status": "active",
                },
            )
            for index, support_id in enumerate(support_ids)
        ],
        (
            "requirement_revision_recorded",
            {
                "requirement_id": "R-large",
                "version_id": "R-large.v2",
                "classification": "semantic",
                "previous_version_id": "R-large.v1",
            },
        ),
    ]
    events = [
        _event(position, event_type, payload)
        for position, (event_type, payload) in enumerate(specs, 1)
    ]
    projection = build_projection(events)

    streamed = iter_final_invariant_blockers(events, projection)
    assert isinstance(streamed, Iterator)
    assert list(streamed) == project_final_invariant_blockers(events, projection=projection)

    archival = list(iter_archival_final_invariant_blockers([], projection, collection_limit=7))
    stale = next(blocker for blocker in archival if blocker["kind"] == "stale_support_evidence")
    assert stale["support_ids"] == support_ids[:7]
    metadata = stale["_graph_archival_read_contract"]["fields"]["$.support_ids"]
    assert metadata == {
        "revision": 1,
        "owner": "final_blockers",
        "truncated": True,
        "total_known": 251,
        "next_cursor": support_ids[6],
        "original_bytes": None,
        "sha256": None,
    }
