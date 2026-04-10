"""Unit tests for env file cleanup."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.cleanup import EnvFileCleanup


def test_cleanup_orphaned_snapshots(tmp_path: Path) -> None:
    """Remove dirs for runs not in active set."""
    store = EnvFileStore(base_dir=tmp_path)
    (tmp_path / "run-1").mkdir()
    (tmp_path / "run-2").mkdir()
    (tmp_path / "canonical").mkdir()

    cleanup = EnvFileCleanup(store)
    removed = cleanup.cleanup_deleted_runs(active_run_ids={"run-1"})
    assert removed == 1
    assert (tmp_path / "run-1").exists()
    assert not (tmp_path / "run-2").exists()
    assert (tmp_path / "canonical").exists()


def test_cleanup_preserves_all_active(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path)
    (tmp_path / "run-1").mkdir()
    (tmp_path / "run-2").mkdir()

    cleanup = EnvFileCleanup(store)
    removed = cleanup.cleanup_deleted_runs(active_run_ids={"run-1", "run-2"})
    assert removed == 0


def test_cleanup_empty_store(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path)
    cleanup = EnvFileCleanup(store)
    removed = cleanup.cleanup_deleted_runs(active_run_ids=set())
    assert removed == 0


def test_cleanup_old_snapshots(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path)

    # Old run (40 days ago)
    old_run = tmp_path / "old-run"
    old_run.mkdir()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    (old_run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "old-run",
                "snapshots": [
                    {
                        "timestamp": old_ts,
                        "snapshot_id": "run_end",
                        "point_type": "run_end",
                        "run_id": "old-run",
                        "files": [],
                    }
                ],
            }
        )
    )

    # Recent run (5 days ago)
    recent_run = tmp_path / "recent-run"
    recent_run.mkdir()
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    (recent_run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "recent-run",
                "snapshots": [
                    {
                        "timestamp": recent_ts,
                        "snapshot_id": "run_end",
                        "point_type": "run_end",
                        "run_id": "recent-run",
                        "files": [],
                    }
                ],
            }
        )
    )

    (tmp_path / "canonical").mkdir()

    cleanup = EnvFileCleanup(store, retention=timedelta(days=30))
    removed = cleanup.cleanup_old_snapshots()
    assert removed == 1
    assert not old_run.exists()
    assert recent_run.exists()
    assert (tmp_path / "canonical").exists()


def test_cleanup_skips_dirs_without_manifest(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path)
    (tmp_path / "no-manifest-run").mkdir()

    cleanup = EnvFileCleanup(store)
    removed = cleanup.cleanup_old_snapshots()
    assert removed == 0
    assert (tmp_path / "no-manifest-run").exists()


def test_cleanup_nonexistent_base(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "nonexistent")
    cleanup = EnvFileCleanup(store)
    removed = cleanup.cleanup_deleted_runs(active_run_ids=set())
    assert removed == 0
