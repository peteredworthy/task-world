"""Tests for environment file store."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.envfiles.errors import SnapshotNotFoundError
from orchestrator.envfiles.models import (
    EnvFileSpec,
    SnapshotManifest,
    SnapshotPoint,
    SnapshotPointType,
)
from orchestrator.envfiles.store import EnvFileStore


def test_capture_and_restore(tmp_path: Path) -> None:
    """Test capturing a snapshot and restoring it."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("SECRET=abc")

    specs = [EnvFileSpec(relative_path=".env")]
    point = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )
    assert point.files == [".env"]
    assert point.snapshot_id == "run_start"
    assert point.run_id == "run-1"
    assert point.point_type == SnapshotPointType.RUN_START

    # Modify worktree
    (worktree / ".env").write_text("SECRET=corrupted")

    # Restore requires manifest
    manifest = SnapshotManifest(
        run_id="run-1",
        env_file_specs=specs,
        snapshots=[point],
    )
    store.save_manifest(manifest)

    # Restore
    restored = store.restore_snapshot("run-1", "run_start", worktree)
    assert restored == [".env"]
    assert (worktree / ".env").read_text() == "SECRET=abc"


def test_ingest_from_source(tmp_path: Path) -> None:
    """Test ingesting files from a source directory."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    source = tmp_path / "my-env-dir"
    source.mkdir()
    (source / ".env").write_text("KEY=val")

    specs = [EnvFileSpec(relative_path=".env")]
    ingested = store.ingest_source("run-1", source, specs)
    assert ingested == [".env"]

    # Verify file was copied into run_start snapshot
    snap_dir = store.snapshot_dir("run-1", "run_start")
    assert (snap_dir / ".env").read_text() == "KEY=val"


def test_copy_back_to_different_location(tmp_path: Path) -> None:
    """Test copying files back to a directory different from source."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("FINAL=value")

    specs = [EnvFileSpec(relative_path=".env")]
    point = store.capture_snapshot("run-1", "run_end", SnapshotPointType.RUN_END, worktree, specs)

    # Save manifest so copy_back can find the point
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir=str(worktree),
        env_file_specs=specs,
        snapshots=[point],
    )
    store.save_manifest(manifest)

    # Copy back to a completely different directory
    target = tmp_path / "deploy-server" / "config"
    copied = store.copy_back("run-1", "run_end", target)
    assert copied == [".env"]
    assert (target / ".env").read_text() == "FINAL=value"


def test_manifest_save_and_load(tmp_path: Path) -> None:
    """Test manifest round-trip serialization."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")

    specs = [
        EnvFileSpec(relative_path=".env", promote_on_success=True),
        EnvFileSpec(relative_path="config.yaml", promote_on_success=False),
    ]

    point1 = SnapshotPoint(
        snapshot_id="run_start",
        point_type=SnapshotPointType.RUN_START,
        run_id="run-1",
        task_id=None,
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        files=[".env", "config.yaml"],
    )

    point2 = SnapshotPoint(
        snapshot_id="task-T01_start",
        point_type=SnapshotPointType.TASK_START,
        run_id="run-1",
        task_id="T01",
        timestamp=datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
        files=[".env"],
    )

    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir="/home/user/secrets",
        env_file_specs=specs,
        snapshots=[point1, point2],
    )

    store.save_manifest(manifest)
    loaded = store.load_manifest("run-1")

    assert loaded.run_id == "run-1"
    assert loaded.source_dir == "/home/user/secrets"
    assert len(loaded.env_file_specs) == 2
    assert loaded.env_file_specs[0].relative_path == ".env"
    assert loaded.env_file_specs[0].promote_on_success is True
    assert len(loaded.snapshots) == 2
    assert loaded.snapshots[0].snapshot_id == "run_start"
    assert loaded.snapshots[1].task_id == "T01"


def test_promote_to_canonical(tmp_path: Path) -> None:
    """Test promoting files to canonical store on successful run."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("API_KEY=prod123")
    (worktree / "config.yaml").write_text("debug: false")

    specs = [
        EnvFileSpec(relative_path=".env", promote_on_success=True),
        EnvFileSpec(relative_path="config.yaml", promote_on_success=False),
    ]

    # Capture run_end snapshot
    store.capture_snapshot("run-1", "run_end", SnapshotPointType.RUN_END, worktree, specs)

    # Promote
    promoted = store.promote_to_canonical("run-1", "proj-1", specs)

    assert promoted == [".env"]  # Only promote_on_success=True files

    canonical = store.canonical_dir("proj-1")
    assert (canonical / ".env").read_text() == "API_KEY=prod123"
    assert not (canonical / "config.yaml").exists()


def test_load_canonical(tmp_path: Path) -> None:
    """Test loading canonical files into a worktree."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")

    # Setup canonical files
    canonical = store.canonical_dir("proj-1")
    canonical.mkdir(parents=True)
    (canonical / ".env").write_text("CANONICAL=value")

    worktree = tmp_path / "worktree"
    worktree.mkdir()

    specs = [EnvFileSpec(relative_path=".env")]
    loaded = store.load_canonical("proj-1", specs, worktree)

    assert loaded == [".env"]
    assert (worktree / ".env").read_text() == "CANONICAL=value"


def test_delete_run_snapshots(tmp_path: Path) -> None:
    """Test cleanup of run snapshots."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("SECRET=abc")

    specs = [EnvFileSpec(relative_path=".env")]
    store.capture_snapshot("run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs)

    run_dir = store.run_dir("run-1")
    assert run_dir.exists()

    store.delete_run_snapshots("run-1")
    assert not run_dir.exists()


def test_capture_missing_file_skipped(tmp_path: Path) -> None:
    """Test that files which don't exist are skipped during capture."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("EXISTS=yes")
    # missing.conf does not exist

    specs = [
        EnvFileSpec(relative_path=".env"),
        EnvFileSpec(relative_path="missing.conf"),
    ]

    point = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )

    assert point.files == [".env"]  # Only existing file captured


def test_restore_specific_files(tmp_path: Path) -> None:
    """Test selective restore of specific files from a snapshot."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("SECRET=original")
    (worktree / "config.yaml").write_text("port: 8000")

    specs = [
        EnvFileSpec(relative_path=".env"),
        EnvFileSpec(relative_path="config.yaml"),
    ]

    point = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )

    manifest = SnapshotManifest(
        run_id="run-1",
        env_file_specs=specs,
        snapshots=[point],
    )
    store.save_manifest(manifest)

    # Modify both files
    (worktree / ".env").write_text("SECRET=corrupted")
    (worktree / "config.yaml").write_text("port: 9999")

    # Restore only .env
    restored = store.restore_snapshot("run-1", "run_start", worktree, files=[".env"])

    assert restored == [".env"]
    assert (worktree / ".env").read_text() == "SECRET=original"
    assert (worktree / "config.yaml").read_text() == "port: 9999"  # Unchanged


def test_inject_into_worktree(tmp_path: Path) -> None:
    """Test inject_into_worktree as an alias for restore_snapshot."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=value")

    specs = [EnvFileSpec(relative_path=".env")]
    point = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )

    manifest = SnapshotManifest(
        run_id="run-1",
        env_file_specs=specs,
        snapshots=[point],
    )
    store.save_manifest(manifest)

    # Remove the file from worktree
    (worktree / ".env").unlink()

    # Inject
    injected = store.inject_into_worktree("run-1", "run_start", worktree)

    assert injected == [".env"]
    assert (worktree / ".env").read_text() == "KEY=value"


def test_snapshot_not_found_error(tmp_path: Path) -> None:
    """Test that SnapshotNotFoundError is raised for missing snapshots."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(SnapshotNotFoundError) as exc_info:
        store.load_manifest("nonexistent-run")

    assert exc_info.value.run_id == "nonexistent-run"
    assert exc_info.value.snapshot_id == "manifest"

    # Create manifest but try to restore nonexistent snapshot
    manifest = SnapshotManifest(
        run_id="run-1",
        env_file_specs=[],
        snapshots=[],
    )
    store.save_manifest(manifest)

    with pytest.raises(SnapshotNotFoundError) as exc_info:
        store.restore_snapshot("run-1", "missing_snapshot", worktree)

    assert exc_info.value.snapshot_id == "missing_snapshot"


def test_nested_file_paths(tmp_path: Path) -> None:
    """Test that nested file paths are handled correctly."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    # Create nested directory structure
    (worktree / "config" / "local").mkdir(parents=True)
    (worktree / "config" / "local" / "secrets.yaml").write_text("api_key: secret123")

    specs = [EnvFileSpec(relative_path="config/local/secrets.yaml")]
    point = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )

    assert point.files == ["config/local/secrets.yaml"]

    # Verify file exists in snapshot
    snap_dir = store.snapshot_dir("run-1", "run_start")
    assert (snap_dir / "config" / "local" / "secrets.yaml").read_text() == "api_key: secret123"


def test_multiple_snapshots_in_manifest(tmp_path: Path) -> None:
    """Test handling multiple snapshots in a single run."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("VERSION=1")

    specs = [EnvFileSpec(relative_path=".env")]

    # Capture run_start
    point1 = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )

    # Modify and capture task_start
    (worktree / ".env").write_text("VERSION=2")
    point2 = store.capture_snapshot(
        "run-1", "task-T01_start", SnapshotPointType.TASK_START, worktree, specs, task_id="T01"
    )

    # Modify and capture task_end
    (worktree / ".env").write_text("VERSION=3")
    point3 = store.capture_snapshot(
        "run-1", "task-T01_end", SnapshotPointType.TASK_END, worktree, specs, task_id="T01"
    )

    manifest = SnapshotManifest(
        run_id="run-1",
        env_file_specs=specs,
        snapshots=[point1, point2, point3],
    )
    store.save_manifest(manifest)

    # Restore each snapshot and verify content
    (worktree / ".env").write_text("VERSION=corrupted")

    store.restore_snapshot("run-1", "run_start", worktree)
    assert (worktree / ".env").read_text() == "VERSION=1"

    store.restore_snapshot("run-1", "task-T01_start", worktree)
    assert (worktree / ".env").read_text() == "VERSION=2"

    store.restore_snapshot("run-1", "task-T01_end", worktree)
    assert (worktree / ".env").read_text() == "VERSION=3"


def test_empty_env_specs(tmp_path: Path) -> None:
    """Test handling runs with no env file specs."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    specs: list[EnvFileSpec] = []
    point = store.capture_snapshot(
        "run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs
    )

    assert point.files == []


def test_load_canonical_nonexistent_project(tmp_path: Path) -> None:
    """Test load_canonical returns empty list when project has no canonical files."""
    store = EnvFileStore(base_dir=tmp_path / "env-store")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    specs = [EnvFileSpec(relative_path=".env")]
    loaded = store.load_canonical("nonexistent-project", specs, worktree)

    assert loaded == []
