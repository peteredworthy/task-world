from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    InputBindingProjection,
    StoredArtifactRef,
    initial_projection,
)
from orchestrator.graph_runtime import (
    GraphDispatchContext,
    hydrate_artifact_excerpt,
    planner_evidence,
)
from tests.unit.graph_test_utils import projection_fixture_set


@pytest.mark.asyncio
async def test_explicit_hydration_decodes_and_bounds_artifact_excerpt(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = await store.put(b"prefix\nabcdef", media_type="text/plain", encoding="utf-8")

    excerpt = await hydrate_artifact_excerpt(store, ref, max_chars=6)

    assert excerpt == "prefix"


@pytest.mark.asyncio
async def test_explicit_hydration_requires_a_typed_reference(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    malformed_ref = StoredArtifactRef.model_construct(
        artifact_id="sha256:" + "0" * 64,
        content_hash="sha256:" + "0" * 64,
        size_bytes=0,
        media_type="text/plain",
        encoding="utf-8",
        storage_uri="artifact://sha256/" + "0" * 64,
    )

    with pytest.raises(ValueError, match="max_chars"):
        await hydrate_artifact_excerpt(store, malformed_ref, max_chars=0)


def test_default_planner_evidence_keeps_check_output_tails_without_references() -> None:
    projection = initial_projection()
    projection = projection_fixture_set(
        projection,
        "input_bindings",
        ("planner-1",),
        {
            "check_result": InputBindingProjection(
                to_node_id="planner-1",
                to_port="check_result",
                record_ids=["check-1"],
                bound_at_position=2,
            )
        },
    )
    record_payload: dict[str, Any] = {
        "record_id": "check-1",
        "record_kind": "output",
        "record_type": "check_result",
        "value": {
            "stdout_tail": "last stdout",
            "stdout_ref": {"content_hash": "sha256:" + "a" * 64},
            "stderr_tail": "last stderr",
            "stderr_ref": {"content_hash": "sha256:" + "b" * 64},
        },
    }
    event = EventEnvelope(
        event_id="check-result-1",
        run_id="run-1",
        position=1,
        event_type="output_record_accepted",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=record_payload,
    )
    context = GraphDispatchContext(
        run_id="run-1",
        node_id="planner-1",
        node_kind="planner",
        node_payload={"node_id": "planner-1", "kind": "planner"},
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-1",
        lease_generation=1,
        execution_id="execution-1",
        base_snapshot_id="snapshot-1",
        dispatch_event_id="dispatch-1",
        graph_projection=projection,
        graph_events=[event],
    )

    evidence = planner_evidence(context, projection, [event])

    value = evidence["bound_records"]["check_result"][0]["record_payload"]["value"]
    assert value == {"stdout_tail": "last stdout", "stderr_tail": "last stderr"}
