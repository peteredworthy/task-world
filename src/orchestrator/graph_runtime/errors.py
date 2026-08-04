"""Typed runtime errors for graph persistence and outbox dispatch."""


class GraphRuntimeError(Exception):
    """Base class for graph runtime failures."""


class StaleProjectionError(GraphRuntimeError):
    """Raised when a command appends against a stale run-local position."""


class OutboxAppendError(GraphRuntimeError):
    """Raised when side-effect intent cannot be written atomically."""


class CompromisedFileStateError(GraphRuntimeError):
    """Raised when runtime dispatch would consume a compromised file-state record."""


class CacheScanBudgetExceededError(GraphRuntimeError):
    """Raised before cache descendant inspection exceeds compiled authority."""

    def __init__(
        self,
        *,
        metric: str,
        limit: int,
        observed: int,
        path: str,
    ) -> None:
        self.metric = metric
        self.limit = limit
        self.observed = observed
        self.path = path
        super().__init__(
            f"cache scan {metric} budget exceeded at {path!r}: limit={limit}, observed={observed}"
        )


class RecoveryEventError(GraphRuntimeError):
    """Raised when a durable recovery request is missing or malformed."""


class RecoveryRestoreError(GraphRuntimeError):
    """Raised when selective restoration from the durable baseline fails."""


class RecoveryCompletionRejectedError(GraphRuntimeError):
    """Raised when the kernel rejects durable recovery completion accounting."""


class ProcessQuiescenceError(GraphRuntimeError):
    """Raised when an owned runner cannot be stopped before recovery."""
