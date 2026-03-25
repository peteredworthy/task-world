"""Workflow-related error types."""


class WorkflowError(Exception):
    """Base class for workflow errors."""


class GateBlockedError(WorkflowError):
    def __init__(self, gate_name: str, blocking_items: list[str]) -> None:
        self.gate_name = gate_name
        self.blocking_items = blocking_items
        super().__init__(f"Gate '{gate_name}' blocked by: {', '.join(blocking_items)}")


class InvalidTransitionError(WorkflowError):
    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status} -> {to_status}")
