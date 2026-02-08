"""Models for scaffolding module."""

from pydantic import BaseModel


class ScaffoldingSpec(BaseModel):
    """Specification for scaffolding to copy to a worktree."""

    source_path: str  # Relative path in routine directory (e.g., "routines/feature-x/scaffolding/")
    target_dir: str = ".orchestrator/scaffolding"  # Target directory in worktree


class ScaffoldingResult(BaseModel):
    """Result of a scaffolding copy operation."""

    files_copied: int
    target_path: str
    gitignore_updated: bool
