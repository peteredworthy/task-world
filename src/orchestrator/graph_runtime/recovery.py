"""Startup recovery for graph event log and outbox state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model
from orchestrator.graph import leases_view, node_states_view, run_state, GraphCommandContext
from orchestrator.graph_runtime.controller import GraphController, rebuild_projection
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem
from orchestrator.graph_runtime.store import GRAPH_AGGREGATE_PREFIX, GraphEventStore

_TERMINAL_RUN_STATES = {"cancelled", "completed", "failed"}


@dataclass(frozen=True)
class RecoveryReport:
    redispatched: list[OutboxItem]
    pending_cleanups: list[OutboxItem]
    awaiting_start_ack: list[dict[str, object]]
    awaiting_callback: list[dict[str, object]]


async def recover(
    session_factory: async_sessionmaker[AsyncSession],
    dispatcher: OutboxDispatcher,
    *,
    run_id: str | None = None,
) -> RecoveryReport:
    """Rebuild projections and reconcile in-flight side effects."""
    pending_before = await dispatcher.pending_items(run_id=run_id)
    pending_cleanups = [item for item in pending_before if item.kind == "snapshot_cleanup"]
    redispatched = await dispatcher.dispatch_pending(run_id=run_id)

    awaiting_start_ack: list[dict[str, object]] = []
    awaiting_callback: list[dict[str, object]] = []
    async with session_factory() as session:
        store = GraphEventStore(session)
        run_ids = [run_id] if run_id is not None else await _run_ids(session)
        for current_run_id in run_ids:
            events = await store.read_run(current_run_id)
            projection = rebuild_projection(events)
            for lease in leases_view(projection).values():
                if lease.state != "active":
                    continue
                node_id = lease.node_id
                node_state = node_states_view(projection).get(str(node_id))
                record: dict[str, object] = {
                    "run_id": current_run_id,
                    "lease_id": lease.lease_id,
                    "node_id": str(node_id),
                    "generation": lease.generation or 0,
                    "execution_id": lease.execution_id or "",
                }
                if node_state == "leased":
                    record["classification"] = "awaiting_start_ack"
                    awaiting_start_ack.append(record)
                elif node_state == "running":
                    record["classification"] = "awaiting_callback"
                    awaiting_callback.append(record)

    return RecoveryReport(
        redispatched=redispatched,
        pending_cleanups=pending_cleanups,
        awaiting_start_ack=awaiting_start_ack,
        awaiting_callback=awaiting_callback,
    )


async def reconcile_graph(
    controller: GraphController,
    *,
    run_id: str,
) -> None:
    """Run the kernel recovery escape hatch for active graph runs."""
    projection = await controller.read_projection(run_id)
    if run_state(projection) != "active":
        return
    position = await controller.current_position(run_id)
    await controller.handle_command(
        run_id,
        position,
        "reconcile",
        context=GraphCommandContext(
            run_id=run_id,
            current_graph_position=position,
        ),
    )


async def _run_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(distinct(EventV2Model.aggregate_id)).where(
            EventV2Model.aggregate_id.like(f"{GRAPH_AGGREGATE_PREFIX}%")
        )
    )
    store = GraphEventStore(session)
    run_ids: list[str] = []
    for aggregate_id in result.scalars():
        run_id = str(aggregate_id).removeprefix(GRAPH_AGGREGATE_PREFIX)
        checkpoint = await store.read_projection_checkpoint(run_id)
        if checkpoint is not None and checkpoint.terminal:
            continue
        if checkpoint is None:
            projection, _, _ = await store.load_projection_with_tail(run_id)
            if run_state(projection) in _TERMINAL_RUN_STATES:
                continue
        run_ids.append(run_id)
    return run_ids
