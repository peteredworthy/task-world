"""Environment file error types."""


class EnvFileError(Exception):
    """Base class for env file errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class SnapshotNotFoundError(EnvFileError):
    """Raised when a snapshot cannot be found."""

    def __init__(self, run_id: str, snapshot_id: str) -> None:
        self.run_id = run_id
        self.snapshot_id = snapshot_id
        super().__init__(f"Snapshot '{snapshot_id}' not found for run '{run_id}'")
