"""Pydantic domain models for the review subsystem."""

from enum import Enum

from pydantic import BaseModel


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
