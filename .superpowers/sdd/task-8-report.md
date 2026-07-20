# Task 8: Rotate and Recover the JSONL Journal Safely

## Implementation

- `JournalConfig` exposes a 64 MiB default and clamps invalid small values to
  1 MiB with a warning.
- Every JSONL mutation now runs in `asyncio.to_thread` and holds a per-path OS
  advisory lock for discovery, exact deduplication, rotation, append, file
  fsync, rename, and parent-directory fsync. Failures remain visible to the
  post-commit observer caller.
- Archive names retain position ranges as a compact candidate index. A matching
  range is streamed before suppressing a position, so sparse legacy archives
  cannot hide missing positions.
- Workflow and graph event-store wiring accepts the configured journal size;
  API dependencies pass `GlobalConfig.journal.max_bytes`. Graph controller and
  the requeue endpoint flush the same post-commit outbox journal path.
- Bootstrap replays archive segments and active journal in global position
  order, rejects malformed structural records with warnings, and preserves
  legacy sequence support. Backup scans archive-only journals too.

## RED / GREEN evidence

RED (`uv run pytest tests/unit/test_jsonl_rotation.py
tests/integration/test_jsonl_rotation_recovery.py -q -n 0`): four expected
failures demonstrated range-only false deduplication, unsynchronized writers,
archive-only backup omission, and structurally malformed record crashes.

GREEN after the fixes:

```text
Exact:   24 passed
Broader: 41 passed
Full:    4935 passed, 6 skipped, 3 pre-existing Python 3.12 SQLite warnings
Hooks:   uv run pre-commit run --all-files (all hooks passed)
```
