"""Output line batcher: accumulates AgentOutputEvent lines and flushes in batches."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from orchestrator.workflow import AgentOutputEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.runners.types import BroadcastCallback

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _BufferEntry:
    lines: list[str]
    start_time: float
    next_line_offset: int
    timer_task: asyncio.Task[None] | None = None


class OutputBatcher:
    """Accumulates agent output lines and flushes them as batched AgentOutputEvents.

    Three flush triggers:
    - count threshold: when a buffer accumulates max_lines lines
    - timer threshold: when flush_interval_ms has elapsed since the first line
    - explicit flush: phase boundaries can drain buffered output immediately

    Accepts either a fixed ``event_store`` (for tests) or a ``session_factory``
    (for production, creates a new committed session per flush).
    """

    def __init__(
        self,
        event_store: "SqliteEventStore | None" = None,
        session_factory: "async_sessionmaker[AsyncSession] | None" = None,
        max_lines: int = 50,
        flush_interval_ms: int = 100,
        clock: Callable[[], float] = time.monotonic,
        connection_manager: "BroadcastCallback | None" = None,
    ) -> None:
        self._fixed_store = event_store
        self._session_factory = session_factory
        self._max_lines = max_lines
        self._flush_interval_s = flush_interval_ms / 1000.0
        self._clock = clock
        self._connection_manager = connection_manager
        self._buffer: dict[tuple[str, str, int], _BufferEntry] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def add_line(self, run_id: str, task_id: str, attempt_id: int, text: str) -> None:
        """Accumulate a line; auto-flush when count or time threshold is reached."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("OutputBatcher is closed")
            key = (run_id, task_id, attempt_id)
            if key not in self._buffer:
                self._buffer[key] = _BufferEntry(
                    lines=[],
                    start_time=self._clock(),
                    next_line_offset=0,
                )
            entry = self._buffer[key]
            if not entry.lines:
                entry.start_time = self._clock()
            entry.lines.append(text)
            self._ensure_timer(key, entry)

            now = self._clock()
            count_exceeded = len(entry.lines) >= self._max_lines
            time_exceeded = (now - entry.start_time) >= self._flush_interval_s
            if count_exceeded or time_exceeded:
                self._cancel_timer(entry)
                await self._flush_entry(key, entry)

    async def flush(self) -> None:
        """Flush all buffer entries that meet count or time thresholds; no-op if empty."""
        async with self._lock:
            now = self._clock()
            for key, entry in list(self._buffer.items()):
                if not entry.lines:
                    continue
                count_exceeded = len(entry.lines) >= self._max_lines
                time_exceeded = (now - entry.start_time) >= self._flush_interval_s
                if count_exceeded or time_exceeded:
                    self._cancel_timer(entry)
                    await self._flush_entry(key, entry)

    async def flush_immediate(self) -> None:
        """Flush all non-empty buffers regardless of thresholds."""
        async with self._lock:
            for key, entry in list(self._buffer.items()):
                if entry.lines:
                    self._cancel_timer(entry)
                    await self._flush_entry(key, entry)

    async def close(self) -> None:
        """Flush pending lines and cancel timer work."""
        await self.aclose()

    async def aclose(self) -> None:
        """Flush pending lines and prevent future additions."""
        cancelled_tasks: list[asyncio.Task[None]] = []
        try:
            async with self._lock:
                self._closed = True
                for entry in self._buffer.values():
                    task = self._cancel_timer(entry)
                    if task is not None:
                        cancelled_tasks.append(task)
                for key, entry in list(self._buffer.items()):
                    if entry.lines:
                        await self._flush_entry(key, entry)
        finally:
            if cancelled_tasks:
                await asyncio.gather(*cancelled_tasks, return_exceptions=True)

    def _ensure_timer(self, key: tuple[str, str, int], entry: _BufferEntry) -> None:
        if self._flush_interval_s <= 0:
            return
        if entry.timer_task is not None and not entry.timer_task.done():
            return
        entry.timer_task = asyncio.create_task(self._flush_after_interval(key))

    def _cancel_timer(self, entry: _BufferEntry) -> asyncio.Task[None] | None:
        task = entry.timer_task
        entry.timer_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            return task
        return None

    async def _flush_after_interval(self, key: tuple[str, str, int]) -> None:
        try:
            await asyncio.sleep(self._flush_interval_s)
            async with self._lock:
                entry = self._buffer.get(key)
                if entry is None or not entry.lines or self._closed:
                    return
                entry.timer_task = None
                if (self._clock() - entry.start_time) < self._flush_interval_s:
                    self._ensure_timer(key, entry)
                    return
                await self._flush_entry(key, entry)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Failed to flush batched agent output from timer", exc_info=True)

    async def _flush_entry(self, key: tuple[str, str, int], entry: _BufferEntry) -> None:
        run_id, task_id, attempt_id = key
        lines_to_flush = list(entry.lines)
        event = AgentOutputEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="agent_output",
            task_id=task_id,
            attempt_num=attempt_id,
            lines=lines_to_flush,
            line_offset=entry.next_line_offset,
        )
        if self._fixed_store is not None:
            await self._fixed_store.append(event)
        elif self._session_factory is not None:
            from orchestrator.db import (
                commit_with_event_outbox,
                create_wired_event_store_v2,
            )

            async with self._session_factory() as session:
                store = create_wired_event_store_v2(session)
                await store.append(event)
                await commit_with_event_outbox(session)
        else:
            return  # No store configured; drop silently (test-only path)
        # Clear buffer only after successful append
        entry.lines.clear()
        entry.next_line_offset += len(lines_to_flush)
        entry.start_time = self._clock()
        if self._connection_manager is not None:
            try:
                await self._connection_manager.broadcast_event(event)
            except Exception:
                logger.debug("Failed to broadcast batched agent output", exc_info=True)
