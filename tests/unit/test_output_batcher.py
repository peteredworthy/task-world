"""Unit tests for OutputBatcher."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest

from orchestrator.runners import OutputBatcher
from orchestrator.workflow import AgentOutputEvent, WorkflowEvent


class FakeClock:
    """Controllable monotonic clock for testing."""

    def __init__(self) -> None:
        self._time: float = 0.0

    def advance(self, ms: float) -> None:
        self._time += ms / 1000.0

    def __call__(self) -> float:
        return self._time


class FakeEventStore:
    """Minimal event store stub that records appended events."""

    def __init__(self) -> None:
        self.appended: list[AgentOutputEvent] = []

    async def append(self, events: "WorkflowEvent | Sequence[WorkflowEvent]") -> list:
        if isinstance(events, (list, tuple)):
            for e in events:
                if isinstance(e, AgentOutputEvent):
                    self.appended.append(e)
        elif isinstance(events, AgentOutputEvent):
            self.appended.append(events)
        return []


class FakeConnectionManager:
    """Minimal broadcast callback that records events."""

    def __init__(self) -> None:
        self.broadcasted: list[AgentOutputEvent] = []

    async def broadcast_event(self, event: object) -> None:
        if isinstance(event, AgentOutputEvent):
            self.broadcasted.append(event)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> FakeEventStore:
    return FakeEventStore()


@pytest.fixture
async def batcher(store: FakeEventStore, clock: FakeClock) -> AsyncGenerator[OutputBatcher, None]:
    output_batcher = OutputBatcher(
        event_store=store,  # type: ignore[arg-type]
        max_lines=50,
        flush_interval_ms=100,
        clock=clock,
    )
    try:
        yield output_batcher
    finally:
        await output_batcher.aclose()


# ---------------------------------------------------------------------------
# Count threshold flush
# ---------------------------------------------------------------------------


async def test_count_threshold_triggers_flush(
    batcher: OutputBatcher, store: FakeEventStore
) -> None:
    """Adding max_lines lines triggers an auto-flush."""
    for i in range(49):
        await batcher.add_line("run-1", "task-1", 1, f"line {i}")
    assert store.appended == [], "Should not flush before threshold"

    await batcher.add_line("run-1", "task-1", 1, "line 49")
    assert len(store.appended) == 1
    event = store.appended[0]
    assert len(event.lines) == 50
    assert event.line_offset == 0


async def test_count_threshold_lines_in_order(
    batcher: OutputBatcher, store: FakeEventStore
) -> None:
    """Batched payload contains lines in the correct order."""
    for i in range(50):
        await batcher.add_line("run-1", "task-1", 1, f"line {i}")
    event = store.appended[0]
    assert event.lines == [f"line {i}" for i in range(50)]


async def test_count_threshold_increments_line_offset(
    batcher: OutputBatcher, store: FakeEventStore
) -> None:
    """After a count-triggered flush, the next batch has the correct line_offset."""
    for i in range(50):
        await batcher.add_line("run-1", "task-1", 1, f"line {i}")
    assert store.appended[0].line_offset == 0

    # Add another batch of 50
    for i in range(50):
        await batcher.add_line("run-1", "task-1", 1, f"line {i + 50}")
    assert len(store.appended) == 2
    assert store.appended[1].line_offset == 50


# ---------------------------------------------------------------------------
# Time threshold flush
# ---------------------------------------------------------------------------


async def test_time_threshold_triggers_flush_via_add_line(
    batcher: OutputBatcher, store: FakeEventStore, clock: FakeClock
) -> None:
    """Advancing the clock past the interval flushes on the next add_line call."""
    await batcher.add_line("run-1", "task-1", 1, "first line")
    assert store.appended == []

    clock.advance(100)  # exactly at the 100ms threshold
    await batcher.add_line("run-1", "task-1", 1, "second line")
    assert len(store.appended) == 1
    assert store.appended[0].lines == ["first line", "second line"]


async def test_time_threshold_triggers_flush_via_flush(
    batcher: OutputBatcher, store: FakeEventStore, clock: FakeClock
) -> None:
    """Calling flush() after the interval elapses flushes without a new line."""
    await batcher.add_line("run-1", "task-1", 1, "line a")
    assert store.appended == []

    clock.advance(200)
    await batcher.flush()
    assert len(store.appended) == 1
    assert store.appended[0].lines == ["line a"]


async def test_time_threshold_triggers_autonomous_flush() -> None:
    """The timer flushes a quiet buffer without another add_line() or flush() call."""
    store = FakeEventStore()
    manager = FakeConnectionManager()
    batcher = OutputBatcher(
        event_store=store,  # type: ignore[arg-type]
        max_lines=50,
        flush_interval_ms=10,
        connection_manager=manager,
    )
    try:
        await batcher.add_line("run-1", "task-1", 1, "line a")
        await asyncio.sleep(0.05)

        assert len(store.appended) == 1
        assert store.appended[0].lines == ["line a"]
        assert store.appended[0].line_offset == 0
        assert manager.broadcasted == store.appended
    finally:
        await batcher.aclose()


async def test_autonomous_flush_waits_for_interval() -> None:
    """The timer does not flush before the configured interval elapses."""
    store = FakeEventStore()
    batcher = OutputBatcher(
        event_store=store,  # type: ignore[arg-type]
        max_lines=50,
        flush_interval_ms=100,
    )
    try:
        await batcher.add_line("run-1", "task-1", 1, "line a")
        await asyncio.sleep(0.02)
        assert store.appended == []
    finally:
        await batcher.aclose()


async def test_below_time_threshold_flush_is_noop(
    batcher: OutputBatcher, store: FakeEventStore, clock: FakeClock
) -> None:
    """flush() does not emit if the time threshold has not been reached."""
    await batcher.add_line("run-1", "task-1", 1, "line")
    clock.advance(50)  # only half the interval
    await batcher.flush()
    assert store.appended == []


# ---------------------------------------------------------------------------
# Immediate flush
# ---------------------------------------------------------------------------


async def test_flush_immediate_ignores_thresholds(
    batcher: OutputBatcher, store: FakeEventStore
) -> None:
    """flush_immediate() flushes all pending lines regardless of thresholds."""
    await batcher.add_line("run-1", "task-1", 1, "line a")
    await batcher.add_line("run-1", "task-1", 1, "line b")
    assert store.appended == []

    await batcher.flush_immediate()
    assert len(store.appended) == 1
    assert store.appended[0].lines == ["line a", "line b"]


async def test_flush_immediate_multiple_keys(batcher: OutputBatcher, store: FakeEventStore) -> None:
    """flush_immediate() flushes all distinct buffer keys."""
    await batcher.add_line("run-1", "task-1", 1, "t1 line")
    await batcher.add_line("run-1", "task-2", 1, "t2 line")

    await batcher.flush_immediate()
    assert len(store.appended) == 2
    run_task_pairs = {(e.task_id, e.lines[0]) for e in store.appended}
    assert run_task_pairs == {("task-1", "t1 line"), ("task-2", "t2 line")}


# ---------------------------------------------------------------------------
# Empty buffer no-op
# ---------------------------------------------------------------------------


async def test_flush_empty_buffer_is_noop(batcher: OutputBatcher, store: FakeEventStore) -> None:
    """flush() with an empty buffer does not call append."""
    await batcher.flush()
    assert store.appended == []


async def test_flush_immediate_empty_buffer_is_noop(
    batcher: OutputBatcher, store: FakeEventStore
) -> None:
    """flush_immediate() with an empty buffer does not call append."""
    await batcher.flush_immediate()
    assert store.appended == []


async def test_flush_after_drain_is_noop(
    batcher: OutputBatcher, store: FakeEventStore, clock: FakeClock
) -> None:
    """flush() after the buffer has already been flushed is a no-op."""
    await batcher.add_line("run-1", "task-1", 1, "line")
    clock.advance(200)
    await batcher.flush()
    assert len(store.appended) == 1

    await batcher.flush()
    assert len(store.appended) == 1  # no second append


async def test_line_offset_monotonic_across_timer_count_and_immediate_flushes() -> None:
    """Timer, count, and immediate flushes all advance a shared line_offset."""
    store = FakeEventStore()
    batcher = OutputBatcher(
        event_store=store,  # type: ignore[arg-type]
        max_lines=2,
        flush_interval_ms=10,
    )
    try:
        await batcher.add_line("run-1", "task-1", 1, "timer line")
        await asyncio.sleep(0.05)

        await batcher.add_line("run-1", "task-1", 1, "count line a")
        await batcher.add_line("run-1", "task-1", 1, "count line b")

        await batcher.add_line("run-1", "task-1", 1, "manual line")
        await batcher.flush_immediate()

        assert [event.line_offset for event in store.appended] == [0, 1, 3]
        assert [event.lines for event in store.appended] == [
            ["timer line"],
            ["count line a", "count line b"],
            ["manual line"],
        ]
    finally:
        await batcher.aclose()


async def test_aclose_cancels_timer_and_flushes_pending_line() -> None:
    """Closing drains pending output and clears timer ownership."""
    store = FakeEventStore()
    batcher = OutputBatcher(
        event_store=store,  # type: ignore[arg-type]
        max_lines=50,
        flush_interval_ms=1000,
    )

    await batcher.add_line("run-1", "task-1", 1, "line a")
    entry = batcher._buffer[("run-1", "task-1", 1)]
    assert entry.timer_task is not None

    await batcher.aclose()

    assert len(store.appended) == 1
    assert store.appended[0].lines == ["line a"]
    assert entry.timer_task is None


# ---------------------------------------------------------------------------
# Correct line ordering in batched payloads
# ---------------------------------------------------------------------------


async def test_line_ordering_preserved_in_batch(
    batcher: OutputBatcher, store: FakeEventStore
) -> None:
    """Lines appear in insertion order inside each batched AgentOutputEvent."""
    lines = [f"output line {i}" for i in range(50)]
    for line in lines:
        await batcher.add_line("run-1", "task-1", 1, line)

    assert store.appended[0].lines == lines


async def test_event_metadata(batcher: OutputBatcher, store: FakeEventStore) -> None:
    """Flushed event carries correct run_id, task_id, attempt_num."""
    for i in range(50):
        await batcher.add_line("run-abc", "task-xyz", 3, f"line {i}")

    event = store.appended[0]
    assert event.run_id == "run-abc"
    assert event.task_id == "task-xyz"
    assert event.attempt_num == 3
    assert event.event_type == "agent_output"


# ---------------------------------------------------------------------------
# Buffer cleared only after successful append
# ---------------------------------------------------------------------------


async def test_buffer_not_cleared_on_append_failure(clock: FakeClock) -> None:
    """If append raises, the buffer lines are preserved for retry."""

    class FailingStore:
        async def append(self, events):  # type: ignore[override]
            raise RuntimeError("DB unavailable")

    manager = FakeConnectionManager()
    batcher = OutputBatcher(
        event_store=FailingStore(),  # type: ignore[arg-type]
        max_lines=2,
        flush_interval_ms=1000,
        clock=clock,
        connection_manager=manager,
    )

    with pytest.raises(RuntimeError):
        await batcher.add_line("run-1", "task-1", 1, "line a")
        await batcher.add_line("run-1", "task-1", 1, "line b")  # triggers flush

    # Buffer should still contain the lines since append failed
    key = ("run-1", "task-1", 1)
    assert key in batcher._buffer
    assert len(batcher._buffer[key].lines) > 0
    assert manager.broadcasted == []


async def test_broadcast_receives_flushed_agent_output(clock: FakeClock) -> None:
    """Each successful flush broadcasts the persisted AgentOutputEvent."""
    store = FakeEventStore()
    manager = FakeConnectionManager()
    batcher = OutputBatcher(
        event_store=store,  # type: ignore[arg-type]
        max_lines=2,
        flush_interval_ms=1000,
        clock=clock,
        connection_manager=manager,
    )

    await batcher.add_line("run-1", "task-1", 4, "line a")
    await batcher.add_line("run-1", "task-1", 4, "line b")

    assert len(store.appended) == 1
    assert manager.broadcasted == store.appended
    event = manager.broadcasted[0]
    assert event.lines == ["line a", "line b"]
    assert event.line_offset == 0

    await batcher.add_line("run-1", "task-1", 4, "line c")
    await batcher.add_line("run-1", "task-1", 4, "line d")

    assert len(manager.broadcasted) == 2
    assert manager.broadcasted[1].lines == ["line c", "line d"]
    assert manager.broadcasted[1].line_offset == 2
