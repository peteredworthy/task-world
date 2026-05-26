# Step 05 Plan - Dry-Run Analysis Notes

## Summary

Step 05 completes the migration by batching agent output, bootstrapping from JSONL, and removing
legacy recovery paths. The plan closes the major technical-debt loops, but it also removes fallback
systems. The dry run found several sequencing risks: batching can lose tail lines, bootstrap can
misread the JSONL format, and cleanup can delete recovery code before the new path is fully proven.

---

## Task 5.1: Implement OutputBatcher

### Failure Modes

**F5.1-A - Time threshold cannot be tested if the batcher reads real time directly**

The plan correctly injects a clock. If implementation accidentally calls `time.monotonic()` inside
methods, tests will need sleeps and become flaky.

**Hardening**: Store the injected clock on the instance and use it for every threshold comparison.
The unit test should use a fake clock and should not sleep.

**F5.1-B - Buffer key must include run, task, and attempt**

If the batcher has one global line buffer, interleaved output from multiple tasks or attempts can
be batched into the wrong event.

**Hardening**: Key buffers by `(run_id, task_id, attempt_id)` or guarantee a single active stream
per batcher instance. The safer plan is keyed buffers. Tests should add lines for two task ids and
assert they flush to separate `AgentOutputEvent`s.

**F5.1-C - `flush()` idempotency can hide failed prior flushes**

An empty-buffer no-op is good, but if appending to the event store fails after the buffer is cleared,
lines are lost.

**Hardening**: Clear the buffer only after the event store append succeeds. Add a test with a
failing injected event store callable and assert the buffer is still present for retry.

---

## Task 5.2: Unit tests for OutputBatcher

### Failure Modes

**F5.2-A - Using a list as event_store stub can diverge from async append interface**

The plan says to inject a list as the event-store stub. If production `OutputBatcher` awaits an
async `append`, a plain list will not match the interface.

**Hardening**: Use a tiny real fake class with `async def append(self, events)` that stores events
in a list. This keeps the test no-mock and interface-compatible.

---

## Task 5.3: Wire OutputBatcher into PhaseHandler

### Failure Modes

**F5.3-A - Tail output can be lost on exceptions and pauses**

The step calls out `flush_immediate()` at phase transitions, but output also needs flushing in
exception paths and cancellation/pause handling. Otherwise the most recent agent lines disappear
when they are most useful.

**Hardening**: Put `flush_immediate()` in `finally` blocks around agent execution where possible.
Add a test where the runner raises after emitting a few lines and assert those lines are persisted.

**F5.3-B - WebSocket line offsets must remain monotonic after batching**

Current activity consumers rely on `line_offset`. If a batched event computes offset from batch
count rather than previous total line count, offsets can duplicate or skip.

**Hardening**: Keep offset assignment in the broadcaster or a shared offset tracker, not inside
ad hoc batch creation. The integration test should assert offsets for all 60 lines, as planned.

---

## Task 5.4: Integration test for output batching via WebSocket

### Failure Modes

**F5.4-A - Test can pass by only inspecting events_v2**

The requirement is both storage and UI delivery. A test that only counts `events_v2` rows can miss a
WebSocket regression.

**Hardening**: Keep assertions on both channels: fewer than 60 stored `AgentOutputEvent` rows and
all 60 lines visible through the WebSocket/activity stream in order.

---

## Task 5.5: Implement JSONL bootstrap for empty-DB startup

### Failure Modes

**F5.5-A - Bootstrap can skip new outbox records if JSONL keys differ**

Existing `history.jsonl` records use `run_id` and `sequence_number`. If Step 01's outbox writes
`aggregate_id` and `position`, bootstrap must support both formats or the post-migration journal
will not seed an empty DB.

**Hardening**: Either make the outbox write legacy-compatible keys or make bootstrap accept both
shapes. Add fixture lines for both legacy and new records.

**F5.5-B - Event class lookup must tolerate unknown historical events**

Old journals can contain events that no longer have a current model class or that have older fields.
Failing the entire bootstrap on one unknown event would make recovery fragile.

**Hardening**: For unknown event types, log and skip only if the event is explicitly non-critical,
or fail with a clear message that names the sequence number. Do not silently drop required lifecycle
events.

**F5.5-C - Bootstrap must be idempotent by event identity**

The plan says skip on position conflict. Position alone can be insufficient if a partially imported
DB contains position values from a different journal.

**Hardening**: Also verify aggregate id, event type, and timestamp when a position conflict is seen.
If they differ, raise a corruption/conflict error rather than skipping.

---

## Task 5.6: Integration test for JSONL bootstrap

### Failure Modes

**F5.6-A - In-memory DB does not exercise startup/Alembic path**

An in-memory bootstrap unit test is useful, but the startup sequence after migrations is where this
will run in production.

**Hardening**: Keep the in-memory functional test, and add or retain one file-backed integration
test that initializes via app startup or `init_db()` with migrations before bootstrap.

---

## Task 5.7: Remove legacy recovery code and EventStore dual-write path

### Failure Modes

**F5.7-A - Cleanup before bootstrap proof removes the only recovery path**

Deleting `journal_replay.py` and related modules is safe only after projection rebuild and JSONL
bootstrap are verified from real journal data.

**Hardening**: Make Task 5.7 depend explicitly on Task 5.6 passing. Do not delete recovery modules
in the same commit as unproven bootstrap wiring.

**F5.7-B - Imports from deleted modules can remain in CLI or tests**

The grep in the plan is necessary. Some references may live in documentation or migration comments,
which should be reviewed rather than blindly removed.

**Hardening**: Use `rg "event_journal|journal_replay|JsonlEventJournal|bootstrap_from_jsonl"` and
manually classify remaining references as expected docs/tests or code needing update.

---

## Task 5.8: Remove pending_signals table and update ARCHITECTURE.md

### Failure Modes

**F5.8-A - Dropping pending_signals before all deployments run Step 04 migration loses queued work**

This project is single-instance, but existing queued signals can still exist in the table at the
moment of migration.

**Hardening**: Migration should either assert `pending_signals` is empty before drop or migrate any
remaining rows into `SignalEnqueued` events before dropping.

**F5.8-B - Documentation can drift from actual routes and data flow**

The architecture document has route and event-system sections. A minimal cleanup may remove old
references but fail to describe the new event-sourced flow.

**Hardening**: Update the event/signaling section with the new write path:
API/service command -> `events_v2` append -> synchronous projectors -> JSONL outbox -> activity and
WebSocket delivery.

---

## Cross-Cutting Concerns

### CC-5.1 - Final full-suite verification is mandatory

This step deletes fallback code and changes logging behavior. Focused tests are not enough.

**Hardening**: Keep the final verification as full `uv run pytest`, `uv run pyright`, and relevant
grep checks. Do not bypass pre-commit hooks if committing the finished run.

### CC-5.2 - Batch defaults must match clarified decision

The human clarification selected 100ms flush and 50 lines per batch.

**Hardening**: Put those defaults in one configuration location and test the default constructor
uses `flush_interval_ms=100` and `max_lines=50`.

---

## Summary of Required Hardening Actions

| ID | Severity | Task | Action |
|----|----------|------|--------|
| F5.1-B | HIGH | 5.1 | Key output buffers by run/task/attempt or prove one stream per instance |
| F5.1-C | HIGH | 5.1 | Clear buffers only after successful append |
| F5.3-A | HIGH | 5.3 | Flush tail output in exception, pause, and cancellation paths |
| F5.3-B | HIGH | 5.3/5.4 | Preserve monotonic WebSocket line offsets after batching |
| F5.5-A | HIGH | 5.5 | Bootstrap must read both legacy and outbox JSONL shapes, or outbox must be legacy-compatible |
| F5.5-C | MED | 5.5 | Treat conflicting positions with different event identity as corruption |
| F5.7-A | HIGH | 5.7 | Delete legacy recovery only after bootstrap proof passes |
| F5.8-A | MED | 5.8 | Migrate or assert empty `pending_signals` before dropping it |
