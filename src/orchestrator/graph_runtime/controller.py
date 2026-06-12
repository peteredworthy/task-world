"""Effectful graph controller wrapper around the pure command kernel."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjection,
    apply_command,
    initial_projection,
    reduce_event,
)
from orchestrator.graph.commands import Clock, IdGenerator
from orchestrator.graph_runtime.errors import StaleProjectionError
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem, append_outbox_rows
from orchestrator.graph_runtime.store import GraphEventStore


@dataclass(frozen=True)
class GraphCommandResult:
    events: list[EventEnvelope]
    outbox_items: list[OutboxItem]
    projection_position: int


class GraphController:
    """Loads graph state, applies pure commands, and commits events plus outbox."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        id_gen: IdGenerator,
        *,
        dispatcher: OutboxDispatcher | None = None,
        auto_dispatch: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_gen = id_gen
        self._dispatcher = dispatcher
        self._auto_dispatch = auto_dispatch

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
    ) -> GraphCommandResult:
        """Apply a command and atomically commit accepted events plus outbox rows."""
        command_payload = dict(payload or {})
        command_payload["run_id"] = run_id
        async with self._session_factory() as session:
            async with session.begin():
                store = GraphEventStore(session)
                existing_events = await store.read_run(run_id)
                current_position = _projection_position(existing_events)
                if current_position != expected_position:
                    msg = (
                        f"stale graph projection for run {run_id}: "
                        f"expected {expected_position}, found {current_position}"
                    )
                    raise StaleProjectionError(msg)

                projection = rebuild_projection(existing_events)
                planned_events = apply_command(
                    projection,
                    existing_events,
                    command_type,
                    command_payload,
                    self._clock,
                    self._id_gen,
                )
                planned_events = self._add_dispatch_intent_events(
                    planned_events,
                    command_type,
                    run_id,
                )
                stored_events = await store.append_events(
                    run_id,
                    expected_position,
                    planned_events,
                )
                outbox_items = await append_outbox_rows(session, stored_events, self._clock)

        if self._dispatcher is not None and self._auto_dispatch and outbox_items:
            await self._dispatcher.dispatch_pending()

        return GraphCommandResult(
            events=stored_events,
            outbox_items=outbox_items,
            projection_position=expected_position + len(stored_events),
        )

    async def current_position(self, run_id: str) -> int:
        """Return the current durable graph position for a run."""
        async with self._session_factory() as session:
            return await GraphEventStore(session).current_position(run_id)

    def _add_dispatch_intent_events(
        self,
        events: list[EventEnvelope],
        command_type: str,
        run_id: str,
    ) -> list[EventEnvelope]:
        """Normalize lease grants into explicit side-effect-intent events.

        The current pure kernel grants leases during ``schedule_tick``. This
        runtime layer adds the PRD §12.3 ``agent_dispatch_requested`` event next
        to each grant, then the outbox mapping keys dispatch by that event id.
        """
        expanded: list[EventEnvelope] = []
        for event in events:
            expanded.append(event)
            if event.event_type != "lease_granted":
                continue
            node_id = event.payload.get("node_id")
            expanded.append(
                EventEnvelope(
                    event_id=self._id_gen.next_id("event"),
                    run_id=run_id,
                    position=-1,
                    event_type="agent_dispatch_requested",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    causation_id=command_type,
                    correlation_id=str(node_id) if isinstance(node_id, str) else None,
                    timestamp=self._clock.now(),
                    payload={
                        "lease_granted_event_id": event.event_id,
                        "lease_id": event.payload.get("lease_id"),
                        "node_id": node_id,
                        "generation": event.payload.get("generation"),
                        "execution_id": event.payload.get("execution_id"),
                        "base_snapshot_id": event.payload.get("base_snapshot_id"),
                        "resource_claims": event.payload.get("resource_claims", []),
                    },
                )
            )
        return expanded


def rebuild_projection(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _projection_position(events: list[EventEnvelope]) -> int:
    if not events:
        return 0
    return max(event.position for event in events)
