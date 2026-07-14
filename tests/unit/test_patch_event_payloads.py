from datetime import UTC, datetime
import inspect

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventMetadata,
    UnknownGraphEventError,
    build_graph_catalog,
    initial_projection,
    reduce_event,
)
from orchestrator.graph.events import patches
from orchestrator.graph.events.patches import (
    EVENT_SPECIFICATIONS,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
)


def test_patch_payload_rejects_misspelled_or_unknown_fields() -> None:
    payload = {
        "patch_id": "patch-1",
        "base_graph_position": 1,
        "actor_role": "planner",
        "proposed_by_node_id": "node-1",
        "successor_planner_node_ids": [],
    }
    assert GraphPatchAcceptedPayload.model_validate(payload).patch_id == "patch-1"
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate({**payload, "base_graph_postion": 1})
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate({**payload, "unknown_field": {}})


def test_only_accepted_and_rejected_patch_events_are_registered() -> None:
    assert {spec.name for spec in EVENT_SPECIFICATIONS} == {
        "graph_patch_accepted",
        "graph_patch_rejected",
    }


def _metadata(event_type: str) -> EventMetadata:
    return EventMetadata(
        event_id=f"event-{event_type}",
        run_id="run-1",
        position=1,
        event_type=event_type,
        payload_schema_generation=2,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_strict_accepted_patch_reducer_does_not_depend_on_legacy_reduction() -> None:
    catalog = build_graph_catalog()
    state = initial_projection()
    state["open_proposal_blockers"]["patch-1"] = {"kind": "open_planner_proposal"}
    payload = GraphPatchAcceptedPayload(
        patch_id="patch-1",
        base_graph_position=0,
        actor_role="planner",
        proposed_by_node_id="planner-1",
        successor_planner_node_ids=["planner-2"],
    )
    event = catalog.resolve_event("graph_patch_accepted").create(
        _metadata("graph_patch_accepted"), payload
    )

    reduced = reduce_event(catalog, state, event)

    assert "reduce_legacy_event" not in inspect.getsource(patches.reduce_graph_patch_accepted)
    assert reduced["open_proposal_blockers"] == {}
    assert reduced["accepted_graph_patches_by_node"] == {"planner-1": ["patch-1"]}
    assert reduced["planner_successors"] == {"planner-1": "planner-2"}


def test_strict_rejected_patch_reducer_does_not_depend_on_legacy_reduction() -> None:
    catalog = build_graph_catalog()
    state = initial_projection()
    state["open_proposal_blockers"]["patch-1"] = {"kind": "open_planner_proposal"}
    payload = GraphPatchRejectedPayload(
        patch_id="patch-1",
        base_graph_position=0,
        actor_role="planner",
        proposed_by_node_id="planner-1",
        reason="stale",
    )
    event = catalog.resolve_event("graph_patch_rejected").create(
        _metadata("graph_patch_rejected"), payload
    )

    reduced = reduce_event(catalog, state, event)

    assert "reduce_legacy_event" not in inspect.getsource(patches.reduce_graph_patch_rejected)
    assert reduced["open_proposal_blockers"] == {}


def test_retired_patch_aliases_are_rejected_by_the_catalog() -> None:
    catalog = build_graph_catalog()
    with pytest.raises(UnknownGraphEventError, match="unknown graph event: graph_patch_proposed"):
        catalog.resolve_event("graph_patch_proposed")
    with pytest.raises(UnknownGraphEventError, match="unknown graph event: proposal_accepted"):
        catalog.resolve_event("proposal_accepted")
