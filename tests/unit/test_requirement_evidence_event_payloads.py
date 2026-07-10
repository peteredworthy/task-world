from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    RequirementRevisionPayload,
    RequirementAuthorityResolutionPayload,
    SequentialIdGenerator,
    SupportEvidencePayload,
    apply_command,
    build_projection,
    initial_projection,
    project_final_invariant_blockers,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
)
from orchestrator.graph_runtime.store import (
    LIGHT_GRAPH_PAYLOAD_FIELDS,
    _json_extract_payload_value,
)
from orchestrator.graph import build_graph_catalog


def test_requirement_revision_payload_preserves_all_authority_classification_inputs() -> None:
    payload = RequirementRevisionPayload.model_validate(
        {
            "requirement_id": "R-1",
            "id": "legacy-R-1",
            "node_id": "requirement-node",
            "revision_id": "revision-1",
            "version_id": "R-1.v2",
            "requirement_version_id": "legacy-version",
            "proposal_id": "proposal-1",
            "patch_id": "patch-1",
            "change_classification": "semantic_change",
            "classification": "semantic",
            "revision_type": "scope_expansion",
            "requires_authority": True,
            "explicit_authority_required": False,
            "new_behavior": True,
            "behavior_change": False,
            "semantic_change": True,
            "validation_strengthening": False,
            "active": True,
            "previous_version_id": "R-1.v1",
            "revision_index": 2,
            "authority_required_reason": "operator approval required",
            "requirement": {"id": "nested-R-1", "priority": "must"},
        }
    )

    assert payload.model_dump(mode="json") == {
        "requirement_id": "R-1",
        "id": "legacy-R-1",
        "node_id": "requirement-node",
        "revision_id": "revision-1",
        "version_id": "R-1.v2",
        "requirement_version_id": "legacy-version",
        "proposal_id": "proposal-1",
        "patch_id": "patch-1",
        "change_classification": "semantic_change",
        "classification": "semantic",
        "revision_type": "scope_expansion",
        "requires_authority": True,
        "explicit_authority_required": False,
        "new_behavior": True,
        "behavior_change": False,
        "semantic_change": True,
        "validation_strengthening": False,
        "active": True,
        "previous_version_id": "R-1.v1",
        "revision_index": 2,
        "authority_required_reason": "operator approval required",
        "requirement": {"id": "nested-R-1", "priority": "must"},
    }


def test_requirement_revision_payload_normalizes_invalid_scalars_and_unknown_keys_to_extra() -> (
    None
):
    payload = RequirementRevisionPayload.model_validate(
        {
            "requirement_id": 7,
            "classification": ["semantic"],
            "requires_authority": "yes",
            "revision_index": True,
            "requirement": "R-1",
            "legacy_note": {"kept": True},
        }
    )

    assert payload.requirement_id is None
    assert payload.classification is None
    assert payload.requires_authority is None
    assert payload.revision_index is None
    assert payload.requirement is None
    assert payload.extra == {
        "requirement_id": 7,
        "classification": ["semantic"],
        "requires_authority": "yes",
        "revision_index": True,
        "requirement": "R-1",
        "legacy_note": {"kept": True},
    }


def test_support_evidence_payload_supports_edge_and_version_aliases() -> None:
    payload = SupportEvidencePayload.model_validate(
        {
            "edge_id": "support-edge-1",
            "evidence_id": "evidence-1",
            "requirement_id": "R-1",
            "version_id": "R-1.v1",
            "status": "stale",
            "stale_reason": "superseded",
            "confidence": "high",
            "legacy_note": 1,
        }
    )

    assert payload.edge_id == "support-edge-1"
    assert payload.version_id == "R-1.v1"
    assert payload.extra == {"legacy_note": 1}


def test_requirement_reducers_tolerate_recorded_and_replay_only_aliases() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1", "classification": "initial"},
            position=1,
        ),
        _event(
            "requirement_amended",
            {
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v2",
                "classification": "semantic",
            },
            position=2,
        ),
        _event(
            "support_edge_recorded",
            {
                "edge_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
            },
            position=3,
        ),
        _event(
            "requirement_revision_proposed",
            {
                "proposal_id": "proposal-2",
                "requirement": {"id": "R-2"},
                "semantic_change": True,
            },
            position=4,
        ),
    ]

    projection = build_projection(build_graph_catalog(), events)

    assert projection["active_requirement_versions"] == {"R-1": "R-1.v2"}
    assert projection["support_evidence"]["S-1"].requirement_version_id == "R-1.v2"
    assert set(projection["authority_revision_blockers"]) == {"R-1.v2", "proposal-2"}


def test_authority_resolution_aliases_clear_full_history_and_checkpoint_blockers() -> None:
    revision = _event(
        "requirement_revision_proposed",
        {
            "proposal_id": "proposal-1",
            "requirement": {"id": "R-1"},
            "semantic_change": True,
        },
        position=1,
    )
    checkpoint = projection_to_checkpoint(build_projection(build_graph_catalog(), [revision]))

    for event_type, identifier in (
        ("authority_resolution_recorded", {"proposal_id": "proposal-1"}),
        ("authority_resolved", {"revision_id": "proposal-1"}),
        ("requirement_revision_authorized", {"patch_id": "proposal-1"}),
    ):
        resolution = _event(event_type, identifier, position=2)
        parsed = RequirementAuthorityResolutionPayload.model_validate(resolution.payload)
        assert parsed.model_dump(mode="json") == identifier
        full_events = [revision, resolution]
        tail_events = [resolution]

        assert project_final_invariants(full_events) == project_final_invariants_from_checkpoint(
            checkpoint, tail_events
        )
        assert project_final_invariants(full_events) == []


def test_requirement_and_support_producers_emit_typed_payloads() -> None:
    revision_events = apply_command(
        initial_projection(),
        [],
        "record_requirement_revision",
        {
            "run_id": "run-1",
            "requirement_id": "R-1",
            "version_id": "R-1.v1",
            "classification": "initial",
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    revision = RequirementRevisionPayload.model_validate(revision_events[0].payload)
    assert revision.requirement_id == "R-1"
    assert revision.extra == {}

    projection = build_projection(build_graph_catalog(), revision_events)
    support_events = apply_command(
        projection,
        revision_events,
        "record_support_evidence",
        {
            "run_id": "run-1",
            "support_id": "S-1",
            "evidence_id": "E-1",
            "requirement_id": "R-1",
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    support = SupportEvidencePayload.model_validate(support_events[0].payload)
    assert support.requirement_version_id == "R-1.v1"
    assert support.extra == {}


def test_validation_strengthening_still_stales_prior_support() -> None:
    events = [
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "R-1", "version_id": "R-1.v1"},
            position=1,
        ),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "S-1",
                "evidence_id": "E-1",
                "requirement_id": "R-1",
                "requirement_version_id": "R-1.v1",
            },
            position=2,
        ),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "R-1",
                "version_id": "R-1.v2",
                "validation_strengthening": True,
                "previous_version_id": "R-1.v1",
            },
            position=3,
        ),
    ]

    support = build_projection(build_graph_catalog(), events)["support_evidence"]["S-1"]
    assert support.status == "stale"
    assert support.stale_reason is not None


def test_light_graph_payload_retains_change_classification_for_requirement_replay() -> None:
    compact_payload = _compact_light_payload(
        {
            "requirement_id": "R-1",
            "version_id": "R-1.v2",
            "change_classification": "semantic_change",
        }
    )

    projection = build_projection(
        build_graph_catalog(),
        [_event("requirement_revision_recorded", compact_payload, position=1)],
    )
    revision = projection["requirement_revisions"]["R-1.v2"]

    assert revision.change_classification == "semantic_change"
    assert revision.requires_authority is True


def test_light_graph_payload_normalizes_sqlite_new_behavior_boolean_for_requirement_replay() -> (
    None
):
    compact_payload = _compact_light_payload(
        {
            "requirement_id": "R-1",
            "version_id": "R-1.v2",
            "new_behavior": 1,
        }
    )

    assert compact_payload["new_behavior"] is True
    projection = build_projection(
        build_graph_catalog(),
        [_event("requirement_revision_recorded", compact_payload, position=1)],
    )
    revision = projection["requirement_revisions"]["R-1.v2"]

    assert revision.change_classification == "new_behavior"
    assert revision.requires_authority is True


def project_final_invariants(events: list[EventEnvelope]) -> list[dict[str, Any]]:
    return [
        blocker
        for blocker in project_final_invariant_blockers(build_graph_catalog(), events)
        if blocker.get("kind") == "unresolved_authority_required_revision"
    ]


def _compact_light_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        field: _json_extract_payload_value(field, payload[field])
        for field in LIGHT_GRAPH_PAYLOAD_FIELDS
        if field in payload
    }


def project_final_invariants_from_checkpoint(
    checkpoint: dict[str, Any],
    tail_events: list[EventEnvelope],
) -> list[dict[str, Any]]:
    projection = projection_from_checkpoint(checkpoint)
    for event in tail_events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    return [
        projection["authority_revision_blockers"][key]
        for key in sorted(projection["authority_revision_blockers"])
    ]


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
