# W8 Drive Loop Cleanup Closure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement the remaining unchecked tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the W8 cleanup that has landed and define the small remaining follow-up work without asking future agents to re-implement completed behavior.

**Architecture:** The current driver still uses the polling loop, but progress detection is now based on event-log position rather than projection signatures. Runtime recovery no longer contains the dead redispatch assignment, quiescent reconcile no longer performs the old extra schedule pass when it produces no new work, and the driver respects future outbox retry times before classifying a run as blocked.

**Tech Stack:** Python 3.12, SQLAlchemy async sessions, graph event/projection models, pytest/pytest-asyncio, `uv run`.

## Global Constraints

- Use `uv run` for all Python commands.
- Do not change lease renewal/expiry semantics.
- Do not remove the driver's worktree-contamination guard.
- Do not remove the no-progress to `graph_blocked` pause behavior without a kernel-level replacement.
- Do not attempt full event-triggered driving in this plan.
- No mocking in tests; use real objects or the existing hand-written fakes.

---

### Completed W8 Work

**Evidence in current tree:**
- `src/orchestrator/graph_runtime/recovery.py` no longer contains `if not redispatched and pending_before: redispatched = []`.
- `src/orchestrator/workflow/graph_driver.py` no longer uses `_progress_signature` or `previous_signature`.
- `GraphRunDriver.drive_to_quiescence()` compares `controller.current_position(run_id)` against `previous_position`.
- `GraphRunDriver.drive_to_quiescence()` checks `dispatcher.earliest_pending_retry_at(run_id=run_id)` before returning a blocked outcome.
- Quiescent active graphs issue `reconcile`, re-read the projection, and continue only if reconcile creates ready/schedulable work or active leases.

**Regression evidence:**
- `tests/unit/test_graph_driver_logic.py::test_driver_uses_event_position_to_detect_stuck_ready_node`
- `tests/unit/test_graph_driver_logic.py::test_driver_returns_reconciled_quiescent_projection_without_second_schedule_tick`
- `tests/unit/test_graph_driver_logic.py::test_driver_continues_when_reconcile_creates_schedulable_work`
- `tests/unit/test_graph_driver_logic.py::test_driver_waits_for_future_outbox_backoff_before_declaring_blocked`
- `tests/integration/test_graph_dynamic_e2e.py`
- `tests/integration/test_graph_default_carrier.py`

---

### Task 1: Prune the Graph Package Public Surface

**Files:**
- Modify: `src/orchestrator/graph/__init__.py`
- Test: import collection via `uv run pytest tests --collect-only -q`

**Interfaces:**
- Consumes: every current `from orchestrator.graph import ...` consumer.
- Produces: unchanged imports for existing consumers and a smaller public package namespace.

- [ ] **Step 1: Build the exact consumer list**

Run:

```bash
rg -n "from orchestrator\.graph import|from \.\.graph import|orchestrator\.graph\." src tests
```

Expected: a list of all package-level graph imports.

- [ ] **Step 2: Edit exports conservatively**

Keep every symbol imported from `orchestrator.graph` by `src/` or `tests/`. Remove symbols that are only imported by `src/orchestrator/graph/__init__.py` itself and are not part of an observed package-level consumer.

- [ ] **Step 3: Verify collection**

Run:

```bash
uv run pytest tests --collect-only -q
```

Expected: collection succeeds with no `ImportError`.

- [ ] **Step 4: Verify graph package consumers**

Run:

```bash
uv run pytest tests/unit/test_graph_*.py tests/integration/test_graph_*.py -q
```

Expected: graph tests pass.

---

### Task 2: Add a Driver/Runtime Stopgap Ledger

**Files:**
- Create: `docs/dynamic-graph/driver-runtime-stopgaps.md`
- Modify: `docs/dynamic-graph/dynamic-graph-implementation-review.html`

**Interfaces:**
- Consumes: current driver/runtime guard behavior in `src/orchestrator/workflow/graph_driver.py`, `src/orchestrator/graph_runtime/dispatch.py`, and `src/orchestrator/graph_runtime/recovery.py`.
- Produces: a short ledger of edge-layer guards, their reason for existence, and the condition under which they can be retired.

- [ ] **Step 1: Inventory current edge guards**

Read the driver/runtime files and list guards such as worktree-contamination checks, orphaned active lease recovery, submit-rejection detection, future outbox retry waiting, and graph lifecycle bridge pause/fail classification.

- [ ] **Step 2: Write the ledger**

Create `docs/dynamic-graph/driver-runtime-stopgaps.md` with columns:

```markdown
| Guard | Layer | Why it exists | Retirement condition | Current owner |
| --- | --- | --- | --- | --- |
```

Every row must have a concrete retirement condition. Use "none yet" only when the guard is intentionally permanent.

- [ ] **Step 3: Link the ledger from the review**

Add the ledger path to the W8 remaining-work note in `dynamic-graph-implementation-review.html`.

- [ ] **Step 4: Verify docs and focused tests**

Run:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py tests/integration/test_graph_dynamic_e2e.py tests/integration/test_graph_default_carrier.py -q
```

Expected: passes.

---

### Task 3: Final W8 Follow-Up Verification

**Files:**
- No planned source changes beyond Tasks 1 and 2.

**Interfaces:**
- Consumes: completed export prune and stopgap ledger.
- Produces: current W8 follow-up evidence.

- [ ] **Step 1: Confirm old signature code stays deleted**

Run:

```bash
rg "_progress_signature|previous_signature|not redispatched and pending_before" src/orchestrator/workflow/graph_driver.py src/orchestrator/graph_runtime/recovery.py
```

Expected: no matches.

- [ ] **Step 2: Run acceptance**

Run:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py \
  tests/integration/test_graph_dynamic_e2e.py \
  tests/integration/test_graph_default_carrier.py -q
```

Expected: passes.

- [ ] **Step 3: Run collection**

Run:

```bash
uv run pytest tests --collect-only -q
```

Expected: passes with no `ImportError`.
