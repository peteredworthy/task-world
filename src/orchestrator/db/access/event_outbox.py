"""Post-commit event outbox helpers for secondary event outputs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import StoredEvent


EventOutboxObserver = Callable[[list["StoredEvent"]], Awaitable[None]]
_SESSION_KEY = "orchestrator_event_outbox"


@dataclass(frozen=True)
class EventOutboxBatch:
    """A post-commit observer invocation queued on a SQLAlchemy session."""

    observer: EventOutboxObserver
    events: list["StoredEvent"]


def queue_event_outbox(
    session: "AsyncSession",
    observer: EventOutboxObserver,
    events: list["StoredEvent"],
) -> None:
    """Queue a secondary event output to run after the session commits."""
    if not events:
        return
    batches = _get_batches(session)
    batches.append(EventOutboxBatch(observer=observer, events=list(events)))


async def commit_with_event_outbox(session: "AsyncSession") -> None:
    """Commit a session, then flush queued secondary event outputs.

    If the database commit fails, queued outbox work is discarded and the
    original commit error is propagated. If a secondary output fails after a
    successful commit, that error is propagated to the caller.
    """
    try:
        await session.commit()
    except Exception:
        clear_event_outbox(session)
        raise
    await flush_event_outbox(session)


async def rollback_with_event_outbox(session: "AsyncSession") -> None:
    """Clear queued secondary event outputs and roll back the session."""
    clear_event_outbox(session)
    await session.rollback()


async def flush_event_outbox(session: "AsyncSession") -> None:
    """Flush queued secondary event outputs in FIFO order."""
    batches = _get_batches(session)
    for batch in batches:
        await batch.observer(batch.events)
    clear_event_outbox(session)


def clear_event_outbox(session: "AsyncSession") -> None:
    """Discard queued secondary event outputs for a session."""
    session.info.pop(_SESSION_KEY, None)


def _get_batches(session: "AsyncSession") -> list[EventOutboxBatch]:
    batches = session.info.setdefault(_SESSION_KEY, [])
    return cast("list[EventOutboxBatch]", batches)
