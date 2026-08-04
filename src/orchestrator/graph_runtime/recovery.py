"""Startup recovery for graph event log and outbox state."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model
from orchestrator.graph import (
    execution_attempts_view,
    leases_view,
    node_states_view,
    run_state,
    GraphCommandContext,
)
from orchestrator.graph_runtime.controller import GraphController
from orchestrator.graph_runtime.errors import StaleProjectionError
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem
from orchestrator.graph_runtime.store import GRAPH_AGGREGATE_PREFIX, GraphEventStore

_TERMINAL_RUN_STATES = {"cancelled", "completed", "failed"}
RECOVERY_MAINTENANCE_RUN_PAGE_LIMIT = 100


def _empty_owned_attempts() -> list[dict[str, object]]:
    return []


@dataclass(frozen=True)
class RecoveryReport:
    redispatched: list[OutboxItem]
    pending_cleanups: list[OutboxItem]
    awaiting_start_ack: list[dict[str, object]]
    awaiting_callback: list[dict[str, object]]
    owned_attempts: list[dict[str, object]] = field(default_factory=_empty_owned_attempts)
    processed_run_ids: tuple[str, ...] = ()
    has_more: bool = False
    next_run_id: str | None = None


async def recover(
    session_factory: async_sessionmaker[AsyncSession],
    dispatcher: OutboxDispatcher,
    *,
    run_id: str | None = None,
    maintenance: bool = False,
    after_run_id: str | None = None,
    limit: int = RECOVERY_MAINTENANCE_RUN_PAGE_LIMIT,
) -> RecoveryReport:
    """Rebuild one run, or one explicitly requested bounded maintenance page."""
    if run_id is not None and (maintenance or after_run_id is not None):
        raise ValueError("single-run recovery cannot use maintenance pagination")
    if run_id is None and not maintenance:
        raise ValueError("unscoped recovery requires maintenance=True")
    if not 1 <= limit <= RECOVERY_MAINTENANCE_RUN_PAGE_LIMIT:
        raise ValueError(
            "maintenance recovery limit must be between 1 and "
            f"{RECOVERY_MAINTENANCE_RUN_PAGE_LIMIT}"
        )

    awaiting_start_ack: list[dict[str, object]] = []
    awaiting_callback: list[dict[str, object]] = []
    owned_attempts: list[dict[str, object]] = []
    terminal_run_ids: set[str] = set()
    async with session_factory() as session:
        store = GraphEventStore(session)
        if run_id is not None:
            run_ids = (run_id,)
            has_more = False
            next_run_id = None
        else:
            run_ids, has_more, next_run_id = await _run_ids_page(
                session,
                after_run_id=after_run_id,
                limit=limit,
            )
        for current_run_id in run_ids:
            projection, _, _ = await store.load_projection_with_tail(current_run_id)
            terminal = run_state(projection) in _TERMINAL_RUN_STATES
            if terminal:
                terminal_run_ids.add(current_run_id)
            # Active lease attempts are already represented in the legacy
            # liveness report below.  Add only inactive/revoked ownership here:
            # otherwise a newly dispatched active runner can race startup
            # reconciliation of its own fresh baseline.
            for attempt in execution_attempts_view(projection).values():
                lease = leases_view(projection).get(attempt.lease_id)
                if lease is None or lease.state != "active":
                    owned_attempts.append(
                        {"run_id": current_run_id, "execution_id": attempt.execution_id}
                    )
            # Terminal histories have an ownership-only recovery pass.  They
            # must never be treated as liveness work that could schedule an
            # agent after cancellation/failure/completion.
            if terminal:
                continue
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

    pending_before: list[OutboxItem] = []
    redispatched: list[OutboxItem] = []
    for current_run_id in run_ids:
        await dispatcher.requeue_failed_snapshot_cleanups_for_startup(
            run_id=current_run_id,
            immediate=current_run_id in terminal_run_ids,
        )
        pending_before.extend(await dispatcher.pending_items(run_id=current_run_id))
        redispatched.extend(
            await dispatcher.dispatch_pending(
                run_id=current_run_id,
                # Terminal recovery can only restore/delete owned snapshots.
                # In particular, it never redelivers agent_dispatch.
                allowed_kinds=(
                    frozenset({"snapshot_cleanup", "snapshot_publish", "runner_recovery"})
                    if current_run_id in terminal_run_ids
                    else None
                ),
            )
        )
    pending_cleanups = [item for item in pending_before if item.kind == "snapshot_cleanup"]
    return RecoveryReport(
        redispatched=redispatched,
        pending_cleanups=pending_cleanups,
        awaiting_start_ack=awaiting_start_ack,
        awaiting_callback=awaiting_callback,
        owned_attempts=owned_attempts,
        processed_run_ids=run_ids,
        has_more=has_more,
        next_run_id=next_run_id,
    )


async def reconcile_graph(
    controller: GraphController,
    *,
    run_id: str,
) -> None:
    """Run the kernel recovery escape hatch for active graph runs."""
    # Recovery dispatch can append an acknowledgement between rebuilding the
    # projection and committing reconciliation.  Rebuild once from that durable
    # acknowledgement rather than abandoning recovery and leaving a dead lease.
    for _ in range(2):
        projection = await controller.read_projection(run_id)
        if run_state(projection) != "active":
            return
        position = await controller.current_position(run_id)
        try:
            await controller.handle_command(
                run_id,
                position,
                "reconcile",
                context=GraphCommandContext(
                    run_id=run_id,
                    current_graph_position=position,
                ),
            )
            return
        except StaleProjectionError:
            continue


async def _run_ids_page(
    session: AsyncSession,
    *,
    after_run_id: str | None,
    limit: int,
) -> tuple[tuple[str, ...], bool, str | None]:
    """Read one deterministic maintenance page without materializing all runs."""
    aggregate_id = EventV2Model.aggregate_id
    statement = (
        select(distinct(aggregate_id))
        .where(aggregate_id.like(f"{GRAPH_AGGREGATE_PREFIX}%"))
        .order_by(aggregate_id)
        .limit(limit + 1)
    )
    if after_run_id is not None:
        statement = statement.where(aggregate_id > f"{GRAPH_AGGREGATE_PREFIX}{after_run_id}")
    result = await session.execute(statement)
    page = tuple(str(value).removeprefix(GRAPH_AGGREGATE_PREFIX) for value in result.scalars())
    has_more = len(page) > limit
    run_ids = page[:limit]
    return run_ids, has_more, run_ids[-1] if has_more else None
