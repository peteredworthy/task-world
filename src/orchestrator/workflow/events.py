"""Workflow event types for observability."""

from dataclasses import dataclass, field
from datetime import datetime

from orchestrator.config.enums import RunStatus, TaskStatus


@dataclass
class WorkflowEvent:
    """Base workflow event."""

    timestamp: datetime
    run_id: str
    event_type: str


@dataclass
class TaskStatusChanged(WorkflowEvent):
    """Emitted when a task changes status."""

    task_id: str = ""
    old_status: TaskStatus = TaskStatus.PENDING
    new_status: TaskStatus = TaskStatus.PENDING


@dataclass
class RunStatusChanged(WorkflowEvent):
    """Emitted when a run changes status."""

    old_status: RunStatus = RunStatus.DRAFT
    new_status: RunStatus = RunStatus.DRAFT


@dataclass
class ChecklistGateEvaluated(WorkflowEvent):
    """Emitted when a checklist gate is evaluated."""

    task_id: str = ""
    passed: bool = False
    blocking_items: list[str] = field(default_factory=lambda: [])


@dataclass
class GradesEvaluated(WorkflowEvent):
    """Emitted when grades are evaluated."""

    task_id: str = ""
    passed: bool = False
    failing_items: list[str] = field(default_factory=lambda: [])


class BufferingEmitter:
    """Event emitter that buffers events in memory.

    Implements the same interface as the EventEmitter protocol used by WorkflowEngine.
    Events can be retrieved after engine calls for async persistence.
    """

    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def emit(self, event: WorkflowEvent) -> None:
        self.events.append(event)

    def drain(self) -> list[WorkflowEvent]:
        """Return all buffered events and clear the buffer."""
        events = self.events
        self.events = []
        return events
