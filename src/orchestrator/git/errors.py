"""Git-related error types."""


class GitError(Exception):
    """Base class for git errors."""


class WorktreeError(GitError):
    """Error related to worktree operations."""


class WorktreeExistsError(WorktreeError):
    def __init__(self, run_id: str, path: str) -> None:
        self.run_id = run_id
        self.path = path
        super().__init__(f"Worktree for run {run_id} already exists at {path}")


class WorktreeNotFoundError(WorktreeError):
    def __init__(self, run_id: str, path: str) -> None:
        self.run_id = run_id
        self.path = path
        super().__init__(f"Worktree for run {run_id} not found at {path}")


class GitCommandError(GitError):
    def __init__(self, command: str, returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Git command failed (exit {returncode}): {command}\n{stderr}")


class WorktreeResetError(WorktreeError):
    def __init__(self, worktree_path: str, message: str) -> None:
        self.worktree_path = worktree_path
        self.message = message
        super().__init__(f"Failed to reset worktree at {worktree_path}: {message}")


class WorktreeCommitError(WorktreeError):
    def __init__(self, worktree_path: str, message: str) -> None:
        self.worktree_path = worktree_path
        self.message = message
        super().__init__(f"Failed to commit worktree changes at {worktree_path}: {message}")


class BranchError(GitError):
    """Base class for branch-related errors."""


class BranchSafetyError(BranchError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class BranchNotFoundError(BranchError):
    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(f"Branch not found: {branch}")


class MergeConflictError(BranchError):
    def __init__(
        self, source: str, target: str, conflicting_files: list[str] | None = None
    ) -> None:
        self.source = source
        self.target = target
        self.conflicting_files = conflicting_files or []
        files_str = ", ".join(self.conflicting_files) if self.conflicting_files else "unknown"
        super().__init__(f"Merge conflict merging {source} into {target}: {files_str}")


class DirtyWorkingTreeError(BranchError):
    def __init__(self, branch: str, dirty_files: list[str]) -> None:
        self.branch = branch
        self.dirty_files = dirty_files
        super().__init__(f"Working tree has {len(dirty_files)} uncommitted change(s) on {branch}")
