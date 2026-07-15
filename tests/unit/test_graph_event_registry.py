from pathlib import Path

import yaml

from orchestrator.graph import CANONICAL_EVENT_TYPES, EXTERNAL_EVENT_TYPES


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
