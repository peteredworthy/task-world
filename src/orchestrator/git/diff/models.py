"""Pydantic models for git diff operations."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


# From diff_models.py (Phase 0)
class FileStatus(str, Enum):
    """Status of a modified file."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class ModifiedFile(BaseModel):
    """A file that has been modified in a branch."""

    path: str
    status: FileStatus
    additions: int
    deletions: int


class CommitInfo(BaseModel):
    """Information about a git commit."""

    sha: str
    short_sha: str
    message: str
    author: str
    timestamp: datetime


# From review/models.py
class DiffScope(str, Enum):
    """Scope of a diff operation."""

    FILE = "file"
    BRANCH = "branch"
    COMMIT = "commit"


class DiffResult(BaseModel):
    """Result of a diff operation."""

    raw_diff: str
    file_path: str | None = None
    scope: DiffScope = DiffScope.BRANCH
