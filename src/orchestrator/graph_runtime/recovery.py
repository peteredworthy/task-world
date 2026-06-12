"""Startup recovery for graph event log and outbox state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model
from orchestrator.graph_runtime.controller import rebuild_projection
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem
from orchestrator.graph_runtime.store import GraphEventStore


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
    pending_before = await dispatcher.pending_items()
    pending_cleanups = [item for item in pending_before if item.kind == "snapshot_cleanup"]
    redispatched = await dispatcher.dispatch_pending()

    awaiting_start_ack: list[dict[str, object]] = []
    awaiting_callback: list[dict[str, object]] = []
    async with session_factory() as session:
        store = GraphEventStore(session)
        run_ids = [run_id] if run_id is not None else await _run_ids(session)
        for current_run_id in run_ids:
            events = await store.read_run(current_run_id)
            projection = rebuild_projection(events)
            for lease in projection["leases"].values():
                if lease.get("state") != "active":
                    continue
                node_id = lease.get("node_id")
                node_state = projection["node_states"].get(str(node_id))
                record: dict[str, object] = {
                    "run_id": current_run_id,
                    "lease_id": str(lease.get("lease_id")),
                    "node_id": str(node_id),
                    "generation": int(lease.get("generation", 0)),
                    "execution_id": str(lease.get("execution_id", "")),
                }
                if node_state == "leased":
                    record["classification"] = "awaiting_start_ack"
                    awaiting_start_ack.append(record)
                elif node_state == "running":
                    record["classification"] = "awaiting_callback"
                    awaiting_callback.append(record)

    if not redispatched and pending_before:
        redispatched = []
    return RecoveryReport(
        redispatched=redispatched,
        pending_cleanups=pending_cleanups,
        awaiting_start_ack=awaiting_start_ack,
        awaiting_callback=awaiting_callback,
    )


async def _run_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(select(distinct(EventV2Model.aggregate_id)))
    return [str(value) for value in result.scalars()]
