"""Scaffolding module for copying template files to worktrees."""

from orchestrator.runners.scaffolding.copier import copy_scaffolding, ensure_gitignore
from orchestrator.runners.scaffolding.errors import ScaffoldingError
from orchestrator.runners.scaffolding.models import ScaffoldingSpec

__all__ = [
    "copy_scaffolding",
    "ensure_gitignore",
    "ScaffoldingError",
    "ScaffoldingSpec",
]
