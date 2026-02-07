"""Artifact models for tracking generated files across steps."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Artifact(BaseModel):
    """A tracked artifact produced by a step."""

    id: str
    run_id: str
    step_id: str
    task_id: str
    path: str  # Relative path within worktree
    content_hash: str
    created_at: datetime
    version: int  # Incremented on updates
    metadata: dict[str, Any] = {}
