"""Typed runtime errors for graph persistence and outbox dispatch."""


class GraphRuntimeError(Exception):
    """Base class for graph runtime failures."""


class StaleProjectionError(GraphRuntimeError):
    """Raised when a command appends against a stale run-local position."""


class InvalidGraphEventPayloadError(GraphRuntimeError):
    """Raised when a catalog-owned event payload fails strict validation at append."""


class EventPayloadCorruptionError(GraphRuntimeError):
    def __init__(self, run_id: str, position: int, event_type: str, detail: str) -> None:
        self.run_id = run_id
        self.position = position
        self.event_type = event_type
        self.detail = detail
        super().__init__(
            f"corrupt graph payload for run {run_id} at position {position} ({event_type}): {detail}"
        )


class IncompatibleGraphPayloadGenerationError(GraphRuntimeError):
    def __init__(self, run_id: str, position: int, generation: int | None) -> None:
        self.run_id = run_id
        self.position = position
        self.generation = generation
        super().__init__(
            f"incompatible graph payload generation for run {run_id} at position {position}: "
            f"expected 2, found {generation!r}"
        )


class OutboxAppendError(GraphRuntimeError):
    """Raised when side-effect intent cannot be written atomically."""


class CompromisedFileStateError(GraphRuntimeError):
    """Raised when runtime dispatch would consume a compromised file-state record."""
