"""Scaffolding module for copying template files to worktrees."""

from orchestrator.scaffolding.copier import copy_scaffolding, ensure_gitignore
from orchestrator.scaffolding.errors import ScaffoldingError
from orchestrator.scaffolding.models import ScaffoldingSpec

__all__ = [
    "copy_scaffolding",
    "ensure_gitignore",
    "ScaffoldingError",
    "ScaffoldingSpec",
]
