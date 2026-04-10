"""Scaffolding module for copying template files to worktrees."""

from orchestrator.runners.scaffolding.copier import copy_scaffolding, ensure_gitignore
from orchestrator.runners.scaffolding.errors import ScaffoldingError
from orchestrator.runners.scaffolding.models import ScaffoldingSpec
from orchestrator.runners.scaffolding.routine_files import (
    RoutineFilesResult,
    copy_routine_files_git,
    copy_routine_files_local,
)

__all__ = [
    "RoutineFilesResult",
    "copy_routine_files_git",
    "copy_routine_files_local",
    "copy_scaffolding",
    "ensure_gitignore",
    "ScaffoldingError",
    "ScaffoldingSpec",
]
