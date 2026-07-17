import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from orchestrator.artifacts import (
    ArtifactGarbageCollectionError,
    FilesystemArtifactStore,
    StoredArtifactRef,
)
from orchestrator.artifacts.gc import (
    ArtifactGarbageCollector,
    collect_artifact_refs,
    sweep_artifacts,
)
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


@pytest.mark.asyncio
async def test_sweep_ignores_symlinked_sha256_root_and_prefix_directories(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    root = tmp_path / "artifacts"
    outside_root = tmp_path / "outside-root"
    outside_root.mkdir()
    root.mkdir()
    root_sha256 = root / "sha256"
    root_sha256.symlink_to(outside_root, target_is_directory=True)
    root_blob = outside_root / "aa" / ("a" * 62)
    root_blob.parent.mkdir()
    root_blob.write_bytes(b"outside-root")
    old_timestamp = (now - timedelta(days=2)).timestamp()
    os.utime(root_blob, (old_timestamp, old_timestamp))

    assert await sweep_artifacts(root, now, frozenset()) == frozenset()
    assert root_blob.exists()

    root_sha256.unlink()
    root_sha256.mkdir()
    outside_prefix = tmp_path / "outside-prefix"
    outside_prefix.mkdir()
    prefix_blob = outside_prefix / ("b" * 62)
    prefix_blob.write_bytes(b"outside-prefix")
    os.utime(prefix_blob, (old_timestamp, old_timestamp))
    (root_sha256 / "bb").symlink_to(outside_prefix, target_is_directory=True)

    assert await sweep_artifacts(root, now, frozenset()) == frozenset()
    assert prefix_blob.exists()


@pytest.mark.asyncio
async def test_sweep_ignores_nonregular_entry_at_valid_cas_path(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    candidate = root / "sha256" / "cc" / ("c" * 62)
    candidate.mkdir(parents=True)

    assert await sweep_artifacts(root, datetime(2026, 1, 2, tzinfo=UTC), frozenset()) == frozenset()
    assert candidate.is_dir()


@pytest.mark.asyncio
async def test_collector_rejects_unknown_and_malformed_graph_events_before_sweeping(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(root)
    orphan = await store.put(b"orphan", media_type="text/plain")
    blob = root / "sha256" / orphan.content_hash[7:9] / orphan.content_hash[9:]
    old_timestamp = (datetime(2026, 1, 2, tzinfo=UTC) - timedelta(days=2)).timestamp()
    os.utime(blob, (old_timestamp, old_timestamp))
    unknown = EventEnvelope(
        event_id="unknown-1",
        run_id="run-1",
        position=1,
        event_type="unknown_event",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload={},
    )
    malformed = unknown.model_copy(update={"event_type": "output_record_accepted", "payload": {}})
    collector = ArtifactGarbageCollector(root)

    for event in (unknown, malformed):
        with pytest.raises(ArtifactGarbageCollectionError):
            await collector.collect([event], datetime(2026, 1, 2, tzinfo=UTC))
        assert blob.exists()
