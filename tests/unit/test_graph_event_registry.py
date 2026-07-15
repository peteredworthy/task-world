from pathlib import Path

import yaml

import pytest

from orchestrator.graph import (
    CANONICAL_EVENT_TYPES,
    EXTERNAL_EVENT_TYPES,
    INTERNAL_EVENT_TYPES_BY_PRODUCER,
    validate_emitted_event_type,
    validate_event_ownership,
)


REMOVED_EVENT_TYPES = {
    "environment_failure_accepted",
    "check_result_classified",
    "graph_patch_proposed",
    "planner_proposal_opened",
    "proposal_opened",
    "proposal_recorded",
    "proposal_accepted",
    "proposal_rejected",
    "proposal_resolved",
    "proposal_closed",
    "requirement_amended",
    "requirement_revision_proposed",
    "support_edge_recorded",
    "authority_resolution_recorded",
    "authority_resolved",
    "requirement_revision_authorized",
    "node_marked_suspect",
    "plan_region_suspect_resolved",
    "node_suspect_resolved",
    "plan_region_suspect_cleared",
    "node_suspect_cleared",
}


def test_replay_only_event_types_are_not_canonical() -> None:
    assert not REMOVED_EVENT_TYPES & CANONICAL_EVENT_TYPES
    assert EXTERNAL_EVENT_TYPES == frozenset({"lease_suspended"})


def test_graph_fixtures_only_use_canonical_events() -> None:
    fixture_types: set[str] = set()
    for path in Path("tests/fixtures/graph").glob("*.yaml"):
        scenarios = yaml.safe_load(path.read_text())
        for scenario in scenarios:
            for section in ("given_events", "then_events"):
                for event in scenario.get(section, []):
                    fixture_types.update(event)
    assert fixture_types <= CANONICAL_EVENT_TYPES


def test_event_factory_rejects_unregistered_internal_event() -> None:
    with pytest.raises(ValueError, match="unregistered event type"):
        validate_emitted_event_type("graph_command_factory", "unregistered_event")


def test_event_ownership_rejects_a_stale_registered_event() -> None:
    stale_registry = {
        **INTERNAL_EVENT_TYPES_BY_PRODUCER,
        "record_decision": frozenset({"stale_event"}),
    }

    with pytest.raises(ValueError, match="stale_event"):
        validate_event_ownership(stale_registry, CANONICAL_EVENT_TYPES)


def test_event_ownership_rejects_a_canonical_event_omission() -> None:
    incomplete_registry = {
        **INTERNAL_EVENT_TYPES_BY_PRODUCER,
        "graph_command_factory": (
            INTERNAL_EVENT_TYPES_BY_PRODUCER["graph_command_factory"]
            - {"authority_decision_recorded"}
        ),
    }

    with pytest.raises(ValueError, match="authority_decision_recorded"):
        validate_event_ownership(incomplete_registry, CANONICAL_EVENT_TYPES)


def test_removed_event_types_have_no_internal_producer_owner() -> None:
    owned_event_types = frozenset().union(*INTERNAL_EVENT_TYPES_BY_PRODUCER.values())
    assert not REMOVED_EVENT_TYPES & owned_event_types
