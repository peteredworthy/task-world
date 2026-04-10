"""Compatibility shim: exposes ORM models under the src.orchestrator.db.models path.

The canonical module is orchestrator.db.orm.models (importable when src/ is in sys.path).
This file allows imports of the form ``from src.orchestrator.db.models import PendingSignal``
when the project root is the working directory (e.g. auto-verify checks).
"""

from orchestrator.db.orm.models import (  # noqa: F401
    AttemptModel,
    ClarificationRequestModel,
    ClarificationResponseModel,
    EventModel,
    PendingSignalModel as PendingSignal,
    ReplayCheckpointModel,
    RunModel,
    RunnerProfileDefaultModel,
    RoutineMetaModel,
    StepModel,
    TaskModel,
)

__all__ = [
    "AttemptModel",
    "ClarificationRequestModel",
    "ClarificationResponseModel",
    "EventModel",
    "PendingSignal",
    "ReplayCheckpointModel",
    "RunModel",
    "RunnerProfileDefaultModel",
    "RoutineMetaModel",
    "StepModel",
    "TaskModel",
]
