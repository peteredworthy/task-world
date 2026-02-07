"""Pydantic models for environment file management."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SnapshotPointType(str, Enum):
    """Type of snapshot point in the run lifecycle."""

    RUN_START = "run_start"
    TASK_START = "task_start"
    TASK_END = "task_end"
    RUN_END = "run_end"


class EnvFileSpec(BaseModel):
    """Declares a file to be managed outside git."""

    relative_path: str
    promote_on_success: bool = False


class SnapshotPoint(BaseModel):
    """Metadata for a single snapshot."""

    snapshot_id: str
    point_type: SnapshotPointType
    run_id: str
    task_id: str | None = None
    timestamp: datetime
    files: list[str] = Field(default_factory=list)


class SnapshotManifest(BaseModel):
    """Index of all snapshots for a run."""

    run_id: str
    source_dir: str | None = None
    env_file_specs: list[EnvFileSpec] = Field(default_factory=lambda: list[EnvFileSpec]())
    snapshots: list[SnapshotPoint] = Field(default_factory=lambda: list[SnapshotPoint]())
