"""Schemas for env file API endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from orchestrator.api.schemas.base import ApiModel


class ManagedFileInfo(ApiModel):
    """Info about a managed env file."""

    path: str
    promote_on_success: bool = False


class SnapshotInfo(ApiModel):
    """Info about a snapshot point."""

    snapshot_id: str
    type: str
    task_id: str | None = None
    timestamp: str
    files: list[str] = Field(default_factory=list)


class RevertEnvFileRequest(ApiModel):
    """Request to revert env files to a snapshot."""

    revert_to: Literal["task_start", "run_start"]
    task_id: str  # Currently active task
    worktree_path: str  # Path to the worktree
    files: list[str] | None = None  # Specific files to revert, None = all


class RevertEnvFileResponse(ApiModel):
    """Response from reverting env files."""

    reverted_to: str
    files_restored: list[str] = Field(default_factory=list)


class EnvFileListResponse(ApiModel):
    """Response listing managed env files."""

    managed_files: list[ManagedFileInfo] = []
    snapshots: list[SnapshotInfo] = []


class CopyBackRequest(ApiModel):
    """Request to copy env files back to a target directory."""

    target_dir: str
    snapshot_id: str = Field(default="run_end", pattern=r"^[a-zA-Z0-9_-]+$")
    files: list[str] | None = None


class CopyBackResponse(ApiModel):
    """Response from copying env files back."""

    target_dir: str
    files_copied: list[str] = Field(default_factory=list)
