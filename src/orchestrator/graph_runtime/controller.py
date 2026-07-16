"""Effectful graph controller wrapper around the pure command kernel."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCommandContext,
    GraphProjection,
    validate_emitted_event_type,
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
        *,
        context: GraphCommandContext | None = None,
    ) -> GraphCommandResult:
        """Apply a command and atomically commit accepted events plus outbox rows.

        The expensive part of this — reading the full run event log and
        rebuilding the projection — happens BEFORE any write lock is taken.
        Only the cheap position re-check and the append itself run inside the
        ``BEGIN IMMEDIATE`` write transaction, so the write lock is held for a
        bounded, small amount of work regardless of how large the run's event
        log has grown. If the position moved between the pre-read and the
        write (a concurrent writer landed first), this raises
        ``StaleProjectionError`` just like a losing ``append_events`` race
        used to; callers already retry on that (see
        ``dispatch._handle_command_retry_stale`` and
        ``graph_driver._handle_command_at_head``), so correctness is
        preserved by optimistic concurrency. ``append_events`` also performs
        its own ``current_position`` check and the UNIQUE constraint on
        ``(aggregate_id, version)`` is the final backstop, so the invariant
        holds even if two callers somehow race past the explicit check below.
        """
        command_payload = dict(payload or {})

        # Phase 1: load the persisted projection snapshot and fold only the
        # event tail OUTSIDE any write lock. This is the part that can take
        # time on a large graph history, so it must not hold BEGIN IMMEDIATE
        # while it runs.
        async with self._session_factory() as read_session:
            read_store = GraphEventStore(read_session)
            (
                projection,
                existing_events,
                current_position,
            ) = await read_store.load_projection_with_tail(run_id)
        if current_position != expected_position:
            msg = (
                f"stale graph projection for run {run_id}: "
                f"expected {expected_position}, found {current_position}"
            )
            raise StaleProjectionError(msg)

        command_context = context or GraphCommandContext(
            run_id=run_id,
            current_graph_position=current_position,
        )
        if (
            command_context.run_id != run_id
            or command_context.current_graph_position != current_position
        ):
            msg = "command context does not match the loaded graph head"
            raise ValueError(msg)
        command_events = existing_events
        patch_base_position = _patch_base_graph_position(command_type, command_payload)
        if patch_base_position is not None and patch_base_position < current_position:
            async with self._session_factory() as read_session:
                command_events = await GraphEventStore(read_session).read_run(
                    run_id,
                    patch_base_position + 1,
                )
        planned_events = apply_command(
            projection,
            command_events,
            command_type,
            command_payload,
            command_context,
            self._clock,
            self._id_gen,
        )
        planned_events = self._add_dispatch_intent_events(
            planned_events,
            command_type,
            run_id,
        )

        # Phase 2: short write transaction. Re-check the position cheaply
        # (COUNT/MAX query, not a full read) before appending, so a writer
        # that landed between phase 1 and here is detected without ever
        # re-reading the whole event log inside the lock.
        async with self._session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                store = GraphEventStore(session)
                head_position = await store.current_position(run_id)
                if head_position != expected_position:
                    msg = (
                        f"stale graph projection for run {run_id}: "
                        f"expected {expected_position}, found {head_position}"
                    )
                    raise StaleProjectionError(msg)

                stored_events = await store.append_events(
                    run_id,
                    expected_position,
                    planned_events,
                )
                outbox_items = await append_outbox_rows(session, stored_events, self._clock)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

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

    async def read_projection(self, run_id: str) -> GraphProjection:
        """Return the current durable graph projection for a run."""
        async with self._session_factory() as session:
            events = await GraphEventStore(session).read_run(run_id)
        return rebuild_projection(events)

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
            validate_emitted_event_type("graph_runtime_controller", "agent_dispatch_requested")
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


def _patch_base_graph_position(
    command_type: str,
    payload: dict[str, object],
) -> int | None:
    if command_type != "submit_patch":
        return None
    value = payload.get("base_graph_position")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
