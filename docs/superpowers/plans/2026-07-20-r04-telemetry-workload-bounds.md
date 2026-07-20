# R04 Telemetry Workload Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound startup journal reconciliation and cost-rollup input work while preserving exact event provenance and telemetry compatibility.

**Architecture:** The JSONL observer will scan each active/archive segment once per locked write transaction, retaining only the current segment's exact integer positions and filtering the incoming page against it before discarding it. The rollup loader will query at most `MAX_ROLLUP_FACTS + 1` raw rows before JSON decoding, raising a separate input-cardinality error if the sentinel row exists. Graph rebuild coverage will use a real `node_usage_recorded` event and inspect persisted run telemetry rather than a synthetic projection shortcut.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async, FastAPI, Pydantic v2, pytest, React/Vitest verification.

## Global Constraints

- Preserve advisory locking, exact sparse-position deduplication, and bounded page/segment memory.
- Set `MAX_ROLLUP_FACTS = 100_000`; permit an internal/test override without exposing it as a public query parameter.
- Return HTTP 400 with a clear time/filter narrowing hint for rollup input overflow; retain the independent 1,000-group error.
- Do not mock; instrumentation must use a real injected segment reader/observer.
- Retain historical `ModelTokenUsage` migration reads; do not forbid compatible legacy fields solely to tighten current construction.
- Do not modify the pre-existing `.superpowers/sdd/progress.md` worktree change.

---

### Task 1: Segment-scoped journal reconciliation

**Files:**
- Modify: `src/orchestrator/db/access/jsonl_outbox.py`
- Test: `tests/integration/test_event_log_durability.py`
- Test: `tests/unit/test_jsonl_outbox.py`

**Interfaces:**
- Consumes: `StoredEvent`, `JournalSegment`, `discover_journal_segments()`, `SqliteEventStore.get_page_after_position()`.
- Produces: injected segment-reader instrumentation and one traversal of each segment per observer page/write transaction.

- [ ] **Step 1: Write failing integration coverage**

Create archive segments with sparse/gap positions and a multi-page DB event stream. Inject a reader that records archive paths and yields their JSONL records. Assert the journal contains every DB position exactly once and each archive path was traversed once across the reconciliation call, rather than once per missing event.

- [ ] **Step 2: Run the focused failing test**

Run: `uv run pytest tests/integration/test_event_log_durability.py -k segment -v`
Expected: FAIL because the observer opens an archive candidate for every event.

- [ ] **Step 3: Implement the minimal segment-scoped scan**

Add a small injected reader protocol/function that yields valid exact integer positions from one path. Under `_advisory_lock`, scan active once and, for each discovered archive, materialize only that archive's position set, discard covered candidates from the pending event map, then release the set before the next archive. Preserve active scan, batch duplicate handling, rotation recovery, and fsync behavior.

- [ ] **Step 4: Run focused journal tests**

Run: `uv run pytest tests/unit/test_jsonl_outbox.py tests/unit/test_jsonl_rotation.py tests/integration/test_event_log_durability.py -v`
Expected: PASS.

### Task 2: Bound raw cost-rollup facts before decoding

**Files:**
- Modify: `src/orchestrator/api/routers/cost_rollup.py`
- Modify: `src/orchestrator/api/presenters/cost_rollup.py`
- Test: `tests/integration/test_api_cost_rollup.py`
- Test: `tests/unit/test_cost_rollup.py`

**Interfaces:**
- Consumes: `CostRollupFilters`, SQLAlchemy select statement, `compute_cost_rollup()`.
- Produces: `MAX_ROLLUP_FACTS`, an overrideable loader limit, and a dedicated input-limit exception mapped to HTTP 400.

- [ ] **Step 1: Write failing same-group volume tests**

Insert more than a small injected max number of `node_usage_recorded` rows with the same run/group. Assert `load_cost_rollup_facts(..., max_facts=small_limit)` rejects after fetching only `small_limit + 1` rows and the route reports HTTP 400 whose detail asks callers to narrow time range or filters. Keep a separate assertion that over-1,000 output groups retains its group-cardinality message.

- [ ] **Step 2: Run focused failing tests**

Run: `uv run pytest tests/integration/test_api_cost_rollup.py tests/unit/test_cost_rollup.py -v`
Expected: FAIL because `result.all()` decodes all matching rows.

- [ ] **Step 3: Implement sentinel-row enforcement**

Define `MAX_ROLLUP_FACTS = 100_000` next to the loader. Apply SQL `.limit(max_facts + 1)`, inspect the raw result length before `json.loads`/`CostRollupFact` construction, and raise a dedicated error with a time/filter narrowing hint. Map only that error to HTTP 400 and leave `CostRollupCardinalityError` intact.

- [ ] **Step 4: Run focused rollup tests**

Run: `uv run pytest tests/integration/test_api_cost_rollup.py tests/unit/test_cost_rollup.py -v`
Expected: PASS.

### Task 3: Rebuild exact node-usage provenance and compatibility regression

**Files:**
- Test: `tests/integration/test_graph_*` or existing graph-store integration test containing `GraphEventStore.rebuild_read_models`
- Modify: stale test constructors using `ModelTokenUsage(cost_per_m_*)`
- Test: affected existing unit/integration tests

**Interfaces:**
- Consumes: `GraphEventStore`, `NodeUsageRecordedPayload`, `ModelTokenUsage`, run API presenters.
- Produces: a regression proving `execution_id:0` provenance survives save/rebuild and remains excluded from public API output.

- [ ] **Step 1: Write the failing real-event regression**

Persist a run and a real `node_usage_recorded` event with `usage_key="<execution_id>:0"`, call `GraphEventStore.rebuild_read_models(run_id)`, and assert the saved `RunModel` has one usage fact with exact tokens, duration, actions, cost, `graph_usage_key`, and `graph_usage_num_actions`. Exercise the normal API presenter and assert the two provenance fields are absent.

- [ ] **Step 2: Run the focused failing regression**

Run: `uv run pytest <selected-graph-integration-test> -k provenance -v`
Expected: FAIL if rebuild loses fact/action provenance or API leakage occurs.

- [ ] **Step 3: Make the minimal production correction, if required**

Correct only the provenance/rebuild path exposed by the regression. Replace stale test-only `cost_per_m_*` keyword arguments for `ModelTokenUsage` with `cost_usd`; do not add `extra="forbid"` if migration fixtures require historical fields.

- [ ] **Step 4: Run focused graph and compatibility tests**

Run: `uv run pytest tests/unit/test_run_evidence_digest_presenter.py tests/integration/test_run_evidence_digest_api.py <selected-graph-integration-test> -v`
Expected: PASS.

### Task 4: Verification report and repository gates

**Files:**
- Create: `docs/superpowers/reports/2026-07-20-r04-telemetry-workload-bounds.md`
- Modify: `docs/ARCHITECTURE.md` only if a public route/module contract changes

- [ ] **Step 1: Record evidence**

Write the report with exact journal traversal evidence, rollup sentinel behavior/message, provenance assertions, commands, and their results.

- [ ] **Step 2: Run targeted and complete verification**

Run: `uv run pytest`, `uv run pyright`, `uv run ruff check .`, `uv run ruff format --check .`, and the frontend test/build commands documented in `package.json`.
Expected: all commands exit 0.

- [ ] **Step 3: Inspect migration and worktree cleanliness**

Run Alembic head/current checks and `git status --short`; verify no migration is needed and leave `.superpowers/sdd/progress.md` unmodified/uncommitted.

- [ ] **Step 4: Commit intended changes**

Stage only implementation, tests, plan/report documentation, and relevant architecture documentation. Commit with:

```bash
git commit -m "fix: bound telemetry reconciliation workloads"
```
