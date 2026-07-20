# Journal Reconciliation Restart Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make startup JSONL reconciliation exact and restart-safe when archives are sparse, active journals rotate, or an active journal ends in a partial record.

**Architecture:** `JsonlOutboxObserver.reconcile()` will scan the active segment first and retain only its exact position set for all subsequent archive filters. It will scan one archive set at a time and append only positions absent from both the active set and that archive set. The locked append path will repair an unterminated active tail before serializing replacement records.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async SQLite, pytest, JSONL files, POSIX advisory locks.

## Global Constraints

- Preserve one bounded active position set plus one archive segment set at a time.
- Scan each active/archive segment no more than once per reconciliation pass.
- Keep database reads globally position-paginated and monotonic through rotations.
- Use real files, real SQLite, and no mocks.
- Fsync a repaired record boundary before appending complete JSON records.
- Do not alter unrelated workflow or telemetry behavior.

---

### Task 1: Prove active-first sparse archive reconciliation

**Files:**
- Modify: `tests/integration/test_event_log_durability.py`
- Modify: `src/orchestrator/db/access/jsonl_outbox.py:129-203`

**Interfaces:**
- Consumes: `JsonlOutboxObserver.reconcile(store, batch_size)` and injected `segment_reader(path) -> set[int]`.
- Produces: active positions are excluded from every archive-range page append, with monotonic page cursors across rotations.

- [ ] **Step 1: Write the failing test**

```python
async def test_journal_drain_reconciles_sparse_archives_without_duplicate_second_pass(...):
    # Archive positions {1, 3, 5}; active fills {2, 4}; DB has 1..7.
    # First pass scans active and archive once, then second pass leaves bytes unchanged.
    assert journal_path.read_bytes() == first_active_bytes
    assert all_positions == list(range(1, 8))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_event_log_durability.py -k sparse -v`
Expected: FAIL because reconciliation scans archives before active and appends an already-active position during an archive range.

- [ ] **Step 3: Write minimal implementation**

```python
active_positions = self._segment_reader(self._path)
for segment in discover_journal_segments(self._path):
    segment_positions = self._segment_reader(segment.path)
    existing_positions = active_positions | segment_positions
    observed += await self._reconcile_page_range(..., existing_positions)
```

Keep the active set stable through archive ranges and use `max(cursor, page[-1].position)` after every page.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_event_log_durability.py -k sparse -v`
Expected: PASS.

### Task 2: Prove partial-tail repair preserves JSONL bootstrap recovery

**Files:**
- Modify: `tests/integration/test_event_log_durability.py`
- Modify: `src/orchestrator/db/access/jsonl_outbox.py:250-339`

**Interfaces:**
- Consumes: `_append_events_under_held_lock(path, max_bytes, events, rotation_operations)` while `_advisory_lock` is held.
- Produces: a valid newline-delimited record stream before replacement records append.

- [ ] **Step 1: Write the failing test**

```python
async def test_journal_reconciliation_repairs_partial_final_record_before_replacement(...):
    journal_path.write_text('{"position": 1}\n{"position":')
    await drain_committed_events_to_journal(session, journal_path, batch_size=1)
    restored = await restore_from_journal(journal_path)
    assert restored[-1].position == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_event_log_durability.py -k partial_final -v`
Expected: FAIL because the appended JSON object is concatenated with the malformed final fragment.

- [ ] **Step 3: Write minimal implementation**

```python
def _repair_active_append_boundary(path: Path, operations: RotationOperations) -> None:
    # Preserve complete final JSON records; truncate only a malformed trailing fragment.
    # Fsync the active file and parent after delimiter/truncation.
```

Invoke it immediately before serializing nonempty replacement events under the advisory lock.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_event_log_durability.py -k partial_final -v`
Expected: PASS.

### Task 3: Correct workload evidence and verify repository checks

**Files:**
- Modify: `docs/superpowers/reports/2026-07-20-r04-telemetry-workload-bounds.md`

**Interfaces:**
- Consumes: exact assertions from the integration regressions.
- Produces: accurate evidence of active-first scanning, per-pass scan counts, byte stability, no duplicates, and restored authoritative events.

- [ ] **Step 1: Correct evidence**

Replace the claim that active is scanned after archives with active-first wording and record the two-pass sparse archive and partial-tail bootstrap evidence.

- [ ] **Step 2: Run focused backend tests**

Run: `uv run pytest tests/integration/test_event_log_durability.py tests/integration/test_jsonl_rotation_recovery.py tests/unit/test_jsonl_outbox.py -v`
Expected: PASS.

- [ ] **Step 3: Run full checks**

Run: `uv run pytest && uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: all commands exit 0.

- [ ] **Step 4: Run UI verification and hooks**

Run the repository UI test command from `package.json`, then `pre-commit run --all-files`.
Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/db/access/jsonl_outbox.py tests/integration/test_event_log_durability.py docs/superpowers/reports/2026-07-20-r04-telemetry-workload-bounds.md docs/superpowers/plans/2026-07-20-journal-reconciliation-restart-safety.md
```
