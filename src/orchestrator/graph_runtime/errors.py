"""Typed runtime errors for graph persistence and outbox dispatch."""

from typing import Any


class GraphRuntimeError(Exception):
    """Base class for graph runtime failures."""


class SubmissionQualityGateError(GraphRuntimeError, ValueError):
    """Raised before staging when authoritative validation does not pass."""

    def __init__(self, message: str, *, report: Any | None = None) -> None:
        self.report = report
        super().__init__(message)


class InvalidExecutionContractError(SubmissionQualityGateError):
    """Raised when immutable node execution authority is malformed."""


class StaleProjectionError(GraphRuntimeError):
    """Raised when a command appends against a stale run-local position."""


class PatchOperationConflictError(GraphRuntimeError, ValueError):
    """Raised when a semantic operation key is reused with different intent."""


class GraphEventEnvelopeTooLargeError(GraphRuntimeError):
    """Raised when a complete serialized event exceeds the write contract."""

    def __init__(self, *, event_type: str, observed_bytes: int, limit_bytes: int) -> None:
        self.event_type = event_type
        self.observed_bytes = observed_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"graph event {event_type!r} is {observed_bytes} bytes; maximum is {limit_bytes} bytes"
        )


class OutboxAppendError(GraphRuntimeError):
    """Raised when side-effect intent cannot be written atomically."""


class CompromisedFileStateError(GraphRuntimeError):
    """Raised when runtime dispatch would consume a compromised file-state record."""


class CacheScanBudgetExceededError(GraphRuntimeError):
    """Historical v1 cache-scan failure retained for durable replay/readback."""

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


class RunnerProcessMissingError(GraphRuntimeError):
    """Raised when a dispatched runner's verified process identity disappears."""
