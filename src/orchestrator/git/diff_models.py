"""Phase 0 artifact: Pydantic models for git diff operations.

This module re-exports the models from git/diff/models.py for backwards compatibility
and to mark completion of Phase 0.
"""

from orchestrator.git.diff.models import (
    CommitInfo,
    DiffResult,
    DiffScope,
    FileStatus,
    ModifiedFile,
)

__all__ = [
    "CommitInfo",
    "DiffResult",
    "DiffScope",
    "FileStatus",
    "ModifiedFile",
]
