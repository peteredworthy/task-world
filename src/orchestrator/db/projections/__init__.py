"""Projection framework: Projector protocol and ProjectionRegistry."""

from orchestrator.db.projections.registry import Projector, ProjectionRegistry
from orchestrator.db.projections.run_lifecycle import RunLifecycleProjector
from orchestrator.db.projections.run_state import RunStateProjector
from orchestrator.db.projections.task_state import TaskStateProjector

__all__ = [
    "Projector",
    "ProjectionRegistry",
    "RunLifecycleProjector",
    "RunStateProjector",
    "TaskStateProjector",
]
