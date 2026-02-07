"""Schemas for env file API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ManagedFileInfo(BaseModel):
    """Info about a managed env file."""

    path: str
    promote_on_success: bool = False


class SnapshotInfo(BaseModel):
    """Info about a snapshot point."""

    snapshot_id: str
    type: str
    task_id: str | None = None
    timestamp: str
    files: list[str] = Field(default_factory=list)


class RevertEnvFileRequest(BaseModel):
    """Request to revert env files to a snapshot."""

    revert_to: str  # "task_start" or "run_start"
    task_id: str  # Currently active task
    worktree_path: str  # Path to the worktree
    files: list[str] | None = None  # Specific files to revert, None = all


class RevertEnvFileResponse(BaseModel):
    """Response from reverting env files."""

    reverted_to: str
    files_restored: list[str] = Field(default_factory=list)


class EnvFileListResponse(BaseModel):
    """Response listing managed env files."""

    managed_files: list[ManagedFileInfo] = []
    snapshots: list[SnapshotInfo] = []


class CopyBackRequest(BaseModel):
    """Request to copy env files back to a target directory."""

    target_dir: str
    snapshot_id: str = "run_end"
    files: list[str] | None = None


class CopyBackResponse(BaseModel):
    """Response from copying env files back."""

    target_dir: str
    files_copied: list[str] = Field(default_factory=list)
