"""Unit tests for EnvFileToolExecutor."""

from datetime import datetime, timezone
from pathlib import Path
from orchestrator.config.models import EnvFileSpec
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.tools import EnvFileToolExecutor
from orchestrator.envfiles.models import (
    SnapshotManifest,
    SnapshotPoint,
    SnapshotPointType,
)


async def test_agent_reverts_to_task_start(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=original")

    specs = [EnvFileSpec(relative_path=".env")]
    store.capture_snapshot("run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs)
    store.capture_snapshot(
        "run-1", "task-T01_start", SnapshotPointType.TASK_START, worktree, specs, task_id="T01"
    )
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir=None,
        env_file_specs=specs,
        snapshots=[
            SnapshotPoint(
                snapshot_id="run_start",
                point_type=SnapshotPointType.RUN_START,
                run_id="run-1",
                timestamp=datetime.now(timezone.utc),
                files=[".env"],
            ),
            SnapshotPoint(
                snapshot_id="task-T01_start",
                point_type=SnapshotPointType.TASK_START,
                run_id="run-1",
                task_id="T01",
                timestamp=datetime.now(timezone.utc),
                files=[".env"],
            ),
        ],
    )
    store.save_manifest(manifest)

    (worktree / ".env").write_text("KEY=corrupted")
    result = await executor.revert_env_file("run-1", "T01", worktree, "task_start")
    assert result["files_restored"] == [".env"]
    assert (worktree / ".env").read_text() == "KEY=original"


async def test_agent_reverts_to_run_start(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=original")

    specs = [EnvFileSpec(relative_path=".env")]
    store.capture_snapshot("run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs)
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir=None,
        env_file_specs=specs,
        snapshots=[
            SnapshotPoint(
                snapshot_id="run_start",
                point_type=SnapshotPointType.RUN_START,
                run_id="run-1",
                timestamp=datetime.now(timezone.utc),
                files=[".env"],
            ),
        ],
    )
    store.save_manifest(manifest)

    (worktree / ".env").write_text("KEY=modified")
    result = await executor.revert_env_file("run-1", "T01", worktree, "run_start")
    assert result["files_restored"] == [".env"]
    assert (worktree / ".env").read_text() == "KEY=original"


async def test_agent_reverts_single_file(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("SECRET=a")
    (worktree / "config.local.yaml").write_text("port: 3000")

    specs = [EnvFileSpec(relative_path=".env"), EnvFileSpec(relative_path="config.local.yaml")]
    store.capture_snapshot(
        "run-1", "task-T01_start", SnapshotPointType.TASK_START, worktree, specs, task_id="T01"
    )
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir=None,
        env_file_specs=specs,
        snapshots=[
            SnapshotPoint(
                snapshot_id="task-T01_start",
                point_type=SnapshotPointType.TASK_START,
                run_id="run-1",
                task_id="T01",
                timestamp=datetime.now(timezone.utc),
                files=[".env", "config.local.yaml"],
            ),
        ],
    )
    store.save_manifest(manifest)

    (worktree / ".env").write_text("SECRET=corrupted")
    (worktree / "config.local.yaml").write_text("port: 9999")

    await executor.revert_env_file("run-1", "T01", worktree, "task_start", files=[".env"])
    assert (worktree / ".env").read_text() == "SECRET=a"
    assert (worktree / "config.local.yaml").read_text() == "port: 9999"  # Unchanged


async def test_revert_invalid_revert_to(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    specs = [EnvFileSpec(relative_path=".env")]
    manifest = SnapshotManifest(run_id="run-1", source_dir=None, env_file_specs=specs, snapshots=[])
    store.save_manifest(manifest)

    result = await executor.revert_env_file("run-1", "T01", worktree, "invalid")
    assert "error" in result


async def test_revert_snapshot_not_found(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    specs = [EnvFileSpec(relative_path=".env")]
    manifest = SnapshotManifest(run_id="run-1", source_dir=None, env_file_specs=specs, snapshots=[])
    store.save_manifest(manifest)

    result = await executor.revert_env_file("run-1", "T01", worktree, "task_start")
    assert "error" in result


async def test_list_env_files(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=val")

    specs = [EnvFileSpec(relative_path=".env", promote_on_success=True)]
    store.capture_snapshot("run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs)
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir="/original/source",
        env_file_specs=specs,
        snapshots=[
            SnapshotPoint(
                snapshot_id="run_start",
                point_type=SnapshotPointType.RUN_START,
                run_id="run-1",
                timestamp=datetime.now(timezone.utc),
                files=[".env"],
            ),
        ],
    )
    store.save_manifest(manifest)

    result = await executor.list_env_files("run-1")
    assert len(result["managed_files"]) == 1
    assert result["managed_files"][0]["path"] == ".env"
    assert result["managed_files"][0]["promote_on_success"] is True
    assert len(result["snapshots"]) == 1


async def test_list_env_files_no_manifest(tmp_path: Path) -> None:
    store = EnvFileStore(base_dir=tmp_path / "store")
    executor = EnvFileToolExecutor(store)
    result = await executor.list_env_files("nonexistent-run")
    assert result["managed_files"] == []
    assert result["snapshots"] == []
