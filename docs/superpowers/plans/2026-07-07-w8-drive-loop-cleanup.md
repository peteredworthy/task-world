# W8 Drive Loop Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement W8 by removing dead graph runtime code, pruning the `orchestrator.graph` public re-export surface to actual consumers, and simplifying `GraphRunDriver.drive_to_quiescence` to use event-log position advancement instead of progress signatures.

**Architecture:** Keep the existing graph driver poll loop and safety guards. Replace the state-signature progress guard with a head-position guard read once per iteration after the tick/dispatch/wait cycle, and issue only one `reconcile` command for quiescent active blockers before classifying the outcome. Keep Slice A and Slice B as separate commits so they can be split into separate PRs.

**Tech Stack:** Python 3.12, FastAPI backend, SQLAlchemy async sessions, Pydantic graph models, pytest/pytest-asyncio, `uv run`.

## Global Constraints

- Do not change lease renewal/expiry semantics.
- Do not remove the driver's worktree-contamination guard.
- Do not remove the driver's no-progress to `graph_blocked` pause behavior.
- Do not attempt full event-triggered driving; keep the poll loop.
- Slice A and Slice B must remain separable as separate commits.
- Use `uv run` for all Python commands.
- No mocking in tests; use real objects or the existing hand-written fakes.

---

### Task 1: Slice A Dead Code and Public Export Prune

**Files:**
- Modify: `src/orchestrator/graph_runtime/recovery.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Test: import collection via `uv run pytest tests --collect-only -q`

**Interfaces:**
- Consumes: current `RecoveryReport`, `recover()`, and all existing imports from `orchestrator.graph`.
- Produces: unchanged public names for every current `from orchestrator.graph import ...` consumer; no `ImportError` on test collection.

- [ ] **Step 1: Verify the recovery no-op is inert**

Read `src/orchestrator/graph_runtime/recovery.py` and confirm this block has no effect because it assigns `[]` to an already falsey `redispatched` only when `not redispatched` is true:

```python
if not redispatched and pending_before:
    redispatched = []
```

- [ ] **Step 2: Delete the no-op**

Remove only that `if` block. Do not change `RecoveryReport` fields or pending cleanup behavior.

- [ ] **Step 3: Build the exact public export list**

Run this consumer scan:

```bash
rg -n "from orchestrator\.graph import|from \.\.graph import|orchestrator\.graph\." src tests
```

For every `from orchestrator.graph import (...)` statement, include each imported symbol in `src/orchestrator/graph/__init__.py`. Keep module-level names imported as `from orchestrator.graph import projections` if collection requires them. Do not keep names that are only used by `src/orchestrator/graph/__init__.py` itself.

- [ ] **Step 4: Prune `src/orchestrator/graph/__init__.py`**

Remove unused imports and `__all__` entries from the top-level graph package. Prefer keeping the same grouping by source module. Do not change direct submodule imports such as `from orchestrator.graph.models import PatchEnvelope`.

- [ ] **Step 5: Verify Slice A**

Run:

```bash
uv run pytest tests --collect-only -q
```

Expected: collection succeeds with no `ImportError`.

Also run:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py -q
```

Expected: passes.

- [ ] **Step 6: Commit Slice A**

```bash
git add src/orchestrator/graph_runtime/recovery.py src/orchestrator/graph/__init__.py
git commit -m "refactor: prune graph exports for W8"
```

### Task 2: Slice B Position-Based Driver Progress

**Files:**
- Modify: `tests/unit/test_graph_driver_logic.py`
- Modify: `src/orchestrator/workflow/graph_driver.py`

**Interfaces:**
- Consumes: `GraphRunDriver.drive_to_quiescence()`, `GraphLoopController.current_position()`, `GraphLoopDispatcher.earliest_pending_retry_at()`, `_recover_orphaned_active_leases()`, `_renew_running_expired_leases()`.
- Produces: no `_progress_signature()` helper, position-based no-progress detection, and no extra projection re-read after quiescent `reconcile`.

- [ ] **Step 1: Write a failing position-progress test**

Add a unit test to `tests/unit/test_graph_driver_logic.py` proving an idle graph is detected by unchanged event position, even if projection content is identical across reads. Use an existing fake controller/dispatcher/executor pattern. Add a controller that returns stable head positions after the first tick, and assert:

```python
assert controller.commands == ["schedule_tick", "schedule_tick"]
assert outcome.completed is False
assert outcome.blocked_reason == "graph has ready node(s) not dispatched: planner-gap"
```

The test must fail before production changes because the current implementation relies on `_progress_signature`.

- [ ] **Step 2: Run the new test red**

Run:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py::<new_test_name> -q
```

Expected: FAIL for the expected old behavior, not syntax/import errors.

- [ ] **Step 3: Replace signature progress with position progress**

In `src/orchestrator/workflow/graph_driver.py`, remove `previous_signature` and `_progress_signature()`. Track the previous event-log head instead:

```python
previous_position: int | None = None
```

At the end of each iteration, after the projection has been read and renewal/quiescence checks have run, call:

```python
position = await controller.current_position(run_id)
```

Treat `position == previous_position` as no progress and run the existing outbox-backoff/orphan-recovery/blocked classification branch. Reset `previous_position = None` before `continue` when renewal, backoff sleep, or orphan recovery means the next loop should not compare against stale state. Otherwise assign `previous_position = position`.

- [ ] **Step 4: Collapse redundant quiescent projection re-read**

When the graph is quiescent with `_should_complete_graph(projection)`, keep reading once after `complete` so the returned outcome sees completed state. When the graph is quiescent and active but blocked, issue `reconcile` once and return `classify_graph_outcome(run_id, projection)` without re-reading solely to compare progress. This removes the recovery re-tick behavior while preserving the source-of-truth kernel reconcile command.

- [ ] **Step 5: Verify Slice B focused tests**

Run:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py -q
```

Expected: passes.

Run:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py tests/integration/test_graph_dynamic_e2e.py tests/integration/test_graph_default_carrier.py -q
```

Expected: passes.

- [ ] **Step 6: Commit Slice B**

```bash
git add tests/unit/test_graph_driver_logic.py src/orchestrator/workflow/graph_driver.py
git commit -m "refactor: use graph positions for driver progress"
```

### Task 3: Final W8 Verification

**Files:**
- No planned source changes.

**Interfaces:**
- Consumes: commits from Task 1 and Task 2.
- Produces: final verification evidence for W8 acceptance.

- [ ] **Step 1: Run W8 acceptance**

```bash
uv run pytest tests/unit/test_graph_driver_logic.py \
  tests/integration/test_graph_dynamic_e2e.py \
  tests/integration/test_graph_default_carrier.py -q
```

Expected: passes.

- [ ] **Step 2: Run graph suite**

```bash
uv run pytest tests -k graph -q
```

Expected: passes.

- [ ] **Step 3: Run collection check**

```bash
uv run pytest tests --collect-only -q
```

Expected: passes with no `ImportError`.

- [ ] **Step 4: Check line-count outcome**

Compare `drive_to_quiescence` before and after the branch and confirm `_progress_signature` is gone:

```bash
rg "_progress_signature|previous_signature" src/orchestrator/workflow/graph_driver.py
```

Expected: no matches.

