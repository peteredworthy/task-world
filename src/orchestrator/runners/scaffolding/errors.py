"""Errors for scaffolding module."""


class ScaffoldingError(Exception):
    """Base error for scaffolding operations."""

    pass


class ScaffoldingNotFoundError(ScaffoldingError):
    """Scaffolding directory not found in routine."""

    def __init__(self, routine_path: str, scaffolding_path: str) -> None:
        self.routine_path = routine_path
        self.scaffolding_path = scaffolding_path
        super().__init__(
            f"Scaffolding not found at '{scaffolding_path}' for routine '{routine_path}'"
        )


class ScaffoldingCopyError(ScaffoldingError):
    """Error copying scaffolding files."""

    def __init__(self, source: str, target: str, reason: str) -> None:
        self.source = source
        self.target = target
        self.reason = reason
        super().__init__(f"Failed to copy scaffolding from '{source}' to '{target}': {reason}")
