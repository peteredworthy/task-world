"""Projector protocol and registry for event-driven read-model maintenance."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import ProjectionCheckpointModel
from orchestrator.time_utils import format_utc_datetime
from orchestrator.workflow import (
    RunCreated,
    WorkflowEvent,
    expand_run_snapshot_for_projection,
)

logger = logging.getLogger(__name__)


def _expand_events_for_projection(events: Sequence[WorkflowEvent]) -> list[WorkflowEvent]:
    expanded: list[WorkflowEvent] = []
    for event in events:
        expanded.append(event)
        if isinstance(event, RunCreated) and event.run_snapshot:
            expanded.extend(expand_run_snapshot_for_projection(event))
    return expanded


@runtime_checkable
class Projector(Protocol):
    """Protocol for event-driven read-model projectors."""

    handled_events: frozenset[type]

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        """Apply a single event to the read model."""
        ...

    async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:
        """Replay a full event stream to rebuild the read model from scratch."""
        ...


class ProjectionRegistry:
    """Registers projectors and coordinates event dispatch and rebuild.

    Registered as a post-append listener on SqliteEventStore so projectors
    run synchronously after every append within the same session.
    """

    def __init__(self) -> None:
        self._projectors: list[Projector] = []

    def register(self, projector: Projector) -> None:
        self._projectors.append(projector)

    @property
    def projector_count(self) -> int:
        """Number of registered projectors."""
        return len(self._projectors)

    async def __call__(
        self,
        stored_events: list[Any],
        session: AsyncSession,
        workflow_events: list[WorkflowEvent],
    ) -> None:
        """Dispatch a batch of appended events to all registered projectors.

        Projector exceptions propagate and abort the append transaction,
        maintaining the consistency guarantee that the event log and read-model
        tables are always in sync.
        """
        handled_by: dict[str, int] = {}

        projection_events = _expand_events_for_projection(workflow_events)
        for event in projection_events:
            for projector in self._projectors:
                if type(event) in projector.handled_events:
                    await projector.handle(event, session)
                    name = type(projector).__name__
                    handled_by[name] = handled_by.get(name, 0) + 1

        if stored_events and handled_by:
            last_position: int = stored_events[-1].position
            now = format_utc_datetime(datetime.now(timezone.utc))
            for projector in self._projectors:
                name = type(projector).__name__
                if name not in handled_by:
                    continue
                existing = await session.get(ProjectionCheckpointModel, name)
                if existing is None:
                    session.add(
                        ProjectionCheckpointModel(
                            projector_name=name,
                            last_position=last_position,
                            updated_at=now,
                        )
                    )
                else:
                    existing.last_position = last_position
                    existing.updated_at = now

    async def rebuild_all(
        self,
        all_events: Sequence[WorkflowEvent],
        session: AsyncSession,
    ) -> None:
        """Replay the full event stream through all projectors.

        Resets all checkpoints to 0 before replaying.
        """
        for projector in self._projectors:
            name = type(projector).__name__
            existing = await session.get(ProjectionCheckpointModel, name)
            if existing is not None:
                existing.last_position = 0
                existing.updated_at = format_utc_datetime(datetime.now(timezone.utc))
            await projector.rebuild(_expand_events_for_projection(all_events), session)
