# R04 Telemetry Workload Bounds Report

## Delivered

1. **Startup journal reconciliation**
   - `JsonlOutboxObserver.reconcile()` scans the active journal once before archive segments, then scans archive segments in global-position order.
   - It retains only the initial active sparse exact-position set for complete cross-range filtering and combines it with exactly one archive sparse set while it fetches bounded DB pages for that archive range; the archive set is then discarded before the next segment.
   - The reconciliation advisory lock spans scan/filter/append work. The monotonic DB cursor, rather than retained appended positions, prevents an active rotation from reopening already advanced work; the final active segment is rescanned once for observer state.
   - Ordinary observer appends likewise scan an archive candidate once per batch, so sparse gap events no longer reopen the same candidate per event.
   - Evidence: an injected real JSONL segment reader reconciles five bounded DB pages with archive positions `1..5`, initial active position `7`, and a forced rotation after every append. The retained active set never exceeds its one-position initial segment; after a second pass, active bytes are unchanged and positions `1..9` occur exactly once across journal files. Clean-tail repair uses one real binary final-byte read and never scans a fragment; malformed-tail truncation and JSONL bootstrap restoration of positions `1, 2` remain covered.

2. **Rollup input bound**
   - `MAX_ROLLUP_FACTS = 100_000` caps raw graph usage facts.
   - The SQL query requests one sentinel row (`max_facts + 1`) and checks that raw row count before `json.loads` or `CostRollupFact` construction.
   - Overflow raises a dedicated HTTP 400 error: `cost rollup exceeds maximum of … facts; narrow time range or filters`.
   - The existing independent 1,000-output-group error remains unchanged. `load_cost_rollup_facts(..., max_facts=...)` is an internal/test override.
   - Evidence: three same-group facts with `max_facts=2` are rejected before decode with the narrowing hint.

3. **Usage provenance**
   - A real saved `node_usage_recorded` event with `usage_key="execution-1:0"` is rebuilt through `GraphEventStore.rebuild_read_models()`.
   - The regression verifies one persisted fact, exact token/cost/duration/action values, and both persisted provenance fields. The API usage schema excludes those internal provenance fields.
   - Stale test constructors now use `cost_usd`; no `extra="forbid"` change was made, preserving migration compatibility.

## TDD Evidence

Each new behavior was written and run red before the minimal implementation:

- Archive instrumentation initially failed because `JsonlOutboxObserver` had no injected segment reader; it then passed after segment-scoped reconciliation was added.
- Sparse active/archive instrumentation initially retained appended DB positions through forced rotations; it then passed after retaining only the initial active segment while the cursor advances monotonically.
- Clean-tail instrumentation initially could not inject real binary reads and full-file repair used `read_bytes`; it then passed after the one-byte fast path and bounded backward fragment scan were introduced.
- Partial-final-record instrumentation initially produced one malformed joined line; it then passed after the held-lock append path durably truncates malformed fragments (or delimits complete unterminated records) before replacement append.
- Same-group rollup input test initially failed because `load_cost_rollup_facts` lacked `max_facts`; it then passed after sentinel-row enforcement was added.
- Exact-provenance regression initially failed at public API import; it then passed after exporting the established presenter through the API boundary.

## Verification

| Command | Result |
| --- | --- |
| `uv run pytest` | PASS — 4,961 passed, 6 skipped (3 existing Python 3.12 SQLite adapter deprecation warnings), 135.51s |
| `uv run pyright` | PASS — 0 errors, 0 warnings |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `npm run test` (`ui/`) | PASS — 55 files, 450 tests |
| `npm run lint` (`ui/`) | PASS |
| `npm run typecheck` (`ui/`) | PASS |
| `npm run build` (`ui/`) | PASS — Vite reports its existing >500 kB chunk-size advisory |
| `uv run alembic -c alembic.ini current && uv run alembic -c alembic.ini heads` | PASS — both `r04a1b2c3d4e (head)`; no migration required |
