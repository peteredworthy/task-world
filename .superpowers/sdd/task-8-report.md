# Task 8: Rotate and Recover the JSONL Journal Safely

## Implementation

- `JournalConfig` exposes a 64 MiB default and clamps invalid small values to
  1 MiB with a warning.
- Every JSONL mutation now runs in `asyncio.to_thread` and holds a per-path OS
  advisory lock for discovery, exact deduplication, rotation, append, file
  fsync, and parent-directory fsync. Failures remain visible to the post-commit
  observer caller.
- Rotation uses the durable link protocol exactly:
  `link(active, archive) → fsync(parent) → unlink(active) → fsync(parent)`.
  `RotationOperations` is an injected filesystem seam; its recorder test
  delegates to real operations and asserts that order. The linked-file recovery
  crash-state test remains in the rotation suite.
- Archive names retain position ranges as a compact candidate index. A matching
  range is streamed before suppressing a position, so sparse legacy archives
  cannot hide missing positions.
- Workflow and graph event-store wiring accepts the configured journal size.
  A configured `build_graph_runtime` factory is injected at application
  composition, while seeding, driver lifecycle commands, cancellation, and the
  graph patch/decision routes pass `GlobalConfig.journal.max_bytes` into every
  production `GraphController`. An AST boundary test enumerates those
  constructions, and a file-backed integration test proves that a controller
  rotates at its injected nondefault limit. Graph controller and the requeue
  endpoint flush the same post-commit outbox journal path.
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
Exact:   19 passed (rotation, recovery, controller-limit, and configuration-boundary tests)
Broader: 118 passed (journal, graph driver, graph API/decision/cancel, and signal-consumer paths)
Assert-clean: `uv run python -m scripts.codemods.r04_otel_vocab --assert-clean` (no output)
Pyright: 0 errors, 0 warnings, 0 informations
Full:    4940 passed, 6 skipped, 3 Python 3.12 SQLite deprecation warnings
Hooks:   `uv run pre-commit run --all-files` (all hooks passed)
```
