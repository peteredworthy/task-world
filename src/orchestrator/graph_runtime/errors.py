"""Typed runtime errors for graph persistence and outbox dispatch."""


class GraphRuntimeError(Exception):
    """Base class for graph runtime failures."""


class StaleProjectionError(GraphRuntimeError):
    """Raised when a command appends against a stale run-local position."""


class CommittedJournalDeliveryError(GraphRuntimeError):
    """Graph events committed but their journal secondary output still failed."""


class OutboxAppendError(GraphRuntimeError):
    """Raised when side-effect intent cannot be written atomically."""


class CompromisedFileStateError(GraphRuntimeError):
    """Raised when runtime dispatch would consume a compromised file-state record."""
