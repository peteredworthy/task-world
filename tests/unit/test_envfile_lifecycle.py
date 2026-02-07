"""Unit tests for EnvFileLifecycle."""

import pytest
from pathlib import Path

from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.envfiles.models import EnvFileSpec, SnapshotPointType
from orchestrator.envfiles.store import EnvFileStore


@pytest.fixture
def store(tmp_path: Path) -> EnvFileStore:
    """Create an EnvFileStore with a temp base directory."""
    return EnvFileStore(base_dir=tmp_path / "store")


@pytest.fixture
def lifecycle(store: EnvFileStore) -> EnvFileLifecycle:
    """Create an EnvFileLifecycle instance."""
    return EnvFileLifecycle(store=store)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """Create a worktree directory."""
    wt = tmp_path / "worktree"
    wt.mkdir(parents=True, exist_ok=True)
    return wt


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Create a source directory with test env files."""
    src = tmp_path / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / ".env").write_text("API_KEY=secret123\n")
    (src / "nested" / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (src / "nested" / "config.yaml").write_text("db: postgres\n")
    return src


@pytest.fixture
def env_specs() -> list[EnvFileSpec]:
    """Standard env specs for testing."""
    return [
        EnvFileSpec(relative_path=".env", promote_on_success=True),
        EnvFileSpec(relative_path="nested/config.yaml", promote_on_success=False),
    ]


@pytest.mark.asyncio
async def test_on_run_start_with_source_dir_injects_files(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """on_run_start with source_dir injects files into worktree."""
    run_id = "run-001"
    project_id = "proj-a"

    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Verify files are in worktree
    assert (worktree / ".env").read_text() == "API_KEY=secret123\n"
    assert (worktree / "nested" / "config.yaml").read_text() == "db: postgres\n"

    # Verify manifest created
    manifest = store.load_manifest(run_id)
    assert manifest.run_id == run_id
    assert manifest.source_dir == str(source_dir)
    assert len(manifest.snapshots) == 1
    assert manifest.snapshots[0].snapshot_id == "run_start"
    assert manifest.snapshots[0].point_type == SnapshotPointType.RUN_START
    assert set(manifest.snapshots[0].files) == {".env", "nested/config.yaml"}


@pytest.mark.asyncio
async def test_on_run_start_without_source_dir_loads_from_canonical(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """on_run_start without source_dir loads from canonical."""
    run_id = "run-002"
    project_id = "proj-a"

    # Pre-populate canonical store
    canon_dir = store.canonical_dir(project_id)
    canon_dir.mkdir(parents=True, exist_ok=True)
    (canon_dir / ".env").write_text("CANONICAL_KEY=value\n")
    (canon_dir / "nested").mkdir(parents=True, exist_ok=True)
    (canon_dir / "nested" / "config.yaml").write_text("db: mysql\n")

    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=None,
    )

    # Verify files loaded from canonical
    assert (worktree / ".env").read_text() == "CANONICAL_KEY=value\n"
    assert (worktree / "nested" / "config.yaml").read_text() == "db: mysql\n"

    # Verify manifest created
    manifest = store.load_manifest(run_id)
    assert manifest.source_dir is None
    assert len(manifest.snapshots) == 1
    assert manifest.snapshots[0].snapshot_id == "run_start"


@pytest.mark.asyncio
async def test_on_task_start_captures_snapshot(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """on_task_start captures snapshot."""
    run_id = "run-003"
    project_id = "proj-a"
    task_id = "T01"

    # Setup run
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Modify files
    (worktree / ".env").write_text("API_KEY=modified\n")

    await lifecycle.on_task_start(run_id=run_id, task_id=task_id, worktree_path=worktree)

    # Verify snapshot captured
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 2
    task_snap = manifest.snapshots[1]
    assert task_snap.snapshot_id == "task-T01_start"
    assert task_snap.point_type == SnapshotPointType.TASK_START
    assert task_snap.task_id == task_id

    # Verify snapshot contains modified content
    store.restore_snapshot(run_id, "task-T01_start", worktree)
    assert (worktree / ".env").read_text() == "API_KEY=modified\n"


@pytest.mark.asyncio
async def test_on_task_end_captures_snapshot(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """on_task_end captures snapshot."""
    run_id = "run-004"
    project_id = "proj-a"
    task_id = "T01"

    # Setup run
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    await lifecycle.on_task_start(run_id=run_id, task_id=task_id, worktree_path=worktree)

    # Modify files
    (worktree / ".env").write_text("API_KEY=task_complete\n")

    await lifecycle.on_task_end(run_id=run_id, task_id=task_id, worktree_path=worktree)

    # Verify snapshot captured
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 3
    task_end_snap = manifest.snapshots[2]
    assert task_end_snap.snapshot_id == "task-T01_end"
    assert task_end_snap.point_type == SnapshotPointType.TASK_END
    assert task_end_snap.task_id == task_id


@pytest.mark.asyncio
async def test_on_run_end_with_success_promotes_to_canonical(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """on_run_end with success promotes to canonical."""
    run_id = "run-005"
    project_id = "proj-a"

    # Setup run
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Modify files
    (worktree / ".env").write_text("API_KEY=final\n")
    (worktree / "nested" / "config.yaml").write_text("db: sqlite\n")

    await lifecycle.on_run_end(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        success=True,
    )

    # Verify run_end snapshot captured
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 2
    assert manifest.snapshots[1].snapshot_id == "run_end"
    assert manifest.snapshots[1].point_type == SnapshotPointType.RUN_END

    # Verify only promote_on_success=True files are promoted
    canon_dir = store.canonical_dir(project_id)
    assert (canon_dir / ".env").read_text() == "API_KEY=final\n"
    # nested/config.yaml has promote_on_success=False, so should not be promoted
    assert not (canon_dir / "nested" / "config.yaml").exists()


@pytest.mark.asyncio
async def test_on_run_end_without_success_does_not_promote(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """on_run_end without success does NOT promote."""
    run_id = "run-006"
    project_id = "proj-a"

    # Setup run
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Modify files
    (worktree / ".env").write_text("API_KEY=failed\n")

    await lifecycle.on_run_end(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        success=False,
    )

    # Verify run_end snapshot captured
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 2
    assert manifest.snapshots[1].snapshot_id == "run_end"

    # Verify canonical store is empty
    canon_dir = store.canonical_dir(project_id)
    assert not (canon_dir / ".env").exists()


@pytest.mark.asyncio
async def test_all_methods_noop_when_env_specs_empty(
    lifecycle: EnvFileLifecycle, worktree: Path
) -> None:
    """All methods are no-op when env_specs is empty."""
    run_id = "run-007"
    project_id = "proj-a"
    task_id = "T01"

    # on_run_start with empty env_specs
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=[],
        source_dir=None,
    )

    # Should not create manifest
    with pytest.raises(Exception):
        lifecycle.store.load_manifest(run_id)

    # on_task_start/end should be no-op
    await lifecycle.on_task_start(run_id=run_id, task_id=task_id, worktree_path=worktree)
    await lifecycle.on_task_end(run_id=run_id, task_id=task_id, worktree_path=worktree)

    # on_run_end should be no-op
    await lifecycle.on_run_end(
        run_id=run_id, project_id=project_id, worktree_path=worktree, success=True
    )


@pytest.mark.asyncio
async def test_all_methods_noop_when_manifest_missing(
    lifecycle: EnvFileLifecycle, worktree: Path
) -> None:
    """All methods (except on_run_start) are no-op when manifest doesn't exist."""
    run_id = "run-008"
    task_id = "T01"
    project_id = "proj-a"

    # Task lifecycle methods should silently return when manifest missing
    await lifecycle.on_task_start(run_id=run_id, task_id=task_id, worktree_path=worktree)
    await lifecycle.on_task_end(run_id=run_id, task_id=task_id, worktree_path=worktree)
    await lifecycle.on_run_end(
        run_id=run_id, project_id=project_id, worktree_path=worktree, success=True
    )

    # No manifest should exist
    with pytest.raises(Exception):
        lifecycle.store.load_manifest(run_id)


@pytest.mark.asyncio
async def test_full_lifecycle_integration(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Full lifecycle: run_start -> task_start -> modify -> task_end -> task_start -> verify state -> run_end."""
    run_id = "run-009"
    project_id = "proj-a"

    # Step 1: Start run
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )
    assert (worktree / ".env").read_text() == "API_KEY=secret123\n"

    # Step 2: Start task T01
    await lifecycle.on_task_start(run_id=run_id, task_id="T01", worktree_path=worktree)
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 2

    # Step 3: Modify files during task
    (worktree / ".env").write_text("API_KEY=t01_modified\n")

    # Step 4: End task T01
    await lifecycle.on_task_end(run_id=run_id, task_id="T01", worktree_path=worktree)
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 3

    # Step 5: Start task T02
    await lifecycle.on_task_start(run_id=run_id, task_id="T02", worktree_path=worktree)
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 4

    # Verify T02 sees the modified state from T01
    assert (worktree / ".env").read_text() == "API_KEY=t01_modified\n"

    # Step 6: Modify during T02
    (worktree / ".env").write_text("API_KEY=t02_modified\n")

    # Step 7: End task T02
    await lifecycle.on_task_end(run_id=run_id, task_id="T02", worktree_path=worktree)
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 5

    # Step 8: End run with success
    await lifecycle.on_run_end(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        success=True,
    )

    # Verify final state
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 6
    snapshot_ids = [s.snapshot_id for s in manifest.snapshots]
    assert snapshot_ids == [
        "run_start",
        "task-T01_start",
        "task-T01_end",
        "task-T02_start",
        "task-T02_end",
        "run_end",
    ]

    # Verify promotion
    canon_dir = store.canonical_dir(project_id)
    assert (canon_dir / ".env").read_text() == "API_KEY=t02_modified\n"
