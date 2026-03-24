"""Integration tests for env file revert API."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import EnvFileSpec
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.models import (
    SnapshotManifest,
    SnapshotPoint,
    SnapshotPointType,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def env_store(tmp_path: Path) -> EnvFileStore:
    return EnvFileStore(base_dir=tmp_path / "env-store")


@pytest.fixture
async def client(tmp_path: Path, env_store: EnvFileStore) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:", routine_dirs=[(FIXTURES, RoutineSource.LOCAL)])
    app.state.envfile_store = env_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_env_files_api(
    client: AsyncClient, env_store: EnvFileStore, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=val")

    specs = [EnvFileSpec(relative_path=".env")]
    env_store.capture_snapshot("run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs)
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir=str(worktree),
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
    env_store.save_manifest(manifest)

    resp = await client.get("/api/runs/run-1/env-files")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["managed_files"]) == 1


async def test_revert_env_files_api(
    client: AsyncClient, env_store: EnvFileStore, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=original")

    specs = [EnvFileSpec(relative_path=".env")]
    env_store.capture_snapshot(
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
                files=[".env"],
            ),
        ],
    )
    env_store.save_manifest(manifest)

    (worktree / ".env").write_text("KEY=corrupted")

    resp = await client.post(
        "/api/runs/run-1/env-files/revert",
        json={
            "revert_to": "task_start",
            "task_id": "T01",
            "worktree_path": str(worktree),
        },
    )
    assert resp.status_code == 200
    assert (worktree / ".env").read_text() == "KEY=original"


async def test_list_snapshots_api(
    client: AsyncClient, env_store: EnvFileStore, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("KEY=val")

    specs = [EnvFileSpec(relative_path=".env")]
    env_store.capture_snapshot("run-1", "run_start", SnapshotPointType.RUN_START, worktree, specs)
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir="/original",
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
    env_store.save_manifest(manifest)

    resp = await client.get("/api/runs/run-1/env-files/snapshots")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_dir"] == "/original"
    assert len(data["snapshots"]) == 1


async def test_copy_back_api(client: AsyncClient, env_store: EnvFileStore, tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".env").write_text("FINAL=value")

    specs = [EnvFileSpec(relative_path=".env")]
    env_store.capture_snapshot("run-1", "run_end", SnapshotPointType.RUN_END, worktree, specs)
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir=str(worktree),
        env_file_specs=specs,
        snapshots=[
            SnapshotPoint(
                snapshot_id="run_end",
                point_type=SnapshotPointType.RUN_END,
                run_id="run-1",
                timestamp=datetime.now(timezone.utc),
                files=[".env"],
            ),
        ],
    )
    env_store.save_manifest(manifest)

    target = tmp_path / "deploy"
    resp = await client.post(
        "/api/runs/run-1/env-files/copy-back",
        json={
            "target_dir": str(target),
            "snapshot_id": "run_end",
        },
    )
    assert resp.status_code == 200
    assert (target / ".env").read_text() == "FINAL=value"


async def test_default_target_api(
    client: AsyncClient, env_store: EnvFileStore, tmp_path: Path
) -> None:
    manifest = SnapshotManifest(
        run_id="run-1",
        source_dir="/original/source",
        env_file_specs=[EnvFileSpec(relative_path=".env")],
    )
    env_store.save_manifest(manifest)

    resp = await client.get("/api/runs/run-1/env-files/default-target")
    assert resp.status_code == 200
    assert resp.json()["default_target"] == "/original/source"
