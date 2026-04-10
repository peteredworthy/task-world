"""Integration tests for env file workflow lifecycle."""

import pytest
from pathlib import Path

from orchestrator.config.models import EnvFileSpec
from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.envfiles.models import SnapshotPointType
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
    """Create a source directory with multiple env files."""
    src = tmp_path / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / ".env").write_text("API_KEY=initial\nDB_HOST=localhost\n")
    (src / ".env.test").write_text("TEST_MODE=true\n")
    (src / "config").mkdir(parents=True, exist_ok=True)
    (src / "config" / "database.yml").write_text("host: localhost\nport: 5432\n")
    return src


@pytest.fixture
def env_specs() -> list[EnvFileSpec]:
    """Standard env specs with mixed promotion settings."""
    return [
        EnvFileSpec(relative_path=".env", promote_on_success=True),
        EnvFileSpec(relative_path=".env.test", promote_on_success=False),
        EnvFileSpec(relative_path="config/database.yml", promote_on_success=True),
    ]


@pytest.mark.asyncio
async def test_full_lifecycle_with_multiple_tasks(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Simulate: run_start → task_start → task_end → task_start → run_end."""
    run_id = "run-full-001"
    project_id = "proj-alpha"

    # === PHASE 1: Run Start ===
    await lifecycle.on_run_start(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Verify initial state
    assert (worktree / ".env").read_text() == "API_KEY=initial\nDB_HOST=localhost\n"
    assert (worktree / ".env.test").read_text() == "TEST_MODE=true\n"
    assert (worktree / "config" / "database.yml").read_text() == "host: localhost\nport: 5432\n"

    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 1
    assert manifest.snapshots[0].point_type == SnapshotPointType.RUN_START

    # === PHASE 2: Task T01 Start ===
    await lifecycle.on_task_start(run_id=run_id, task_id="T01", worktree_path=worktree)

    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 2
    assert manifest.snapshots[1].point_type == SnapshotPointType.TASK_START
    assert manifest.snapshots[1].task_id == "T01"

    # === PHASE 3: Task T01 modifies files ===
    (worktree / ".env").write_text("API_KEY=t01_key\nDB_HOST=t01_host\n")
    (worktree / "config" / "database.yml").write_text("host: t01_db\nport: 3306\n")

    # === PHASE 4: Task T01 End ===
    await lifecycle.on_task_end(run_id=run_id, task_id="T01", worktree_path=worktree)

    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 3
    assert manifest.snapshots[2].point_type == SnapshotPointType.TASK_END
    assert manifest.snapshots[2].task_id == "T01"

    # Verify T01 end snapshot captured modifications
    t01_end_dir = store.snapshot_dir(run_id, "task-T01_end")
    assert (t01_end_dir / ".env").read_text() == "API_KEY=t01_key\nDB_HOST=t01_host\n"

    # === PHASE 5: Task T02 Start ===
    await lifecycle.on_task_start(run_id=run_id, task_id="T02", worktree_path=worktree)

    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 4

    # Verify T02 sees T01's modifications (state carries forward)
    assert (worktree / ".env").read_text() == "API_KEY=t01_key\nDB_HOST=t01_host\n"
    assert (worktree / "config" / "database.yml").read_text() == "host: t01_db\nport: 3306\n"

    # === PHASE 6: Task T02 modifies files ===
    (worktree / ".env").write_text("API_KEY=final\nDB_HOST=prod\n")

    # === PHASE 7: Task T02 End ===
    await lifecycle.on_task_end(run_id=run_id, task_id="T02", worktree_path=worktree)

    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 5

    # === PHASE 8: Run End (success) ===
    await lifecycle.on_run_end(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        success=True,
    )

    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 6
    assert manifest.snapshots[5].point_type == SnapshotPointType.RUN_END

    # Verify final snapshot order
    snapshot_types = [s.point_type for s in manifest.snapshots]
    assert snapshot_types == [
        SnapshotPointType.RUN_START,
        SnapshotPointType.TASK_START,
        SnapshotPointType.TASK_END,
        SnapshotPointType.TASK_START,
        SnapshotPointType.TASK_END,
        SnapshotPointType.RUN_END,
    ]

    # Verify promotion to canonical (only promote_on_success=True files)
    canon_dir = store.canonical_dir(project_id)
    assert (canon_dir / ".env").read_text() == "API_KEY=final\nDB_HOST=prod\n"
    assert (canon_dir / "config" / "database.yml").read_text() == "host: t01_db\nport: 3306\n"
    assert not (canon_dir / ".env.test").exists()  # promote_on_success=False


@pytest.mark.asyncio
async def test_next_task_sees_previous_task_changes(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Task T02 should see files as modified by Task T01."""
    run_id = "run-chain-001"
    project_id = "proj-beta"

    # Start run
    await lifecycle.on_run_start(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    initial_env = (worktree / ".env").read_text()
    assert initial_env == "API_KEY=initial\nDB_HOST=localhost\n"

    # T01: Start, modify, end
    await lifecycle.on_task_start(run_id=run_id, task_id="T01", worktree_path=worktree)
    (worktree / ".env").write_text("API_KEY=changed_by_t01\n")
    (worktree / "config" / "database.yml").write_text("modified: by_t01\n")
    await lifecycle.on_task_end(run_id=run_id, task_id="T01", worktree_path=worktree)

    # T02 should see T01's changes
    await lifecycle.on_task_start(run_id=run_id, task_id="T02", worktree_path=worktree)

    # Verify state carried forward
    assert (worktree / ".env").read_text() == "API_KEY=changed_by_t01\n"
    assert (worktree / "config" / "database.yml").read_text() == "modified: by_t01\n"

    # T02 makes further changes
    (worktree / ".env").write_text("API_KEY=changed_by_t02\n")
    await lifecycle.on_task_end(run_id=run_id, task_id="T02", worktree_path=worktree)

    # T03 should see T02's changes
    await lifecycle.on_task_start(run_id=run_id, task_id="T03", worktree_path=worktree)
    assert (worktree / ".env").read_text() == "API_KEY=changed_by_t02\n"
    assert (worktree / "config" / "database.yml").read_text() == "modified: by_t01\n"

    # Verify we can restore any previous state
    store.restore_snapshot(run_id, "task-T01_end", worktree)
    assert (worktree / ".env").read_text() == "API_KEY=changed_by_t01\n"

    store.restore_snapshot(run_id, "run_start", worktree)
    assert (worktree / ".env").read_text() == "API_KEY=initial\nDB_HOST=localhost\n"


@pytest.mark.asyncio
async def test_no_promotion_on_failure(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Run end with success=False should not update canonical."""
    run_id = "run-fail-001"
    project_id = "proj-gamma"

    # Pre-populate canonical store with "old" values
    canon_dir = store.canonical_dir(project_id)
    canon_dir.mkdir(parents=True, exist_ok=True)
    (canon_dir / ".env").write_text("API_KEY=old_canonical\n")
    (canon_dir / "config").mkdir(parents=True, exist_ok=True)
    (canon_dir / "config" / "database.yml").write_text("host: old_canonical\n")

    # Start run
    await lifecycle.on_run_start(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Task modifies files
    await lifecycle.on_task_start(run_id=run_id, task_id="T01", worktree_path=worktree)
    (worktree / ".env").write_text("API_KEY=new_value\n")
    (worktree / "config" / "database.yml").write_text("host: new_db\n")
    await lifecycle.on_task_end(run_id=run_id, task_id="T01", worktree_path=worktree)

    # Run end with FAILURE
    await lifecycle.on_run_end(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        success=False,
    )

    # Verify run_end snapshot was captured
    manifest = store.load_manifest(run_id)
    run_end_snap = next(s for s in manifest.snapshots if s.point_type == SnapshotPointType.RUN_END)
    assert run_end_snap is not None

    # Verify canonical store was NOT updated (still has old values)
    assert (canon_dir / ".env").read_text() == "API_KEY=old_canonical\n"
    assert (canon_dir / "config" / "database.yml").read_text() == "host: old_canonical\n"


@pytest.mark.asyncio
async def test_snapshot_restoration_at_any_point(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Verify we can restore to any snapshot point for debugging/rollback."""
    run_id = "run-restore-001"
    project_id = "proj-delta"

    # Run lifecycle
    await lifecycle.on_run_start(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    await lifecycle.on_task_start(run_id=run_id, task_id="T01", worktree_path=worktree)
    (worktree / ".env").write_text("STATE=t01_start\n")
    await lifecycle.on_task_end(run_id=run_id, task_id="T01", worktree_path=worktree)

    await lifecycle.on_task_start(run_id=run_id, task_id="T02", worktree_path=worktree)
    (worktree / ".env").write_text("STATE=t02_start\n")
    await lifecycle.on_task_end(run_id=run_id, task_id="T02", worktree_path=worktree)

    await lifecycle.on_run_end(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        success=True,
    )

    # Now test restoration to each point
    manifest = store.load_manifest(run_id)
    assert len(manifest.snapshots) == 6

    # Restore to run_start
    store.restore_snapshot(run_id, "run_start", worktree)
    assert (worktree / ".env").read_text() == "API_KEY=initial\nDB_HOST=localhost\n"

    # Restore to task-T01_end
    store.restore_snapshot(run_id, "task-T01_end", worktree)
    assert (worktree / ".env").read_text() == "STATE=t01_start\n"

    # Restore to task-T02_end
    store.restore_snapshot(run_id, "task-T02_end", worktree)
    assert (worktree / ".env").read_text() == "STATE=t02_start\n"

    # Restore to run_end
    store.restore_snapshot(run_id, "run_end", worktree)
    assert (worktree / ".env").read_text() == "STATE=t02_start\n"


@pytest.mark.asyncio
async def test_lifecycle_with_no_source_dir_uses_canonical(
    lifecycle: EnvFileLifecycle,
    store: EnvFileStore,
    worktree: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Full lifecycle starting from canonical instead of source_dir."""
    run_id = "run-canonical-001"
    project_id = "proj-epsilon"

    # Pre-populate canonical store
    canon_dir = store.canonical_dir(project_id)
    canon_dir.mkdir(parents=True, exist_ok=True)
    (canon_dir / ".env").write_text("API_KEY=from_canonical\n")
    (canon_dir / ".env.test").write_text("TEST_MODE=canonical\n")
    (canon_dir / "config").mkdir(parents=True, exist_ok=True)
    (canon_dir / "config" / "database.yml").write_text("host: canonical_db\n")

    # Start run WITHOUT source_dir
    await lifecycle.on_run_start(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=None,
    )

    # Verify files loaded from canonical
    assert (worktree / ".env").read_text() == "API_KEY=from_canonical\n"
    assert (worktree / ".env.test").read_text() == "TEST_MODE=canonical\n"
    assert (worktree / "config" / "database.yml").read_text() == "host: canonical_db\n"

    # Verify manifest has no source_dir
    manifest = store.load_manifest(run_id)
    assert manifest.source_dir is None

    # Task modifies and ends successfully
    await lifecycle.on_task_start(run_id=run_id, task_id="T01", worktree_path=worktree)
    (worktree / ".env").write_text("API_KEY=updated\n")
    await lifecycle.on_task_end(run_id=run_id, task_id="T01", worktree_path=worktree)

    await lifecycle.on_run_end(
        run_id=run_id,
        repo_name=project_id,
        worktree_path=worktree,
        success=True,
    )

    # Verify canonical was updated
    assert (canon_dir / ".env").read_text() == "API_KEY=updated\n"
