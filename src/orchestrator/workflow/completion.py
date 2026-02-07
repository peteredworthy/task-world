"""Completion handling for runs.

This module handles worktree cleanup when a run completes.
"""

from orchestrator.git.errors import WorktreeNotFoundError
from orchestrator.git.worktree import WorktreeManager
from orchestrator.state.models import Run


def handle_run_completion(
    run: Run,
    worktree_manager: WorktreeManager,
) -> None:
    """Handle cleanup when a run completes.

    Args:
        run: The run that has completed
        worktree_manager: Manager for git worktree operations

    Raises:
        WorktreeNotFoundError: If worktree is configured but not found (suppressed)
    """
    if not run.worktree_path:
        return

    if run.delete_worktree_on_completion:
        try:
            worktree_manager.delete(run.id, force=True)
        except WorktreeNotFoundError:
            # Worktree already removed or never existed, no action needed
            pass
