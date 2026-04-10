"""Env file API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from orchestrator.api.deps import get_envfile_store
from orchestrator.api.schemas.envfiles import (
    CopyBackRequest,
    CopyBackResponse,
    RevertEnvFileRequest,
)
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.tools import EnvFileToolExecutor
from orchestrator.time_utils import format_utc_datetime

router = APIRouter(prefix="/api", tags=["envfiles"])


@router.get("/runs/{run_id}/env-files")
async def list_env_files(
    run_id: str,
    store: Annotated[EnvFileStore, Depends(get_envfile_store)],
) -> dict[str, Any]:
    """List managed env files and available snapshots for a run."""
    executor = EnvFileToolExecutor(store)
    return await executor.list_env_files(run_id)


@router.get("/runs/{run_id}/env-files/snapshots")
async def list_snapshots(
    run_id: str,
    store: Annotated[EnvFileStore, Depends(get_envfile_store)],
) -> dict[str, Any]:
    """List all snapshot points for a run."""
    manifest = store.load_manifest(run_id)
    return {
        "source_dir": manifest.source_dir,
        "snapshots": [
            {
                "snapshot_id": s.snapshot_id,
                "type": s.point_type.value,
                "task_id": s.task_id,
                "timestamp": format_utc_datetime(s.timestamp),
                "files": s.files,
            }
            for s in manifest.snapshots
        ],
    }


@router.post("/runs/{run_id}/env-files/revert")
async def revert_env_files(
    run_id: str,
    request: RevertEnvFileRequest,
    store: Annotated[EnvFileStore, Depends(get_envfile_store)],
) -> dict[str, Any]:
    """Revert env files to an earlier snapshot."""
    executor = EnvFileToolExecutor(store)
    return await executor.revert_env_file(
        run_id=run_id,
        task_id=request.task_id,
        worktree_path=Path(request.worktree_path),
        revert_to=request.revert_to,
        files=request.files,
    )


@router.post("/runs/{run_id}/env-files/copy-back")
async def copy_back_env_files(
    run_id: str,
    request: CopyBackRequest,
    store: Annotated[EnvFileStore, Depends(get_envfile_store)],
) -> CopyBackResponse:
    """Copy env files from a run snapshot to a target directory."""
    copied = store.copy_back(
        run_id=run_id,
        snapshot_id=request.snapshot_id,
        target_dir=Path(request.target_dir),
        files=request.files,
    )
    return CopyBackResponse(
        target_dir=request.target_dir,
        files_copied=copied,
    )


@router.get("/runs/{run_id}/env-files/default-target")
async def get_default_copy_back_target(
    run_id: str,
    store: Annotated[EnvFileStore, Depends(get_envfile_store)],
) -> dict[str, Any]:
    """Get the default copy-back target (original source directory)."""
    manifest = store.load_manifest(run_id)
    return {"default_target": manifest.source_dir}
