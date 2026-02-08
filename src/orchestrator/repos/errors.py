"""Errors for repos module."""


class RepoNotFoundError(Exception):
    """Raised when a requested repository is not found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Repository not found: {name}")


class BranchNotFoundError(Exception):
    """Raised when a requested branch is not found."""

    def __init__(self, repo_name: str, branch_name: str) -> None:
        self.repo_name = repo_name
        self.branch_name = branch_name
        super().__init__(f"Branch '{branch_name}' not found in repository '{repo_name}'")
