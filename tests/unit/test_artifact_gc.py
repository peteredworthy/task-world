import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from orchestrator.artifacts import FilesystemArtifactStore, StoredArtifactRef
from orchestrator.artifacts.gc import collect_artifact_refs, sweep_artifacts
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from tests.unit.graph_test_utils import canonical_event_payload


class NestedEvidence(BaseModel):
    ref: StoredArtifactRef | None = None
    children: list[object] = []


@pytest.mark.asyncio
async def test_collects_only_typed_stored_artifact_references(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    retained = await store.put(b"retained", media_type="text/plain")
    untyped_hash = "sha256:" + "f" * 64

    graph_event = EventEnvelope(
        event_id="output-1",
        run_id="run-1",
        position=1,
        event_type="output_record_accepted",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(
            "output_record_accepted",
            {
                "record_id": "check-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-node",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-1",
                "task_region_id": "region-1",
                "attempt_number": 1,
                "value": {
                    "status": "passed",
                    "classification": "passed",
                    "command_id": "check",
                    "command_text": "true",
                    "command": {"id": "check", "cmd": "true", "timeout_seconds": 1},
                    "worktree_path": "/tmp/worktree",
                    "base_snapshot_id": "snapshot-1",
                    "execution_id": "execution-1",
                    "duration_ms": 1,
                    "stdout_tail": "tail",
                    "stdout_ref": retained.model_dump(mode="json"),
                    "stderr_tail": "",
                    "stderr_ref": None,
                    "stdout_truncated": True,
                    "stderr_truncated": False,
                    "timeout_seconds": 1,
                    "environment_policy": {"cwd": "/tmp/worktree", "env": "inherited"},
                },
            },
        ),
    )

    refs = collect_artifact_refs(
        [NestedEvidence(ref=retained, children=[{"content_hash": untyped_hash}]), graph_event]
    )

    assert refs == frozenset({retained.content_hash})


@pytest.mark.asyncio
async def test_sweep_preserves_retained_and_grace_period_blobs_and_ignores_malformed_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(root)
    retained = await store.put(b"retained", media_type="text/plain")
    young = await store.put(b"young", media_type="text/plain")
    old = await store.put(b"old", media_type="text/plain")
    now = datetime(2026, 1, 2, tzinfo=UTC)
    for ref, age in (
        (retained, timedelta(days=2)),
        (young, timedelta(days=1)),
        (old, timedelta(days=2)),
    ):
        path = root / "sha256" / ref.content_hash[7:9] / ref.content_hash[9:]
        timestamp = (now - age).timestamp()
        path.touch()
        path.chmod(0o600)
        os.utime(path, (timestamp, timestamp))
    malformed = root / "sha256" / "zz" / "not-a-digest"
    malformed.parent.mkdir(parents=True)
    malformed.write_bytes(b"leave me")

    deleted = await sweep_artifacts(root, now, frozenset({retained.content_hash}))
    repeated = await sweep_artifacts(root, now, frozenset({retained.content_hash}))

    assert deleted == frozenset({old.content_hash})
    assert repeated == frozenset()
    assert await store.read(retained) == b"retained"
    assert await store.read(young) == b"young"
    assert malformed.exists()
